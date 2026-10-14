from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .errors import DomainError


_WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{index}" for index in range(1, 10)),
    *(f"lpt{index}" for index in range(1, 10)),
}
_FORBIDDEN_CHARS = set(':<>"|?*')


def _within(root: str, candidate: str) -> bool:
    try:
        return os.path.commonpath([os.path.normcase(root), os.path.normcase(candidate)]) == os.path.normcase(root)
    except ValueError:
        return False


def _reject(message: str):
    raise DomainError(400, "path_rejected", message)


class Workspace:
    def __init__(self, root: Path, run_id: str):
        self.root = Path(root).resolve()
        self.run_id = run_id
        if not self.root.is_dir():
            raise DomainError(400, "workspace_missing", "The workspace root does not exist.")
        self._real_root = os.path.realpath(self.root)

    @classmethod
    def create(cls, repo: Path, base_sha: str, run_id: str, parent: Path | None = None) -> "Workspace":
        repo = Path(repo).resolve()
        if not (repo / ".git").exists() and not (repo / ".git").is_file():
            raise DomainError(400, "repo_invalid", "The path is not a git repository.")
        head = cls._git(repo, "rev-parse", "--verify", f"{base_sha}^{{commit}}")
        parent = Path(parent) if parent else repo
        parent.mkdir(parents=True, exist_ok=True)
        target = Path(tempfile.mkdtemp(prefix=f"cshcli-{run_id}-", dir=parent))
        try:
            cls._git(repo, "worktree", "add", "--detach", str(target), head)
        except DomainError:
            shutil.rmtree(target, ignore_errors=True)
            raise
        return cls(target, run_id)

    def close(self) -> None:
        try:
            self._git(self.root, "worktree", "remove", "--force", str(self.root))
        except DomainError:
            pass
        shutil.rmtree(self.root, ignore_errors=True)

    def resolve(self, relative_path: str) -> Path:
        if not isinstance(relative_path, str) or not relative_path:
            _reject("Provide a non-empty relative path.")
        if "\x00" in relative_path:
            _reject("The path contains a null byte.")
        if "\\" in relative_path:
            _reject("Use '/' as the path separator.")
        if relative_path.startswith("/") or relative_path.startswith("~"):
            _reject("Absolute paths are not allowed inside a workspace.")
        if len(relative_path) > 1 and relative_path[1] == ":":
            _reject("Drive-qualified paths are not allowed inside a workspace.")
        candidate = Path(relative_path)
        if candidate.is_absolute() or candidate.drive or candidate.root:
            _reject("Absolute paths are not allowed inside a workspace.")
        parts = candidate.parts
        if not parts:
            _reject("Provide a non-empty relative path.")
        for part in parts:
            if part in ("..", "."):
                _reject("The path may not contain '.' or '..'.")
            if set(part) & _FORBIDDEN_CHARS:
                _reject(f"The path may not contain {''.join(sorted(_FORBIDDEN_CHARS))}.")
            if any(ord(character) < 32 for character in part):
                _reject("The path may not contain control characters.")
            if part != part.rstrip(" ."):
                _reject("A path segment may not end with a space or a dot.")
            stem = part.split(".")[0]
            if stem != stem.rstrip(" ."):
                _reject("A path segment may not end with a space or a dot before its extension.")
            if stem.lower() in _WINDOWS_RESERVED:
                _reject(f"'{part}' is a reserved device name on Windows.")
        resolved = (self.root / candidate).resolve()
        if resolved != self.root and not _within(str(self.root), str(resolved)):
            _reject("The path escapes the workspace.")
        self._assert_no_link_escape(candidate, resolved)
        return resolved

    def read(self, relative_path: str) -> bytes:
        target = self.resolve(relative_path)
        if not target.is_file():
            raise DomainError(404, "file_not_found", "The path does not exist in this workspace.")
        return target.read_bytes()

    def write(self, relative_path: str, content: bytes, *, create_parents: bool = True) -> Path:
        target = self.resolve(relative_path)
        self._assert_parent_within(target)
        if create_parents:
            target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return target

    def remove(self, relative_path: str) -> None:
        target = self.resolve(relative_path)
        self._assert_parent_within(target)
        if target.is_file() or target.is_symlink():
            target.unlink()
        elif target.is_dir():
            shutil.rmtree(target)

    def rename(self, source: str, destination: str) -> Path:
        origin = self.resolve(source)
        target = self.resolve(destination)
        self._assert_parent_within(origin)
        self._assert_parent_within(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        origin.rename(target)
        return target

    def tracked_changes(self) -> list[str]:
        porcelain = self._git(self.root, "status", "--porcelain=v1", "-z")
        changed = []
        for entry in porcelain.split("\0"):
            if not entry:
                continue
            path = entry[3:].strip('"')
            if " -> " in path:
                path = path.split(" -> ")[1]
            changed.append(path)
        return sorted(changed)

    def diff(self, base_sha: str | None = None) -> str:
        arguments = ["diff", "--no-color", "--no-ext-diff"]
        arguments.append(base_sha) if base_sha else arguments.append("HEAD")
        return self._git(self.root, *arguments)

    def _assert_no_link_escape(self, candidate: Path, resolved: Path) -> None:
        current = self.root
        for part in candidate.parts[:-1]:
            current = current / part
            if current.is_symlink():
                _reject("The path traverses a symbolic link.")
        if candidate.name and (self.root / candidate).is_symlink():
            real = Path(os.path.realpath(self.root / candidate))
            if not _within(str(self._real_root), str(real)):
                _reject("The path is a symbolic link pointing outside the workspace.")

    def _assert_parent_within(self, target: Path) -> None:
        parent = target.parent if not target.parent.exists() else target.parent.resolve()
        if parent != self.root and not _within(str(self.root), str(parent)):
            _reject("The parent directory escapes the workspace.")
        real_parent = os.path.realpath(parent)
        if real_parent != self._real_root and not _within(str(self._real_root), real_parent):
            _reject("The parent directory is a link pointing outside the workspace.")

    @staticmethod
    def _git(repo: Path, *arguments: str) -> str:
        try:
            result = subprocess.run(
                ["git", *arguments], cwd=str(repo), shell=False, check=False,
                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)
        except OSError:
            raise DomainError(502, "git_unavailable", "git is not available on this machine.") from None
        except subprocess.TimeoutExpired:
            raise DomainError(504, "git_timeout", "git did not answer in time.") from None
        if result.returncode != 0:
            message = (result.stderr or "").strip().splitlines()
            detail = message[-1] if message else "unknown error"
            raise DomainError(502, "git_failed", f"git {' '.join(arguments[:2])} failed: {detail}")
        return (result.stdout or "").rstrip()