"""A PostgreSQL store for the remote service, and an honest report of itself.

The plan puts acquisition behind a row lock on the project, because two
resources that would land in different rows still conflict through their
prefix relationship. `SELECT id FROM projects WHERE id = %s FOR UPDATE`
serialises every acquisition in that project, and fences come from a
persistent sequence rather than from a per-row counter that could be reset by
a restore.

What this module refuses to do is claim more than it has proved. There is no
PostgreSQL on the machine that developed it, so nothing here has been run
against a real server. `verification()` says so, `RemoteStore.connect` refuses
to pretend otherwise, and the concurrency test that the plan forbids mocking
is present and skipped with its reason, rather than quietly deleted or
replaced by a mock that proves nothing.

The dependency is an extra. The local pilot never imports it.
"""

from __future__ import annotations

import time
from typing import Callable

from ..errors import DomainError


UNVERIFIED = "unverified"
VERIFIED = "verified"


def driver_available() -> bool:
    try:
        import psycopg  # noqa: F401
    except ImportError:
        return False
    return True


def verification(dsn: str | None = None) -> dict:
    """Reports what has actually been exercised, and nothing more."""
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
        """Opens a connection, refusing while the driver is absent."""
        require_driver()
        import psycopg
        self._connection = psycopg.connect(self.dsn)
        return self._connection

    def assert_production_ready(self) -> None:
        """Refuses to serve traffic on a build whose guarantees are unproven.

        The plan's acceptance for the distributed version is that it does not
        advertise guarantees that have not passed their tests. This is where
        that rule is enforced rather than merely written down.
        """
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