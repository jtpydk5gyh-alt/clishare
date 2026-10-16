from __future__ import annotations

import json
import ssl
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import __version__
from .remote.database import RemoteStore, driver_available

MAX_BODY = 1024 * 1024


class RemoteCoordinator(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = True
    allow_reuse_address = True
    request_queue_size = 64

    def __init__(self, address, store):
        self.store = store
        self.started_at = time.time()
        self.tls = True
        super().__init__(address, RemoteHandler)

    def server_close(self) -> None:
        try:
            super().server_close()
        finally:
            self.store.close()

    def health(self) -> dict:
        try:
            self.store.connect().execute("SELECT 1")
            database = "postgresql"
        except Exception:
            database = "unavailable"
        return {
            "status": "ok" if database == "postgresql" else "degraded",
            "mode": "remote",
            "database": database,
            "tls": self.tls,
            "driver": "psycopg",
            "version": __version__,
            "protocol": "v1",
            "uptime_seconds": round(time.time() - self.started_at, 3),
        }


class RemoteHandler(BaseHTTPRequestHandler):
    server_version = f"CSHCLI/{__version__}"
    sys_version = ""

    def do_GET(self) -> None:
        if self.path.split("?")[0] not in ("/healthz", "/health"):
            self._send(404, {"error": "not_found",
                             "detail": "El servicio remoto expone /healthz."})
            return
        self._send(200, self.server.health())

    def do_POST(self) -> None:
        self._send(405, {"error": "method_not_allowed",
                         "detail": "El servicio remoto no acepta escrituras todavia."})

    def log_message(self, *arguments) -> None:
        return

    def _send(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-CSHCLI-TLS", "on")
        self.end_headers()
        self.wfile.write(body)


def make_remote_server(dsn: str, certificate: str | None, key: str | None,
                       host: str = "127.0.0.1", port: int = 0) -> RemoteCoordinator:
    if not dsn:
        raise ValueError("El servicio remoto necesita un DSN de PostgreSQL.")
    if not certificate or not key:
        raise ValueError("El servicio remoto necesita un certificado y su clave.")
    if not Path(certificate).is_file():
        raise ValueError(f"El certificado no existe: {certificate}")
    if not Path(key).is_file():
        raise ValueError(f"La clave no existe: {key}")
    if not driver_available():
        raise ValueError("Falta el driver: pip install 'cshcli[remote]'")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(certfile=certificate, keyfile=key)
    coordinator = RemoteCoordinator((host, port), RemoteStore(dsn))
    coordinator.socket = context.wrap_socket(coordinator.socket, server_side=True)
    return coordinator