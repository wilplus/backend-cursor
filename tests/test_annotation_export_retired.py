"""The daily annotation export is retired, and stays retired (ML-1; audit
2026-09-22 I-1 / LEGACY-4).

The route answers 410 (routes/phase2_guard), so a cron that POSTed to it
failed every run. The cron script and its Dockerfile are gone so a dead job
cannot be re-provisioned; the pairs the coach's answers make are read by the
weekly job that a later, separately authorised door opens (build plan ML-9).
"""
from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]

try:
    from app import app as flask_app
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    flask_app = None
    _IMPORT_ERROR = e


class AnnotationExportRetiredTests(unittest.TestCase):
    def test_the_cron_and_its_dockerfile_are_gone(self):
        self.assertFalse((ROOT / "bin" / "railway-annotation-export-cron.sh").exists())
        self.assertFalse((ROOT / "Dockerfile.annotation-cron").exists())

    def test_the_route_is_a_410(self):
        if flask_app is None:  # pragma: no cover
            self.skipTest(f"app import failed: {_IMPORT_ERROR}")
        flask_app.config["TESTING"] = True
        with flask_app.test_client() as client:
            response = client.post("/v2/internal/annotation-export", json={})
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.get_json().get("code"), "PHASE2_DISABLED")


if __name__ == "__main__":
    unittest.main()
