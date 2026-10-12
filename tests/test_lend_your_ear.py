"""Lend your ear, the one engine of the walk's other voices (founder
2026-10-07, Q-B11 A, N62), the licensed corpus and the delayed measure.

Pins: the Album share switch, the per-Take blind set it fed and Bold voices
are RETIRED, their service doors gone and their routes 404 whatever the
switches say, nothing written; the one consent path that admits a
speaker's moment to a peer queue is the per-Take community share
(services/communities.py, community_clips_live), read by the engine's
``other_voices`` and nothing else; at most three other voices per walk,
community first, then training clips; a blind stratified pick (build_set)
that never holds two clips of one pair; the payload carries only the id,
the kind and the sound; a peer label lands under lane game_peer through
the quorum's access rule; the measure's pair is the first valid attempt,
excludes fallbacks and rewrites, is judged after seven days, refuses the
speaker, the coach who handled the moment and an exposed rater, settles
only by quorum, and no longer has a door into any queue.
"""
from __future__ import annotations

import unittest

from services import lend_your_ear as lye


def _snippet(sid, band=None, session="take-9"):
    row = {"id": sid, "session_id": session, "audio_segment_path": f"s/{sid}.webm",
           "duration_ms": 3000, "metrics": {}}
    if band:
        row["metrics"]["voice_confidence"] = {"band": band}
    return row


class SetTests(unittest.TestCase):


    def test_the_stratum_is_the_machine_s_read_never_surfaced(self):
        self.assertEqual(lye.stratum(_snippet("x", band="delivery_signal_high")), "confident")
        self.assertEqual(lye.stratum(_snippet("x", band="delivery_signal_low")), "weak")
        self.assertEqual(lye.stratum(_snippet("x")), "unknown")
        self.assertEqual(lye.stratum(None), "unknown")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
