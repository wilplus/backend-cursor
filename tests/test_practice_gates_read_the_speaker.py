"""
STORY    As a speaker who accepted the policy in force, I want my exercise and
         the cues that route it, whatever older recording the Take is read
         through, so that the walk offers me what my Data & consent page
         says is on (WIL-90; founder 2026-10-20).
OUTCOME
  O1  The Manager's exercise offer asks about me as my own page reads me
      (`take_speaker_principal`), never about one recording's acquirer.
  O2  The verbal-cue gate asks the same question of the same person.
PROVES   O1 -> test_the_exercise_offer_reads_the_speaker_as_their_page_does
         O2 -> test_the_cue_gate_reads_the_speaker_as_their_page_does
WHY      #1206 moved the coach's gate; the Manager's offer and the cues still
         read the recording's acquirer, so an older or claimed Take got no
         exercise while the page showed practice on.
"""
from __future__ import annotations

from types import SimpleNamespace

from services import processing_authorization as pa


class _Service:
    enforced = True
    asked: list[str] = []

    def __init__(self, _database):
        pass

    def take_speaker_principal(self, take_id):
        _Service.asked.append(("speaker", str(take_id)))
        return "speaker-principal"

    def take_acquisition_principal(self, take_id):
        raise AssertionError("the recording's acquirer is the wrong person")

    def choice_permitted(self, principal, choice):
        return principal == "speaker-principal" and choice == pa.PERSONALISED_PRACTICE


def test_the_exercise_offer_reads_the_speaker_as_their_page_does(monkeypatch):
    from services.ideal_text_changes import _ChangesRun
    _Service.asked = []
    monkeypatch.setattr(pa, "ProcessingAuthorizationService", _Service)
    run = SimpleNamespace(db=object(), arm_sid="take-9")
    assert _ChangesRun._practice_permitted(run) is True
    assert _Service.asked == [("speaker", "take-9")]


def test_the_cue_gate_reads_the_speaker_as_their_page_does(monkeypatch):
    from services import verbal_cues
    _Service.asked = []
    monkeypatch.setattr(pa, "ProcessingAuthorizationService", _Service)
    assert verbal_cues._practice_permitted(object(), "take-9") is True
    assert _Service.asked == [("speaker", "take-9")]
