"""willab — training-audio import (founder 2026-07-28).

services/training_import.py: bulk audio in, coach-reviewable pieces out,
without minting a project the speaker owns.

WHAT THIS PINS DOWN — the isolation, which is the whole feature:
  * source='training_import', NOT 'audit_upload'. Every user-facing list and
    every per-speaker BASELINE reader filters audit_upload, so this one value
    is what keeps a fifty-voice corpus out of one speaker's acoustic norm. A
    regression here corrupts every read that speaker gets afterwards, silently;
  * imports still get their own arc (every coach surface is arc-scoped — an
    arc-less import would be analysed and then invisible);
  * provenance is written (recording_origin='admin_import' + source_metadata)
    and degrades on a pre-migration DB instead of losing the import;
  * the min-content gate still guards the corpus;
  * a failure returns a reason, never raises — one bad file must not abort a
    batch.

Run: python3 -m unittest test_training_import
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock

_ORIG = {}


def setUpModule():
    # Stub the storage + heavy deps so the module imports and runs without a
    # live bucket, Whisper, or ffmpeg.
    for name in ("services.db", "services.coach_video_storage",
                 "services.min_content_gate", "services.lab_recording"):
        _ORIG[name] = sys.modules.get(name)

    db_stub = types.ModuleType("services.db")
    db_stub.db = MagicMock()
    sys.modules["services.db"] = db_stub

    store = types.ModuleType("services.coach_video_storage")
    store.put_coach_object_bytes = lambda *a, **k: None
    store.coach_media_public_url = lambda key: f"https://cdn/{key}"
    sys.modules["services.coach_video_storage"] = store

    gate = types.ModuleType("services.min_content_gate")
    gate.evaluate_min_content_bytes = lambda b: (
        {"ok": True, "duration_sec": 42.0} if b != b"BAD"
        else {"ok": False, "reason": "too_short"})
    sys.modules["services.min_content_gate"] = gate

    lab = types.ModuleType("services.lab_recording")
    lab.process_lab_recording = lambda **kw: {
        "snippets": [{"id": "p1"}, {"id": "p2"}, {"id": "p3"}]}
    sys.modules["services.lab_recording"] = lab


def tearDownModule():
    for name, mod in _ORIG.items():
        if mod is not None:
            sys.modules[name] = mod
        else:
            sys.modules.pop(name, None)


def _db() -> MagicMock:
    d = MagicMock()
    d.create_recording.return_value = None
    d.find_training_import_by_key.return_value = None
    return d


def _import(**over):
    from services.training_import import import_training_audio
    kwargs = dict(audio_bytes=b"AUDIO", filename="talk.mp3",
                  user_id="user-1", topic="My conference talk",
                  database=over.pop("database", _db()))
    kwargs.update(over)
    return kwargs["database"], import_training_audio(**kwargs)


class IsolationTests(unittest.TestCase):
    """The markers that make an import invisible to the speaker."""

    def test_session_source_is_training_import_not_audit_upload(self):
        """THE load-bearing assertion. audit_upload is what
        v2_list_user_lab_sessions (the per-speaker baseline reader) and every
        user-facing history query filter on — an import wearing that value
        would blend other people's voices into this speaker's own norm."""
        from services.training_import import IMPORT_SOURCE
        db, result = _import()
        self.assertTrue(result["ok"])
        db.set_session_source.assert_called_once()
        args = db.set_session_source.call_args.args
        self.assertEqual(args[1], IMPORT_SOURCE)
        self.assertNotEqual(args[1], "audit_upload")

    def test_import_gets_its_own_single_take_arc(self):
        """Every coach surface is arc-scoped; an arc-less import would be
        analysed and then unreachable."""
        db, result = _import()
        db.set_session_arc.assert_called_once()
        sid, arc_id, take_index = db.set_session_arc.call_args.args
        self.assertEqual(sid, result["session_id"])
        self.assertEqual(arc_id, result["arc_id"])
        self.assertEqual(take_index, 1)
        self.assertNotEqual(result["arc_id"], result["session_id"])

    def test_provenance_is_written_on_the_recording(self):
        from services.training_import import IMPORT_ORIGIN
        db, _ = _import(speaker_label="Jane Doe", source_note="from YouTube")
        payload = db.create_recording.call_args.args[0]
        self.assertEqual(payload["recording_origin"], IMPORT_ORIGIN)
        meta = payload["source_metadata"]
        self.assertEqual(meta["source_kind"], "training_import")
        self.assertEqual(meta["speaker_label"], "Jane Doe")
        self.assertEqual(meta["import_notes"], "from YouTube")
        self.assertEqual(meta["source_title"], "talk.mp3")

    def test_speaker_label_rides_the_session_context(self):
        """The grouping key a per-speaker model will need."""
        db, _ = _import(speaker_label="Jane Doe")
        ctx = db.set_session_intake_context.call_args.args[1]
        self.assertEqual(ctx["speaker_label"], "Jane Doe")
        self.assertEqual(ctx["topic"], "My conference talk")


class PipelineParityTests(unittest.TestCase):

    def test_runs_the_same_analysis_a_live_take_runs(self):
        _db_, result = _import()
        self.assertEqual(result["snippet_count"], 3)
        self.assertTrue(result["ok"])

    def test_analysis_receives_the_stored_parent_url(self):
        # Patch through sys.modules, NOT `import services.lab_recording as x`:
        # the latter binds the `services` package ATTRIBUTE (the real module,
        # already imported by another suite), while training_import's
        # function-level `from services.lab_recording import ...` reads
        # sys.modules — so an attribute patch lands on the wrong object and
        # the test passes alone but fails in the full run.
        lab = sys.modules["services.lab_recording"]
        seen = {}
        orig = lab.process_lab_recording

        def _spy(**kw):
            seen.update(kw)
            return {"snippets": []}
        lab.process_lab_recording = _spy
        try:
            _db_, result = _import()
        finally:
            lab.process_lab_recording = orig
        self.assertEqual(seen["session_id"], result["session_id"])
        self.assertTrue(seen["parent_audio_url"].startswith("https://cdn/"))
        self.assertEqual(seen["user_id"], "user-1")


class GateAndFailureTests(unittest.TestCase):

    def test_gate_rejection_is_a_reason_not_an_exception(self):
        _db_, result = _import(audio_bytes=b"BAD")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "too_short")

    def test_missing_topic_is_rejected(self):
        _db_, result = _import(topic="   ")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "no_topic")

    def test_empty_audio_is_rejected(self):
        _db_, result = _import(audio_bytes=b"")
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "no_audio")

    def test_pre_migration_db_still_imports_without_provenance(self):
        """recording_origin / source_metadata are an old, possibly-unrun
        migration — losing the import over them would be the wrong trade."""
        db = _db()
        calls = []

        def _create(payload):
            calls.append(payload)
            if len(calls) == 1:
                raise RuntimeError(
                    "column \"source_metadata\" does not exist (PGRST204)")
        db.create_recording.side_effect = _create
        _db_, result = _import(database=db)
        self.assertTrue(result["ok"])
        self.assertEqual(len(calls), 2)
        self.assertNotIn("source_metadata", calls[1])
        self.assertNotIn("recording_origin", calls[1])

    def test_analysis_failure_reports_without_raising(self):
        lab = sys.modules["services.lab_recording"]   # see the note above
        orig = lab.process_lab_recording

        def _boom(**kw):
            raise RuntimeError("whisper down")
        lab.process_lab_recording = _boom
        try:
            _db_, result = _import()
        finally:
            lab.process_lab_recording = orig
        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "analysis_failed")
        # the session id still comes back so a partial import is traceable
        self.assertIn("session_id", result)


class StageTickTests(unittest.TestCase):
    """The coach-only ticks. A normal user's upload never reaches this lane."""

    def test_default_is_confidence_only(self):
        from services.training_import import DEFAULT_STAGES, normalize_stages
        self.assertEqual(normalize_stages(None), set(DEFAULT_STAGES))
        self.assertEqual(normalize_stages(None), {"confidence"})

    def test_confidence_cannot_be_unticked(self):
        """Without transcript + acoustics there is no take at all — that is
        what a bucket is for, not this endpoint."""
        from services.training_import import normalize_stages
        self.assertIn("confidence", normalize_stages("analytics"))
        self.assertIn("confidence", normalize_stages([]))
        self.assertIn("confidence", normalize_stages("ideal_text"))

    def test_comma_string_and_list_both_parse(self):
        from services.training_import import normalize_stages
        self.assertEqual(normalize_stages("analytics,ideal_text"),
                         {"confidence", "analytics", "ideal_text"})
        self.assertEqual(normalize_stages(["analytics"]),
                         {"confidence", "analytics"})

    def test_unknown_stage_degrades_instead_of_failing(self):
        """A newer FE sending a stage this build lacks must degrade to what
        it has, not 400 an upload that already cost a file read."""
        from services.training_import import normalize_stages
        self.assertEqual(normalize_stages("analytics,telepathy"),
                         {"confidence", "analytics"})
        self.assertEqual(normalize_stages(42), {"confidence"})

    def test_stages_reach_the_pipeline(self):
        lab = sys.modules["services.lab_recording"]
        seen = {}
        orig = lab.process_lab_recording

        def _spy(**kw):
            seen.update(kw)
            return {"snippets": []}
        lab.process_lab_recording = _spy
        try:
            _import(stages="analytics")
        finally:
            lab.process_lab_recording = orig
        self.assertEqual(seen["stages"], {"confidence", "analytics"})

    def test_default_import_reports_its_stages(self):
        _db_, result = _import()
        self.assertEqual(result["stages"], ["confidence"])


class AsyncSplitTests(unittest.TestCase):
    """prepare/run split — the route returns 202 after prepare and analyses
    in a thread, so a proxy timeout can't masquerade as a failed import."""

    def test_prepare_does_no_analysis(self):
        from services.training_import import prepare_training_import
        lab = sys.modules["services.lab_recording"]
        called = []
        orig = lab.process_lab_recording
        lab.process_lab_recording = lambda **kw: called.append(1) or {}
        try:
            out = prepare_training_import(
                audio_bytes=b"AUDIO", filename="t.mp3", user_id="u1",
                topic="T", database=_db())
        finally:
            lab.process_lab_recording = orig
        self.assertTrue(out["ok"])
        self.assertEqual(called, [], "prepare must not run the analysis")
        self.assertIn("session_id", out)
        self.assertIn("parent_audio_url", out)

    def test_prepare_marks_the_session_processing(self):
        from services.training_import import prepare_training_import
        db = _db()
        prepare_training_import(audio_bytes=b"A", filename="t.mp3",
                                user_id="u1", topic="T", database=db)
        db.set_session_analysis_state.assert_called_once()
        self.assertEqual(
            db.set_session_analysis_state.call_args.args[1], "processing")

    def test_run_marks_ready_and_returns_counts(self):
        from services.training_import import (
            prepare_training_import, run_training_import_analysis,
        )
        db = _db()
        db.get_snippets_by_session.return_value = []
        prepared = prepare_training_import(
            audio_bytes=b"A", filename="t.mp3", user_id="u1", topic="T",
            database=db)
        out = run_training_import_analysis(
            prepared=prepared, audio_bytes=b"A", filename="t.mp3",
            database=db)
        self.assertTrue(out["ok"])
        self.assertEqual(out["snippet_count"], 3)
        self.assertEqual(db.set_session_analysis_state.call_args.args[1],
                         "ready")

    def test_analysis_failure_marks_failed_for_the_poll(self):
        """The FE polls analysis_state — a crashed thread must leave a
        'failed', not a session stuck on 'processing' forever."""
        from services.training_import import (
            prepare_training_import, run_training_import_analysis,
        )
        db = _db()
        prepared = prepare_training_import(
            audio_bytes=b"A", filename="t.mp3", user_id="u1", topic="T",
            database=db)
        lab = sys.modules["services.lab_recording"]
        orig = lab.process_lab_recording

        def _boom(**kw):
            raise RuntimeError("whisper down")
        lab.process_lab_recording = _boom
        try:
            out = run_training_import_analysis(
                prepared=prepared, audio_bytes=b"A", filename="t.mp3",
                database=db)
        finally:
            lab.process_lab_recording = orig
        self.assertFalse(out["ok"])
        self.assertEqual(db.set_session_analysis_state.call_args.args[1],
                         "failed")


class IdempotencyTests(unittest.TestCase):
    """A retry after a proxy timeout must return the ORIGINAL import — a talk
    imported twice is labelled twice and trains twice, invisibly."""

    def test_known_key_returns_the_original_and_creates_nothing(self):
        from services.training_import import prepare_training_import
        db = _db()
        db.find_training_import_by_key.return_value = {
            "id": "sess-orig", "arc_id": "arc-orig",
            "intake_context": {"topic": "T", "label_queue": ["a", "b"]},
        }
        out = prepare_training_import(
            audio_bytes=b"A", filename="t.mp3", user_id="u1", topic="T",
            database=db, idempotency_key="abc-123")
        self.assertTrue(out["ok"])
        self.assertTrue(out["duplicate"])
        self.assertEqual(out["session_id"], "sess-orig")
        self.assertEqual(out["queue_count"], 2)
        db.v2_create_guest_session.assert_not_called()
        db.create_recording.assert_not_called()

    def test_key_is_stored_so_the_retry_can_find_it(self):
        from services.training_import import prepare_training_import
        db = _db()
        prepare_training_import(audio_bytes=b"A", filename="t.mp3",
                                user_id="u1", topic="T", database=db,
                                idempotency_key="abc-123")
        ctx = db.set_session_intake_context.call_args.args[1]
        self.assertEqual(ctx["import_key"], "abc-123")

    def test_lookup_failure_still_imports(self):
        """Refusing a legitimate first import is worse than risking the
        duplicate the key existed to prevent."""
        from services.training_import import prepare_training_import
        db = _db()
        db.find_training_import_by_key.side_effect = RuntimeError("db down")
        out = prepare_training_import(
            audio_bytes=b"A", filename="t.mp3", user_id="u1", topic="T",
            database=db, idempotency_key="abc-123")
        self.assertTrue(out["ok"])
        self.assertFalse(out.get("duplicate"))

    def test_no_key_means_no_lookup(self):
        from services.training_import import prepare_training_import
        db = _db()
        prepare_training_import(audio_bytes=b"A", filename="t.mp3",
                                user_id="u1", topic="T", database=db)
        db.find_training_import_by_key.assert_not_called()


class ZeroPieceHonestyTests(unittest.TestCase):
    """A zero-piece import must NOT read as success (FE 2026-07-29: the first
    real import, a Polish talk, returned ok:true with nothing to show, so
    'worked perfectly' and 'silently did nothing' were identical on the
    wire)."""

    def _run(self, snippets, extra=None):
        from services.training_import import (
            prepare_training_import, run_training_import_analysis,
        )
        db = _db()
        db.get_snippets_by_session.return_value = []
        prepared = prepare_training_import(
            audio_bytes=b"A", filename="talk.mp3", user_id="u1",
            topic="T", database=db, **(extra or {}))
        lab = sys.modules["services.lab_recording"]
        orig = lab.process_lab_recording
        lab.process_lab_recording = lambda **kw: {"snippets": snippets}
        try:
            return db, run_training_import_analysis(
                prepared=prepared, audio_bytes=b"A", filename="talk.mp3",
                database=db)
        finally:
            lab.process_lab_recording = orig

    def test_zero_pieces_is_not_ok(self):
        _db_, out = self._run([])
        self.assertFalse(out["ok"])
        self.assertEqual(out["snippet_count"], 0)
        self.assertIn(out["reason"], ("NO_SPEECH_DETECTED", "NO_CANDIDATES"))
        self.assertTrue(out["detail"])

    def test_empty_transcript_blames_language_not_the_cutter(self):
        """The distinction the coach needs: nothing transcribed (usually a
        language problem) vs transcribed-but-nothing-kept (tuning)."""
        _db_, out = self._run([])
        self.assertEqual(out["reason"], "NO_SPEECH_DETECTED")
        self.assertIn("language", out["detail"])

    def test_zero_pieces_marks_the_session_failed_for_the_poll(self):
        db, _out = self._run([])
        self.assertEqual(db.set_session_analysis_state.call_args.args[1],
                         "failed")

    def test_duration_rides_the_failure_so_it_can_be_diagnosed(self):
        """Duration separates 'never decoded' from 'decoded but no speech' —
        the FE surfaces it and it is the whole diagnosis."""
        _db_, out = self._run([])
        self.assertIn("duration_sec", out)
        self.assertEqual(out["duration_sec"], 42.0)

    def test_pieces_present_is_still_ok(self):
        _db_, out = self._run([{"id": "p1"}])
        self.assertTrue(out["ok"])
        self.assertEqual(out["snippet_count"], 1)


class LanguageTests(unittest.TestCase):

    def test_language_rides_the_session_context(self):
        from services.training_import import prepare_training_import
        db = _db()
        prepare_training_import(audio_bytes=b"A", filename="t.mp3",
                                user_id="u1", topic="T", database=db,
                                language="PL")
        ctx = db.set_session_intake_context.call_args.args[1]
        self.assertEqual(ctx["language"], "pl")

    def test_absent_language_stays_absent(self):
        """No hint = Whisper auto-detects, exactly as the live path always
        has — the import must not invent 'en'."""
        from services.training_import import prepare_training_import
        db = _db()
        prepare_training_import(audio_bytes=b"A", filename="t.mp3",
                                user_id="u1", topic="T", database=db)
        ctx = db.set_session_intake_context.call_args.args[1]
        self.assertNotIn("language", ctx)

    def test_language_reaches_the_pipeline(self):
        from services.training_import import (
            prepare_training_import, run_training_import_analysis,
        )
        db = _db()
        db.get_snippets_by_session.return_value = []
        prepared = prepare_training_import(
            audio_bytes=b"A", filename="t.mp3", user_id="u1", topic="T",
            database=db, language="pl")
        lab = sys.modules["services.lab_recording"]
        seen = {}
        orig = lab.process_lab_recording

        def _spy(**kw):
            seen.update(kw)
            return {"snippets": [{"id": "p1"}]}
        lab.process_lab_recording = _spy
        try:
            run_training_import_analysis(prepared=prepared, audio_bytes=b"A",
                                         filename="t.mp3", database=db)
        finally:
            lab.process_lab_recording = orig
        self.assertEqual(seen["session_context"]["language"], "pl")


class ImportListDegradationTests(unittest.TestCase):
    """The corpus index must never come back empty just because an older
    column is unmigrated — an empty list reads exactly like 'nothing
    imported', which is the failure this list exists to rule out."""

    def _database_service(self):
        """The REAL DatabaseService class.

        setUpModule replaces sys.modules['services.db'] with a stub carrying
        only `db`, so a plain import here finds no class. Restore the real
        module (or import it fresh) just long enough to grab the class, then
        put the stub back — leaving the real module in place would let the
        other tests in this file reach a live client."""
        import importlib
        import types as _t
        stub = sys.modules.get("services.db")
        real = _ORIG.get("services.db")
        for name in ("supabase", "sentry_sdk"):
            if name not in sys.modules:
                m = _t.ModuleType(name)
                m.create_client = lambda *a, **k: None
                m.Client = object
                sys.modules[name] = m
        try:
            if real is not None:
                sys.modules["services.db"] = real
            else:
                sys.modules.pop("services.db", None)
                real = importlib.import_module("services.db")
                sys.modules["services.db"] = real
            return real.DatabaseService
        finally:
            if stub is not None:
                sys.modules["services.db"] = stub

    def _svc(self, *, fail_on_analysis_state: bool):
        import types as _t
        DatabaseService = self._database_service()
        seen = {"cols": []}

        class _Q:
            def __init__(self, cols):
                self.cols = cols

            def eq(self, *a):
                return self

            def order(self, *a, **k):
                return self

            def limit(self, *a):
                return self

            def execute(self):
                if fail_on_analysis_state and "analysis_state" in self.cols:
                    raise RuntimeError(
                        'column "analysis_state" does not exist')
                return _t.SimpleNamespace(data=[{"id": "s1"}])

        class _T:
            def select(self, cols):
                seen["cols"].append(cols)
                return _Q(cols)

        svc = DatabaseService.__new__(DatabaseService)
        svc.client = _t.SimpleNamespace(table=lambda name: _T())
        return svc, seen

    def test_falls_back_when_analysis_state_is_unmigrated(self):
        svc, seen = self._svc(fail_on_analysis_state=True)
        rows = svc.list_training_import_sessions()
        self.assertEqual(rows, [{"id": "s1"}], "the list must still serve")
        self.assertEqual(len(seen["cols"]), 2, "should have retried")
        self.assertNotIn("analysis_state", seen["cols"][1])

    def test_uses_analysis_state_when_available(self):
        svc, seen = self._svc(fail_on_analysis_state=False)
        svc.list_training_import_sessions()
        self.assertEqual(len(seen["cols"]), 1)
        self.assertIn("analysis_state", seen["cols"][0])


class HelperTests(unittest.TestCase):

    def test_audio_extension_detection(self):
        from services.training_import import is_audio_filename
        for good in ("a.mp3", "b.WAV", "c.m4a", "d.webm", "e.flac"):
            self.assertTrue(is_audio_filename(good), good)
        for bad in ("notes.txt", "deck.pdf", "", None, "noext"):
            self.assertFalse(is_audio_filename(bad), str(bad))

    def test_content_type_guess(self):
        from services.training_import import content_type_for
        self.assertEqual(content_type_for("x.mp3"), "audio/mpeg")
        self.assertEqual(content_type_for("x.wav"), "audio/wav")
        self.assertEqual(content_type_for("x.unknown"), "audio/webm")

    def test_source_metadata_drops_empties(self):
        from services.training_import import build_source_metadata
        meta = build_source_metadata(filename="a.mp3", speaker_label="  ",
                                     source_note=None)
        self.assertEqual(set(meta), {"source_kind", "source_title"})


class FenceTests(unittest.TestCase):

    def test_the_baseline_reader_is_untouched_by_imports(self):
        """v2_list_user_lab_sessions is THE per-speaker baseline reader and
        must keep its audit_upload filter — the import lane has its own
        reader instead (list_training_import_sessions)."""
        with open("services/db.py", encoding="utf-8") as fh:
            source = fh.read()
        block = source.split("def v2_list_user_lab_sessions")[1][:1600]
        self.assertIn('"audit_upload"', block)
        self.assertNotIn("training_import", block)

    def test_import_lane_never_writes_audit_upload(self):
        with open("services/training_import.py", encoding="utf-8") as fh:
            source = fh.read()
        code = "\n".join(
            ln for ln in source.splitlines()
            if not ln.strip().startswith(("#", "*"))
        ).split('"""')[-1]
        self.assertNotIn('"audit_upload"', code)

    def test_import_is_not_synthetic(self):
        """Real human speech — it must NOT be marked synthetic, or the
        Subsystem-S wall in learning_export would exclude the whole corpus
        from coach-truth training."""
        with open("services/training_import.py", encoding="utf-8") as fh:
            source = fh.read()
        self.assertNotIn('data_origin', source.split('"""')[-1])


if __name__ == "__main__":
    unittest.main()
