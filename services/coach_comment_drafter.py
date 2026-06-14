"""AI-Commentator — per-snippet coach-comment draft (willab Phase 4 / Prompt 2).

For each snippet of a deck recording, generate a short coach-style note draft
from {transcript + the snippet's slide{title,body} + slide stickiness} so the
coach opens the comment field PRE-FILLED and only CORRECTS it instead of
writing from scratch. The (draft, coach-final) diff becomes the comment-clone
training corpus (captured at publish, separately).

Generation is fire-and-forget off the process path: process_lab_recording runs
synchronously on the upload response, so we never block it with N LLM calls —
we spawn a daemon that drafts each snippet and persists it FROZEN. The coach
reviews minutes-to-hours later, by which point the drafts are ready; a missing
draft just falls back to a blank field (no error).

Reuses the snippet_drafts.py pattern (OpenAIService + llm_schemas), adds the
slide grounding + a few-shot coach-voice style guide. Best-effort everywhere:
every failure logs and returns None/blank — never raises into processing.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

_MODEL = "gpt-4o-mini"
_MAX_TOKENS = 200


# A few-shot coach-voice style guide — terse, second-person, slide-aware.
_FEW_SHOT = (
    "Examples of the voice (slide point → moment → note):\n"
    "  • Slide \"The ask\" / they rushed the number → "
    "\"You hit the ask, but the price flew by — let it land next time.\"\n"
    "  • Slide \"Why now\" / steady, well-paced → "
    "\"Calm, deliberate pacing here — the urgency read as confidence.\"\n"
    "  • Slide \"Our traction\" / energy dropped → "
    "\"Your energy dipped right where the proof points were — own them.\"\n"
)


def _system_prompt() -> str:
    from services.will_voice import with_voice_rules
    return with_voice_rules(
        "You draft the one-line note a willab speaking coach would leave on "
        "ONE moment of a slide presentation. The coach sees your draft "
        "pre-filled and types over it, so write exactly as they would.\n\n"
        "VOICE: second-person, terse, specific. No preamble, no praise "
        "inflation (\"amazing!\"), no therapy-speak. Tie the note to the "
        "slide's point when it helps; otherwise speak to the delivery.\n"
        "GROUND in the transcript + slide the user prompt gives you. If "
        "there's too little to say anything specific, write the simplest "
        "honest note rather than inventing detail.\n\n"
        + _FEW_SHOT
        + "\nOUTPUT: strict JSON with key \"coach_note\" only."
    )


def _user_prompt(transcript: str, slide: dict, slide_stickiness: Optional[dict]) -> str:
    title = (slide.get("title") or "").strip() if isinstance(slide, dict) else ""
    body = (slide.get("body") or "").strip() if isinstance(slide, dict) else ""
    if len(body) > 400:
        body = body[:400].rstrip() + "…"
    sticky = ""
    if isinstance(slide_stickiness, dict):
        comp = slide_stickiness.get("composite")
        if isinstance(comp, (int, float)):
            sticky = f"\nslide stickiness (0-1, higher = the talk covered the slide): {comp:.2f}"
    return (
        f"slide title: \"{title}\"\n"
        f"slide body: \"{body or '(none)'}\"\n"
        f"what they said here: \"{transcript}\"{sticky}"
    )


def generate_coach_note_draft(
    transcript: str,
    slide: dict,
    slide_stickiness: Optional[dict] = None,
) -> Optional[str]:
    """The testable core: one LLM call → a short coach-note draft, or None on
    empty transcript / no LLM / failure. Pure of DB."""
    transcript = (transcript or "").strip()
    if not transcript:
        return None
    try:
        from services.openai_service import OpenAIService
        service = OpenAIService()
    except Exception as e:
        logger.warning("coach_comment_drafter: openai import failed: %s", e)
        return None
    if not service.client:
        return None
    try:
        from services.llm_schemas import COACH_NOTE_DRAFT_SCHEMA, response_format
        resp = service.client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": _user_prompt(transcript, slide, slide_stickiness)},
            ],
            max_tokens=_MAX_TOKENS,
            temperature=0.5,
            response_format=response_format(COACH_NOTE_DRAFT_SCHEMA),
        )
        raw = (resp.choices[0].message.content or "").strip()
    except Exception as e:
        logger.warning("coach_comment_drafter: llm call failed: %s", e)
        return None
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        logger.warning("coach_comment_drafter: unparseable output %r", raw[:200])
        return None
    note = (parsed.get("coach_note") or "").strip()
    return note[:300] if note else None


def dispatch_coach_note_drafts(
    session_id: str,
    snippets: list[dict],
    slides: Optional[list],
    advances: Optional[list],
) -> None:
    """Fire-and-forget: draft a coach note for each snippet of a DECK recording
    and persist it frozen. No-op without slides/snippets. Never raises into the
    caller (process_lab_recording)."""
    if not slides or not snippets:
        return
    try:
        threading.Thread(
            target=_draft_all,
            args=(session_id, snippets, slides, advances),
            daemon=True,
        ).start()
    except Exception as e:
        logger.warning("coach_comment_drafter: dispatch failed sid=%s: %s", session_id, e)


def _draft_all(session_id, snippets, slides, advances) -> None:
    from services.slide_alignment import slide_index_for_offset
    from services.db import db
    written = 0
    for snip in (snippets or []):
        try:
            sid = snip.get("id")
            transcript = (snip.get("transcript") or "").strip()
            if not sid or not transcript:
                continue
            idx = slide_index_for_offset(snip.get("start_offset_ms"), advances)
            slide = (
                slides[idx]
                if isinstance(idx, int) and 0 <= idx < len(slides)
                else None
            )
            if not isinstance(slide, dict):
                continue
            sticky = (snip.get("metrics") or {}).get("slide_stickiness") \
                if isinstance(snip.get("metrics"), dict) else None
            draft = generate_coach_note_draft(transcript, slide, sticky)
            if draft and db.set_charisma_snippet_ai_draft_coach_note(sid, draft):
                written += 1
        except Exception as e:
            logger.warning(
                "coach_comment_drafter: draft failed sid=%s snip=%s: %s",
                session_id, snip.get("id"), e,
            )
    logger.info(
        "coach_comment_drafter: drafted %d/%d for session %s",
        written, len(snippets or []), session_id,
    )
