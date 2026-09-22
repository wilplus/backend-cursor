"""Every model name `runtime_config` can serve is enumerated and gated.

R-13 (minor, Job 1 review 2026-09-22), same class as LEGACY-1 for the
non-learned surfaces. ``OpenAIService._chat_model`` resolves
``openai_chat_model`` and ``openai_copilot_model`` straight out of
``runtime_config`` with a sixty-second cache. The table is service-role
writable, has no RLS and (before this workstream) no trigger, and the repo
contains no writer for either key — so a row that appeared in it would be
served to every chat and copilot call with no flag, no evaluation and no
provenance, and nothing in the codebase would be surprised.

Two properties, both of which must hold for the surface keys too:

  1. the set of runtime_config keys that can name a model is CLOSED — a new
     key cannot be read into a model id without being added here;
  2. reading one is GATED — the promotion flag decides, not the row.
"""
from __future__ import annotations

import ast
import pathlib
import unittest
from unittest import mock


REPO = pathlib.Path(__file__).resolve().parents[1]


def _runtime_config_key_literals() -> set[str]:
    """Every string literal handed to `get_runtime_config` in the tree."""
    found: set[str] = set()
    for path in [*(REPO / "services").rglob("*.py"),
                 *(REPO / "scripts").rglob("*.py"),
                 *(REPO / "routes").rglob("*.py")]:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - not our problem here
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name != "get_runtime_config":
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.add(arg.value)
    return found


class TheModelKeysAreAClosedSet(unittest.TestCase):
    def test_every_read_key_is_on_the_allowlist(self):
        from services.runtime_model_gate import MODEL_CONFIG_KEYS

        for key in _runtime_config_key_literals():
            with self.subTest(key=key):
                self.assertIn(key, MODEL_CONFIG_KEYS)

    def test_every_trainable_surface_key_is_on_the_allowlist(self):
        from services.ml_surface_contracts import SURFACES
        from services.runtime_model_gate import MODEL_CONFIG_KEYS

        for contract in SURFACES.values():
            with self.subTest(surface=contract.id):
                self.assertIn(contract.runtime_config_key, MODEL_CONFIG_KEYS)

    def test_the_two_unlearned_chat_keys_are_named(self):
        from services.runtime_model_gate import MODEL_CONFIG_KEYS

        self.assertIn("openai_chat_model", MODEL_CONFIG_KEYS)
        self.assertIn("openai_copilot_model", MODEL_CONFIG_KEYS)


class ReadingAModelKeyIsGated(unittest.TestCase):
    def test_chat_model_ignores_runtime_config_when_promotion_disabled(self):
        """R-13's own regression: the copilot/chat keys obey the same gate."""
        from services.openai_service import OpenAIService

        with mock.patch("services.runtime_model_gate.promotion_is_enabled",
                        return_value=False), \
             mock.patch("services.db.db.get_runtime_config",
                        return_value="ft:gpt-4.1-mini:org:proj:smuggled"), \
             mock.patch("services.llm_client.build_openai_client", return_value=None):
            service = OpenAIService()
            self.assertNotEqual(service._chat_model("default"), "ft:gpt-4.1-mini:org:proj:smuggled")
            self.assertNotEqual(service._chat_model("copilot"), "ft:gpt-4.1-mini:org:proj:smuggled")

    def test_an_unknown_key_is_never_resolved_into_a_model(self):
        from services.runtime_model_gate import resolve_gated_model

        with self.assertRaises(ValueError):
            resolve_gated_model("openai_surface_model_not_a_surface", read=lambda k: "ft:x")


class TheDatabaseRefusesTheWriteToo(unittest.TestCase):
    """Defence in depth: the Python gate cannot bind a psql session."""

    def test_a_migration_guards_every_model_key(self):
        from services.runtime_model_gate import MODEL_CONFIG_KEYS

        sql = (REPO / "migrations"
               / "guard_runtime_config_model_keys.sql").read_text(encoding="utf-8")
        self.assertIn("BEFORE INSERT OR UPDATE", sql.upper())
        self.assertIn("runtime_config", sql)
        for key in MODEL_CONFIG_KEYS:
            with self.subTest(key=key):
                # Either named outright or covered by the surface prefix.
                self.assertTrue(
                    key in sql or "openai_surface_model_%" in sql,
                    f"{key} is not guarded by the trigger",
                )

    def test_the_guard_is_in_the_manifest(self):
        manifest = (REPO / "migrations" / "manifest.txt").read_text(encoding="utf-8")
        self.assertIn("guard_runtime_config_model_keys.sql", manifest)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
