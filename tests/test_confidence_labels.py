"""willab — confidence labelling (founder 2026-07-28), the corpus for the
app's core function: recognising the confident snippet.

services/confidence_labels.py.

WHAT THIS PINS DOWN:
  * the label shape — `confident` yes/no is REQUIRED and must be a real
    boolean (a truthy string is refused, not coerced: a rating corpus that
    silently accepted junk is worse than one that rejected it); `intensity`
    is an optional 1-5 on the Jiang & Pell scale;
  * STRATIFIED sampling — the queue draws from the confident, neutral AND
    doubtful bands. A corpus drawn only from machine-confident pieces teaches
    the model to agree with itself and never shows it the boundary;
  * BLIND COACH — the queue payload carries the moment and nothing else: no
    band, no score, no acoustic read, and no ordering tell;
  * determinism — the same session yields the same queue (resumable batches,
    replayable imports).

Run: python3 -m unittest tests.test_confidence_labels
"""
from __future__ import annotations

import unittest


def _snip(sid, score=None, **over):
    row = {"id": sid, "transcript": f"line {sid}",
           "audio_ref": f"s3://{sid}", "start_offset_ms": 0,
           "duration_ms": 1500, "session_id": "sess-1"}
    if score is not None:
        row["metrics"] = {"voice_confidence": {"score": score}}
    row.update(over)
    return row


class BlindPayloadTests(unittest.TestCase):

    def test_queue_payload_carries_no_machine_read(self):
        from services.confidence_labels import queue_payload
        rows = queue_payload([_snip("s1", score=0.9, metrics={
            "voice_confidence": {"score": 0.9, "band": "confident"},
            "acoustic_read": {"potentiometer": 0.8},
            "user_tone_word": "confident",
        }, _selection={
            "reason": "model_boundary", "sampling_probability": 1.0,
        })])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["transcript"], "line s1")
        for banned in ("metrics", "voice_confidence", "acoustic_read",
                       "band", "score", "user_tone_word", "_selection",
                       "selection_reason", "sampling_probability"):
            self.assertNotIn(banned, row)


if __name__ == "__main__":
    unittest.main()
