"""willab — BE-7 (founder fix-pack 2026-07-16): the coach feedback video
size cap is env-tunable.

Both upload endpoints (POST /v2/coach/sessions/<sid>/video and
POST .../snippets/<snip_id>/breakthrough-video) already read
``getattr(config, "COACH_FEEDBACK_VIDEO_MAX_MB", 100)`` — but the attr was
never defined in config.py, so the cap was a hardcoded 100 MB. It is now a
real env-driven Config attr (default 100) parsed via ``_env_int``, whose
malformed-value guard means a bad env var can never crash import (live
loop). No route changes.

The reload-shaped test loads config.py as a FRESH probe module instead of
``importlib.reload``-ing the shared ``config`` module, so the rest of a
single-process suite run (CI runs everything in one pytest process) never
sees a mutated Config class.

Run: python3 -m unittest test_video_size_cap_config
"""
from __future__ import annotations

import importlib.util
import os
import unittest
from unittest.mock import patch

try:
    from config import Config, _env_int
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Config = None
    _env_int = None
    _IMPORT_ERROR = e

_CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "config.py")


def _load_fresh_config():
    """Execute config.py as a new, uncached module (the current os.environ
    applies) without touching the shared ``config`` module."""
    spec = importlib.util.spec_from_file_location(
        "config_probe_be7", _CONFIG_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class VideoSizeCapConfigTests(unittest.TestCase):

    def test_attr_exists_with_default_100(self):
        self.assertTrue(hasattr(Config, "COACH_FEEDBACK_VIDEO_MAX_MB"))
        if not (os.getenv("COACH_FEEDBACK_VIDEO_MAX_MB") or "").strip():
            # no override in this environment ⇒ the historical 100 MB cap
            self.assertEqual(Config.COACH_FEEDBACK_VIDEO_MAX_MB, 100)

    def test_env_override_applies(self):
        with patch.dict(os.environ, {"COACH_FEEDBACK_VIDEO_MAX_MB": "250"}):
            self.assertEqual(
                _env_int("COACH_FEEDBACK_VIDEO_MAX_MB", 100), 250)
            self.assertEqual(
                _load_fresh_config().Config.COACH_FEEDBACK_VIDEO_MAX_MB, 250)

    def test_malformed_env_falls_back_never_crashes(self):
        for bad in ("banana", "10MB", "1.5", " ", ""):
            with patch.dict(os.environ,
                            {"COACH_FEEDBACK_VIDEO_MAX_MB": bad}):
                self.assertEqual(
                    _env_int("COACH_FEEDBACK_VIDEO_MAX_MB", 100), 100, bad)
                # import must survive the bad value (live loop)
                self.assertEqual(
                    _load_fresh_config().Config.COACH_FEEDBACK_VIDEO_MAX_MB,
                    100, bad)

    def test_unset_env_falls_back(self):
        env = {k: v for k, v in os.environ.items()
               if k != "COACH_FEEDBACK_VIDEO_MAX_MB"}
        with patch.dict(os.environ, env, clear=True):
            self.assertEqual(
                _env_int("COACH_FEEDBACK_VIDEO_MAX_MB", 100), 100)


if __name__ == "__main__":
    unittest.main()
