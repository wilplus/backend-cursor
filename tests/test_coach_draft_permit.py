"""A coach's AI draft takes the speaker's permit (second plan, Phase 1,
founder "go" 2026-10-05).

The coach's three drafts (a request answer, the Take word, a moment line)
send the speaker's transcript to the provider. They live under /v2/coach/,
outside the core gate, so the call went out with no permit even in enforce
mode. ``speaker_provider_route`` binds each one to the SPEAKER's current
authority: it resolves the Take's owner, requires current authorization and
opens the protected scope every provider call inside reads its permit from.
"""
from __future__ import annotations

import pathlib

import pytest

from services.processing_authorization import (
    ProcessingAuthorizationError,
    ProcessingAuthorizationService,
)

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture
def authority(monkeypatch):
    seen: dict = {}

    def resolve(self, principal_id, *, user_id=None, recording_id=None):
        seen["resolved"] = (principal_id, user_id)
        return principal_id or None

    def require(self, principal_id, *, operation):
        seen["required"] = (principal_id, operation)
        if seen.get("refuse"):
            raise ProcessingAuthorizationError(
                "PROCESSING_AUTHORIZATION_REQUIRED", "Not authorized.", 403)
        return None

    monkeypatch.setattr(ProcessingAuthorizationService,
                        "resolve_acquisition_principal", resolve)
    monkeypatch.setattr(ProcessingAuthorizationService, "require_current", require)
    return seen


@pytest.mark.parametrize("path, view", [
    ("routes/v2/coach.py", "def v2_coach_exercise_request_draft("),
    ("routes/v2/coach_words.py", "def v2_coach_take_word_draft("),
    ("routes/v2/coach_words.py", "def v2_coach_moment_line_draft("),
])
def test_every_coach_draft_route_takes_the_permit(path, view):
    source = (ROOT / path).read_text()
    head = source[:source.index(view)].rsplit("@v2_bp.route", 1)[1]
    assert "@speaker_provider_route" in head, f"{view} sends words without a permit"
