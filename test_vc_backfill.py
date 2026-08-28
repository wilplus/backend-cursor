"""willab — repairing a voice-confidence weighting change while ranking is LIVE.

The composite stamps at record time and nothing re-stamps it, so changing the
weighting (v1 sex-blind -> v2 sex-routed, cue 1 REVERSES for men) left old and
new scores competing in the same arc on different scales. Two halves:

  * the GATE (test_voice_confidence.py) — a superseded weighting does not rank;
  * the REPAIR (here) — scripts/backfill_voice_confidence.py re-stamps history
    under the current weighting, and the cache signature notices.

What this pins down, all of it a way the repair could quietly be worse than the
problem:
  * IDEMPOTENT — a second run must not rewrite what it already wrote;
  * DRY RUN BY DEFAULT — no --apply, no writes, ever;
  * the backfill resolves sex through the SAME path as the recorder, so a
    backfilled piece and a freshly recorded one are comparable (the entire
    point) — and in particular it cannot resurrect #290;
  * silence over invention — no baseline means no stamp, not a neutral 0.0;
  * a warm best-presentation cache cannot outlive a weighting change.

Run: python3 -m unittest test_vc_backfill
"""
from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

_ORIG_SERVICES_DB = None


def setUpModule():
    global _ORIG_SERVICES_DB
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)


USER = "11111111-1111-4111-8111-111111111111"

# Enough spread that feature_stats keeps every feature and a baseline resolves.
def _metrics(i: int, *, stamped_version: str | None = None) -> dict:
    m = {
        "f0_sd": 20.0 + i, "dynamic_db": 10.0 + i, "f0_mean": 110.0 + i,
        "wpm": 130.0 + i, "pause_ratio": 0.2 + i * 0.01,
        "pause_ms": 300.0 + i, "f0_mid_end_delta": 2.0 + i,
        "intensity_envelope": -1.0 - i * 0.1,
    }
    if stamped_version:
        m["voice_confidence"] = {"score": 0.42, "band": "close_to_confident",
                                 "baseline": "user", "cues": 7,
                                 "version": stamped_version}
    return m


class _FakeDB:
    """Minimal store surface the backfill touches."""

    def __init__(self, n=10, stamped_version=None, declared_sex=None):
        self.snips = [
            {"id": f"s{i}", "metrics": _metrics(i,
                                                stamped_version=stamped_version)}
            for i in range(n)
        ]
        self.declared_sex = declared_sex
        self.writes: list = []

    def v2_list_user_lab_sessions(self, user_id, limit=200):
        return [{"id": "sess-1"}]

    def get_snippets_by_session(self, session_id):
        return self.snips

    def get_user_speaker_sex(self, user_id):
        return self.declared_sex

    def update_snippet_metrics_blob(self, snippet_id, metrics_json):
        self.writes.append((snippet_id, metrics_json))
        for s in self.snips:                     # persist, so re-runs see it
            if s["id"] == snippet_id:
                s["metrics"] = metrics_json
        return True


def _backfill_user():
    """Load the script by PATH — scripts/ is a directory of standalone
    entry points, not a package, and making it one just so a test can import
    would be the test changing the repo's shape. Same approach as
    test_video_size_cap_config.py."""
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "scripts", "backfill_voice_confidence.py")
    spec = importlib.util.spec_from_file_location("_vc_backfill_script", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.backfill_user


def _run(db, *, apply):
    return _backfill_user()(db, USER, apply=apply, max_sessions=200)


class BackfillTests(unittest.TestCase):

    def test_dry_run_writes_nothing(self):
        """The default. A data migration that can write by accident is a bug."""
        db = _FakeDB(stamped_version="voice-confidence-v1")
        counts = _run(db, apply=False)
        self.assertEqual(db.writes, [])
        self.assertEqual(counts["would_write"], 10)
        self.assertEqual(counts["from_v1"], 10)

    def test_apply_restamps_to_the_current_version(self):
        from services.voice_confidence import _VERSION
        db = _FakeDB(stamped_version="voice-confidence-v1")
        counts = _run(db, apply=True)
        self.assertEqual(counts["written"], 10)
        for _sid, blob in db.writes:
            self.assertEqual(blob["voice_confidence"]["version"], _VERSION)

    def test_restamped_pieces_rank_again(self):
        """The whole point: after the backfill the gate stops excluding them."""
        from services.voice_confidence import rank_term
        db = _FakeDB(stamped_version="voice-confidence-v1")
        stale = db.snips[0]["metrics"]
        with unittest.mock.patch.dict(
                "os.environ", {"VOICE_CONFIDENCE_RANKING_ENABLED": "1"}):
            self.assertIsNone(rank_term(stale))       # before
            _run(db, apply=True)
            self.assertIsNotNone(rank_term(db.snips[0]["metrics"]))   # after

    def test_second_run_is_a_no_op(self):
        db = _FakeDB(stamped_version="voice-confidence-v1")
        _run(db, apply=True)
        db.writes.clear()
        counts = _run(db, apply=True)
        self.assertEqual(db.writes, [])
        self.assertEqual(counts["already_current"], 10)
        self.assertEqual(counts.get("written", 0), 0)

    def test_never_stamped_pieces_are_picked_up_too(self):
        """Pieces recorded before the composite existed are the same repair."""
        db = _FakeDB(stamped_version=None)
        counts = _run(db, apply=True)
        self.assertEqual(counts["never_stamped"], 10)
        self.assertEqual(counts["written"], 10)

    def test_no_baseline_stamps_nothing(self):
        """Silence over invention — a fabricated neutral would be
        indistinguishable from a real middling read and would rank as one."""
        db = _FakeDB(n=2, stamped_version="voice-confidence-v1")
        counts = _run(db, apply=True)
        self.assertEqual(db.writes, [])
        self.assertEqual(counts["skipped_no_baseline"], 2)

    def test_a_declared_sex_routes_the_whole_speaker(self):
        db = _FakeDB(stamped_version="voice-confidence-v1", declared_sex="female")
        _run(db, apply=True)
        for _sid, blob in db.writes:
            self.assertEqual(blob["voice_confidence"]["sex"], "female")
            self.assertEqual(blob["voice_confidence"]["sex_source"], "declared")

    def test_a_decline_is_honoured_by_the_backfill_too(self):
        db = _FakeDB(stamped_version="voice-confidence-v1",
                     declared_sex="prefer_not_to_say")
        _run(db, apply=True)
        for _sid, blob in db.writes:
            self.assertEqual(blob["voice_confidence"]["sex"], "unknown")
            self.assertEqual(blob["voice_confidence"]["sex_source"],
                             "not_stated")

    def test_the_other_metrics_survive_the_rewrite(self):
        """It re-stamps one derived key; it must not be a blob replacement."""
        db = _FakeDB(stamped_version="voice-confidence-v1")
        _run(db, apply=True)
        _sid, blob = db.writes[0]
        for key in ("f0_sd", "dynamic_db", "wpm", "pause_ms"):
            self.assertIn(key, blob)

    def test_a_write_failure_is_counted_not_swallowed(self):
        db = _FakeDB(stamped_version="voice-confidence-v1")
        db.update_snippet_metrics_blob = lambda *a, **k: False
        counts = _run(db, apply=True)
        self.assertEqual(counts["write_failed"], 10)
        self.assertEqual(counts.get("written", 0), 0)


class BackfillMatchesTheRecorderTests(unittest.TestCase):
    """If these two resolve sex differently, backfilled and freshly recorded
    pieces are not comparable — which is the bug, not the fix."""

    def test_both_go_through_resolve_take_sex(self):
        with open("scripts/backfill_voice_confidence.py",
                  encoding="utf-8") as fh:
            script = fh.read()
        with open("services/lab_recording.py", encoding="utf-8") as fh:
            recorder = fh.read()
        with open("services/recording_piece_analysis.py", encoding="utf-8") as fh:
            recorder_stage = fh.read()
        self.assertIn("resolve_take_sex", script)
        self.assertIn("enrich_canonical_pieces", recorder)
        self.assertIn("resolve_take_sex", recorder_stage)
        # Neither may carry its own copy of the precedence.
        self.assertNotIn("speaker_is_account_holder", script)
        self.assertNotIn("speaker_is_account_holder", recorder_stage)

    def test_the_backfill_cannot_touch_training_imports(self):
        """#290's bug, reachable a second way. An import's speaker identity is
        in a transient session_context, so it cannot be recovered — the script
        must rely on the audit_upload-only listing rather than reading
        snippets directly, and must never invent a speaker_sex."""
        with open("scripts/backfill_voice_confidence.py",
                  encoding="utf-8") as fh:
            script = fh.read()
        self.assertIn("v2_list_user_lab_sessions", script)
        # session_context is passed as None — the normal-take path, explicitly.
        # Whitespace-insensitive: this pins the ARGUMENT, not the formatting.
        collapsed = " ".join(script.split())
        self.assertIn("resolve_take_sex( user_id, None,", collapsed,
                      "backfill must resolve sex on the normal-take path")


class CacheSignatureTests(unittest.TestCase):

    def test_a_weighting_change_invalidates_warm_caches(self):
        """Without this a backfilled arc keeps serving picks made under the
        retired weighting until something unrelated invalidates it — so the
        repair would land arc-by-arc at random times."""
        from services import best_presentation as bp
        sessions = [{"id": "a", "take_index": 1, "results_published_at": ""}]
        before = bp._bp_signature(sessions)
        with unittest.mock.patch(
                "services.voice_confidence._VERSION", "voice-confidence-v99"):
            after = bp._bp_signature(sessions)
        self.assertNotEqual(before, after)

    def test_the_ranking_flag_still_moves_the_signature(self):
        from services import best_presentation as bp
        sessions = [{"id": "a", "take_index": 1, "results_published_at": ""}]
        with unittest.mock.patch.dict(
                "os.environ", {"VOICE_CONFIDENCE_RANKING_ENABLED": "0"}):
            off = bp._bp_signature(sessions)
        with unittest.mock.patch.dict(
                "os.environ", {"VOICE_CONFIDENCE_RANKING_ENABLED": "1"}):
            on = bp._bp_signature(sessions)
        self.assertNotEqual(off, on)


if __name__ == "__main__":
    unittest.main()
