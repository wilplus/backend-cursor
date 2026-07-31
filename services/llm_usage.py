"""willab — record what every model call costs us.

Phase 0 of the token-pricing plan (docs/PRICING-TOKENS-PLAN.md §7,
founder-approved 2026-07-27). Writes one ``llm_usage`` row per OpenAI call so
the ×7 price multiplier in the plan stops being my estimate and becomes a
measured number.

CONTRACT: this module NEVER raises and NEVER changes a caller's result.
It sits on the F1 live loop (every take fires ~10 model calls through it), and
the standing fence is that instrumentation must not be able to break recording.
Same discipline as ``services/f1_observability.py`` — swallow everything, log,
carry on.

SELF-DISABLING. The writer trips a process-local breaker after
``_FAILURE_BREAKER`` consecutive failures and stops trying. This is what makes
it safe to deploy BEFORE ``migrations/add_llm_usage.sql`` has been run in prod:
a missing table costs one warning line, not one exception per model call
forever. Restart (or a successful write) re-arms it.

KNOWN GAP — PER-TAKE ATTRIBUTION (Phase 0.1)
--------------------------------------------
``session_id`` / ``arc_id`` are plumbed end-to-end (column, writer, and
``chat_complete`` parameter) but **no chat caller passes them yet**. The
services on the take path — say_it_stronger, snippet_stickiness,
moment_suggestions, slide_alignment — do not have ``session_id`` in scope at
their ``chat_complete`` call, and threading it means signature changes across
all of them. Whisper DOES carry it (``lab_recording`` has it right there).

So today: per-SURFACE totals are complete and correct; per-TAKE cost must be
derived by dividing a surface total by the take count, which
``scripts/llm_usage_report.py`` does. That is unbiased for the mean but gives
no distribution. Attributing only *some* chat surfaces would be worse than
attributing none — a session_id GROUP BY would then silently report a take as
costing just its transcription — so the current state is deliberately uniform.

WHAT IT DOES NOT DO
-------------------
* No prompts, no completions, no user content — surfaces and counts only.
* Not a user-facing billing ledger. This is what we PAY OpenAI. The user's
  token balance is a separate append-only ledger (plan Phase 1) and must never
  be derived from these rows — fence §6.2.
* No batching or background threads. One synchronous insert per call, ~10-30ms,
  against a take pipeline that already runs 10-30s. Buffering would trade that
  ~0.2% for losing the tail of every crashed pipeline, which is exactly the
  data most worth having.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

_TABLE = "llm_usage"

_FAILURE_BREAKER = 5
"""Consecutive write failures before this module goes quiet. Low on purpose:
the realistic cause is a structural one (table missing, credentials wrong) that
retrying cannot fix, and the cost of finding out is a log line per model call."""

_consecutive_failures = 0
_breaker_open = False


def _enabled() -> bool:
    """Default ON. Set ``LLM_USAGE_ENABLED=0`` to kill it without a deploy.

    Default-ON is deliberate. An observability table that ships dark needs
    someone to remember an env var later, and this repo has a standing habit of
    flags that never got flipped. The write is additive, swallowed, and
    breaker-guarded, so the downside of it being on is a log line.
    """
    return (os.getenv("LLM_USAGE_ENABLED") or "1").strip().lower() \
        not in ("0", "false", "no")


def reset_breaker() -> None:
    """Re-arm the writer. For tests and for an admin 'try again after the
    migration ran' path."""
    global _consecutive_failures, _breaker_open
    _consecutive_failures = 0
    _breaker_open = False


def record_chat_usage(
    *,
    surface: str,
    model: Optional[str],
    tokens_in: Optional[int],
    tokens_out: Optional[int],
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    arc_id: Optional[str] = None,
) -> None:
    """Record one chat-completion call. Best-effort; never raises."""
    try:
        from services.llm_pricing import cost_for_chat, PRICE_VERSION
        _write({
            "surface": surface,
            "model": (model or "").strip() or "unknown",
            "tokens_in": _int(tokens_in),
            "tokens_out": _int(tokens_out),
            "cost_usd": cost_for_chat(model, tokens_in, tokens_out),
            "price_version": PRICE_VERSION,
            "user_id": _text(user_id),
            "session_id": _text(session_id),
            "arc_id": _text(arc_id),
        })
    except Exception as e:  # pragma: no cover — belt and braces
        _swallow(surface, e)


def record_response_usage(
    response: Any,
    *,
    surface: str,
    model: Optional[str],
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    arc_id: Optional[str] = None,
) -> None:
    """Record usage straight off a raw OpenAI response object.

    For the services that call ``client.chat.completions.create`` directly
    instead of going through ``services/llm.py`` — master_doc_rag, life_engine,
    stickiness, snippet_drafts, coach_comment_drafter, baseline_summary. Without
    this they are invisible to the ledger, and the per-take total would
    under-report by roughly a third.

    Defensive about the response shape: OpenAI omits ``usage`` on some error
    paths, and a missing count must cost us the row's precision, not the row.
    """
    try:
        usage = getattr(response, "usage", None)
        record_chat_usage(
            surface=surface,
            model=model,
            tokens_in=getattr(usage, "prompt_tokens", None) if usage else None,
            tokens_out=(
                getattr(usage, "completion_tokens", None) if usage else None
            ),
            user_id=user_id,
            session_id=session_id,
            arc_id=arc_id,
        )
    except Exception as e:  # pragma: no cover — belt and braces
        _swallow(surface, e)


def record_audio_usage(
    *,
    surface: str,
    seconds: Optional[float],
    model: str = "whisper-1",
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    arc_id: Optional[str] = None,
) -> None:
    """Record one speech-to-text call. Best-effort; never raises.

    ``seconds`` is the AUDIO duration, which is what Whisper bills on — token
    columns stay NULL for these rows. Transcription is ~52% of a take's cost
    and the only line that scales without limit, so it is the single most
    important thing in this table.
    """
    try:
        from services.llm_pricing import cost_for_audio, PRICE_VERSION
        _write({
            "surface": surface,
            "model": model,
            "audio_seconds": _float(seconds),
            "cost_usd": cost_for_audio(seconds),
            "price_version": PRICE_VERSION,
            "user_id": _text(user_id),
            "session_id": _text(session_id),
            "arc_id": _text(arc_id),
        })
    except Exception as e:  # pragma: no cover — belt and braces
        _swallow(surface, e)


def _write(row: dict[str, Any]) -> None:
    global _consecutive_failures, _breaker_open
    if _breaker_open or not _enabled():
        return
    # Drop keys the caller left empty so the insert carries only real columns.
    payload = {k: v for k, v in row.items() if v is not None}
    if not payload.get("surface"):
        return
    try:
        from services.db import db
        client = getattr(db, "client", None)
        if client is None:
            return
        client.table(_TABLE).insert(payload).execute()
        _consecutive_failures = 0
    except Exception as e:
        _swallow(payload.get("surface"), e)


def _swallow(surface: Any, exc: BaseException) -> None:
    """Log a write failure and trip the breaker once it has happened enough."""
    global _consecutive_failures, _breaker_open
    try:
        _consecutive_failures += 1
        if _consecutive_failures >= _FAILURE_BREAKER and not _breaker_open:
            _breaker_open = True
            logger.warning(
                "llm_usage: %d consecutive write failures — disabling for this "
                "process. Most likely migrations/add_llm_usage.sql has not been "
                "run. Last error (surface=%s): %s",
                _consecutive_failures, surface, exc,
            )
        elif not _breaker_open:
            logger.warning(
                "llm_usage: write failed surface=%s err=%s", surface, exc,
            )
    except Exception:
        pass


def _int(v: Any) -> Optional[int]:
    try:
        if v is None or isinstance(v, bool):
            return None
        return int(v)
    except (TypeError, ValueError):
        return None


def _float(v: Any) -> Optional[float]:
    try:
        if v is None or isinstance(v, bool):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _text(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None
