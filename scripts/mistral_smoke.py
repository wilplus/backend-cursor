#!/usr/bin/env python3
"""Run three synthetic checks through the configured Mistral chat endpoint.

This is an operator smoke check, not a production surface. It sends no user
data and deliberately bypasses the protected-generation boundary, whose
permits exist for processing a speaker's data. The client and endpoint are
the same production transport used by ``services.llm.chat_complete``.

The key is read only from ``MISTRAL_API_KEY`` and is never printed. Production
routing remains disabled until ``MISTRAL_TEXT_SURFACES`` is explicitly set.
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any, Callable

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from config import Config  # noqa: E402
from services.chat_provider import ChatTarget, build_chat_client  # noqa: E402


class SmokeFailure(RuntimeError):
    """The configured Mistral endpoint did not satisfy a basic contract."""


def _content(response: Any) -> str:
    try:
        return str(response.choices[0].message.content or "").strip()
    except (AttributeError, IndexError, TypeError) as error:
        raise SmokeFailure("the endpoint returned an unexpected response shape") from error


def _exact(expected: str) -> Callable[[str], None]:
    def validate(text: str) -> None:
        if text.strip() != expected:
            raise SmokeFailure(f"expected {expected!r}, received {text!r}")
    return validate


def _polish(text: str) -> None:
    if "mówię po polsku" not in text.casefold():
        raise SmokeFailure("the Polish check did not remain in Polish")


def _structured(text: str) -> None:
    try:
        payload = json.loads(text)
    except (TypeError, ValueError) as error:
        raise SmokeFailure("the structured check was not valid JSON") from error
    if payload != {"status": "ok", "language": "pl"}:
        raise SmokeFailure(f"unexpected structured payload: {payload!r}")


def run_smoke(client: Any, model: str, *, emit: Callable[[str], None] = print) -> None:
    """Run English, Polish, and structured-output checks or raise."""
    cases = (
        (
            "english_plain",
            [
                {"role": "system", "content": "Return only the word READY."},
                {"role": "user", "content": "Confirm that you can answer."},
            ],
            None,
            _exact("READY"),
        ),
        (
            "polish_plain",
            [
                {
                    "role": "system",
                    "content": "Odpowiedz wyłącznie zdaniem: Mówię po polsku.",
                },
                {"role": "user", "content": "W jakim języku odpowiadasz?"},
            ],
            None,
            _polish,
        ),
        (
            "structured_json",
            [
                {
                    "role": "system",
                    "content": (
                        "Return one JSON object with exactly two keys. "
                        "Set status to ok and language to pl."
                    ),
                },
                {"role": "user", "content": "Return the object now."},
            ],
            {"type": "json_object"},
            _structured,
        ),
    )
    for name, messages, response_format, validate in cases:
        kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 80,
        }
        if response_format is not None:
            kwargs["response_format"] = response_format
        started = time.perf_counter()
        response = client.chat.completions.create(**kwargs)
        validate(_content(response))
        emit(f"PASS {name} {int((time.perf_counter() - started) * 1000)}ms")


def main() -> int:
    model = str(Config.MISTRAL_MODEL or "").strip()
    if not str(Config.MISTRAL_API_KEY or "").strip():
        print("REFUSED: MISTRAL_API_KEY is not configured", file=sys.stderr)
        return 2
    if not model:
        print("REFUSED: MISTRAL_MODEL is not configured", file=sys.stderr)
        return 2

    target = ChatTarget(
        provider="mistral",
        model=model,
        base_url=str(Config.MISTRAL_BASE_URL or "").strip(),
    )
    try:
        client = build_chat_client(target)
        if client is None:
            raise SmokeFailure("the Mistral client is unavailable")
        run_smoke(client, model)
    except Exception as error:
        print(f"FAIL {type(error).__name__}: {error}", file=sys.stderr)
        return 1

    print("Mistral smoke check: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
