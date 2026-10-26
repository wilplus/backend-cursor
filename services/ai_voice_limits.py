"""Cost safeguards for the AI voice (founder 2026-10-12: Starter, 40,000
credits a month; warn at 28,000, stop at 38,000. Founder 2026-10-26, N188:
3 clips a day and 20 a month for each speaker, and no new voice while the
plan's voice slots are full).

Checked before every provider call that costs credits. When usage cannot be
read, the answer is no: an unknown spend is never a reason to spend. Nothing
here ever upgrades a plan, adds funds or creates a clone per session.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from config import Config
from services import ai_voice_store as store

_log = logging.getLogger(__name__)


def estimated_credits(characters: int) -> float:
    return round(max(0, int(characters)) * float(Config.AI_VOICE_CREDITS_PER_CHARACTER), 2)


def estimated_usd(credits: float) -> Optional[float]:
    rate = float(Config.AI_VOICE_USD_PER_1000_CREDITS)
    return round(credits / 1000.0 * rate, 4) if rate > 0 else None


def _month_credits(database: Any, provider_usage: Optional[dict]) -> float:
    local = sum(float(row.get("credits_estimated") or 0)
                for row in store.cycles_since(database, store.start_of_month()))
    used = (provider_usage or {}).get("used")
    return max(local, float(used)) if isinstance(used, (int, float)) else local


def clip_refusal(database: Any, owner_user_id: str, *,
                 characters: int, provider_usage: Optional[dict] = None) -> Optional[str]:
    """None when one more clip of ``characters`` may be made; else a code:
    ``usage_unknown`` · ``speaker_daily`` · ``speaker_monthly`` ·
    ``total_daily`` · ``monthly``."""
    try:
        today = store.start_of_day()
        mine = store.cycles_since(database, today, owner_user_id=owner_user_id)
        mine_this_month = store.cycles_since(database, store.start_of_month(),
                                             owner_user_id=owner_user_id)
        everyone = store.cycles_since(database, today)
        month = _month_credits(database, provider_usage)
    except Exception:  # noqa: BLE001 — fail closed on cost
        _log.warning("ai voice: usage unreadable, no clip", exc_info=True)
        return "usage_unknown"
    if len(mine) >= int(Config.AI_VOICE_DAILY_CLIPS_PER_SPEAKER):
        return "speaker_daily"
    if len(mine_this_month) >= int(Config.AI_VOICE_MONTHLY_CLIPS_PER_SPEAKER):
        return "speaker_monthly"
    if len(everyone) >= int(Config.AI_VOICE_DAILY_CLIPS_TOTAL):
        return "total_daily"
    after = month + estimated_credits(characters)
    if after >= int(Config.AI_VOICE_STOP_CREDITS):
        return "monthly"
    if after >= int(Config.AI_VOICE_WARN_CREDITS):
        _warn_once(after)
    return None


def clone_refusal(database: Any) -> Optional[str]:
    try:
        made_today = store.clones_created_since(database, store.start_of_day())
        in_use = store.voices_in_use(database)
    except Exception:  # noqa: BLE001 — fail closed on cost
        _log.warning("ai voice: clone count unreadable, no clone", exc_info=True)
        return "usage_unknown"
    if made_today >= int(Config.AI_VOICE_DAILY_CLONES_TOTAL):
        return "clones_daily"
    if in_use >= int(Config.AI_VOICE_VOICE_SLOTS):
        _log.warning("ai voice: the plan's %d voice slots are full, no clone",
                     int(Config.AI_VOICE_VOICE_SLOTS))
        return "voice_slots"
    return None


_warned_on: Optional[str] = None


def _warn_once(credits: float) -> None:
    """One warning a day to the founder's error tracker, never to a speaker."""
    global _warned_on
    day = store.start_of_day().date().isoformat()
    if _warned_on == day:
        return
    _warned_on = day
    message = (f"AI voice credits this month near the stop: about {int(credits)} "
               f"of {Config.AI_VOICE_STOP_CREDITS} (plan {Config.AI_VOICE_MONTHLY_CREDITS})")
    _log.warning(message)
    try:
        import sentry_sdk
        sentry_sdk.capture_message(message, level="warning")
    except Exception:  # noqa: BLE001 — the warning never costs the clip
        _log.debug("ai voice: warning not sent", exc_info=True)
