"""Shadow serving — predict_direction (willab Phase 4 / Prompt 1, B3).

Monkeypatches _latest_bundle so no DB / object storage is needed. The bundle
build needs scikit-learn, so those cases SKIP locally and run in CI; the
no-model / bad-input cases run anywhere.

Run: python3 -m unittest test_learning_serve
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
import services.learning_serve as ls


def _make_bundle():
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    from sklearn.pipeline import Pipeline
    X, y = [], []
    for label, base in (("threat", 0.0), ("challenge", 100.0)):
        for j in range(15):
            X.append([base + (j % 3) + i for i in range(len(FEATURES_11))])
            y.append(label)
    pipe = Pipeline([("scale", StandardScaler()), ("clf", LogisticRegression(max_iter=500))])
    pipe.fit(np.array(X, dtype=float), y)
    return {"pipeline": pipe, "features": list(FEATURES_11), "classes": ["threat", "challenge"]}


class PredictDirectionTests(unittest.TestCase):
    def setUp(self):
        self._orig = ls._latest_bundle

    def tearDown(self):
        ls._latest_bundle = self._orig

    def test_no_model_returns_none(self):
        ls._latest_bundle = lambda: (None, None)
        self.assertIsNone(ls.predict_direction({k: 1.0 for k in FEATURES_11}))

    def test_non_dict_features_returns_none(self):
        ls._latest_bundle = lambda: ("v1", {"x": 1})
        self.assertIsNone(ls.predict_direction(None))
        self.assertIsNone(ls.predict_direction("nope"))

    @unittest.skipUnless(_HAS_SKLEARN, "scikit-learn not installed")
    def test_predicts_label_and_confidence(self):
        bundle = _make_bundle()
        ls._latest_bundle = lambda: ("v1", bundle)
        out = ls.predict_direction({k: 1.0 for k in FEATURES_11})
        self.assertIn(out["label"], bundle["classes"])
        self.assertIsInstance(out["confidence"], float)
        self.assertGreaterEqual(out["confidence"], 0.0)
        self.assertLessEqual(out["confidence"], 1.0)
        self.assertEqual(out["model_version"], "v1")

    @unittest.skipUnless(_HAS_SKLEARN, "scikit-learn not installed")
    def test_incomplete_features_returns_none(self):
        bundle = _make_bundle()
        ls._latest_bundle = lambda: ("v1", bundle)
        partial = {k: 1.0 for k in FEATURES_11[:5]}  # missing 6 features
        self.assertIsNone(ls.predict_direction(partial))


class DispatchTests(unittest.TestCase):
    def test_empty_snippets_noop(self):
        self.assertIsNone(ls.dispatch_shadow_predictions("s1", []))


if __name__ == "__main__":
    unittest.main()
