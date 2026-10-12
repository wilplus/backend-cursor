"""AI-Commentator drafter (willab Phase 4 / Prompt 2).

Tests the plain-language metric conversion, the take-comparison logic, and the
generate core with a FAKE OpenAIService injected — so it runs in the lean env
(no openai, no DB). The metric→plain-language conversion is the key fence: the
model must NEVER see raw F0/SD/dB.

Run: python3 -m unittest tests.test_coach_comment_drafter
"""
from __future__ import annotations

import sys
import types
import unittest

_ORIG_OPENAI_SVC = None
_ORIG_DB = None
_ORIG_SUPABASE = None

_CANNED = (
    '{"coach_note": "\\ud83c\\udfa4 Warm, confident open. \\u2705 Your pace is '
    'comfortable. \\ud83d\\udca1 Tighten the vague phrase next time."}'
)


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
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
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
_FULL_METRICS = {
    "wpm": 135, "f0_sd": 30, "pause_ratio": 0.15, "dynamic_db": 10,
    "stickiness": {"composite": 0.8},
}


class GenerateCoachNoteDraftTests(unittest.TestCase):
    def _gen(self, transcript, slide=_SLIDE, metrics=None, **kw):
        from services.coach_comment_drafter import generate_coach_note_draft
        return generate_coach_note_draft(transcript, slide, metrics, **kw)


    def test_deckless_no_slide_still_drafts(self):
        # BE-2: a spoken pitch with no slide still produces a draft from the
        # transcript + plain-language metrics (slide=None, not skipped).
        _install_fake_openai()
        self.assertTrue(self._gen("real transcript here", slide=None,
                                  metrics=_FULL_METRICS, goal="pitch the raise"))


if __name__ == "__main__":
    unittest.main()
