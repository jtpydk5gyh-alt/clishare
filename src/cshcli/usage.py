from __future__ import annotations

import decimal
import json
import re
import time
import uuid
from decimal import Decimal, InvalidOperation
from typing import Callable

from .errors import DomainError


CURRENCY = re.compile(r"^[A-Z]{3}$")

SCHEMA = """
CREATE TABLE IF NOT EXISTS usage_records (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    task_id TEXT,
    provider TEXT NOT NULL,
    model TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    cost TEXT,
    currency TEXT,
    price_as_of TEXT,
    unit TEXT,
    unknown_fields_json TEXT NOT NULL,
    correlation_json TEXT NOT NULL,
    recorded_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS usage_by_project ON usage_records(project_id, recorded_at);
CREATE TABLE IF NOT EXISTS budgets (
    project_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    currency TEXT NOT NULL,
    amount TEXT NOT NULL,
    max_agents INTEGER NOT NULL,
    set_at REAL NOT NULL,
    PRIMARY KEY (project_id, user_id, currency)
);
"""


def _decimal(value, field: str) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise DomainError(400, "invalid_amount", f"{field} must be a decimal amount.")
    try:
        amount = Decimal(str(value))
    except InvalidOperation:
        raise DomainError(400, "invalid_amount", f"{field} must be a decimal amount.") from None
    if not amount.is_finite():
        raise DomainError(400, "invalid_amount", f"{field} must be finite.")
    if amount < 0:
        raise DomainError(400, "invalid_amount", f"{field} cannot be negative.")
    return format(amount, "f")


def _currency(value: str) -> str:
    if not isinstance(value, str) or not CURRENCY.match(value):
        raise DomainError(400, "invalid_currency",
                          "A currency is three uppercase letters, for example EUR.")
    return value


def _token_count(value, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise DomainError(400, "invalid_count", f"{field} must be a nonnegative integer or null.")
    return value


def _load_record(row) -> dict:
    return {"id": row["id"], "project_id": row["project_id"], "user_id": row["user_id"],
            "task_id": row["task_id"], "provider": row["provider"], "model": row["model"],
            "input_tokens": row["input_tokens"], "output_tokens": row["output_tokens"],
            "cost": row["cost"], "currency": row["currency"],
            "price_as_of": row["price_as_of"], "unit": row["unit"],
            "unknown_fields": json.loads(row["unknown_fields_json"]),
            "correlation": json.loads(row["correlation_json"]),
            "recorded_at": row["recorded_at"]}


def _costed(store, project_id: str, user_id: str | None, currency: str | None) -> list[dict]:
    query = "SELECT * FROM usage_records WHERE project_id = ?"
    arguments: list = [project_id]
    if user_id is not None:
        query += " AND user_id = ?"
        arguments.append(user_id)
    with store._connection() as connection:
        rows = connection.execute(query, arguments).fetchall()
    records = [_load_record(row) for row in rows]
    if currency is None:
        return records
    return [record for record in records
            if record["currency"] == currency or record["currency"] is None]


class Usage:
    def _costed(self, project_id: str, user_id: str | None,
                currency: str | None) -> list[dict]:
        return _costed(self.store, project_id, user_id, currency)

    def __init__(self, store, clock: Callable[[], float] = time.time):
        self.store = store
        self.clock = clock
        with self.store._connection(write=True) as connection:
            connection.executescript(SCHEMA)

    def record(self, project_id: str, user_id: str, provider: str, *,
               task_id: str | None = None, model: str | None = None,
               input_tokens: int | None = None, output_tokens: int | None = None,
               cost: str | Decimal | None = None, currency: str | None = None,
               price_as_of: str | None = None, unit: str | None = None,
               request_id: str | None = None, lease_id: str | None = None,
               fence: int | None = None) -> dict:
        with self.store._connection() as connection:
            self.store._authorize(connection, user_id, project_id)
        provider = _text(provider, "provider", 120)
        input_tokens = _token_count(input_tokens, "input_tokens")
        output_tokens = _token_count(output_tokens, "output_tokens")

        if cost is not None and currency is None:
            raise DomainError(400, "cost_without_currency",
                              "A cost needs the currency it is expressed in.")
        if cost is not None and price_as_of is None:
            raise DomainError(400, "cost_without_price_date",
                              "A cost needs the date its price was read; an undated price "
                              "cannot be compared with a budget.")
        amount = _decimal(cost, "cost") if cost is not None else None
        money = _currency(currency) if currency is not None else None

        told = {"input_tokens": input_tokens, "output_tokens": output_tokens,
                "cost": amount, "currency": money, "price_as_of": price_as_of,
                "unit": unit}
        unknown = sorted(key for key, value in told.items() if value is None)

        correlation = {key: value for key, value in
                       (("request_id", request_id), ("task_id", task_id),
                        ("lease_id", lease_id), ("fence", fence)) if value is not None}
        now = self.clock()
        identifier = str(uuid.uuid4())
        with self.store._connection(write=True) as connection:
            self.store._authorize(connection, user_id, project_id)
            connection.execute(
                "INSERT INTO usage_records(id, project_id, user_id, task_id, provider, model,"
                " input_tokens, output_tokens, cost, currency, price_as_of, unit,"
                " unknown_fields_json, correlation_json, recorded_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (identifier, project_id, user_id, task_id, provider, model,
                 input_tokens, output_tokens, amount, money, price_as_of, unit,
                 json.dumps(unknown), json.dumps(correlation), now))
            self.store._event(connection, user_id, project_id, "usage.recorded", {
                "usage_id": identifier, "provider": provider, "model": model,
                "input_tokens": input_tokens, "output_tokens": output_tokens,
                "cost": amount, "currency": money, "unknown_fields": unknown,
                **correlation})
        return self.get(project_id, identifier)

    def get(self, project_id: str, identifier: str) -> dict:
        with self.store._connection() as connection:
            row = connection.execute("SELECT * FROM usage_records WHERE id = ?",
                                     (identifier,)).fetchone()
        if row is None:
            raise DomainError(404, "usage_not_found", "That usage record does not exist.")
        return self._load(row)

    def total(self, project_id: str, user_id: str | None = None,
              currency: str = "EUR") -> dict:
        money = _currency(currency)
        records = self._costed(project_id, user_id, money)
        total = Decimal("0")
        unknown_records = 0
        for record in records:
            if record["cost"] is None:
                unknown_records += 1
                continue
            total += Decimal(record["cost"])
        return {"project_id": project_id, "user_id": user_id, "currency": money,
                "known_total": format(total, "f"), "records": len(records),
                "records_with_unknown_cost": unknown_records,
                "detail": "Unknown costs are excluded from the total, not counted as zero."}

    def export(self, project_id: str, user_id: str, limit: int = 1000) -> dict:
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 10000:
            raise DomainError(400, "invalid_limit", "limit must be between 1 and 10000.")
        with self.store._connection() as connection:
            self.store._authorize(connection, user_id, project_id)
            rows = connection.execute(
                "SELECT * FROM usage_records WHERE project_id = ? ORDER BY recorded_at, id"
                " LIMIT ?", (project_id, limit)).fetchall()
        return {"project_id": project_id, "count": len(rows),
                "records": [self._load(row) for row in rows],
                "retention": "Unbounded for now; the retention period is not configured."}

    def _load(self, row) -> dict:
        return _load_record(row)


class BudgetPolicy:
    def __init__(self, store, clock: Callable[[], float] = time.time):
        self.store = store
        self.clock = clock
        with self.store._connection(write=True) as connection:
            connection.executescript(SCHEMA)

    def set_budget(self, owner_id: str, project_id: str, currency: str, amount: str,
                   max_agents: int) -> dict:
        with self.store._connection(write=True) as connection:
            self.store._authorize(connection, owner_id, project_id, write=True, owner=True)
        money = _currency(currency)
        value = _decimal(amount, "amount")
        if isinstance(max_agents, bool) or not isinstance(max_agents, int) or max_agents < 1:
            raise DomainError(400, "invalid_limit", "max_agents must be a positive integer.")
        now = self.clock()
        with self.store._connection(write=True) as connection:
            self.store._authorize(connection, owner_id, project_id, write=True, owner=True)
            connection.execute(
                "INSERT INTO budgets(project_id, user_id, currency, amount, max_agents, set_at)"
                " VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(project_id, user_id, currency) DO UPDATE SET"
                " amount = excluded.amount, max_agents = excluded.max_agents,"
                " set_at = excluded.set_at",
                (project_id, owner_id, money, value, max_agents, now))
            self.store._event(connection, owner_id, project_id, "budget.set", {
                "currency": money, "amount": value, "max_agents": max_agents})
        return {"project_id": project_id, "user_id": owner_id, "currency": money,
                "amount": value, "max_agents": max_agents, "set_at": now}

    def get(self, project_id: str, user_id: str, currency: str) -> dict:
        money = _currency(currency)
        with self.store._connection() as connection:
            row = connection.execute(
                "SELECT * FROM budgets WHERE project_id = ? AND user_id = ? AND currency = ?",
                (project_id, user_id, money)).fetchone()
        if row is None:
            raise DomainError(404, "budget_not_found", "That budget does not exist.")
        return {"project_id": project_id, "user_id": row["user_id"],
                "currency": row["currency"], "amount": row["amount"],
                "max_agents": row["max_agents"], "set_at": row["set_at"]}

    def authorize_run(self, user_id: str, project_id: str, *,
                      estimated_cost: str | None = None, currency: str = "EUR") -> dict:
        money = _currency(currency)
        with self.store._connection() as connection:
            self.store._authorize(connection, user_id, project_id)
            budget = connection.execute(
                "SELECT * FROM budgets WHERE project_id = ? AND user_id = ? AND currency = ?",
                (project_id, user_id, money)).fetchone()
            active = connection.execute(
                "SELECT COUNT(*) AS total FROM run_reservations"
                " WHERE project_id = ? AND user_id = ? AND state = 'reserved'",
                (project_id, user_id)).fetchone()["total"]
        if budget is None:
            return {"authorised": True, "reason": "no_budget", "active_agents": active,
                    "detail": "No budget is set for this member; the run is allowed.",
                    "estimated_cost": estimated_cost, "spent": None}
        if active >= budget["max_agents"]:
            raise DomainError(
                409, "agent_limit_reached",
                f"{active} run(s) are already reserved for this member and the ceiling "
                f"is {budget['max_agents']}.")
        if estimated_cost is None:
            raise DomainError(
                409, "estimate_required",
                "A budget is set, so a run needs an estimate; refusing rather than "
                "assuming the cost is zero.")
        estimate = Decimal(_decimal(estimated_cost, "estimated_cost"))
        total = Decimal("0")
        unknown = 0
        for record in _costed(self.store, project_id, user_id, money):
            if record["cost"] is None:
                unknown += 1
            else:
                total += Decimal(record["cost"])
        if unknown:
            raise DomainError(
                409, "usage_incomplete",
                f"{unknown} recorded call(s) have no known cost; the budget cannot be "
                "compared until they are priced.")
        if total + estimate > Decimal(budget["amount"]):
            raise DomainError(
                409, "budget_exceeded",
                f"The budget is {budget['amount']} {budget['currency']}, {format(total, 'f')} "
                f"is spent and {format(estimate, 'f')} was estimated.")
        return {"authorised": True, "reason": "within_budget", "budget": budget["amount"],
                "spent": format(total, "f"), "estimated_cost": format(estimate, "f"),
                "remaining": format(Decimal(budget["amount"]) - total - estimate, "f"),
                "active_agents": active, "max_agents": budget["max_agents"],
                "currency": budget["currency"]}


def _text(value: str, field: str, limit: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise DomainError(400, "invalid_field", f"{field} must be a nonempty string.")
    if len(value) > limit:
        raise DomainError(400, "invalid_field", f"{field} must be at most {limit} characters.")
    return value.strip()