"""Shadow direction classifier — train core (willab Phase 4 / Prompt 1, B2).

Tests train_direction_classifier on synthetic corpora. Needs scikit-learn, so
it SKIPS locally when sklearn isn't installed and runs in CI (requirements).

Run: python3 -m unittest test_learning_train
"""
from __future__ import annotations

import unittest

try:
    import sklearn  # noqa: F401
    import numpy  # noqa: F401
    _HAS_SKLEARN = True
except Exception:
    _HAS_SKLEARN = False

from services.learning_export import FEATURES_11


def _row(label, base):
    # a separable-ish feature vector keyed off the class so the model can learn
    return {"features": {k: float(base + i) for i, k in enumerate(FEATURES_11)},
            "label": label}


def _corpus(per_class=20):
    rows = []
    for label, base in (("threat", 0.0), ("ambiguous", 50.0), ("challenge", 100.0)):
        for j in range(per_class):
            rows.append(_row(label, base + (j % 3)))
    return rows


@unittest.skipUnless(_HAS_SKLEARN, "scikit-learn not installed in this env")
class TrainDirectionClassifierTests(unittest.TestCase):
    def _train(self, rows):
        from services.learning_train import train_direction_classifier
        return train_direction_classifier(rows)

    def test_trains_and_returns_artifact_and_metrics(self):
        artifact, metrics, warnings = self._train(_corpus(20))  # 60 rows
        self.assertIsInstance(artifact, (bytes, bytearray))
        self.assertGreater(len(artifact), 0)
        self.assertEqual(metrics["corpus_size"], 60)
        self.assertEqual(set(metrics["classes"]), {"threat", "ambiguous", "challenge"})
        self.assertIn("accuracy", metrics)
        self.assertIn("f1_macro", metrics)
        # separable synthetic data → it should learn something
        self.assertGreater(metrics["accuracy"], 0.6)

    def test_artifact_round_trips_and_predicts(self):
        import io
        import joblib
        import numpy as np
        artifact, _m, _w = self._train(_corpus(20))
        bundle = joblib.load(io.BytesIO(artifact))
        self.assertEqual(bundle["features"], list(FEATURES_11))
        X = np.array([[1.0 + i for i in range(len(FEATURES_11))]])
        pred = bundle["pipeline"].predict(X)
        self.assertEqual(len(pred), 1)
        self.assertIn(pred[0], bundle["classes"])

    def test_small_corpus_warns_but_still_trains(self):
        artifact, metrics, warnings = self._train(_corpus(4))  # 12 rows, < floor
        self.assertIsInstance(artifact, (bytes, bytearray))
        self.assertTrue(any("provisional" in w for w in warnings), warnings)

    def test_single_class_returns_none(self):
        rows = [_row("threat", float(i)) for i in range(20)]
        artifact, _metrics, warnings = self._train(rows)
        self.assertIsNone(artifact)
        self.assertTrue(any("one label class" in w for w in warnings), warnings)

    def test_empty_corpus_returns_none(self):
        artifact, metrics, warnings = self._train([])
        self.assertIsNone(artifact)
        self.assertEqual(metrics["corpus_size"], 0)


if __name__ == "__main__":
    unittest.main()
