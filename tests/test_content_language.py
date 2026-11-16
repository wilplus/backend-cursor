from types import SimpleNamespace

from services.content_language import (
    complete_in_language,
    detect_typed_language,
    resolve_content_language,
    validate_output_language,
)


def test_content_language_uses_recording_before_typed_message():
    assert resolve_content_language(
        recording_language="pl", typed_message="This is an English message"
    ) == "pl"


def test_content_language_detects_polish_and_english_typed_messages():
    assert detect_typed_language("Cześć, więc chcę ćwiczyć") == "pl"
    assert detect_typed_language("This is a message for your talk") == "en"


def test_output_language_validation_distinguishes_polish_and_english():
    assert validate_output_language("To jest krótka odpowiedź.", "pl")
    assert not validate_output_language("This is a short answer.", "pl")
    assert validate_output_language("This is a short answer.", "en")


def test_language_generation_retries_once_then_returns_valid_result():
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text="This is an English answer." if len(calls) == 1
                               else "To jest polska odpowiedź.")

    result = complete_in_language(
        generate, target_language="pl", system="system", user="user"
    )
    assert result.text == "To jest polska odpowiedź."
    assert len(calls) == 2
    assert "TARGET CONTENT LANGUAGE" in calls[0]["system"]


def test_language_generation_is_bounded_when_both_outputs_fail():
    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(text="This is an English answer.")

    assert complete_in_language(
        generate, target_language="pl", system="system", user="user"
    ) is None
    assert len(calls) == 2
