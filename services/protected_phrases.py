"""Protected phrases (founder 2026-07-20) — gradual refinement rule 4.

Two protections, both on the STUDENT's side of the text:

  A. RECURRING WORDING — "if a user keeps using certain phrases across the
     recordings, we take it as THEIR wording and do not force the change."
     A phrase that appears in >= 2 spoken takes of the arc is the speaker's
     own voice: polish and stickiness-replace suggestions targeting it are
     never offered. HARMFUL content is the explicit carve-out — threat- and
     profanity-triggered replaces are still offered.

  B. USER-EDIT INHERITANCE — the student's in-place edit of version N is
     decomposed into phrase-level decisions (difflib, word-level) and
     written onto the decision ledger (source='user_edit', approved), so
     version N+1 bakes their wording forward wherever the phrases still
     occur. Pure insertions can't be phrase-keyed and are skipped (v1);
     a wholesale rewrite (low similarity) is kept as the edit itself and
     NOT decomposed — grafting a rewrite piecewise would be dishonest.

L1: both protections only ever preserve or apply the student's own words.
AC-9: internal — nothing here rides a user payload. Pure helpers +
best-effort db calls; every failure degrades to today's behavior.
"""
from __future__ import annotations

import difflib
import logging
import re
from typing import Any, Optional

from services.ideal_decision_ledger import normalize_phrase

logger = logging.getLogger(__name__)

# A recurring phrase shorter than this is noise ("a", "the"), not wording.
_MIN_PHRASE_CHARS = 4
# One decomposed edit block bigger than this is a rewrite, not a phrase.
_MAX_BLOCK_CHARS = 160
# Below this whole-text similarity the edit is a rewrite — no decomposition.
_MIN_EDIT_RATIO = 0.5

_MARKERS = (
    re.compile(r"\[\[moment:[^\]]*\]\]"),   # anchor open
    re.compile(r"\[\[/moment\]\]"),         # anchor close
    re.compile(r"\{\{orange:"),             # accent open (keep inner text)
    re.compile(r"\}\}"),                    # accent close
    re.compile(r"\*\*"),                    # bold
)


def _plain(text: Any) -> str:
    """The text with every wire marker stripped — decomposition compares
    WORDS, never markup."""
    if not isinstance(text, str):
        return ""
    out = text
    for pat in _MARKERS:
        out = pat.sub("", out)
    return re.sub(r"\s+", " ", out).strip()


def collect_take_texts(database, arc_id: Any) -> list:
    """One normalized transcript per SPOKEN take of the arc — the corpus
    the recurrence check runs against. Best-effort: [] on any failure."""
    if not arc_id:
        return []
    try:
        from services.best_presentation import spoken_arc_sessions
        sessions = spoken_arc_sessions(database.get_arc_sessions(arc_id))
        texts = []
        for s in sessions:
            sid = str(s.get("id") or "")
            if not sid:
                continue
            parts = []
            for sn in (database.get_snippets_by_session(sid) or []):
                t = (sn.get("transcript")
                     or sn.get("transcription_text") or "").strip()
                if t:
                    parts.append(t)
            joined = normalize_phrase(" ".join(parts))
            if joined:
                texts.append(joined)
        return texts
    except Exception as e:
        logger.warning("protected_phrases: take texts failed arc=%s: %s",
                       arc_id, e)
        return []


def phrase_recurs(phrase: Any, take_texts: Any, *,
                  min_takes: int = 2) -> bool:
    """True when the normalized phrase occurs in >= min_takes distinct
    takes — the speaker's OWN wording, protected from forced change."""
    norm = normalize_phrase(phrase)
    if len(norm) < _MIN_PHRASE_CHARS:
        return False
    hits = sum(1 for t in (take_texts or []) if norm in t)
    return hits >= min_takes


def decompose_user_edit(base_text: Any, user_text: Any) -> list:
    """The student's edit as phrase-level decisions:
    [{old, new}] with old != '' (a deletion has new='';
    pure insertions are skipped — no phrase to key on). Word-level
    difflib; markers stripped first; a low-similarity rewrite returns []
    (kept as the wholesale edit, not grafted piecewise)."""
    a = _plain(base_text)
    b = _plain(user_text)
    if not a or not b or a == b:
        return []
    a_words, b_words = a.split(" "), b.split(" ")
    sm = difflib.SequenceMatcher(None, a_words, b_words, autojunk=False)
    if sm.ratio() < _MIN_EDIT_RATIO:
        return []
    out = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag in ("equal", "insert"):
            continue
        old = " ".join(a_words[i1:i2]).strip()
        new = " ".join(b_words[j1:j2]).strip() if tag == "replace" else ""
        if not old or len(old) > _MAX_BLOCK_CHARS \
                or len(new) > _MAX_BLOCK_CHARS:
            continue
        out.append({"old": old, "new": new})
    return out


def record_user_edit_decisions(database, arc_id: Any, *, base_text: Any,
                               user_text: Any,
                               version: Any = None) -> int:
    """Write the decomposed edit onto the decision ledger — each block an
    APPROVED 'replace' with source='user_edit', so the next assembly bakes
    the student's wording forward (rule: their edit is never reversed).
    Returns rows written; best-effort, never raises."""
    try:
        blocks = decompose_user_edit(base_text, user_text)
        written = 0
        for blk in blocks:
            ok = database.upsert_ideal_decision(
                arc_id=str(arc_id), kind="replace",
                target_phrase=normalize_phrase(blk["old"]),
                display_phrase=blk["old"],
                replacement_text=blk["new"],
                decision="approved", source="user_edit",
                snippet_id=None,
                version=(version if isinstance(version, int) else None))
            if ok:
                written += 1
        return written
    except Exception as e:
        logger.warning("protected_phrases: edit ledger failed arc=%s: %s",
                       arc_id, e)
        return 0
