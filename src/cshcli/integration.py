from __future__ import annotations

import time
from typing import Callable

from .errors import DomainError
from .store import Store, _text, _valid_unicode


_SHA_LENGTH = 40
_STATES = ("accepted", "superseded")
_RESERVED_FOR_ACCEPT = ("pending",)
_RESERVED_FOR_REJECT = ("rejected",)


def _git_sha(value, field):
    if not isinstance(value, str):
        raise DomainError(400, "invalid_patch", f"{field} must be text.")
    value = value.strip()
    if len(value) != _SHA_LENGTH or any(character not in "0123456789abcdef" for character in value):
        raise DomainError(
            400, "invalid_patch",
            f"{field} must be a full 40 character lowercase git SHA; got {value!r}.",
        )
    return value


def _patch_resource(value):
    value = _text(value, "resource", 1024)
    if not value.startswith("file:"):
        raise DomainError(400, "invalid_patch", "Only file resources can be accepted as a patch.")
    return value


class IntegrationGate:
    def __init__(self, store: Store, clock: Callable[[], float] = time.time):
        self.store = store
        self.clock = clock

    def accept_patch(
        self,
        user_id: str,
        project_id: str,
        run_id: str,
        authorization_generation: int,
        lease_fences: dict[str, int],
        base_sha: str,
        commit_sha: str,
        resources: list[str] | None = None,
    ) -> dict:
        if not isinstance(lease_fences, dict) or not lease_fences:
            raise DomainError(400, "invalid_patch", "Provide the fence of every lease you touched.")
        base_sha = _git_sha(base_sha, "base_sha")
        commit_sha = _git_sha(commit_sha, "commit_sha")
        if base_sha == commit_sha:
            raise DomainError(400, "invalid_patch", "base_sha and commit_sha must differ.")
        run_id = _text(run_id, "run_id", 200)
        normalized = {}
        for resource, fence in lease_fences.items():
            normalized[_patch_resource(resource)] = self._fence(fence)
        touched = [_patch_resource(item) for item in resources] if resources else list(normalized)
        missing = sorted(set(touched) - set(normalized))
        if missing:
            raise DomainError(400, "invalid_patch", f"Missing fence for: {', '.join(missing)}.")

        now = self.clock()
        with self.store._connection(write=True) as connection:
            self.store._authorize(connection, user_id, project_id, write=True)
            generation = self.store.authorization_generation(user_id, project_id)
            if type(authorization_generation) is not int:
                raise DomainError(400, "invalid_generation", "authorization_generation must be an integer.")
            if authorization_generation < generation:
                raise DomainError(
                    409, "generation_stale",
                    f"Authorization generation is {generation}; the run must re-authorise before publishing.",
                )
            previous = connection.execute(
                "SELECT commit_sha FROM accepted_patches WHERE project_id = ? AND commit_sha = ?",
                (project_id, commit_sha),
            ).fetchone()
            if previous is not None:
                return {
                    "project_id": project_id, "run_id": run_id, "base_sha": base_sha,
                    "commit_sha": commit_sha, "state": "accepted",
                    "resources": sorted(normalized), "accepted_at": now,
                    "idempotent_replay": True,
                }
            open_attempt = connection.execute(
                "SELECT commit_sha, base_sha, state FROM patch_attempts WHERE project_id = ? AND run_id = ?",
                (project_id, run_id),
            ).fetchone()
            if open_attempt is not None:
                raise DomainError(
                    409, "run_already_published",
                    "This run already submitted a patch; use a new run to publish again.",
                )
            for resource, fence in sorted(normalized.items()):
                self._require_live_lease(connection, user_id, project_id, resource, fence, now)
            connection.execute(
                "INSERT INTO patch_attempts(project_id, run_id, user_id, base_sha, commit_sha, resources_json,"
                " fences_json, state, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (project_id, run_id, user_id, base_sha, commit_sha,
                 self._json(sorted(normalized)), self._json(normalized), "pending", now),
            )
            connection.execute(
                "INSERT INTO accepted_patches(project_id, commit_sha, base_sha, run_id, user_id,"
                " resources_json, accepted_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project_id, commit_sha, base_sha, run_id, user_id, self._json(sorted(normalized)), now),
            )
            connection.execute(
                "UPDATE patch_attempts SET state = 'accepted' WHERE project_id = ? AND run_id = ?",
                (project_id, run_id),
            )
            self.store._event(connection, user_id, project_id, "patch.accepted", {
                "run_id": run_id, "base_sha": base_sha, "commit_sha": commit_sha,
                "resources": sorted(normalized), "authorization_generation": authorization_generation,
            })
        return {
            "project_id": project_id, "run_id": run_id, "base_sha": base_sha,
            "commit_sha": commit_sha, "state": "accepted",
            "resources": sorted(normalized), "accepted_at": now,
            "idempotent_replay": False,
        }

    def list_accepted(self, user_id: str, project_id: str, limit: int = 10) -> dict:
        if type(limit) is not int or limit < 1 or limit > 100:
            raise DomainError(400, "invalid_limit", "limit must be an integer between 1 and 100.")
        with self.store._connection() as connection:
            self.store._authorize(connection, user_id, project_id, write=False)
            rows = connection.execute(
                "SELECT commit_sha, base_sha, run_id, resources_json, accepted_at FROM accepted_patches"
                " WHERE project_id = ? ORDER BY accepted_at DESC, commit_sha DESC LIMIT ?",
                (project_id, limit),
            ).fetchall()
            items = [
                {
                    "commit_sha": row["commit_sha"], "base_sha": row["base_sha"],
                    "run_id": row["run_id"], "resources": self._load(row["resources_json"], []),
                    "accepted_at": row["accepted_at"],
                }
                for row in rows
            ]
        return {"items": items, "count": len(items)}

    def _require_live_lease(self, connection, user_id, project_id, resource, fence, now):
        lease = connection.execute(
            "SELECT id, resource, fence, user_id, agent_id, expires_at FROM leases"
            " WHERE project_id = ? AND resource = ? ORDER BY fence DESC LIMIT 1",
            (project_id, resource),
        ).fetchone()
        if lease is None:
            raise DomainError(409, "lease_missing", f"No lease covers {resource}.")
        if lease["user_id"] != user_id:
            raise DomainError(
                403, "lease_foreign",
                f"{resource} is leased by another member; you cannot publish it.",
            )
        if lease["fence"] != fence:
            raise DomainError(
                409, "fence_mismatch",
                f"{resource} is at fence {lease['fence']}; your fence {fence} is stale.",
            )
        if lease["expires_at"] <= now:
            raise DomainError(
                409, "lease_expired",
                f"The lease on {resource} expired; re-acquire it and revalidate before publishing.",
            )
        return lease

    @staticmethod
    def _fence(value):
        if type(value) is not int or value < 1 or value > 2**63 - 1:
            raise DomainError(400, "invalid_patch", "Every fence must be a positive integer.")
        return value

    @staticmethod
    def _json(payload):
        import json
        return json.dumps(payload, separators=(",", ":"), sort_keys=True)

    @staticmethod
    def _load(raw, fallback):
        import json
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return fallback