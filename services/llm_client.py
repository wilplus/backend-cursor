"""The one place an OpenAI client is constructed (audit Q-A4, Phase 3).

Two constructors used to exist — ``OpenAIService.__init__`` and
``services/life_engine._client`` — each restating the strict timeout and
retry policy that keeps a hung provider call from parking a gunicorn worker
for the SDK's 600 s default. A third would have been a copy of a copy. Now
every client comes from ``build_openai_client`` and a fence test
(``tests/test_llm_client_fence.py``) fails the unit tier if ``OpenAI(`` is
called anywhere else.

ONE CLIENT PER PROCESS (loading times, 2026-11-05). ``OpenAIService()`` is
built per model call (``services.llm.chat_complete``, the transcription
adapter), and each build used to construct a fresh ``openai.OpenAI`` — a new
connection pool, so every call paid a new TCP + TLS handshake to the
provider, a dozen times inside one Take's processing. The client is now
built once per process and per settings, and its pool is reused. The SDK
client is safe to share between threads.

It is keyed by ``os.getpid()`` on purpose. The rq worker forks a process per
job and gunicorn forks its workers; a pooled TLS connection shared across a
fork corrupts both sides (the same failure ``worker._worker_child`` resets
the DB client for). A forked child never matches its parent's key, so it
builds its own client, and the parent's entry is left untouched rather than
closed from the child.

This module builds clients; it does not decide *when* a call is allowed.
User-data calls still go through the Phase-1 authorization boundary
(``services/authorized_provider.py``) and ``services/llm.chat_complete``;
CLAUDE.md's "no direct provider clients" rule is about that boundary, and
this module keeps it by having exactly one door.
"""
from __future__ import annotations

import os
from typing import Any, Optional

#: (pid, key, timeout, max_retries) -> client. Entries a fork inherited are
#: never used (their pid is not ours) and never closed here. No lock: a lock
#: held by another thread at fork time would stay held in the child forever,
#: and two threads racing here only build one spare client, which is dropped.
_CLIENTS: dict[tuple[int, str, float, int], Any] = {}


def build_openai_client(
    api_key: Optional[str], *, timeout: float, max_retries: int,
) -> Optional[Any]:
    """Return a configured ``openai.OpenAI`` client, or ``None`` without a key.

    ``None`` is the documented "provider unavailable" signal every caller
    already handles; it is never an exception, so a missing key can never
    break an import or the live loop. ``timeout`` and ``max_retries`` are
    mandatory on purpose: a caller that wants the SDK defaults has to say
    so, and none does.

    The same process asking with the same settings gets the same client back,
    so its connections stay open between calls; a forked process gets its
    own (see the module docstring).
    """
    key = (api_key or "").strip()
    if not key:
        return None
    slot = (os.getpid(), key, float(timeout), int(max_retries))
    client = _CLIENTS.get(slot)
    if client is None:
        import openai  # lazy: keeps this module importable where the SDK is absent

        client = _CLIENTS.setdefault(
            slot, openai.OpenAI(api_key=key, timeout=timeout, max_retries=max_retries))
    return client
