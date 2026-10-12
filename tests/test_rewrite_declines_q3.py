"""After "Keep my words" the same rewrite is not offered again on that
Paragraph until its words change (founder 2026-10-05, N48.2, Q3 A; PARTS
§12.3, the Intent Ledger).

Pins:
  * the record: an owner `keep_wording` on an earlier Take's V3 rewrite,
    resolved through the freeze that served it to (Paragraph, quote,
    proposed words) and the Paragraph's words in that freeze's document;
  * the rule: V3 excludes a matching rewrite as `declined_by_owner` while
    the Paragraph's words are unchanged, and offers it again once they
    change; the block's next defensible rewrite anchors instead, nothing is
    invented;
  * what never changes: a decline on the same Take, or recorded after the
    Take began, does not count; a candidate already in the Take's frozen
    selection is never excluded; an unreadable record applies nothing.
"""
from __future__ import annotations

from services.rewrite_declines import (
    DECLINED_BY_OWNER,
    rewrite_key,
)
from services.take_feedback_policy_v3 import build_shadow_frame
from tests.test_verbal_lanes_take_document_n48_1 import (
    RECORDING,
    SERVED,
    SPOKEN,
    _lane,
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


class _FakeDb:
    def __init__(self, declines, *, paragraph=WORDS, frozen_at="2026-10-05T09:00:00Z",
                 quote=SPOKEN[0][2], proposed=PROPOSED):
        self.declines = declines
        self.rows = {
            "memberships": [{"id": "m1", "take_id": EARLIER, "frozen_at": frozen_at,
                             "document_snapshot_id": "snap-1"}],
            "items": [{"membership_id": "m1", "candidate_key": "rw-1",
                       "candidate_id": "cand-1", "source_ideal_part_id": PART}],
            "candidates": [{"id": "cand-1", "generated_output": {
                "quote": quote, "proposed_text": proposed}}],
            "snapshots": [{"id": "snap-1", "payload": {"parts": [
                {"id": PART, "text": paragraph}, {"id": "other", "text": "x"}]}}],
        }
        self.asked = []

    def list_rewrite_declines(self, arc_id, owner):
        return self.declines

    def read_declined_v3_rewrite_rows(self, takes, keys):
        self.asked.append((sorted(takes), sorted(keys)))
        return self.rows


def _decline(take=EARLIER, at="2026-10-05T09:30:00Z", item="rw-1"):
    return {"take_session_id": take, "feedback_id": item, "created_at": at}


KEY = rewrite_key(PART, SPOKEN[0][2], PROPOSED)


# ── V3: the rewrite lane ────────────────────────────────────────────────────


def _frame(rows, declined=frozenset(), frozen=frozenset()):
    return build_shadow_frame(
        take_document=_placed_document(parts=True), snippets=_snippets(),
        suggestions={}, feedback_candidates=rows, take_index=2,
        expected_recording_id=RECORDING, served_text=SERVED,
        declined_rewrites=declined, frozen_candidate_ids=frozen)


def _item(frame, candidate_id):
    return next(row for row in _lane(frame, "rewrite_clarity")["candidates"]
                if row["candidate_id"] == candidate_id)


class TestTheRewriteLane:
    def test_a_declined_rewrite_is_excluded_with_its_reason(self):
        frame = _frame([_rewrite()], declined=frozenset({KEY}))
        item = _item(frame, "structural-repair")
        assert item["eligibility"] == "excluded"
        assert item["exclusion_reason"] == DECLINED_BY_OWNER
        assert _lane(frame, "rewrite_clarity")["selected_candidate_ids"] == []
        assert {"candidate_kind": "verbal_feedback",
                "feedback_family": "rewrite_clarity",
                "candidate_id": "structural-repair", "input_index": 0,
                "reason": DECLINED_BY_OWNER} in frame["excluded_candidates"]


# ── the read path ───────────────────────────────────────────────────────────

class TestTheReadPath:

    def test_the_run_hands_v3_the_standing_keys_and_its_frozen_selection(self):
        from types import SimpleNamespace

        from services.ideal_text_changes import _ChangesRun

        run = _ChangesRun.__new__(_ChangesRun)
        run.db = _FakeDb([_decline()])
        run.arc_id, run.user_id, run.arm_sid = "arc", "owner", THIS
        run.feedback_set = {"selected_keys": [
            {"id": "structural-repair", "feedback_family": "rewrite_clarity"},
            {"id": "cv-1", "feedback_family": "confident_voice"}, "junk"]}
        declined, frozen = run._declined_rewrites(
            {"id": THIS, "created_at": TAKE_STARTED}, [{"id": PART, "text": WORDS}])
        assert declined == frozenset({KEY})
        assert frozen == frozenset({"structural-repair", "cv-1"})
        # Anything that raises applies nothing and never fails the read.
        run.db = SimpleNamespace(
            list_rewrite_declines=lambda *_a: 1 / 0,
            read_declined_v3_rewrite_rows=lambda *_a: None)
        run.feedback_set = None
        assert run._declined_rewrites({"id": THIS, "created_at": TAKE_STARTED},
                                      []) == (frozenset(), frozenset())
