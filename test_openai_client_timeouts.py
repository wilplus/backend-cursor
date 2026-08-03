"""Strict OpenAI client timeouts (async-queue work 2026-08-03).

The debt being retired: no client timeout was ever set, so a hung OpenAI
call rode the SDK's 600s default inside a gunicorn worker — half the
backend's capacity at --workers 2. These tests pin:

  * Config defaults (120s LLM / 600s transcribe / 2 retries) + env
    override + malformed-env fallback (never crash import — live loop).
  * OpenAIService builds its client WITH timeout + max_retries.
  * transcribe_audio runs on a with_options client carrying the larger
    transcribe timeout (Whisper on a long take legitimately runs minutes).

Run: python3 -m unittest test_openai_client_timeouts
"""
from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import patch

for _m in ("supabase", "sentry_sdk"):
    if _m not in sys.modules:
        sys.modules[_m] = types.ModuleType(_m)
if not hasattr(sys.modules["supabase"], "create_client"):
    sys.modules["supabase"].create_client = lambda *a, **k: None  # type: ignore[attr-defined]
    sys.modules["supabase"].Client = object  # type: ignore[attr-defined]
if not hasattr(sys.modules["sentry_sdk"], "capture_exception"):
    sys.modules["sentry_sdk"].capture_exception = lambda *a, **k: None  # type: ignore[attr-defined]

try:
    import services.openai_service as osvc
    _IMPORT_ERR = None
except Exception as e:  # pragma: no cover
    osvc = None  # type: ignore[assignment]
    _IMPORT_ERR = e


class ConfigTimeoutTests(unittest.TestCase):

    def _fresh_config(self):
        from importlib import reload
        import config as config_mod
        return reload(config_mod).Config()

    def test_defaults(self):
        with patch.dict(os.environ, {}, clear=False):
            for k in ("OPENAI_TIMEOUT_SECONDS",
                      "OPENAI_TRANSCRIBE_TIMEOUT_SECONDS",
                      "OPENAI_MAX_RETRIES"):
                os.environ.pop(k, None)
            cfg = self._fresh_config()
        self.assertEqual(cfg.OPENAI_TIMEOUT_SECONDS, 120.0)
        self.assertEqual(cfg.OPENAI_TRANSCRIBE_TIMEOUT_SECONDS, 600.0)
        self.assertEqual(cfg.OPENAI_MAX_RETRIES, 2)

    def test_env_override(self):
        with patch.dict(os.environ, {
            "OPENAI_TIMEOUT_SECONDS": "30",
            "OPENAI_TRANSCRIBE_TIMEOUT_SECONDS": "900",
            "OPENAI_MAX_RETRIES": "0",
        }):
            cfg = self._fresh_config()
        self.assertEqual(cfg.OPENAI_TIMEOUT_SECONDS, 30.0)
        self.assertEqual(cfg.OPENAI_TRANSCRIBE_TIMEOUT_SECONDS, 900.0)
        self.assertEqual(cfg.OPENAI_MAX_RETRIES, 0)

    def test_malformed_env_falls_back_never_crashes(self):
        with patch.dict(os.environ, {
            "OPENAI_TIMEOUT_SECONDS": "ten minutes",
            "OPENAI_MAX_RETRIES": "??",
        }):
            cfg = self._fresh_config()
        self.assertEqual(cfg.OPENAI_TIMEOUT_SECONDS, 120.0)
        self.assertEqual(cfg.OPENAI_MAX_RETRIES, 2)


@unittest.skipIf(osvc is None, f"needs app deps: {_IMPORT_ERR}")
class OpenAIClientConstructionTests(unittest.TestCase):

    def test_client_built_with_timeout_and_retries(self):
        captured = {}

        class _FakeClient:
            def __init__(self, **kwargs):
                captured.update(kwargs)

        with patch.object(osvc.config, "OPENAI_API_KEY", "sk-test"), \
                patch.object(osvc.openai, "OpenAI", _FakeClient):
            svc = osvc.OpenAIService()
        self.assertIsNotNone(svc.client)
        self.assertEqual(captured.get("timeout"),
                         osvc.config.OPENAI_TIMEOUT_SECONDS)
        self.assertEqual(captured.get("max_retries"),
                         osvc.config.OPENAI_MAX_RETRIES)

    def test_no_key_still_builds_none_client(self):
        with patch.object(osvc.config, "OPENAI_API_KEY", ""):
            svc = osvc.OpenAIService()
        self.assertIsNone(svc.client)

    def test_transcribe_uses_with_options_transcribe_timeout(self):
        seen = {}

        class _Transcriptions:
            def create(self, **kwargs):
                seen["kwargs"] = kwargs
                return types.SimpleNamespace(text="hello", segments=[],
                                             words=None)

        class _OptClient:
            audio = types.SimpleNamespace(
                transcriptions=_Transcriptions())

        class _Client:
            def with_options(self, **kwargs):
                seen["options"] = kwargs
                return _OptClient()

        svc = osvc.OpenAIService.__new__(osvc.OpenAIService)
        svc.client = _Client()
        from io import BytesIO
        out = svc.transcribe_audio(BytesIO(b"RIFFxxxx"), "take.webm")
        self.assertEqual(
            seen["options"].get("timeout"),
            osvc.config.OPENAI_TRANSCRIBE_TIMEOUT_SECONDS,
        )
        self.assertEqual(out.get("text"), "hello")


if __name__ == "__main__":
    unittest.main()
