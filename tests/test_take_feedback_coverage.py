"""Each served Take keeps its coverage and lane outcomes (D-ML-5; 0437;
contract 24c, 24d, 25; AC-9; LIVE LOOP).

The row is written at serve time, one per Take; a shortfall raises a
warning event; the write is best-effort and never blocks serving; nothing
about it reaches a user payload."""
from __future__ import annotations

import re
from pathlib import Path

import pytest

import services.mlc3_first_client_feedback as feedback
from services.first_client_repository import FirstClientRepository
from tests.test_mlc3_first_client_feedback import (
    USER,
    _Database,
    _source,
)

ROOT = Path(__file__).resolve().parents[1]


class _Recording(_Database):
    def __init__(self, answer=True, raises=False):
        super().__init__()
        self.rows: list[dict] = []
        self.answer = answer
        self.raises = raises

    def record_take_feedback_coverage(self, row):
        self.rows.append(row)
        if self.raises:
            raise RuntimeError("database down")
        return self.answer


def _serve(monkeypatch, database):
    from config import Config

    monkeypatch.setattr(Config, "MLC3_SERVICE_ENABLED", True)
    session, document, snippets = _source()
    return feedback.prepare_first_client_feedback(
        database=database, session=session, take_document=document,
        served_text=document["text"], snippets=snippets, suggestions={},
        feedback_candidates=[], owner_user_id=USER,
    )


def _warnings(monkeypatch) -> list:
    seen: list = []
    import services.f1_observability as observability
    monkeypatch.setattr(observability, "observe_f1_degrade",
                        lambda reason, **context: seen.append((reason, context)))
    return seen


def test_a_served_take_writes_one_row_with_policy_counts_and_lanes(monkeypatch):
    database = _Recording()
    rows = _serve(monkeypatch, database)
    assert rows and len(database.rows) == 1
    row = database.rows[0]
    session, _, _ = _source()
    assert row["take_session_id"] == session["id"]
    assert row["project_id"] == session["project_id"]
    assert row["take_index"] == 1
    assert row["policy_version"] == "take-feedback-policy-v3-serving-v1"
    assert row["slides_with_blocks"] == 1
    assert row["slides_covered"] == 1
    assert row["required_floor"] == 0.7
    assert row["floor_met"] is True
    assert row["uncovered"] == []
    assert row["lane_outcomes"] == {
        "confident_voice": "selected",
        "rewrite_clarity": "no_defensible_candidate",
        "great_formulation": "no_defensible_candidate",
    }


def test_no_row_and_no_write_when_the_take_is_not_served(monkeypatch):
    from config import Config

    database = _Recording()
    monkeypatch.setattr(Config, "MLC3_SERVICE_ENABLED", False)
    session, document, snippets = _source()
    assert feedback.prepare_first_client_feedback(
        database=database, session=session, take_document=document,
        served_text=document["text"], snippets=snippets, suggestions={},
        feedback_candidates=[], owner_user_id=USER,
    ) is None
    assert database.rows == []


def test_a_failed_write_never_blocks_serving(monkeypatch):
    database = _Recording(raises=True)
    rows = _serve(monkeypatch, database)
    assert rows is not None and len(rows) == 1
    assert len(database.rows) == 1


def test_the_rows_served_carry_nothing_of_the_coverage(monkeypatch):
    """AC-9: the coverage is internal; the payload is what it was."""
    rows = _serve(monkeypatch, _Recording())
    text = repr(rows)
    for key in ("floor_met", "slides_covered", "slides_with_blocks",
                "required_floor", "lane_outcomes", "coverage"):
        assert key not in text


def _short_frame() -> dict:
    return {
        "policy_version": "take-feedback-policy-v3-serving-v1",
        "coverage": {"assessable_slides": 3, "covered_slides": 1,
                     "required_floor": 0.8, "meets_floor": False,
                     "uncovered": [{"slide_index": 1, "reasons": ["x"]},
                                   {"slide_index": 2, "reasons": ["y"]}]},
        "blocks": [{"slide_index": 0, "selected_candidate_id": "c"},
                   {"slide_index": 1}, {"slide_index": 2}],
        "verbal_lanes": {"rewrite_clarity": {"outcome": "selected"},
                         "great_formulation": {"outcome": "no_defensible_candidate"}},
    }


@pytest.mark.parametrize("answer, warned", [
    (True, True),    # the first serve of the Take: warn
    (None, True),    # the write failed: nothing says it warned before
    (False, False),  # a reread of a Take already recorded: quiet
])
def test_a_shortfall_raises_a_warning_event_once_per_take(monkeypatch, answer, warned):
    seen = _warnings(monkeypatch)
    database = _Recording(answer=answer)
    feedback._record_coverage(database, {"id": "t", "take_index": 2}, _short_frame())
    assert len(database.rows) == 1
    if not warned:
        assert seen == []
        return
    assert len(seen) == 1
    reason, context = seen[0]
    assert reason == "feedback_coverage_shortfall"
    assert context["slides_with_blocks"] == 3 and context["slides_covered"] == 1
    assert context["take"] == "t"


def test_a_met_floor_raises_nothing(monkeypatch):
    seen = _warnings(monkeypatch)
    frame = _short_frame()
    frame["coverage"] = {**frame["coverage"], "covered_slides": 3,
                         "meets_floor": True, "uncovered": []}
    feedback._record_coverage(_Recording(), {"id": "t"}, frame)
    assert seen == []


def test_a_take_with_no_valid_block_types_its_voice_lane_honestly():
    frame = {"policy_version": "p", "blocks": [],
             "coverage": {"assessable_slides": 0, "covered_slides": 0,
                          "required_floor": 1.0, "meets_floor": True,
                          "uncovered": []}}
    row = feedback.coverage_row({"id": "t", "take_index": 3}, frame)
    assert row is not None
    assert row["lane_outcomes"]["confident_voice"] == "no_valid_block"
    assert row["lane_outcomes"]["rewrite_clarity"] == "absent"
    assert feedback.coverage_row({"id": "t"}, None) is None
    assert feedback.coverage_row({}, frame) is None


class _Query:
    def __init__(self, client, table):
        self.client, self.table = client, table
        self.op = None

    def upsert(self, row, **kwargs):
        self.client.calls.append(("upsert", row, kwargs))
        self.op = "upsert"
        return self

    def update(self, row):
        self.client.calls.append(("update", row))
        self.op = "update"
        return self

    def eq(self, column, value):
        self.client.calls.append(("eq", column, value))
        return self

    def execute(self):
        if self.client.error:
            raise RuntimeError({"code": "42P01", "message": "missing"})

        class Result:
            data = (self.client.inserted if self.op == "upsert" else [])
        return Result()


class _Client:
    def __init__(self, inserted, error=False):
        self.inserted, self.error, self.calls = inserted, error, []

    def table(self, name):
        assert name == "take_feedback_coverage"
        return _Query(self, name)


def test_the_repository_inserts_once_then_refreshes():
    row = {"take_session_id": "t", "floor_met": False}
    client = _Client(inserted=[row])
    repository = FirstClientRepository(lambda: client)
    assert repository.record_take_feedback_coverage(row) is True
    assert client.calls[0][0] == "upsert"
    assert client.calls[0][2] == {"on_conflict": "take_session_id",
                                  "ignore_duplicates": True}

    client = _Client(inserted=[])
    repository = FirstClientRepository(lambda: client)
    assert repository.record_take_feedback_coverage(row) is False
    update = [call for call in client.calls if call[0] == "update"][0][1]
    assert "take_session_id" not in update and "first_served_at" not in update
    assert update["last_served_at"]

    client = _Client(inserted=[], error=True)
    assert FirstClientRepository(lambda: client).record_take_feedback_coverage(
        row) is None
    assert FirstClientRepository(lambda: client).record_take_feedback_coverage(
        {}) is None


def test_no_route_reads_the_table():
    """AC-9: only the serve path's writer names the table."""
    for path in (ROOT / "routes").rglob("*.py"):
        assert "take_feedback_coverage" not in path.read_text(), path
    readers = [path for path in (ROOT / "services").rglob("*.py")
               if '"take_feedback_coverage"' in path.read_text()]
    assert sorted(p.name for p in readers) == [
        "data_purge_registry.py", "first_client_repository.py"]


def test_the_migration_is_listed_idempotent_and_the_purge_knows_it():
    from services.data_purge_registry import DEPENDENCIES

    manifest = (ROOT / "migrations" / "manifest.txt").read_text()
    assert "0437\teach_served_take_keeps_its_coverage.sql" in manifest
    sql = (ROOT / "migrations" / "each_served_take_keeps_its_coverage.sql").read_text()
    assert "CREATE TABLE IF NOT EXISTS public.take_feedback_coverage" in sql
    assert "ENABLE ROW LEVEL SECURITY" in sql
    assert "DROP " not in re.sub(r"--.*", "", sql).upper()
    by_relation = {d.relation: d for d in DEPENDENCIES}
    dependency = by_relation["take_feedback_coverage"]
    assert (dependency.selector_column, dependency.locator_kind,
            dependency.disposition) == ("take_session_id", "take", "delete")
