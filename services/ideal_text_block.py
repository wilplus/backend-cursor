"""The ideal text as ONE block (founder 2026-07-15) — auto-assembled from the
arc's takes, reviewed/approved by the coach in the same minimalist editor the
user later sees, served to the student only once approved + unlocked ($25).

MARKER CONTRACT (shared with the FE renderer/editor):
  * ``**…**``  — bold: the key OPENING fragments (from the coach key_phrases).
  * ``[[moment:<snippet_id>|<take_session_id>]]…[[/moment]]`` — an underlined
    KEY MOMENT: tapping it in the notebook deep-links back to that exact
    moment on the take's feedback page.
Markers are plain text (degrade readably anywhere); raw HTML is stripped at
the save routes. The coach's edit REPLACES the whole block, markers included —
the anchors travel with the text.

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

_MAX_BLOCK_CHARS = 20000


def assemble_ideal_text_block(arc_id: str, *, database=None) -> dict:
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

    if not bp.get("ready"):
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


def extract_key_moments(text: Any) -> list:
    """Parse the [[moment:…]] anchors out of a (possibly coach-edited) block —
    the served key_moments list always reflects the CURRENT text, so a coach
    deleting a moment's paragraph deletes its deep-link too. Pure."""
    if not isinstance(text, str) or not text:
        return []
    out = []
    seen = set()
    for m in MOMENT_RE.finditer(text):
        key = (m.group("snippet_id"), m.group("session_id"))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "snippet_id": m.group("snippet_id"),
            "take_session_id": m.group("session_id"),
        })
    return out


def _accepts_database(fn) -> bool:
    try:
        import inspect
        return "database" in inspect.signature(fn).parameters
    except Exception:
        return False
