"""Force-alignment on reads (F1-CORE handoff §3, 2026-08-03).

A read recording has GROUND TRUTH: the exact ideal-text version the user
read (the read already pairs to a version via intake_context.read_target
= 'ideal_text' + ideal_version). Instead of trusting blind generic
transcription alone, the read's transcribed words are force-aligned
against that script:

  * matched words take the SCRIPT's surface form (near-exact transcript
    fidelity — the script is what was actually in front of the speaker);
  * every word keeps its Whisper timing (charisma_snippets.words already
    stores per-word start/end — see add_snippet_transcripts.sql);
  * the DEVIATIONS from the script (skips / substitutions / insertions)
    are persisted as structured deltas — deviations are signal, not
    noise (where the reader stumbled, improvised, or dropped a line).

Both outputs feed F1 piece (a): transcript fidelity + precise word
timing for the delivery/emphasis analysis.

Pure alignment core (difflib over normalized tokens — same dependency
class as take_alignment's anchors) + a best-effort orchestrator called
from the analysis worker's READ lane. Never raises into the pipeline;
a missing table degrades to a warning (migrations/add_read_alignments
.sql)."""
from __future__ import annotations

import difflib
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[\w']+")
# Plain-text guard for the script: the served ideal text can carry
# accent/emphasis marker tokens; their SYNTAX must not pollute the token
# stream ("orange" from a {{orange: opener would align as a said word).
# The [[...]] catch-all also swallows malformed moment wrappers that
# strip_moment_markers (which validates ids) leaves behind.
_MARKER_RE = re.compile(r"\{\{orange:|\}\}|\*\*|__|==|\[\[[^\]]*\]\]")


def _norm(token: str) -> str:
    return token.strip("'").lower()


def _script_tokens(text: str) -> list:
    """[(surface, norm)] for the script, markers stripped first."""
    try:
        from services.ideal_text_block import strip_moment_markers
        text = strip_moment_markers(text or "")
    except Exception:
        text = text or ""
    text = _MARKER_RE.sub(" ", text)
    return [(m.group(0), _norm(m.group(0)))
            for m in _TOKEN_RE.finditer(text) if _norm(m.group(0))]


def align_words_to_script(script_text: str, hyp_words: list) -> Optional[dict]:
    """The pure core. ``hyp_words`` = [{word, start_ms, end_ms}] in speech
    order (timings may be None when word timestamps were unavailable).

    Returns {aligned_transcript, words, deviations} or None when either
    side is empty.

      words       [{word, start_ms, end_ms, script_index}] — the aligned
                  transcript's words in order; script_index is the
                  matched script token's position (None on an insertion
                  or substitution — the reader's own words).
      deviations  [{kind: 'skip'|'substitution'|'insertion',
                    script_text, said_text, start_ms, end_ms}] — the
                  structured deltas from the script.

    Matched words render with the SCRIPT surface (fidelity); off-script
    words render verbatim as transcribed (L1 — never invented). Pure."""
    script = _script_tokens(script_text or "")
    hyp = [
        {"word": str(w.get("word") or "").strip(),
         "norm": _norm(str(w.get("word") or "")),
         "start_ms": w.get("start_ms"), "end_ms": w.get("end_ms")}
        for w in (hyp_words or [])
        if _norm(str(w.get("word") or ""))
    ]
    if not script or not hyp:
        return None

    sm = difflib.SequenceMatcher(
        None, [s[1] for s in script], [h["norm"] for h in hyp],
        autojunk=False)
    out_words: list = []
    deviations: list = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                h = hyp[j1 + k]
                out_words.append({
                    "word": script[i1 + k][0],
                    "start_ms": h["start_ms"], "end_ms": h["end_ms"],
                    "script_index": i1 + k,
                })
        elif op == "replace":
            said = hyp[j1:j2]
            for h in said:
                out_words.append({
                    "word": h["word"],
                    "start_ms": h["start_ms"], "end_ms": h["end_ms"],
                    "script_index": None,
                })
            deviations.append({
                "kind": "substitution",
                "script_text": " ".join(s[0] for s in script[i1:i2]),
                "said_text": " ".join(h["word"] for h in said),
                "start_ms": said[0]["start_ms"],
                "end_ms": said[-1]["end_ms"],
            })
        elif op == "delete":
            # Script words never spoken — anchor the skip to the moment
            # the audio moved past them.
            _at = (hyp[j1]["start_ms"] if j1 < len(hyp)
                   else hyp[-1]["end_ms"])
            deviations.append({
                "kind": "skip",
                "script_text": " ".join(s[0] for s in script[i1:i2]),
                "said_text": "",
                "start_ms": _at, "end_ms": _at,
            })
        elif op == "insert":
            said = hyp[j1:j2]
            for h in said:
                out_words.append({
                    "word": h["word"],
                    "start_ms": h["start_ms"], "end_ms": h["end_ms"],
                    "script_index": None,
                })
            deviations.append({
                "kind": "insertion",
                "script_text": "",
                "said_text": " ".join(h["word"] for h in said),
                "start_ms": said[0]["start_ms"],
                "end_ms": said[-1]["end_ms"],
            })
    return {
        "aligned_transcript": " ".join(w["word"] for w in out_words),
        "words": out_words,
        "deviations": deviations,
    }


def _read_version(ctx: dict) -> Optional[int]:
    """The ideal-text version this read was a read OF, or None when the
    tag is absent or unparseable (a read we cannot place against a
    script is never aligned — see _script_for_read)."""
    raw = ctx.get("ideal_version")
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _script_for_read(ctx: dict, arc_id: Any, database) -> Optional[str]:
    """The exact ideal-text version this read was a read OF: the frozen
    per-version snapshot first; the live row only when it still IS that
    version. Anything else → None (never align against the wrong text)."""
    version = _read_version(ctx)
    if version is None:
        return None
    snap = database.get_ideal_text_version(str(arc_id), version)
    if snap and (snap.get("text") or "").strip():
        return snap["text"]
    row = database.get_coach_arc_ideal_text(str(arc_id)) or {}
    if row.get("version") == version:
        live = (row.get("auto_text") or "").strip() \
            or (row.get("text") or "").strip()
        if live:
            return live
    return None


def _hyp_words_from_snippets(snips: list) -> list:
    """[{word, start_ms, end_ms}] across the read's snippets in speech
    order. Whisper word timings (charisma_snippets.words — absolute
    SECONDS) when present; a row without them degrades to its transcript
    tokens with null timings, so alignment still lands text-level."""
    out: list = []
    for s in sorted(snips or [],
                    key=lambda x: (x.get("start_offset_ms") or 0,
                                   str(x.get("id") or ""))):
        words = s.get("words")
        if isinstance(words, list) and words:
            for w in words:
                if not isinstance(w, dict):
                    continue
                token = str(w.get("word") or "").strip()
                if not token:
                    continue
                _s, _e = w.get("start"), w.get("end")
                out.append({
                    "word": token,
                    "start_ms": (int(round(float(_s) * 1000))
                                 if isinstance(_s, (int, float))
                                 and not isinstance(_s, bool) else None),
                    "end_ms": (int(round(float(_e) * 1000))
                               if isinstance(_e, (int, float))
                               and not isinstance(_e, bool) else None),
                })
            continue
        text = (s.get("transcript") or s.get("transcription_text") or "")
        for m in _TOKEN_RE.finditer(text):
            out.append({"word": m.group(0),
                        "start_ms": None, "end_ms": None})
    return out


def process_read_alignment(session_id: Any, database=None) -> bool:
    """Align one READ session against its script and persist the result.
    Called from the analysis worker's read lane after snippets exist.
    Best-effort: False (with a warning) on anything missing — never
    raises into the pipeline (LIVE LOOP)."""
    if database is None:
        from services.db import db as database
    try:
        sid = str(session_id)
        session = database.v2_get_session_by_id(sid) or {}
        _ctx = session.get("intake_context")
        ctx = _ctx if isinstance(_ctx, dict) else {}
        if ctx.get("read_target") != "ideal_text":
            return False        # not an ideal-text read — nothing to align
        arc_id = session.get("arc_id")
        version = _read_version(ctx)
        if not arc_id or version is None:
            return False
        script = _script_for_read(ctx, arc_id, database)
        if not script:
            logger.info("read_alignment: no script for sid=%s (version "
                        "snapshot missing) — skipped", sid)
            return False
        snips = database.get_snippets_by_session(sid) or []
        hyp = _hyp_words_from_snippets(snips)
        result = align_words_to_script(script, hyp)
        if not result:
            return False
        ok = database.upsert_read_alignment(sid, {
            "arc_id": str(arc_id),
            "ideal_version": version,
            "aligned_transcript": result["aligned_transcript"],
            "words": result["words"],
            "deviations": result["deviations"],
        })
        if ok:
            logger.info(
                "read_alignment: sid=%s words=%d deviations=%d",
                sid, len(result["words"]), len(result["deviations"]))
        return bool(ok)
    except Exception as e:
        logger.warning("read_alignment failed sid=%s: %s", session_id, e)
        return False
