"""The learned detector's fit (3.5 pack, file 22 E3; document 02 v1.2 §3c).

Pins:
  * off (DETECTOR_TRAINING_AUTHORISED False): the weekly step reads and
    writes nothing, and ``fit`` refuses;
  * on: only the blind answers of speakers who hold the training yes and
    have not objected are fitted, from the fair test's train split only;
  * a speaker who withdrew drops out at the next fit;
  * the fit is deterministic (same answers in any order: same cut-off, same
    version), and its verdicts reach the shadow log only, under the fit's
    own version, for consented speakers' clips; the live detector is
    unchanged.
"""
from __future__ import annotations

import random
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from services import detector_candidates as dc
from services import detector_rollout as dr
from services import learning_weekly as lw

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


class _Untouchable:
    def __getattr__(self, name):
        raise AssertionError(f"the off switch read {name}")


def _consent(yes: set, objected: set = frozenset()):
    """Patches: the training yes per Take, the objection per Take, and a
    split that keeps every speaker in train unless named 'h-'."""
    return (patch("services.pair_consent.take_holds_training_yes",
                  side_effect=lambda db, take: str(take) in yes),
            patch("services.error_presence_audit._objected",
                  side_effect=lambda db, take: str(take) in objected),
            patch("services.exercise_fair_test.split_of",
                  side_effect=lambda s: "holdout" if s.startswith("h-") else "train"))


class OffTests(unittest.TestCase):
    def test_off_reads_and_writes_nothing(self):
        with patch("config.Config.DETECTOR_TRAINING_AUTHORISED", False, create=True):
            self.assertEqual(dc.fit_all(_Untouchable(), config=_On, now=NOW),
                             {"skipped": "DETECTOR_TRAINING_AUTHORISED is off"})
            with self.assertRaises(dc.NotAuthorised):
                dc.LearnedDetector("rushing").fit(_answers("t", "a"))
        with ON:
            # The job's own config off is enough to stop it.
            self.assertIn("skipped", dc.fit_all(_Untouchable(), config=object(), now=NOW))

    def test_the_weekly_job_skips_it_while_off(self):
        class _Weekly:
            rows: dict = {}

            def upsert_ledger_snapshot(self, **row):
                return row
        with patch("services.learning_ledger.ledger", return_value={"ledger_version": "x"}):
            report = lw.run_weekly(_Weekly(), config=object(), now=NOW)
        self.assertEqual(report["detector_fit"], {"skipped": "DETECTOR_TRAINING_AUTHORISED is off"})


class FitTests(unittest.TestCase):
    def _fit(self, db, yes, objected=frozenset()):
        a, b, c = _consent(yes, objected)
        with ON, a, b, c:
            return dc.fit_all(db, config=_On, now=NOW)

    def test_fits_only_consented_speakers_answers(self):
        answers = (_answers("tA", "a") + _answers("tB", "b", inverted=True)
                   + _answers("tC", "c", inverted=True) + _answers("tH", "h-1", inverted=True))
        # B has no yes, C objected, H is a held-out speaker.
        out = self._fit(_Db(answers), yes={"tA", "tC", "tH"}, objected={"tC"})
        rushing = out["fits"]["rushing"]
        self.assertTrue(rushing["fitted"])
        self.assertEqual((rushing["n_yes"], rushing["n_no"]), (35, 35))
        self.assertEqual(rushing["model"]["feature"], "pause_ratio")
        self.assertEqual(rushing["model"]["direction"], "lt")
        self.assertTrue(0.054 < rushing["model"]["cut"] < 0.20)
        self.assertEqual(rushing["balanced_accuracy"], 1.0)
        self.assertTrue(rushing["fit_version"].startswith(dc.LEARNED_VERSION + "+"))
        # No answers for the other errors: nothing fitted, said in words.
        self.assertEqual(out["fits"]["ending_compression"]["why"], "not enough answers yet")

    def test_a_withdrawn_speaker_drops_out_at_the_next_fit(self):
        answers = _answers("tA", "a")
        self.assertTrue(self._fit(_Db(answers), yes={"tA"})["fits"]["rushing"]["fitted"])
        after = self._fit(_Db(answers), yes=set())["fits"]["rushing"]
        self.assertFalse(after["fitted"])
        self.assertEqual((after["n_yes"], after["n_no"]), (0, 0))

    def test_cant_tell_and_too_few_answers_fit_nothing(self):
        rows = _answers("tA", "a", n=29) + [{**_answers("tA", "a", n=1)[0], "answer": "cant_tell",
                                             "clip_id": "x"}]
        with ON:
            out = dc.LearnedDetector("rushing").fit(rows)
        self.assertEqual((out["fitted"], out["n_yes"], out["n_no"]), (False, 29, 29))

    def test_the_fit_is_deterministic(self):
        rows = _answers("tA", "a") + _answers("tB", "b")
        shuffled = list(rows)
        random.Random(7).shuffle(shuffled)
        with ON:
            first = dc.LearnedDetector("rushing").fit(rows)
            second = dc.LearnedDetector("rushing").fit(shuffled)
            again = dc.LearnedDetector("rushing").fit(rows)
        self.assertEqual(first, second)
        self.assertEqual(first, again)
        with ON:
            changed = dc.LearnedDetector("rushing").fit(rows[:-1])
        self.assertNotEqual(changed["fit_version"], first["fit_version"])

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

    def test_the_weekly_job_runs_the_fit_when_authorised(self):
        class _Weekly(_Db):
            def upsert_ledger_snapshot(self, **row):
                self.row = row
                return row
        db = _Weekly(_answers("tA", "a"))
        a, b, c = _consent({"tA"})
        with ON, a, b, c, patch("services.learning_ledger.ledger", return_value={"ledger_version": "x"}):
            report = lw.run_weekly(db, config=_On, now=NOW)
        self.assertTrue(report["detector_fit"]["fits"]["rushing"]["fitted"])
        self.assertEqual(db.row["snapshot"]["doors_pass"]["detector_fit"], report["detector_fit"])


if __name__ == "__main__":
    unittest.main()
