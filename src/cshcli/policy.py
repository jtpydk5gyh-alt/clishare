from __future__ import annotations

import json
import time
import uuid
from typing import Callable

from .errors import DomainError


_POSITIVE_LIMITS = ("max_agents", "max_inference_calls", "max_capture_bytes", "max_runtime_seconds")
_DEFAULT_MAX_AGENTS = 11
_DEFAULT_RUNTIME_SECONDS = 900
_UNKNOWN = "unknown"
_RESERVED = "reserved"
_SETTLED = "settled"
_ABANDONED = "abandoned"
_OPEN_STATES = (_RESERVED,)
_SETTLEABLE_STATES = (_RESERVED, _ABANDONED)


def _invalid_limits(message):
    return DomainError(400, "invalid_limits", message)


def _identifier(value, field, maximum=200):
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise DomainError(400, "invalid_input", f"{field} must be text of 1..{maximum} characters.")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise DomainError(400, "invalid_input", f"{field} must be valid text.") from None
    return value


def _encode(payload):
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _normalized_limits(limits, ceiling=_DEFAULT_MAX_AGENTS):
    if not isinstance(limits, dict):
        raise _invalid_limits("Limits must be an object.")
    normalized = {}
    for key, value in limits.items():
        if key in _POSITIVE_LIMITS:
            if type(value) is not int or value < 1:
                raise _invalid_limits(f"{key} must be a positive integer.")
        elif key == "allow_unknown_cost" and type(value) is not bool:
            raise _invalid_limits("allow_unknown_cost must be a boolean.")
        normalized[key] = value
    normalized.setdefault("max_agents", _DEFAULT_MAX_AGENTS)
    if normalized["max_agents"] > ceiling:
        raise _invalid_limits(
            f"max_agents may not exceed the project ceiling of {ceiling}."
        )
    return normalized


def _unknown_fields(measured_usage):
    return sorted(key for key, value in measured_usage.items() if value is None or value == _UNKNOWN)


def _expires_at(limits, created_at):
    return created_at + limits.get("max_runtime_seconds", _DEFAULT_RUNTIME_SECONDS)


def _reservation_view(reservation, expires_at=None):
    view = {
        "run_id": reservation["run_id"],
        "attempt_id": reservation["attempt_id"],
        "user_id": reservation["user_id"],
        "project_id": reservation["project_id"],
        "authorization_generation": reservation["authorization_generation"],
        "limits": json.loads(reservation["limits_json"]),
        "state": reservation["state"],
        "created_at": reservation["created_at"],
    }
    if expires_at is not None:
        view["expires_at"] = expires_at
    return view


class Policy:
    def __init__(self, store, clock: Callable[[], float] = time.time) -> None:
        self.store = store
        self.clock = clock

    def reserve_run(self, user_id: str, project_id: str, run_id: str,
                    authorization_generation: int, limits: dict) -> dict:
        run_id = _identifier(run_id, "run_id")
        ceiling = self.project_agent_ceiling(project_id)
        normalized = _normalized_limits(limits, ceiling)
        if type(authorization_generation) is not int:
            raise DomainError(400, "invalid_input", "authorization_generation must be an integer.")
        current = self.store.authorization_generation(user_id, project_id)
        if authorization_generation < current:
            raise DomainError(
                409, "generation_stale",
                f"Authorization generation is {current}; reserve again after re-authorizing.",
            )
        with self.store._connection(write=True) as connection:
            self.store._authorize(connection, user_id, project_id, write=True)
            existing = connection.execute(
                "SELECT run_id, attempt_id, user_id, project_id, authorization_generation, limits_json, state, created_at"
                " FROM run_reservations WHERE run_id = ? ORDER BY created_at DESC, attempt_id DESC LIMIT 1",
                (run_id,),
            ).fetchone()
            if existing:
                reservation = dict(existing)
                if reservation["state"] == _SETTLED:
                    return _reservation_view(reservation)
                if reservation["state"] == _RESERVED:
                    if (
                        reservation["authorization_generation"] != authorization_generation
                        or json.loads(reservation["limits_json"]) != normalized
                    ):
                        raise DomainError(
                            409, "reservation_mismatch",
                            "The run is already reserved with a different generation or limits.",
                        )
                    return _reservation_view(reservation)
            now = self.clock()
            self._reclaim_expired(connection, project_id, now)
            active = connection.execute(
                "SELECT COUNT(*) FROM run_reservations WHERE project_id = ? AND state = ?",
                (project_id, _RESERVED),
            ).fetchone()[0]
            if active >= normalized["max_agents"]:
                raise DomainError(
                    409, "agent_limit_reached",
                    f"The project already has {active} active runs; the limit is {normalized['max_agents']}.",
                )
            attempt_id, created_at = str(uuid.uuid4()), now
            connection.execute(
                "INSERT INTO run_reservations(run_id, attempt_id, user_id, project_id, authorization_generation,"
                " limits_json, state, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, attempt_id, user_id, project_id, authorization_generation,
                 _encode(normalized), _RESERVED, created_at),
            )
            self.store._event(connection, user_id, project_id, "policy.reserved", {
                "run_id": run_id,
                "attempt_id": attempt_id,
                "authorization_generation": authorization_generation,
                "limits": normalized,
                "expires_at": _expires_at(normalized, created_at),
            })
            reservation = {
                "run_id": run_id,
                "attempt_id": attempt_id,
                "user_id": user_id,
                "project_id": project_id,
                "authorization_generation": authorization_generation,
                "limits_json": _encode(normalized),
                "state": _RESERVED,
                "created_at": created_at,
            }
        return _reservation_view(reservation)

    def finish_run(self, user_id: str, project_id: str, run_id: str,
                     attempt_id: str, measured_usage: dict) -> dict:
        run_id = _identifier(run_id, "run_id")
        attempt_id = _identifier(attempt_id, "attempt_id")
        if not isinstance(measured_usage, dict):
            raise DomainError(400, "invalid_input", "measured_usage must be an object.")
        with self.store._connection(write=True) as connection:
            self.store._authorize(connection, user_id, project_id, write=True)
            row = connection.execute(
                "SELECT run_id, attempt_id, user_id, project_id, authorization_generation, limits_json, state"
                " FROM run_reservations WHERE run_id = ? AND attempt_id = ?", (run_id, attempt_id),
            ).fetchone()
            if row is None:
                raise DomainError(404, "reservation_not_found", "The reservation does not exist.")
            reservation = dict(row)
            if reservation["user_id"] != user_id:
                raise DomainError(
                    403, "reservation_foreign",
                    "This reservation belongs to another member; you cannot settle it.",
                )
            settled = connection.execute(
                "SELECT 1 FROM run_settlements WHERE run_id = ? AND attempt_id = ?", (run_id, attempt_id)
            ).fetchone()
            if reservation["state"] == _SETTLED or settled:
                raise DomainError(409, "already_settled", "The attempt is already settled.")
            if reservation["state"] not in _SETTLEABLE_STATES:
                raise DomainError(
                    409, "reservation_not_reserved",
                    f"The attempt is {reservation['state']}; only a reserved attempt can be settled.",
                )
            unknown_usage = _unknown_fields(measured_usage)
            if "cost" in unknown_usage and json.loads(reservation["limits_json"]).get("allow_unknown_cost") is not True:
                raise DomainError(
                    409, "cost_unknown",
                    "The cost is unknown and this policy does not allow an unknown cost.",
                )
            settled_at = self.clock()
            connection.execute(
                "INSERT INTO run_settlements(run_id, attempt_id, measured_usage_json, unknown_usage_json, settled_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (run_id, attempt_id, _encode(measured_usage), _encode(unknown_usage), settled_at),
            )
            connection.execute(
                "UPDATE run_reservations SET state = ? WHERE run_id = ? AND attempt_id = ?",
                (_SETTLED, run_id, attempt_id),
            )
            self.store._event(connection, reservation["user_id"], reservation["project_id"], "policy.settled", {
                "run_id": run_id,
                "attempt_id": attempt_id,
                "authorization_generation": reservation["authorization_generation"],
                "measured_usage": measured_usage,
                "unknown_usage": unknown_usage,
            })
        return {
            "run_id": run_id,
            "attempt_id": attempt_id,
            "authorization_generation": reservation["authorization_generation"],
            "measured_usage": dict(measured_usage),
            "unknown_usage": unknown_usage,
            "settled_at": settled_at,
        }

    def _reclaim_expired(self, connection, project_id, now):
        rows = connection.execute(
            "SELECT run_id, attempt_id, user_id, project_id, authorization_generation, limits_json, created_at"
            " FROM run_reservations WHERE project_id = ? AND state = ?",
            (project_id, _RESERVED),
        ).fetchall()
        for row in rows:
            reservation = dict(row)
            if now < _expires_at(json.loads(reservation["limits_json"]), reservation["created_at"]):
                continue
            connection.execute(
                "UPDATE run_reservations SET state = ? WHERE run_id = ? AND attempt_id = ? AND state = ?",
                (_ABANDONED, reservation["run_id"], reservation["attempt_id"], _RESERVED),
            )
            self.store._event(connection, reservation["user_id"], project_id, "policy.abandoned", {
                "run_id": reservation["run_id"],
                "attempt_id": reservation["attempt_id"],
                "authorization_generation": reservation["authorization_generation"],
                "reason": "runtime_limit_reached",
                "released_at": now,
            })

    def active_runs(self, user_id: str, project_id: str) -> dict:
        with self.store._connection(write=True) as connection:
            self.store._authorize(connection, user_id, project_id, write=False)
            now = self.clock()
            self._reclaim_expired(connection, project_id, now)
            rows = connection.execute(
                "SELECT run_id, attempt_id, user_id, project_id, authorization_generation, limits_json,"
                " state, created_at FROM run_reservations WHERE project_id = ? AND state = ?"
                " ORDER BY created_at, run_id",
                (project_id, _RESERVED),
            ).fetchall()
            views = [
                _reservation_view(dict(row), _expires_at(json.loads(row["limits_json"]), row["created_at"]))
                for row in rows
            ]
        return {"active": views, "count": len(views), "checked_at": now}

    def project_agent_ceiling(self, project_id: str) -> int:
        return _DEFAULT_MAX_AGENTS

    def policy_rules(self) -> dict:
        return {
            "default_max_agents": _DEFAULT_MAX_AGENTS,
            "default_max_runtime_seconds": _DEFAULT_RUNTIME_SECONDS,
            "unknown_usage_is_never_zero": True,
            "unknown_cost_requires_allow_unknown_cost": True,
            "memory_cannot_change_limits": True,
        }
