"""willab — what each model call costs US, in dollars.

Phase 0 of the token-pricing plan (docs/PRICING-TOKENS-PLAN.md §7). One place
that knows OpenAI's list prices, so ``services/llm_usage.py`` can stamp a
``cost_usd`` on every recorded call.

READ THIS BEFORE TRUSTING cost_usd
----------------------------------
``cost_usd`` is DERIVED and perishable — OpenAI reprices, and a row written in
July at July's prices does not become wrong, it becomes historical. The
durable facts are the raw counts (``tokens_in`` / ``tokens_out`` /
``audio_seconds``) stored alongside it. When prices move: bump ``PRICE_VERSION``
and, if you care about a consistent series, backfill ``cost_usd`` from the raw
counts. Never the reverse.

This module is NOT the user-facing price list. It is what we PAY. The user
price is a flat published token number per action (plan §2), deliberately
disconnected from per-call cost — fence §6.2: a cost-derived user price varies
with how the user performed, which is an AC-9 score in billing clothes.

Pure arithmetic: no I/O, no config reads, no exceptions on unknown input.
"""
from __future__ import annotations

from typing import Optional


PRICE_VERSION = "2026-07-openai-list"
"""Bump when any number below changes. Stamped onto every usage row so a
repricing stays auditable — you can always tell which table produced a
given cost_usd."""


# ── Chat models: (USD per 1M input tokens, USD per 1M output tokens) ────
#
# Keys are matched by longest prefix (see _lookup), so a dated snapshot id
# like "gpt-4o-mini-2024-07-18" resolves to the "gpt-4o-mini" entry without
# needing its own row here.
CHAT_PRICES_USD_PER_M: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o":      (2.50, 10.00),
}

WHISPER_USD_PER_MINUTE = 0.006
"""whisper-1 list price. Billed per second, rounded up to the nearest second
by OpenAI; we do not model the rounding — at $0.0001/second it is noise."""

_UNKNOWN_MODEL_FALLBACK = (0.15, 0.60)
"""An unrecognised model bills at the cheap-model rate rather than returning
None. Rationale: a NULL cost on a real call reads as 'free' in every rollup,
which is the one wrong answer. A slightly-off number is visibly wrong and gets
fixed; a missing number quietly biases the mean. ``is_known_model`` lets a
caller detect the fallback when that matters."""


def _lookup(model: Optional[str]) -> tuple[float, float]:
    """Longest-prefix match so dated snapshot ids resolve to their family.

    ``gpt-4o-mini-2024-07-18`` must match ``gpt-4o-mini`` (0.15/0.60), NOT
    ``gpt-4o`` (2.50/10.00) — a plain 'startswith over dict order' would pick
    whichever came first and could overcharge by 16×. Longest prefix wins.
    """
    name = (model or "").strip().lower()
    if not name:
        return _UNKNOWN_MODEL_FALLBACK
    best: Optional[str] = None
    for key in CHAT_PRICES_USD_PER_M:
        if name.startswith(key) and (best is None or len(key) > len(best)):
            best = key
    return CHAT_PRICES_USD_PER_M[best] if best else _UNKNOWN_MODEL_FALLBACK


def is_known_model(model: Optional[str]) -> bool:
    """False when ``cost_for_chat`` would fall back to the default rate."""
    name = (model or "").strip().lower()
    return bool(name) and any(
        name.startswith(k) for k in CHAT_PRICES_USD_PER_M
    )


def cost_for_chat(
    model: Optional[str],
    tokens_in: Optional[int],
    tokens_out: Optional[int],
) -> Optional[float]:
    """USD for one chat completion. None only when BOTH counts are unusable.

    A single missing count is treated as 0 rather than voiding the row: OpenAI
    occasionally omits one side of ``usage``, and half a cost is much closer to
    the truth than no cost at all.
    """
    in_rate, out_rate = _lookup(model)
    ti = _coerce_int(tokens_in)
    to = _coerce_int(tokens_out)
    if ti is None and to is None:
        return None
    return ((ti or 0) * in_rate + (to or 0) * out_rate) / 1_000_000.0


def cost_for_audio(seconds: Optional[float]) -> Optional[float]:
    """USD for one Whisper transcription. None when duration is unusable."""
    secs = _coerce_float(seconds)
    if secs is None or secs <= 0:
        return None
    return secs / 60.0 * WHISPER_USD_PER_MINUTE


def _coerce_int(v: object) -> Optional[int]:
    try:
        if v is None or isinstance(v, bool):
            return None
        return max(0, int(v))
    except (TypeError, ValueError):
        return None


def _coerce_float(v: object) -> Optional[float]:
    try:
        if v is None or isinstance(v, bool):
            return None
        f = float(v)
        return f if f == f and f not in (float("inf"), float("-inf")) else None
    except (TypeError, ValueError):
        return None
