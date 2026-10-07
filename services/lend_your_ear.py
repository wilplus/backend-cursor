"""Lend your ear: the one engine that serves the walk's other voices
(founder 2026-10-07, Q-B11 A, decisions log N62; the lock N52.4).

Q-B11 A: "At most 3 other voices per walk, community first, then training
clips, on the same judgement screen without the slide bar. Lend your ear's
engine serves them under the per-Take consent only. The Album share switch
and Bold voices are retired."

THE ONE CONSENT PATH is the per-Take community share (N52.4, migration
0432, ``services/communities.py``): a speaker shares one Take with the
communities they choose, revocably, and ``community_clips_live`` is the
only thing that admits a speaker's moment to a peer queue. The Voice Album
share switch (migration 0410, ``voice_album_shares`` and the view
``shared_clips_live``), the per-Take blind set it fed (``lend_your_ear_sets``,
``lend_your_ear_answers``) and Bold voices (``bold_voices_plays``,
``after_practice_steps``) are RETIRED: their routes answer 404 whatever any
switch says, nothing reads the share view any more, and nothing is written
to those tables. No row is dropped; a retention operation on them is a
separately authorised, previewed step, not this module's.

THE OTHER VOICES are at most ``OTHER_VOICES_MAX`` (3) per walk: the
community's clips first (the listener's private communities, then the
general one, never their own, never one they answered, never one the coach
+ peer quorum settled), then training clips from the licensed corpus for
the places left, a blind stratified pick by the machine's read
(``build_set``: confident, weak, unknown, random order). Audio only (AC-9):
the clip id, the sound, where it starts, how long it is and which kind it
is. No name, no words, no read, no number about anyone's voice.

THE ANSWER is the communities' (``communities.answer``): one per person per
clip, the same five answers. A community clip's answer is a PEER rating,
kept in ``community_answers`` and written as a peer label (lane
``game_peer``) only under the quorum's access rule (``_peer_label``); it is
never a coach label, never owner routing and never a training label by
itself (L3). A training clip is not a snippet and takes no label. Owner
answers never enter.

``PEER_LANE_ENABLED`` no longer opens any speaker route. It still gates the
coach's licensed-corpus tool (``services/corpus_clips.py``) and the
ledger's historical counts of the retired lane.
"""
from __future__ import annotations

import logging
import random
from typing import Any, Iterable, Optional

_log = logging.getLogger(__name__)

#: Q-B11 A: at most three other voices per walk, community first.
OTHER_VOICES_MAX = 3
SET_SIZE = OTHER_VOICES_MAX
STRATA = ("confident", "weak", "unknown")
#: What a clip in the walk's queue may be. The Album share ("shared") and
#: the delayed measure's pair clips ("delayed") rode the retired switch
#: and are no sources any more.
SOURCES = ("community", "training")


def peer_lane_enabled() -> bool:
    """The coach's licensed-corpus tool and the ledger's historical counts.
    No speaker route reads it since Q-B11 A."""
    from config import Config
    return bool(getattr(Config, "PEER_LANE_ENABLED", False))


# ── the policy version a share rides ──────────────────────────────────────

def accepted_policy_at_least(database: Any, owner_user_id: Any,
                             version: Optional[str]) -> bool:
    """Whether the speaker's current Phase-1 authorization is on `version`
    or a later one. False when no version is named, and false when the read
    fails: unknown reads as not accepted. The communities' share
    (services/communities.py) names its own version."""
    from services.processing_authorization import ProcessingAuthorizationService
    if not version:
        return False
    try:
        service = ProcessingAuthorizationService(database)
        status = service.status(service.user_acquisition_principal(str(owner_user_id)))
    except Exception as e:  # noqa: BLE001 — unknown reads as not accepted: the safe side
        _log.warning("share policy read failed user=%s: %s", owner_user_id, e, exc_info=True)
        return False
    accepted = str(status.get("policy_version") or "")
    return bool(status.get("authorized")) and accepted >= str(version)


# ── the blind pick ────────────────────────────────────────────────────────

def stratum(snippet: Any) -> str:
    """The machine's read of a clip, as a stratum; never surfaced."""
    from services.label_quorum import machine_proposal
    proposal = machine_proposal(snippet) if isinstance(snippet, dict) else None
    return {"yes": "confident", "no": "weak"}.get(proposal or "", "unknown")


def build_set(candidates: Iterable[dict], *, recent_pairs: Iterable[str],
              size: int = SET_SIZE, rng: Any = None) -> list[dict]:
    """Up to `size` clips: one per stratum where one exists (confident, weak,
    unknown), then any; never two clips of one pair, never a clip whose
    pair the listener heard within the gap; random order. Pure."""
    rng = rng or random.Random()
    blocked = {str(p) for p in recent_pairs}
    pool = [c for c in candidates if isinstance(c, dict) and c.get("clip_id")
            and str(c.get("pair_id") or "") not in blocked]
    rng.shuffle(pool)
    chosen: list[dict] = []
    pairs_in: set[str] = set()

    def _take(clip: dict) -> None:
        chosen.append(clip)
        if clip.get("pair_id"):
            pairs_in.add(str(clip["pair_id"]))

    for name in STRATA:
        if len(chosen) >= size:
            break
        pick = next((c for c in pool if c not in chosen and c.get("stratum") == name
                     and str(c.get("pair_id") or "") not in pairs_in), None)
        if pick:
            _take(pick)
    for clip in pool:
        if len(chosen) >= size:
            break
        if clip not in chosen and str(clip.get("pair_id") or "") not in pairs_in:
            _take(clip)
    rng.shuffle(chosen)
    return chosen


def _audio(database: Any, clip: dict) -> Optional[str]:
    """The playable sound of a community clip (a snippet) or a training
    clip (a licensed corpus row)."""
    from services.audio_ref_resolver import resolve_playable_ref
    if clip.get("source") == "training":
        return (clip.get("corpus") or {}).get("audio_url")
    from services.snippet_audio_url import resolve_snippet_audio_url
    return resolve_snippet_audio_url(clip.get("snippet") or {}, database=database) \
        or resolve_playable_ref((clip.get("snippet") or {}).get("audio_segment_path"))


# ── the other voices ──────────────────────────────────────────────────────

def training_clips(database: Any, *, answered: set[str], size: int,
                   rng: Any = None) -> list[dict]:
    """Up to `size` licensed corpus clips the listener has not answered,
    one per stratum where one exists (the machine's pick; the stratum
    itself never leaves here). Audio only."""
    if size <= 0:
        return []
    pool = [{"clip_id": str(row["id"]), "stratum": row.get("machine_stratum") or "unknown",
             "pair_id": None, "corpus": row}
            for row in database.list_corpus_clips_active() or []
            if isinstance(row, dict) and row.get("id") and row.get("audio_url")
            and str(row["id"]) not in answered]
    chosen = build_set(pool, recent_pairs=[], size=size, rng=rng or random.Random())
    return [{"clip_id": c["clip_id"], "source": "training",
             "audio_ref": c["corpus"].get("audio_url"), "start_offset_ms": 0,
             "duration_ms": c["corpus"].get("duration_ms")} for c in chosen]


def other_voices(database: Any, *, listener_id: str, rng: Any = None,
                 limit: int = OTHER_VOICES_MAX) -> list[dict]:
    """The walk's other voices (Q-B11 A): at most `limit`, the community's
    clips first (a Take shared under the per-Take consent, N52.4), then
    training clips for the places left. Audio only (AC-9). The one door
    for another speaker's moment is ``communities.community_clips``; no
    Album share, no measure pair, nothing else is read."""
    from services.communities import answered_clip_ids, community_clips
    me = str(listener_id)
    limit = max(0, int(limit))
    answered = answered_clip_ids(database, me)
    clips = community_clips(database, listener_id=me, answered=answered, limit=limit)
    clips.extend(training_clips(database, answered=answered,
                                size=limit - len(clips), rng=rng))
    return clips[:limit]


# ── the peer label ────────────────────────────────────────────────────────

def _peer_label(database: Any, *, listener_id: str, snippet_id: str,
                row: dict) -> tuple[Optional[str], str]:
    """The peer label for a shared recording, under the quorum's access
    rule; (label row id or None, the outcome named). Lane game_peer, never
    the owner's, never the coach's (L3)."""
    from services.label_quorum import machine_proposal, rater_submission_access
    from services.state_ratings import resolve_lane
    snippet = database.get_snippet_by_id(snippet_id) or {}
    labels = (database.get_confidence_labels_by_snippet_ids([snippet_id]) or {}).get(snippet_id, [])
    access = rater_submission_access(labels, listener_id)
    if not access.get("allowed"):
        return None, str(access.get("outcome") or "closed")
    try:
        saved = database.upsert_state_rating(
            snippet_id=snippet_id, row=row, rater_id=listener_id,
            session_id=snippet.get("session_id"),
            lane=resolve_lane(is_coach=False, is_owner=False),
            self_report=False, machine_value=machine_proposal(snippet))
    except Exception as e:  # noqa: BLE001 — the answer is still kept
        _log.warning("peer label write failed snip=%s: %s", snippet_id, e, exc_info=True)
        return None, "label_failed"
    return ("written" if saved else None), ("new" if saved else "label_failed")
