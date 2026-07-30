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

Run: python3 -m unittest test_confidence_labels
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


class ValidateTests(unittest.TestCase):

    def test_yes_no_plus_intensity(self):
        from services.confidence_labels import validate_confidence_label
        row, err = validate_confidence_label({"confident": True,
                                              "intensity": 4})
        self.assertIsNone(err)
        self.assertIs(row["confident"], True)
        self.assertEqual(row["intensity"], 4)
        self.assertEqual(row["source"], "coach")

    def test_confident_false_is_a_real_label(self):
        from services.confidence_labels import validate_confidence_label
        row, err = validate_confidence_label({"confident": False,
                                              "intensity": 2})
        self.assertIsNone(err)
        self.assertIs(row["confident"], False)

    def test_intensity_is_optional(self):
        from services.confidence_labels import validate_confidence_label
        row, err = validate_confidence_label({"confident": True})
        self.assertIsNone(err)
        self.assertIsNone(row["intensity"])

    def test_confident_is_required_and_must_be_boolean(self):
        """A truthy string must be REFUSED, not coerced — silent coercion is
        how a rating corpus fills with values nobody meant."""
        from services.confidence_labels import validate_confidence_label
        for bad in ({}, {"confident": "true"}, {"confident": 1},
                    {"confident": None}, {"intensity": 3}):
            self.assertIsNone(validate_confidence_label(bad)[0], str(bad))

    def test_intensity_range_is_enforced(self):
        from services.confidence_labels import validate_confidence_label
        for bad in (0, 6, -1, 2.5, True, "3"):
            row, err = validate_confidence_label({"confident": True,
                                                  "intensity": bad})
            self.assertIsNone(row, f"intensity={bad!r} should be rejected")
            self.assertIn("intensity", err)
        for good in (1, 2, 3, 4, 5):
            self.assertIsNotNone(validate_confidence_label(
                {"confident": True, "intensity": good})[0])

    def test_junk_body(self):
        from services.confidence_labels import validate_confidence_label
        self.assertIsNone(validate_confidence_label(None)[0])
        self.assertIsNone(validate_confidence_label("x")[0])
        self.assertIsNone(validate_confidence_label(
            {"confident": True, "source": "nope"})[0])


class BandTests(unittest.TestCase):

    def test_bands(self):
        from services.confidence_labels import band_of
        self.assertEqual(band_of(0.8), "confident")
        self.assertEqual(band_of(0.0), "neutral")
        self.assertEqual(band_of(-0.8), "doubtful")
        self.assertEqual(band_of(None), "unscored")
        self.assertEqual(band_of(True), "unscored")


class StratifiedQueueTests(unittest.TestCase):

    def _pool(self):
        pool = []
        for i in range(8):
            pool.append(_snip(f"c{i}", score=0.6 + i * 0.01))   # confident
        for i in range(8):
            pool.append(_snip(f"n{i}", score=0.0))              # neutral
        for i in range(8):
            pool.append(_snip(f"d{i}", score=-0.6 - i * 0.01))  # doubtful
        return pool

    def test_draws_from_every_band_not_just_the_confident_one(self):
        """THE methodological assertion. A queue of only machine-confident
        pieces teaches the model to confirm its own guesses — it never sees
        what unconfident looks like, so it cannot learn the boundary."""
        from services.confidence_labels import stratified_label_queue
        picked = stratified_label_queue(self._pool(), per_band=3, seed="s")
        ids = {p["id"] for p in picked}
        self.assertTrue(any(i.startswith("c") for i in ids), "no confident")
        self.assertTrue(any(i.startswith("n") for i in ids), "no neutral")
        self.assertTrue(any(i.startswith("d") for i in ids), "no doubtful")
        self.assertEqual(len(picked), 9)   # 3 per band × 3 populated bands

    def test_unscored_pieces_participate(self):
        """Excluding them would bias the corpus toward pieces the composite
        happened to measure."""
        from services.confidence_labels import stratified_label_queue
        pool = self._pool() + [_snip("u1"), _snip("u2")]
        ids = {p["id"] for p in
               stratified_label_queue(pool, per_band=2, seed="s")}
        self.assertTrue(any(i.startswith("u") for i in ids))

    def test_deterministic(self):
        from services.confidence_labels import stratified_label_queue
        a = [p["id"] for p in
             stratified_label_queue(self._pool(), per_band=3, seed="s1")]
        b = [p["id"] for p in
             stratified_label_queue(self._pool(), per_band=3, seed="s1")]
        self.assertEqual(a, b)

    def test_order_is_not_a_band_tell(self):
        """Bands must not be contiguous in the returned order — position
        would anchor the label exactly like a visible score would."""
        from services.confidence_labels import stratified_label_queue
        picked = stratified_label_queue(self._pool(), per_band=4, seed="s")
        prefixes = [p["id"][0] for p in picked]
        # A band-ordered list would be cccc nnnn dddd — assert we see at
        # least one transition back to an earlier band.
        transitions = sum(1 for i in range(1, len(prefixes))
                          if prefixes[i] != prefixes[i - 1])
        self.assertGreater(transitions, 2,
                           f"looks band-ordered: {''.join(prefixes)}")

    def test_empty_and_junk(self):
        from services.confidence_labels import stratified_label_queue
        self.assertEqual(stratified_label_queue([]), [])
        self.assertEqual(stratified_label_queue(None), [])
        self.assertEqual(stratified_label_queue([None, 7, {}]), [])


class BlindPayloadTests(unittest.TestCase):

    def test_queue_payload_carries_no_machine_read(self):
        from services.confidence_labels import queue_payload
        rows = queue_payload([_snip("s1", score=0.9, metrics={
            "voice_confidence": {"score": 0.9, "band": "confident"},
            "acoustic_read": {"potentiometer": 0.8},
            "user_tone_word": "confident",
        })])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["transcript"], "line s1")
        for banned in ("metrics", "voice_confidence", "acoustic_read",
                       "band", "score", "user_tone_word"):
            self.assertNotIn(banned, row)

    def test_audio_fallback_chain(self):
        from services.confidence_labels import queue_payload
        row = queue_payload([{"id": "s1", "storage_path": "s3://parent"}])[0]
        self.assertEqual(row["audio_ref"], "s3://parent")


class CorpusSummaryTests(unittest.TestCase):

    def test_balance_and_intensity(self):
        from services.confidence_labels import corpus_summary
        s = corpus_summary([
            {"confident": True, "intensity": 5, "rater_id": "c1"},
            {"confident": True, "intensity": 4, "rater_id": "c1"},
            {"confident": False, "intensity": 2, "rater_id": "c2"},
        ])
        self.assertEqual(s["total"], 3)
        self.assertEqual(s["confident_yes"], 2)
        self.assertEqual(s["confident_no"], 1)
        self.assertAlmostEqual(s["balance"], 0.667, places=2)
        self.assertEqual(s["raters"], 2)
        self.assertAlmostEqual(s["mean_intensity"], 3.67, places=1)

    def test_empty(self):
        from services.confidence_labels import corpus_summary
        s = corpus_summary([])
        self.assertEqual(s["total"], 0)
        self.assertIsNone(s["balance"])


class FullStateUpsertTests(unittest.TestCase):
    """An omitted intensity CLEARS the stored one. The FE saves yes/no first
    and the grade second, so a coach who FLIPS their answer sends
    {confident} alone — carrying the old grade forward would leave a 5
    attached to a 'no' nobody graded."""

    def _svc_payload(self, row):
        import sys as _sys
        import types as _types
        from unittest.mock import MagicMock as _MM
        _orig = _sys.modules.get("supabase")
        if _orig is None:
            m = _types.ModuleType("supabase")
            m.create_client = lambda *a, **k: None
            m.Client = object
            _sys.modules["supabase"] = m
        try:
            from services.db import DatabaseService
        finally:
            if _orig is None:
                _sys.modules.pop("supabase", None)
        cap: dict = {}

        class _T:
            def upsert(self, payload, **kw):
                cap["payload"] = dict(payload)
                return self

            def execute(self):
                return _types.SimpleNamespace(data=[])

        svc = DatabaseService.__new__(DatabaseService)
        svc.client = _types.SimpleNamespace(table=lambda name: _T())
        svc.upsert_confidence_label(snippet_id="s1", row=row,
                                    rater_id="c1", session_id="sess-1")
        return cap.get("payload", {})

    def test_omitted_intensity_is_written_as_null(self):
        payload = self._svc_payload({"confident": False})
        self.assertIn("intensity", payload)
        self.assertIsNone(payload["intensity"],
                          "a flipped answer must not keep the old grade")

    def test_given_intensity_is_written(self):
        payload = self._svc_payload({"confident": True, "intensity": 4})
        self.assertEqual(payload["intensity"], 4)
        self.assertIs(payload["confident"], True)


class FenceTests(unittest.TestCase):

    def test_confidence_lane_is_separate_from_training_labels(self):
        """training_labels is the challenge/threat DIRECTION corpus feeding a
        different model. Folding confidence into it would silently change
        what that model trains on."""
        with open("services/confidence_labels.py", encoding="utf-8") as fh:
            source = fh.read()
        code = source.split('"""')[-1]
        self.assertNotIn("training_labels", code)

    def test_module_is_pure(self):
        import ast
        with open("services/confidence_labels.py", encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                self.assertFalse(
                    isinstance(fn, ast.Attribute) and fn.attr == "table",
                    "confidence_labels must stay pure — no DB access")


if __name__ == "__main__":
    unittest.main()
