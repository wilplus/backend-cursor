"""willab — F1 degrade observability (no contract change).

F1's load-bearing path (perfect per-slide transcript → best-text-per-slide) is
built to SILENTLY FALL BACK on internal failure: the LLM continuity polish bails
→ verbatim; a per-slide transcript step errors → coarser bucketing; the readout
re-derive fails → slide-less payload. The WIRE RESPONSE is deliberately
unchanged (that's what keeps the live loop unbreakable) — but today the fallback
is INVISIBLE: ``lab/recordings`` still 201s, ``best-presentation`` still
``ready:true``.

``observe_f1_degrade`` makes each fallback OBSERVABLE — a WARNING log + a Sentry
event keyed ``f1.degrade:<reason>`` — so the silent-degrade RATE is finally
measurable, WITHOUT moving the payload by a byte. (If the rate turns out
non-trivial, the follow-up is a soft ``degraded``/``refining`` FE affordance —
a SEPARATE PR + founder call; it brushes AC-9, so a "still refining" hint is fine
but a quality SCORE is not. Not bundled here.)

Pure observability: this NEVER raises and NEVER changes a caller's result.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def observe_f1_degrade(
    reason: str, *, exc: Optional[BaseException] = None, **context: Any,
) -> None:
    """Record an F1 silent-fallback as an observable event (log + Sentry).

    ``reason`` is a stable lower_snake tag (e.g. ``polish_compose_failed``,
    ``slide_transcript_failed``, ``readout_rederive_failed``) so the rate is
    queryable. ``exc`` attaches a stack trace when the fallback was triggered by
    an exception; omit it for a condition-driven degrade. Best-effort: any
    failure here (including Sentry being unconfigured) is swallowed — the
    caller's fallback payload is unchanged."""
    try:
        ctx = " ".join(f"{k}={v}" for k, v in context.items() if v is not None)
        logger.warning("f1.degrade reason=%s %s", reason, ctx)
    except Exception:
        pass
    try:
        import sentry_sdk

        # Scope the tag + context to THIS event so we don't pollute later events;
        # degrade to a plain capture if the scope API isn't available.
        _scope_cm = getattr(sentry_sdk, "push_scope", None) or getattr(
            sentry_sdk, "new_scope", None,
        )
        if _scope_cm is not None:
            with _scope_cm() as scope:
                try:
                    scope.set_tag("f1_degrade", reason)
                    if context:
                        scope.set_context("f1_degrade", dict(context))
                except Exception:
                    pass
                if exc is not None:
                    sentry_sdk.capture_exception(exc)
                else:
                    sentry_sdk.capture_message(f"f1.degrade:{reason}", level="warning")
        else:
            if exc is not None:
                sentry_sdk.capture_exception(exc)
            else:
                sentry_sdk.capture_message(f"f1.degrade:{reason}", level="warning")
    except Exception:
        pass
