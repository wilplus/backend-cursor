"""Lend your ear, the share toggle, and the others' voices (founder
2026-10-01, F3, F4; Phase 4 of the after-practice paths), dark behind
``Config.PEER_LANE_ENABLED`` (on from 2026-10-02, N25, after the founder's
own answers to C1 to C3, Q3 to Q5 of N23, and the signed 3.3 wording, N24;
off again from 2026-10-03, N29, until the share switch and Lend your ear
have a screen);
the share switch itself waits per speaker for ``PEER_SHARE_POLICY_VERSION``.

F3: "A blind 'Lend your ear' step reopens the peer lane. Speakers judge up to
three short shared or licensed clips, audio only, never their own, at most
once per Take after a practice that lands. Their answers count toward the
coach + peer quorum. The retired Game stays retired."
F4: "Licensed corpus clips may be played to speakers, without names, in
'Lend your ear' and 'Bold voices'."

THE SHARE is a toggle on a Voice Album moment (three-yes, L3): off by
default, per recording, revocable. Both pools (Lend your ear and Bold
voices) read one live view (migration 0410, ``shared_clips_live``: shared,
not revoked, still in the Album), so one revocation removes the clip from
both at once.

THE SET is up to three clips, a blind stratified mix by the machine's read
(confident, weak, unknown), never the listener's own, never a clip they
answered, never the before and the after of one pair in one set and never
on the same day as its partner (founder correction 5). Audio only: the clip
id and the sound, no name, no words, no source, no reveal. The order is
random. Fewer than three judgeable clips shows what exists; none means the
sheet skips the bridge and the step.

THE ANSWER is one per person per clip, the same five answers, written to
``confidence_labels`` under lane ``game_peer`` for a shared recording
(``state_ratings.resolve_lane``; ``label_quorum``: coach + peer settles, a
disagreement routes a third rater) and kept beside it in
``lend_your_ear_answers``; a licensed corpus clip is not a snippet and
keeps its answers in that table alone. Owner answers never enter (L3).
"""
from __future__ import annotations

import logging
import random
from typing import Any, Iterable, Optional

_log = logging.getLogger(__name__)

SET_SIZE = 3
STRATA = ("confident", "weak", "unknown")
SOURCES = ("shared", "corpus")
#: The before and the after of one pair never on the same day for one
#: listener (correction 5); the partner waits this many days.
PAIR_GAP_DAYS = 1


def peer_lane_enabled() -> bool:
    from config import Config
    return bool(getattr(Config, "PEER_LANE_ENABLED", False))


# ── the share toggle ───────────────────────────────────────────────────────

def _accepted_share_terms(database: Any, owner_user_id: Any) -> bool:
    """Q4-A (founder 2026-10-02): the switch exists only for a speaker whose
    current Phase-1 authorization is on the policy version that describes
    it, or a later one. False while no such version is published
    (PEER_SHARE_POLICY_VERSION None), and false when the read fails."""
    from config import Config
    return accepted_policy_at_least(
        database, owner_user_id, getattr(Config, "PEER_SHARE_POLICY_VERSION", None))


def accepted_policy_at_least(database: Any, owner_user_id: Any,
                             version: Optional[str]) -> bool:
    """Whether the speaker's current Phase-1 authorization is on `version`
    or a later one. False when no version is named, and false when the read
    fails: unknown reads as not accepted. Shared with the communities' share
    (services/communities.py), which names its own version."""
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


def set_share(database: Any, *, owner_user_id: str, snippet_id: str,
              body: Any) -> tuple[int, dict]:
    """Share or withdraw one Voice Album moment. 409 when the moment is not
    in the speaker's Album: only an aligned moment (three yes) can be lent."""
    fields: dict = body if isinstance(body, dict) else {}
    shared = fields.get("shared")
    if not isinstance(shared, bool):
        return 400, {"code": "INVALID_INPUT", "error": "shared must be true or false"}
    if not peer_lane_enabled():
        return 404, {"code": "NOT_FOUND", "error": "not found"}
    snippet = database.get_snippet_by_id(str(snippet_id))
    session = (database.v2_get_session_by_id(str(snippet.get("session_id") or ""))
               if snippet else None)
    if (not snippet or not session or str(session.get("user_id")) != str(owner_user_id)
            or not session.get("arc_id")):
        return 404, {"code": "NOT_FOUND", "error": "snippet not found"}
    if not _accepted_share_terms(database, owner_user_id):
        return 409, {"code": "TERMS_REACCEPT_REQUIRED",
                     "error": "Accept the updated Terms and Privacy first."}
    arc_id = str(session["arc_id"])
    if shared and not database.voice_album_has(arc_id, str(snippet_id)):
        return 409, {"code": "NOT_IN_ALBUM",
                     "error": "Only a Voice Album moment can be shared."}
    row = database.set_voice_album_share(
        owner_user_id=str(owner_user_id), arc_id=arc_id, snippet_id=str(snippet_id),
        take_session_id=str(session.get("id")), shared=shared)
    return 200, {"snippet_id": str(snippet_id),
                 "shared": bool(row and not row.get("revoked_at"))}


# ── the pool and the set ──────────────────────────────────────────────────

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


def _shared_candidates(database: Any, *, listener_id: str, answered: set[str]) -> list[dict]:
    """Shared clips still in an Album, never the listener's own, never one
    they answered, never one already settled."""
    from services.label_quorum import SETTLED_STATUSES, resolve
    shared = [row for row in database.list_shared_clips_live() or []
              if isinstance(row, dict) and row.get("snippet_id")
              and str(row.get("owner_user_id")) != str(listener_id)
              and str(row["snippet_id"]) not in answered]
    if not shared:
        return []
    ids = [str(r["snippet_id"]) for r in shared]
    labels = database.get_confidence_labels_by_snippet_ids(ids) or {}
    snippets = {str(s.get("id")): s for s in
                (database.get_snippets_by_ids(ids) or []) if isinstance(s, dict)}
    out: list[dict] = []
    for row in shared:
        sid = str(row["snippet_id"])
        if resolve(labels.get(sid, [])).get("status") in SETTLED_STATUSES:
            continue
        out.append({"clip_id": sid, "source": "shared",
                    "stratum": stratum(snippets.get(sid)),
                    "pair_id": row.get("pair_id"), "snippet": snippets.get(sid)})
    return out


def _candidates(database: Any, *, listener_id: str) -> list[dict]:
    """Shared clips still in an Album and licensed corpus clips, never the
    listener's own, never one they answered, never one already settled."""
    answered = {str(c) for c in database.list_lend_your_ear_answered_clip_ids(str(listener_id)) or []}
    out: list[dict] = _shared_candidates(database, listener_id=listener_id, answered=answered)
    for row in database.list_corpus_clips_active() or []:
        if isinstance(row, dict) and row.get("id") and str(row["id"]) not in answered:
            out.append({"clip_id": str(row["id"]), "source": "corpus",
                        "stratum": row.get("machine_stratum") or "unknown",
                        "pair_id": None, "corpus": row})
    # Phase 5: the measure's pairs enter as separate, unlabelled clips. A
    # pair rides its original's share (Q3-A), so the shared entry and the
    # pair's before are the same voice: they carry one pair id, and the set
    # and the day keep them apart like any pair.
    from services.delayed_measure import clips_for_listener
    delayed = [c for c in clips_for_listener(database, listener_id=str(listener_id))
               if str(c.get("clip_id")) not in answered]
    before_of = {str((c.get("pair") or {}).get("before_snippet_id") or ""): str(c.get("pair_id"))
                 for c in delayed if c.get("pair_id")}
    for c in out:
        if c.get("source") == "shared" and not c.get("pair_id") and str(c["clip_id"]) in before_of:
            c["pair_id"] = before_of[str(c["clip_id"])]
    out.extend(delayed)
    return out


def _audio(database: Any, clip: dict) -> Optional[str]:
    from services.audio_ref_resolver import resolve_playable_ref
    if clip.get("source") == "corpus":
        return (clip.get("corpus") or {}).get("audio_url")
    if clip.get("source") == "delayed":
        from services.delayed_measure import audio_for
        return audio_for(database, clip)[0]
    from services.snippet_audio_url import resolve_snippet_audio_url
    return resolve_snippet_audio_url(clip.get("snippet") or {}, database=database) \
        or resolve_playable_ref((clip.get("snippet") or {}).get("audio_segment_path"))


def _duration(clip: dict) -> Any:
    if clip.get("source") == "delayed":
        return clip.get("duration_ms")
    source = clip.get("corpus") if clip.get("source") == "corpus" else clip.get("snippet")
    return (source or {}).get("duration_ms")


def open_set(database: Any, *, listener_id: str, take_session_id: str) -> tuple[int, dict]:
    """The Take's set, built once after a practice that lands and returned
    as built on every later read. Audio only."""
    if not peer_lane_enabled():
        return 404, {"code": "NOT_FOUND", "error": "not found"}
    session = database.v2_get_session_by_id(str(take_session_id))
    if not session or str(session.get("user_id")) != str(listener_id):
        return 404, {"code": "NOT_FOUND", "error": "Take not found"}
    existing = database.get_lend_your_ear_set_for_take(str(take_session_id))
    if isinstance(existing, dict):
        return 200, _set_payload(existing)
    if not database.list_landed_practices_for_take(str(take_session_id), str(listener_id)):
        return 409, {"code": "NOT_YET", "error": "Lend your ear opens after a practice that lands."}
    recent = database.list_recent_pair_ids_for_listener(str(listener_id), days=PAIR_GAP_DAYS) or []
    chosen = build_set(_candidates(database, listener_id=str(listener_id)), recent_pairs=recent)
    for c in chosen:
        if c.get("source") == "delayed":
            from services.delayed_measure import audio_for
            c["duration_ms"] = audio_for(database, c)[1]
    clips = [{"clip_id": c["clip_id"], "source": c["source"], "pair_id": c.get("pair_id"),
              "clip": c.get("clip"),
              "audio_ref": _audio(database, c), "duration_ms": _duration(c),
              "stratum": c.get("stratum")} for c in chosen]
    row = database.insert_lend_your_ear_set({
        "listener_user_id": str(listener_id), "take_session_id": str(take_session_id),
        "clips": clips, "size": len(clips)})
    if not isinstance(row, dict):
        return 500, {"code": "V2_ERROR", "error": "Could not open the set."}
    try:
        database.mark_after_practice_step(owner_user_id=str(listener_id),
                                          take_session_id=str(take_session_id),
                                          step="lend_your_ear")
    except Exception as e:  # noqa: BLE001 — the step mark is bookkeeping
        _log.warning("lend_your_ear step mark failed take=%s: %s", take_session_id, e, exc_info=True)
    return 200, _set_payload(row)


def _set_payload(row: dict) -> dict:
    """What the listener gets: the id and the sound. No name, no words, no
    source, no read (F3; AC-9)."""
    raw = row.get("clips")
    clips: list = raw if isinstance(raw, list) else []
    answered = {str(a) for a in (row.get("answered_clip_ids") or [])}
    return {
        "set_id": str(row.get("id")),
        "clips": [{"clip_id": str(c.get("clip_id")), "audio_ref": c.get("audio_ref"),
                   "duration_ms": c.get("duration_ms"),
                   "answered": str(c.get("clip_id")) in answered}
                  for c in clips if isinstance(c, dict)],
    }


# ── the answer ─────────────────────────────────────────────────────────────

def answer(database: Any, *, listener_id: str, set_id: str, body: Any) -> tuple[int, dict]:
    """One answer per person per clip; a shared recording's answer also
    becomes a peer label (lane game_peer) where the quorum still takes
    raters. Never the listener's own clip: the set never held one."""
    from services.state_ratings import validate_rating
    if not peer_lane_enabled():
        return 404, {"code": "NOT_FOUND", "error": "not found"}
    fields: dict = body if isinstance(body, dict) else {}
    row, err = validate_rating({"state_id": "confidence", "value": fields.get("value")})
    if err or row is None:
        return 400, {"code": "INVALID_INPUT", "error": err or "value is required"}
    the_set = database.get_lend_your_ear_set(str(set_id), str(listener_id))
    if not isinstance(the_set, dict):
        return 404, {"code": "NOT_FOUND", "error": "set not found"}
    raw_clips = the_set.get("clips")
    clips: list = list(raw_clips) if isinstance(raw_clips, list) else []
    clip = next((c for c in clips
                 if isinstance(c, dict) and str(c.get("clip_id")) == str(fields.get("clip_id"))), None)
    if clip is None:
        return 400, {"code": "INVALID_INPUT", "error": "clip_id is not in this set"}
    if str(clip["clip_id"]) in {str(a) for a in (the_set.get("answered_clip_ids") or [])}:
        return 409, {"code": "ALREADY_ANSWERED", "error": "You answered this one."}
    if clip.get("source") == "shared":
        label_id, outcome = _peer_label(database, listener_id=str(listener_id),
                                        snippet_id=str(clip["clip_id"]), row=row)
    elif clip.get("source") == "delayed":
        from services.delayed_measure import vote
        status, _ = vote(database, pair_id=str(clip.get("pair_id")), clip=str(clip.get("clip")),
                         rater_id=str(listener_id), rater_kind="peer", value=row["value"])
        label_id, outcome = None, ("vote" if status == 200 else f"vote_{status}")
    else:
        label_id, outcome = None, "corpus"
    saved = database.insert_lend_your_ear_answer({
        "set_id": str(set_id), "listener_user_id": str(listener_id),
        "clip_id": str(clip["clip_id"]), "clip_source": str(clip.get("source") or "shared"),
        "pair_id": clip.get("pair_id"), "value": row["value"],
        "label_id": label_id, "label_outcome": outcome,
    })
    if not isinstance(saved, dict):
        return 500, {"code": "V2_ERROR", "error": "Could not save the answer."}
    answered = len({str(a) for a in (the_set.get("answered_clip_ids") or [])} | {str(clip["clip_id"])})
    return 200, {"recorded": True, "answered": answered, "of": len(clips)}


def _peer_label(database: Any, *, listener_id: str, snippet_id: str,
                row: dict) -> tuple[Optional[str], str]:
    """The peer label for a shared recording, under the quorum's access
    rule; (label row id or None, the outcome named)."""
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


# ── the others' voices (Bold voices, Phase 4 part) ────────────────────────

def others_for_bold_voices(database: Any, *, listener_id: str) -> list[dict]:
    """Shared clips the quorum settled Yes, never the listener's own, and
    licensed corpus clips a coach labelled Yes; no names (F4). [] off."""
    from services.label_quorum import SETTLED_STATUSES, resolve
    if not peer_lane_enabled():
        return []
    out: list[dict] = []
    shared = [row for row in database.list_shared_clips_live() or []
              if isinstance(row, dict) and row.get("snippet_id")
              and str(row.get("owner_user_id")) != str(listener_id)]
    if shared:
        ids = [str(r["snippet_id"]) for r in shared]
        labels = database.get_confidence_labels_by_snippet_ids(ids) or {}
        snippets = {str(s.get("id")): s for s in
                    (database.get_snippets_by_ids(ids) or []) if isinstance(s, dict)}
        for sid in ids:
            verdict = resolve(labels.get(sid, []))
            if verdict.get("status") in SETTLED_STATUSES and verdict.get("value") == "yes":
                clip = {"source": "shared", "snippet": snippets.get(sid)}
                out.append({"clip_id": sid, "audio_ref": _audio(database, clip),
                            "duration_ms": _duration(clip)})
    for row in database.list_corpus_clips_active() or []:
        if isinstance(row, dict) and row.get("coach_value") == "yes" and row.get("audio_url"):
            out.append({"clip_id": str(row.get("id")), "audio_ref": row.get("audio_url"),
                        "duration_ms": row.get("duration_ms")})
    return out
