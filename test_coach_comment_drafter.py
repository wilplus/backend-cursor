"""AI-Commentator drafter (willab Phase 4 / Prompt 2).

Tests the testable core (generate_coach_note_draft) with a FAKE OpenAIService
injected into sys.modules — so it runs in the lean env (no openai, no DB). The
process hook + frozen DB write are exercised in CI route/db tests.

Run: python3 -m unittest test_coach_comment_drafter
"""
from __future__ import annotations

import sys
import types
import unittest


_ORIG_OPENAI_SVC = None
_ORIG_DB = None
_ORIG_SUPABASE = None

_CANNED = '{"coach_note": "You hit the ask, but let the price land next time."}'


class _FakeMsg:
    def __init__(self, content):
        self.content = content


class _FakeChoice:
    def __init__(self, content):
        self.message = _FakeMsg(content)


class _FakeResp:
    def __init__(self, content):
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content):
        self._content = content

    def create(self, **kwargs):
        return _FakeResp(self._content)


class _FakeClient:
    def __init__(self, content):
        self.chat = types.SimpleNamespace(completions=_FakeCompletions(content))


def _install_fake_openai(content=_CANNED, has_client=True):
    mod = types.ModuleType("services.openai_service")

    class _FakeOpenAIService:
        def __init__(self):
            self.client = _FakeClient(content) if has_client else None

    mod.OpenAIService = _FakeOpenAIService
    sys.modules["services.openai_service"] = mod


def setUpModule():
    global _ORIG_OPENAI_SVC, _ORIG_DB, _ORIG_SUPABASE
    _ORIG_OPENAI_SVC = sys.modules.get("services.openai_service")
    _ORIG_DB = sys.modules.get("services.db")
    _ORIG_SUPABASE = sys.modules.get("supabase")
    # coach_comment_drafter._draft_all imports services.db lazily; keep import
    # safe even though these unit tests don't exercise the worker.
    from unittest.mock import MagicMock
    sys.modules["supabase"] = MagicMock()
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub
    _install_fake_openai()


def _restore(name, orig):
    if orig is not None:
        sys.modules[name] = orig
    else:
        sys.modules.pop(name, None)


def tearDownModule():
    _restore("services.openai_service", _ORIG_OPENAI_SVC)
    _restore("services.db", _ORIG_DB)
    _restore("supabase", _ORIG_SUPABASE)


_SLIDE = {"index": 2, "title": "The ask", "body": "We're raising $2M at $10M."}


class GenerateCoachNoteDraftTests(unittest.TestCase):
    def _gen(self, transcript, slide=_SLIDE, sticky=None):
        from services.coach_comment_drafter import generate_coach_note_draft
        return generate_coach_note_draft(transcript, slide, sticky)

    def test_produces_draft_from_transcript_and_slide(self):
        _install_fake_openai()
        out = self._gen("and that's the ask, two million at ten")
        self.assertTrue(out)
        self.assertIn("ask", out.lower())

    def test_empty_transcript_returns_none_without_llm(self):
        self.assertIsNone(self._gen(""))
        self.assertIsNone(self._gen("   "))

    def test_no_client_returns_none(self):
        _install_fake_openai(has_client=False)
        self.assertIsNone(self._gen("some real transcript here"))
        _install_fake_openai()  # restore for other tests

    def test_unparseable_output_returns_none(self):
        _install_fake_openai(content="not json at all")
        self.assertIsNone(self._gen("some real transcript here"))
        _install_fake_openai()

    def test_blank_coach_note_returns_none(self):
        _install_fake_openai(content='{"coach_note": "   "}')
        self.assertIsNone(self._gen("some real transcript here"))
        _install_fake_openai()

    def test_stickiness_is_optional(self):
        _install_fake_openai()
        out = self._gen("the numbers part", sticky={"composite": 0.8})
        self.assertTrue(out)


class DispatchTests(unittest.TestCase):
    def test_no_slides_is_noop(self):
        from services.coach_comment_drafter import dispatch_coach_note_drafts
        # No slides / no snippets → returns without spawning anything.
        self.assertIsNone(dispatch_coach_note_drafts("s1", [{"id": "a"}], None, []))
        self.assertIsNone(dispatch_coach_note_drafts("s1", [], [_SLIDE], []))


if __name__ == "__main__":
    unittest.main()
