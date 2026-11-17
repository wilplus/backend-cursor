"""Thin wrapper around OpenAI-compatible ``chat.completions.create``.

One place that:
  • Resolves the approved provider + handles the "client unavailable"
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


def operational_chat_complete(
    client: Any,
    *,
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
    max_tokens: int,
    response_format: Optional[dict] = None,
    timeout: Optional[float] = None,
) -> Any:
    """Call the shared chat transport for a synthetic operational probe.

    This deliberately does not issue a protected-data permit or write to the
    user-usage ledger. It is reserved for probes whose prompts contain no
    speaker data; production surfaces must call :func:`chat_complete`.
    """
    create_kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format is not None:
        create_kwargs["response_format"] = response_format
    if timeout is not None:
        create_kwargs["timeout"] = timeout
    return client.chat.completions.create(**create_kwargs)


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
    provider: str
    model: str
    duration_ms: int
    prompt_tokens: Optional[int]
    completion_tokens: Optional[int]
    total_tokens: Optional[int]


def _is_timeout_error(error: BaseException) -> bool:
    """Recognise provider/client timeout classes without coupling to an SDK."""
    return isinstance(error, TimeoutError) or "timeout" in type(error).__name__.lower()


def _record_failure(out: Optional[dict[str, Any]], code: str, *, timeout: bool = False) -> None:
    """Expose only a stable failure category to a caller's fallback path."""
    if out is None:
        return
    out["last_code"] = code
    if timeout:
        out["timed_out"] = True


def _timeout_for_request(
    spec_timeout: Optional[float], deadline_monotonic: Optional[float],
    failure_out: Optional[dict[str, Any]], surface: str,
) -> tuple[Optional[float], bool]:
    """Return this provider call's remaining timeout and whether it is spent."""
    if deadline_monotonic is None:
        return spec_timeout, False
    remaining = float(deadline_monotonic) - time.monotonic()
    if remaining <= 0:
        _record_failure(failure_out, "request_deadline", timeout=True)
        logger.warning("llm.chat surface=%s request_deadline_exhausted", surface)
        return None, True
    return (min(spec_timeout, remaining)
            if spec_timeout is not None else remaining), False


def _response_missed_request_deadline(
    deadline_monotonic: Optional[float], failure_out: Optional[dict[str, Any]],
    surface: str,
) -> bool:
    """Keep a completed-but-late provider response out of the chat turn."""
    if deadline_monotonic is None or time.monotonic() < float(deadline_monotonic):
        return False
    _record_failure(failure_out, "request_deadline", timeout=True)
    logger.warning("llm.chat surface=%s response_after_request_deadline", surface)
    return True


def _chat_create_kwargs(
    model: str, messages: list[dict[str, str]], temperature: float,
    max_tokens: int, response_format: Optional[dict], timeout: Optional[float],
) -> dict[str, Any]:
    """Build the provider payload without adding branches to the main wrapper."""
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format is not None:
        kwargs["response_format"] = response_format
    if timeout is not None:
        kwargs["timeout"] = timeout
    return kwargs


def _record_completed_chat_operation(authorization, provider_permit_id, response,
                                     *, surface: str, provider: str, model: str) -> None:
    """Close a provider permit for a completed operation when this route has one."""
    if authorization is not None:
        authorization.record_provider_event(
            provider_permit_id,
            "completed",
            provider_operation_ref=str(getattr(response, "id", "") or "") or None,
            metadata={
                "surface": surface,
                "provider": provider,
                "model": model,
            },
        )


def _model_the_promotion_gate_allows(
    surface: str, resolved: str, default: str,
) -> str:
    """The last thing between a promoted model and a speaker's document.

    LEGACY-1 (audit 2026-09-22). `resolve_surface_model` is the gate and this
    is not a second one; it is the assertion that the gate ran. `chat_complete`
    chooses the model that writes the Take-1 Ideal Text and every Say It
    Stronger card, and the whole finding was that you could read that function
    end to end without meeting the promotion flag once. Extracted rather than
    inlined because `chat_complete` is a grandfathered-complexity function that
    may only come down.

    Falls back rather than raising: a mis-set gate must not take the live loop
    down, and the caller's own default is always a served model.
    """
    if resolved == default:
        return resolved

    from services.ml_surface_contracts import (
        active_evaluation_override, runtime_config_key,
    )
    from services.runtime_model_gate import promoted_keys

    # A golden evaluation is not a promotion: it runs the candidate through
    # this very adapter, in-process, to decide whether the gate should open at
    # all. Gating it would make promotion unreachable.
    if active_evaluation_override(surface) == resolved:
        return resolved
    try:
        key = runtime_config_key(surface)
    except ValueError:
        key = ""
    if key and key in promoted_keys():
        return resolved

    logger.error(
        "llm.chat surface=%s promoted_model_withheld "
        "not_in_PROMOTION_SURFACES model=%s served=%s",
        surface, resolved, default,
    )
    return default


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
    failure_out: Optional[dict[str, Any]] = None,
    deadline_monotonic: Optional[float] = None,
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
    failure_out : dict | None
        Optional mutable, stable failure summary for a caller that has a
        renderable fallback. It never receives provider exception text.
    deadline_monotonic : float | None
        Optional request-wide monotonic deadline. When present, this call's
        provider timeout is capped to its remaining budget; an already-spent
        budget returns the normal ``None`` fallback signal without opening a
        provider permit/client. It cannot interrupt a blocking SDK call, but
        a response that arrives after the budget is not used.

    Returns
    -------
    LLMResult | None
        ``None`` on any failure (client unavailable, network error,
        empty response, malformed JSON when JSON was expected).
    """
    response_format = response_format_override or spec.response_format
    from services.ml_surface_contracts import resolve_surface_model
    model = _model_the_promotion_gate_allows(
        surface, resolve_surface_model(surface, spec.model), spec.model,
    )
    from services.chat_provider import build_chat_client, resolve_chat_target
    target = resolve_chat_target(surface, model)

    timeout_seconds, deadline_exhausted = _timeout_for_request(
        spec.timeout_seconds, deadline_monotonic, failure_out, surface,
    )
    if deadline_exhausted:
        return None

    # Provider identity is resolved before authorization, but no client is
    # constructed until the permit has been issued.
    authorization = None
    provider_permit_id = None
    try:
        from services.authorized_provider import authorize_protected_generation
        authorization, provider_permit_id = authorize_protected_generation(
            surface, provider=target.provider,
        )
    except Exception:
        raise

    try:
        client = build_chat_client(target)
    except Exception as e:
        _record_failure(failure_out, "provider_init_failed",
                        timeout=_is_timeout_error(e))
        if authorization is not None:
            authorization.record_provider_event(
                provider_permit_id, "failed", error_code=type(e).__name__,
            )
        logger.warning(
            "llm.chat surface=%s provider=%s init_failed err=%s",
            surface, target.provider, e,
        )
        return None
    if not client:
        _record_failure(failure_out, "provider_unavailable")
        if authorization is not None:
            authorization.record_provider_event(
                provider_permit_id, "failed", error_code="PROVIDER_UNAVAILABLE",
            )
        logger.warning(
            "llm.chat surface=%s provider=%s client_unavailable",
            surface, target.provider,
        )
        return None
    model = target.model
    create_kwargs = _chat_create_kwargs(
        model,
        messages_override or [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        spec.temperature,
        spec.max_tokens,
        response_format,
        timeout_seconds,
    )

    t0 = time.perf_counter()
    try:
        response = operational_chat_complete(
            client,
            model=str(create_kwargs["model"]),
            messages=create_kwargs["messages"],
            temperature=float(create_kwargs["temperature"]),
            max_tokens=int(create_kwargs["max_tokens"]),
            response_format=create_kwargs.get("response_format"),
            timeout=create_kwargs.get("timeout"),
        )
    except Exception as e:
        _record_failure(failure_out, "provider_timeout"
                        if _is_timeout_error(e) else "provider_error",
                        timeout=_is_timeout_error(e))
        duration_ms = int((time.perf_counter() - t0) * 1000)
        logger.warning(
            "llm.chat surface=%s provider=%s model=%s duration_ms=%d "
            "user=%s call_failed err=%s",
            surface, target.provider, model, duration_ms, user_id or "-", e,
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

    _record_completed_chat_operation(
        authorization, provider_permit_id, response,
        surface=surface, provider=target.provider, model=model,
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
            provider=target.provider,
            model=model,
            tokens_in=prompt_tokens,
            tokens_out=completion_tokens,
            user_id=user_id,
            session_id=session_id,
            arc_id=arc_id,
        )
    except Exception:
        pass

    # A provider can return after its requested timeout because of SDK retry
    # behavior or a late network response. It is recorded above, but never
    # used to answer a stale turn or start another stage in its budget.
    if _response_missed_request_deadline(
            deadline_monotonic, failure_out, surface):
        return None

    raw = (response.choices[0].message.content or "").strip()
    if not raw:
        _record_failure(failure_out, "empty_response")
        logger.warning(
            "llm.chat surface=%s provider=%s model=%s duration_ms=%d "
            "user=%s empty_response",
            surface, target.provider, model, duration_ms, user_id or "-",
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
        "llm.chat surface=%s provider=%s model=%s duration_ms=%d "
        "user=%s prompt_tokens=%s completion_tokens=%s",
        surface, target.provider, model, duration_ms, user_id or "-",
        prompt_tokens, completion_tokens,
    )

    return LLMResult(
        text=raw,
        parsed=parsed,
        provider=target.provider,
        model=model,
        duration_ms=duration_ms,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
    )


def embed(texts: list[str], *, surface: str, model: Optional[str] = None,
          user_id: Optional[str] = None) -> Optional[list[list[float]]]:
    """Read texts into vectors with the shared reader (N616 item 8): ONE
    provider call for all of them, under the caller's processing
    authorization (a permit for the call, as ``chat_complete``), each text
    cut to ``READER_MAX_CHARS``. None on any failure; an authority failure
    raises."""
    from services.llm_config import READER_MAX_CHARS, READER_MODEL
    inputs = [str(t or " ")[:READER_MAX_CHARS] or " " for t in texts]
    if not inputs:
        return []
    from services.authorized_provider import authorize_protected_generation
    authorization, permit_id = authorize_protected_generation(surface)

    def failed(code: str) -> None:
        if authorization is not None:
            authorization.record_provider_event(permit_id, "failed", error_code=code)

    try:
        from services.openai_service import OpenAIService
        service = OpenAIService()
    except Exception as e:
        logger.warning("llm.embed surface=%s init_failed", surface, exc_info=True)
        failed(type(e).__name__)
        return None
    if not service.client:
        failed("PROVIDER_UNAVAILABLE")
        return None
    name = model or READER_MODEL
    try:
        response = service.client.embeddings.create(model=name, input=inputs)
        vectors = [list(map(float, d.embedding)) for d in response.data]
    except Exception as e:
        logger.warning("llm.embed surface=%s user=%s failed", surface, user_id or "-", exc_info=True)
        failed(type(e).__name__)
        return None
    if authorization is not None:
        authorization.record_provider_event(permit_id, "completed",
                                            metadata={"surface": surface, "model": name})
    return vectors if len(vectors) == len(inputs) else None
