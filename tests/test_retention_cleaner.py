"""
STORY    As the founder, I want old data cleaned on schedule only when I turn
         the live key on, in a safe order, so that nothing is deleted early
         or out of order.
OUTCOME
  O1  A dry run only counts what is due and deletes nothing.
  O2  A live run is refused while the live key is off.
  O3  A live run deletes in order: old guest accounts, then the
      measurements, then the recording, then its event, then old logs,
      then old financial rows.
  O4  If the code's list of tables disagrees with the database, nothing is
      deleted; the cleaner only touches tables reviewed for deletion.
  O5  The scheduled-run route does nothing without its secret.
PROVES   O1 -> test_a_dry_run_counts_records_and_deletes_nothing
         O2 -> test_a_live_request_is_refused_while_the_key_is_off
         O3 -> test_a_live_run_works_through_the_four_rules_in_order,
               test_the_measurements_go_before_the_recording
         O4 -> test_a_registry_that_disagrees_with_the_database_deletes_nothing,
               test_every_relation_the_cleaner_writes_is_classified_and_none_is_retained
         O5 -> RouteTests::test_the_route_is_dead_without_its_secret
WHY      Founder 2026-10-05, decisions log N48.4 Q16 A and N50.
"""
from __future__ import annotations

import pathlib
import re
import unittest
from typing import Any
from unittest import mock

import pytest

from services import retention_cleaner as rc
from services.data_purge_registry import (
    DEPENDENCIES,
    DYNAMIC_RUNTIME_RELATIONS,
    LINEAGE_TOMBSTONES,
    classified_relations,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]
MIGRATION_NAME = "old_data_goes_on_a_schedule.sql"
MIGRATION = (ROOT / "migrations" / MIGRATION_NAME).read_text()
CODE = "\n".join(line.split("--", 1)[0] for line in MIGRATION.splitlines())


def _function(name: str) -> str:
    """A function as 0423 wrote it."""
    match = re.search(
        rf"CREATE OR REPLACE FUNCTION public\.{name}\((.*?)\n\$\$;", CODE, re.S)
    assert match, name
    return match.group(1)


def _since_0423() -> list[str]:
    rows = (ROOT / "migrations" / "manifest.txt").read_text().splitlines()
    files = [row.split("\t")[1].strip() for row in rows if "\t" in row]
    return files[files.index(MIGRATION_NAME):]


def _latest(name: str) -> str:
    """A function as the database has it now: its last definition in
    manifest order (0426 re-issues four of 0423's)."""
    found = None
    for file in _since_0423():
        text = (ROOT / "migrations" / file).read_text()
        code = "\n".join(line.split("--", 1)[0] for line in text.splitlines())
        for match in re.finditer(
                rf"CREATE OR REPLACE FUNCTION public\.{name}\((.*?)\n\$\$;",
                code, re.S):
            found = match.group(1)
    assert found, name
    return found


def _stores() -> list[dict]:
    """retention_measurement_stores_v1, read from the migration."""
    body = _function("retention_measurement_stores_v1")
    rows = re.findall(
        r"\('([a-z0-9_.]+)', '([a-z0-9_]+)',\s*'(take|account)', '(wipe|delete)', "
        r"'([a-z0-9_]+)', (NULL::text\[\]|ARRAY\[[^\]]*\])\)", body)
    return [{"store": s, "relation": r, "scope": sc, "action": a,
             "key_column": k, "columns": re.findall(r"'([a-z0-9_]+)'", cols)}
            for s, r, sc, a, k, cols in rows]


def _log_tables() -> list[str]:
    return re.findall(r"\('([a-z0-9_]+)', ARRAY",
                      _latest("retention_log_relations_v1"))


def _financial_tables() -> list[str]:
    return re.findall(r"\('([a-z0-9_]+)', '[a-z0-9_]+'\)",
                      _latest("retention_financial_relations_v1"))


# ── A database stand-in: records every call, in order ───────────────────────

class _Result:
    def __init__(self, data: Any) -> None:
        self.data = data


class _Query:
    def __init__(self, db: "_Db", relation: str) -> None:
        self.db, self.relation = db, relation
        self.op, self.filters, self.kwargs = "select", [], {}

    def select(self, columns: str) -> "_Query":
        self.op = "select"
        return self

    def delete(self, **kwargs: Any) -> "_Query":
        self.op, self.kwargs = "delete", kwargs
        return self

    def eq(self, column: str, value: Any) -> "_Query":
        self.filters.append((column, value))
        return self

    def in_(self, column: str, values: list) -> "_Query":
        self.filters.append((column, tuple(values)))
        return self

    def limit(self, count: int) -> "_Query":
        return self

    def execute(self) -> _Result:
        self.db.calls.append((self.op, self.relation, tuple(self.filters)))
        return _Result(self.db.on_table(self))


class _Rpc:
    def __init__(self, db: "_Db", name: str, params: dict) -> None:
        self.db, self.name, self.params = db, name, params

    def execute(self) -> _Result:
        self.db.calls.append(("rpc", self.name, dict(self.params)))
        answer = self.db.answers.get(self.name)
        return _Result(answer(self.params) if callable(answer) else answer)


class _Db:
    def __init__(self, answers: dict) -> None:
        self.calls: list[tuple] = []
        self.answers = answers
        self.rows: dict[str, list] = {}
        self.client = self

    def rpc(self, name: str, params: dict) -> _Rpc:
        return _Rpc(self, name, params)

    def table(self, relation: str) -> _Query:
        return _Query(self, relation)

    def on_table(self, query: _Query) -> list:
        if query.op == "delete":
            return self.rows.pop(query.relation, [])
        return []

    def rpcs(self, name: str) -> list[dict]:
        return [c[2] for c in self.calls if c[0] == "rpc" and c[1] == name]

    def index(self, kind: str, name: str) -> int:
        return next(i for i, c in enumerate(self.calls)
                    if c[0] == kind and c[1] == name)


def _record(**extra: Any) -> dict:
    return {"id": "run-1", "requested_mode": "dry_run", "mode": "dry_run",
            "state": "completed", "refusal": None, "as_of": "2026-10-05",
            "due": [{"rule": 1, "would_delete": "x", "how_many": 0}],
            "done": {}, "left_due": None, **extra}


CLAIM = {
    "audio_object_id": "a1", "take_id": "t1", "storage_provider": "r2",
    "bucket": "take-audio", "object_key": "p/t1.wav",
    "exact_bytes_sha256": "a" * 64, "account_user_id": "u1",
    "last_audio_of_account": True, "wiped": {},
}


def _live_db(*, logs: dict | None = None, claim: dict | None = None,
             stores: list | None = None, financial: dict | None = None,
             log_relations: list | None = None) -> _Db:
    batches = {table: list(seq) for table, seq in
               {**(logs or {}), **(financial or {})}.items()}

    def due(params: dict) -> list:
        rule = params["p_rule"]
        if rule == "guests":
            return [{"item_id": "g1"}]
        if rule == "audio":
            return [{"item_id": "a1"}]
        queue = batches.get(params["p_relation"]) or []
        return [{"item_id": i} for i in (queue.pop(0) if queue else [])]

    return _Db({
        "begin_retention_live_run_v1": _record(mode="live", requested_mode="live",
                                               state="running"),
        "retention_measurement_stores_v1": stores if stores is not None else _stores(),
        "retention_log_relations_v1": [{"relation": t} for t in (
            log_relations if log_relations is not None else _log_tables())],
        "retention_financial_relations_v1": [
            {"relation": t} for t in _financial_tables()],
        "list_retention_due_v1": due,
        "request_retention_guest_purge_v1": {"purge_request_id": "req-1",
                                             "state": "requested"},
        "claim_retention_audio_v1": dict(claim or CLAIM),
        "settle_retention_audio_v1": {},
        "count_retention_outcome_v1": {},
        "finish_retention_live_run_v1": lambda p: _record(
            mode="live", requested_mode="live", state=p["p_state"],
            error_code=p["p_error_code"]),
    })


@pytest.fixture
def storage(monkeypatch):
    """The object store: every call is recorded in the database's call log,
    so the order of measurements, object and event can be read off."""
    state = {"absent": False, "raise": None, "db": None}

    def delete(key, *, bucket, storage_provider, expected_sha256):
        state["db"].calls.append(("storage", "delete", (bucket, key, expected_sha256)))
        if state["raise"]:
            raise state["raise"]
        return True

    def absent(key, *, bucket, storage_provider):
        state["db"].calls.append(("storage", "absent", (bucket, key)))
        return state["absent"]

    monkeypatch.setattr(rc, "delete_verified_lab_audio_object", delete)
    monkeypatch.setattr(rc, "verify_lab_audio_object_absent", absent)
    return state


@pytest.fixture
def erasure(monkeypatch):
    runs: list[str] = []
    outcome = {"result": {"state": "done"}}

    class _Orchestrator:
        def run(self, request_id):
            runs.append(request_id)
            if isinstance(outcome.get("raise"), Exception):
                raise outcome["raise"]
            return outcome

    monkeypatch.setattr(rc, "orchestrator_for", lambda db, rid: _Orchestrator())
    return {"runs": runs, "outcome": outcome}


@pytest.fixture
def live(monkeypatch):
    monkeypatch.setattr(rc, "RETENTION_CLEANER_LIVE", True)


# ── The two keys ────────────────────────────────────────────────────────────


def test_a_dry_run_counts_records_and_deletes_nothing(storage):
    db = _Db({"record_retention_dry_run_v1": _record()})
    storage["db"] = db
    summary = rc.run(db)
    assert db.rpcs("record_retention_dry_run_v1") == [{
        "p_requested_mode": "dry_run", "p_cleaner_version": rc.CLEANER_VERSION,
        "p_refusal": None, "p_as_of": None}]
    assert [c[:2] for c in db.calls] == [("rpc", "record_retention_dry_run_v1")]
    assert summary["run_id"] == "run-1" and summary["due"]


def test_a_live_request_is_refused_while_the_key_is_off(storage, erasure, monkeypatch):
    monkeypatch.setattr(rc, "RETENTION_CLEANER_LIVE", False)
    db = _Db({"record_retention_dry_run_v1": _record(
        requested_mode="live", state="refused", refusal=rc.REFUSAL_LIVE_OFF)})
    storage["db"] = db
    summary = rc.run(db, mode="live")
    assert db.rpcs("record_retention_dry_run_v1")[0]["p_requested_mode"] == "live"
    assert db.rpcs("record_retention_dry_run_v1")[0]["p_refusal"] == rc.REFUSAL_LIVE_OFF
    assert [c[:2] for c in db.calls] == [("rpc", "record_retention_dry_run_v1")]
    assert erasure["runs"] == []
    assert summary["refusal"] == rc.REFUSAL_LIVE_OFF


# ── A live run (the key patched on) ────────────────────────────────────────

def test_a_live_run_works_through_the_four_rules_in_order(live, storage, erasure):
    db = _live_db(logs={"life_reminder_log": [["7", "8"], []]},
                  financial={"token_ledger": [["11", "12", "13"], []]})
    storage["db"] = db
    db.rows = {"session_sniper_metrics": [{"session_id": "t1"}],
               "user_acoustic_baseline": [{"user_id": "u1"}, {"user_id": "u1"}]}
    summary = rc.run(db, mode="live", purge_execution=True)

    assert summary["state"] == "completed"
    # Rule 1 runs the account purge on the request the database opened.
    assert erasure["runs"] == ["req-1"]
    # Rule 2: the claim (which empties the measurement columns), the
    # measurement rows, the object by its hash, and only then the event.
    claim = db.index("rpc", "claim_retention_audio_v1")
    rows = [i for i, c in enumerate(db.calls) if c[0] == "delete"
            and c[1] in ("session_sniper_metrics", "dimension_evaluations",
                         "arc_part_acoustics", "user_acoustic_baseline")]
    obj = db.index("storage", "delete")
    settle = db.index("rpc", "settle_retention_audio_v1")
    assert claim < min(rows) and max(rows) < obj < settle
    assert db.calls[obj][2] == ("take-audio", "p/t1.wav", "a" * 64)
    assert db.rpcs("settle_retention_audio_v1") == [{
        "p_run_id": "run-1", "p_audio_object_id": "a1", "p_outcome": "deleted",
        "p_error_code": None}]
    # Rule 3: the due ids, removed by id, in the reviewed table.
    logs = db.calls.index(("delete", "life_reminder_log", (("id", ("7", "8")),)))
    # Rule 4: the same, in a financial table, after the logs.
    ledger = db.calls.index(("delete", "token_ledger",
                             (("id", ("11", "12", "13")),)))
    assert settle < logs < ledger
    assert {c[2]["p_rule"] for c in db.calls
            if c[:2] == ("rpc", "list_retention_due_v1")} == {
        "guests", "audio", "logs", "financial"}
    counted = {(c[2]["p_key"], c[2]["p_n"]) for c in db.calls
               if c[1] == "count_retention_outcome_v1"}
    assert {("guests.erased", 1), ("logs.life_reminder_log", 2),
            ("financial.token_ledger", 3),
            ("measurements.session_sniper_metrics", 1),
            ("measurements.user_acoustic_baseline", 2)} <= counted
    assert db.index("rpc", "finish_retention_live_run_v1") == len(db.calls) - 1


def test_a_registry_that_disagrees_with_the_database_deletes_nothing(
        live, storage, erasure):
    stores = [s for s in _stores() if s["relation"] != "user_acoustic_baseline"]
    db = _live_db(stores=stores)
    storage["db"] = db
    summary = rc.run(db, mode="live")
    assert summary["state"] == "failed"
    assert summary["error_code"] == "RETENTION_REGISTRY_MISMATCH"
    assert erasure["runs"] == []
    assert not db.rpcs("claim_retention_audio_v1")
    assert not [c for c in db.calls if c[0] in ("delete", "storage")]


# ── What it may touch ───────────────────────────────────────────────────────


def test_every_relation_the_cleaner_writes_is_classified_and_none_is_retained():
    written = ({s["relation"] for s in _stores()} | set(rc.LOG_TABLES))
    assert written <= classified_relations()
    removed = {r for r, _ in rc.TAKE_MEASUREMENT_ROWS + rc.ACCOUNT_MEASUREMENT_ROWS}
    assert (removed | set(rc.LOG_TABLES) | set(rc.FINANCIAL_TABLES)
            <= DYNAMIC_RUNTIME_RELATIONS)
    by_relation: dict[str, set] = {}
    for dep in DEPENDENCIES:
        by_relation.setdefault(dep.relation, set()).add(dep.disposition)
    for relation in written:
        assert "retain" not in by_relation.get(relation, set()), relation
    # Rule 4 is the one exception, and exactly it: the relations the purge
    # keeps as financial evidence (v1.3), whose period the clean-up ends.
    financial = {dep.relation for dep in DEPENDENCIES
                 if dep.retention_category == "financial_evidence"}
    assert financial == set(rc.FINANCIAL_TABLES)
    for relation in financial:
        assert by_relation[relation] == {"retain"}, relation
    # A tombstone relation is written only in the columns its receipt erases
    # anyway (0379): never what the receipt keeps.
    erasable = {"acoustic_feature_snapshots": {"features"}}
    keep = {"id", "arc_id", "owner_principal_id", "user_id", "project_id",
            "take_index", "canonical_take_index", "recording_kind",
            "analysis_state", "paired_session_id", "created_at", "updated_at",
            "completed_at"}
    for store in _stores():
        if "tombstone" not in by_relation.get(store["relation"], set()):
            continue
        assert store["action"] == "wipe", store
        if store["relation"] == "v2_sessions":
            assert not set(store["columns"]) & keep
            assert store["relation"] in LINEAGE_TOMBSTONES
        else:
            assert set(store["columns"]) <= erasable[store["relation"]], store


# ── The migration ───────────────────────────────────────────────────────────


def test_the_measurements_go_before_the_recording():
    claim = _function("claim_retention_audio_v1")
    assert claim.index("retention_wipe_measurements_v1") < claim.index("RETURN jsonb_build_object(\n")
    settle = _function("settle_retention_audio_v1")
    assert "processing_audio_object_deletion_events" in settle
    assert "retention_wipe_measurements_v1" not in settle


# ── The cron route ──────────────────────────────────────────────────────────

class RouteTests(unittest.TestCase):
    def setUp(self):
        try:
            from app import app
        except Exception as e:  # pragma: no cover
            self.skipTest(f"app import failed: {e}")
        app.config["TESTING"] = True
        self.client = app.test_client()
        from config import Config
        self.config = Config

    def _post(self, body, secret="right", configured="right"):
        with mock.patch.object(self.config, "RETENTION_CLEANER_SECRET", configured):
            return self.client.post("/v2/internal/retention/clean", json=body,
                                    headers={"X-Internal-Secret": secret})

    def test_the_route_is_dead_without_its_secret(self):
        self.assertEqual(self._post({}, configured="").status_code, 503)
