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
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _polish_as_suggestions_enabled() -> bool:
    """Serve the VERBATIM ideal text and offer the light polish as approvable
    stars, instead of silently replacing (founder 2026-07-18). DEFAULT OFF —
    on top of MOMENT_SUGGESTIONS_ENABLED (the star machinery it reuses)."""
    return (os.getenv("POLISH_AS_SUGGESTIONS_ENABLED") or "0").strip().lower() \
        in ("1", "true", "yes")

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
                              require_ready: bool = True,
                              extra_anchor_ids=None) -> dict:
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

    # POLISH-AS-SUGGESTIONS (founder 2026-07-18): serve the speaker's VERBATIM
    # words and offer the light polish as an approvable star, instead of
    # silently replacing. More L1-faithful — the deliverable is what they
    # actually said until THEY accept a change. `polish` collects the diffs
    # for the worker to persist as suggestions.
    _polish_on = _polish_as_suggestions_enabled()
    paragraphs: list = []
    key_moments: list = []
    polish: list = []
    for s in (bp.get("slides") or []):
        _edited = (s.get("text") or "").strip()
        _verbatim = (s.get("verbatim") or "").strip()
        text = (_verbatim if _polish_on else _edited) or _edited
        if not text:
            continue
        snip_id = s.get("snippet_id")
        take_sid = s.get("session_id") or s.get("take_session_id")
        # A polish diff → an approvable suggestion; anchor the pick so its
        # star attaches. (When polish is OFF, key_phrases still bold as before.)
        _is_polish = bool(_polish_on and s.get("polished")
                          and snip_id and take_sid and _verbatim != _edited)
        if not _polish_on:
            # Bold the key openings — first occurrence of each phrase.
            for kp in (s.get("key_phrases") or [])[:5]:
                kp = (kp or "").strip()
                if kp and kp in text and f"**{kp}**" not in text:
                    text = text.replace(kp, f"**{kp}**", 1)
        # Key-moment anchor — a coach-confirmed breakthrough pick wraps
        # whole; so does a star-suggestion pick (extra_anchor_ids, founder
        # 2026-07-18 — the grey star needs an in-text anchor to attach to);
        # so does a polished pick (the polish star folds verbatim→edited).
        _extra = extra_anchor_ids or set()
        if (s.get("breakthrough") or _is_polish
                or (snip_id and str(snip_id) in _extra)) \
                and snip_id and take_sid:
            text = (f"[[moment:{snip_id}|{take_sid}]]{text}[[/moment]]")
            key_moments.append({
                "snippet_id": str(snip_id),
                "take_session_id": str(take_sid),
            })
            if _is_polish:
                polish.append({
                    "snippet_id": str(snip_id),
                    "edited": _edited,          # the fold target on Approve
                })
        paragraphs.append(text)

    return {
        "text": "\n\n".join(paragraphs)[:_MAX_BLOCK_CHARS],
        "key_moments": key_moments,
        "polish": polish,   # [{snippet_id, edited}] — the worker persists these
        "ready": True,
    }


def maybe_assemble_ideal_text(arc_id: Optional[str], *, database=None,
                              require_target: bool = True,
                              include_suggestion_anchors: bool = False) -> bool:
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
        _extra = None
        if include_suggestion_anchors:
            # Star suggestions (2026-07-18): a suggestion-flagged pick gets
            # an in-text anchor so its grey star can attach. Best-effort.
            try:
                _extra = set(
                    database.get_moment_suggestions_by_arc(arc_id) or {})
            except Exception:
                _extra = None
        auto = assemble_ideal_text_block(
            arc_id, database=database, require_ready=require_target,
            extra_anchor_ids=_extra)
        text = (auto.get("text") or "").strip()
        if not text:
            return False
        ok = database.persist_auto_ideal_text(arc_id, text)
        if ok:
            logger.info("ideal_text: eager draft persisted arc=%s chars=%d",
                        arc_id, len(text))
        # Persist the polish diffs as approvable suggestions (founder
        # 2026-07-18) — kind='replace' + trigger='polish', replacement =
        # the light-edited version, so Approve folds verbatim→edited via the
        # existing serve fold. The served text stays verbatim. Never displaces
        # an acoustic/structural star already on that snippet (upsert is
        # snippet-keyed; acoustic stars are stored earlier in the same worker
        # pass, so 'replace'/'structure' win — a polish only lands where the
        # snippet had no other star). Best-effort.
        if ok and _polish_as_suggestions_enabled():
            try:
                _existing = database.get_moment_suggestions_by_arc(arc_id) or {}
                for p in (auto.get("polish") or []):
                    _sid = str(p.get("snippet_id"))
                    _prior = _existing.get(_sid)
                    # An acoustic/structural star owns this snippet → leave it.
                    # A prior POLISH row may refresh (a re-record can re-edit).
                    if _prior and _prior.get("trigger") != "polish":
                        continue
                    _edited = (p.get("edited") or "").strip()
                    if not _edited:
                        continue
                    database.upsert_moment_suggestion(
                        _sid, str(arc_id), "replace", _edited, None, "polish")
            except Exception as _pe:
                logger.warning("ideal_text: polish persist failed arc=%s: %s",
                               arc_id, _pe)
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


def strip_moment_markers(text: Any) -> str:
    """Drop the [[moment:…]] / [[/moment]] WRAPPERS, keeping their inner
    text (founder audit 2026-07-18).

    Why the SD lane serves stripped text: the FE locates each star by
    finding the moment's `anchor` in the served text, but its segmenter
    REFUSES a range that sits inside a marker token — and the anchor (the
    moment's inner text) sits exactly inside the [[moment:…]] wrapper. With
    the wrappers present every star candidate is dropped, the whole
    star/suggestion layer goes dark, and a FREE grey suggestion falls
    through to the paid coach affordance. Serving the anchor path OR the
    marker path — never both — is the fix. Other rich markers (**bold**,
    {{orange:…}}, __underline__, //italic//) are untouched. Pure."""
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    out = MOMENT_SPAN_RE.sub(lambda m: m.group("inner"), text)
    # Any unclosed opening token left behind (legacy blocks) goes too.
    return MOMENT_RE.sub("", out)


def _accepts_database(fn) -> bool:
    try:
        import inspect
        return "database" in inspect.signature(fn).parameters
    except Exception:
        return False
