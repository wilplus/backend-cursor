"""
STORY    As a speaker, I want a rewrite I answered "Keep my words" to stay
         away until I change that Paragraph, so that I am not asked the same
         thing again.
OUTCOME
  O1  While the Paragraph's words are unchanged, the declined rewrite is
      excluded as declined_by_owner and not selected.
  O2  Once the Paragraph's words change, the same rewrite is eligible again.
  O3  Only declines from an earlier Take, recorded before this Take began,
      count; a candidate already in this Take's frozen selection is never
      excluded.
  O4  An unreadable decline record applies nothing (the rewrite is offered).
  (Never-5 neighbour: the speaker's own words decide; nothing is invented.)
PROVES   O1 -> test_a_declined_rewrite_stays_away_while_the_words_are_unchanged
         O2 -> test_the_rewrite_is_offered_again_once_the_words_change
         O3 -> test_same_take_or_late_declines_do_not_count
               test_a_frozen_selection_is_never_taken_back
         O4 -> test_an_unreadable_record_applies_nothing
WHY      Founder 2026-10-05, N48.2 Q3 A (PARTS 12.3, the Intent Ledger).
"""
from __future__ import annotations

from services.rewrite_declines import DECLINED_BY_OWNER, standing_declines
from services.take_feedback_policy_v3 import build_shadow_frame
from tests.test_verbal_lanes_take_document_n48_1 import (
    RECORDING,
    SERVED,
    SPOKEN,
    _placed_document,
    _rewrite,
    _snippets,
)

TAKE_STARTED = "2026-10-05T10:00:00+00:00"
EARLIER = "take-1"
THIS = "take-2"
PART = "part-slide-1"
WORDS = "Our second idea is simple and it changes how every student"
PROPOSED = "Our second idea is simple."
CANDIDATE = "structural-repair"


class _FakeDb:
    """The two reads `standing_declines` makes: the owner's declines and the
    freezes that served them."""

    def __init__(self, declines, *, rows_readable=True):
        self.declines = declines
        self.rows = {
            "memberships": [{"id": "m1", "take_id": EARLIER,
                             "frozen_at": "2026-10-05T09:00:00Z",
                             "document_snapshot_id": "snap-1"}],
            "items": [{"membership_id": "m1", "candidate_key": "rw-1",
                       "candidate_id": "cand-1", "source_ideal_part_id": PART}],
            "candidates": [{"id": "cand-1", "generated_output": {
                "quote": SPOKEN[0][2], "proposed_text": PROPOSED}}],
            "snapshots": [{"id": "snap-1", "payload": {"parts": [
                {"id": PART, "text": WORDS}, {"id": "other", "text": "x"}]}}],
        } if rows_readable else None

    def list_rewrite_declines(self, _arc_id, _owner):
        return self.declines

    def read_declined_v3_rewrite_rows(self, _takes, _keys):
        return self.rows


def _decline(take=EARLIER, at="2026-10-05T09:30:00Z", item="rw-1"):
    return {"take_session_id": take, "feedback_id": item, "created_at": at}


def _standing(db, paragraph=WORDS):
    return standing_declines(
        db, arc_id="arc", owner_user_id="owner", take_session_id=THIS,
        take_created_at=TAKE_STARTED, parts=[{"id": PART, "text": paragraph}])


def _frame(declined=frozenset(), frozen=frozenset()):
    return build_shadow_frame(
        take_document=_placed_document(parts=True), snippets=_snippets(),
        suggestions={}, feedback_candidates=[_rewrite()], take_index=2,
        expected_recording_id=RECORDING, served_text=SERVED,
        declined_rewrites=declined, frozen_candidate_ids=frozen)


def _lane(frame):
    return frame["verbal_lanes"]["rewrite_clarity"]


def _item(frame):
    return next(row for row in _lane(frame)["candidates"]
                if row["candidate_id"] == CANDIDATE)


def _offered(frame):
    """The rewrite is back in the running: eligible, no exclusion."""
    item = _item(frame)
    return item["eligibility"] == "eligible" and item["exclusion_reason"] is None


def test_a_declined_rewrite_stays_away_while_the_words_are_unchanged():
    frame = _frame(declined=_standing(_FakeDb([_decline()])))
    item = _item(frame)
    assert item["eligibility"] == "excluded"
    assert item["exclusion_reason"] == DECLINED_BY_OWNER
    assert _lane(frame)["selected_candidate_ids"] == []
    assert {"candidate_kind": "verbal_feedback",
            "feedback_family": "rewrite_clarity",
            "candidate_id": CANDIDATE, "input_index": 0,
            "reason": DECLINED_BY_OWNER} in frame["excluded_candidates"]


def test_the_rewrite_is_offered_again_once_the_words_change():
    changed = "Our second idea is simple and it changes every classroom"
    declined = _standing(_FakeDb([_decline()]), paragraph=changed)
    assert declined == frozenset()
    assert _offered(_frame(declined=declined))
    # Whitespace alone is not a change of words.
    assert _standing(_FakeDb([_decline()]), paragraph=f"  {WORDS}  ") != frozenset()


def test_same_take_or_late_declines_do_not_count():
    same_take = _FakeDb([_decline(take=THIS)])
    after_start = _FakeDb([_decline(at="2026-10-05T10:05:00Z")])
    for db in (same_take, after_start):
        declined = _standing(db)
        assert declined == frozenset()
        assert _offered(_frame(declined=declined))


def test_a_frozen_selection_is_never_taken_back():
    declined = _standing(_FakeDb([_decline()]))
    assert declined  # the decline stands ...
    frame = _frame(declined=declined, frozen=frozenset({CANDIDATE}))
    assert _item(frame).get("exclusion_reason") != DECLINED_BY_OWNER
    assert _offered(frame)  # ... but what this Take served stays served


def test_an_unreadable_record_applies_nothing():
    for db in (_FakeDb(None), _FakeDb([_decline()], rows_readable=False)):
        declined = _standing(db)
        assert declined == frozenset()
        assert _offered(_frame(declined=declined))
