"""AI-Commentator — per-snippet coach-comment draft (willab Phase 4 / Prompt 2).

For each snippet, draft the feedback note in the willab Insights voice —
friendly, plain-language, encouragement-first — so the coach opens the comment
PRE-FILLED and only corrects it. The (draft, coach-final) diff becomes the
comment-clone corpus (captured at publish, separately).

Grounding (founder spec 2026-06-15): the speaker's GOAL (the session topic) +
the snippet's SLIDE {title, body} WHEN THERE IS A DECK (optional — a spoken
pitch with no slides still drafts) + a TAKE-COMPARISON to their previous
recordings + this moment's metrics CONVERTED TO PLAIN LANGUAGE in code — the
model never sees F0/SD/voiced%/dB/'coherence score', only "pace: comfortable".

Generation is fire-and-forget off the synchronous process path; drafts persist
FROZEN. Best-effort everywhere — every failure logs and returns None/blank.
"""
from __future__ import annotations

import json
import logging
import threading
from typing import Any, Optional

logger = logging.getLogger(__name__)

_MODEL = "gpt-4o-mini"
_MAX_TOKENS = 320  # ~120 words + emoji-led lines


# ── metrics → plain language (the ONLY form the LLM sees) ──────────────────
def _bucket(v: Any, lo: float, hi: float, labels: tuple) -> Optional[str]:
    if not isinstance(v, (int, float)) or isinstance(v, bool):
        return None
    return labels[0] if v < lo else (labels[2] if v > hi else labels[1])


def metric_observations(metrics: Optional[dict]) -> dict:
    """Convert the acoustic metrics to plain-language observations. Founder rule:
    NEVER expose F0/SD/voiced%/dB/coherence-score to the model — it gets these
    words instead. Returns only the buckets we could compute."""
    m = metrics or {}
    wpm = m.get("wpm") if m.get("wpm") is not None else m.get("speech_rate")
    db_range = m.get("dynamic_db") if m.get("dynamic_db") is not None else m.get("loudness_range")
    coh = (m.get("stickiness") or {}).get("composite") if isinstance(m.get("stickiness"), dict) else None
    buckets = {
        "pace": _bucket(wpm, 110, 160, ("a bit slow", "comfortable", "a bit fast")),
        "pitch": _bucket(m.get("f0_sd"), 20, 45, ("flat / monotone", "natural rise and fall", "expressive")),
        "pauses": _bucket(m.get("pause_ratio"), 0.08, 0.22, ("rushed", "well-balanced", "a lot of pausing")),
        "volume": _bucket(db_range, 6, 14, ("flat volume", "varied volume", "energetic volume")),
        "clarity": _bucket(coh, 0.4, 0.7, ("somewhat unclear", "easy to follow", "very clear")),
    }
    return {k: v for k, v in buckets.items() if v}


# Prompt text lives in the registry (services/prompts/) — moved verbatim
# 2026-08-03; hash-locked in prompts.lock.json. Aliases keep this module's
# surface stable for callers and tests.
from services.prompts import coach_comment_drafter as _prompts

_STYLE_EXAMPLE = _prompts.STYLE_EXAMPLE
_system_prompt = _prompts.system
_user_prompt = _prompts.user


def generate_coach_note_draft(
    transcript: str,
    slide: Optional[dict],
    metrics: Optional[dict] = None,
    *,
    take_comparison: Optional[str] = None,
    goal: Optional[str] = None,
) -> Optional[str]:
    """Testable core: one LLM call → a friendly coach-note draft in the willab
    Insights voice, or None on empty transcript / no LLM / failure. Metrics are
    converted to plain language HERE so the model never sees raw acoustics."""
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
    observations = metric_observations(metrics)
    try:
        from services.llm_schemas import COACH_NOTE_DRAFT_SCHEMA, response_format
        resp = service.client.chat.completions.create(
            model=_MODEL,
            messages=[
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": _user_prompt(
                    transcript, slide, observations, take_comparison, goal)},
            ],
            max_tokens=_MAX_TOKENS,
            temperature=0.6,
            response_format=response_format(COACH_NOTE_DRAFT_SCHEMA),
        )
        # Cost ledger (token-pricing Phase 0). Recorded HERE, immediately
        # after the call returns and BEFORE any parsing — we have already
        # paid for this response, so a downstream parse failure must not
        # lose the cost row. This service bypasses services/llm.py, so
        # without this hook it is invisible to the ledger.
        try:
            from services.llm_usage import record_response_usage
            record_response_usage(resp, surface="coach_comment_draft",
                                  model=_MODEL,)
        except Exception:
            pass
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
    return note[:900] if note else None


# ── take-vs-take comparison (best-effort, fed to the drafter) ──────────────
_AGG = {
    "pace": ("wpm", "speech_rate"),
    "pitch": ("f0_sd",),
    "pauses": ("pause_ratio",),
    "volume": ("dynamic_db", "loudness_range"),
}


def _aggregate(snippets) -> dict:
    """Mean of each normalized metric across a session's snippets."""
    sums: dict = {}
    counts: dict = {}
    for snip in (snippets or []):
        m = snip.get("metrics") if isinstance(snip.get("metrics"), dict) else {}
        for norm_key, aliases in _AGG.items():
            v = next((m.get(a) for a in aliases if isinstance(m.get(a), (int, float))
                      and not isinstance(m.get(a), bool)), None)
            if v is not None:
                sums[norm_key] = sums.get(norm_key, 0.0) + float(v)
                counts[norm_key] = counts.get(norm_key, 0) + 1
    return {k: sums[k] / counts[k] for k in sums if counts.get(k)}


def compare_takes(this: dict, prior: dict) -> Optional[str]:
    """Plain-language deltas of this take vs a prior aggregate. None if nothing
    comparable."""
    out: list[str] = []
    plan = [
        ("pace", "pace", "a bit faster", "a bit more controlled", 8.0),
        ("pitch", "pitch variety", "more expressive", "a touch flatter", 5.0),
        ("pauses", "pausing", "more pauses", "fewer pauses", 0.04),
        ("volume", "energy", "more energetic", "steadier", 2.0),
    ]
    for key, label, more, less, tol in plan:
        a, b = this.get(key), prior.get(key)
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            continue
        out.append(f"{label} about the same" if abs(a - b) < tol
                   else f"{label} {more if a > b else less}")
    return "; ".join(out) or None


def _build_take_comparison(session_id, this_agg) -> Optional[str]:
    """Best-effort 'vs your previous takes' line. Compares this take's aggregate
    to the user's most recent prior recording (same topic when known)."""
    if not this_agg:
        return None
    try:
        from services.db import db
        session = db.v2_get_session_by_id(session_id) or {}
        uid = session.get("user_id")
        created = session.get("created_at") or ""
        ctx = session.get("intake_context") if isinstance(session.get("intake_context"), dict) else {}
        topic = (ctx or {}).get("topic")
        if not uid:
            return None
        prior = db.v2_list_user_lab_sessions(uid, limit=20) or []
        cands = [
            s for s in prior
            if (s.get("created_at") or "") < created and str(s.get("id")) != str(session_id)
        ]
        if topic:
            same = [s for s in cands
                    if isinstance(s.get("intake_context"), dict)
                    and s["intake_context"].get("topic") == topic]
            cands = same or cands
        cands.sort(key=lambda s: s.get("created_at") or "", reverse=True)
        for s in cands[:3]:
            snips = db.get_snippets_by_session(s.get("id")) or []
            prior_agg = _aggregate(snips)
            if prior_agg:
                return compare_takes(this_agg, prior_agg)
        return None
    except Exception as e:
        logger.warning("coach_comment_drafter: take comparison failed: %s", e)
        return None


def dispatch_coach_note_drafts(
    session_id: str,
    snippets: list[dict],
    slides: Optional[list],
    advances: Optional[list],
    *,
    goal: Optional[str] = None,
    llm_ids: Optional[set] = None,
) -> None:
    """Fire-and-forget: draft a coach note for each snippet, persist it frozen.
    Slides are OPTIONAL grounding — a deck-less recording (a spoken pitch with
    no slides) still drafts from transcript + plain-language metrics + goal, so
    the coach's comment field opens pre-filled either way. No-op only without
    snippets. Never raises into the caller (process_lab_recording).

    ``llm_ids`` (pieces-canonical, founder 2026-07-14): when given, ONLY
    snippet ids in the set get an LLM-drafted note; every other piece writes
    NOTHING here (its comment is the deterministic auto-comment computed at
    serve time — services/auto_comment.py — so no LLM cost, no ai_draft flood
    of the clone corpus, and publish emits ≤budget annotation events). The
    coach labeling surface stays blind: the draft carries NO tone word (the
    learned direction guess never reaches the note). None (legacy) → LLM for
    all snippets, unchanged."""
    if not snippets:
        return
    try:
        threading.Thread(
            target=_draft_all,
            args=(session_id, snippets, slides, advances, goal, llm_ids),
            daemon=True,
        ).start()
    except Exception as e:
        logger.warning("coach_comment_drafter: dispatch failed sid=%s: %s", session_id, e)


def _draft_all(session_id, snippets, slides, advances, goal,
               llm_ids=None) -> None:
    from services.slide_alignment import slide_index_for_offset
    from services.db import db
    slides = slides or []
    # one take-comparison per session (fed to every snippet's draft)
    take_comparison = _build_take_comparison(session_id, _aggregate(snippets))
    written = 0
    for snip in (snippets or []):
        try:
            sid = snip.get("id")
            transcript = (snip.get("transcript") or "").strip()
            if not sid or not transcript:
                continue
            # Pieces-canonical: non-budget pieces write NOTHING here — their
            # comment is the serve-time deterministic auto-comment. Only the
            # budget set gets an LLM draft (keeps the ai_draft/clone corpus at
            # ≤budget rows, not one per piece).
            if llm_ids is not None and str(sid) not in llm_ids:
                continue
            _metrics = (snip.get("metrics")
                        if isinstance(snip.get("metrics"), dict) else None)
            # Slide grounding when this moment maps to one; None otherwise
            # (deck-less recording) — the drafter handles a missing slide.
            idx = slide_index_for_offset(snip.get("start_offset_ms"), advances)
            slide = (
                slides[idx]
                if isinstance(idx, int) and 0 <= idx < len(slides)
                else None
            )
            # NO tone clause is appended — the coach labels blind, so the
            # learned direction guess must never reach this note (BLIND
            # COACH). The tone word lives only on the USER's serve-time
            # comment.
            draft = generate_coach_note_draft(
                transcript, slide,
                _metrics,
                take_comparison=take_comparison,
                goal=goal,
            )
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
