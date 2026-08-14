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

Order is DETERMINISTIC (no random, replayable): rounds rank by VOICE
SOURCE first (founder queue order 2026-08-14 — the player's own voice,
then consented app users, then the coach-labelled YouTube corpus), sha1
of arc+snippet within a class, with an optional pinned first round for
/game?snippet=<id> deep links.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

_MAX_ROUNDS = 10


def _order_key(arc_id: Any, snippet_id: Any) -> str:
    return hashlib.sha1(f"{arc_id}:{snippet_id}".encode("utf-8")).hexdigest()


def _source_class(sess: Any, user_id: Any) -> int:
    """Whose voice a round carries decides its place in the queue
    (founder 2026-08-14, unparked from product context): the PLAYER's
    own voice first (0), then other consented app users (1), then the
    machine-extracted, coach-labelled YouTube corpus (2 — sessions with
    source='training_import', the same import lane resolve_lane stamps
    bootstrap). "Own" means the person playing, not the arc owner: a
    peer labelling someone else's arc hears their own takes first if any
    are present. Consent itself is enforced upstream (what may reach the
    arc at all); this ranks only what is already legitimately here."""
    s = sess if isinstance(sess, dict) else {}
    if str(s.get("source") or "") == "training_import":
        return 2
    if user_id is not None and str(s.get("user_id") or "") == str(user_id):
        return 0
    return 1


def _playable_ref(ref):
    """services/audio_ref_resolver — the one bucket-authoritative copy."""
    from services.audio_ref_resolver import resolve_playable_ref
    return resolve_playable_ref(ref)


def _twice_labelled(db, snippet_ids: Any) -> set:
    """Founder 2026-08-10: "min twice labelled voice snippet goes to the
    game." A snippet qualifies once at least TWO DISTINCT raters have
    committed an ANSWER on it — yes/no/neutral (or a legacy boolean).
    Never an abstention (unrateable carries no answer; two abstentions
    are not two labels) and never a bootstrap row (one expert rating
    model-proposed imports is not panel evidence — the written rationale
    PANEL_LANES already carries). Best-effort: a read miss admits
    NOTHING rather than everything."""
    try:
        by_snip = db.get_confidence_labels_by_snippet_ids(
            [str(s) for s in (snippet_ids or [])]) or {}
    except Exception as e:
        logger.warning("game gate: label read failed: %s", e)
        return set()
    out: set = set()
    for snip_id, rows in by_snip.items():
        raters = set()
        for r in (rows or []):
            if not isinstance(r, dict) or r.get("unrateable") is True:
                continue
            if (r.get("lane") or "") == "bootstrap":
                continue
            answered = r.get("value") in ("yes", "no", "neutral") \
                or isinstance(r.get("confident"), bool)
            if answered and r.get("rater_id"):
                raters.add(str(r.get("rater_id")))
        if len(raters) >= 2:
            out.add(str(snip_id))
    return out


def _arc_moments(db, arc_id: Any) -> tuple:
    """(keys, decoys, snippets_by_id, session_by_snippet) for the arc —
    coach truth only. keys = challenge-labeled; decoys = everything else
    (unlabeled + threat: both are honestly 'not a key moment').

    GATED (founder 2026-08-10): only snippets already labelled by ≥2
    distinct raters reach the game — serving AND answer-validation both,
    from this one place, so a snippet that stops being eligible also
    stops being answerable (a stale open tab must not post a junk
    label)."""
    from services.challenge_threat import resolve_direction
    keys: list = []
    decoys: list = []
    by_id: dict = {}
    sess_by_id: dict = {}
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
            sess_by_id[snip_id] = sess
            coach_dir = resolve_direction(labels.get(snip_id), None)
            (keys if coach_dir == "challenge" else decoys).append(snip_id)
    eligible = _twice_labelled(db, list(by_id.keys()))
    keys = [s for s in keys if s in eligible]
    decoys = [d for d in decoys if d in eligible]
    by_id = {k: v for k, v in by_id.items() if k in eligible}
    sess_by_id = {k: v for k, v in sess_by_id.items() if k in eligible}
    return keys, decoys, by_id, sess_by_id


def build_game_rounds(db, arc_id: Any, user_id: Any,
                      first_snippet: Any = None) -> list:
    """The rounds payload — NO truth included. Keys + an equal number of
    decoys (as available), deterministic order, ≤ _MAX_ROUNDS, the deep-linked
    snippet pinned first when it belongs to the arc."""
    keys, decoys, by_id, sess_by_id = _arc_moments(db, arc_id)
    if not keys:
        return []  # nothing coach-confirmed yet → no game
    keys = sorted(keys, key=lambda s: _order_key(arc_id, s))
    decoys = sorted(decoys, key=lambda s: _order_key(arc_id, s))
    n_keys = min(len(keys), _MAX_ROUNDS // 2)
    n_decoys = min(len(decoys), n_keys)
    chosen = keys[:n_keys] + decoys[:n_decoys]
    # Queue order (founder 2026-08-14): voice-source class first — own →
    # consented app users → YouTube corpus — sha1 within a class. The
    # class ranks the ORDER only; which keys/decoys are chosen stays
    # hash-deterministic above, and the deep-link pin below still beats
    # everything (explicit navigation).
    chosen = sorted(chosen, key=lambda s: (
        _source_class(sess_by_id.get(s), user_id),
        _order_key(arc_id, s)))
    if first_snippet and str(first_snippet) in chosen:
        chosen.remove(str(first_snippet))
        chosen.insert(0, str(first_snippet))
    rounds: list = []
    for i, snip_id in enumerate(chosen):
        s = by_id[snip_id]
        rounds.append({
            "round": i,
            # round_id IS the snippet id — the FE reads this as its round
            "round_id": snip_id,     # identity and sends it BACK on answer;
            "snippet_id": snip_id,   # kept as an explicit alias.
            "transcript": s.get("transcript") or "",
            # Ear-first rounds (founder design pass 2026-07-28): the FE no
            # longer shows the transcript, so audio_ref is LOAD-BEARING — a
            # null here is an unplayable round. storage_path joins the chain
            # because pieces-canonical rows carry the parent take there (the
            # same fallback the breakthroughs list and cross-take moments
            # already use); start/duration clamp the slice.
            # Resolved (founder 2026-08-10): ear-first rounds make this
            # LOAD-BEARING, and an s3:// fallback ref is an unplayable
            # round. Healthy public URLs pass through untouched.
            "audio_ref": _playable_ref(
                s.get("audio_segment_path") or s.get("audio_ref")
                or s.get("storage_path")),
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
        # Wrap each keyword in **…** INLINE so the FE tints it orange
        # (services/api/arcGame.ts splitTintedSegments reads **kw**/==kw==).
        joined = ", ".join(f"**{k}**" for k in keywords)
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


def _normalise_answer(answer_is_key: Any) -> Optional[str]:
    """bool (legacy wire) or 'yes'/'no'/'neutral' → the ternary value.
    'neutral' is the founder's missing third answer (2026-08-10:
    "yes / no / idk — idk is missing")."""
    if isinstance(answer_is_key, bool):
        return "yes" if answer_is_key else "no"
    if answer_is_key in ("yes", "no", "neutral"):
        return str(answer_is_key)
    return None


def answer_round(db, arc_id: Any, user_id: Any, snippet_id: Any,
                 answer_is_key: Any) -> Optional[dict]:
    """Verify the snippet belongs to this arc, resolve the coach truth,
    persist the answer, and build the verdict + why. None when the snippet
    isn't part of the arc (caller 404s) or the answer is malformed.

    THE GAME IS A LABELLING LANE (founder 2026-08-10: same instrument as
    the coach lanes). Every answer writes the ternary confidence corpus in
    its own lane — game_owner / game_peer, declared in SPEC §6.2 and
    unwritten until now — blind by construction: truth is never in the
    rounds payload. The key-moment peer guess stays a SEPARATE second-order
    signal, and an "I don't know" writes no guess at all: a fabricated
    neutral would be indistinguishable from a real one afterwards."""
    keys, decoys, by_id, sess_by_id = _arc_moments(db, arc_id)
    snip_id = str(snippet_id)
    if snip_id not in by_id:
        return None
    truth_is_key = snip_id in keys
    value = _normalise_answer(answer_is_key)
    if value is None:
        return None

    # THE LABEL — the same ternary instrument as every other lane.
    try:
        from services.state_ratings import resolve_lane, validate_rating
        # state_id names the CONSTRUCT (the question registry's key),
        # never the snippet — the snippet rides upsert_state_rating's own
        # parameter.
        row, _err = validate_rating({"state_id": "confidence",
                                     "value": value})
        if row:
            sess = sess_by_id.get(snip_id) or {}
            lane = resolve_lane(
                sess.get("source"), is_coach=False,
                is_owner=bool(user_id)
                and str(sess.get("user_id")) == str(user_id))
            db.upsert_state_rating(
                snippet_id=snip_id, row=row,
                rater_id=str(user_id) if user_id else None,
                session_id=(str(sess.get("id"))
                            if sess.get("id") else None),
                lane=lane)
    except Exception as e:
        logger.warning("game: confidence write failed snip=%s: %s",
                       snip_id, e)

    # Second-order signal (L2/L3): the game answer, below coach truth.
    # Only a real guess writes — neutral is not a guess.
    if value != "neutral":
        answer = value == "yes"
        try:
            db.insert_snippet_peer_label(
                snippet_id=snip_id,
                rater_id=str(user_id) if user_id else None,
                label="key_moment" if answer else "neutral",
                source="game",
                shown_origin="real",
            )
        except Exception as e:
            logger.warning("game: peer-label write failed snip=%s: %s",
                           snip_id, e)

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
    why_obj = build_why(snippet, patterns, truth_is_key)
    # FE-aligned verdict shape (services/api/arcGame.ts submitGameAnswer):
    # `why` is a FLAT string array (keywords already **-wrapped inline) and
    # `video_ref` is TOP-LEVEL, not nested under `why`. `correct` is None
    # on an "I don't know" — there is no verdict on an abstained guess,
    # and the FE shows the reveal without a win/lose frame.
    return {
        "correct": (None if value == "neutral"
                    else (value == "yes") == truth_is_key),
        "truth_is_key": truth_is_key,
        "why": why_obj.get("paragraphs") or [],
        "keywords": why_obj.get("keywords") or [],
        "video_ref": why_obj.get("video_ref"),
    }
