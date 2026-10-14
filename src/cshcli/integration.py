from __future__ import annotations

import subprocess
import time
from pathlib import Path
from typing import Callable

from .errors import DomainError
from .store import Store, _resource, _text


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
    value = _resource(value)
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
        repo: str | Path | None = None,
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
        if resources is not None and not isinstance(resources, list):
            raise DomainError(400, "invalid_patch", "Resources must be a list.")
        touched = [_patch_resource(item) for item in resources] if resources else list(normalized)
        missing = sorted(set(touched) - set(normalized))
        if missing:
            raise DomainError(400, "invalid_patch", f"Missing fence for: {', '.join(missing)}.")

        git_report = None
        if repo is not None:
            git_report = self.verify_with_git(repo, base_sha, commit_sha)
            outside = sorted(
                path for path in git_report["changed_paths"]
                if not any(path == item.removeprefix("file:") or
                           path.startswith(item.removeprefix("file:") + "/")
                           for item in normalized))
            if outside:
                raise DomainError(
                    409, "changes_outside_lease",
                    f"The commit touches paths that were not leased: {', '.join(outside)}.",
                )

        with self.store._connection(write=True) as connection:
            self.store._authorize(connection, user_id, project_id, write=True)
            now = self.clock()
            generation = self.store.authorization_grant(connection, user_id, project_id)
            if type(authorization_generation) is not int:
                raise DomainError(400, "invalid_generation", "authorization_generation must be an integer.")
            if authorization_generation != generation:
                raise DomainError(
                    409, "generation_stale",
                    f"Authorization generation is {generation}; the run must re-authorise before publishing.",
                )
            previous = connection.execute(
                "SELECT * FROM accepted_patches WHERE project_id = ? AND commit_sha = ?",
                (project_id, commit_sha),
            ).fetchone()
            if previous is not None:
                if previous["user_id"] != user_id:
                    raise DomainError(403, "patch_foreign", "This acceptance belongs to another member.")
                original_resources = self._load(previous["resources_json"], [])
                if previous["base_sha"] != base_sha or original_resources != sorted(normalized):
                    raise DomainError(409, "patch_mismatch", "The commit was accepted with a different base or resources.")
                return {
                    "project_id": project_id, "run_id": previous["run_id"], "base_sha": previous["base_sha"],
                    "commit_sha": commit_sha, "state": "accepted",
                    "resources": original_resources, "accepted_at": previous["accepted_at"],
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

    def verify_with_git(self, repo: Path, base_sha: str, commit_sha: str) -> dict:
        """Checks the two commits exist and reports what the head actually touches."""
        repository = Path(repo)
        if not (repository / ".git").exists():
            raise DomainError(400, "repo_missing", "The repository path has no .git directory.")
        missing = [sha for sha in (base_sha, commit_sha)
                   if not self._commit_exists(repository, sha)]
        if missing:
            raise DomainError(
                409, "commit_unknown",
                f"The repository does not contain: {', '.join(missing)}.",
            )
        if not self._is_ancestor(repository, base_sha, commit_sha):
            raise DomainError(
                409, "base_not_ancestor",
                "base_sha is not an ancestor of commit_sha; the patch does not build on the claimed base.",
            )
        changed = self._changed_paths(repository, base_sha, commit_sha)
        return {"verified": True, "changed_paths": changed}

    @staticmethod
    def _commit_exists(repository: Path, sha: str) -> bool:
        result = subprocess.run(
            ["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=str(repository),
            shell=False, check=False, capture_output=True, text=True)
        return result.returncode == 0

    @staticmethod
    def _is_ancestor(repository: Path, ancestor: str, descendant: str) -> bool:
        result = subprocess.run(
            ["git", "merge-base", "--is-ancestor", ancestor, descendant],
            cwd=str(repository), shell=False, check=False, capture_output=True, text=True)
        return result.returncode == 0

    @staticmethod
    def _changed_paths(repository: Path, base_sha: str, commit_sha: str) -> list[str]:
        result = subprocess.run(
            ["git", "diff", "--name-only", "-z", f"{base_sha}..{commit_sha}"],
            cwd=str(repository), shell=False, check=False, capture_output=True,
            text=True, encoding="utf-8", errors="replace")
        return sorted({line.strip('"') for line in result.stdout.split("\0") if line.strip('"')})

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