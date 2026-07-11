"""Engine 5 — the key-moments game (founder 2026-07-11, replaces the 501
stub behind the existing $25 gate).

Rounds mix the arc owner's COACH-CONFIRMED key moments (challenge-labeled)
with their OWN coach-unmarked/threat moments as neutral decoys. Truth is
never in the rounds payload — the FE learns it by answering. Every answer
persists into snippet_peer_labels (source='game') as SECOND-ORDER signal
below coach truth (L2/L3 fence: never joined into training_labels).

"Here is why" (max 3 short paragraphs, prose only, AC-9-qualitative):
  1. the moment's load-bearing words (keywords the FE tints orange),
  2. this user's mined acoustic patterns (Engine 4 — services/user_patterns),
  3. the moment's plain-language delivery technique (_moment_note).
Plus the coach's breakthrough video when one is attached to the moment.

Order is DETERMINISTIC (sha1 of arc+snippet — no random, replayable), with
an optional pinned first round for /game?snippet=<id> deep links.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_MAX_ROUNDS = 10


def _order_key(arc_id: Any, snippet_id: Any) -> str:
    return hashlib.sha1(f"{arc_id}:{snippet_id}".encode("utf-8")).hexdigest()


def _arc_moments(db, arc_id: Any) -> tuple:
    """(keys, decoys, snippets_by_id) for the arc — coach truth only.
    keys = challenge-labeled; decoys = everything else (unlabeled + threat:
    both are honestly 'not a key moment')."""
    from services.challenge_threat import resolve_direction
    keys: list = []
    decoys: list = []
    by_id: dict = {}
    for sess in (db.get_arc_sessions(arc_id) or []):
        sid = sess.get("id")
        if not sid:
            continue
        labels = {
            str(r.get("snippet_id")): r.get("value")
            for r in (db.get_training_labels(sid) or [])
        }
        for s in (db.get_snippets_by_session(sid) or []):
            snip_id = str(s.get("id"))
            if not (s.get("transcript") or "").strip():
                continue
            by_id[snip_id] = s
            coach_dir = resolve_direction(labels.get(snip_id), None)
            (keys if coach_dir == "challenge" else decoys).append(snip_id)
    return keys, decoys, by_id


def build_game_rounds(db, arc_id: Any, user_id: Any,
                      first_snippet: Any = None) -> list:
    """The rounds payload — NO truth included. Keys + an equal number of
    decoys (as available), deterministic order, ≤ _MAX_ROUNDS, the deep-linked
    snippet pinned first when it belongs to the arc."""
    keys, decoys, by_id = _arc_moments(db, arc_id)
    if not keys:
        return []  # nothing coach-confirmed yet → no game
    keys = sorted(keys, key=lambda s: _order_key(arc_id, s))
    decoys = sorted(decoys, key=lambda s: _order_key(arc_id, s))
    n_keys = min(len(keys), _MAX_ROUNDS // 2)
    n_decoys = min(len(decoys), n_keys)
    chosen = keys[:n_keys] + decoys[:n_decoys]
    chosen = sorted(chosen, key=lambda s: _order_key(arc_id, s))
    if first_snippet and str(first_snippet) in chosen:
        chosen.remove(str(first_snippet))
        chosen.insert(0, str(first_snippet))
    rounds: list = []
    for i, snip_id in enumerate(chosen):
        s = by_id[snip_id]
        rounds.append({
            "round": i,
            "snippet_id": snip_id,
            "transcript": s.get("transcript") or "",
            "audio_ref": s.get("audio_segment_path") or s.get("audio_ref"),
            "start_offset_ms": s.get("start_offset_ms"),
            "duration_ms": s.get("duration_ms"),
        })
    return rounds


def _keywords_for(snippet: Any) -> list:
    """Up to 3 load-bearing words/phrases: the Say-It-Stronger upgrade
    ORIGINALS when the card exists (what the speaker actually said), else the
    longest distinct content words. Pure."""
    sis = snippet.get("say_it_stronger") if isinstance(snippet, dict) else None
    out: list = []
    if isinstance(sis, dict):
        for u in (sis.get("upgrades") or []):
            orig = (u.get("original") or "").strip() if isinstance(u, dict) else ""
            if orig and orig.lower() not in (o.lower() for o in out):
                out.append(orig)
            if len(out) >= 3:
                return out
    if not out:
        words = sorted(
            {w.strip(".,!?\"'").lower()
             for w in (snippet.get("transcript") or "").split()
             if len(w.strip(".,!?\"'")) > 4},
            key=len, reverse=True,
        )
        out = words[:3]
    return out


def build_why(snippet: Any, patterns: list, truth_is_key: bool) -> dict:
    """The 'Here is why' payload — ≤3 short prose paragraphs (AC-9:
    qualitative only), keywords for the FE's orange tint, and the coach's
    video when attached. Pure given inputs."""
    from services.best_presentation import _moment_note
    paragraphs: list = []
    keywords = _keywords_for(snippet)
    if keywords:
        joined = ", ".join(f"“{k}”" for k in keywords)
        paragraphs.append(
            (f"The load-bearing words in this moment: {joined}."
             if truth_is_key else
             f"The words doing the work here: {joined} — solid, but the "
             "delivery didn't lift them."))
    kind = "positive" if truth_is_key else "negative"
    for p in (patterns or []):
        if isinstance(p, dict) and p.get("kind") == kind and p.get("statement"):
            paragraphs.append(p["statement"])
            break
    note = _moment_note(snippet) if isinstance(snippet, dict) else ""
    if note:
        paragraphs.append(note)
    return {
        "paragraphs": paragraphs[:3],
        "keywords": keywords,
        "video_ref": (snippet or {}).get("breakthrough_video_ref"),
    }


def answer_round(db, arc_id: Any, user_id: Any, snippet_id: Any,
                 answer_is_key: Any) -> Optional[dict]:
    """Verify the snippet belongs to this arc, resolve the coach truth,
    persist the answer as a second-order peer label, and build the verdict +
    why. None when the snippet isn't part of the arc (caller 404s)."""
    keys, decoys, by_id = _arc_moments(db, arc_id)
    snip_id = str(snippet_id)
    if snip_id not in by_id:
        return None
    truth_is_key = snip_id in keys
    answer = bool(answer_is_key)

    # Second-order signal (L2/L3): the game answer, below coach truth.
    try:
        db.insert_snippet_peer_label(
            snippet_id=snip_id,
            rater_id=str(user_id) if user_id else None,
            label="key_moment" if answer else "neutral",
            source="game",
            shown_origin="real",
        )
    except Exception as e:
        logger.warning("game: peer-label write failed snip=%s: %s", snip_id, e)

    # Coach video: attached per snippet on the drafts lane.
    snippet = dict(by_id[snip_id])
    try:
        sess_id = snippet.get("session_id")
        _get_drafts = getattr(db, "get_coach_snippet_drafts", None)
        if sess_id and callable(_get_drafts):
            for d in (_get_drafts(sess_id) or []):
                if str(d.get("snippet_id")) == snip_id:
                    snippet["breakthrough_video_ref"] = d.get(
                        "breakthrough_video_ref")
                    break
    except Exception:
        pass

    from services.user_patterns import build_user_patterns
    patterns = build_user_patterns(user_id, database=db)
    return {
        "correct": answer == truth_is_key,
        "truth_is_key": truth_is_key,
        "why": build_why(snippet, patterns, truth_is_key),
    }
