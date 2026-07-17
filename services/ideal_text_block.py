"""The ideal text as ONE block (founder 2026-07-15) — auto-assembled from the
arc's takes, reviewed/approved by the coach in the same minimalist editor the
user later sees, served to the student only once approved + unlocked ($25).

MARKER CONTRACT (shared with the FE renderer/editor — BOTH the coach panel
and the student notebook use the same set; founder 2026-07-17: the coach
gets every formatting affordance the student later has):
  * ``**…**``          — bold: the key OPENING fragments (from key_phrases).
  * ``__…__``          — underline.
  * ``//…//``          — italic (cursive).
  * ``{{orange:…}}``   — the ONE accent color (brand orange; no other
                          colors by design).
  * ``[[moment:<snippet_id>|<take_session_id>]]…[[/moment]]`` — a KEY
    MOMENT: tapping it in the notebook deep-links back to that exact
    moment on the take's feedback page (FE styles it distinctly from a
    plain ``__underline__``).
Markers are plain text (degrade readably anywhere); raw HTML is stripped at
the save routes, markers survive untouched — the BE never parses any of
them except MOMENT_RE. The coach's edit REPLACES the whole block, markers
included — the anchors travel with the text.

L1: the auto draft is assembled from the takes' COACH-CORRECTED verbatim picks
(build_best_presentation — selection + light stitch, never an AI rewrite);
the coach's one-block edit then owns it. The user's notebook copy is a
separate personal row (user_arc_ideal_notes) — editing it never touches this
canonical. AC-9: text only, no scores anywhere.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

MOMENT_RE = re.compile(
    r"\[\[moment:(?P<snippet_id>[0-9a-fA-F-]{8,})\|"
    r"(?P<session_id>[0-9a-fA-F-]{8,})\]\]"
)

# The FULL moment span, capturing the inner text (the FE's `anchor` — "the
# literal text fragment inside `text` to underline"). DOTALL so a moment can
# wrap a multi-line span.
MOMENT_SPAN_RE = re.compile(
    r"\[\[moment:(?P<snippet_id>[0-9a-fA-F-]{8,})\|"
    r"(?P<session_id>[0-9a-fA-F-]{8,})\]\](?P<inner>.*?)\[\[/moment\]\]",
    re.DOTALL,
)

_MAX_BLOCK_CHARS = 20000


def assemble_ideal_text_block(arc_id: str, *, database=None,
                              require_ready: bool = True) -> dict:
    """The AUTO draft: build_best_presentation's per-slide/section picks
    collapsed into one marker-carrying block.

    Per pick: the pick's key_phrases get **bolded** where they occur in its
    text (first occurrence each); a pick that is a coach-confirmed
    breakthrough is wrapped whole in a [[moment:…]] anchor (snippet_id +
    take session_id → the feedback-page deep link).

    Returns {"text": str, "key_moments": [{"snippet_id", "take_session_id"}],
    "ready": bool} — ready=False (empty text) below 3 takes. Pure given db.
    """
    if database is None:
        from services.db import db as database
    from services.best_presentation import build_best_presentation

    bp = build_best_presentation(arc_id, coach_view=True, database=database) \
        if _accepts_database(build_best_presentation) \
        else build_best_presentation(arc_id, coach_view=True)

    # require_ready=False (single deliverable, founder 2026-07-17): the ideal
    # text assembles from take 1 — bp["ready"] is only the legacy 3-take
    # progress flag; the compose itself runs on any takes present.
    if require_ready and not bp.get("ready"):
        return {"text": "", "key_moments": [], "ready": False}

    paragraphs: list = []
    key_moments: list = []
    for s in (bp.get("slides") or []):
        text = (s.get("text") or "").strip()
        if not text:
            continue
        # Bold the key openings — first occurrence of each phrase.
        for kp in (s.get("key_phrases") or [])[:5]:
            kp = (kp or "").strip()
            if kp and kp in text and f"**{kp}**" not in text:
                text = text.replace(kp, f"**{kp}**", 1)
        # Key-moment anchor — a coach-confirmed breakthrough pick wraps whole.
        snip_id = s.get("snippet_id")
        take_sid = s.get("session_id") or s.get("take_session_id")
        if s.get("breakthrough") and snip_id and take_sid:
            text = (f"[[moment:{snip_id}|{take_sid}]]{text}[[/moment]]")
            key_moments.append({
                "snippet_id": str(snip_id),
                "take_session_id": str(take_sid),
            })
        paragraphs.append(text)

    return {
        "text": "\n\n".join(paragraphs)[:_MAX_BLOCK_CHARS],
        "key_moments": key_moments,
        "ready": True,
    }


def maybe_assemble_ideal_text(arc_id: Optional[str], *, database=None,
                              require_target: bool = True) -> bool:
    """EAGER assembly (founder 2026-07-15): called from the analysis pipeline
    when a SPOKEN take completes — the moment the arc's 3rd spoken take is in,
    assemble the draft and PERSIST it as the machine block, so the coach's
    panel opens instantly and the coach list can badge "ideal text ready to
    review". Idempotent + guard-safe:
      * <3 spoken takes → no-op;
      * the WORKING text: a coach-edited or approved block is never touched
        (persist_auto_ideal_text's guard);
      * the frozen MACHINE copy (auto_text): always refreshed — a re-record
        improves the free instant surface even mid-coach-edit (2026-07-17).
    Best-effort: any failure returns False, never raises into the pipeline."""
    if not arc_id:
        return False
    try:
        if database is None:
            from services.db import db as database
        from services.best_presentation import (
            TAKES_TARGET, spoken_arc_sessions,
        )
        spoken = spoken_arc_sessions(database.get_arc_sessions(arc_id))
        # require_target=False (single deliverable, 2026-07-17): assemble
        # after EVERY take, take 1 included; the legacy lanes keep the
        # 3-take trigger.
        if require_target and len(spoken) < TAKES_TARGET:
            return False
        if not spoken:
            return False
        auto = assemble_ideal_text_block(
            arc_id, database=database, require_ready=require_target)
        text = (auto.get("text") or "").strip()
        if not text:
            return False
        ok = database.persist_auto_ideal_text(arc_id, text)
        if ok:
            logger.info("ideal_text: eager draft persisted arc=%s chars=%d",
                        arc_id, len(text))
        return ok
    except Exception as e:
        logger.warning("ideal_text: eager assembly failed arc=%s: %s",
                       arc_id, e)
        return False


def extract_key_moments(text: Any) -> list:
    """Parse the [[moment:…]] anchors out of a (possibly coach-edited) block —
    the served key_moments list always reflects the CURRENT text, so a coach
    deleting a moment's paragraph deletes its deep-link too.

    Each entry carries ``anchor`` — the moment's inner text, the literal
    fragment the FE locates in the served text to make tappable (the SD
    contract pin: the FE drops a key moment with no anchor). Falls back to
    the bare opening-token parse for a legacy block that has no closing
    ``[[/moment]]``. Pure."""
    if not isinstance(text, str) or not text:
        return []
    out = []
    seen = set()
    for m in MOMENT_SPAN_RE.finditer(text):
        key = (m.group("snippet_id"), m.group("session_id"))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "snippet_id": m.group("snippet_id"),
            "take_session_id": m.group("session_id"),
            "anchor": (m.group("inner") or "").strip(),
        })
    # Legacy fallback: opening tokens with no matching [[/moment]] close.
    for m in MOMENT_RE.finditer(text):
        key = (m.group("snippet_id"), m.group("session_id"))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "snippet_id": m.group("snippet_id"),
            "take_session_id": m.group("session_id"),
            "anchor": "",
        })
    return out


def _accepts_database(fn) -> bool:
    try:
        import inspect
        return "database" in inspect.signature(fn).parameters
    except Exception:
        return False
