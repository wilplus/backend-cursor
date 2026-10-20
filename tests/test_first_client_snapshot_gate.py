"""
STORY    As a speaker, I want a Take whose feedback can't be proven against the
         frozen bundle to show no V3 feedback rather than unrecorded feedback,
         so that what I see is always what was recorded.
OUTCOME
  O1  A source snapshot that does not match the served text declines with
      its named reason BEFORE the exposure bundle is recorded (D20 order),
      and hands back no learning bundle.
  O2  A visible row whose candidate is not in the bundle declines by name,
      and hands back no learning bundle.
  O3  A provable Take serves its rows, and only then hands the recorded
      bundle back through the `learning` out-parameter.
PROVES   O1 -> test_a_snapshot_that_does_not_match_declines_before_the_bundle_is_recorded
         O2 -> test_a_visible_row_outside_the_bundle_declines
         O3 -> test_a_provable_take_serves_rows_and_hands_back_the_recorded_bundle
NOTE     O2 empties the bundle index through the private `_canonical_index`:
         no real inventory can produce a row the bundle lacks, so this is the
         one seam that reaches the refusal.
"""
from __future__ import annotations

import pytest

from services import mlc3_first_client_feedback as module
from services.mlc3_first_client_feedback import (
    V3Unavailable,
    prepare_first_client_feedback,
)
from tests.first_client_fakes import (
    USER,
    _Database,
    _source,
)

RECORD_BUNDLE = "record_feedback_v3_service_candidate_set"


@pytest.fixture(autouse=True)
def _service_on(monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "MLC3_SERVICE_ENABLED", True)


def _run(database, learning):
    session, document, snippets = _source()
    return prepare_first_client_feedback(
        database=database, session=session, take_document=document,
        served_text=document["text"], snippets=snippets, suggestions={},
        feedback_candidates=[], owner_user_id=USER, learning=learning,
    )


class _SnapshotOfOtherWords(_Database):
    def execute(self):
        result = super().execute()
        result.data = {**result.data, "surface": "Words the speaker never saw."}
        return result


def test_a_snapshot_that_does_not_match_declines_before_the_bundle_is_recorded():
    database, learning = _SnapshotOfOtherWords(), {}

    result = _run(database, learning)

    assert result == V3Unavailable("source_snapshot_does_not_match_served_text")
    assert RECORD_BUNDLE not in database.calls
    assert database.bundle is None
    assert learning == {}


def test_a_visible_row_outside_the_bundle_declines(monkeypatch):
    monkeypatch.setattr(module, "_canonical_index", lambda bundle: {})
    learning: dict = {}

    result = _run(_Database(), learning)

    assert result == V3Unavailable("visible_row_candidate_not_in_bundle")
    assert learning == {}


def test_a_provable_take_serves_rows_and_hands_back_the_recorded_bundle():
    database, learning = _Database(), {}

    rows = _run(database, learning)

    assert isinstance(rows, list) and rows
    assert RECORD_BUNDLE in database.calls
    assert learning["bundle"]["candidate_set_id"] == (
        database.bundle["candidate_set_id"])
