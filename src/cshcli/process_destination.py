"""A destination that lives outside this process.

`InProcessDestination` in `deploy.py` proves the coordination: idempotence,
approval binding, fencing, reconciliation and rollback. It proves none of it
against anything real, because a dictionary in the same process cannot lose an
answer, cannot refuse a connection and cannot be stopped by anything the worker
does.

This module provides the thing the plan's acceptance line actually asks for. A
destination that:

- writes the active digest to a directory, from a **separate process**, so the
  state survives the worker and can be read by another process entirely;
- answers `health` over a **real HTTP request** to localhost, through a server
  thread that is genuinely reachable and genuinely slow;
- can be made to **time out for real**, by pointing the health check at a
  socket that accepts and never replies, rather than by raising a flag;
- can be made to **fail health for real**, by stopping the server, so the
  failure is a refused connection rather than a dictionary lookup.

The child process is a plain interpreter running a tiny script. Nothing here
is a cloud provider and nothing here should be described as one. What it does
prove is that the worker's failure handling survives a destination that fails
in the ways real ones fail, which an in-memory object cannot.
"""

from __future__ import annotations

import http.client
import json
import os
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .deploy import DestinationTimeout
from .errors import DomainError


CHILD = """
import json, os, sys
path, digest, external_id, fence = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
os.makedirs(path, exist_ok=True)
record = {"digest": digest, "external_id": external_id, "fence": fence}
current = os.path.join(path, "active.json")
if os.path.exists(current):
    try:
        previous = json.load(open(current, encoding="utf-8"))
        if int(previous.get("fence", 0)) >= fence:
            sys.stderr.write("stale fence")
            sys.exit(3)
    except (ValueError, OSError):
        pass
with open(os.path.join(path, "external-" + external_id + ".json"), "w", encoding="utf-8") as handle:
    json.dump(record, handle)
temporary = current + ".tmp"
with open(temporary, "w", encoding="utf-8") as handle:
    json.dump(record, handle)
os.replace(temporary, current)
print(json.dumps(record))
"""


class BlackHole:
    """A socket that accepts the connection and never answers.

    A refused connection is a failure; a connection that hangs is a timeout.
    The worker's behaviour differs between the two, so the test needs the
    second one and cannot have it from a flag.
    """

    def __init__(self):
        self._socket = socket.socket()
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen(8)
        self._held = []
        self._running = True
        self._thread = threading.Thread(target=self._accept, daemon=True)
        self._thread.start()

    @property
    def port(self) -> int:
        return self._socket.getsockname()[1]

    def _accept(self) -> None:
        while self._running:
            try:
                connection, _ = self._socket.accept()
            except OSError:
                return
            self._held.append(connection)

    def close(self) -> None:
        self._running = False
        for connection in self._held:
            try:
                connection.close()
            except OSError:
                pass
        try:
            self._socket.close()
        except OSError:
            pass


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *arguments):
        return

    def do_GET(self):
        root = self.server.root
        active = root / "active.json"
        body = json.dumps({"serving": active.is_file(),
                           "digest": _read(active) if active.is_file() else None}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _read(path: Path) -> str | None:
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("digest")
    except (ValueError, OSError):
        return None


class ProcessDestination:
    """Writes state from a child process and answers health over HTTP."""

    def __init__(self, root: Path, interpreter: str | None = None):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.interpreter = interpreter or sys.executable
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._blackhole: BlackHole | None = None
        self._sequence = 0

    @property
    def port(self) -> int:
        if self._server is None:
            raise RuntimeError("the health server is not running")
        return self._server.server_address[1]

    def start(self) -> "ProcessDestination":
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.root = self.root
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop_server(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None
        if self._thread is not None:
            self._thread.join(5)
            self._thread = None

    def stall(self) -> None:
        self._blackhole = BlackHole()

    def unstall(self) -> None:
        if self._blackhole is not None:
            self._blackhole.close()
            self._blackhole = None

    def close(self) -> None:
        self.unstall()
        self.stop_server()

    def promote(self, change) -> dict:
        change.authorize()
        self._sequence += 1
        external_id = f"{change.environment}-{self._sequence}"
        result = subprocess.run(
            [self.interpreter, "-c", CHILD, str(self.root), change.digest,
             external_id, str(change.fence)],
            capture_output=True, text=True, encoding="utf-8", timeout=60)
        if result.returncode == 3:
            raise DomainError(409, "stale_fence",
                              f"{change.environment} already holds a newer fence than {change.fence}.")
        if result.returncode != 0:
            raise RuntimeError(f"the destination refused the change: {result.stderr.strip()[:200]}")
        return {"external_id": external_id, "digest": change.digest, "fence": change.fence}

    def describe(self, external_id: str) -> dict:
        if not external_id:
            return {"decided": False, "digest": None, "external_id": external_id}
        record = self.root / f"external-{external_id}.json"
        if not record.is_file():
            return {"decided": False, "digest": None, "external_id": external_id}
        return {"decided": True, "digest": _read(record), "external_id": external_id}

    def health(self, digest: str) -> dict:
        if self._blackhole is not None:
            raise DestinationTimeout()
        if self._server is None:
            return {"healthy": False, "detail": "No health endpoint is listening."}
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            connection.request("GET", "/health")
            response = connection.getresponse()
            payload = json.loads(response.read())
        except (OSError, ValueError, http.client.HTTPException):
            return {"healthy": False, "detail": "The health endpoint did not answer."}
        finally:
            connection.close()
        if not payload.get("serving"):
            return {"healthy": False, "detail": "The environment serves nothing."}
        if payload.get("digest") != digest:
            return {"healthy": False, "detail": "The environment serves another artefact."}
        return {"healthy": True, "detail": "The health endpoint served the expected artefact."}