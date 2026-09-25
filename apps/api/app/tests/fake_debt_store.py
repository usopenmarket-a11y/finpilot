"""Supabase test double for HTTP contract tests; SQL behavior is tested in PostgreSQL."""

from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from postgrest.exceptions import APIError


class FakeDebtStore:
    def __init__(self):
        self.rows = {"debts": [], "debt_payments": []}

    def table(self, name):
        return Query(self, name)


class Query:
    def __init__(self, store, table):
        self.store, self.name = store, table
        self.filters = []
        self.operation, self.payload = "select", None
        self.start, self.stop = 0, None

    def select(self, *_):
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def order(self, *_):
        return self

    def limit(self, count):
        self.stop = count
        return self

    def range(self, start, end):
        self.start, self.stop = start, end + 1
        return self

    def insert(self, payload):
        self.operation, self.payload = "insert", payload
        return self

    def update(self, payload):
        self.operation, self.payload = "update", payload
        return self

    async def execute(self):
        rows = self.store.rows[self.name]
        if self.operation == "insert":
            now = datetime.now(UTC).isoformat()
            row = {"id": str(uuid4()), "created_at": now, "notes": None, **self.payload}
            if self.name == "debts":
                row = {
                    "counterparty_phone": None,
                    "counterparty_email": None,
                    "due_date": None,
                    "updated_at": now,
                    **row,
                }
            else:
                debt = next(d for d in self.store.rows["debts"] if d["id"] == row["debt_id"])
                balance = Decimal(str(debt["outstanding_balance"])) - Decimal(str(row["amount"]))
                if balance < 0:
                    raise APIError(
                        {"code": "23514", "message": "overpayment", "details": None, "hint": None}
                    )
                debt.update(
                    outstanding_balance=str(balance),
                    status="settled" if balance == 0 else "partial",
                    updated_at=now,
                )
            rows.append(row)
            result = [row]
        else:
            result = [r for r in rows if all(r.get(k) == v for k, v in self.filters)]
            if self.operation == "update":
                for row in result:
                    row.update(self.payload)
            result = result[self.start : self.stop]
        return SimpleNamespace(data=deepcopy(result))
