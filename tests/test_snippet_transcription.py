import pytest

from services import snippet_transcription


def test_strict_provider_mode_records_missing_client_as_uncertain(monkeypatch):
    monkeypatch.setattr(snippet_transcription.openai_service, "client", None)

    with pytest.raises(
        snippet_transcription.SnippetTranscriptionProviderError,
        match="openai_client_not_initialized",
    ):
        snippet_transcription.transcribe_snippet_bytes(
            b"audio",
            raise_on_provider_error=True,
        )


def test_existing_best_effort_mode_remains_non_throwing(monkeypatch):
    monkeypatch.setattr(snippet_transcription.openai_service, "client", None)

    assert snippet_transcription.transcribe_snippet_bytes(b"audio") is None

