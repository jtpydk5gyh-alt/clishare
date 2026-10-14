from __future__ import annotations

import time
from typing import Callable

from .errors import DomainError
from .integration import _git_sha
from .store import _text as validate_text

_PROTECTED_PREFIXES = ("rules/", "contracts/")
_PAGE_LIMIT = 10
_TRUNCATE_BYTES = 200
_SUPERSEDED = "superseded"
_NOT_A_MEMBER = "El usuario no pertenece al proyecto."


def _text(row: dict, field: str) -> str:
    value = row.get(field)
    return value if isinstance(value, str) else ""


def _entry(row: dict, content: str, omitted: bool) -> dict:
    return {
        "key": row["key"],
        "version": row.get("version"),
        "author_id": row.get("author_id"),
        "updated_at": row.get("updated_at"),
        "scope": row.get("scope") or "project",
        "status": row.get("status") or "proposed",
        "content": content,
        "omitted": omitted,
    }


def _truncate(content: str) -> str:
    return content.encode("utf-8")[:_TRUNCATE_BYTES].decode("utf-8", errors="ignore") + "…"


class ContextAssembler:
    def __init__(self, store, clock: Callable[[], float] = time.time):
        self._store = store
        self._clock = clock

    def _read(self, user_id: str, project_id: str) -> list:
        rows, cursor = [], None
        while True:
            try:
                page = self._store.list_memory_page(user_id, project_id, limit=_PAGE_LIMIT, after=cursor)
            except DomainError as error:
                if error.status == 403:
                    raise DomainError(403, "not_a_member", _NOT_A_MEMBER) from error
                raise
            rows.extend(page.get("items") or [])
            cursor = page.get("next_cursor")
            if cursor is None:
                return rows

    def _select(self, rows: list, budget: int) -> tuple:
        entries, omitted, used = [], [], 0
        for reserved in (True, False):
            for row in rows:
                if (row["key"].startswith(_PROTECTED_PREFIXES)) is not reserved:
                    continue
                content = _text(row, "content")
                size = len(content.encode("utf-8"))
                if reserved and used + size > budget:
                    raise DomainError(409, "context_budget_exceeded", "Critical rules and contracts exceed the context budget.")
                if used + size <= budget:
                    entries.append(_entry(row, content, False))
                    used += size
                else:
                    omitted.append(_entry(row, _truncate(content), True))
        entries.sort(key=lambda row: row["key"])
        return entries, omitted, used

    def build(
        self,
        user_id: str,
        project_id: str,
        task_id: str,
        base_sha: str,
        context_budget_bytes: int,
        after_revision: int | None = None,
    ) -> dict:
        task_id = validate_text(task_id, "task_id", 200)
        base_sha = _git_sha(base_sha, "base_sha")
        if type(context_budget_bytes) is not int or context_budget_bytes < 0:
            raise DomainError(400, "invalid_input", "context_budget_bytes must be a nonnegative integer.")
        if after_revision is not None and (type(after_revision) is not int or after_revision < 0):
            raise DomainError(400, "invalid_input", "after_revision must be a nonnegative integer.")
        rows = sorted(
            (row for row in self._read(user_id, project_id) if row.get("status") != _SUPERSEDED),
            key=lambda row: row["key"],
        )
        if context_budget_bytes <= 0:
            entries, omitted, used = [], [], 0
        else:
            entries, omitted, used = self._select(rows, context_budget_bytes)
        return {
            "task_id": task_id,
            "base_sha": base_sha,
            "user_id": user_id,
            "project_id": project_id,
            "entries": entries,
            "omitted": omitted,
            "budget_bytes": context_budget_bytes,
            "used_bytes": used,
            "generated_at": self._clock(),
            "after_revision": after_revision,
        }