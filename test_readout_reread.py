"""Unit tests for build_readout_from_session (parked-restore + history).

The canonical §3.3 readout re-derived from PERSISTED snippets (features
+ persisted stickiness), + the post-publish coach-layer fold. DB mocked.

Run: python3 -m unittest test_readout_reread
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# Stub services.db so lab_recording imports without a live client.
_stub_db = types.ModuleType("services.db")
_stub_db.db = MagicMock()
sys.modules.setdefault("services.db", _stub_db)


def _snippet(sid, **over):
    base = {
        "id": sid,
        "transcript": f"transcript {sid}",
        "audio_segment_path": "https://x/parent.webm",
        "start_offset_ms": 0,
        "duration_ms": 8000,
        "metrics": {
            "wpm": 140, "f0_mean": 165.0, "pause_ms": 220, "dynamic_db": 12.0,
            "stickiness": {"composite": 0.7, "comment": "Held one idea."},
        },
    }
    base.update(over)
    return base


class ReadoutFromSessionTests(unittest.TestCase):

    def _build(self, snippets, session=None, include_insights=True):
        from services import lab_recording as mod
        from services.db import db
        with patch.object(db, "get_snippets_by_session", return_value=snippets), \
             patch.object(db, "v2_get_session_by_id", return_value=(session or {})):
            return mod.build_readout_from_session(
                "sess1", include_insights=include_insights,
            )

    def test_rebuilds_features_and_persisted_stickiness(self):
        out = self._build([_snippet("a")])
        snip = out["snippets"][0]
        self.assertEqual(snip["id"], "a")
        self.assertEqual(snip["features"]["speech_rate"], 140)   # ← wpm
        self.assertEqual(snip["features"]["f0_mean"], 165.0)
        # stickiness comes from the PERSISTED metrics blob (the fix)
        self.assertEqual(snip["stickiness"]["composite"], 0.7)
        self.assertEqual(snip["stickiness"]["comment"], "Held one idea.")

    def test_features_block_excludes_stickiness_subkey(self):
        out = self._build([_snippet("a")])
        # the §3.3 features dict must NOT carry the internal stickiness key
        self.assertNotIn("stickiness", out["snippets"][0]["features"])

    def test_chronological_index(self):
        out = self._build([_snippet("a"), _snippet("b"), _snippet("c")])
        self.assertEqual([s["index"] for s in out["snippets"]], [1, 2, 3])

    def test_missing_stickiness_yields_none(self):
        s = _snippet("a")
        del s["metrics"]["stickiness"]
        out = self._build([s])
        self.assertIsNone(out["snippets"][0]["stickiness"]["composite"])

    def test_no_insights_pre_publish(self):
        out = self._build([_snippet("a")], session={"id": "sess1"})
        self.assertNotIn("insights_payload", out)
        self.assertNotIn("coach", out["snippets"][0])

    def test_folds_coach_layer_post_publish(self):
        session = {
            "id": "sess1",
            "insights_payload": {
                "overall_message": "Strong open.",
                "snippet_notes": [
                    {"snippet_id": "a", "note": "best 8s", "tag": "strong"},
                ],
            },
        }
        out = self._build([_snippet("a"), _snippet("b")], session=session)
        self.assertEqual(out["insights_payload"]["overall_message"], "Strong open.")
        # coach note folded onto snippet a, not b
        self.assertEqual(out["snippets"][0]["coach"]["note"], "best 8s")
        self.assertEqual(out["snippets"][0]["coach"]["tag"], "strong")
        self.assertNotIn("coach", out["snippets"][1])

    def test_include_insights_false_skips_fold(self):
        session = {"id": "sess1", "insights_payload": {"overall_message": "x",
                   "snippet_notes": []}}
        out = self._build([_snippet("a")], session=session, include_insights=False)
        self.assertNotIn("insights_payload", out)

    def test_empty_session(self):
        out = self._build([])
        self.assertEqual(out["snippets"], [])


if __name__ == "__main__":
    unittest.main()
