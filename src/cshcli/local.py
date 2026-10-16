from __future__ import annotations

import os
from pathlib import Path
from threading import Thread

from .client import Client
from .errors import DomainError
from .server import make_server


class EmbeddedCoordinator:
    def __init__(self, db_path):
        self.server = make_server(db_path, "127.0.0.1", 0)
        self.thread = Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(5)


def connect(url=None, token=None, db_path=".cshcli/coordinator.sqlite3",
            probe_url="http://127.0.0.1:8765"):
    if url:
        return Client(url, token), ()
    reachable = Client(probe_url, token)
    try:
        reachable.request("GET", "/health")
        return reachable, ()
    except DomainError:
        pass
    embedded = EmbeddedCoordinator(db_path)
    return Client(embedded.url, token), (embedded,)


def session_root():
    return Path(os.environ.get("CSHCLI_HOME", ".cshcli"))


def database_path():
    return Path(os.environ.get("CSHCLI_DB", session_root() / "coordinator.sqlite3"))