"""Shared test fakes — the ONE place the supabase query-chain fake lives.

Before this module existed, ~40 test files each hand-rolled their own
``_FakeResult`` / ``_FakeQuery`` / ``_FakeClient`` copy of the same three
classes (and every copy supported a slightly different subset of the chain).
New tests import from here; old tests migrate opportunistically when touched.

    from tests.fakes import FakeSupabaseClient, swap_attr

    client = FakeSupabaseClient({"coach_users": [{"id": "c1"}]})
    with swap_attr(admin_mod.db, "client", client):
        ...  # code under test reads table("coach_users") rows

Deliberately NOT a PostgREST emulator: filters (.eq/.neq/...) are RECORDED
for assertions but do not filter — each test states the exact rows a table
returns, same contract as the hand-rolled fakes this replaces. If a test
needs dynamic behavior, pass a callable as the table's value and it is
invoked (with the FakeQuery) at execute() time.
"""
from __future__ import annotations

import contextlib
from typing import Any, Callable, Dict, List, Union


class FakeResult:
    """What .execute() returns: .data rows and an optional .count."""

    def __init__(self, rows: List[dict], count: Union[int, None] = None):
        self.data = rows
        self.count = count if count is not None else len(rows)


class FakeQuery:
    """Chainable stub for table(...).select(...).eq(...)....execute().

    Every filter/modifier returns self and appends to .calls, so a test can
    assert what the code under test asked for:

        q = client.tables["recordings"]        # the FakeQuery it used
        assert ("eq", ("user_id", "u1"), {}) in q.calls
    """

    _CHAIN_METHODS = (
        "select", "eq", "neq", "gt", "gte", "lt", "lte", "like", "ilike",
        "is_", "in_", "or_", "not_", "contains", "order", "limit", "range",
        "single", "maybe_single", "filter", "match",
    )

    def __init__(self, rows_or_fn: Union[List[dict], Callable[["FakeQuery"], Any]]):
        self._rows_or_fn = rows_or_fn
        self.calls: List[tuple] = []
        self.payload: Any = None  # last insert/update/upsert body

    def __getattr__(self, name: str):
        if name in self._CHAIN_METHODS:
            def _chain(*args: Any, **kwargs: Any) -> "FakeQuery":
                self.calls.append((name, args, kwargs))
                return self
            return _chain
        raise AttributeError(
            f"FakeQuery has no '{name}' — add it to _CHAIN_METHODS if the "
            f"real supabase chain grew a new method"
        )

    # Write verbs capture the payload and keep chaining.
    def insert(self, payload: Any, *args: Any, **kwargs: Any) -> "FakeQuery":
        self.calls.append(("insert", (payload,) + args, kwargs))
        self.payload = payload
        return self

    def update(self, payload: Any, *args: Any, **kwargs: Any) -> "FakeQuery":
        self.calls.append(("update", (payload,) + args, kwargs))
        self.payload = payload
        return self

    def upsert(self, payload: Any, *args: Any, **kwargs: Any) -> "FakeQuery":
        self.calls.append(("upsert", (payload,) + args, kwargs))
        self.payload = payload
        return self

    def delete(self, *args: Any, **kwargs: Any) -> "FakeQuery":
        self.calls.append(("delete", args, kwargs))
        return self

    def execute(self) -> Any:
        if callable(self._rows_or_fn):
            out = self._rows_or_fn(self)
            return out if isinstance(out, FakeResult) else FakeResult(out or [])
        return FakeResult(list(self._rows_or_fn))


class FakeSupabaseClient:
    """Drop-in for services.db's ``db.client`` in tests.

    table_rows maps table name → list of rows (returned verbatim on
    execute()) or → callable(FakeQuery) for dynamic behavior. Unknown
    tables return []. Each table() call reuses one FakeQuery per table so
    recorded .calls accumulate where tests can find them (.tables).
    """

    def __init__(self, table_rows: Union[Dict[str, Any], None] = None):
        self._table_rows = dict(table_rows or {})
        self.tables: Dict[str, FakeQuery] = {}

    def table(self, name: str) -> FakeQuery:
        if name not in self.tables:
            self.tables[name] = FakeQuery(self._table_rows.get(name, []))
        return self.tables[name]


@contextlib.contextmanager
def swap_attr(obj: Any, name: str, value: Any):
    """Set obj.name = value for the block, ALWAYS restoring the original.

    The save/patch/restore dance every setUp/tearDown pair hand-rolls,
    exception-safe. Works for module attributes too (swap_attr(auth,
    "verify_supabase_token", fake)).
    """
    orig = getattr(obj, name)
    setattr(obj, name, value)
    try:
        yield value
    finally:
        setattr(obj, name, orig)
