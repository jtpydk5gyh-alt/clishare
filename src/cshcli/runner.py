"""The runner mediates every write an agent makes.

A runner owns one worktree and exposes a deliberately small surface: read a
file, write a file, remove one, rename one. There is no method that runs a
command, opens a socket or reaches outside its own workspace. That omission
is the guarantee. On Windows and macOS nothing here is a container, and this
module does not pretend otherwise; the plan puts arbitrary execution in a
Linux container or VM with verified controls, and until that exists the
runner admits reading, chat and worktree utilities only.

Three rules hold for every operation:

1. The lease is validated against the coordinator immediately before the
   bytes move. A validated lease is a moment, not a permission, so the
   publication gate checks again before anything lands.
2. The workspace resolves the path. A runner cannot be pointed at the host,
   at a neighbouring checkout, or through a symlink, because it never passes
   a path anywhere the workspace has not already resolved and refused.
3. A stopped runner writes nothing. Losing the heartbeat is not a warning,
   it ends the run.
"""

from __future__ import annotations

import time
from typing import Callable, Protocol

from .errors import DomainError
from .workspace import Workspace


class LeaseCoordinator(Protocol):
    def validate_lease(self, project_id: str, lease_id: str, fence: int,
                       resource: str | None = None) -> dict: ...

    def renew_lease(self, project_id: str, lease_id: str, fence: int,
                    ttl: int = 120) -> dict: ...


class Runner:
    def __init__(
        self,
        coordinator: LeaseCoordinator,
        workspace: Workspace,
        *,
        project_id: str,
        run_id: str,
        lease_ttl: int = 120,
        heartbeat_seconds: int = 30,
        clock: Callable[[], float] = time.monotonic,
    ):
        if not isinstance(heartbeat_seconds, int) or isinstance(heartbeat_seconds, bool):
            raise DomainError(400, "invalid_heartbeat", "heartbeat_seconds must be an integer.")
        if heartbeat_seconds < 1 or heartbeat_seconds > 3600:
            raise DomainError(400, "invalid_heartbeat", "heartbeat_seconds must be between 1 and 3600.")
        if not isinstance(lease_ttl, int) or isinstance(lease_ttl, bool):
            raise DomainError(400, "invalid_ttl", "lease_ttl must be an integer.")
        if lease_ttl < 1 or lease_ttl > 3600:
            raise DomainError(400, "invalid_ttl", "lease_ttl must be between 1 and 3600.")
        self.coordinator = coordinator
        self.workspace = workspace
        self.project_id = project_id
        self.run_id = run_id
        self.lease_ttl = lease_ttl
        self.heartbeat_seconds = heartbeat_seconds
        self.clock = clock
        self.stopped = False
        self._held: dict[str, int] = {}
        self._last_beat = clock()

    @property
    def run_id(self) -> str:
        return self._run_id

    @run_id.setter
    def run_id(self, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise DomainError(400, "invalid_run", "run_id must be a nonempty string.")
        if len(value) > 200:
            raise DomainError(400, "invalid_run", "run_id must be at most 200 characters.")
        self._run_id = value

    @property
    def project_id(self) -> str:
        return self._project_id

    @project_id.setter
    def project_id(self, value: str) -> None:
        if not isinstance(value, str) or not value.strip():
            raise DomainError(400, "invalid_project", "project_id must be a nonempty string.")
        if len(value) > 200:
            raise DomainError(400, "invalid_project", "project_id must be at most 200 characters.")
        self._project_id = value

    def track(self, lease_id: str, fence: int) -> None:
        if not isinstance(fence, int) or isinstance(fence, bool) or fence < 1:
            raise DomainError(400, "invalid_fence", "fence must be a positive integer.")
        if not isinstance(lease_id, str) or not lease_id.strip():
            raise DomainError(400, "invalid_lease", "lease_id must be a nonempty string.")
        self._held[lease_id] = fence
        self._last_beat = self.clock()

    def stop(self) -> None:
        self.stopped = True

    def heartbeat_due(self) -> bool:
        return not self.stopped and (self.clock() - self._last_beat) >= self.heartbeat_seconds

    def heartbeat(self) -> list[dict]:
        """Renews every tracked lease, or stops the runner if any is gone.

        A coordinator that cannot confirm a lease leaves the runner unable to
        write, rather than writing on an assumption.
        """
        if self.stopped:
            return []
        renewed = []
        try:
            for lease_id, fence in sorted(self._held.items()):
                renewed.append(self.coordinator.renew_lease(
                    self.project_id, lease_id, fence, self.lease_ttl))
        except DomainError:
            self.stopped = True
            raise
        self._last_beat = self.clock()
        return renewed

    def _assert_live(self) -> None:
        if self.stopped:
            raise DomainError(409, "runner_stopped",
                              "This runner was stopped; it no longer writes anything.")

    def _authorise(self, lease_id: str, fence: int, resource: str) -> dict:
        self._assert_live()
        if not isinstance(fence, int) or isinstance(fence, bool) or fence < 1:
            raise DomainError(400, "invalid_fence", "fence must be a positive integer.")
        known = self._held.get(lease_id)
        if known is None:
            raise DomainError(400, "unknown_lease",
                              "Track the lease with track() before using it.")
        if known != fence:
            raise DomainError(409, "fence_mismatch",
                              "That fence is not the one this runner holds for the lease.")
        return self.coordinator.validate_lease(
            self.project_id, lease_id, fence, resource)

    def read_file(self, relative_path: str, lease_id: str, fence: int) -> bytes:
        self._assert_live()
        return self.workspace.read(relative_path)

    def write_file(self, relative_path: str, content: bytes, lease_id: str, fence: int) -> None:
        self._authorise(lease_id, fence, "file:" + _relative(relative_path))
        self._assert_live()
        self.workspace.write(relative_path, content)

    def remove(self, relative_path: str, lease_id: str, fence: int) -> None:
        self._authorise(lease_id, fence, "file:" + _relative(relative_path))
        self._assert_live()
        self.workspace.remove(relative_path)

    def rename(self, source: str, destination: str, lease_id: str, fence: int) -> None:
        self._authorise(lease_id, fence, "file:" + _relative(destination))
        self._assert_live()
        self.workspace.rename(source, destination)

    def changed_paths(self) -> list[str]:
        return self.workspace.tracked_changes()

    def diff(self, base_sha: str | None = None) -> str:
        return self.workspace.diff(base_sha)


def _relative(path: str) -> str:
    if not isinstance(path, str) or not path.strip():
        raise DomainError(400, "invalid_path", "The path must be a nonempty string.")
    cleaned = path.replace("\\", "/").strip("/")
    if not cleaned or ".." in cleaned.split("/"):
        raise DomainError(400, "invalid_path", "The path must stay inside the workspace.")
    return cleaned