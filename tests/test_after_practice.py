"""Praise after practice, encouragement, Bold voices and the coach's
readings (founder 2026-10-01, F5; Phase 3 of the after-practice paths),
dark behind PRAISE_AFTER_PRACTICE_ENABLED.

Pins: off, nothing is said, written or served; on, one sentence from the
closed set names the targeted problem that cleared, else the one cue that
moved, else that the attempt sounded more assured, else "Good job", about
the attempt the speaker LANDED on; In-between hears the gentler line; a
rewrite practice compares only attempts of the accepted text; a practice
left hears a real step or the effort line; Bold voices serve the own
landed attempt and published coach readings without a name; each step is
shown once per Take; the coach tool refuses what it should.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from services import after_practice as ap
from services import bold_voices as bv
from services import coach_readings as cr

ROOT = Path(__file__).resolve().parents[1]
ON = patch("config.Config.PRAISE_AFTER_PRACTICE_ENABLED", True)


def _attempt(index, *, original=None, attempt=None, snapshot=None, aid=None):
    return {"id": aid or f"a-{index}", "attempt_index": index,
            "acoustic_metrics": snapshot or {},
            "comparison": {"cues": {"original": original or {}, "attempt": attempt or {}}}}


PRACTICE = {"id": "p-1", "owner_user_id": "owner-1", "kind": "exercise",
            "exercise_snapshot": {"matching_criteria": {"primary_problem_tag": "rushing"}},
            "acoustic_evidence": {"signals": {"insufficient_pauses": True},
                                  "snapshot": {"confidence": 0.2}}}


class CueTests(unittest.TestCase):
    def test_gains_follow_the_cue_table_order_and_the_bar(self):
        before = {"pitch_range": 0.0, "loudness_range": -0.2, "pausing": 0.1, "speech_rate": 0.0}
        after = {"pitch_range": 0.4, "loudness_range": 0.4, "pausing": 0.9, "speech_rate": 1.0}
        self.assertEqual(ap.cue_gains(before, after),
                         [("full_volume", 0.6), ("no_hesitation", 0.8), ("kept_moving", 1.0)])
        self.assertEqual(ap.cue_gains(None, after), [])
        self.assertEqual(ap.cue_gains({"pitch_range": True}, {"pitch_range": 2.0}), [])

    def test_cue_reads_need_a_baseline_and_use_the_one_table(self):
        self.assertEqual(ap.cue_reads({"f0_sd": 3.0}, None), {})
        reads = ap.cue_reads({"f0_sd": 3.0, "wpm": 150.0},
                             {"f0_sd": (2.0, 1.0), "wpm": (140.0, 10.0)})
        self.assertEqual(reads, {"pitch_range": 1.0, "speech_rate": 1.0})
        comparison = ap.attach_cue_reads(
            {"x": 1}, original_metrics={"f0_sd": 2.0}, attempt_metrics={"f0_sd": 3.0},
            baseline={"f0_sd": (2.0, 1.0)}, baseline_kind="user")
        self.assertEqual(comparison["cues"]["original"], {"pitch_range": 0.0})
        self.assertEqual(comparison["cues"]["attempt"], {"pitch_range": 1.0})
        self.assertEqual(comparison["cues"]["baseline"], "user")
        self.assertNotIn("cues", ap.attach_cue_reads(
            {}, original_metrics={}, attempt_metrics={}, baseline=None, baseline_kind="none"))


class PraiseTests(unittest.TestCase):
    def test_the_targeted_problem_that_cleared_comes_first(self):
        landed = _attempt(2, snapshot={"pause_ratio": 0.2}, original={"pitch_range": 0},
                          attempt={"pitch_range": 2.0})
        said = ap.praise_after_practice(PRACTICE, [_attempt(1), landed], "a-2", "yes")
        self.assertEqual((said["key"], said["lane"], said["error"], said["attempt_index"]),
                         ("cleared:rushing", "cleared", "rushing", 2))
        self.assertEqual(said["sentence"], ap.PRAISE["cleared:rushing"][0])
        self.assertEqual(said["rule_version"], ap.RULE_VERSION)

    def test_then_the_one_cue_that_moved_then_the_machine_leg_then_good_job(self):
        still_rushing = {"pause_ratio": 0.02}
        landed = _attempt(1, snapshot=still_rushing, original={"pausing": 0.0},
                          attempt={"pausing": 0.7})
        said = ap.praise_after_practice(PRACTICE, [landed], "a-1", "in_between")
        self.assertEqual((said["key"], said["cue"], said["variant"]),
                         ("cue:no_hesitation", "no_hesitation", "in_between"))
        self.assertEqual(said["sentence"], ap.PRAISE["cue:no_hesitation"][1])
        landed = _attempt(1, snapshot={**still_rushing, "confidence": 0.6})
        said = ap.praise_after_practice(PRACTICE, [landed], "a-1", "yes")
        self.assertEqual((said["key"], said["lane"]), ("more_assured", "machine_leg"))
        landed = _attempt(1, snapshot={**still_rushing, "confidence": 0.1})
        said = ap.praise_after_practice(PRACTICE, [landed], "a-1", "yes")
        self.assertEqual((said["key"], said["sentence"]), ("good_job", "Good job."))

    def test_it_describes_the_attempt_the_speaker_landed_on(self):
        first = _attempt(1, snapshot={"pause_ratio": 0.2})
        third = _attempt(3, snapshot={"pause_ratio": 0.01, "confidence": 0.1})
        said = ap.praise_after_practice(PRACTICE, [first, _attempt(2), third], "a-3", "yes")
        self.assertEqual((said["attempt_index"], said["key"]), (3, "good_job"))
        self.assertEqual(ap.praise_after_practice(PRACTICE, [first], "missing", "yes")["key"],
                         "good_job")

    def test_a_rewrite_practice_compares_only_the_accepted_text(self):
        practice = {**PRACTICE, "kind": "rewrite"}
        one = _attempt(1, snapshot={"pause_ratio": 0.5, "confidence": 0.9},
                       original={"pausing": -1.0}, attempt={"pausing": 0.0})
        self.assertEqual(ap.praise_after_practice(practice, [one], "a-1", "yes")["key"],
                         "good_job")
        two = _attempt(2, attempt={"pausing": 0.8})
        said = ap.praise_after_practice(practice, [one, two], "a-2", "yes")
        self.assertEqual((said["key"], said["lane"]), ("cue:no_hesitation", "cue"))

    def test_every_sentence_is_in_the_closed_set_and_carries_no_number(self):
        for key, (yes, gentle) in ap.PRAISE.items():
            for sentence in (yes, gentle):
                self.assertFalse(any(ch.isdigit() for ch in sentence), key)
                self.assertTrue(sentence.endswith("."), key)
        self.assertEqual(set(ap.ENCOURAGEMENT), {"step", "effort"})

    def test_encouragement_is_a_real_step_between_tries_or_the_effort(self):
        rows = [_attempt(1, attempt={"pitch_range": 0.0}), _attempt(2, attempt={"pitch_range": 0.1}),
                _attempt(3, attempt={"pitch_range": 0.9})]
        said = ap.encouragement(rows)
        self.assertEqual((said["key"], said["cue"]), ("step", "wide_range"))
        self.assertEqual(ap.encouragement(rows[:1])["key"], "effort")
        self.assertEqual(ap.encouragement([])["key"], "effort")


class _Db:
    def __init__(self):
        self.updates: list = []
        self.steps: list = []
        self.plays: list = []
        self.readings: list = []

    # Bold voices asks the peer lane for others' clips (on from 2026-10-02,
    # N25; off again from 2026-10-03, N29); this Take has none lent and no corpus.
    def list_shared_clips_live(self):
        return []

    def list_corpus_clips_active(self):
        return []

    def update_confident_voice_practice(self, practice_id, owner, fields):
        self.updates.append((practice_id, owner, fields))
        return {"id": practice_id, **fields}

    def list_confident_voice_practice_attempts(self, _pid):
        return [_attempt(1, aid="a-1", snapshot={"pause_ratio": 0.2})]

    def v2_get_session_by_id(self, sid):
        return {"id": sid, "user_id": "owner-1"} if sid == "take-1" else None

    def list_landed_practices_for_take(self, _take, _owner):
        return [{"id": "p-1", "selected_attempt_id": "a-1", "exact_passage": "the words"}]

    def list_published_coach_readings(self):
        return [{"id": "r-1", "passage": "a line", "media_url": "https://m/r.mp3",
                 "media_kind": "audio", "coach_id": "coach-9"}]

    def list_after_practice_steps(self, _take):
        return [{"step": "bold_voices", "shown_at": "t1"}]

    def mark_after_practice_step(self, **kwargs):
        key = (kwargs["take_session_id"], kwargs["step"])
        if key in self.steps:
            return False
        self.steps.append(key)
        return True

    def record_bold_voices_play(self, **kwargs):
        self.plays.append(kwargs)
        return {"id": "play-1"}

    def list_coach_readings(self, coach_id):
        return [r for r in self.readings if r["coach_id"] == coach_id]

    def insert_coach_reading(self, row):
        self.readings.append({"id": f"r-{len(self.readings) + 1}", "published_at": None, **row})
        return self.readings[-1]

    def set_coach_reading_published(self, *, reading_id, coach_id, published):
        row = next((r for r in self.readings if r["id"] == reading_id and r["coach_id"] == coach_id), None)
        if row:
            row["published_at"] = "now" if published else None
        return row

    def count_after_practice(self, since):
        return {"practices_landed": 2, "bold_voices_heard": 1,
                "steps": {"bridge": 0, "lend_your_ear": 0, "bold_voices": 1}}


class OffTests(unittest.TestCase):
    """The off behaviour, under the switch patched off (the live default is
    off again since 2026-10-05: no screen renders any of it)."""
    def setUp(self):
        self._off = patch("config.Config.PRAISE_AFTER_PRACTICE_ENABLED", False)
        self._off.start()
        self.addCleanup(self._off.stop)

    def test_the_switch_is_off_until_a_screen_ships(self):
        self._off.stop()
        from config import Config as _live
        self.assertFalse(_live.PRAISE_AFTER_PRACTICE_ENABLED)
        self._off.start()

    def test_off_nothing_is_said_written_or_served(self):
        db = _Db()
        self.assertIsNone(ap.after_landing(db, PRACTICE, [_attempt(1)], "a-1", "yes"))
        self.assertIsNone(ap.after_dismissal(db, PRACTICE))
        self.assertEqual(db.updates, [])
        self.assertEqual(cr.list_readings(db, coach_id="c")[0], 404)
        self.assertEqual(cr.create_reading(db, coach_id="c", passage="x", media_file=None,
                                           media_kind="audio", max_mb=1)[0], 404)


@ON
class OnTests(unittest.TestCase):
    def test_the_landing_keeps_the_sentence_on_the_practice(self):
        db = _Db()
        said = ap.after_landing(db, PRACTICE, [_attempt(1, snapshot={"pause_ratio": 0.2})], "a-1", "yes")
        self.assertEqual(said["key"], "cleared:rushing")
        self.assertEqual(db.updates[0][2], {"after_practice": said})
        self.assertEqual(db.updates[0][:2], ("p-1", "owner-1"))

    def test_the_dismissal_keeps_the_encouragement(self):
        db = _Db()
        said = ap.after_dismissal(db, PRACTICE)
        self.assertEqual(said["key"], "effort")
        self.assertEqual(db.updates[0][2]["after_practice"]["sentence"], ap.ENCOURAGEMENT["effort"])

    def test_a_failed_write_never_costs_the_judgement(self):
        class _Down(_Db):
            def update_confident_voice_practice(self, *_a):
                raise RuntimeError("down")
        self.assertIsNone(ap.after_landing(_Down(), PRACTICE, [_attempt(1)], "a-1", "yes"))

    def test_bold_voices_are_retired_whatever_the_switch_says(self):
        # Q-B11 A (founder 2026-10-07, N62): "The Album share switch and
        # Bold voices are retired." No service door, and the three routes
        # answer 404 before any read, with the switch on.
        from flask import Flask, request
        import routes.v2.after_practice as route
        for door in ("bold_voices_for_take", "mark_step", "record_heard", "STEPS", "CLIP_KINDS"):
            self.assertFalse(hasattr(bv, door), door)
        source = (ROOT / "routes/v2/after_practice.py").read_text()
        routes_ = {
            "v2_bold_voices": ("/user/takes/<take_session_id>/bold-voices", "GET"),
            "v2_after_practice_step": ("/user/takes/<take_session_id>/after-practice-step", "POST"),
            "v2_bold_voices_heard": ("/user/takes/<take_session_id>/bold-voices/heard", "POST"),
        }
        self.assertEqual(source.count("@v2_bp.route("), len(routes_))
        self.assertNotIn("services.db", source)
        app = Flask(__name__)
        for name, (path, method) in routes_.items():
            self.assertIn(f'@v2_bp.route("{path}", methods=["{method}"])', source)
            with app.test_request_context("/v2/x", method=method,
                                          json={"step": "bold_voices", "clip_kind": "own_attempt",
                                                "clip_id": "a-1"}):
                request.user_id = "owner-1"
                response, status = getattr(route, name).__wrapped__("take-1")
            self.assertEqual(status, 404, name)
            self.assertEqual(response.get_json()["code"], "NOT_FOUND", name)
        # The ledger's count stays (never a speaker-facing number).
        db = _Db()
        self.assertEqual(bv.after_practice_counts(db, since="t0")["since"], "t0")

    def test_the_coach_tool_records_and_publishes_a_reading(self):
        class _File:
            filename = "reading.mp3"
            content_type = "audio/mpeg"

            def read(self):
                return b"abc"
        db = _Db()
        with patch("services.journal_media.put_object_bytes",
                   return_value={"public_url": "https://m/x.mp3", "key": "k"}):
            status, payload = cr.create_reading(
                db, coach_id="coach-1", passage=" Say it whole. ", media_file=_File(),
                media_kind="audio", max_mb=10)
        self.assertEqual(status, 201)
        self.assertEqual(payload["reading"]["passage"], "Say it whole.")
        self.assertIsNone(payload["reading"]["published_at"])
        self.assertEqual(cr.publish_reading(db, coach_id="coach-1", reading_id="r-1",
                                            published=True)[1]["reading"]["published_at"], "now")
        self.assertEqual(cr.publish_reading(db, coach_id="coach-2", reading_id="r-1",
                                            published=True)[0], 404)
        self.assertEqual(cr.list_readings(db, coach_id="coach-1")[1]["readings"][0]["id"], "r-1")

    def test_the_coach_tool_refuses_what_it_should(self):
        class _Big:
            filename = "reading.wav"
            content_type = "audio/wav"

            def read(self):
                return b"x" * (2 * 1024 * 1024)

        class _Wrong:
            filename = "reading.txt"
            content_type = "text/plain"

            def read(self):
                return b"x"
        db = _Db()
        self.assertEqual(cr.create_reading(db, coach_id="c", passage="", media_file=_Big(),
                                           media_kind="audio", max_mb=1)[0], 400)
        self.assertEqual(cr.create_reading(db, coach_id="c", passage="x", media_file=None,
                                           media_kind="audio", max_mb=1)[0], 400)
        self.assertEqual(cr.create_reading(db, coach_id="c", passage="x", media_file=_Wrong(),
                                           media_kind="audio", max_mb=1)[0], 415)
        self.assertEqual(cr.create_reading(db, coach_id="c", passage="x", media_file=_Big(),
                                           media_kind="audio", max_mb=1)[0], 413)
        self.assertEqual(cr.publish_reading(db, coach_id="c", reading_id="r", published="yes")[0], 400)
        self.assertEqual(db.readings, [])

    def test_the_ledger_counts_ride_the_window(self):
        self.assertEqual(bv.after_practice_counts(_Db(), since="s")["practices_landed"], 2)


class WiringTests(unittest.TestCase):
    def test_the_judgement_the_dismissal_and_the_attempt_ask_the_rule(self):
        adoption = (ROOT / "services/practice_adoption.py").read_text()
        self.assertIn("after_landing(database, result[\"practice_row\"], attempts,", adoption)
        routes = (ROOT / "routes/v2/user_sessions.py").read_text()
        self.assertIn("_practice_user_payload(_dismissed(updated))", routes)
        self.assertIn("comparison = _attempt_comparison(", routes)
        self.assertIn('"after_practice": _after_practice_public(practice.get("after_practice"))', routes)
        self.assertIn('"after_practice": after', (ROOT / "services/learning_ledger.py").read_text())

    def test_the_contract_the_config_the_migration_and_the_routes_record_f5(self):
        self.assertIn("29c. **After the practice**",
                      (ROOT / "docs/CANONICAL_PRODUCT_CONTRACT.md").read_text())
        self.assertIn("PRAISE_AFTER_PRACTICE_ENABLED = False", (ROOT / "config.py").read_text())
        sql = (ROOT / "migrations/a_practice_hears_what_changed.sql").read_text()
        for needle in ("ADD COLUMN IF NOT EXISTS after_practice",
                       "CREATE TABLE IF NOT EXISTS public.coach_readings",
                       "CREATE TABLE IF NOT EXISTS public.after_practice_steps",
                       "CREATE TABLE IF NOT EXISTS public.bold_voices_plays"):
            self.assertIn(needle, sql)
        self.assertIn("a_practice_hears_what_changed.sql",
                      (ROOT / "migrations/manifest.txt").read_text())
        modules = (ROOT / "routes/v2/__init__.py").read_text()
        self.assertIn('"coach_readings", "after_practice"', modules)
        from services.data_purge_registry import DEPENDENCIES
        by = {d.relation: (d.selector_column, d.locator_kind) for d in DEPENDENCIES}
        self.assertEqual(by["after_practice_steps"], ("take_session_id", "take"))
        self.assertEqual(by["bold_voices_plays"], ("take_session_id", "take"))
        self.assertEqual(by["coach_readings"], ("coach_id", "user"))

    def test_no_scorer_reads_the_sentence(self):
        for name in ("services/exercise_adequacy_labels.py", "services/exercise_fair_test.py",
                     "services/exercise_evaluation.py", "services/practice_more_confident.py"):
            self.assertNotIn("after_practice", (ROOT / name).read_text(), name)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
