"""Sessions with an expiry and a revocation that a running job cannot ignore.

The local pilot issues one permanent token per user at registration. That is
fine while the coordinator is a loopback process nobody else can reach, and
unacceptable the moment it answers over a network: there is no way to end one
session without ending every session, and no way to tell a revoked agent apart
from an agent that simply never came back.

A session here is a value with a hash, an expiry and a row that can be
deleted. Authentication compares hashes and never stores the token. Revocation
bumps `authorization_generation` for the member and agent, so work that was
queued before the revocation still holds an authorisation that no longer
matches when it finally tries to act.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
import time
from typing import Callable

from .errors import DomainError


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions(
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    issued_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_by_user ON sessions(user_id);
CREATE TABLE IF NOT EXISTS revocations(
    scope TEXT PRIMARY KEY,
    generation INTEGER NOT NULL
);
"""


def hash_token(token: str, secret: bytes) -> str:
    return hmac.new(secret, token.encode("utf-8"), hashlib.sha256).hexdigest()


class Identity:
    def __init__(self, database: str = ":memory:", *, secret: bytes | None = None,
                 clock: Callable[[], float] = time.time):
        self.secret = secret or secrets.token_bytes(32)
        self.clock = clock
        self.connection = sqlite3.connect(database, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.executescript(SCHEMA)
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()

    def issue_session(self, user_id: str, ttl: int = 3600) -> dict:
        if not isinstance(user_id, str) or not user_id.strip() or len(user_id) > 200:
            raise DomainError(400, "invalid_user", "user_id must be a nonempty string.")
        if type(ttl) is not int or ttl < 1 or ttl > 30 * 24 * 3600:
            raise DomainError(400, "invalid_ttl", "ttl must be between 1 second and 30 days.")
        session_id, token = str(secrets.token_hex(16)), secrets.token_urlsafe(32)
        now = self.clock()
        self.connection.execute(
            "INSERT INTO sessions(id, user_id, token_hash, issued_at, expires_at) VALUES (?, ?, ?, ?, ?)",
            (session_id, user_id, hash_token(token, self.secret), now, now + ttl))
        self.connection.commit()
        return {"session_id": session_id, "user_id": user_id, "token": token,
                "issued_at": now, "expires_at": now + ttl}

    def authenticate(self, token: str) -> str:
        if not isinstance(token, str) or not token or len(token) > 4096:
            raise DomainError(401, "invalid_token", "Invalid or expired session.")
        now = self.clock()
        row = self.connection.execute(
            "SELECT id, user_id, expires_at FROM sessions WHERE token_hash = ?",
            (hash_token(token, self.secret),)).fetchone()
        if row is None:
            raise DomainError(401, "invalid_token", "Invalid or expired session.")
        if row["expires_at"] <= now:
            self.revoke_session(row["user_id"], row["id"])
            raise DomainError(401, "session_expired", "This session has expired.")
        return row["user_id"]

    def revoke_session(self, actor_id: str, session_id: str) -> None:
        if not isinstance(actor_id, str) or not actor_id.strip():
            raise DomainError(400, "invalid_actor", "actor_id must be a nonempty string.")
        if not isinstance(session_id, str) or not session_id.strip():
            raise DomainError(400, "invalid_session", "session_id must be a nonempty string.")
        cursor = self.connection.execute(
            "DELETE FROM sessions WHERE id = ? AND user_id = ?", (session_id, actor_id))
        self.connection.commit()
        if cursor.rowcount == 0:
            raise DomainError(404, "session_not_found",
                              "That session does not exist for this user.")

    def revoke_all_sessions(self, user_id: str) -> int:
        cursor = self.connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        self.connection.commit()
        return cursor.rowcount

    def revoke_agent(self, actor_id: str, project_id: str, user_id: str,
                     agent_id: str | None = None) -> dict:
        for value, label in ((actor_id, "actor_id"), (project_id, "project_id"),
                             (user_id, "user_id")):
            if not isinstance(value, str) or not value.strip() or len(value) > 200:
                raise DomainError(400, "invalid_field", f"{label} must be a nonempty string.")
        scope = f"{project_id}:{user_id}" + (f":{agent_id}" if agent_id else "")
        with self.connection:
            self.connection.execute(
                "INSERT INTO revocations(scope, generation) VALUES (?, 1) "
                "ON CONFLICT(scope) DO UPDATE SET generation = generation + 1", (scope,))
            row = self.connection.execute(
                "SELECT generation FROM revocations WHERE scope = ?", (scope,)).fetchone()
            if not agent_id:
                self.connection.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
        return {"scope": scope, "authorization_generation": row["generation"]}

    def authorization_generation(self, user_id: str, project_id: str,
                                 agent_id: str | None = None) -> int:
        scope = f"{project_id}:{user_id}" + (f":{agent_id}" if agent_id else "")
        row = self.connection.execute(
            "SELECT generation FROM revocations WHERE scope = ?", (scope,)).fetchone()
        return row["generation"] if row else 0

    def assert_authorized(self, user_id: str, project_id: str, generation: int,
                          agent_id: str | None = None) -> None:
        """Refuses work that was queued before a revocation.

        This is the check the plan asks for on a queued merge or a deploy
        waiting for approval: the artefacts survive, and nothing new happens.
        """
        current = self.authorization_generation(user_id, project_id, agent_id)
        if type(generation) is not int:
            raise DomainError(400, "invalid_generation", "authorization_generation must be an integer.")
        if generation != current:
            raise DomainError(
                409, "authorization_revoked",
                f"Authorization generation is {current}; this work must be re-authorised.")