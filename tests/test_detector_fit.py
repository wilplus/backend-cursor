"""
STORY    As the founder, I want the learned detector trained only on blind
         answers from consenting speakers, with its verdicts going only to a
         shadow log, so that no speaker sees an untested detector and no data
         is used without a yes.
OUTCOME
  O1  Switch off: the weekly step reads and writes nothing, and a direct fit
      is refused.
  O2  Switch on: only answers from speakers who hold the training yes, have
      not objected and sit in the train split are fitted; a speaker who
      withdraws drops out at the next fit; the fit is order-independent.
  O3  Verdicts go to the shadow log once, under the fit's own version, for
      consented speakers' clips only; the live detector is unchanged.
PROVES   O1 -> test_switch_off_reads_and_writes_nothing
         O2 -> test_only_consented_train_split_answers_are_fitted
         O3 -> test_verdicts_go_to_the_shadow_log_only_for_consented_clips
WHY      3.5 pack, file 22 E3; document 02 v1.2 §3c (dark lane, PLF1 Phase 2).
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from services import detector_candidates as dc
from services import detector_rollout as dr

NOW = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
ON = patch("config.Config.DETECTOR_TRAINING_AUTHORISED", True, create=True)


class _On:
    DETECTOR_TRAINING_AUTHORISED = True


def _answers(take: str, speaker: str, *, n: int = 35, inverted: bool = False) -> list[dict]:
    """n Yes answers on rushed clips (low pause ratio) and n No answers on
    calm ones, for one speaker's Take; inverted swaps the answers."""
    rows = []
    for i in range(n):
        for said_yes, pause in ((True, 0.02 + i * 0.001), (False, 0.20 + i * 0.002)):
            answer = said_yes != inverted
            rows.append({"clip_id": f"{take}-{'r' if said_yes else 'c'}{i}", "coach_id": "coach",
                         "take_session_id": take, "speaker_user_id": speaker,
                         "error_id": "rushing", "answer": "yes" if answer else "no",
                         "measurements": {"pause_ratio": pause, "wpm": 150 + i},
                         "sampling_probability": 0.5})
    return rows


class _Db:
    def __init__(self, answers, clips=()):
        self.answers = list(answers)
        self.clips = list(clips)
        self.shadow: list[dict] = []

    def list_error_presence_audit_answered_all(self):
        return list(self.answers)

    def list_clips_for_rescore(self, *, since, limit=2000):
        return list(self.clips)

    def record_verbal_cue_shadow(self, rows):
        new = [r for r in rows if (r["snippet_id"], r["error_id"], r["detector_version"]) not in
               {(s["snippet_id"], s["error_id"], s["detector_version"]) for s in self.shadow}]
        self.shadow.extend(new)
        return len(new)


def _consent(yes: set, objected: set = frozenset()):
    """Patches: the training yes per Take, the objection per Take, and a
    split that keeps every speaker in train unless named 'h-'."""
    return (patch("services.pair_consent.take_holds_training_yes",
                  side_effect=lambda db, take: str(take) in yes),
            patch("services.error_presence_audit._objected",
                  side_effect=lambda db, take: str(take) in objected),
            patch("services.exercise_fair_test.split_of",
                  side_effect=lambda s: "holdout" if s.startswith("h-") else "train"))


class _Off:
    DETECTOR_TRAINING_AUTHORISED = False


class _UnreadableDb(_Db):
    """Any read or write here means the off switch leaked."""

    def list_error_presence_audit_answered_all(self):
        raise AssertionError("read while off")

    def list_clips_for_rescore(self, *, since, limit=2000):
        raise AssertionError("read while off")

    def record_verbal_cue_shadow(self, rows):
        raise AssertionError("wrote while off")


class FitTests(unittest.TestCase):
    def _fit(self, db, yes, objected=frozenset()):
        a, b, c = _consent(yes, objected)
        with ON, a, b, c:
            return dc.fit_all(db, config=_On, now=NOW)

    def test_switch_off_reads_and_writes_nothing(self):
        db = _UnreadableDb(_answers("tA", "a"))
        with patch("config.Config.DETECTOR_TRAINING_AUTHORISED", False, create=True):
            self.assertEqual(dc.fit_all(db, config=_Off, now=NOW),
                             {"skipped": "DETECTOR_TRAINING_AUTHORISED is off"})
            # The process switch alone also closes the door.
            self.assertIn("skipped", dc.fit_all(db, config=_On, now=NOW))
            with self.assertRaises(dc.NotAuthorised):
                dc.LearnedDetector("rushing").fit(_answers("tA", "a"))

    def test_only_consented_train_split_answers_are_fitted(self):
        # tA consents; the others would invert the answers if they leaked in.
        answers = (_answers("tA", "a")
                   + _answers("tB", "b", inverted=True)            # no training yes
                   + _answers("tC", "c", inverted=True)            # objected
                   + _answers("tD", "h-d", inverted=True))         # held-out speaker
        yes = {"tA", "tC", "tD"}
        fit = self._fit(_Db(answers), yes, objected={"tC"})["fits"]["rushing"]
        self.assertTrue(fit["fitted"])
        self.assertEqual((fit["n_yes"], fit["n_no"]), (35, 35))
        # Same answers in another order: same fit.
        again = self._fit(_Db(list(reversed(answers))), yes, objected={"tC"})
        self.assertEqual(again["fits"]["rushing"]["fit_version"], fit["fit_version"])
        # tA withdraws: nothing is left to fit on.
        withdrawn = self._fit(_Db(answers), {"tD"})["fits"]["rushing"]
        self.assertEqual((withdrawn["n_yes"], withdrawn["n_no"]), (0, 0))
        self.assertFalse(withdrawn["fitted"])

    def test_verdicts_go_to_the_shadow_log_only_for_consented_clips(self):
        clips = [{"clip_id": "s1", "take_session_id": "tA", "clip_kind": "snippet",
                  "snapshot": {"pause_ratio": 0.03}},
                 {"clip_id": "s2", "take_session_id": "tA", "clip_kind": "snippet",
                  "snapshot": {"pause_ratio": 0.4}},
                 {"clip_id": "s3", "take_session_id": "tB", "clip_kind": "snippet",
                  "snapshot": {"pause_ratio": 0.03}},
                 {"clip_id": "s4", "take_session_id": "tA", "clip_kind": "snippet",
                  "snapshot": {}}]
        db = _Db(_answers("tA", "a"), clips)
        live_before = dict(dr.LIVE_DETECTOR)
        out = self._fit(db, yes={"tA"})
        version = out["fits"]["rushing"]["fit_version"]
        self.assertEqual(out["shadow_written"], 2)
        self.assertEqual({(r["snippet_id"], r["fired"]) for r in db.shadow}, {("s1", True), ("s2", False)})
        self.assertEqual({r["detector_version"] for r in db.shadow}, {version})
        self.assertTrue(all("serves_user" not in r for r in db.shadow))
        # Insert-once: the same fit again writes nothing new.
        self.assertEqual(self._fit(db, yes={"tA"})["shadow_written"], 0)
        self.assertEqual(dr.LIVE_DETECTOR, live_before)
        self.assertNotIn(version, dr.REGISTRY)
        # A serving process holds no fit: the registered candidate stays quiet.
        self.assertIsNone(dc.learned("rushing", {"pause_ratio": 0.03}))


if __name__ == "__main__":
    unittest.main()
