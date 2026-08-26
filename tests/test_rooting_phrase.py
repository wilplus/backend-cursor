from services.rooting_phrase import propose_rooting_phrase, validate_rooting_phrase


def test_proposal_is_an_exact_visible_span():
    text = "The pause before a sentence is the room deciding to listen."
    proposal = propose_rooting_phrase(text)
    assert proposal is not None
    assert text[proposal["start"]:proposal["end"]] == proposal["text"]
    assert 1 <= len(proposal["text"].split()) <= 7


def test_validation_refuses_paraphrase_offsets_and_marker_grammar():
    text = "Make these exact words memorable."
    assert validate_rooting_phrase(text, "exact words", 11, 22) == {
        "text": "exact words", "start": 11, "end": 22,
    }
    assert validate_rooting_phrase(text, "better words", 11, 23) is None
    assert validate_rooting_phrase("{{orange:exact}}", "{{orange:exact}}", 0, 16) is None
