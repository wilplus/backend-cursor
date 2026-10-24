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

THE OTHER VOICES (founder 2026-10-23, N119; until then one per practice
try, N97) are three per walk: one clip the machine reads high, one in the
middle and one low (``confidence_labels.band_of``, the bands the coaches'
mixed corpus rounds use, N101), each of another speaker, never the
listener's own, never one they answered, in a blind order fixed for the
Take (``other_voices``, ``pick_levels``). In each level the community's
clips come first (the listener's private communities, then the general
one, never one the coach + peer quorum settled), then the training corpus:
the imported clips the coaches judge, played under the corpus basis (CO2,
N58; this amends CM1 A), then the licensed corpus. With fewer speakers or
levels it serves fewer, never one speaker twice, and logs why. Audio only
(AC-9): the clip id, the sound, where it starts, how long it is and which
kind it is; an imported clip plays by a short-lived signed link. No name,
no words, no read, no number about anyone's voice.

THE ANSWER is the communities' (``communities.answer``): one per person per
clip, the same five answers. A community clip's answer is a PEER rating,
kept in ``community_answers`` and written as a peer label (lane
``game_peer``) only under the quorum's access rule (``_peer_label``); it is
never a coach label, never owner routing and never a training label by
itself (L3). A training clip takes no label: a licensed clip's answer stays
in ``community_answers``, an imported clip's in ``import_clip_answers``.
Owner answers never enter.

``PEER_LANE_ENABLED``, which last gated only the coach's licensed-corpus
tool and the ledger's counts of the retired lane, stayed off and was
deleted 2026-10-11 with that tool.
"""
from __future__ import annotations

import hashlib
import itertools
import logging
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)

#: N119: the three levels of the machine's read a walk asks one clip of
#: each, as ``confidence_labels.band_of`` names them. Never surfaced.
LEVELS = ("delivery_signal_high", "delivery_signal_neutral", "delivery_signal_low")
_LEVEL_NAMES = {"delivery_signal_high": "high", "delivery_signal_neutral": "middle",
                "delivery_signal_low": "low"}
#: At most three other voices per walk, one per level.
OTHER_VOICES_MAX = len(LEVELS)
#: A licensed corpus clip's filed stratum (0410), as a level; "unknown" has none.
_STRATUM_LEVEL = {"confident": "delivery_signal_high", "weak": "delivery_signal_low"}
#: Imports read together while the walk's clips are gathered.
_IMPORT_BATCH = 5
#: What a clip in the walk's queue may be. The Album share ("shared") and
#: the delayed measure's pair clips ("delayed") rode the retired switch
#: and are no sources any more.
SOURCES = ("community", "training")


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

def _key(seed: str, purpose: str, value: Any) -> str:
    return hashlib.sha1(f"{seed}:{purpose}:{value}".encode("utf-8")).hexdigest()


def pick_levels(by_level: dict[str, list[dict]], *, seed: str,
                serves: Callable[[dict], bool]) -> tuple[list[dict], dict[str, str]]:
    """One clip per level (N119), each of another speaker. ``by_level``
    lists each level's candidates in the order they are preferred, each
    ``{clip_id, source, speaker}``; ``serves`` says whether one plays (the
    caller memoises it). The levels are tried in every order and the
    fullest set wins, then the one with more community clips, then the
    first order, so a speaker whose clips crowd one level never empties
    another. Returns the clips in a blind order (a seeded hash of their ids
    alone: the place never tells the level) and, for each level left out,
    why. Pure but for ``serves``."""
    best: tuple[tuple[int, int], dict[str, dict]] = ((-1, -1), {})
    for order in itertools.permutations(LEVELS):
        chosen: dict[str, dict] = {}
        for level in order:
            used = {c["speaker"] for c in chosen.values()}
            pick = next((c for c in by_level.get(level) or []
                         if c["speaker"] not in used and serves(c)), None)
            if pick is not None:
                chosen[level] = pick
        rank = (len(chosen), sum(1 for c in chosen.values() if c["source"] == "community"))
        if rank > best[0]:
            best = (rank, chosen)
    chosen = best[1]
    used = {c["speaker"] for c in chosen.values()}
    why: dict[str, str] = {}
    for level in LEVELS:
        if level in chosen:
            continue
        candidates = by_level.get(level) or []
        why[level] = ("no clip" if not candidates
                      else "only a speaker already in the set"
                      if any(c["speaker"] in used for c in candidates)
                      else "no clip that plays")
    return sorted(chosen.values(), key=lambda c: _key(seed, "order", c["clip_id"])), why


# ── the other voices ──────────────────────────────────────────────────────

def _open_imports(database: Any, seed: str) -> list[dict]:
    """The training imports the coaches judge (N101) whose clips may be
    played: set up and not archived, in a seeded order."""
    from services.corpus_coach_queue import corpus_queue_open
    try:
        rows = database.takes.list_training_import_cohorts() or []
    except Exception as e:  # noqa: BLE001 — the community clips still come
        _log.warning("other voices: imports read failed: %s", e, exc_info=True)
        return []
    rows = [im for im in rows if isinstance(im, dict) and corpus_queue_open(im)
            and not (im.get("intake_context") or {}).get("archived_at")]
    return sorted(rows, key=lambda im: _key(seed, "import", im.get("id")))


def imported_candidates(database: Any, imports: list[dict], *, answered: set[str],
                        seed: str) -> list[dict]:
    """The clips of these imports' frozen cohorts the listener has not
    answered, each with its level and speaker, in a seeded order: one
    batched read. The speaker is the import's (``corpus_split``), never the
    coach who imported it; nothing here leaves the server but the clip."""
    from services.confidence_labels import band_of, stored_selection_records
    from services.corpus_split import import_speaker_key
    cohort: dict[str, dict] = {}
    for im in imports:
        for record in stored_selection_records(im.get("intake_context") or {}):
            cohort.setdefault(record["snippet_id"], im)
    ids = sorted(sid for sid in cohort if sid not in answered)
    scores = (database.get_snippet_scores_by_ids(ids) or {}) if ids else {}
    out: list[dict] = []
    for sid in sorted(ids, key=lambda s: _key(seed, "clip", s)):
        im, found = cohort[sid], scores.get(sid)
        # A cohort clip whose piece is gone, or that moved Takes, is not served.
        if not found or str(found.get("session_id")) != str(im.get("id")):
            continue
        level = band_of(found.get("score"))
        if level not in LEVELS:
            continue
        out.append({"clip_id": sid, "source": "training", "level": level,
                    "speaker": f"import:{import_speaker_key(im) or im.get('id')}",
                    "import_session_id": str(im.get("id"))})
    return out


def licensed_candidates(database: Any, *, answered: set[str], seed: str) -> list[dict]:
    """The licensed corpus clips (0410) the listener has not answered, by
    the stratum a coach filed them under, in a seeded order. Each is its
    own speaker: the table names none."""
    out: list[dict] = []
    rows = [row for row in database.list_corpus_clips_active() or []
            if isinstance(row, dict) and row.get("id") and row.get("audio_url")
            and str(row["id"]) not in answered]
    for row in sorted(rows, key=lambda r: _key(seed, "clip", r["id"])):
        level = _STRATUM_LEVEL.get(str(row.get("machine_stratum") or ""))
        if level:
            out.append({"clip_id": str(row["id"]), "source": "training", "level": level,
                        "speaker": f"licensed:{row['id']}", "corpus": row})
    return out


def _audio(database: Any, snippet: dict) -> Optional[str]:
    """The playable sound of a community clip (a snippet)."""
    from services.audio_ref_resolver import resolve_playable_ref
    from services.snippet_audio_url import resolve_snippet_audio_url
    return resolve_snippet_audio_url(snippet or {}, database=database) \
        or resolve_playable_ref((snippet or {}).get("audio_segment_path"))


def _serve(database: Any, candidate: dict, *, listener_id: str) -> Optional[dict]:
    """The clip as the walk receives it, audio only (AC-9), or None when it
    no longer plays. An imported clip plays by a short-lived signed link
    (``corpus_coach_queue.playback_body``)."""
    from services.corpus_coach_queue import playback_body
    clip_id = candidate["clip_id"]
    if candidate.get("corpus") is not None:
        row = candidate["corpus"]
        return {"clip_id": clip_id, "source": "training", "audio_ref": row.get("audio_url"),
                "start_offset_ms": 0, "duration_ms": row.get("duration_ms"), "community": None}
    snippet = database.get_snippet_by_id(clip_id)
    if not isinstance(snippet, dict):
        return None
    if candidate.get("import_session_id"):
        if str(snippet.get("session_id")) != candidate["import_session_id"]:
            return None
        body = playback_body(snippet)
        if body is None:
            return None
        return {"clip_id": clip_id, "source": "training", "audio_ref": body["url"],
                "start_offset_ms": body.get("start_offset_ms"),
                "duration_ms": body.get("duration_ms"), "community": None}
    if snippet.get("is_skipped") or (snippet.get("user_id")
                                     and str(snippet.get("user_id")) == listener_id):
        return None
    from services.communities import _clip_audio
    audio = _clip_audio(database, snippet)
    if not audio:
        return None
    return {"clip_id": clip_id, "source": "community", "audio_ref": audio,
            "start_offset_ms": snippet.get("start_offset_ms"),
            "duration_ms": snippet.get("duration_ms"),
            "community": candidate.get("community")}


def other_voices(database: Any, *, listener_id: str,
                 take: Optional[str] = None) -> list[dict]:
    """The walk's other voices (N119): one clip the machine reads high, one
    in the middle and one low, each of another speaker, never the
    listener's own or one they answered, in a blind order fixed for the
    Take (``take`` seeds every draw). In each level the community's clips
    come first (a Take shared under the per-Take consent, N52.4, the one
    door ``communities.community_candidates``), then the imported training
    corpus the coaches judge, then the licensed corpus. Fewer only when
    fewer speakers or levels are left, and that is logged. Audio only
    (AC-9)."""
    from services.communities import answered_clip_ids, community_candidates, hearing_for
    from services.parallel import run_in_parallel
    me = str(listener_id)
    seed = f"{me}:{take or ''}"
    # What the listener answered and where they may listen do not depend on
    # each other: one round trip, not three in a row (founder 2026-10-20).
    answered, hearing = run_in_parallel(
        lambda: answered_clip_ids(database, me),
        lambda: hearing_for(database, me))
    by_level: dict[str, list[dict]] = {level: [] for level in LEVELS}

    def add(candidates: list[dict]) -> None:
        for c in candidates:
            if c["level"] in by_level:
                by_level[c["level"]].append(c)

    add(community_candidates(database, listener_id=me, answered=answered,
                             hearing=hearing, seed=seed))
    served: dict[str, Optional[dict]] = {}

    def serves(c: dict) -> bool:
        if c["clip_id"] not in served:
            served[c["clip_id"]] = _serve(database, c, listener_id=me)
        return served[c["clip_id"]] is not None

    imports = _open_imports(database, seed)
    batches = [imports[i:i + _IMPORT_BATCH] for i in range(0, len(imports), _IMPORT_BATCH)]
    licensed = False
    while True:
        picked, why = pick_levels(by_level, seed=seed, serves=serves)
        if len(picked) >= len(LEVELS):
            break
        if batches:
            add(imported_candidates(database, batches.pop(0), answered=answered, seed=seed))
        elif not licensed:
            licensed = True
            add(licensed_candidates(database, answered=answered, seed=seed))
        else:
            break
    reasons = "; ".join(f"{_LEVEL_NAMES[level]}: {reason}" for level, reason in why.items())
    if not picked:
        _log.warning("other voices: no other speakers for listener=%s take=%s (%s)",
                     me, take, reasons)
    elif len(picked) < len(LEVELS):
        _log.info("other voices: fewer than three (%d) for listener=%s take=%s (%s)",
                  len(picked), me, take, reasons)
    return [clip for c in picked if (clip := served[c["clip_id"]]) is not None]


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
    if saved:
        # V4 brief 1.7 (0442): the clip's soft-label counts follow the peer
        # label. A side write that never raises (services.clip_answer_counts).
        from services.clip_answer_counts import refresh
        refresh(database, snippet_id)
    return ("written" if saved else None), ("new" if saved else "label_failed")
