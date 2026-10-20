"""
STORY    As the founder, I want no model to be swapped in through a config
         row without the promotion flag, so that my speakers' Ideal Text is
         never written by an unapproved model.
OUTCOME
  O1  The set of runtime_config keys that can name a model is closed: every
      surface's key and every model key named in services/, routes/ or
      scripts/ is enumerated, and an unlisted key is refused, never read.
  O2  Reading an enumerated key is gated: a row is served only for a
      surface the founder named; otherwise the caller's default, also for
      the chat and copilot keys (R-13).
PROVES   O1 -> test_every_key_that_can_name_a_model_is_enumerated
         O2 -> test_a_row_is_served_only_when_its_surface_is_promoted,
               test_chat_model_ignores_runtime_config_when_promotion_disabled
WHY      R-13 / LEGACY-1 (Job 1 review 2026-09-22): runtime_config is
         service-role writable with no RLS.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path
from unittest import mock

from services import runtime_model_gate as gate
from services.ml_surface_contracts import SURFACES

ROOT = Path(__file__).resolve().parents[1]
MODEL_KEY = re.compile(r"[\"'](openai_(?:surface_model_[a-z_]+|[a-z_]*_model))[\"']")
SMUGGLED = "ft:gpt-4.1-mini:org:proj:smuggled"


class TheSetIsClosed(unittest.TestCase):

    def test_every_key_that_can_name_a_model_is_enumerated(self):
        for surface in SURFACES.values():
            self.assertIn(surface.runtime_config_key, gate.MODEL_CONFIG_KEYS, surface.id)
        named = {key for folder in ("services", "routes", "scripts")
                 for path in (ROOT / folder).rglob("*.py")
                 for key in MODEL_KEY.findall(path.read_text(errors="ignore"))}
        self.assertIn("openai_chat_model", named)
        self.assertEqual(named - gate.MODEL_CONFIG_KEYS, set())
        read = mock.Mock(return_value=SMUGGLED)
        with self.assertRaises(ValueError):
            gate.resolve_gated_model("openai_surface_model_new_thing", read=read)
        read.assert_not_called()


class ReadingAModelKeyIsGated(unittest.TestCase):

    def test_a_row_is_served_only_when_its_surface_is_promoted(self):
        key = "openai_surface_model_ideal_text"
        with mock.patch.object(gate, "promoted_keys", return_value=frozenset()):
            self.assertEqual(gate.resolve_gated_model(
                key, read=lambda _k: SMUGGLED, default="stock"), "stock")
        with mock.patch.object(gate, "promoted_keys", return_value=frozenset({key})):
            self.assertEqual(gate.resolve_gated_model(
                key, read=lambda _k: SMUGGLED, default="stock"), SMUGGLED)

    def test_chat_model_ignores_runtime_config_when_promotion_disabled(self):
        """R-13's own regression: the copilot/chat keys obey the same gate."""
        from services.openai_service import OpenAIService

        with mock.patch("services.runtime_model_gate.promoted_keys",
                        return_value=frozenset()), \
             mock.patch("services.db.db.get_runtime_config", return_value=SMUGGLED), \
             mock.patch("services.llm_client.build_openai_client", return_value=None):
            service = OpenAIService()
            self.assertNotEqual(service._chat_model("default"), SMUGGLED)
            self.assertNotEqual(service._chat_model("copilot"), SMUGGLED)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
