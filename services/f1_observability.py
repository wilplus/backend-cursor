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


def observe_reason_tiers(
    take_id: str, take_index: Any, blocks: Any,
) -> None:
    """One line per Take: which reason tier won each block, and how coarse.

    24j card 2. The reason layer sits behind ``REASONABLE_CONFIDENCE_ENABLED``
    (default OFF) and cannot be turned on responsibly while the DEGRADED RATE
    is unmeasurable — `reason_tier` is derived from true entailment only for
    the LLM-budget subset, and from word overlap for the rest. Word overlap is
    exactly the "keyword matching" the product does not want to be, so the
    share of Takes whose verdicts came from it is the number that decides
    whether the layer is ready. Today nothing records it.

    Deliberately logged whether or not the flag is on: measuring BEFORE the
    cutover is the entire point, and with the flag off `ordering_rank` returns
    a constant so these tiers are observed without influencing any ordering.

    ⚠ AC-9. Tier names and `degraded` are verdicts about what the words did —
    `"not"` says the speaker missed the slide's point — and are exactly the
    kind of thing AC-9 bans from reaching a person. They go to the server log
    and nowhere else. This function returns None, is called for its side
    effect only, and must never be wired into a payload, a response or the
    FE. `tests/test_reason_tier_observability.py` fails if the frame grows a
    key because of it.

    Pure observation: never raises, never mutates ``blocks``, never changes a
    caller's result.
    """
    try:
        counts = {"covered": 0, "partial": 0, "not": 0, "unmeasured": 0}
        degraded = 0
        selected_total = 0
        rows = blocks if isinstance(blocks, list) else []

        for block in rows:
            if not isinstance(block, dict):
                continue
            selected_id = block.get("selected_candidate_id")
            if not selected_id:
                continue
            candidates = block.get("confidence_candidates")
            chosen = next(
                (
                    row for row in (candidates or [])
                    if isinstance(row, dict)
                    and row.get("candidate_id") == selected_id
                ),
                None,
            )
            if chosen is None:
                continue
            selected_total += 1
            tier = chosen.get("reason_tier")
            counts[tier if tier in counts else "unmeasured"] += 1
            if chosen.get("reason_degraded"):
                degraded += 1

        logger.info(
            "f1.reason_tiers take=%s take_index=%s blocks=%d selected=%d "
            "covered=%d partial=%d not=%d unmeasured=%d degraded=%d",
            take_id, take_index, len(rows), selected_total,
            counts["covered"], counts["partial"], counts["not"],
            counts["unmeasured"], degraded,
        )
    except Exception:
        pass


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
