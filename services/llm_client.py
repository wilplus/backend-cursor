"""The one place an OpenAI client is constructed (audit Q-A4, Phase 3).

Two constructors used to exist — ``OpenAIService.__init__`` and
``services/life_engine._client`` — each restating the strict timeout and
retry policy that keeps a hung provider call from parking a gunicorn worker
for the SDK's 600 s default. A third would have been a copy of a copy. Now
every client comes from ``build_openai_client`` and a fence test
(``tests/test_llm_client_fence.py``) fails the unit tier if ``OpenAI(`` is
called anywhere else.

This module builds clients; it does not decide *when* a call is allowed.
User-data calls still go through the Phase-1 authorization boundary
(``services/authorized_provider.py``) and ``services/llm.chat_complete``;
CLAUDE.md's "no direct provider clients" rule is about that boundary, and
this module keeps it by having exactly one door.
"""
from __future__ import annotations

from typing import Any, Optional


def build_openai_client(
    api_key: Optional[str], *, timeout: float, max_retries: int,
) -> Optional[Any]:
    """Return a configured ``openai.OpenAI`` client, or ``None`` without a key.

    ``None`` is the documented "provider unavailable" signal every caller
    already handles; it is never an exception, so a missing key can never
    break an import or the live loop. ``timeout`` and ``max_retries`` are
    mandatory on purpose: a caller that wants the SDK defaults has to say
    so, and none does.
    """
    key = (api_key or "").strip()
    if not key:
        return None
    import openai  # lazy: keeps this module importable where the SDK is absent

    return openai.OpenAI(api_key=key, timeout=timeout, max_retries=max_retries)
