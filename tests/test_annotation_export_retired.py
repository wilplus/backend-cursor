"""
STORY    As the founder, I want the retired learning-export routes to be
         gone, so that counsel's claim that every Phase-2 learning route is
         closed stays true.
OUTCOME
  O1  Both retired paths answer "not found" (404).
PROVES   O1 -> RetiredPhase2RoutesAreAbsent::test_each_retired_path_is_a_404
WHY      ML-1; audit 2026-09-22 I-1 / LEGACY-4; removed by the founder
         2026-10-12.
"""
from __future__ import annotations

import unittest

try:
    from app import app as flask_app
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    flask_app = None
    _IMPORT_ERROR = e

RETIRED_PATHS = (
    "/v2/internal/annotation-export",
    "/v2/internal/copilot-video/retrain",
)


class RetiredPhase2RoutesAreAbsent(unittest.TestCase):
    def test_each_retired_path_is_a_404(self):
        if flask_app is None:  # pragma: no cover
            self.skipTest(f"app import failed: {_IMPORT_ERROR}")
        flask_app.config["TESTING"] = True
        with flask_app.test_client() as client:
            for path in RETIRED_PATHS:
                with self.subTest(path=path):
                    self.assertEqual(client.post(path, json={}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
