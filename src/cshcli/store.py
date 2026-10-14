from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import secrets
import sqlite3
import time
import unicodedata
import uuid

from .errors import DomainError


_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    name_key TEXT NOT NULL UNIQUE,
    token_hash TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_id TEXT NOT NULL REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS memberships (
    project_id TEXT NOT NULL REFERENCES projects(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    role TEXT NOT NULL CHECK (role IN ('owner', 'member', 'viewer')),
    PRIMARY KEY (project_id, user_id)
);
CREATE TABLE IF NOT EXISTS invitations (
    token_hash TEXT PRIMARY KEY,
    project_id TEXT NOT NULL REFERENCES projects(id),
    role TEXT NOT NULL CHECK (role IN ('member', 'viewer')),
    expires_at REAL NOT NULL,
    used_by TEXT REFERENCES users(id)
);
CREATE TABLE IF NOT EXISTS memory (
    project_id TEXT NOT NULL REFERENCES projects(id),
    key TEXT NOT NULL,
    content TEXT NOT NULL,
    version INTEGER NOT NULL CHECK (version > 0),
    author_id TEXT NOT NULL REFERENCES users(id),
    updated_at REAL NOT NULL,
    kind TEXT,
    scope TEXT,
    status TEXT NOT NULL DEFAULT 'proposed',
    source_commit TEXT,
    evidence TEXT,
    expires_at REAL,
    PRIMARY KEY (project_id, key)
);
CREATE TABLE IF NOT EXISTS leases (
    fence INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    project_id TEXT NOT NULL REFERENCES projects(id),
    agent_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id),
    resource TEXT NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS leases_project_expiry ON leases(project_id, expires_at);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects(id),
    user_id TEXT NOT NULL REFERENCES users(id),
    kind TEXT NOT NULL,
    data TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS events_project_id ON events(project_id, id);
CREATE TABLE IF NOT EXISTS run_reservations (
    run_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id),
    project_id TEXT NOT NULL REFERENCES projects(id),
    authorization_generation INTEGER NOT NULL,
    limits_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('reserved', 'settled', 'abandoned')),
    created_at REAL NOT NULL,
    PRIMARY KEY (run_id, attempt_id)
);
CREATE TABLE IF NOT EXISTS patch_attempts (
    project_id TEXT NOT NULL REFERENCES projects(id),
    run_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id),
    base_sha TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    resources_json TEXT NOT NULL,
    fences_json TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('pending', 'accepted', 'rejected')),
    created_at REAL NOT NULL,
    PRIMARY KEY (project_id, run_id)
);
CREATE TABLE IF NOT EXISTS accepted_patches (
    project_id TEXT NOT NULL REFERENCES projects(id),
    commit_sha TEXT NOT NULL,
    base_sha TEXT NOT NULL,
    run_id TEXT NOT NULL,
    user_id TEXT NOT NULL REFERENCES users(id),
    resources_json TEXT NOT NULL,
    accepted_at REAL NOT NULL,
    PRIMARY KEY (project_id, commit_sha)
);
CREATE TABLE IF NOT EXISTS run_settlements (
    run_id TEXT NOT NULL,
    attempt_id TEXT NOT NULL,
    measured_usage_json TEXT NOT NULL,
    unknown_usage_json TEXT NOT NULL,
    settled_at REAL NOT NULL,
    PRIMARY KEY (run_id, attempt_id),
    FOREIGN KEY (run_id, attempt_id) REFERENCES run_reservations(run_id, attempt_id)
);
"""


_MEMORY_COLUMNS = (
    ("kind", "TEXT"),
    ("scope", "TEXT"),
    ("status", "TEXT NOT NULL DEFAULT 'proposed'"),
    ("source_commit", "TEXT"),
    ("evidence", "TEXT"),
    ("expires_at", "REAL"),
)

_MEMORY_KINDS = ("decision", "contract", "evidence", "handoff")
_MEMORY_SCOPES = ("project", "task", "resource")
_MEMORY_STATUSES = ("proposed", "verified", "superseded")
_MEMORY_SELECT = (
    "SELECT key, content, version, author_id, updated_at, kind, scope, status, source_commit, evidence, expires_at FROM memory"
)


def _migrate_memory_columns(connection):
    """Add the revision metadata columns that pilot databases do not have yet."""
    existing = {row["name"] for row in connection.execute("PRAGMA table_info(memory)")}
    for column, definition in _MEMORY_COLUMNS:
        if column not in existing:
            connection.execute(f"ALTER TABLE memory ADD COLUMN {column} {definition}")


def _migrate_reservation_states(connection):
    """Recreate run_reservations so an older pilot database accepts the abandoned state."""
    table = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'run_reservations'"
    ).fetchone()
    if table is None or "abandoned" in table["sql"]:
        return
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute("ALTER TABLE run_reservations RENAME TO run_reservations_legacy")
    connection.execute(
        "CREATE TABLE run_reservations ("
        " run_id TEXT NOT NULL,"
        " attempt_id TEXT NOT NULL,"
        " user_id TEXT NOT NULL REFERENCES users(id),"
        " project_id TEXT NOT NULL REFERENCES projects(id),"
        " authorization_generation INTEGER NOT NULL,"
        " limits_json TEXT NOT NULL,"
        " state TEXT NOT NULL CHECK (state IN ('reserved', 'settled', 'abandoned')),"
        " created_at REAL NOT NULL,"
        " PRIMARY KEY (run_id, attempt_id))"
    )
    connection.execute(
        "INSERT INTO run_reservations SELECT * FROM run_reservations_legacy"
    )
    connection.execute("DROP TABLE run_reservations_legacy")
    connection.execute("PRAGMA foreign_keys = ON")


def _invalid_memory_metadata(message):
    return DomainError(400, "invalid_memory_metadata", message)


def _memory_metadata(metadata):
    if metadata is None:
        metadata = {}
    if not isinstance(metadata, dict):
        raise _invalid_memory_metadata("Memory metadata must be an object.")
    kind = metadata.get("kind")
    if kind is not None and kind not in _MEMORY_KINDS:
        raise _invalid_memory_metadata(f"Memory kind must be one of {', '.join(_MEMORY_KINDS)}.")
    scope = metadata.get("scope")
    if scope is not None and scope not in _MEMORY_SCOPES:
        raise _invalid_memory_metadata(f"Memory scope must be one of {', '.join(_MEMORY_SCOPES)}.")
    status = metadata.get("status", "proposed")
    if status not in _MEMORY_STATUSES:
        raise _invalid_memory_metadata(f"Memory status must be one of {', '.join(_MEMORY_STATUSES)}.")
    source_commit = metadata.get("source_commit")
    if source_commit is not None and (not _valid_unicode(source_commit) or len(source_commit) > 200):
        raise _invalid_memory_metadata("Memory source_commit must be text of at most 200 characters.")
    evidence = metadata.get("evidence")
    if evidence is not None and (
        not isinstance(evidence, list) or any(not isinstance(item, str) for item in evidence)
    ):
        raise _invalid_memory_metadata("Memory evidence must be a list of strings.")
    expires_at = metadata.get("expires_at")
    if expires_at is not None:
        if isinstance(expires_at, bool) or not isinstance(expires_at, (int, float)):
            raise _invalid_memory_metadata("Memory expires_at must be a number.")
        expires_at = float(expires_at)
    return {
        "kind": kind,
        "scope": scope,
        "status": status,
        "source_commit": source_commit,
        "evidence": evidence,
        "expires_at": expires_at,
    }


def _memory_entry(row):
    """Normalize a memory row; unreadable evidence degrades to None."""
    entry = dict(row)
    raw = entry.get("evidence")
    try:
        decoded = json.loads(raw) if raw is not None else None
    except (TypeError, ValueError):
        decoded = None
    entry["evidence"] = decoded if isinstance(decoded, list) else None
    for column in ("kind", "scope", "source_commit", "expires_at"):
        entry[column] = entry.get(column)
    if entry.get("status") is None:
        entry["status"] = "proposed"
    return entry


def _hash_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _valid_unicode(value):
    return isinstance(value, str) and not any(unicodedata.category(char) == "Cs" for char in value)


def _text(value, field, maximum):
    if not _valid_unicode(value) or any(unicodedata.category(char) == "Cc" for char in value):
        raise DomainError(400, "invalid_input", f"{field} must be text without control characters.")
    value = value.strip()
    if not value or len(value) > maximum:
        raise DomainError(400, "invalid_input", f"{field} must contain 1..{maximum} characters.")
    return value


def _integer(value, field, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise DomainError(400, "invalid_input", f"{field} must be an integer in {minimum}..{maximum}.")
    return value


def _resource(value):
    if not isinstance(value, str) or not value or len(value) > 1024:
        raise DomainError(400, "invalid_resource", "A resource must be a nonempty string of at most 1024 characters.")
    if value.startswith("deploy:"):
        environment = value[7:]
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", environment):
            raise DomainError(400, "invalid_resource", "Deploy environments must use 1..64 letters, numbers, underscores or hyphens.")
        return "deploy:" + environment.casefold()
    if not value.startswith("file:"):
        raise DomainError(400, "invalid_resource", "Resources must begin with file: or deploy:.")
    path = value[5:]
    parts = path.split("/")
    reserved = re.compile(r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", re.IGNORECASE)
    if (
        not path
        or "\\" in path
        or any(char in path for char in ':<>"|?*')
        or any(unicodedata.category(char) in ("Cc", "Cs") for char in path)
        or any(
            not part or part in (".", "..") or part.endswith((" ", ".")) or reserved.match(part)
            for part in parts
        )
    ):
        raise DomainError(400, "invalid_resource", "File resources require an unambiguous relative POSIX path without traversal.")
    return "file:" + path.casefold()


def _conflicts(left, right):
    if left == right:
        return True
    if left.startswith("file:") and right.startswith("file:"):
        return left.startswith(right + "/") or right.startswith(left + "/")
    return False


class Store:
    def __init__(self, db_path: str | Path, clock=time.time):
        self.db_path = str(db_path)
        self.clock = clock
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript("BEGIN IMMEDIATE;" + _SCHEMA + "COMMIT;")
            connection.execute("BEGIN IMMEDIATE")
            try:
                _migrate_memory_columns(connection)
                _migrate_reservation_states(connection)
                connection.commit()
            except BaseException:
                connection.rollback()
                raise

    @contextmanager
    def _connection(self, write=False):
        connection = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            if write:
                connection.execute("BEGIN IMMEDIATE")
            yield connection
            if write:
                connection.commit()
        except BaseException:
            if write:
                connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _user(connection, user_id):
        if not _valid_unicode(user_id) or not connection.execute("SELECT 1 FROM users WHERE id = ?", (user_id,)).fetchone():
            raise DomainError(401, "invalid_user", "Authentication is required.")

    @classmethod
    def _authorize(cls, connection, user_id, project_id, write=False, owner=False):
        cls._user(connection, user_id)
        if not _valid_unicode(project_id) or not connection.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone():
            raise DomainError(404, "project_not_found", "Project does not exist.")
        membership = connection.execute(
            "SELECT role FROM memberships WHERE project_id = ? AND user_id = ?", (project_id, user_id)
        ).fetchone()
        if not membership or (owner and membership["role"] != "owner") or (write and membership["role"] == "viewer"):
            raise DomainError(403, "forbidden", "Your project role does not permit this operation.")
        return membership["role"]

    def _event(self, connection, user_id, project_id, kind, data):
        connection.execute(
            "INSERT INTO events(project_id, user_id, kind, data, created_at) VALUES (?, ?, ?, ?, ?)",
            (project_id, user_id, kind, json.dumps(data, separators=(",", ":"), sort_keys=True), self.clock()),
        )

    def register_user(self, name):
        name = _text(name, "name", 80)
        user_id, token = str(uuid.uuid4()), secrets.token_urlsafe(32)
        with self._connection(write=True) as connection:
            if connection.execute("SELECT 1 FROM users WHERE name_key = ?", (name.casefold(),)).fetchone():
                raise DomainError(409, "name_taken", "This user name is already registered.")
            connection.execute(
                "INSERT INTO users(id, name, name_key, token_hash) VALUES (?, ?, ?, ?)",
                (user_id, name, name.casefold(), _hash_token(token)),
            )
        return {"id": user_id, "name": name, "token": token}

    def authenticate(self, token):
        if not _valid_unicode(token) or not token or len(token) > 4096:
            raise DomainError(401, "invalid_token", "Invalid authentication token.")
        with self._connection() as connection:
            user = connection.execute("SELECT id FROM users WHERE token_hash = ?", (_hash_token(token),)).fetchone()
            if not user:
                raise DomainError(401, "invalid_token", "Invalid authentication token.")
            return user["id"]

    def create_project(self, user_id, name):
        name = _text(name, "project name", 120)
        project_id = str(uuid.uuid4())
        with self._connection(write=True) as connection:
            self._user(connection, user_id)
            connection.execute("INSERT INTO projects(id, name, owner_id) VALUES (?, ?, ?)", (project_id, name, user_id))
            connection.execute("INSERT INTO memberships(project_id, user_id, role) VALUES (?, ?, 'owner')", (project_id, user_id))
            self._event(connection, user_id, project_id, "project.created", {"name": name})
        return {"id": project_id, "name": name, "owner_id": user_id}

    def list_projects(self, user_id):
        with self._connection() as connection:
            self._user(connection, user_id)
            return [dict(row) for row in connection.execute(
                "SELECT p.id, p.name, p.owner_id, m.role FROM projects p JOIN memberships m ON m.project_id = p.id WHERE m.user_id = ? ORDER BY p.name, p.id",
                (user_id,),
            )]

    def create_invite(self, user_id, project_id, role="member", ttl=3600):
        with self._connection(write=True) as connection:
            self._authorize(connection, user_id, project_id, owner=True)
            if role not in ("member", "viewer"):
                raise DomainError(400, "invalid_role", "Invitation role must be member or viewer.")
            _integer(ttl, "ttl", 1, 604800)
            token, expires_at = secrets.token_urlsafe(32), self.clock() + ttl
            connection.execute(
                "INSERT INTO invitations(token_hash, project_id, role, expires_at) VALUES (?, ?, ?, ?)",
                (_hash_token(token), project_id, role, expires_at),
            )
            self._event(connection, user_id, project_id, "invitation.created", {"role": role, "expires_at": expires_at})
        return {"token": token, "role": role, "expires_at": expires_at}

    def accept_invite(self, user_id, token):
        with self._connection(write=True) as connection:
            self._user(connection, user_id)
            if not _valid_unicode(token) or not token or len(token) > 4096:
                raise DomainError(404, "invite_not_found", "Invitation does not exist.")
            token_hash = _hash_token(token)
            invite = connection.execute("SELECT * FROM invitations WHERE token_hash = ?", (token_hash,)).fetchone()
            if not invite:
                raise DomainError(404, "invite_not_found", "Invitation does not exist.")
            if invite["used_by"] is not None:
                raise DomainError(409, "invite_used", "Invitation has already been accepted.")
            if invite["expires_at"] <= self.clock():
                raise DomainError(409, "invite_expired", "Invitation has expired.")
            project_id, role = invite["project_id"], invite["role"]
            connection.execute(
                "INSERT INTO memberships(project_id, user_id, role) VALUES (?, ?, ?) ON CONFLICT(project_id, user_id) DO UPDATE SET role = CASE WHEN memberships.role = 'owner' THEN 'owner' ELSE excluded.role END",
                (project_id, user_id, role),
            )
            connection.execute("UPDATE invitations SET used_by = ? WHERE token_hash = ?", (user_id, token_hash))
            role = self._authorize(connection, user_id, project_id)
            self._event(connection, user_id, project_id, "invitation.accepted", {"role": role})
        return {"project_id": project_id, "role": role}

    def list_memory(self, user_id, project_id):
        with self._connection() as connection:
            self._authorize(connection, user_id, project_id)
            return [_memory_entry(row) for row in connection.execute(
                _MEMORY_SELECT + " WHERE project_id = ? ORDER BY key", (project_id,)
            )]

    def list_memory_page(self, user_id, project_id, limit=10, after=None):
        with self._connection() as connection:
            self._authorize(connection, user_id, project_id)
            _integer(limit, "limit", 1, 10)
            if after is not None:
                after = _text(after, "memory cursor", 200)
            rows = connection.execute(
                _MEMORY_SELECT + " WHERE project_id = ? AND key > ? ORDER BY key LIMIT ?",
                (project_id, after if after is not None else "", limit + 1),
            ).fetchall()
            items = [_memory_entry(row) for row in rows[:limit]]
            next_cursor = items[-1]["key"] if len(rows) > limit else None
            return {"items": items, "next_cursor": next_cursor}

    def put_memory(self, user_id, project_id, key, content, expected_version, metadata=None):
        metadata = _memory_metadata(metadata)
        with self._connection(write=True) as connection:
            self._authorize(connection, user_id, project_id, write=True)
            key = _text(key, "memory key", 200)
            if not _valid_unicode(content) or len(content.encode("utf-8")) > 262144:
                raise DomainError(400, "invalid_input", "Memory content must be text of at most 256 KiB.")
            _integer(expected_version, "expected_version", 0, 2**63 - 2)
            current = connection.execute("SELECT version FROM memory WHERE project_id = ? AND key = ?", (project_id, key)).fetchone()
            actual = current["version"] if current else 0
            if actual != expected_version:
                raise DomainError(409, "version_conflict", f"Memory version is {actual}; reload before updating.")
            version, updated_at = actual + 1, self.clock()
            evidence = metadata["evidence"]
            connection.execute(
                "INSERT INTO memory(project_id, key, content, version, author_id, updated_at, kind, scope, status, source_commit, evidence, expires_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(project_id, key) DO UPDATE SET content = excluded.content, version = excluded.version,"
                " author_id = excluded.author_id, updated_at = excluded.updated_at, kind = excluded.kind,"
                " scope = excluded.scope, status = excluded.status, source_commit = excluded.source_commit,"
                " evidence = excluded.evidence, expires_at = excluded.expires_at",
                (project_id, key, content, version, user_id, updated_at, metadata["kind"], metadata["scope"],
                 metadata["status"], metadata["source_commit"],
                 json.dumps(evidence, separators=(",", ":"), sort_keys=True) if evidence is not None else None,
                 metadata["expires_at"]),
            )
            self._event(connection, user_id, project_id, "memory.updated", {"key": key, "version": version})
        return {
            "key": key, "content": content, "version": version, "author_id": user_id, "updated_at": updated_at,
            "kind": metadata["kind"], "scope": metadata["scope"], "status": metadata["status"],
            "source_commit": metadata["source_commit"], "evidence": metadata["evidence"],
            "expires_at": metadata["expires_at"],
        }

    def acquire_leases(self, user_id, project_id, agent_id, resources, ttl=120):
        with self._connection(write=True) as connection:
            role = self._authorize(connection, user_id, project_id, write=True)
            agent_id = _text(agent_id, "agent_id", 120)
            _integer(ttl, "ttl", 1, 3600)
            if not isinstance(resources, list) or not 1 <= len(resources) <= 100:
                raise DomainError(400, "invalid_resource", "Acquire 1..100 resources as a list.")
            canonical = [_resource(value) for value in resources]
            for index, resource in enumerate(canonical):
                if resource.startswith("deploy:") and role != "owner":
                    raise DomainError(403, "forbidden", "Only the project owner can acquire deploy leases.")
                if any(_conflicts(resource, earlier) for earlier in canonical[:index]):
                    raise DomainError(400, "overlapping_resources", "A resource batch cannot contain duplicate or overlapping paths.")
            now = self.clock()
            active = connection.execute(
                "SELECT resource FROM leases WHERE project_id = ? AND expires_at > ?", (project_id, now)
            ).fetchall()
            for resource in canonical:
                if any(_conflicts(resource, lease["resource"]) for lease in active):
                    raise DomainError(409, "lease_conflict", f"Resource {resource} overlaps an active lease.")
            acquired = []
            for resource in canonical:
                lease_id = str(uuid.uuid4())
                cursor = connection.execute(
                    "INSERT INTO leases(id, project_id, agent_id, user_id, resource, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (lease_id, project_id, agent_id, user_id, resource, now + ttl),
                )
                acquired.append({"id": lease_id, "project_id": project_id, "agent_id": agent_id, "user_id": user_id,
                                 "resource": resource, "fence": cursor.lastrowid, "expires_at": now + ttl})
            self._event(connection, user_id, project_id, "leases.acquired", {"agent_id": agent_id, "leases": [
                {"id": item["id"], "resource": item["resource"], "fence": item["fence"]} for item in acquired
            ]})
        return acquired

    def list_leases(self, user_id, project_id):
        with self._connection() as connection:
            self._authorize(connection, user_id, project_id)
            return [dict(row) for row in connection.execute(
                "SELECT id, project_id, agent_id, user_id, resource, fence, expires_at FROM leases WHERE project_id = ? AND expires_at > ? ORDER BY fence",
                (project_id, self.clock()),
            )]

    def _held_lease(self, connection, user_id, project_id, lease_id, fence):
        _integer(fence, "fence", 1, 2**63 - 1)
        if not _valid_unicode(lease_id):
            raise DomainError(404, "lease_not_found", "Lease does not exist in this project.")
        lease = connection.execute("SELECT * FROM leases WHERE id = ? AND project_id = ?", (lease_id, project_id)).fetchone()
        if not lease:
            raise DomainError(404, "lease_not_found", "Lease does not exist in this project.")
        if lease["user_id"] != user_id:
            raise DomainError(403, "forbidden", "Only the lease holder can renew or release it.")
        if lease["fence"] != fence:
            raise DomainError(409, "fence_mismatch", "The fencing token does not match the lease.")
        if lease["expires_at"] <= self.clock():
            raise DomainError(409, "lease_expired", "Lease has expired; acquire a new lease before continuing.")
        return dict(lease)

    def renew_lease(self, user_id, project_id, lease_id, fence, ttl=120):
        with self._connection(write=True) as connection:
            self._authorize(connection, user_id, project_id, write=True)
            _integer(ttl, "ttl", 1, 3600)
            lease = self._held_lease(connection, user_id, project_id, lease_id, fence)
            lease["expires_at"] = self.clock() + ttl
            connection.execute("UPDATE leases SET expires_at = ? WHERE id = ?", (lease["expires_at"], lease_id))
            self._event(connection, user_id, project_id, "lease.renewed", {"id": lease_id, "fence": fence, "expires_at": lease["expires_at"]})
        return lease

    def release_lease(self, user_id, project_id, lease_id, fence):
        with self._connection(write=True) as connection:
            self._authorize(connection, user_id, project_id, write=True)
            self._held_lease(connection, user_id, project_id, lease_id, fence)
            connection.execute("DELETE FROM leases WHERE id = ?", (lease_id,))
            self._event(connection, user_id, project_id, "lease.released", {"id": lease_id, "fence": fence})
        return {"released": True}

    def list_events(self, user_id, project_id, limit=100):
        with self._connection() as connection:
            self._authorize(connection, user_id, project_id)
            _integer(limit, "limit", 1, 1000)
            events = []
            for row in connection.execute(
                "SELECT id, project_id, user_id, kind, data, created_at FROM events WHERE project_id = ? ORDER BY id DESC LIMIT ?", (project_id, limit)
            ):
                event = dict(row)
                event["data"] = json.loads(event["data"])
                events.append(event)
            return events

    def authorization_generation(self, user_id: str, project_id: str, agent_id: str | None = None) -> int:
        if agent_id is not None:
            _text(agent_id, "agent_id", 120)
        with self._connection() as connection:
            self._authorize(connection, user_id, project_id)
        return 1
