"""
STORY    As the founder, I can verify the configured Mistral endpoint with
         synthetic English, Polish, and JSON before any speaker is routed.
OUTCOME
  O1  The smoke check proves plain English, Polish, and structured JSON.
  O2  It refuses to run without an explicit key and model.
  O3  Its report never contains the API key or synthetic response text.
PROVES
  O1 -> test_the_smoke_check_covers_english_polish_and_structured_json
  O2 -> test_the_command_refuses_without_the_key_or_model
  O3 -> test_the_command_reports_only_case_status_and_latency
WHY      A three-call check catches access, language, and response-contract
         failures before one low-risk production surface is enabled.
"""
from __future__ import annotations

from types import SimpleNamespace

from scripts import mistral_smoke


class _Completions:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        text = next(self.replies)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        )


def _client(*replies):
    completions = _Completions(replies)
    return SimpleNamespace(
        chat=SimpleNamespace(completions=completions),
        completions=completions,
    )


def test_the_smoke_check_covers_english_polish_and_structured_json():
    client = _client(
        "READY",
        "Mówię po polsku.",
        '{"status":"ok","language":"pl"}',
    )

    mistral_smoke.run_smoke(client, "mistral-small-2603", emit=lambda _line: None)

    calls = client.completions.calls
    assert len(calls) == 3
    assert "response_format" not in calls[0]
    assert "response_format" not in calls[1]
    assert calls[2]["response_format"] == {"type": "json_object"}
    assert all(call["model"] == "mistral-small-2603" for call in calls)


def test_the_command_refuses_without_the_key_or_model(monkeypatch, capsys):
    monkeypatch.setattr(mistral_smoke.Config, "MISTRAL_API_KEY", "")
    monkeypatch.setattr(mistral_smoke.Config, "MISTRAL_MODEL", "")

    assert mistral_smoke.main() == 2
    assert "MISTRAL_API_KEY is not configured" in capsys.readouterr().err


def test_the_command_reports_only_case_status_and_latency(monkeypatch, capsys):
    secret = "never-print-this-secret"
    client = _client(
        "READY",
        "Mówię po polsku.",
        '{"status":"ok","language":"pl"}',
    )
    monkeypatch.setattr(mistral_smoke.Config, "MISTRAL_API_KEY", secret)
    monkeypatch.setattr(mistral_smoke.Config, "MISTRAL_MODEL", "mistral-small-2603")
    monkeypatch.setattr(mistral_smoke.Config, "MISTRAL_BASE_URL", "https://example.invalid/v1")
    monkeypatch.setattr(mistral_smoke, "build_chat_client", lambda _target: client)

    assert mistral_smoke.main() == 0

    output = capsys.readouterr()
    assert secret not in output.out + output.err
    assert "Mówię po polsku" not in output.out + output.err
    assert "PASS english_plain" in output.out
    assert "PASS polish_plain" in output.out
    assert "PASS structured_json" in output.out
    assert "Mistral smoke check: PASS" in output.out
