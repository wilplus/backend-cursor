"""The retired Phase-2 learning routes stay closed (ML-1; audit 2026-09-22
I-1 / LEGACY-4).

The annotation export and the copilot-video retrain answered 410 on every
request until 2026-10-12, when the founder had both removed. A retired path is
now closed by absence: the server has no such route and answers 404. This is
the evidence behind the counsel claim that every Phase-2 learning route is
fail-closed.
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
