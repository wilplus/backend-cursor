"""
STORY    As a coach labelling confidence, I want the queue to show only the
         moment, and to cover clips the machine reads as high, neutral and low,
         so that my labels are blind and teach the model the boundary.
OUTCOME
  O1  Never-2: the queue payload I receive carries the moment's words and
      audio, and no machine score, band, acoustic read or selection reason.
  O2  The queue draws from the high, neutral and low bands, not only from
      clips the machine already calls confident, and the same session seed
      gives the same queue.
PROVES   O1 -> test_queue_payload_carries_no_machine_read
         O2 -> test_the_queue_covers_every_band_and_is_stable_per_session
WHY      Founder 2026-07-28: a corpus drawn from machine-confident clips only
         teaches the model to agree with itself.
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
        self.assertEqual(row["audio_ref"], "s3://s1")
        for banned in ("metrics", "voice_confidence", "acoustic_read",
                       "band", "score", "user_tone_word", "_selection",
                       "selection_reason", "sampling_probability"):
            self.assertNotIn(banned, row)


class StratifiedQueueTests(unittest.TestCase):

    def test_the_queue_covers_every_band_and_is_stable_per_session(self):
        from services.confidence_labels import mixed_label_queue
        # Mostly clips near the boundary, a few the machine reads high or low.
        pool = ([_snip(f"mid{i}", score=0.01 * (i - 15)) for i in range(30)]
                + [_snip(f"high{i}", score=0.8) for i in range(5)]
                + [_snip(f"low{i}", score=-0.8) for i in range(5)])
        queue = mixed_label_queue(pool, target_size=10, seed="session-1")
        ids = [row["id"] for row in queue]
        self.assertEqual(len(ids), 10)
        self.assertTrue(any(i.startswith("high") for i in ids), ids)
        self.assertTrue(any(i.startswith("low") for i in ids), ids)
        self.assertTrue(any(i.startswith("mid") for i in ids), ids)
        again = mixed_label_queue(list(reversed(pool)), target_size=10,
                                  seed="session-1")
        self.assertEqual([row["id"] for row in again], ids)


if __name__ == "__main__":
    unittest.main()
