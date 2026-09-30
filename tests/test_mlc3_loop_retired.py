"""The MLC-3 service loop is retired, and stays retired (ML-15; founder
2026-09-30, L8; contract 66).

The nineteen speaker routes under /v2/user/mlc3/... and the eight coach
routes under /v2/coach/mlc3/... answer 410 GONE through one tombstone per
module, the way routes/v2/arcs.py and routes/phase2_guard.py retire a door.
The composers' lanes (routes/v2/coach_guidance_delivery.py and the bundle
module's coach feedback-language route) are gone; the monitors' cron
scripts, the readiness checkers and their CLIs are gone; the coach corpus
queue never hands out an MLC-3 inline blind assignment again. The tables
and migrations stay, and the one live route under the /user/mlc3 prefix —
the bundle module's exercise-correlation read — is not shadowed.
"""
from __future__ import annotations

import pathlib
import unittest
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]

flask_app: Any
_IMPORT_ERROR: Exception | None
try:
    from app import app as flask_app
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    flask_app = None
    _IMPORT_ERROR = e

U = "11111111-1111-1111-1111-111111111111"
V = "22222222-2222-2222-2222-222222222222"

# A representative sample of the 27 retired paths, both modules, every
# method the loop used.
RETIRED = (
    ("POST", "/v2/user/mlc3/feedback/render"),
    ("POST", "/v2/user/mlc3/feedback/respond"),
    ("POST", "/v2/user/mlc3/feedback/speaker"),
    ("POST", "/v2/user/mlc3/exercise-offers"),
    ("GET", f"/v2/user/mlc3/exercise-offers/{U}"),
    ("GET", f"/v2/user/mlc3/exercise-offers/{U}/playback"),
    ("POST", f"/v2/user/mlc3/exercise-offers/{U}/events"),
    ("POST", f"/v2/user/mlc3/exercise-offers/{U}/practice-sessions"),
    ("GET", f"/v2/user/mlc3/practice-sessions/{U}"),
    ("POST", f"/v2/user/mlc3/practice-sessions/{U}/events"),
    ("POST", f"/v2/user/mlc3/practice-sessions/{U}/attempts"),
    ("POST", f"/v2/user/mlc3/practice-sessions/{U}/preference"),
    ("GET", f"/v2/user/mlc3/practice-attempts/{U}/playback"),
    ("POST", f"/v2/user/mlc3/practice-attempts/{U}/speaker"),
    ("GET", f"/v2/user/mlc3/guidance/{U}"),
    ("GET", f"/v2/user/mlc3/guidance/{U}/playback"),
    ("POST", f"/v2/user/mlc3/guidance/{U}/events"),
    ("GET", f"/v2/coach/mlc3/reviews/playback/{U}"),
    ("GET", f"/v2/coach/mlc3/source-playback/{U}"),
    ("POST", f"/v2/coach/mlc3/inline/assignments/{U}/render"),
    ("POST", f"/v2/coach/mlc3/inline/assignments/{U}/judgments"),
    ("GET", f"/v2/coach/mlc3/reviews/{U}"),
    ("POST", f"/v2/coach/mlc3/reviews/assignments/{U}/render"),
    ("POST", f"/v2/coach/mlc3/reviews/assignments/{U}/judgments"),
    ("POST", f"/v2/coach/mlc3/reviews/{U}/complete"),
)

DELETED = (
    "bin/railway-mlc3-founder-canary-monitor.sh",
    "bin/railway-mlc3-general-service-monitor.sh",
    "scripts/monitor_mlc3_founder_canary.py",
    "scripts/monitor_mlc3_general_service.py",
    "services/mlc3_founder_canary_monitor.py",
    "services/mlc3_general_service_monitor.py",
    "services/mlc3_founder_canary_readiness.py",
    "services/mlc3_general_service_readiness.py",
    "scripts/check_mlc3_founder_canary_readiness.py",
    "scripts/check_mlc3_general_service_readiness.py",
    "scripts/rehearse_mlc3_founder_r2.py",
    "scripts/sign_mlc3_founder_deployment_attestation.py",
    "scripts/mlc3_repoint_rollout_to_active_policy.sql",
    "routes/v2/coach_guidance_delivery.py",
)


class Mlc3LoopRetiredTests(unittest.TestCase):
    def _client(self):
        if flask_app is None:  # pragma: no cover
            self.skipTest(f"app import failed: {_IMPORT_ERROR}")
        flask_app.config["TESTING"] = True
        return flask_app.test_client()

    def test_every_retired_path_is_a_410(self):
        with self._client() as client:
            for method, path in RETIRED:
                with self.subTest(method=method, path=path):
                    response = client.open(path, method=method, json={})
                    self.assertEqual(response.status_code, 410)
                    body = response.get_json()
                    self.assertEqual(body.get("code"), "GONE")
                    self.assertIn("retired", body.get("error", ""))

    def test_the_tombstones_keep_their_modules_and_registration(self):
        from routes.v2 import DOMAIN_MODULES

        self.assertIn("mlc3_first_client_service", DOMAIN_MODULES)
        self.assertIn("mlc3_first_client_coach", DOMAIN_MODULES)
        self.assertNotIn("coach_guidance_delivery", DOMAIN_MODULES)

    def test_the_bundle_exercise_correlation_read_is_not_shadowed(self):
        if flask_app is None:  # pragma: no cover
            self.skipTest(f"app import failed: {_IMPORT_ERROR}")
        adapter = flask_app.url_map.bind("localhost")
        endpoint, _args = adapter.match(
            f"/v2/user/mlc3/confident-moment-exercise/{U}/{V}", method="GET",
        )
        self.assertTrue(
            endpoint.endswith("get_confident_moment_exercise_correlation"),
            endpoint,
        )
        gone, _args = adapter.match(
            f"/v2/user/mlc3/exercise-offers/{U}", method="GET",
        )
        self.assertTrue(gone.endswith("v2_mlc3_user_service_retired"), gone)

    def test_the_composers_routes_are_gone(self):
        if flask_app is None:  # pragma: no cover
            self.skipTest(f"app import failed: {_IMPORT_ERROR}")
        rules = {rule.rule for rule in flask_app.url_map.iter_rules()}
        for prefix in (
            "/v2/coach/guidance/",
            "/v2/coach/confident-moment-bundles/",
        ):
            with self.subTest(prefix=prefix):
                self.assertFalse(
                    [rule for rule in rules if rule.startswith(prefix)],
                    prefix,
                )
        self.assertFalse(
            [rule for rule in rules if rule.endswith("/feedback-language")]
        )

    def test_the_monitors_readiness_and_composers_files_are_gone(self):
        for relative in DELETED:
            with self.subTest(path=relative):
                self.assertFalse((ROOT / relative).exists(), relative)

    def test_the_coach_queue_never_hands_out_an_inline_assignment(self):
        from routes.v2 import coach

        self.assertIs(coach._inline_authoring_for(U), False)
        self.assertFalse(hasattr(coach, "_coach_inline_authoring_queue"))
        self.assertFalse(hasattr(coach, "_coach_inline_canonical_queue_rows"))

    def test_the_serving_gates_are_untouched(self):
        # runtime_is_enabled / inline_authoring_is_enabled still gate V3
        # serving (config.py); the loop's retirement changed no flag.
        from services import coach_guidance_delivery

        self.assertTrue(callable(coach_guidance_delivery.runtime_is_enabled))
        self.assertTrue(
            callable(coach_guidance_delivery.inline_authoring_is_enabled)
        )


if __name__ == "__main__":
    unittest.main()
