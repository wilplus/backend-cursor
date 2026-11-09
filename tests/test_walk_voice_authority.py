"""
STORY    As a speaker, I want Will's written walk message to be made only under
         my Take's processing authorization, so that no word of my Take
         reaches the AI provider without a permit we can record and delete.
OUTCOME
  O1  When the authorization mode enforces, the GPT-4o call that writes
      Will's message runs inside my Take's protected provider scope, bound
      to my principal and my Take; with no principal for the Take, no call
      is made and the walk says its signed line.
PROVES   O1 -> test_wills_message_is_written_only_inside_my_takes_protected_scope
WHY      CLAUDE.md How to ship: every provider call goes through the
         processing-authorization path (N565, services/walk_voice.py).
"""
from types import SimpleNamespace

import pytest

from services import walk_voice
from services.authorized_provider import scoped_adapter


class _Db:
    def v2_get_session_by_id(self, take_id):
        return {"id": take_id, "user_id": "me", "owner_principal_id": "principal-1",
                "take_index": 2, "arc_id": "arc"}

    def get_snippets_by_session(self, take_id):
        return [{"id": "s1", "transcript": "So that you can learn together.", "metrics": {}}]


class _Authorization:
    principal: "str | None" = "principal-1"

    def __init__(self, database):
        self.enforced = True

    def resolve_acquisition_principal(self, owner_principal_id, user_id=None):
        return self.principal if owner_principal_id == "principal-1" else None


@pytest.fixture
def calls(monkeypatch):
    seen: list = []
    monkeypatch.setattr("services.rings.feature_is_on_for_user",
                        lambda feature, user, database=None: True)
    monkeypatch.setattr("services.processing_authorization.ProcessingAuthorizationService",
                        _Authorization)
    for part in ("_note", "_level", "_last"):
        monkeypatch.setattr(walk_voice, part, lambda *a: None)

    def chat_complete(**kwargs):
        seen.append(scoped_adapter())
        return SimpleNamespace(text="Want to try it slower?")
    monkeypatch.setattr("services.llm.chat_complete", chat_complete)
    return seen


def test_wills_message_is_written_only_inside_my_takes_protected_scope(calls, monkeypatch):
    assert walk_voice.write(_Db(), "me", "take-1", "try", "s1") == "Want to try it slower?"
    adapter = calls[0]
    assert adapter is not None, "the provider was called outside the Take's scope"
    assert adapter.coordinates.acquisition_principal_id == "principal-1"
    assert adapter.coordinates.take_id == "take-1"
    # Outside the write, no scope is left behind.
    assert scoped_adapter() is None

    # No principal for the Take: no call, the signed line.
    monkeypatch.setattr(_Authorization, "principal", None)
    assert walk_voice.write(_Db(), "me", "take-1", "try", "s1") is None
    assert len(calls) == 1
