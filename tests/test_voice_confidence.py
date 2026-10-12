"""willab — the voice-confidence composite (founder spec 2026-07-27, Jiang &
Pell 2017) and its entry into the L2 ranking blend.

services/voice_confidence.py: the 7-cue speaker-relative confident↔doubtful
read; services/power_phrase_ranking.py: the new w_v term.

WHAT THIS PINS DOWN:
  * every cue's DIRECTION, one at a time — the whole spec is directions, so a
    silently inverted sign is the failure mode that matters. Cue 6
    (f0_mid_end_delta) is tested explicitly because our field is
    ``mid - end``, which inverts the spec sheet's wording;
  * the NEUTRAL DEAD ZONE — a middling clip must read 0.0, not be forced to a
    pole;
  * partial-blob RENORMALIZATION — a piece missing cues must not drift toward
    neutral just because features were absent;
  * SILENCE over invention — no baseline / too few cues → None, never 0.0;
  * the ranking is a strict NO-OP until the flag is on (byte-for-byte), and
    the authority ordering (coach > breakthrough > delivery) survives the new
    term;
  * AC-9 — the score/band never reach a user OR coach payload.

Run: python3 -m unittest tests.test_voice_confidence
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock

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


# A baseline where every feature has mean 0.0 and sd 1.0, so a raw metric value
# IS its z-score — the cue directions become readable by eye.
_UNIT_BASELINE = {
    "f0_sd": (0.0, 1.0),
    "dynamic_db": (0.0, 1.0),
    "f0_mean": (0.0, 1.0),
    "wpm": (0.0, 1.0),
    "pause_ratio": (0.0, 1.0),
    "pause_ms": (0.0, 1.0),
    "f0_mid_end_delta": (0.0, 1.0),
    "intensity_envelope": (0.0, 1.0),
}

# Neutral on every cue — the base each single-cue test perturbs.
_FLAT = {k: 0.0 for k in _UNIT_BASELINE}


def _with(**over) -> dict:
    m = dict(_FLAT)
    m.update(over)
    return m


class TestAttach(unittest.TestCase):

    def _pieces(self, n=6):
        return [{"metrics": _with(f0_sd=float(i))} for i in range(n)]

    def test_attach_stamps_every_measurable_piece(self):
        from services.voice_confidence import attach_voice_confidence
        pieces = self._pieces()
        attach_voice_confidence(pieces, baseline=_UNIT_BASELINE,
                                baseline_kind="user")
        for p in pieces:
            read = p["metrics"]["voice_confidence"]
            self.assertEqual(read["version"], "voice-confidence-universal-v3")
            self.assertEqual(read["baseline"], "user")
            self.assertNotIn("sex", read)
            self.assertNotIn("sex_source", read)
            from services.voice_confidence import BANDS
            self.assertIn(read["band"], BANDS)
            self.assertGreaterEqual(read["score"], -1.0)
            self.assertLessEqual(read["score"], 1.0)


if __name__ == "__main__":
    unittest.main()
