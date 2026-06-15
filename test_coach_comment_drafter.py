"""AI-Commentator drafter (willab Phase 4 / Prompt 2).

Tests the plain-language metric conversion, the take-comparison logic, and the
generate core with a FAKE OpenAIService injected — so it runs in the lean env
(no openai, no DB). The metric→plain-language conversion is the key fence: the
model must NEVER see raw F0/SD/dB.

Run: python3 -m unittest test_coach_comment_drafter
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


class MetricObservationsTests(unittest.TestCase):
    """The fence: metrics become plain words; raw acoustic terms never appear."""

    def _obs(self, m):
        from services.coach_comment_drafter import metric_observations
        return metric_observations(m)

    def test_full_metrics_to_plain_buckets(self):
        obs = self._obs(_FULL_METRICS)
        self.assertEqual(set(obs), {"pace", "pitch", "pauses", "volume", "clarity"})
        self.assertEqual(obs["pace"], "comfortable")
        self.assertEqual(obs["clarity"], "very clear")
        # never leak raw acoustic terms into the values
        blob = " ".join(obs.values()).lower()
        for jargon in ("f0", "sd", "db", "wpm", "coherence", "%"):
            self.assertNotIn(jargon, blob)

    def test_fast_slow_buckets(self):
        self.assertEqual(self._obs({"wpm": 80})["pace"], "a bit slow")
        self.assertEqual(self._obs({"wpm": 200})["pace"], "a bit fast")

    def test_speech_rate_alias(self):
        self.assertEqual(self._obs({"speech_rate": 135})["pace"], "comfortable")

    def test_partial_metrics_only_present_buckets(self):
        obs = self._obs({"wpm": 135})
        self.assertEqual(set(obs), {"pace"})

    def test_empty_metrics_empty(self):
        self.assertEqual(self._obs(None), {})
        self.assertEqual(self._obs({}), {})

    def test_bool_is_not_numeric(self):
        self.assertNotIn("pace", self._obs({"wpm": True}))


class CompareTakesTests(unittest.TestCase):
    def _cmp(self, a, b):
        from services.coach_comment_drafter import compare_takes
        return compare_takes(a, b)

    def test_faster_vs_prior(self):
        out = self._cmp({"pace": 160}, {"pace": 120})
        self.assertIn("faster", out)

    def test_more_controlled_vs_prior(self):
        out = self._cmp({"pace": 120}, {"pace": 160})
        self.assertIn("controlled", out)

    def test_about_the_same(self):
        out = self._cmp({"pace": 130}, {"pace": 132})
        self.assertIn("about the same", out)

    def test_nothing_comparable_returns_none(self):
        self.assertIsNone(self._cmp({}, {}))


class GenerateCoachNoteDraftTests(unittest.TestCase):
    def _gen(self, transcript, slide=_SLIDE, metrics=None, **kw):
        from services.coach_comment_drafter import generate_coach_note_draft
        return generate_coach_note_draft(transcript, slide, metrics, **kw)

    def test_produces_draft(self):
        _install_fake_openai()
        out = self._gen("and that's the ask", metrics=_FULL_METRICS,
                        goal="pitch the raise", take_comparison="pace a bit more controlled")
        self.assertTrue(out)

    def test_empty_transcript_returns_none(self):
        self.assertIsNone(self._gen(""))
        self.assertIsNone(self._gen("   "))

    def test_no_client_returns_none(self):
        _install_fake_openai(has_client=False)
        self.assertIsNone(self._gen("real transcript", metrics=_FULL_METRICS))
        _install_fake_openai()

    def test_unparseable_returns_none(self):
        _install_fake_openai(content="not json")
        self.assertIsNone(self._gen("real transcript"))
        _install_fake_openai()

    def test_works_without_metrics_or_goal(self):
        _install_fake_openai()
        self.assertTrue(self._gen("real transcript here"))


class DispatchTests(unittest.TestCase):
    def test_no_slides_is_noop(self):
        from services.coach_comment_drafter import dispatch_coach_note_drafts
        self.assertIsNone(dispatch_coach_note_drafts("s1", [{"id": "a"}], None, []))
        self.assertIsNone(dispatch_coach_note_drafts("s1", [], [_SLIDE], []))


if __name__ == "__main__":
    unittest.main()
