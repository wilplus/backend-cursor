"""
STORY    As a speaker, I want the moment I open to show the card the
         follow-up rules choose (praise, exercise, coach request or rewrite),
         so that I never see a rewrite where a coach request was due.
OUTCOME
  O1  Each cell of the open matrix gives its card: confident -> praise; weak
      and a problem fired -> exercise (matched) or coach request; weak and
      nothing fired -> rewrite.
  O2  Only that closed set of values is served, nothing about the read.
  O3  A moment is left without a card when its clip cannot be read, and
      the coach request is left out when no coach is on the panel.
  O4  Served Confident Voice moments carry the card; notes do not.
PROVES   O1 -> test_each_matrix_cell_opens_its_card,
               test_open_cards_serves_the_cell_per_moment
         O2 -> test_open_cards_serves_the_cell_per_moment
         O3 -> test_open_cards_serves_the_cell_per_moment,
               test_no_coach_on_the_panel_drops_only_the_coach_request
         O4 -> test_served_moments_carry_the_card_and_notes_do_not
WHY      Founder 2026-10-05, N48.1 Wave 1 step 1: the page guessed its card
         without knowing what fired (AC-9) and showed the rewrite.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services import ideal_text_changes as itc
from services import judgement_follow_up as jf

# snippet id -> (read, fired, has an exercise draw); "boom" cannot be read.
CLIPS = {
    "s1": ("confident", False, False),
    "s2": ("weak", True, True),
    "s3": ("weak", True, False),
    "s4": ("weak", False, False),
    "s5": "boom",
}


def _database():
    return SimpleNamespace(
        get_confident_voice_practice_candidates=lambda ids: [
            {"id": i} for i in ids if i in CLIPS],
        get_snippets_by_session=lambda sid: [],
        get_confident_voice_exercise_assignment=lambda sid, snip: (
            {"id": "x"} if CLIPS[snip][2] else None),
    )


def _read_of(snippet, median, vocabulary):
    clip = CLIPS[snippet["id"]]
    if clip == "boom":
        raise ValueError("unreadable clip")
    read, fired, _ = clip
    return {"read": read, "observed": ["pace"] if fired else []}


def _open_cards(*, coach):
    with patch.object(jf, "_read_of", _read_of), \
         patch("services.confident_voice_practice.coach_on_panel",
               return_value=coach), \
         patch("services.confident_voice_practice.detected_problem_vocabulary",
               return_value=set()):
        return jf.open_cards(_database(), take_session_id="take-1",
                             snippet_ids=[*CLIPS, "gone"])


class DecideAtOpenTests(unittest.TestCase):
    def test_each_matrix_cell_opens_its_card(self):
        self.assertEqual(
            [jf.decide_at_open(read, fired, matched)[0]
             for read, fired, matched in (
                 ("confident", False, False), ("confident", True, True),
                 ("weak", True, True), ("weak", True, False),
                 ("weak", False, True))],
            ["praise", "praise", "exercise", "coach_request", "rewrite"])


class OpenCardsTests(unittest.TestCase):
    def test_open_cards_serves_the_cell_per_moment(self):
        cards = _open_cards(coach=True)
        self.assertEqual(cards, {"s1": "praise", "s2": "exercise",
                                 "s3": "coach_request", "s4": "rewrite"})
        self.assertLessEqual(set(cards.values()), set(jf.OPEN_CARDS))

    def test_no_coach_on_the_panel_drops_only_the_coach_request(self):
        self.assertEqual(_open_cards(coach=False),
                         {"s1": "praise", "s2": "exercise", "s4": "rewrite"})


class ServedRowTests(unittest.TestCase):
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
        run = itc._ChangesRun.__new__(itc._ChangesRun)
        run.changes, run.arm_sid, run.db = rows, "take-1", object()
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


if __name__ == "__main__":
    unittest.main()
