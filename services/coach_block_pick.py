"""The blind "pick the most confident" (founder 2026-10-01, C5-b; Phase 8 of
the coach panel), dark behind ``Config.COACH_BLOCK_PICK_ENABLED``.

C5-b: "On a sample of blocks, the coach hears that block's candidate
moments, audio only, in random order, without knowing which one the machine
bookmarked, and picks the one that sounds most confident. The pick never
changes the speaker's bookmarks. It is stored to measure, and later to
teach, the Manager's choice."

THE SAMPLE: V3 blocks (the frozen shadow frame) with at least two eligible
confidence candidates; at most three clips per sheet, the machine's pick
among them (D1), shuffled, audio only (no transcript, no speaker, no Take,
no hint); never a block of a Take the coach is walking, never a clip the
coach was exposed to; the weekly cap (20 per coach) is shared with the
error audit (Phase 6a).

THE RECORD (migration 0411, ``coach_block_pick``, append-only, provenance
``coach_block_pick``): the block, the Take, the candidate clips in the order
shown, the pick or Can't tell, the Manager's pick (stored, never sent to a
client), the versions. Never mixed with confidence labels, owner answers or
exercise outcomes (L3); never changes ideal_text_feedback_sets (L2). The
ledger reports the match rate with Can't tell counted apart. No training:
voice training waits for C1 and the founder's sentence.
"""
from __future__ import annotations

import logging
import random
from collections import Counter
from typing import Any, Iterable

_log = logging.getLogger(__name__)

#: At most this many clips on one sheet, the Manager's pick always among them.
SHEET_SIZE = 3
MIN_CANDIDATES = 2
PROVENANCE = "coach_block_pick"
POLICY_VERSION = "coach-block-pick-v1"
#: Wording approved by the founder (D2), word for word.
WORDING = {
    "queue_line": "Also waiting · blind",
    "title": "Pick the most confident moment",
    "short_title": "Pick the most confident",
    "private": "Private · training · one block · random order",
    "question": "Which of these sounds most confident?",
    "clip": "Clip {letter}",
    "this_one": "This one",
    "most_confident": "Most confident",
    "blind_note": "Audio only. No words, no names, no hint of the machine's pick.",
    "save": "Save my pick",
    "cant_tell": "Can't tell",
    "progress": "Block {n} of {of}",
}


def block_pick_enabled() -> bool:
    from config import Config
    return bool(getattr(Config, "COACH_BLOCK_PICK_ENABLED", False))


# ── blocks worth asking about ─────────────────────────────────────────────

def askable_blocks(frame: Any, *, take_session_id: str) -> list[dict]:
    """The frozen frame's blocks with at least two eligible candidates and
    a Manager pick: {block_id, take_session_id, candidate_ids, manager_pick}.
    Pure."""
    blocks = frame.get("blocks") if isinstance(frame, dict) else None
    out: list[dict] = []
    for block in blocks or []:
        if not isinstance(block, dict) or not block.get("selected_candidate_id"):
            continue
        eligible = [c for c in (block.get("confidence_candidates") or [])
                    if isinstance(c, dict) and c.get("eligibility") == "eligible"
                    and c.get("snippet_id")]
        if len(eligible) < MIN_CANDIDATES:
            continue
        pick = next((c for c in eligible
                     if str(c.get("candidate_id")) == str(block["selected_candidate_id"])), None)
        if pick is None:
            continue
        out.append({"block_id": str(block.get("block_id")), "take_session_id": str(take_session_id),
                    "candidate_ids": [str(c["snippet_id"]) for c in eligible],
                    "manager_pick": str(pick["snippet_id"])})
    return out


def sheet_clips(block: dict, *, rng: Any = None) -> list[str]:
    """Up to three clip ids, the Manager's pick always among them, shuffled.
    Pure."""
    rng = rng or random.Random()
    others = [c for c in block.get("candidate_ids") or [] if c != block.get("manager_pick")]
    rng.shuffle(others)
    chosen = [str(block["manager_pick"])] + others[:SHEET_SIZE - 1]
    rng.shuffle(chosen)
    return chosen


def sample_for_coach(database: Any, *, coach_id: str, week: str,
                     rng: Any = None) -> list[dict]:
    """Fill this coach's week up to the shared cap with blocks they may
    judge blind. [] off or when the cap is spent."""
    from services.coach_exposure import exposed_clip_ids, record_exposure
    from services.error_presence_audit import WEEKLY_CAP
    if not block_pick_enabled():
        return []
    rng = rng or random.Random()
    spent = int(database.count_coach_blind_answers(str(coach_id), week) or 0)
    pending = database.list_coach_block_picks_pending(str(coach_id)) or []
    room = WEEKLY_CAP - spent - len(pending)
    if room <= 0:
        return []
    done = {str(r.get("block_id")) for r in (database.list_coach_block_picks_by_coach(str(coach_id)) or [])
            if isinstance(r, dict)}
    walking = {str(t) for t in (database.list_takes_coach_is_walking(str(coach_id)) or [])}
    written: list[dict] = []
    for frame_row in database.list_recent_v3_frames(limit=200) or []:
        if len(written) >= room:
            break
        if not isinstance(frame_row, dict):
            continue
        take = str(frame_row.get("take_session_id") or "")
        if not take or take in walking:
            continue
        for block in askable_blocks(frame_row.get("frame"), take_session_id=take):
            if len(written) >= room or block["block_id"] in done:
                continue
            if exposed_clip_ids(database, str(coach_id), block["candidate_ids"]):
                continue
            clips = sheet_clips(block, rng=rng)
            row = database.insert_coach_block_pick({
                "coach_id": str(coach_id), "take_session_id": take,
                "block_id": block["block_id"], "candidate_snippet_ids": clips,
                "manager_pick_snippet_id": block["manager_pick"],
                "policy_version": POLICY_VERSION,
                "frame_policy_version": frame_row.get("policy_version"),
                "week": week, "provenance": PROVENANCE,
            })
            if isinstance(row, dict):
                written.append(row)
                for clip in clips:
                    record_exposure(database, coach_id=str(coach_id), clip_id=clip, via="block_pick")
    return written


# ── the sheet and the answer ──────────────────────────────────────────────

def queue(database: Any, *, coach_id: str) -> tuple[int, dict]:
    """The coach's pending picks, audio only; the Manager's pick is never
    in the payload. 404 off."""
    from services.snippet_audio_url import snippet_clip_playback
    if not block_pick_enabled():
        return 404, {"code": "NOT_FOUND", "error": "not found"}
    rows = [r for r in (database.list_coach_block_picks_pending(str(coach_id)) or []) if isinstance(r, dict)]
    items = []
    for n, row in enumerate(rows, start=1):
        clips = []
        for i, clip_id in enumerate(row.get("candidate_snippet_ids") or []):
            snippet = database.get_snippet_by_id(str(clip_id)) or {}
            # Audio and its window only (BLIND COACH): the parent ref plays
            # only the clip once the offsets ride along.
            clips.append({"clip_id": str(clip_id), "letter": "ABC"[i] if i < 3 else str(i + 1),
                          **snippet_clip_playback(snippet, database)})
        items.append({"pick_id": str(row.get("id")), "clips": clips, "n": n, "of": len(rows)})
    return 200, {"items": items, "wording": WORDING}


def answer(database: Any, *, coach_id: str, pick_id: str, body: Any) -> tuple[int, dict]:
    """Body {pick_clip_id} or {cant_tell: true}: one answer, once."""
    if not block_pick_enabled():
        return 404, {"code": "NOT_FOUND", "error": "not found"}
    fields: dict = body if isinstance(body, dict) else {}
    cant_tell = fields.get("cant_tell") is True
    pick = fields.get("pick_clip_id")
    if cant_tell == bool(pick):
        return 400, {"code": "INVALID_INPUT", "error": "pick one clip, or say you can't tell"}
    row = database.get_coach_block_pick(str(pick_id), str(coach_id))
    if not isinstance(row, dict):
        return 404, {"code": "NOT_FOUND", "error": "pick not found"}
    if row.get("answered_at"):
        return 409, {"code": "ALREADY_ANSWERED", "error": "That block is already answered."}
    if pick and str(pick) not in {str(c) for c in (row.get("candidate_snippet_ids") or [])}:
        return 400, {"code": "INVALID_INPUT", "error": "pick_clip_id is not on this sheet"}
    saved = database.answer_coach_block_pick(pick_id=str(pick_id), coach_id=str(coach_id),
                                             pick_snippet_id=str(pick) if pick else None,
                                             cant_tell=cant_tell)
    if not isinstance(saved, dict):
        return 500, {"code": "V2_ERROR", "error": "Could not save the pick."}
    return 200, {"recorded": True}


# ── the ledger ─────────────────────────────────────────────────────────────

def match_rate(rows: Iterable[Any]) -> dict:
    """Picks that matched the Manager's, with Can't tell counted apart.
    Pure; founder-only."""
    counts: Counter = Counter()
    for r in rows:
        if not isinstance(r, dict) or not r.get("answered_at"):
            continue
        if r.get("cant_tell"):
            counts["cant_tell"] += 1
        elif str(r.get("pick_snippet_id")) == str(r.get("manager_pick_snippet_id")):
            counts["match"] += 1
        else:
            counts["differ"] += 1
    judged = counts["match"] + counts["differ"]
    return {"answered": judged + counts["cant_tell"], "match": counts["match"],
            "differ": counts["differ"], "cant_tell": counts["cant_tell"],
            "match_rate": round(counts["match"] / judged, 3) if judged else None,
            "policy_version": POLICY_VERSION}


def ledger(database: Any) -> dict:
    if not block_pick_enabled():
        return {"enabled": False, **match_rate([])}
    return {"enabled": True, **match_rate(database.list_coach_block_picks_all() or [])}


