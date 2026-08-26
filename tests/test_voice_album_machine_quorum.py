from services.voice_album import _machine_confident


def test_neutral_review_nomination_is_not_machine_yes():
    assert _machine_confident({"kind": "emphasize", "trigger": "confident"})
    assert _machine_confident({"kind": "emphasize", "trigger": "charisma"})
    assert not _machine_confident({
        "kind": "emphasize", "trigger": "confidence_review",
    })
