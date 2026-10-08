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
    resolve_declines,
    rewrite_key,
    standing_declines,
)
from tests.test_verbal_lanes_take_document_n48_1 import (
    RECORDING,
    SERVED,
    SPOKEN,
    _lane,
    _placed_document,
    _rewrite,
    _snippets,
)
from services.take_feedback_policy_v3 import build_shadow_frame

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


def _standing(db, *, parts=None, take=THIS, started=TAKE_STARTED):
    return standing_declines(
        db, arc_id="arc", owner_user_id="owner", take_session_id=take,
        take_created_at=started,
        parts=parts if parts is not None else [{"id": PART, "text": WORDS}])


KEY = rewrite_key(PART, SPOKEN[0][2], PROPOSED)


class TestTheRecord:
    def test_a_decline_on_an_earlier_take_stands_while_the_words_are_the_same(self):
        db = _FakeDb([_decline()])
        assert _standing(db) == frozenset({KEY})
        assert db.asked == [([EARLIER], ["rw-1"])]

    def test_whitespace_is_not_a_change_of_words(self):
        db = _FakeDb([_decline()])
        spaced = WORDS.replace(" ", "  ") + "\n"
        assert _standing(db, parts=[{"id": PART, "text": spaced}]) == frozenset({KEY})

    def test_changed_words_lift_the_decline(self):
        db = _FakeDb([_decline()])
        changed = [{"id": PART, "text": WORDS + " at home"}]
        assert _standing(db, parts=changed) == frozenset()

    def test_a_paragraph_no_longer_in_the_document_lifts_it(self):
        assert _standing(_FakeDb([_decline()]), parts=[{"id": "other", "text": "x"}]) \
            == frozenset()

    def test_a_decline_on_this_take_does_not_count(self):
        # Answering this Take's own card must never change this Take.
        db = _FakeDb([_decline(take=THIS)])
        assert _standing(db) == frozenset()
        assert db.asked == []

    def test_a_decline_recorded_after_this_take_began_does_not_count(self):
        db = _FakeDb([_decline(at="2026-10-05T10:00:01Z")])
        assert _standing(db) == frozenset()

    def test_only_a_freeze_made_before_the_decline_names_the_rewrite(self):
        db = _FakeDb([_decline()], frozen_at="2026-10-05T09:45:00Z")
        assert _standing(db) == frozenset()

    def test_an_unreadable_record_applies_nothing(self):
        db = _FakeDb(None)
        assert _standing(db) == frozenset()
        db = _FakeDb([_decline()])
        db.rows = None
        assert _standing(db) == frozenset()
        assert _standing(object()) == frozenset()
        assert _standing(_FakeDb([_decline()]), started=None) == frozenset()

    def test_a_decline_that_cannot_be_proven_is_left_out(self):
        declines = [{"take": EARLIER, "item": "rw-1",
                     "at": __import__("datetime").datetime.fromisoformat(
                         "2026-10-05T09:30:00+00:00")}]
        rows = _FakeDb([]).rows
        assert resolve_declines(declines, {**rows, "snapshots": []}) == []
        assert resolve_declines(declines, {**rows, "items": []}) == []
        no_words = {**rows, "candidates": [{"id": "cand-1", "generated_output": {
            "quote": "q", "proposed_text": ""}}]}
        assert resolve_declines(declines, no_words) == []

    def test_the_reader_asks_for_keep_my_words_on_rewrites_only(self):
        from services.db import DatabaseService

        calls = []

        class _Chain:
            def __getattr__(self, name):
                def step(*args, **_kwargs):
                    calls.append((name, args))
                    return self
                return step

            def execute(self):
                return type("R", (), {"data": [_decline()]})()

        service = DatabaseService.__new__(DatabaseService)
        service.client = _Chain()
        assert service.list_rewrite_declines("arc", "owner") == [_decline()]
        assert ("eq", ("feedback_family", "rewrite_clarity")) in calls
        assert ("eq", ("response", "keep_wording")) in calls
        assert ("eq", ("owner_user_id", "owner")) in calls
        assert ("select", ("take_session_id,feedback_id,created_at",)) in calls

        class _Down:
            def table(self, _name):
                raise RuntimeError("down")

        service.client = _Down()
        assert service.list_rewrite_declines("arc", "owner") is None
        assert service.read_declined_v3_rewrite_rows([EARLIER], ["rw-1"]) is None


# ── V3: the rewrite lane ────────────────────────────────────────────────────

def _second_rewrite():
    # Another defensible rewrite inside the same weak block.
    return {**_rewrite("second-repair"),
            "quote": SPOKEN[1][2], "snippet_id": "s1b",
            "span": {"start": SERVED.index(SPOKEN[1][2]),
                     "end": SERVED.index(SPOKEN[1][2]) + len(SPOKEN[1][2])},
            "proposed_text": "Each learner gets a short daily task.",
            "_manager_evidence": {"fallback": False, "specificity": 1,
                                  "detector": "x", "lexical_words_invented": 0}}


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

    def test_without_a_decline_it_is_offered(self):
        frame = _frame([_rewrite()])
        assert _lane(frame, "rewrite_clarity")["selected_candidate_ids"] == [
            "structural-repair"]

    def test_the_blocks_next_defensible_rewrite_anchors_instead(self):
        rows = [_rewrite(), _second_rewrite()]
        assert _lane(_frame(rows), "rewrite_clarity")["selected_candidate_ids"] \
            == ["structural-repair"]
        frame = _frame(rows, declined=frozenset({KEY}))
        assert _lane(frame, "rewrite_clarity")["selected_candidate_ids"] == [
            "second-repair"]

    def test_a_different_proposal_is_a_different_rewrite(self):
        other = rewrite_key(PART, SPOKEN[0][2], "Our idea is simple.")
        frame = _frame([_rewrite()], declined=frozenset({other}))
        assert _lane(frame, "rewrite_clarity")["selected_candidate_ids"] == [
            "structural-repair"]

    def test_another_paragraph_is_not_declined(self):
        other = rewrite_key("part-slide-2", SPOKEN[0][2], PROPOSED)
        frame = _frame([_rewrite()], declined=frozenset({other}))
        assert _item(frame, "structural-repair")["eligibility"] == "eligible"

    def test_case_and_spacing_do_not_make_a_new_rewrite(self):
        key = rewrite_key(PART, SPOKEN[0][2].upper(), "  our second idea is SIMPLE. ")
        frame = _frame([_rewrite()], declined=frozenset({key}))
        assert _item(frame, "structural-repair")["exclusion_reason"] == DECLINED_BY_OWNER

    def test_a_frozen_selection_is_never_taken_back(self):
        frame = _frame([_rewrite()], declined=frozenset({KEY}),
                       frozen=frozenset({"structural-repair"}))
        assert _lane(frame, "rewrite_clarity")["selected_candidate_ids"] == [
            "structural-repair"]

    def test_praise_is_untouched(self):
        from tests.test_verbal_lanes_take_document_n48_1 import _praise
        praise_key = rewrite_key("part-slide-2", SPOKEN[3][2], SPOKEN[3][2])
        frame = _frame([_praise()], declined=frozenset({praise_key}))
        assert _lane(frame, "great_formulation")["candidates"][0][
            "eligibility"] == "eligible"


# ── the read path ───────────────────────────────────────────────────────────

class TestTheReadPath:
    def test_the_batch_reader_returns_the_four_reads(self):
        from services.db import DatabaseService

        data = {
            "feedback_v3_memberships": [{"id": "m1", "take_id": EARLIER,
                                         "frozen_at": "x",
                                         "document_snapshot_id": "snap-1"}],
            "feedback_v3_membership_items": [{"membership_id": "m1",
                                              "candidate_key": "rw-1",
                                              "candidate_id": "cand-1",
                                              "source_ideal_part_id": PART}],
            "feedback_candidates": [{"id": "cand-1", "generated_output": {}}],
            "ideal_text_document_snapshots": [{"id": "snap-1", "payload": {}}],
        }

        class _Table:
            def __init__(self, name):
                self.name = name

            def __getattr__(self, _name):
                return lambda *a, **k: self

            def execute(self):
                return type("R", (), {"data": data[self.name]})()

        class _Client:
            def table(self, name):
                return _Table(name)

        service = DatabaseService.__new__(DatabaseService)
        service.client = _Client()
        rows = service.read_declined_v3_rewrite_rows([EARLIER], ["rw-1"])
        assert rows == {"memberships": data["feedback_v3_memberships"],
                        "items": data["feedback_v3_membership_items"],
                        "candidates": data["feedback_candidates"],
                        "snapshots": data["ideal_text_document_snapshots"]}
        assert service.read_declined_v3_rewrite_rows([], []) == {
            "memberships": [], "items": [], "candidates": [], "snapshots": []}

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
