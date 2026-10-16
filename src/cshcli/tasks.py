from __future__ import annotations

import json
import time
import uuid
from typing import Callable, Iterable

from .errors import DomainError


QUEUED = "queued"
RUNNING = "running"
BLOCKED = "blocked"
REVIEW = "review"
MERGED = "merged"
FAILED = "failed"
CANCELLED = "cancelled"

STATES = (QUEUED, RUNNING, BLOCKED, REVIEW, MERGED, FAILED, CANCELLED)
TERMINAL = (MERGED, FAILED, CANCELLED)
DEPENDENCY_STATES = (QUEUED, RUNNING, BLOCKED, REVIEW, FAILED, CANCELLED)


class TaskService:
    def __init__(self, store, clock: Callable[[], float] = time.time):
        self.store = store
        self.clock = clock

    def create(self, user_id: str, project_id: str, title: str,
               dependencies: Iterable[str] | None = None,
               resources: Iterable[str] | None = None,
               agent_id: str | None = None) -> dict:
        title = _text(title, "title", 200)
        with self.store._connection(write=True) as connection:
            self.store._authorize(connection, user_id, project_id)
            wanted = _unique(dependencies, "dependency")
            held = _unique(resources, "resource")
            for dependency in wanted:
                if not self._same_project(connection, project_id, dependency):
                    raise DomainError(404, "task_not_found",
                                      "Every dependency must be a task of the same project.")
            state = BLOCKED if wanted else QUEUED
            now = self.clock()
            task_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO tasks(id, project_id, author_id, assignee_id, title, state,"
                " base_sha, commit_sha, resources_json, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?, NULL, NULL, ?, ?, ?)",
                (task_id, project_id, user_id, agent_id, title, state,
                 json.dumps(held), now, now))
            for dependency in wanted:
                connection.execute(
                    "INSERT INTO task_dependencies(task_id, depends_on) VALUES (?, ?)",
                    (task_id, dependency))
            self._assert_acyclic(connection, project_id)
            self.store._event(connection, user_id, project_id, "task.created",
                              {"task_id": task_id, "state": state,
                               "dependencies": wanted, "resources": held})
            return self._load(connection, task_id)

    def claim(self, user_id: str, project_id: str, task_id: str,
              agent_id: str, ttl: int = 120) -> dict:
        agent_id = _text(agent_id, "agent_id", 120)
        with self.store._connection(write=True) as connection:
            self.store._authorize(connection, user_id, project_id)
            task = self._row(connection, project_id, task_id)
            now = self.clock()
            pending = self._unmerged_dependencies(connection, project_id, task_id)
            if task["state"] != QUEUED and not (task["state"] == BLOCKED and pending):
                raise DomainError(409, "task_not_claimable",
                                  f"This task is {task['state']}; only a queued task can be claimed.")
            if task["assignee_id"] is not None:
                raise DomainError(409, "task_already_claimed",
                                  "Another agent already claimed this task.")
            if pending:
                raise DomainError(
                    409, "dependencies_pending",
                    f"Waiting on: {', '.join(sorted(pending))}.")
            resources = json.loads(task["resources_json"])
            acquired = []
            try:
                acquired = self.store._acquire(connection, user_id, project_id,
                                               agent_id, resources, ttl, now)
                connection.execute(
                    "UPDATE tasks SET state = ?, assignee_id = ?, updated_at = ? WHERE id = ?",
                    (RUNNING, agent_id, now, task_id))
                self.store._event(connection, user_id, project_id, "task.claimed",
                                  {"task_id": task_id, "agent_id": agent_id,
                                   "leases": [{"id": item["id"], "resource": item["resource"],
                                               "fence": item["fence"]} for item in acquired]})
            except DomainError:
                for lease in acquired:
                    connection.execute("UPDATE leases SET expires_at = ? WHERE id = ?",
                                       (now - 1, lease["id"]))
                raise
            return self._load(connection, task_id)

    def complete(self, user_id: str, project_id: str, task_id: str,
                 commit_sha: str, base_sha: str | None = None) -> dict:
        with self.store._connection(write=True) as connection:
            self.store._authorize(connection, user_id, project_id, write=True)
            task = self._row(connection, project_id, task_id)
            if task["state"] != RUNNING:
                raise DomainError(409, "task_not_running",
                                  f"This task is {task['state']}; only a running task completes.")
            commit_sha = _sha(commit_sha, "commit_sha")
            base_sha = _sha(base_sha, "base_sha") if base_sha is not None else task["base_sha"]
            now = self.clock()
            connection.execute(
                "UPDATE tasks SET state = ?, commit_sha = ?, base_sha = ?, updated_at = ?"
                " WHERE id = ?", (REVIEW, commit_sha, base_sha, now, task_id))
            self._unblock(connection, user_id, project_id, task_id, now)
            self.store._event(connection, user_id, project_id, "task.completed",
                              {"task_id": task_id, "commit_sha": commit_sha,
                               "base_sha": base_sha})
            return self._load(connection, task_id)

    def cancel(self, user_id: str, project_id: str, task_id: str) -> dict:
        with self.store._connection(write=True) as connection:
            self.store._authorize(connection, user_id, project_id, write=True)
            task = self._row(connection, project_id, task_id)
            if task["state"] in TERMINAL:
                raise DomainError(409, "task_final", "A finished task cannot be cancelled.")
            now = self.clock()
            connection.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?",
                               (CANCELLED, now, task_id))
            self._unblock(connection, user_id, project_id, task_id, now)
            self.store._event(connection, user_id, project_id, "task.cancelled",
                              {"task_id": task_id})
            return self._load(connection, task_id)

    def mark(self, user_id: str, project_id: str, task_id: str, state: str) -> dict:
        if state not in STATES:
            raise DomainError(400, "invalid_state", "Unknown task state.")
        with self.store._connection(write=True) as connection:
            self.store._authorize(connection, user_id, project_id, write=True)
            task = self._row(connection, project_id, task_id)
            if task["state"] in TERMINAL and state != task["state"]:
                raise DomainError(409, "task_final",
                                  "A finished task keeps its outcome.")
            now = self.clock()
            connection.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?",
                               (state, now, task_id))
            self._unblock(connection, user_id, project_id, task_id, now)
            self.store._event(connection, user_id, project_id, "task.state",
                              {"task_id": task_id, "state": state})
            return self._load(connection, task_id)

    def get(self, user_id: str, project_id: str, task_id: str) -> dict:
        with self.store._connection() as connection:
            self.store._authorize(connection, user_id, project_id)
            return self._load(connection, task_id)

    def list(self, user_id: str, project_id: str) -> list[dict]:
        with self.store._connection() as connection:
            self.store._authorize(connection, user_id, project_id)
            return [self._load(connection, row["id"]) for row in connection.execute(
                "SELECT id FROM tasks WHERE project_id = ? ORDER BY created_at, id",
                (project_id,))]

    def _row(self, connection, project_id, task_id):
        if not isinstance(task_id, str) or not task_id.strip():
            raise DomainError(400, "invalid_task", "task_id must be a nonempty string.")
        row = connection.execute(
            "SELECT * FROM tasks WHERE id = ? AND project_id = ?", (task_id, project_id)).fetchone()
        if row is None:
            raise DomainError(404, "task_not_found", "That task does not exist in this project.")
        return row

    def _same_project(self, connection, project_id, task_id) -> bool:
        return connection.execute(
            "SELECT 1 FROM tasks WHERE id = ? AND project_id = ?",
            (task_id, project_id)).fetchone() is not None

    def _unmerged_dependencies(self, connection, project_id, task_id) -> list[str]:
        rows = connection.execute(
            "SELECT d.depends_on AS id, t.state AS state FROM task_dependencies d"
            " JOIN tasks t ON t.id = d.depends_on WHERE d.task_id = ?",
            (task_id,)).fetchall()
        return [row["id"] for row in rows if row["state"] != MERGED]

    def _unblock(self, connection, user_id, project_id, task_id, now) -> None:
        rows = connection.execute(
            "SELECT task_id FROM task_dependencies WHERE depends_on = ?", (task_id,)).fetchall()
        for row in rows:
            dependent = row["task_id"]
            state = connection.execute("SELECT state FROM tasks WHERE id = ?",
                                       (dependent,)).fetchone()["state"]
            if state != BLOCKED:
                continue
            if not self._unmerged_dependencies(connection, project_id, dependent):
                connection.execute("UPDATE tasks SET state = ?, updated_at = ? WHERE id = ?",
                                   (QUEUED, now, dependent))
                self.store._event(connection, user_id, project_id, "task.unblocked",
                                  {"task_id": dependent})

    def _assert_acyclic(self, connection, project_id) -> None:
        edges: dict[str, list[str]] = {}
        for row in connection.execute(
                "SELECT d.task_id AS task_id, d.depends_on AS depends_on"
                " FROM task_dependencies d JOIN tasks t ON t.id = d.task_id"
                " WHERE t.project_id = ?", (project_id,)):
            edges.setdefault(row["task_id"], []).append(row["depends_on"])
        colour: dict[str, int] = {}
        for start in sorted(edges):
            stack = [(start, iter(edges.get(start, ())))]
            colour[start] = 1
            while stack:
                node, children = stack[-1]
                advanced = False
                for child in children:
                    state = colour.get(child, 0)
                    if state == 1:
                        raise DomainError(409, "dependency_cycle",
                                          "These tasks form a cycle and cannot be ordered.")
                    if state == 0:
                        colour[child] = 1
                        stack.append((child, iter(edges.get(child, ()))))
                        advanced = True
                        break
                if not advanced:
                    colour[node] = 2
                    stack.pop()

    def _load(self, connection, task_id) -> dict:
        row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        dependencies = [item["depends_on"] for item in connection.execute(
            "SELECT depends_on FROM task_dependencies WHERE task_id = ? ORDER BY depends_on",
            (task_id,))]
        return {"id": row["id"], "project_id": row["project_id"], "author_id": row["author_id"],
                "assignee_id": row["assignee_id"], "title": row["title"], "state": row["state"],
                "base_sha": row["base_sha"], "commit_sha": row["commit_sha"],
                "resources": json.loads(row["resources_json"]),
                "dependencies": dependencies,
                "created_at": row["created_at"], "updated_at": row["updated_at"]}


def _text(value, field, limit):
    if not isinstance(value, str) or not value.strip():
        raise DomainError(400, "invalid_field", f"{field} must be a nonempty string.")
    if len(value) > limit:
        raise DomainError(400, "invalid_field", f"{field} must be at most {limit} characters.")
    return value.strip()


def _sha(value, field):
    text = _text(value, field, 64)
    if len(text) != 40 or any(character not in "0123456789abcdef" for character in text):
        raise DomainError(400, "invalid_sha", f"{field} must be a lowercase 40-character SHA.")
    return text


def _unique(values, field):
    if values is None:
        return []
    if isinstance(values, str) or not isinstance(values, (list, tuple, set)):
        raise DomainError(400, "invalid_field", f"{field} must be a list.")
    seen = []
    for value in values:
        text = _text(value, field, 200)
        if text not in seen:
            seen.append(text)
    return seen