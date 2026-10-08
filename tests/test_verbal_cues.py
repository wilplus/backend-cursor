"""Spoken-word cues in the shadow stage (founder 2026-09-28, D2 + D3).

Pins:
  * each cue fires on what its written definition says, and ambiguous words
    never count;
  * a clip that cannot be measured honestly (not English, no words) gets no
    verdict at all — never a false "absent";
  * a Take logs one row per (clip, cue) under the current version, only with
    the speaker's personalised-practice yes, and a failed write never touches
    processing;
  * shadow cues route nothing: the matcher, the catalogue and the library's
    authoring form all treat `shadow` as not detected;
  * the thresholds and lexicons are versioned;
  * the coach comparison reports what it can know and says what it can't.
"""
from __future__ import annotations

import hashlib
import inspect
import json
import pathlib
import unittest
from unittest import mock

from services import verbal_cue_validation as validation
from services import verbal_cues as vc

ROOT = pathlib.Path(__file__).resolve().parent.parent


class MeasureTests(unittest.TestCase):
    def _fired(self, text, language="en"):
        out = vc.measure(text, language)
        return {cue: out[cue]["fired"] for cue in vc.CUES} if out else None

    def test_a_filler_cluster_needs_two_and_a_rate(self):
        self.assertTrue(self._fired("Um, uh, the plan is ready.")["filler_cluster"])
        # One is not a cluster.
        self.assertFalse(self._fired("Um, the plan is ready.")["filler_cluster"])
        # Two spread over a long passage fall under 5 per 100 words.
        long = "um " + "word " * 60 + "uh"
        self.assertFalse(self._fired(long)["filler_cluster"])

    def test_words_that_are_sometimes_fillers_never_count(self):
        out = vc.measure("So, like, you know, it works, like, so well.", "en")
        self.assertEqual(out["filler_cluster"]["measurements"]["count"], 0)

    def test_hedging_counts_only_unambiguous_hedges(self):
        self.assertTrue(self._fired("I think this is maybe right.")["hedging"])
        out = vc.measure("We might could quite rather about.", "en")
        self.assertFalse(out["hedging"]["fired"])
        self.assertEqual(out["hedging"]["measurements"]["count"], 0)
        self.assertGreater(
            out["hedging"]["measurements"]["ambiguous_not_counted"], 0)

    def test_restarts_are_immediate_repeats(self):
        self.assertTrue(self._fired("We we saw the the growth.")["restart_repair"])
        self.assertFalse(self._fired("We saw the growth, we did.")["restart_repair"])

    def test_a_clip_that_cannot_be_measured_gets_no_verdict(self):
        for text, language in (("Yyy, eee, no no.", "pl"), ("Um uh", None),
                               ("", "en"), (None, "en"), ("...", "en")):
            self.assertIsNone(vc.measure(text, language), (text, language))

    def test_the_verbal_cue_rules_are_versioned(self):
        """A change to a threshold, the hedge lexicon, the hesitation tokens
        or the repeat pattern changes what every future verdict means. Bump
        VERBAL_CUES_VERSION, then update this fingerprint."""
        from services import transcript_smoothing as ts
        from services import verbal_markers as vm
        source = (inspect.getsource(vc.measure)
                  + json.dumps([vc.SUPPORTED_LANGUAGES, vc.FILLER_MIN_COUNT,
                                vc.FILLER_MIN_PER_100_WORDS,
                                vc.HEDGE_MIN_COUNT, vc.RESTART_MIN_COUNT])
                  + json.dumps(vm.LEXICONS["en"]["hedge"], sort_keys=True)
                  + json.dumps(ts.HESITATIONS["en"]) + ts._REPEAT_RE.pattern)
        self.assertEqual(
            (vc.VERBAL_CUES_VERSION,
             hashlib.sha256(source.encode()).hexdigest()),
            ("verbal-cues-v1",
             "84ab07ab3f4043e6a87b0ee8b912e1e8464a38c9fa0f2e9a505262ca500f1123"))


class _Db:
    def __init__(self, snippets, languages, fail=False):
        self.snippets = snippets
        self.languages = languages
        self.fail = fail
        self.written = []

    def get_snippets_by_session(self, _take):
        return self.snippets

    def get_recording(self, recording_id):
        return {"transcription_language": self.languages.get(recording_id)}

    def record_verbal_cue_shadow(self, rows):
        if self.fail:
            raise RuntimeError("function does not exist")
        self.written.extend(rows)
        return len(rows)


def _permitted(value=True):
    return mock.patch.object(vc, "_practice_permitted", return_value=value)


class RecordTakeTests(unittest.TestCase):
    def _db(self, **kw):
        return _Db([
            {"id": "s1", "recording_id": "r1", "transcript": "Um, uh, we we go."},
            {"id": "s2", "recording_id": "r1", "transcript": "Growth was strong."},
            {"id": "s3", "recording_id": "r2", "transcript": "Yyy, no no."},
        ], {"r1": "en", "r2": "pl"}, **kw)

    def test_one_row_per_measurable_clip_and_cue(self):
        db = self._db()
        with _permitted():
            self.assertEqual(vc.record_take(db, "take-1"), 6)
        self.assertEqual({(r["snippet_id"], r["error_id"]) for r in db.written},
                         {(s, c) for s in ("s1", "s2") for c in vc.CUES})
        first = next(r for r in db.written
                     if r["snippet_id"] == "s1" and r["error_id"] == "filler_cluster")
        self.assertTrue(first["fired"])
        self.assertEqual(first["detector_version"], vc.VERBAL_CUES_VERSION)
        self.assertEqual(first["language"], "en")
        self.assertEqual(first["take_session_id"], "take-1")

    def test_no_transcript_text_is_logged(self):
        db = self._db()
        with _permitted():
            vc.record_take(db, "take-1")
        self.assertNotIn("we we go", json.dumps(db.written))

    def test_without_the_speaker_s_yes_nothing_is_measured(self):
        db = self._db()
        with _permitted(False):
            self.assertEqual(vc.record_take(db, "take-1"), 0)
        self.assertEqual(db.written, [])

    def test_the_pipeline_runs_it_best_effort(self):
        source = (ROOT / "services/analysis_worker.py").read_text()
        self.assertIn('_deg.run("verbal_cue_shadow", _verbal_cue_shadow)', source)
        # Beside the session-globals step, outside the Ideal Text try that
        # turns an error into a failed Take.
        self.assertLess(source.index('_deg.run("session_globals"'),
                        source.index('_deg.run("verbal_cue_shadow"'))
        self.assertLess(source.index('_deg.run("verbal_cue_shadow"'),
                        source.index('_emit(progress, "ideal_text"'))


class ShadowRoutesNothingTests(unittest.TestCase):
    class _Library:
        def __init__(self, rows):
            self.rows = rows

        def list_speaking_errors(self):
            return self.rows

        def get_speaking_error(self, error_id):
            return next((r for r in self.rows if r["error_id"] == error_id), None)

        def upsert_diagnostic_exercise(self, row):
            return row

        def upsert_speaking_error(self, row):
            return row

    _ROWS = [{"error_id": "rushing", "status": "detected"},
             {"error_id": "hedging", "status": "shadow"}]

    def test_the_matcher_does_not_see_a_shadow_cue(self):
        from services import confident_voice_practice as cvp
        self.assertEqual(cvp.detected_problem_vocabulary(self._Library(self._ROWS)),
                         frozenset({"rushing"}))

    def test_an_exercise_cannot_be_tagged_with_a_shadow_cue(self):
        from services import diagnostic_exercise_catalogue as cat
        with self.assertRaises(cat.CatalogueRefusal) as ctx:
            cat.save_exercise(self._Library(self._ROWS), {
                "exercise_id": "soften-less", "title": "Say it plainly",
                "explanation_video_url": "https://x/v.mp4",
                "acoustic_problem_tags": ["hedging"], "active": False})
        self.assertEqual(ctx.exception.code, "TAG_NOT_DETECTED")

    def test_the_authoring_form_cannot_demote_a_shadow_cue(self):
        from services import speaking_error_library as lib
        with self.assertRaises(lib.LibraryRefusal) as ctx:
            lib.save_observed_error(self._Library(self._ROWS), {
                "error_id": "hedging", "label": "Hedging",
                "definition": "x", "asks": "y"})
        self.assertEqual(ctx.exception.code, "ALREADY_IN_SHADOW")


def _answers(yes_fired: int, yes_quiet: int, *, no: int = 0, version="verbal-cues-v1",
             probability=0.5):
    """Blind audit rows for one cue: Yes on clips the detector fired on,
    Yes on clips it stayed quiet on, and some No answers."""
    rows = [{"answer": "yes", "fired_at_sampling": True, "detector_version": version,
             "sampling_probability": probability} for _ in range(yes_fired)]
    rows += [{"answer": "yes", "fired_at_sampling": False, "detector_version": version,
              "sampling_probability": probability} for _ in range(yes_quiet)]
    rows += [{"answer": "no", "fired_at_sampling": True, "detector_version": version,
              "sampling_probability": probability} for _ in range(no)]
    return rows


class ValidationTests(unittest.TestCase):
    _OBS = [{"snippet_id": "a", "fired": True}, {"snippet_id": "b", "fired": False},
            {"snippet_id": "c", "fired": True}, {"snippet_id": "d", "fired": False}]

    def test_caught_is_measured_against_the_coaches_yes_in_the_blind_audit(self):
        """N48.5 Q24 A (founder 2026-10-05): "coaches' Yes answers in the
        blind error audit are what promote a shadow cue"."""
        summary = validation.summarise(
            self._OBS, [{"snippet_id": "a"}], _answers(3, 1, no=2),
            detector_version="verbal-cues-v1")
        self.assertEqual(summary["clips_measured"], 4)
        self.assertEqual(summary["fire_rate"], 0.5)
        self.assertEqual((summary["audit_yes"], summary["audit_no"]), (4, 2))
        self.assertEqual(summary["caught"], 3)
        self.assertEqual(summary["caught_rate"], 0.75)
        # The moments a coach once named are history, never the bar.
        self.assertEqual(summary["coach_named_measured"], 1)

    def test_the_catch_rate_is_weighted_by_sampling_probability(self):
        # Fired clips are oversampled (p=1.0), quiet ones undersampled
        # (p=0.25): 4 caught and 1 missed raw, but the missed one stands for
        # four clips, so half the present errors were caught.
        rows = _answers(4, 0, probability=1.0) + _answers(0, 1, probability=0.25)
        summary = validation.audit_summary(rows)
        self.assertEqual(summary["caught_rate"], 0.5)

    def test_answers_under_another_detector_version_do_not_count(self):
        rows = _answers(30, 0, version="verbal-cues-v2")
        summary = validation.audit_summary(rows, detector_version="verbal-cues-v1")
        self.assertEqual(summary["audit_yes"], 0)

    def test_false_alarms_are_reported_unknown_not_guessed(self):
        summary = validation.summarise(self._OBS, [])
        self.assertIsNone(summary["false_alarm_rate"])
        self.assertIn("audit", summary["false_alarm_note"])
        self.assertIsNone(summary["caught_rate"])

    def test_the_bar_is_the_founder_s(self):
        # D3a (2026-09-28) as amended by Q24 A (2026-10-05): 30 coaches' Yes
        # answers in the blind audit, 80% of them caught.
        self.assertEqual((validation.PROMOTION_MIN_YES,
                          validation.PROMOTION_MIN_CAUGHT_RATE), (30, 0.8))
        self.assertFalse(hasattr(validation, "PROMOTION_MIN_NAMED"))
        summary = validation.summarise([], [], _answers(24, 6))
        self.assertEqual(validation.meets_bar(
            summary, min_yes=validation.PROMOTION_MIN_YES,
            min_caught_rate=validation.PROMOTION_MIN_CAUGHT_RATE), (True, None))
        summary = validation.summarise([], [], _answers(23, 7))
        self.assertFalse(validation.meets_bar(
            summary, min_yes=validation.PROMOTION_MIN_YES,
            min_caught_rate=validation.PROMOTION_MIN_CAUGHT_RATE)[0])
        # Named moments, however many, never clear it.
        summary = validation.summarise(
            [{"snippet_id": str(i), "fired": True} for i in range(40)],
            [{"snippet_id": str(i)} for i in range(40)], _answers(2, 0))
        self.assertFalse(validation.meets_bar(
            summary, min_yes=30, min_caught_rate=0.8)[0])

    def test_a_cue_the_audit_does_not_sample_is_never_ready(self):
        summary = validation.summarise([], [], _answers(40, 0), audited=False)
        ok, why = validation.meets_bar(summary, min_yes=30, min_caught_rate=0.8)
        self.assertFalse(ok)
        self.assertIn("not in the blind error audit", why)

    def test_the_bar_is_never_a_silent_default(self):
        summary = validation.summarise(self._OBS, [], _answers(1, 0))
        self.assertEqual(validation.meets_bar(
            summary, min_yes=1, min_caught_rate=0.8), (True, None))
        ok, why = validation.meets_bar(summary, min_yes=30,
                                       min_caught_rate=0.8)
        self.assertFalse(ok)
        self.assertIn("30", why)
        signature = inspect.signature(validation.meets_bar)
        for name in ("min_yes", "min_caught_rate"):
            self.assertIs(signature.parameters[name].default,
                          inspect.Parameter.empty)

    def test_the_report_reads_the_audit_only_for_audited_cues(self):
        class _Db:
            asked: list = []

            def list_verbal_cue_shadow_observations(self, cue, version):
                return []

            def list_coach_named_moments(self, cue):
                return []

            def list_error_presence_audit_answered(self, cue):
                self.asked.append(cue)
                return _answers(1, 0)

        db = _Db()
        with mock.patch("services.error_presence_audit.false_alarm_rate", return_value=None), \
                mock.patch("services.error_presence_audit.errors_in_scope",
                      return_value=("rushing", "hedging")):
            out = validation.report(db, detector_version="verbal-cues-v1",
                                    cues=("hedging", "low_volume"))
        self.assertEqual(db.asked, ["hedging"])
        self.assertEqual(out["hedging"]["audit_yes"], 1)
        self.assertFalse(out["low_volume"]["audited"])
        self.assertEqual(out["low_volume"]["audit_yes"], 0)
