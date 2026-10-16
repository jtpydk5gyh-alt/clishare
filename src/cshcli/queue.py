from __future__ import annotations

import subprocess
import time
import uuid
from pathlib import Path
from typing import Callable

from .errors import DomainError


QUEUED = "queued"
MERGED = "merged"
FAILED = "failed"
REVIEW = "review"
SUSPENDED = "suspended"


SCHEMA = """
CREATE TABLE IF NOT EXISTS integration_queue (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    task_id TEXT,
    base_sha TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued', 'merged', 'failed', 'review', 'suspended')),
    tested_sha TEXT,
    merge_sha TEXT,
    observed_base TEXT,
    detail TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE (project_id, commit_sha)
);
CREATE INDEX IF NOT EXISTS integration_queue_order
    ON integration_queue(project_id, state, created_at);
"""


class IntegrationQueue:
    def __init__(self, store, repository: Path | None = None,
                 integration_branch: str = "integration",
                 checks: Callable[[Path], bool] | None = None,
                 clock: Callable[[], float] = time.time):
        self.store = store
        self.repository = Path(repository) if repository is not None else None
        self.integration_branch = integration_branch
        self.checks = checks
        self.clock = clock
        with self.store._connection(write=True) as connection:
            connection.executescript(SCHEMA)

    def submit(self, project_id: str, commit_sha: str, base_sha: str,
               task_id: str | None = None) -> dict:
        commit_sha = _sha(commit_sha, "commit_sha")
        base_sha = _sha(base_sha, "base_sha")
        if not _exists(self._repository(), commit_sha):
            raise DomainError(404, "commit_not_found",
                              "That commit does not exist in the linked repository.")
        now = self.clock()
        identifier = str(uuid.uuid4())
        with self.store._connection(write=True) as connection:
            self._require_accepted(connection, project_id, commit_sha, base_sha)
            existing = connection.execute(
                "SELECT * FROM integration_queue WHERE project_id = ? AND commit_sha = ?",
                (project_id, commit_sha)).fetchone()
            if existing is not None:
                return self._load(connection, existing["id"])
            connection.execute(
                "INSERT INTO integration_queue(id, project_id, task_id, base_sha, commit_sha,"
                " state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (identifier, project_id, task_id, base_sha, commit_sha, QUEUED, now, now))
            self.store._event(connection, self._service_identity(project_id), project_id, "integration.submitted",
                              {"queue_id": identifier, "commit_sha": commit_sha,
                               "base_sha": base_sha})
            return self._load(connection, identifier)

    def process_next(self, project_id: str) -> dict:
        with self.store._connection() as connection:
            if not connection.execute("SELECT 1 FROM projects WHERE id = ?",
                                      (project_id,)).fetchone():
                raise DomainError(404, "project_not_found", "Project does not exist.")
            suspended = connection.execute(
                "SELECT id FROM integration_queue WHERE project_id = ? AND state = ?",
                (project_id, SUSPENDED)).fetchone()
            if suspended is not None:
                raise DomainError(409, "integration_suspended",
                                  "A member was revoked after acceptance; an owner must review.")
            pending = connection.execute(
                "SELECT id FROM integration_queue WHERE project_id = ? AND state = ?"
                " ORDER BY created_at, id LIMIT 1", (project_id, QUEUED)).fetchone()
        if pending is None:
            return {"project_id": project_id, "state": "idle", "detail": "Nothing is queued."}
        return self._process(pending["id"])

    def get(self, project_id: str, identifier: str) -> dict:
        with self.store._connection() as connection:
            row = connection.execute(
                "SELECT id FROM integration_queue WHERE id = ? AND project_id = ?",
                (identifier, project_id)).fetchone()
            if row is None:
                raise DomainError(404, "queue_not_found",
                                  "That queue entry does not exist in this project.")
            return self._load(connection, identifier)

    def list(self, project_id: str) -> list[dict]:
        with self.store._connection() as connection:
            return [self._load(connection, row["id"]) for row in connection.execute(
                "SELECT id FROM integration_queue WHERE project_id = ? ORDER BY created_at, id",
                (project_id,))]

    def _process(self, identifier: str) -> dict:
        repository = self._repository()
        if self.checks is None:
            raise DomainError(409, "checks_not_configured",
                              "Configure integration checks before processing the queue.")
        with self.store._connection() as connection:
            row = connection.execute("SELECT * FROM integration_queue WHERE id = ?",
                                     (identifier,)).fetchone()
            self._require_accepted(connection, row["project_id"], row["commit_sha"],
                                   row["base_sha"])
        project_id, commit_sha = row["project_id"], row["commit_sha"]
        observed = self._branch_sha()
        if observed is None:
            return self._settle(identifier, REVIEW,
                                detail="The integration branch does not exist yet.")
        checkout = _Checkout(repository, self.integration_branch)
        try:
            checkout.reset_to(observed)
            rebased = checkout.cherry_pick(commit_sha)
            if rebased is None:
                return self._settle(identifier, REVIEW, observed_base=observed,
                                    detail="The patch does not apply on top of the branch.")
            tested = rebased
            if self.checks is not None and not self.checks(checkout.path):
                return self._settle(identifier, FAILED, observed_base=observed,
                                    tested_sha=tested,
                                    detail="The checks failed on the composed result.")
            if self._branch_sha() != observed:
                return self._settle(identifier, REVIEW, observed_base=observed,
                                    tested_sha=tested,
                                    detail="The branch moved while the checks ran; recompute.")
            merged = checkout.push_fast_forward(observed, tested)
            if merged is None:
                return self._settle(identifier, REVIEW, observed_base=observed,
                                    tested_sha=tested,
                                    detail="The branch moved before the update; nothing changed.")
            return self._settle(identifier, MERGED, observed_base=observed,
                                tested_sha=tested, merge_sha=merged, checks_passed=True)
        finally:
            checkout.close()

    def suspend(self, project_id: str, reason: str = "The author was revoked.") -> int:
        with self.store._connection(write=True) as connection:
            cursor = connection.execute(
                "UPDATE integration_queue SET state = ?, updated_at = ?"
                " WHERE project_id = ? AND state IN (?, ?)",
                (SUSPENDED, self.clock(), project_id, QUEUED, REVIEW))
            self.store._event(connection, self._service_identity(project_id), project_id, "integration.suspended",
                              {"reason": reason})
        return cursor.rowcount

    def _service_identity(self, project_id_or_queue: str) -> str:
        with self.store._connection() as connection:
            row = connection.execute(
                "SELECT project_id FROM integration_queue WHERE id = ?",
                (project_id_or_queue,)).fetchone()
            project_id = row["project_id"] if row is not None else project_id_or_queue
            owner = connection.execute(
                "SELECT user_id FROM memberships WHERE project_id = ? AND role = 'owner'",
                (project_id,)).fetchone()
        if owner is None:
            raise DomainError(404, "project_not_found", "Project does not exist.")
        return owner["user_id"]

    def _require_accepted(self, connection, project_id: str, commit_sha: str,
                      base_sha: str) -> None:
        accepted = connection.execute(
            "SELECT base_sha FROM accepted_patches WHERE project_id = ? AND commit_sha = ?",
            (project_id, commit_sha)).fetchone()
        if accepted is None:
            raise DomainError(
                409, "patch_not_accepted",
                "Only a patch accepted by the publication gate can enter the queue.")
        if accepted["base_sha"] != base_sha:
            raise DomainError(
                409, "patch_base_mismatch",
                "The patch was accepted with a different base.")

    def _repository(self) -> Path:
        if self.repository is None:
            raise DomainError(409, "repository_not_configured",
                              "Set CSHCLI_REPOSITORY or name a repository; the integration "
                              "queue will not guess one.")
        return self.repository

    def _branch_sha(self) -> str | None:
        result = subprocess.run(["git", "rev-parse", "--verify", "--quiet",
                                 f"refs/heads/{self.integration_branch}"],
                                cwd=self._repository(), capture_output=True, text=True)
        answer = result.stdout.strip()
        return answer or None

    def _settle(self, identifier: str, state: str, observed_base: str | None = None,
                tested_sha: str | None = None, merge_sha: str | None = None,
                checks_passed: bool | None = None, detail: str = "") -> dict:
        now = self.clock()
        identity = self._service_identity(identifier)
        with self.store._connection(write=True) as connection:
            row = connection.execute("SELECT project_id FROM integration_queue WHERE id = ?",
                                     (identifier,)).fetchone()
            connection.execute(
                "UPDATE integration_queue SET state = ?, tested_sha = ?, merge_sha = ?,"
                " observed_base = ?, detail = ?, updated_at = ? WHERE id = ?",
                (state, tested_sha, merge_sha, observed_base, detail, now, identifier))
            self.store._event(connection, identity, row["project_id"], "integration.settled",
                              {"queue_id": identifier, "state": state, "tested_sha": tested_sha,
                               "merge_sha": merge_sha, "detail": detail})
            result = self._load(connection, identifier)
        if checks_passed is not None:
            result["checks_passed"] = checks_passed
        return result

    def _load(self, connection, identifier: str) -> dict:
        row = connection.execute("SELECT * FROM integration_queue WHERE id = ?",
                                     (identifier,)).fetchone()
        if row is None:
            raise DomainError(404, "queue_not_found", "That queue entry does not exist.")
        return {"id": row["id"], "project_id": row["project_id"], "task_id": row["task_id"],
                "base_sha": row["base_sha"], "commit_sha": row["commit_sha"],
                "state": row["state"], "tested_sha": row["tested_sha"],
                "merge_sha": row["merge_sha"], "observed_base": row["observed_base"],
                "detail": row["detail"] or "", "created_at": row["created_at"],
                "updated_at": row["updated_at"]}


class _Checkout:
    def __init__(self, repository: Path, branch: str):
        self.repository = Path(repository)
        self.branch = branch
        self.path = self.repository.parent / f".cshcli-integration-{uuid.uuid4().hex[:8]}"
        result = subprocess.run(
            ["git", "worktree", "add", "--detach", str(self.path), "HEAD"],
            cwd=self.repository, capture_output=True, text=True)
        if result.returncode != 0:
            raise DomainError(500, "checkout_failed",
                              f"Could not create the integration checkout: {result.stderr.strip()[:200]}")

    def reset_to(self, sha: str) -> None:
        _git(self.path, "reset", "--hard", sha)

    def cherry_pick(self, commit_sha: str) -> str | None:
        result = _git(self.path, "cherry-pick", commit_sha, check=False)
        if result.returncode != 0:
            _git(self.path, "cherry-pick", "--abort", check=False)
            return None
        return _git(self.path, "rev-parse", "HEAD").stdout.strip()

    def push_fast_forward(self, expected: str, tested: str) -> str | None:
        result = _git(self.path, "update-ref", f"refs/heads/{self.branch}",
                      tested, expected, check=False)
        if result.returncode != 0:
            return None
        return tested

    def close(self) -> None:
        subprocess.run(["git", "worktree", "remove", "--force", str(self.path)],
                       cwd=self.repository, capture_output=True, text=True)


def _git(repository: Path, *arguments: str, check: bool = True):
    return subprocess.run(["git", *arguments], cwd=repository, capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          check=check)


def _exists(repository: Path, sha: str) -> bool:
    return subprocess.run(["git", "cat-file", "-e", f"{sha}^{{commit}}"], cwd=repository,
                          capture_output=True).returncode == 0


def _sha(value: str, field: str) -> str:
    if not isinstance(value, str) or len(value) != 40:
        raise DomainError(400, "invalid_sha", f"{field} must be a 40 character SHA.")
    if any(character not in "0123456789abcdef" for character in value):
        raise DomainError(400, "invalid_sha", f"{field} must be a lowercase hexadecimal SHA.")
    return value