"""The coach's queue of moments (founder 2026-09-30, A1 to A8; P2-6).

Pins: speakers oldest first; one word per moment; the kind rides only after
THIS coach's rating (BLIND COACH); the pseudonym is the queue's own.
"""
from __future__ import annotations

import unittest

from services.coach_moments_queue import (
    moment_state, moments_queue, reached_moments,
)

ALL = lambda _sid: {"s1", "s2", "s3"}  # noqa: E731 -- every moment reached


class StateTests(unittest.TestCase):
    def test_unrated_is_judge_it_and_says_nothing_else(self):
        self.assertEqual(moment_state(None, {"kind": "praise"}), {"state": "judge_it"})
        self.assertEqual(moment_state({"value": "yes", "unrateable": True},
                                      {"kind": "praise"}), {"state": "judge_it"})

    def test_rated_states_carry_the_kind(self):
        rated = {"value": "no", "unrateable": False}
        self.assertEqual(moment_state(rated, None), {"state": "judged"})
        self.assertEqual(moment_state(rated, {"kind": "error", "resolution": None}),
                         {"state": "answer_it", "kind": "error"})
        self.assertEqual(moment_state(rated, {"kind": "praise", "resolution": "line_written"}),
                         {"state": "answered", "kind": "praise"})
        self.assertEqual(moment_state(rated, {"kind": "rewrite", "resolution": "no_safe_match"}),
                         {"state": "nothing_to_add", "kind": "rewrite"})


class QueueTests(unittest.TestCase):
    def test_speakers_oldest_first_takes_under_them(self):
        rows = [
            {"id": "t-b2", "user_id": "u-b", "review_requested_at": "2026-09-30T10:00", "take_index": 2},
            {"id": "t-a1", "user_id": "u-a", "review_requested_at": "2026-09-29T10:00", "take_index": 1},
            {"id": "t-b1", "user_id": "u-b", "review_requested_at": "2026-09-28T10:00", "take_index": 1},
        ]
        ratings = {"t-a1": {"s1": {"value": "yes", "unrateable": False}}}
        requests = {("t-a1", "s1"): {"kind": "praise", "resolution": None}}
        out = moments_queue(
            rows, moments_for=lambda r: ["s1", "s2"] if r["id"] == "t-a1" else ["s3"],
            reached_for=ALL, ratings_for=lambda sid: ratings.get(sid, {}),
            request_for=lambda sid, snip: requests.get((sid, snip)),
            pseudonym_for=lambda uid: f"Quiet {uid}")
        self.assertEqual([s["pseudonym"] for s in out], ["Quiet u-b", "Quiet u-a"])
        self.assertEqual([t["take_index"] for t in out[0]["takes"]], [1, 2])
        a = out[1]["takes"][0]
        self.assertEqual(a["moments"], [
            {"snippet_id": "s1", "state": "answer_it", "kind": "praise"},
            {"snippet_id": "s2", "state": "judge_it"},
        ])
        self.assertEqual(a["waiting"], 2)
        self.assertEqual(out[0]["waiting"], 2)

    def test_no_name_no_id_reaches_the_shape(self):
        out = moments_queue(
            [{"id": "t", "user_id": "u", "created_at": "x"}],
            moments_for=lambda r: [], reached_for=ALL, ratings_for=lambda s: {},
            request_for=lambda s, n: None, pseudonym_for=lambda u: "Calm Heron")
        self.assertEqual(set(out[0]), {"pseudonym", "goal", "takes", "waiting", "waiting_for_text"})
        self.assertNotIn("user_id", out[0]["takes"][0])

    def test_a_take_whose_bookmarks_are_not_frozen_rides_as_waiting_for_text(self):
        # Founder 2026-10-01 (A1): never silently absent. `moments_for` says
        # None for "not frozen yet" and [] for "frozen, nothing bookmarked".
        out = moments_queue(
            [{"id": "t-new", "user_id": "u", "created_at": "2026-10-01T09:00"},
             {"id": "t-old", "user_id": "u", "created_at": "2026-09-30T09:00"}],
            moments_for=lambda r: None if r["id"] == "t-new" else [],
            reached_for=ALL, ratings_for=lambda s: {}, request_for=lambda s, n: None,
            pseudonym_for=lambda u: "Calm Otter")
        takes = {t["session_id"]: t for t in out[0]["takes"]}
        self.assertTrue(takes["t-new"]["waiting_for_text"])
        self.assertEqual(takes["t-new"]["moments"], [])
        self.assertEqual(takes["t-new"]["waiting"], 0)
        self.assertFalse(takes["t-old"]["waiting_for_text"])
        self.assertEqual(out[0]["waiting_for_text"], 1)



class ReachedTests(unittest.TestCase):
    """N48.2, Q1 A (audit D9): only moments the speaker was shown or
    answered reach the coach's queue."""

    def test_opened_skipped_answered_and_requested_count_nothing_else(self):
        reached = reached_moments(
            [{"take_session_id": "t", "snippet_id": "s-open", "event": "opened"},
             {"take_session_id": "t", "snippet_id": "s-skip", "event": "skipped"},
             {"take_session_id": "t", "snippet_id": "s-odd", "event": "rendered"},
             {"take_session_id": "t", "snippet_id": None, "event": "opened"},
             "junk"],
            [{"take_session_id": "t", "snippet_id": "s-answered"},
             {"take_session_id": "u", "snippet_id": "s-other-take"}],
            [("t", "s-requested"), "junk"])
        self.assertEqual(reached["t"], {"s-open", "s-skip", "s-answered", "s-requested"})
        self.assertEqual(reached["u"], {"s-other-take"})

    def test_a_bookmark_that_never_reached_the_speaker_is_not_listed(self):
        out = moments_queue(
            [{"id": "t", "user_id": "u", "created_at": "x"}],
            moments_for=lambda r: ["s-met", "s-frozen-only", "s-answered"],
            reached_for=lambda sid: {"s-met", "s-answered"} if sid == "t" else set(),
            ratings_for=lambda s: {}, request_for=lambda s, n: None,
            pseudonym_for=lambda u: "Calm Heron")
        take = out[0]["takes"][0]
        self.assertEqual([m["snippet_id"] for m in take["moments"]],
                         ["s-met", "s-answered"])
        self.assertEqual(take["waiting"], 2)

    def test_reach_is_per_take_never_borrowed_from_another(self):
        out = moments_queue(
            [{"id": "t1", "user_id": "u", "created_at": "1"},
             {"id": "t2", "user_id": "u", "created_at": "2"}],
            moments_for=lambda r: ["s"],
            reached_for=lambda sid: {"s"} if sid == "t1" else set(),
            ratings_for=lambda s: {}, request_for=lambda s, n: None,
            pseudonym_for=lambda u: "Calm Heron")
        takes = {t["session_id"]: t for t in out[0]["takes"]}
        self.assertEqual(len(takes["t1"]["moments"]), 1)
        self.assertEqual(takes["t2"]["moments"], [])

    def test_no_answer_value_can_travel(self):
        # BLIND COACH: the reach read is existence only. An answer row that
        # carries a response still contributes nothing but its ids, and the
        # listed moment says only "judge_it".
        reached = reached_moments(
            [], [{"take_session_id": "t", "snippet_id": "s", "response": "no"}])
        out = moments_queue(
            [{"id": "t", "user_id": "u", "created_at": "x"}],
            moments_for=lambda r: ["s"], reached_for=lambda sid: reached.get(sid, set()),
            ratings_for=lambda s: {}, request_for=lambda s, n: None,
            pseudonym_for=lambda u: "Calm Heron")
        self.assertEqual(out[0]["takes"][0]["moments"],
                         [{"snippet_id": "s", "state": "judge_it"}])
        self.assertNotIn("no", str(out))


def _label(rater, value, **extra):
    return {"rater_id": rater, "value": value, "lane": "coach", "self_report": False,
            "state_id": "confidence", "unrateable": value == "audio_unclear", **extra}


def _queue_for(rater, labels, *, own=None, requests=None):
    """One Take, one moment `s`, as `rater` sees it."""
    return moments_queue(
        [{"id": "t", "user_id": "u", "created_at": "x"}],
        moments_for=lambda r: ["s"], reached_for=lambda sid: {"s"},
        ratings_for=lambda sid: ({"s": own} if own else {}),
        request_for=lambda sid, snip: (requests or {}).get(snip),
        pseudonym_for=lambda u: "Calm Heron",
        labels_for=lambda sid: labels, rater_id=rater)[0]["takes"][0]


class TheLedgerRoutesTheClipTests(unittest.TestCase):
    """K5: one Audio unclear sends the clip to a DIFFERENT coach; two
    quarantine it; neither is a label. K4/K6: two matching answers settle
    it, a disagreement or a Not sure asks a third coach, three without a
    pair are UNRESOLVED; the owner never counts, the machine never votes."""

    def test_the_coach_who_said_audio_unclear_no_longer_sees_judge_it(self):
        # The bug: _RATED left audio_unclear out, so the reporter saw "Judge
        # it" and every retry was a 409 (FRESH_RATER_REQUIRED).
        unclear = {"value": "audio_unclear", "unrateable": True}
        take = _queue_for("coach-a", [_label("coach-a", "audio_unclear")], own=unclear)
        self.assertEqual(take["moments"], [])
        self.assertEqual(take["waiting"], 0)
        # Without the panel's rows the coach's own report still decides.
        self.assertEqual(_queue_for("coach-a", None, own=unclear)["moments"], [])

    def test_the_clip_goes_to_a_different_coach_audio_retry(self):
        take = _queue_for("coach-b", [_label("coach-a", "audio_unclear")])
        self.assertEqual(take["moments"], [{"snippet_id": "s", "state": "judge_it"}])

    def test_two_audio_unclear_reports_quarantine_it_for_a_new_coach(self):
        labels = [_label("coach-a", "audio_unclear"), _label("coach-b", "audio_unclear")]
        self.assertEqual(_queue_for("coach-c", labels)["moments"], [])

    def test_a_coach_who_already_judged_a_quarantined_clip_keeps_their_moment(self):
        labels = [_label("coach-c", "no"), _label("coach-a", "audio_unclear"),
                  _label("coach-b", "audio_unclear")]
        take = _queue_for("coach-c", labels, own={"value": "no", "unrateable": False},
                          requests={"s": {"kind": "error", "resolution": None}})
        self.assertEqual(take["moments"], [{"snippet_id": "s", "state": "answer_it",
                                            "kind": "error"}])

    def test_two_matching_answers_ask_nobody_new(self):
        labels = [_label("coach-a", "yes"), _label("coach-b", "yes")]
        self.assertEqual(_queue_for("coach-c", labels)["moments"], [])
        # The two who judged it keep their own state.
        take = _queue_for("coach-a", labels, own={"value": "yes", "unrateable": False})
        self.assertEqual(take["moments"], [{"snippet_id": "s", "state": "judged"}])

    def test_a_disagreement_or_a_not_sure_asks_a_third_coach(self):
        for second in ("no", "not_sure"):
            labels = [_label("coach-a", "yes"), _label("coach-b", second)]
            take = _queue_for("coach-c", labels)
            self.assertEqual(take["moments"], [{"snippet_id": "s", "state": "judge_it"}],
                             second)

    def test_three_without_a_pair_are_unresolved_and_ask_nobody_new(self):
        labels = [_label("coach-a", "yes"), _label("coach-b", "no"),
                  _label("coach-c", "not_sure")]
        self.assertEqual(_queue_for("coach-d", labels)["moments"], [])

    def test_the_owner_never_counts_toward_the_pair(self):
        # A coach who rated their own clip is a self-report: one coach's yes
        # plus the owner's yes is still a singleton, so a second coach is asked.
        labels = [_label("coach-a", "yes"), _label("owner-1", "yes", self_report=True)]
        take = _queue_for("coach-b", labels)
        self.assertEqual(take["moments"], [{"snippet_id": "s", "state": "judge_it"}])

    def test_routing_returns_a_reason_never_a_value(self):
        from services.coach_moments_queue import routing
        why = routing(None, [_label("coach-a", "yes"), _label("coach-b", "yes")], "coach-c")
        self.assertEqual(why, "rating_closed")
        self.assertIsNone(routing(None, [], "coach-c"))


class TheLabelReadTests(unittest.TestCase):
    def test_labels_are_read_in_chunks_and_a_failed_read_routes_on_own_rows(self):
        from services.coach_moments_queue import labels_for_snippets

        class _Db:
            calls: list = []

            def get_confidence_labels_by_snippet_ids(self, ids, *, strict=False):
                self.calls.append((len(ids), strict))
                return {i: [_label("coach-a", "yes")] for i in ids}

        db = _Db()
        labels_for = labels_for_snippets(db, [f"s{i}" for i in range(320)])
        self.assertEqual([n for n, _ in db.calls], [150, 150, 20])
        self.assertTrue(all(strict for _, strict in db.calls))
        self.assertEqual(len(labels_for("s7")), 1)
        self.assertEqual(labels_for("unknown"), [])

        class _Broken:
            def get_confidence_labels_by_snippet_ids(self, ids, *, strict=False):
                raise RuntimeError("down")

        self.assertIsNone(labels_for_snippets(_Broken(), ["s1"])("s1"))


if __name__ == "__main__":
    unittest.main()
