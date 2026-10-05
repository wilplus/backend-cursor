"""The card the page opens a moment on (founder 2026-10-05, N48.1, Wave 1
step 1).

The follow-up matrix decides at the open what shows (`decide_at_open`), but
the page chose its card itself and, never told whether a problem fired
(AC-9), showed the rewrite where the matrix says the coach's request. The
served moment now carries `open_card`, computed by the same `decide_at_open`
from the same clip read and exercise draw `follow_up_for_open` uses. Pins:
one value per matrix cell; a closed enum and nothing else rides the row; the
field is omitted when the inputs are unavailable, when the switch is off, and
for the coach's request when no coach is on the panel.
"""
from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

from services import confident_voice_practice as cvp
from services import judgement_follow_up as jf
from services import ideal_text_changes as itc


def _snippet(sid):
    return {"id": sid, "transcript": "we think the timing matters here",
            "duration_ms": 4000, "audio_segment_path": f"s/{sid}.webm",
            "words": [], "metrics": {"wpm": 150.0, "pause_ratio": 0.1,
                                     "voiced_ratio": 0.8,
                                     "audio_quality": {"reliable": True}}}


class _Db:
    def __init__(self, *, assigned=(), coach=True, fail=False, known=None):
        self.assigned = set(assigned)
        self.coach = coach
        self.fail = fail
        self.known = known
        self.candidate_reads = 0
        self.raised: list = []

    def get_confident_voice_practice_candidates(self, ids):
        self.candidate_reads += 1
        if self.fail:
            raise RuntimeError("down")
        return [_snippet(s) for s in ids
                if self.known is None or s in self.known]

    def get_snippets_by_session(self, _take):
        return [{"metrics": {"wpm": 150.0}}]

    def get_confident_voice_exercise_assignment(self, _take, sid):
        return {"exercise_id": "x"} if sid in self.assigned else None

    def any_active_coach(self):
        return self.coach

    def list_speaking_errors(self):
        return [{"error_id": "rushing", "status": "detected"}]

    def request_exercise_from_coach(self, **kwargs):  # pragma: no cover
        self.raised.append(kwargs)


# Per snippet: (read, fired). The verdict shapes match the lane's.
READS = {
    "conf": ("confident", False),
    "conf-fired": ("confident", True),
    "weak-fired": ("weak", True),
    "weak-quiet": ("weak", False),
    "unread": ("unknown", False),
}


def _verdict(read, fired):
    pattern = {"confident": "confident",
               "weak": "low_confidence_rushing_dominant",
               "unknown": None}[read]
    if pattern is None:
        return {"eligible": False, "reason": "confidence_unavailable"}
    return {"eligible": True, "pattern": pattern, "priority": 1,
            "signals": {"insufficient_pauses": True} if fired else {},
            "snapshot": {}}


def _eligibility(snippet, **_kw):
    return _verdict(*READS[snippet["id"]])


class OpenCardTests(unittest.TestCase):
    def setUp(self):
        for p in (patch("config.Config.JUDGEMENT_AFTER_FEEDBACK_ENABLED", True),
                  patch.object(cvp, "exercise_eligibility", _eligibility)):
            p.start()
            self.addCleanup(p.stop)
        cvp._coach_presence = (0.0, None)
        self.addCleanup(setattr, cvp, "_coach_presence", (0.0, None))

    def _cards(self, db, ids):
        return jf.open_cards(db, take_session_id="take-1", snippet_ids=ids)

    def test_one_card_per_matrix_cell(self):
        db = _Db(assigned={"weak-fired-matched"})
        READS["weak-fired-matched"] = ("weak", True)
        self.addCleanup(READS.pop, "weak-fired-matched")
        cards = self._cards(db, ["conf", "conf-fired", "weak-fired-matched",
                                 "weak-fired", "weak-quiet", "unread"])
        self.assertEqual(cards, {
            "conf": "praise",
            "conf-fired": "praise",
            "weak-fired-matched": "exercise",
            "weak-fired": "coach_request",
            "weak-quiet": "rewrite",
            "unread": "rewrite",
        })

    def test_the_cells_are_decide_at_open_itself(self):
        db = _Db(assigned={"weak-fired"})
        for sid, (read, fired) in READS.items():
            matched = sid in db.assigned
            now, _ = jf.decide_at_open(read, fired, matched)
            self.assertEqual(self._cards(db, [sid]).get(sid), now, sid)

    def test_only_the_closed_enum_rides(self):
        cards = self._cards(_Db(), list(READS))
        self.assertTrue(set(cards.values()) <= set(jf.OPEN_CARDS))
        self.assertEqual(set(jf.OPEN_CARDS),
                         {"praise", "exercise", "coach_request", "rewrite"})

    def test_no_coach_on_the_panel_leaves_the_coach_request_out(self):
        cards = self._cards(_Db(coach=False), ["weak-fired", "weak-quiet"])
        self.assertEqual(cards, {"weak-quiet": "rewrite"})

    def test_switch_off_serves_no_field(self):
        with patch("config.Config.JUDGEMENT_AFTER_FEEDBACK_ENABLED", False):
            self.assertEqual(self._cards(_Db(), ["weak-fired"]), {})

    def test_unavailable_inputs_omit_the_field(self):
        self.assertEqual(self._cards(_Db(fail=True), ["weak-fired"]), {})
        self.assertEqual(self._cards(_Db(known=set()), ["weak-fired"]), {})
        self.assertEqual(
            self._cards(_Db(known={"conf"}), ["conf", "weak-fired"]),
            {"conf": "praise"})
        self.assertEqual(jf.open_cards(_Db(), take_session_id="",
                                       snippet_ids=["conf"]), {})

    def test_one_batched_read_and_no_request_raised(self):
        db = _Db()
        self._cards(db, list(READS))
        self.assertEqual(db.candidate_reads, 1)
        self.assertEqual(db.raised, [])

    def test_the_open_and_the_page_agree(self):
        # follow_up_for_open runs the same read: its "now" is the page's card.
        class _Req(_Db):
            request = None

            def get_exercise_coach_request(self, *_a):
                return self.request

            def request_exercise_from_coach(self, **kwargs):
                self.request = kwargs

        for sid in READS:
            db = _Req()
            card = self._cards(db, [sid]).get(sid)
            with patch.object(jf, "_raise_request", return_value=True):
                now = jf.follow_up_for_open(
                    db, take_session_id="take-1", snippet_id=sid,
                    owner_user_id="owner-1")
            self.assertEqual(card, now, sid)


class ServedRowTests(unittest.TestCase):
    def _run(self, rows):
        run = itc._ChangesRun.__new__(itc._ChangesRun)
        run.changes = rows
        run.arm_sid = "take-1"
        run.db = object()
        return run

    def test_served_moments_carry_the_card_and_notes_do_not(self):
        rows = [
            {"id": "m1", "source": "confident_voice", "snippet_id": "s1",
             "bookmark_tier": "weak"},
            {"id": "m2", "feedback_family": "confident_voice",
             "snippet_id": "s2", "bookmark_tier": "confident"},
            {"id": "m3", "source": "confident_voice", "snippet_id": "s3"},
            {"id": "n1", "feedback_family": "rewrite_clarity",
             "snippet_id": "s1"},
        ]
        run = self._run(rows)
        with patch.object(jf, "open_cards",
                          return_value={"s1": "coach_request", "s2": "praise"}
                          ) as called:
            run._open_cards()
        self.assertEqual(called.call_args.kwargs["snippet_ids"],
                         ["s1", "s2", "s3"])
        self.assertEqual(rows[0]["open_card"], "coach_request")
        self.assertEqual(rows[1]["open_card"], "praise")
        self.assertNotIn("open_card", rows[2])
        self.assertNotIn("open_card", rows[3])

    def test_no_take_no_read(self):
        run = self._run([{"source": "confident_voice", "snippet_id": "s1"}])
        run.arm_sid = None
        with patch.object(jf, "open_cards") as called:
            run._open_cards()
        called.assert_not_called()

    def test_the_stage_runs_after_the_window_through_the_log(self):
        src = inspect.getsource(itc._ChangesRun.execute)
        self.assertIn('log.run("changes.open_cards", self._open_cards)', src)
        self.assertLess(src.index("self._window"),
                        src.index("self._open_cards"))
        self.assertNotIn("self._open_cards()", src)


if __name__ == "__main__":
    unittest.main()
