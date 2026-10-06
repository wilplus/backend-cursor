"""The machine checks each practise try (founder lock 2026-10-06, the
Feedback walk; decisions log N52.3), dark behind
MACHINE_PRACTICE_CHECK_ENABLED.

Pins: the speaker is never asked; a try measurably better than the original
(the targeted problem cleared, a cue moved, or the machine leg higher) is
praise and closes the practice on that try; anything else is again, with
the encouragement's step or effort key; a rewrite practice is praised, never
measured against the original; the decision is never written as the
speaker's answer (L3); the screen sees only the outcome and the line key
(AC-9); the moment counts as settled and its helper words can be tapped; the
route is off until the walk's screens ship.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from services import practice_check as pc
from services.moment_events import settled_status_by_moment
from services.practice_adoption import helper_words_from_practice

ROOT = Path(__file__).resolve().parents[1]

PRACTICE = {"id": "p-1", "owner_user_id": "owner-1", "kind": "exercise", "status": "open",
            "exercise_snapshot": {"matching_criteria": {"primary_problem_tag": "rushing"}},
            "acoustic_evidence": {"signals": {"insufficient_pauses": True},
                                  "snapshot": {"confidence": 0.2}}}
STILL_RUSHING = {"pause_ratio": 0.02, "confidence": 0.1}


def _attempt(index, *, snapshot=None, original=None, attempt=None, aid=None):
    return {"id": aid or f"a-{index}", "attempt_index": index,
            "transcript": "we doubled  revenue",
            "acoustic_metrics": snapshot if snapshot is not None else dict(STILL_RUSHING),
            "comparison": {"cues": {"original": original or {}, "attempt": attempt or {}}}}


class _Db:
    def __init__(self, attempts):
        self.attempts = attempts
        self.updates: list = []

    def list_confident_voice_practice_attempts(self, _pid):
        return list(self.attempts)

    def update_confident_voice_practice(self, practice_id, owner, fields):
        self.updates.append((practice_id, owner, fields))
        return {**PRACTICE, **fields}

    def keep_confident_voice_practice_attempt(self, *_a, **_k):  # pragma: no cover
        raise AssertionError("the machine never writes the speaker's answer")


# ── the decision ──────────────────────────────────────────────────────────

def test_a_try_where_the_targeted_problem_cleared_is_praise():
    tried = _attempt(1, snapshot={"pause_ratio": 0.2, "confidence": 0.1})
    check = pc.decide(PRACTICE, [tried], "a-1")
    assert (check["next"], check["key"], check["lane"]) == ("praise", "cleared:rushing", "cleared")
    assert check["decided_by"] == "machine" and check["rule_version"] == pc.RULE_VERSION


def test_a_cue_that_moved_or_the_machine_leg_is_praise_too():
    moved = _attempt(1, original={"pausing": 0.0}, attempt={"pausing": 0.7})
    assert pc.decide(PRACTICE, [moved], "a-1")["key"] == "cue:no_hesitation"
    surer = _attempt(1, snapshot={**STILL_RUSHING, "confidence": 0.6})
    assert pc.decide(PRACTICE, [surer], "a-1")["key"] == "more_assured"


def test_nothing_measurably_better_is_again_with_effort_or_a_step():
    first = _attempt(1)
    check = pc.decide(PRACTICE, [first], "a-1")
    assert (check["next"], check["key"]) == ("again", "effort")
    second = _attempt(2, attempt={"pausing": 0.7})
    first_read = _attempt(1, attempt={"pausing": 0.0})
    check = pc.decide(PRACTICE, [first_read, second], "a-2")
    # A real step between the tries, still not better than the original.
    assert (check["next"], check["key"]) == ("again", "step")


def test_a_rewrite_try_is_praised_and_never_measured_against_the_original():
    rewrite = {**PRACTICE, "kind": "rewrite"}
    check = pc.decide(rewrite, [_attempt(1)], "a-1")
    assert (check["next"], check["key"]) == ("praise", "good_job")
    one = _attempt(1, attempt={"pausing": -1.0})
    two = _attempt(2, attempt={"pausing": 0.0})
    assert pc.decide(rewrite, [one, two], "a-2")["key"] == "cue:no_hesitation"


def test_only_two_outcomes_and_the_screen_sees_no_measure():
    for tried in (_attempt(1), _attempt(1, snapshot={"pause_ratio": 0.2})):
        check = pc.decide(PRACTICE, [tried], "a-1")
        assert check["next"] in pc.NEXT
        assert pc.public_check(check) == {"next": check["next"], "key": check["key"]}


# ── the loop ──────────────────────────────────────────────────────────────

def test_praise_closes_the_practice_on_that_try_without_an_answer():
    db = _Db([_attempt(1), _attempt(2, snapshot={"pause_ratio": 0.2})])
    with patch("services.delayed_measure.enrol") as enrol:
        status, body = pc.check_attempt(db, PRACTICE, "a-2", "owner-1")
    assert status == 200 and body["outcome"] == "done"
    assert body["check"] == {"next": "praise", "key": "cleared:rushing"}
    assert body["attempt_transcript"] == "we doubled revenue"
    fields = db.updates[-1][2]
    assert fields["status"] == "completed" and fields["selected_attempt_id"] == "a-2"
    assert fields["landed_attempt_index"] == 2 and fields["closed_at"]
    # L3: the machine's decision is never the speaker's answer.
    assert "final_user_answer" not in fields and "user_answer" not in fields
    assert fields["after_practice"]["decided_by"] == "machine"
    enrol.assert_called_once()


def test_again_keeps_the_practice_open_and_only_the_latest_try_is_checked():
    db = _Db([_attempt(1), _attempt(2)])
    status, body = pc.check_attempt(db, PRACTICE, "a-2", "owner-1")
    assert (status, body["outcome"], body["check"]["next"]) == (200, "again", "again")
    assert "status" not in db.updates[-1][2]
    status, body = pc.check_attempt(db, PRACTICE, "a-1", "owner-1")
    assert (status, body["code"]) == (409, "NOT_CHECKABLE")
    status, body = pc.check_attempt(db, {**PRACTICE, "status": "completed"}, "a-2", "owner-1")
    assert (status, body["code"]) == (409, "PRACTICE_CLOSED")


def test_a_failed_write_is_an_error_not_a_silent_praise():
    db = _Db([_attempt(1, snapshot={"pause_ratio": 0.2})])
    db.update_confident_voice_practice = lambda *a, **k: None
    status, body = pc.check_attempt(db, PRACTICE, "a-1", "owner-1")
    assert (status, body["code"]) == (500, "V2_ERROR")


# ── what a machine-closed practice means elsewhere ───────────────────────

CLOSED = {**PRACTICE, "status": "completed", "final_user_answer": None,
          "selected_attempt_id": "a-1", "project_id": "arc-1",
          "after_practice": {"decided_by": "machine", "next": "praise", "key": "good_job"}}


def test_a_machine_closed_practice_settles_its_moment():
    class _Moments:
        def list_moment_events_for_take(self, _take):
            return []

        def list_confident_voice_practice_for_take(self, _take, _owner):
            return [{**CLOSED, "snippet_id": "s-1"},
                    {**CLOSED, "snippet_id": "s-2",
                     "after_practice": {"decided_by": "machine", "next": "again"}}]
    settled = settled_status_by_moment(_Moments(), take_session_id="take-1", owner_user_id="owner-1")
    assert settled == {"s-1": "approved", "s-2": "dismissed"}


def test_its_helper_words_can_be_tapped_from_the_praised_try():
    class _Words:
        def list_confident_voice_practice_attempts(self, _pid):
            return [_attempt(1)]

        class takes:
            @staticmethod
            def get_arc_sessions(_arc):
                return []
    with patch("services.intervention_spend.latest_spoken_take_sid", return_value="t-1"), \
            patch("services.slide_helper_words.record_pick") as pick:
        status, body = helper_words_from_practice(_Words(), CLOSED, "part-1", "doubled", "owner-1")
    assert (status, body["phrase"]) == (200, "doubled")
    pick.assert_called_once()
    not_praised = {**CLOSED, "after_practice": {"decided_by": "machine", "next": "again"}}
    status, body = helper_words_from_practice(_Words(), not_praised, "part-1", "doubled", "owner-1")
    assert (status, body["code"]) == (409, "NOT_ADOPTED")


# ── the switch and the route ──────────────────────────────────────────────

def test_the_switch_is_off_until_the_walk_screens_ship():
    from config import Config
    assert Config.MACHINE_PRACTICE_CHECK_ENABLED is False
    assert pc.machine_practice_check_enabled() is False


def test_the_route_is_fenced_and_hides_the_measure():
    source = (ROOT / "routes/v2/user_sessions.py").read_text()
    start = source.index("def v2_check_confident_voice_practice_attempt")
    route = source[start:source.index("@v2_bp.route", start)]
    assert "machine_practice_check_enabled()" in route
    assert route.index("machine_practice_check_enabled()") < route.index("get_confident_voice_practice")
    head = source[source.rindex("@v2_bp.route", 0, start):start]
    assert '"<attempt_id>/check", methods=["POST"]' in head
    for fence in ("@require_auth", 'operational_purpose_disabled("personalized_exercise_recommendation")',
                  'consent_choice_required("personalised_practice")'):
        assert fence in head
    assert '"after_practice": _after_practice_public(' in source


def test_the_owner_payload_shows_only_the_outcome_of_a_machine_check():
    from routes.v2.user_sessions import _after_practice_public
    blob = {"decided_by": "machine", "next": "praise", "key": "cue:no_hesitation",
            "lane": "cue", "attempt_index": 2, "rule_version": pc.RULE_VERSION}
    assert _after_practice_public(blob) == {"next": "praise", "key": "cue:no_hesitation"}
    old = {"key": "good_job", "sentence": "Good job."}
    assert _after_practice_public(old) == old
    assert _after_practice_public(None) is None
