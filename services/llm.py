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

User-data callers must enter an ``AuthorizedProviderAdapter`` scope before
calling this wrapper. Direct provider clients are reserved for the low-level
adapter itself and non-user operational probes.
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
    session_id: Optional[str] = None,
    arc_id: Optional[str] = None,
    messages_override: Optional[list[dict[str, str]]] = None,
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
    session_id, arc_id : str | None
        Optional cost attribution for the ``llm_usage`` ledger (token-pricing
        Phase 0). Purely additive — they affect nothing but which row the cost
        lands on. Pass them wherever the call site knows them; "what does one
        take actually cost?" is unanswerable without ``session_id``.

    Returns
    -------
    LLMResult | None
        ``None`` on any failure (client unavailable, network error,
        empty response, malformed JSON when JSON was expected).
    """
    authorization = None
    provider_permit_id = None
    try:
        from services.authorized_provider import authorize_protected_generation
        authorization, provider_permit_id = authorize_protected_generation(surface)
    except Exception:
        # A protected call must fail closed.  In particular, an authority
        # failure may never be converted into the wrapper's usual optional
        # ``None`` fallback.
        raise

    # Lazy import — keep this module importable even when openai_service
    # isn't (test contexts, scripts).
    try:
        from services.openai_service import OpenAIService
        service = OpenAIService()
    except Exception as e:
        if authorization is not None:
            authorization.record_provider_event(
                provider_permit_id, "failed", error_code=type(e).__name__,
            )
        logger.warning(
            "llm.chat surface=%s init_failed err=%s", surface, e,
        )
        return None
    if not service.client:
        if authorization is not None:
            authorization.record_provider_event(
                provider_permit_id, "failed", error_code="PROVIDER_UNAVAILABLE",
            )
        logger.warning(
            "llm.chat surface=%s client_unavailable", surface,
        )
        return None

    response_format = response_format_override or spec.response_format
    from services.ml_surface_contracts import resolve_surface_model
    model = resolve_surface_model(surface, spec.model)
    create_kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages_override or [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": spec.temperature,
        "max_tokens": spec.max_tokens,
    }
    if response_format is not None:
        create_kwargs["response_format"] = response_format
    if spec.timeout_seconds is not None:
        create_kwargs["timeout"] = spec.timeout_seconds

    t0 = time.perf_counter()
    try:
        response = service.client.chat.completions.create(**create_kwargs)
    except Exception as e:
        duration_ms = int((time.perf_counter() - t0) * 1000)
        logger.warning(
            "llm.chat surface=%s model=%s duration_ms=%d "
            "user=%s call_failed err=%s",
            surface, model, duration_ms, user_id or "-", e,
        )
        if authorization is not None:
            authorization.record_provider_event(
                provider_permit_id, "failed", error_code=type(e).__name__,
            )
        return None

    duration_ms = int((time.perf_counter() - t0) * 1000)

    # Token usage — present on most response shapes but defensive None
    # access in case OpenAI changes the contract.
    usage = getattr(response, "usage", None)
    prompt_tokens = getattr(usage, "prompt_tokens", None) if usage else None
    completion_tokens = (
        getattr(usage, "completion_tokens", None) if usage else None
    )
    total_tokens = getattr(usage, "total_tokens", None) if usage else None

    if authorization is not None:
        authorization.record_provider_event(
            provider_permit_id,
            "completed",
            provider_operation_ref=str(getattr(response, "id", "") or "") or None,
            metadata={"surface": surface, "model": model},
        )

    # Cost ledger (token-pricing Phase 0). THE hook that covers every surface
    # routed through this wrapper — ~15 of them, including the whole per-take
    # analysis pipeline. Recorded BEFORE the empty-response bail below: an
    # empty completion is still a completion we were billed for, and dropping
    # those rows would bias the measured cost downward exactly where the model
    # is misbehaving. Best-effort by contract — llm_usage swallows all its own
    # failures, so this cannot affect what we return.
    try:
        from services.llm_usage import record_chat_usage
        record_chat_usage(
            surface=surface,
            model=model,
            tokens_in=prompt_tokens,
            tokens_out=completion_tokens,
            user_id=user_id,
            session_id=session_id,
            arc_id=arc_id,
        )
    except Exception:
        pass

    raw = (response.choices[0].message.content or "").strip()
    if not raw:
        logger.warning(
            "llm.chat surface=%s model=%s duration_ms=%d "
            "user=%s empty_response",
            surface, model, duration_ms, user_id or "-",
        )
        return None

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
                surface, model, duration_ms, user_id or "-",
                raw[:200], e,
            )
            # Don't return None — caller might still want the raw
            # text. They can check ``parsed is None`` to detect.

    logger.info(
        "llm.chat surface=%s model=%s duration_ms=%d "
        "user=%s prompt_tokens=%s completion_tokens=%s",
        surface, model, duration_ms, user_id or "-",
        prompt_tokens, completion_tokens,
    )

    return LLMResult(
        text=raw,
        parsed=parsed,
        model=model,
        duration_ms=duration_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )
