"""Star-suggestion generation (founder 2026-07-18).

After a take's analysis, each notable snippet (resolved by
services.moment_direction: coach label → potentiometer; replace triggers:
threat / profanity / very low slide stickiness) gets ONE generated
suggestion the grey star opens:

  * emphasize — a short qualitative "why this landed" line;
  * replace   — an audience-appropriate replacement phrase, in the
                speaker's register, + a short "why swap this" line.

Every string passes say_it_stronger._guard_copy (AC-9: digits/construct
vocabulary kill the string). Persisted per snippet (moment_suggestions);
Approve/Revert live in user_suggestion_feedback. L1 (founder sign-off):
an approved replacement writes the STUDENT's serve-time copy only — the
canonical ideal text is never mutated by anything in this module.

Best-effort throughout: a generation miss stores nothing (no star), and
never breaks the analysis pipeline (LIVE LOOP).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_SYSTEM = (
    "You are a speech coach's assistant reviewing ONE short spoken moment "
    "from a live presentation rehearsal. Reply in the SAME language the "
    "moment was spoken in. Never use digits. Keep every field short and "
    "conversational.\n"
    'Return STRICT JSON: {"why": str, "replacement": str|null}.\n'
    "- kind=emphasize: `why` = one sentence on why this moment lands "
    "(delivery-agnostic, about the words and their effect; warm, specific, "
    "no scores, no flattery filler). `replacement` = null.\n"
    "- kind=replace: `replacement` = a natural alternative phrasing of the "
    "SAME point, appropriate for the stated audience, in the speaker's own "
    "register (plain words they would actually say; never add facts or "
    "claims they didn't make). `why` = one sentence on why the swap helps. "
    "If the moment contains profanity, the replacement must be clean.\n"
)


def generate_moment_suggestion(
    kind: str, transcript: str, *,
    audience: Optional[str] = None,
    trigger: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[dict]:
    """{'why': str, 'replacement': str|None} or None on any miss. Guarded."""
    if kind not in ("emphasize", "replace"):
        return None
    if not isinstance(transcript, str) or not transcript.strip():
        return None
    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_MOMENT_SUGGESTION
        from services.say_it_stronger import _guard_copy

        payload = {
            "kind": kind,
            "moment": transcript.strip()[:600],
            "audience": (audience or "a general professional audience"),
            "reason_flag": trigger or "",
        }
        result = chat_complete(
            spec=SPEC_MOMENT_SUGGESTION,
            system=_SYSTEM,
            user=json.dumps(payload, ensure_ascii=False),
            surface="moment_suggestion",
            user_id=user_id,
        )
        parsed = getattr(result, "parsed", None) if result else None
        if not isinstance(parsed, dict):
            return None
        why = _guard_copy((parsed.get("why") or "").strip()) or None
        replacement = None
        if kind == "replace":
            replacement = _guard_copy(
                (parsed.get("replacement") or "").strip()) or None
            if not replacement:
                return None   # a replace star without a replacement is dead
        if not why and not replacement:
            return None
        return {"why": why, "replacement": replacement}
    except Exception as e:
        logger.warning("moment_suggestion: generation failed: %s", e)
        return None


def generate_for_session(session_id: str, arc_id: Optional[str], *,
                         database=None) -> int:
    """Analysis-time hook (flag-gated at the caller): resolve + generate +
    persist suggestions for one take's snippets. Coach labels don't exist at
    record time, so resolution here is potentiometer/profanity/stickiness;
    a later coach-verified star supersedes at serve. Capped per take
    (MOMENT_SUGGESTIONS_MAX_PER_TAKE). Returns the number stored."""
    if not session_id or not arc_id:
        return 0
    try:
        if database is None:
            from services.db import db as database
        from config import Config
        from services.lab_recording import build_readout_from_session
        from services.moment_direction import (
            resolve_moment_direction, resolve_suggestion_kind,
        )

        try:
            _cap = max(1, int(Config().MOMENT_SUGGESTIONS_MAX_PER_TAKE))
        except Exception:
            _cap = 8
        try:
            _sticky_max = max(
                0, int(Config().MOMENT_REPLACE_STICKINESS_MAX_PCT)) / 100.0
        except Exception:
            _sticky_max = 0.15

        # Coach-view readout = full metrics (acoustic_read + stickiness).
        # Internal read only — nothing here is a user payload.
        readout = build_readout_from_session(
            session_id, include_slide_scores=True)
        session = {}
        try:
            session = database.v2_get_session_by_id(session_id) or {}
        except Exception:
            pass
        ctx = session.get("intake_context") \
            if isinstance(session.get("intake_context"), dict) else {}
        audience = (ctx or {}).get("audience") or None

        stored = 0
        for snip in (readout.get("snippets") or []):
            if stored >= _cap:
                logger.info(
                    "moment_suggestion: cap %d hit sid=%s (rest skipped)",
                    _cap, session_id)
                break
            try:
                snip_id = snip.get("id")
                transcript = (snip.get("transcript") or "").strip()
                if not snip_id or not transcript:
                    continue
                direction = resolve_moment_direction(
                    None, snip.get("acoustic_read"))
                _stick = snip.get("slide_stickiness")
                if isinstance(_stick, dict):
                    _stick = _stick.get("composite")
                kind = resolve_suggestion_kind(
                    direction, transcript,
                    slide_stickiness=_stick, stickiness_max=_sticky_max)
                if kind is None:
                    continue
                from services.text_flags import has_profanity
                trigger = ("threat" if direction == "threat"
                           else "profanity" if has_profanity(transcript)
                           else "stickiness" if kind == "replace"
                           else "charisma")
                gen = generate_moment_suggestion(
                    kind, transcript, audience=audience, trigger=trigger,
                    user_id=session.get("user_id"))
                if not gen:
                    continue
                if database.upsert_moment_suggestion(
                        str(snip_id), str(arc_id), kind,
                        gen.get("replacement"), gen.get("why"), trigger):
                    stored += 1
            except Exception as _snip_err:
                logger.warning(
                    "moment_suggestion: snippet failed sid=%s snip=%s: %s",
                    session_id, snip.get("id"), _snip_err)
                continue
        if stored:
            logger.info("moment_suggestion: stored %d sid=%s arc=%s",
                        stored, session_id, arc_id)
        return stored
    except Exception as e:
        logger.warning("moment_suggestion: session pass failed sid=%s: %s",
                       session_id, e)
        return 0
