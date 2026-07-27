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

L1 (docstring-truth fix 2026-07-18 — the old "never an AI rewrite" wording
overclaimed): the auto draft is assembled from the takes' COACH-CORRECTED
verbatim picks via build_best_presentation, whose compose step IS a
constrained LLM pass — "mostly verbatim, a few words per slide for
continuity, never new claims" (the founder-sanctioned light polish, i.e.
seam-smoothing, not a free rewrite). Under POLISH_AS_SUGGESTIONS_ENABLED
even that polish stops being silent: the VERBATIM words are served and the
polish is offered as an approvable star. The coach's one-block edit then
owns the canonical. The user's notebook copy is a separate personal row
(user_arc_ideal_notes) — editing it never touches this canonical. AC-9:
text only, no scores anywhere.
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

_ACCENT_OPEN = "{{orange:"
_ACCENT_CLOSE = "}}"


def accent_span(inner: Any) -> str:
    """``inner`` wrapped in ``{{orange:…}}`` ONE LINE AT A TIME.

    The founder's 2026-07-27 screenshot showed a bare ``{{orange:`` sitting on
    its own line in the middle of the student's ideal text. Two reasons a
    marker may never straddle a newline: the contract above promises markers
    are plain text that "degrade readably anywhere" (a dangling opener does
    not), and the FE's rich-marker parser is FLAT and single-line, so it
    cannot close a span that crosses ``\\n``.

    So ``"a\\nb"`` becomes ``"{{orange:a}}\\n{{orange:b}}"``. A blank line is
    left alone (no empty ``{{orange:}}``), and whitespace at each line's edges
    stays OUTSIDE its wrapper so the words inside are exactly the words that
    were emphasized. Pure."""
    if not isinstance(inner, str) or not inner.strip():
        return inner if isinstance(inner, str) else ""
    out = []
    for line in inner.split("\n"):
        body = line.strip()
        if not body:
            out.append(line)
            continue
        lead = len(line) - len(line.lstrip())
        out.append(line[:lead] + _ACCENT_OPEN + body + _ACCENT_CLOSE
                   + line[lead + len(body):])
    return "\n".join(out)


def wrap_accent(text: Any, lo: Any, hi: Any) -> str:
    """``text`` with ``text[lo:hi]`` accented via accent_span — the ONE way
    the BE emits ``{{orange:…}}``.

    A span that is already accented (or sits immediately after an opener)
    returns ``text`` untouched — the fold and the ledger bake both run over
    text the other may have already marked, and a double wrap prints its own
    syntax. Out-of-bounds or non-int offsets are a no-op rather than a
    corruption. Pure."""
    if not isinstance(text, str):
        return ""
    if not isinstance(lo, int) or not isinstance(hi, int):
        return text
    if not (0 <= lo < hi <= len(text)):
        return text
    span = text[lo:hi]
    if _ACCENT_OPEN in span or text[:lo].endswith(_ACCENT_OPEN):
        return text
    return text[:lo] + accent_span(span) + text[hi:]


def sanitize_markers(text: Any) -> str:
    """The last guard before the text goes on the wire: drop every marker
    token that cannot render, keeping every WORD (founder 2026-07-27).

    Three things happen, in one left-to-right pass:
      * an accent span that crosses a newline is RE-WRAPPED per line (the
        emphasis survives; only the unrenderable placement changes) — this is
        what rescues rows baked before wrap_accent existed;
      * an unmatched ``{{orange:`` (no ``}}`` before end-of-text or before the
        next opener) and a stray ``}}`` lose the TOKEN, never their words;
      * an odd ``**`` loses its last occurrence.

    ``__``/``//`` are deliberately NOT balanced — ``//`` occurs in every URL
    and a "fix" there would corrupt real content. ``[[moment:…]]`` is
    untouched (MOMENT_RE is the one marker the BE parses; stripping is
    strip_moment_markers' job). Idempotent, and never reorders or deletes
    prose. Pure."""
    if not isinstance(text, str) or not text:
        return text if isinstance(text, str) else ""
    out = []
    i, n = 0, len(text)
    while i < n:
        j = text.find(_ACCENT_OPEN, i)
        if j < 0:
            out.append(text[i:].replace(_ACCENT_CLOSE, ""))
            break
        out.append(text[i:j].replace(_ACCENT_CLOSE, ""))
        body = j + len(_ACCENT_OPEN)
        close = text.find(_ACCENT_CLOSE, body)
        nxt = text.find(_ACCENT_OPEN, body)
        if close < 0 or (0 <= nxt < close):
            # Unmatched opener — drop the token and carry on from the words.
            i = body
            continue
        out.append(accent_span(text[body:close]))
        i = close + len(_ACCENT_CLOSE)
    result = "".join(out)
    if result.count("**") % 2:
        _last = result.rfind("**")
        result = result[:_last] + result[_last + 2:]
    return result


def _living_transcript_enabled() -> bool:
    """THE DOCUMENT MODEL (founder decision 2026-07-20 #1): the ideal text
    is the speaker's FULL transcript of the take, not a stitched selection
    of best-ranked moments ("it is very much shorter than what I really
    said"). DEFAULT OFF — flag ON swaps the document source; every other
    lane (ledger bake, protected phrases, versions, snapshots, coach
    verify) is untouched and keeps working on the new base."""
    return (os.getenv("LIVING_TRANSCRIPT_ENABLED") or "0").strip().lower() \
        in ("1", "true", "yes")


def assemble_transcript_document(arc_id: str, *, database=None) -> dict:
    """The full-transcript document, ledger-baked — the flag-ON assembly
    path. Same return shape as assemble_ideal_text_block so every caller
    (persist, version bump, snapshot, serve) works unchanged.

    key_moments/polish are EMPTY here on purpose: on the transcript
    document, changes are span-anchored tracked changes (BE-C), not
    moment-wrapped picks. The anchor markers stay out of the text."""
    if database is None:
        from services.db import db as database
    from services.ideal_decision_ledger import bake_piece, load_ledger
    from services.transcript_document import (
        build_transcript_document, relocate_pieces,
    )

    doc = build_transcript_document(arc_id, database=database)
    if not doc or not (doc.get("text") or "").strip():
        return {"text": "", "key_moments": [], "polish": [], "ready": False}

    text = doc["text"]
    pieces = doc.get("pieces") or []
    # The student's APPROVED changes bake into every future document
    # (gradual-refinement rule 1). Applied to the whole document, then the
    # pieces are RE-ANCHORED monotonically onto the baked text — so an
    # approval takes effect immediately AND the surviving anchors stay
    # exact (both were confirmed review findings).
    try:
        _approved = [r for r in load_ledger(database, arc_id)
                     if r.get("decision") == "approved"]
        if _approved:
            baked = bake_piece(text, _approved)
            if baked != text:
                text = baked
                pieces = relocate_pieces(text, pieces)
    except Exception as _le:
        logger.warning("living_transcript: bake failed arc=%s: %s",
                       arc_id, _le)

    # Coach-surfaced pieces stay KEY MOMENTS on the document: the
    # explanations lane (and the only paid surface) must not go dark in
    # transcript mode (review finding).
    key_moments = [{
        "snippet_id": p["snippet_id"],
        "take_session_id": p.get("take_session_id"),
        "anchor": p.get("text") or "",
    } for p in pieces if p.get("breakthrough")]

    return {
        "text": text[:_MAX_BLOCK_CHARS],
        "key_moments": key_moments,
        "polish": [],
        "ready": True,
        "document": {
            "pieces": pieces,
            "take_session_id": doc.get("take_session_id"),
            "take_index": doc.get("take_index"),
        },
    }


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

    # ── DECISION LEDGER (founder 2026-07-20, gradual refinement rule 1):
    # every change the student APPROVED bakes into this machine copy
    # wherever its phrase still occurs — plain text, no star, never
    # reversed. Decided phrases (approved OR dismissed) are also excluded
    # from re-offering (rule 2/3: each version's stars = its delta).
    # Best-effort: no ledger (pre-migration) → today's behavior. ──
    from services.ideal_decision_ledger import (
        bake_piece, ledger_keys, load_ledger, normalize_phrase,
    )
    _ledger_rows = load_ledger(database, arc_id)
    _approved = [r for r in _ledger_rows
                 if r.get("decision") == "approved"]
    _decided = ledger_keys(_ledger_rows)

    paragraphs: list = []
    key_moments: list = []
    polish: list = []
    for s in (bp.get("slides") or []):
        _edited = (s.get("text") or "").strip()
        _verbatim = (s.get("verbatim") or "").strip()
        text = (_verbatim if _polish_on else _edited) or _edited
        if not text:
            continue
        if _approved:
            text = bake_piece(text, _approved)
        snip_id = s.get("snippet_id")
        take_sid = s.get("session_id") or s.get("take_session_id")
        # A polish diff → an approvable suggestion; anchor the pick so its
        # star attaches. (When polish is OFF, key_phrases still bold as before.)
        # A phrase the student already DECIDED on (approved → just baked
        # above; dismissed → remembered) is never re-offered.
        _is_polish = bool(_polish_on and s.get("polished")
                          and snip_id and take_sid and _verbatim != _edited
                          and ("polish", normalize_phrase(_verbatim))
                          not in _decided)
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
                    "verbatim": _verbatim,      # recurrence check (rule 4a)
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
        # THE DOCUMENT SOURCE (founder decision 2026-07-20 #1): the full
        # transcript of the latest spoken take, or — flag OFF — the legacy
        # best-moments selection. Everything downstream (persist, version
        # bump, snapshot, verify, ledger) is identical either way.
        from services.master_document import (
            assemble_master_document, master_document_enabled,
        )
        if _living_transcript_enabled() and master_document_enabled():
            # THE MASTER MODEL (founder 2026-07-22): one persistent
            # document per project; new takes only offer block upgrades.
            # No skeleton yet (flip-ON window / pre-migration) → the
            # living-transcript document keeps serving; assembly must
            # never silently stop (review findings #19/#29).
            auto = assemble_master_document(arc_id, database=database)
            if not auto.get("ready"):
                auto = assemble_transcript_document(arc_id,
                                                    database=database)
        elif _living_transcript_enabled():
            auto = assemble_transcript_document(arc_id, database=database)
        else:
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
                # Protected phrases (founder 2026-07-20, rule 4a): a polish
                # whose changed span is wording the speaker uses in >= 2
                # takes is THEIR phrasing — the smoothing is never offered.
                from services.protected_phrases import (
                    collect_take_texts, phrase_recurs,
                )
                from services.suggestion_quotes import diff_quote
                _take_texts = collect_take_texts(database, arc_id)
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
                    _span = diff_quote(p.get("verbatim"), _edited) \
                        or (p.get("verbatim") or "")
                    if phrase_recurs(_span, _take_texts):
                        continue   # their wording — keep it (rule 4a)
                    database.upsert_moment_suggestion(
                        _sid, str(arc_id), "replace", _edited, None, "polish")
            except Exception as _pe:
                logger.warning("ideal_text: polish persist failed arc=%s: %s",
                               arc_id, _pe)
        # ── Per-VERSION snapshot (founder 2026-07-20): freeze this
        # version's text (with anchors) + its pending reasoning, so the
        # version bubble stays readable after later versions supersede it
        # (the GET's ?version form serves it). Runs AFTER the polish
        # persist so the step's suggestions are complete. Sanitized at
        # write time — AC-9/CONSTRUCT hold in storage, not just at serve.
        # Best-effort; pre-migration → no history, today's behavior. ──
        if ok:
            try:
                _row_now = database.get_coach_arc_ideal_text(arc_id) or {}
                _v_now = _row_now.get("version") or 1
                _sugs_now = database.get_moment_suggestions_by_arc(
                    arc_id) or {}
                database.upsert_ideal_text_version(
                    str(arc_id), int(_v_now), text,
                    sanitize_suggestions_snapshot(_sugs_now))
            except Exception as _sv_err:
                logger.warning(
                    "ideal_text: version snapshot failed arc=%s: %s",
                    arc_id, _sv_err)
        return ok
    except Exception as e:
        logger.warning("ideal_text: eager assembly failed arc=%s: %s",
                       arc_id, e)
        return False


def sanitize_suggestions_snapshot(sugs: Any) -> list:
    """The user-safe projection of the pending suggestions for a version
    SNAPSHOT (founder 2026-07-20) — mirrors the serve shapes exactly, so
    AC-9/CONSTRUCT hold in STORAGE: structure/delivery keep only their
    device vocabulary; text suggestions keep replacement/why with the
    trigger clamped to 'polish'|None (the raw threat/charisma vocabulary
    never lands in a row a user payload is built from). Pure."""
    out = []
    for sid, s in (sugs or {}).items():
        if not isinstance(s, dict):
            continue
        kind = s.get("kind")
        if kind in ("structure", "delivery"):
            out.append({
                "snippet_id": str(sid), "kind": kind,
                "device": s.get("trigger"),
                "quote": (s.get("why") if kind == "structure" else None),
            })
        elif kind in ("emphasize", "replace"):
            out.append({
                "snippet_id": str(sid), "kind": kind,
                "replacement": s.get("replacement_text"),
                "why": s.get("why"),
                "trigger": ("polish" if s.get("trigger") == "polish"
                            else None),
            })
    return out


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
