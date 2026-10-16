from __future__ import annotations

import time
from typing import Callable

from ..errors import DomainError


UNVERIFIED = "unverified"
VERIFIED = "verified"


def driver_available() -> bool:
    try:
        import psycopg
    except ImportError:
        return False
    return True


def verification(dsn: str | None = None) -> dict:
    if not driver_available():
        return {"state": UNVERIFIED, "driver": "psycopg", "reason": "driver_not_installed",
                "hint": "pip install 'cshcli[remote]'"}
    if not dsn:
        return {"state": UNVERIFIED, "driver": "psycopg", "reason": "no_dsn",
                "hint": "set CSHCLI_REMOTE_DSN"}
    return {"state": UNVERIFIED, "driver": "psycopg", "reason": "concurrency_unproven",
            "hint": "run tests/test_remote_postgres.py against a real server"}


def require_driver() -> None:
    if not driver_available():
        raise DomainError(
            503, "remote_driver_missing",
            "El servicio remoto necesita el driver de PostgreSQL: pip install 'cshcli[remote]'.")


class RemoteStore:
    def __init__(self, dsn: str, clock: Callable[[], float] = time.time):
        if not isinstance(dsn, str) or not dsn.strip():
            raise DomainError(400, "invalid_dsn", "Provide a PostgreSQL DSN.")
        self.dsn = dsn.strip()
        self.clock = clock
        self._connection = None
        self.reported = verification(self.dsn)

    def connect(self):
        require_driver()
        if self._connection is not None and not self._connection.closed:
            return self._connection
        import psycopg
        self._connection = psycopg.connect(self.dsn)
        return self._connection

    def assert_production_ready(self) -> None:
        if self.reported["state"] != VERIFIED:
            raise DomainError(
                503, "remote_unverified",
                f"Remote storage is {self.reported['state']} ({self.reported['reason']}). "
                "Run the concurrency and restore drills before serving users.")

    def acquire_leases(self, user_id: str, project_id: str, agent_id: str,
                       resources: list[str], ttl: int = 120) -> list[dict]:
        connection = self._connection or self.connect()
        with connection.transaction():
            connection.execute(
                "SELECT id FROM projects WHERE id = %s FOR UPDATE", (project_id,))
            active = connection.execute(
                "SELECT resource FROM leases WHERE project_id = %s AND expires_at > %s",
                (project_id, self.clock())).fetchall()
            held = [row[0] for row in active]
            for resource in resources:
                if any(_overlaps(resource, other) for other in held):
                    raise DomainError(409, "lease_conflict",
                                      f"Resource {resource} overlaps an active lease.")
            acquired = []
            for resource in resources:
                row = connection.execute(
                    "INSERT INTO leases(id, project_id, agent_id, user_id, resource,"
                    " expires_at) VALUES (gen_random_uuid()::text, %s, %s, %s, %s, %s)"
                    " RETURNING fence", (project_id, agent_id, user_id, resource,
                                          self.clock() + ttl)).fetchone()
                acquired.append({"project_id": project_id, "agent_id": agent_id,
                                 "user_id": user_id, "resource": resource,
                                 "fence": row[0], "expires_at": self.clock() + ttl})
            connection.execute(
                "INSERT INTO events(project_id, user_id, kind, payload_json, created_at)"
                " VALUES (%s, %s, %s, %s, %s)",
                (project_id, user_id, "leases.acquired", "{}", self.clock()))
            return acquired

    def close(self) -> None:
        if self._connection is not None:
            self._connection.close()
            self._connection = None


def _overlaps(left: str, right: str) -> bool:
    if left == right:
        return True
    if left.startswith("file:") and right.startswith("file:"):
        left = left[5:]
        right = right[5:]
        return left.startswith(right + "/") or right.startswith(left + "/")
    return False