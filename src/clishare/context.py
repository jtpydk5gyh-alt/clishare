import time
from typing import Callable

from .errors import DomainError


_PRIORITY_PREFIXES = ("rules/", "contracts/")
_SUMMARY_MAX_BYTES = 200
_SUMMARY_SUFFIX = "\u2026"


def _byte_size(value: str) -> int:
    return len(value.encode("utf-8"))


class ContextAssembler:
    def __init__(self, store, clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self.clock = clock

    def build(
        self,
        user_id: str,
        project_id: str,
        task_id: str,
        base_sha: str,
        context_budget_bytes: int,
        after_revision: int | None = None,
    ) -> dict:
        manifest = {
            "task_id": task_id,
            "base_sha": base_sha,
            "user_id": user_id,
            "project_id": project_id,
            "entries": [],
            "omitted": [],
            "budget_bytes": context_budget_bytes,
            "used_bytes": 0,
            "generated_at": self.clock(),
            "after_revision": after_revision,
        }
        if context_budget_bytes <= 0:
            return manifest
        try:
            page = self.store.list_memory_page(user_id, project_id, limit=10)
        except DomainError as error:
            if error.status == 403:
                raise DomainError(403, "not_a_member", "User is not a member of the project.")
            raise
        items = sorted(page["items"], key=lambda entry: entry["key"])
        prepared = []
        for entry in items:
            if entry.get("status") == "superseded":
                continue
            prepared.append({
                "key": entry["key"],
                "version": entry.get("version"),
                "author_id": entry.get("author_id"),
                "updated_at": entry.get("updated_at"),
                "scope": entry.get("scope") or "project",
                "status": entry.get("status") or "proposed",
                "content": entry.get("content", ""),
                "omitted": False,
            })
        total_bytes = sum(_byte_size(entry["content"]) for entry in prepared)
        if total_bytes <= context_budget_bytes:
            manifest["entries"] = prepared
            manifest["used_bytes"] = total_bytes
            return manifest
        entries: list[dict] = []
        omitted: list[str] = []
        used_bytes = 0
        for entry in prepared:
            key = entry["key"]
            content = entry["content"]
            if key.startswith(_PRIORITY_PREFIXES):
                entries.append(entry)
                used_bytes += _byte_size(content)
                continue
            summary = _summarize(content)
            truncated = dict(entry)
            truncated["content"] = summary
            truncated["omitted"] = True
            entries.append(truncated)
            omitted.append(key)
            used_bytes += _byte_size(summary)
        manifest["entries"] = entries
        manifest["omitted"] = omitted
        manifest["used_bytes"] = used_bytes
        return manifest


def _summarize(content: str) -> str:
    encoded = content.encode("utf-8")
    if len(encoded) <= _SUMMARY_MAX_BYTES:
        return content + _SUMMARY_SUFFIX
    head = encoded[:_SUMMARY_MAX_BYTES].decode("utf-8", errors="ignore")
    return head + _SUMMARY_SUFFIX