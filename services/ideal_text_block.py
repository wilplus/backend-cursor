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

L1: the document is the full transcript of the Take it is built from
(``assemble_transcript_document``), ledger-baked. The best-of assembly
(``assemble_ideal_text_block`` over ``build_best_presentation``'s picks, with
its polish-as-suggestions lane) is removed (founder 2026-10-05, N48.3 Q13 A;
contract 52): it was the flag-off path of LIVING_TRANSCRIPT_ENABLED, which is
on in production. The coach's one-block edit then owns the canonical. The user's notebook copy is a separate personal row
(user_arc_ideal_notes) — editing it never touches this canonical. AC-9:
text only, no scores anywhere.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional
from config import Config

config = Config()

logger = logging.getLogger(__name__)


def _polish_as_suggestions_enabled() -> bool:
    """Serve the VERBATIM ideal text and offer the light polish as approvable
    stars, instead of silently replacing (founder 2026-07-18). DEFAULT OFF —
    on top of MOMENT_SUGGESTIONS_ENABLED (the star machinery it reuses)."""
    return bool(config.POLISH_AS_SUGGESTIONS_ENABLED)

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

# ── THE EMPHASIS WINDOW (SPEC-APPENDIX-F §F.4; founder 2026-08-10: "the
# interventions need to be precise … use the table to connect it as per
# spec"). ──
#
# The table assigns emphasis (V1–V5) and rhetorical devices (V11–V13) the
# UNIT window — the intonation unit, ~1.6 s of speech, Chafe mean ~4.84
# words realised over 1–2 s (§F.1). An accent is a pointer at a spoken
# moment; a pointer the size of a paragraph points at nothing. The ceiling
# is TWO realised units: room for a natural spoken phrase, never a sentence
# run — the founder's screenshot showed whole-snippet transcripts (a moment
# accept's target is the full snippet) painted orange across ten sentences.
#
# Enforced at BOTH ends: candidates beyond the window never become offers
# (intervention_candidates — a budget slot must not be spent on paint the
# bake will refuse), and the ledger bake refuses to paint an oversize
# emphasize row (legacy rows already approved). The WORDS are never touched
# — only the paint is withheld.
ACCENT_WINDOW_MAX_WORDS = 12


def within_accent_window(phrase: Any) -> bool:
    """May this phrase be PAINTED as an emphasis accent? (§F.4 UNIT rule.)

    Words are counted on the marker-free text — a phrase carrying baked
    ``**``/``{{orange:…}}`` tokens must measure its words, not its syntax.
    Empty or non-string phrases refuse (nothing to point at). Pure."""
    if not isinstance(phrase, str):
        return False
    words = phrase.replace(_ACCENT_OPEN, " ").replace(_ACCENT_CLOSE, " ") \
        .replace("**", " ").split()
    return 0 < len(words) <= ACCENT_WINDOW_MAX_WORDS


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
    is the speaker's FULL transcript of the take. The flag no longer swaps
    the document source: the transcript document is the only one since the
    best-of assembly was removed (2026-10-05, N48.3 Q13 A). It still gates
    the lanes built on that document (the tracked-changes block, the
    post-decision reassembly, the canonical provenance read), and it is ON
    in production; the code default stays 0 until every service's boot line
    shows it set (audit A2, remediation C5). Read once at boot through
    Config (audit Q-A5)."""
    return bool(config.LIVING_TRANSCRIPT_ENABLED)


def assemble_transcript_document(arc_id: str, *, database=None,
                                 session_id: Optional[str] = None) -> dict:
    """The full-transcript document, ledger-baked — the only assembly path
    since the best-of assembly was removed (N48.3 Q13 A). Every caller
    (persist, version bump, snapshot, serve) reads this one shape.

    key_moments/polish are EMPTY here on purpose: on the transcript
    document, changes are span-anchored tracked changes (BE-C), not
    moment-wrapped picks. The anchor markers stay out of the text."""
    if database is None:
        from services.db import db as database
    from services.ideal_decision_ledger import bake_piece, load_ledger
    from services.transcript_document import (
        build_transcript_document, relocate_pieces,
    )

    doc = build_transcript_document(
        arc_id, database=database, session_id=session_id)
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
                # paragraph_fallback: a baked change rewrites the very
                # words it lands on, so the piece it touched is the one
                # that vanishes. Anchoring it to its paragraph keeps the
                # piece and its slide index instead of losing both to a
                # successful accept.
                pieces = relocate_pieces(text, pieces,
                                         paragraph_fallback=True)
    except Exception as _le:
        logger.warning("living_transcript: bake failed arc=%s: %s",
                       arc_id, _le)

    return {
        "text": text[:_MAX_BLOCK_CHARS],
        "key_moments": [],
        "polish": [],
        "ready": True,
        "document": {
            "pieces": pieces,
            # One row per served paragraph. Slide linkage consumes paragraph
            # identity, not snippet identity; persisting only `pieces` forced
            # the GET to rebuild this from the latest Take, which no longer
            # describes a canonical Take-1 document after review 2.0.
            "paragraphs": [
                dict(p) for p in (doc.get("paragraphs") or [])
                if isinstance(p, dict)
            ],
            "take_session_id": doc.get("take_session_id"),
            "take_index": doc.get("take_index"),
        },
    }


def _snapshot_version(database, arc_id, text) -> None:
    """Per-VERSION snapshot (founder 2026-07-20): freeze this version's text
    (with anchors) + its pending reasoning, so the version bubble stays
    readable after later versions supersede it (the GET's ?version form
    serves it). Sanitized at write time — AC-9/CONSTRUCT hold in storage,
    not just at serve. Pre-migration → no history, today's behavior."""
    _row_now = database.ideal_text.get_coach_arc_ideal_text(arc_id) or {}
    _v_now = _row_now.get("version") or 1
    _sugs_now = database.get_moment_suggestions_by_arc(arc_id) or {}
    _doc_now = _row_now.get("document")
    database.upsert_ideal_text_version(
        str(arc_id), int(_v_now), text,
        sanitize_suggestions_snapshot(_sugs_now),
        document=_doc_now if isinstance(_doc_now, dict) else None)


def _take_index(value: Any) -> Optional[int]:
    """A real 1-based Take index, or None (a bool is not an index)."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value


def maybe_assemble_ideal_text(arc_id: Optional[str], *, database=None,
                              require_target: bool = True,
                              source_session_id: Optional[str] = None,
                              degradation=None) -> bool:
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
    Best-effort: any failure returns False, never raises into the pipeline.
    Every optional stage names itself in ``degradation`` (a
    ``DegradationLog``, audit Q-C1) when it falls back; the pipeline passes
    its run's log so the job row carries the list."""
    if not arc_id:
        return False
    from services.degradation import DegradationLog
    log = (degradation if degradation is not None
           else DegradationLog("ideal_text"))
    try:
        if database is None:
            from services.db import db as database
        _ideal_text_repo = getattr(database, "ideal_text", None)
        get_existing = getattr(_ideal_text_repo,
                               "get_coach_arc_ideal_text", None)
        existing = get_existing(arc_id) if callable(get_existing) else None
        existing = existing or {}
        if str(existing.get("auto_text") or existing.get("text") or "").strip():
            # Take 1 creates the canonical Ideal Text. Later takes produce
            # feedback proposals; they never refresh, rebuild or version-bump
            # the document behind the user's back.
            return True
        from services.slide_selection import (
            TAKES_TARGET, spoken_arc_sessions,
        )
        spoken = spoken_arc_sessions(database.takes.get_arc_sessions(arc_id))
        source_take_count = len(spoken)
        if source_session_id:
            # Pin the source to THIS accepted recording. An arc-level "latest
            # take" lookup could otherwise build the document from a different
            # Take than the one being processed.
            #
            # ANY spoken Take may be the source, not only Take 1. We only get
            # here when the Project has no document at all (the guard above),
            # and since Option A (2026-09-22) the worker asks a later Take to
            # create it in exactly that case. Refusing every index but 1 made
            # that request a silent no-op: the poll timed out and the Take
            # ended as `failed_ideal_text_unconfirmed`.
            source_row = database.v2_get_session_by_id(
                str(source_session_id)) or {}
            source_take_index = source_row.get("take_index")
            pinned_index = _take_index(source_take_index)
            if (str(source_row.get("arc_id") or "") != str(arc_id)
                    or pinned_index is None
                    or source_row.get("recording_kind") == "read"):
                logger.warning(
                    "ideal_text: source take refused arc=%s sid=%s "
                    "row_arc=%s take_index=%r kind=%s", arc_id,
                    source_session_id, source_row.get("arc_id"),
                    source_take_index, source_row.get("recording_kind"))
                return False
            source_take_count = pinned_index
        # require_target=False (single deliverable, 2026-07-17): assemble
        # after EVERY take, take 1 included; the legacy lanes keep the
        # 3-take trigger.
        if require_target and len(spoken) < TAKES_TARGET:
            return False
        if not spoken:
            logger.warning(
                "ideal_text: no spoken take on the project arc=%s sid=%s",
                arc_id, source_session_id)
            return False
        # THE DOCUMENT SOURCE (founder decision 2026-07-20 #1): the full
        # transcript of a spoken Take, pinned to the accepted recording when
        # one is named. The legacy best-moments selection that used to run
        # with LIVING_TRANSCRIPT_ENABLED off is removed (N48.3 Q13 A); the
        # master-document lane is retired too (audit C2).
        if source_session_id:
            # Exact provenance beats an arc-level "latest take" lookup on a
            # retry. build_transcript_document's historical form reads only
            # this session's already-persisted snippets/corrections.
            auto = assemble_transcript_document(
                arc_id,
                database=database,
                session_id=str(source_session_id),
            )
        else:
            auto = assemble_transcript_document(arc_id, database=database)
        text = (auto.get("text") or "").strip()
        if not text:
            logger.warning(
                "ideal_text: assembled document is empty arc=%s sid=%s",
                arc_id, source_session_id)
            return False
        # THE VERSION IS THE TAKE COUNT (founder 2026-08-05): take 1 → 1.0,
        # take 2 → 2.0. `spoken` is the same list the trigger above counted,
        # so the number the badge shows and the number that gated assembly
        # can never disagree.
        ok = database.persist_auto_ideal_text(
            arc_id, text, take_count=source_take_count,
            # The piece provenance for THIS text, written in the same upsert.
            # It is what services/part_acoustics.fold_session scores per part;
            # before 2026-08-13 it was never persisted at all, so the fold had
            # nothing to read and the acoustic KPI never measured a take.
            document=auto.get("document"))
        if ok:
            logger.info(
                "ideal_text: eager draft persisted arc=%s chars=%d v=%d",
                arc_id, len(text), source_take_count)
        # Best-effort stages after the persist, each named when it falls
        # back: the per-version snapshot and the cold-open publication — a write-boundary responsibility; the
        # student GET intentionally cannot assemble or repair a document, it
        # only reads the immutable head published here.
        if ok:
            log.run("assembly.version_snapshot",
                    lambda: _snapshot_version(database, arc_id, text))

            def _publish_core() -> None:
                from services.ideal_text_core_snapshot import publish_for_arc
                publish_for_arc(database, str(arc_id))
            log.run("assembly.core_snapshot_publish", _publish_core)
        return ok
    except Exception as e:
        # The whole assembly fell back (False, as always) — and now says so.
        log.record("assembly", e)
        return False


def sanitize_suggestions_snapshot(sugs: Any) -> list:
    """The user-safe projection of the pending suggestions for a version
    SNAPSHOT (founder 2026-07-20) — mirrors the serve shapes exactly, so
    AC-9/CONSTRUCT hold in STORAGE: structure/delivery keep only their
    device vocabulary; text suggestions keep replacement/why with the
    trigger clamped to 'polish'|None (internal classifier vocabulary never
    lands in a row a user payload is built from). Pure."""
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
