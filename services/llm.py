"""Thin wrapper around OpenAI's ``chat.completions.create``.

One place that:
  • Loads the OpenAI client once + handles the "client unavailable"
    fallback uniformly across every caller.
  • Forwards the spec (model / temperature / max_tokens / response_format)
    from ``services.llm_config`` without each caller having to know
    the OpenAI argument names.
  • Emits ONE structured log line per call — `llm.chat surface=X
    model=Y duration_ms=Z prompt_tokens=A completion_tokens=B`. This
    is the only consistent signal we have for cost + latency tracking
    until we ship turn logging.
  • Returns ``None`` on any failure mode (client down, network error,
    parse error). Callers MUST handle None — every existing service
    already does this, so the contract is consistent.

Non-goals
---------
This wrapper is NOT a full LLM client abstraction. It deliberately
does not:
  • support streaming (we don't use streaming anywhere today)
  • support function calling / tool use (no caller needs it; add when
    one does)
  • retry on failure (every caller has its own fallback path, and
    silent retries hide cost)
  • cache responses (nothing in our flow benefits from a cache)

It's intentionally small. When a caller needs something this wrapper
doesn't expose, they can still go direct via
``services.openai_service.OpenAIService().client``.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from services.llm_config import LLMSpec


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMResult:
    """Return shape from ``chat_complete``.

    ``text`` is always the raw stripped string response. ``parsed`` is
    populated when ``spec.response_format`` requests JSON AND parsing
    succeeded — None when parsing failed (caller can still inspect
    ``text``).
    """
    text: str
    parsed: Optional[Any]
    model: str
    duration_ms: int
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    total_tokens: Optional[int]


def chat_complete(
    *,
    spec: LLMSpec,
    system: str,
    user: str,
    surface: str,
    response_format_override: Optional[dict] = None,
    user_id: Optional[str] = None,
) -> Optional[LLMResult]:
    """Run one ``chat.completions.create`` against the spec.

    Args
    ----
    spec : LLMSpec
        The decoding config from ``services.llm_config``.
    system : str
        System message content.
    user : str
        User message content.
    surface : str
        Short identifier for the calling code path, e.g.
        ``"snippet_followup"`` or ``"directive_suggestions"``. Used
        only for log attribution — pick a stable string per call site.
    response_format_override : dict | None
        When set, replaces ``spec.response_format``. Use this for
        callers like ``master_doc_rag`` that ship a pinned JSON
        schema; the schema lives next to the caller, not in
        ``llm_config``.
    user_id : str | None
        Optional user attribution for the log line. Leave None for
        cron / admin / system contexts.

    Returns
    -------
    LLMResult | None
        ``None`` on any failure (client unavailable, network error,
        empty response, malformed JSON when JSON was expected).
    """
    # Lazy import — keep this module importable even when openai_service
    # isn't (test contexts, scripts).
    try:
        from services.openai_service import OpenAIService
        service = OpenAIService()
    except Exception as e:
        logger.warning(
            "llm.chat surface=%s init_failed err=%s", surface, e,
        )
        return None
    if not service.client:
        logger.warning(
            "llm.chat surface=%s client_unavailable", surface,
        )
        return None

    response_format = response_format_override or spec.response_format
    create_kwargs: dict[str, Any] = {
        "model": spec.model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": spec.temperature,
        "max_tokens": spec.max_tokens,
    }
    if response_format is not None:
        create_kwargs["response_format"] = response_format

    t0 = time.perf_counter()
    try:
        response = service.client.chat.completions.create(**create_kwargs)
    except Exception as e:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        logger.warning(
            "llm.chat surface=%s model=%s duration_ms=%d "
            "user=%s call_failed err=%s",
            surface, spec.model, duration_ms, user_id or "-", e,
        )
        return None

    duration_ms = int((time.perf_counter() - t0) * 1000)
    raw = (response.choices[0].message.content or "").strip()
    if not raw:
        logger.warning(
            "llm.chat surface=%s model=%s duration_ms=%d "
            "user=%s empty_response",
            surface, spec.model, duration_ms, user_id or "-",
        )
        return None

    # Token usage — present on most response shapes but defensive None
    # access in case OpenAI changes the contract.
    usage = getattr(response, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
    completion_tokens = (
        getattr(usage, "completion_tokens", None) if usage else None
    )
    total_tokens = getattr(usage, "total_tokens", None) if usage else None

    parsed: Optional[Any] = None
    if response_format and response_format.get("type") in (
        "json_object", "json_schema",
    ):
        try:
            parsed = json.loads(raw)
        except (json.JSONDecodeError, ValueError) as e:
            logger.warning(
                "llm.chat surface=%s model=%s duration_ms=%d "
                "user=%s json_parse_failed raw_head=%r err=%s",
                surface, spec.model, duration_ms, user_id or "-",
                raw[:200], e,
            )
            # Don't return None — caller might still want the raw
            # text. They can check ``parsed is None`` to detect.

    logger.info(
        "llm.chat surface=%s model=%s duration_ms=%d "
        "user=%s prompt_tokens=%s completion_tokens=%s",
        surface, spec.model, duration_ms, user_id or "-",
        prompt_tokens, completion_tokens,
    )

    return LLMResult(
        text=raw,
        parsed=parsed,
        model=spec.model,
        duration_ms=duration_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )
