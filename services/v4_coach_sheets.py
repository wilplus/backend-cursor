"""V4's blind coach sheet (V4 Phase 1, B1.8 and B1.9; build plan
D-ML-13; founder S-B8 A, Q-B8 A, QG4 B, QG9 A, QB7 B, QB8 A, V18 A, V19 A,
V20 A, M9, H7; migration 0453). On from 2026-10-08; the switch was
deleted 2026-10-11.

B1.8 "PICK THE MOMENT FOR FEEDBACK". Up to three moments (clips) of one
block, each with its words and audio, in random order; the rater picks the
one that most needs work, or "None needs it" (QB7 B: praise is not asked).
The blocks come from V4's dark picks (0452): mostly where V4 is least sure,
plus a random share (``RANDOM_SHARE``); about ten a week each (H7). For a
coach, about one in ten is a block they answered two to three weeks before,
unmarked (QG9 A). The founder answers the same sheet and the founder's
answers alone are the golden set (QG4 B); "None needs it" from both is
agreement (V18 A).

B1.9 "WHICH SOUNDS SURER" is gone from the app (founder, 25 November 2026,
N701): it trained nothing (M10). Answers already given stay readable and are
erased on withdrawal (``pair_consent``); no new pair is made.

BLIND (BLIND COACH, AC-9). A sheet carries words, audio and letters only.
The machine's picks, the slice, the passage's level and why a block was
asked are stored and never sent. Every clip shown is recorded as an
exposure, so the same coach is never asked to judge it blind afterwards.
The words on the screens are the signed prototype's (S-B8 A), held by the
frontend's coach panel copy; ``WORDING`` repeats them for the record.

ONLY SPEAKERS WITH THE TRAINING YES (3.5 pack, file 22 item E4; Privacy 3.5
§4a, signed 2026-10-08: "A coach may hear a moment of yours, without your
name, to answer a question that teaches our software"). A Take reaches a
sheet only while its speaker holds the training yes and has not objected to
the blind check (``pair_consent.take_may_reach_a_coach_sheet``: the pairs'
own consent read and 0454's objection read, nothing route-local). It is read
when a sheet is written, again when the queue is served and again when it is
answered, so a speaker who withdraws drops out of every pending sheet at
once. Anyone else is skipped, never waited on.
"""
from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from services import pair_consent

_log = logging.getLogger(__name__)

POLICY_VERSION = "take-feedback-policy-v3-universal-dark-v3"
PICKER_VERSION = "v4-picker-v1"
#: H7, M9: about ten blocks a week each, for each sheet.
WEEKLY_CAP = 10
#: B1.8: the rest of the week's blocks are where V4 is least sure.
RANDOM_SHARE = 0.3
#: QG9 A: about one in ten of a coach's blocks is a re-pick, 14 to 21 days on.
REPICK_SHARE = 0.1
REPICK_AFTER = timedelta(days=14)
REPICK_BEFORE = timedelta(days=21)
SHEET_SIZE = 3

#: The signed words (S-B8 A, prototype 4keT4hRL73HGNeNVGH2VEt).
WORDING = {
    "pick": {
        "queue_line": "Also waiting · blind",
        "row": "Pick the moment for feedback",
        "title": "Pick the moment for feedback",
        "caption": "Words and audio. No names, no hint of the machine's pick.",
        "question": "Which moment most needs feedback?",
        "moment": "Moment {letter}",
        "this_one": "This one",
        "needs_it_most": "Needs it most",
        "save": "Save my pick",
        "none": "None needs it",
        "progress": "Block {n} of {of}",
        "kept": "Thank you. That one is kept.",
    },
}


def rater_role(user_id: str) -> str:
    """The founder (the admin) or a coach; the founder's picks are golden."""
    from routes.admin import is_admin
    return "founder" if is_admin(user_id) else "coach"


# ── B1.8: the blocks ───────────────────────────────────────────────────────

def sheet_clips(block: dict, v4: Optional[str], v3: Optional[str], *,
                rng: Any) -> list[str]:
    """Up to three of the block's clips, V4's and V3's moments among them
    when they exist, shuffled. Pure."""
    clips = [str(c) for c in block.get("snippet_ids") or []]
    must = [c for c in dict.fromkeys([v4, v3]) if c and c in clips]
    others = [c for c in clips if c not in must]
    rng.shuffle(others)
    chosen = (must + others)[:SHEET_SIZE]
    rng.shuffle(chosen)
    return chosen


def candidate_blocks(frame_rows: Iterable[dict], picks_by_take: dict[str, list[dict]]
                     ) -> list[dict]:
    """Every block with at least two clips and a V4 pick row, least sure
    first. Pure."""
    out: list[dict] = []
    for row in frame_rows:
        take = str(row.get("take_session_id") or "")
        raw = row.get("frame")
        frame: dict = raw if isinstance(raw, dict) else {}
        picks = {str(p.get("block_id")): p for p in picks_by_take.get(take) or []}
        for block in frame.get("blocks") or []:
            pick = picks.get(str(block.get("block_id")))
            if pick is None or len(block.get("snippet_ids") or []) < 2:
                continue
            out.append({"take_session_id": take, "block": block,
                        "sureness": float(pick.get("sureness") or 0.0),
                        "v4": pick.get("v4_snippet_id"), "v3": pick.get("v3_snippet_id")})
    out.sort(key=lambda c: (c["sureness"], c["take_session_id"], str(c["block"].get("block_id"))))
    return out


def _due_repick(rows: Iterable[dict], now: datetime) -> Optional[dict]:
    for row in rows:
        when = row.get("answered_at")
        try:
            at = datetime.fromisoformat(str(when).replace("Z", "+00:00")) if when else None
        except ValueError:
            at = None
        if at and row.get("slice") != "repick" and REPICK_AFTER <= now - at <= REPICK_BEFORE:
            return row
    return None


def _week_room(rows: list[dict], week: str) -> int:
    """What is left of the week's cap; nothing once the founder cleared the
    line this week (cleared_week, 0482): new ones come next week."""
    if any(r.get("cleared_week") == week for r in rows):
        return 0
    return WEEKLY_CAP - sum(1 for r in rows if r.get("week") == week)


def _admitted(database: Any, take_session_id: Any, memo: Optional[dict] = None) -> bool:
    """3.5 E4: this Take's speaker holds the training yes and has not
    objected to the blind check. Memoised per call when given a dict."""
    take = str(take_session_id or "")
    if not take:
        return False
    if memo is not None and take in memo:
        return memo[take]
    ok = pair_consent.take_may_reach_a_coach_sheet(database, take)
    if memo is not None:
        memo[take] = ok
    return ok


def _open_frames(database: Any, rater_id: str) -> list[dict]:
    """Recent V3 frames, none from a Take this rater is walking, and only
    from speakers who hold the training yes (3.5 E4)."""
    walking = {str(t) for t in database.list_takes_coach_is_walking(rater_id) or []}
    memo: dict = {}
    return [r for r in database.list_recent_v3_frames(limit=200) or []
            if isinstance(r, dict) and str(r.get("take_session_id")) not in walking
            and _admitted(database, r.get("take_session_id"), memo)]


def _write_pick(database: Any, *, rater_id: str, role: str, week: str, candidate: dict,
                slice_: str, chosen: list[str], repick_of: Optional[str] = None) -> Optional[dict]:
    """One block sheet, unless a fresh one would show a clip the rater
    already heard (a repick shows the same clips on purpose)."""
    from services.coach_exposure import exposed_clip_ids, record_exposure
    if repick_of is None and exposed_clip_ids(database, rater_id, chosen):
        return None
    try:
        row = database.insert_v4_pick_sheet({
            "rater_id": rater_id, "rater_role": role,
            "take_session_id": candidate["take_session_id"],
            "policy_version": POLICY_VERSION, "picker_version": PICKER_VERSION,
            "block_id": str(candidate["block"].get("block_id")), "clip_ids": chosen,
            "v4_snippet_id": candidate["v4"] if candidate["v4"] in chosen else None,
            "v3_snippet_id": candidate["v3"] if candidate["v3"] in chosen else None,
            "slice": slice_, "repick_of": repick_of, "week": week,
        })
    except Exception as e:  # noqa: BLE001 -- one refused block never empties the queue
        _log.warning("v4 pick sheet not written rater=%s block=%s: %s",
                     rater_id, candidate["block"].get("block_id"), e)
        return None
    if not isinstance(row, dict):
        return None
    for clip in chosen:
        record_exposure(database, coach_id=rater_id, clip_id=clip, via="block_pick")
    return row


def _repick_candidate(due: dict) -> dict:
    return {"take_session_id": str(due["take_session_id"]),
            "block": {"block_id": due["block_id"], "snippet_ids": due.get("clip_ids") or []},
            "v4": due.get("v4_snippet_id"), "v3": due.get("v3_snippet_id")}


def _next_candidate(pool: list[dict], rng: Any) -> tuple[dict, str]:
    """A random block RANDOM_SHARE of the time, else the least sure."""
    if rng.random() < RANDOM_SHARE:
        return pool.pop(rng.randrange(len(pool))), "random"
    return pool.pop(0), "unsure"


def fill_pick_sheets(database: Any, *, rater_id: str, week: str, rng: Any = None,
                     now: Optional[datetime] = None) -> list[dict]:
    """Fill this rater's week up to WEEKLY_CAP. [] off or when full."""
    rng = rng or random.Random()
    now = now or datetime.now(timezone.utc)
    role = rater_role(rater_id)
    mine = [r for r in database.list_v4_pick_sheets(rater_id) or [] if isinstance(r, dict)]
    room = _week_room(mine, week)
    if room <= 0:
        return []
    asked = {(str(r.get("take_session_id")), str(r.get("block_id"))) for r in mine}
    frames = _open_frames(database, rater_id)
    picks = {str(f["take_session_id"]): database.list_v4_picks(str(f["take_session_id"])) or []
             for f in frames}
    # A Take has one frame per policy version and they share block ids; a
    # block is asked once (v4_moment_pick_sheets_once).
    pool = []
    for c in candidate_blocks(frames, picks):
        key = (c["take_session_id"], str(c["block"].get("block_id")))
        if key not in asked:
            asked.add(key)
            pool.append(c)
    common = {"rater_id": rater_id, "role": role, "week": week}
    written: list[dict] = []
    due = _due_repick(mine, now) if role == "coach" else None
    if due is not None and not _admitted(database, due.get("take_session_id")):
        due = None
    if due is not None and rng.random() < REPICK_SHARE * WEEKLY_CAP / room:
        row = _write_pick(database, **common, candidate=_repick_candidate(due), slice_="repick",
                          chosen=list(due.get("clip_ids") or []), repick_of=str(due["id"]))
        written.extend([row] if row else [])
    while pool and len(written) < room:
        candidate, slice_ = _next_candidate(pool, rng)
        chosen = sheet_clips(candidate["block"], candidate["v4"], candidate["v3"], rng=rng)
        row = _write_pick(database, **common, candidate=candidate, slice_=slice_, chosen=chosen)
        written.extend([row] if row else [])
    return written


# ── B1.9: the pairs ───────────────────────────────────────────────────────

# ── the sheets and the answers ────────────────────────────────────────────

def _ms(value: Any) -> Optional[int]:
    """Where a clip sits in its recording: a position, never a score."""
    return int(value) if isinstance(value, (int, float)) and value >= 0 else None


def _admitted_rows(database: Any, sheets: Any) -> list[dict]:
    """The pending sheets whose speaker still holds the training yes (3.5
    E4), the consent reads for the distinct Takes side by side."""
    pending = [r for r in sheets or []
               if isinstance(r, dict) and not r.get("answered_at") and not r.get("cleared_week")]
    admitted = pair_consent.takes_may_reach_a_coach_sheet(
        database, [r.get("take_session_id") for r in pending])
    return [r for r in pending if admitted.get(str(r.get("take_session_id") or ""))]


def pick_queue(database: Any, *, rater_id: str) -> tuple[int, dict]:
    """Pending blocks: words, audio, letters. Nothing the machine chose."""
    from services.snippet_audio_url import snippet_clip_playback, snippet_rows_by_id
    rows = _admitted_rows(database, database.list_v4_pick_sheets(rater_id))
    snippets = snippet_rows_by_id(
        database, [c for r in rows for c in (r.get("clip_ids") or [])], with_transcript=True)
    items = []
    for n, row in enumerate(rows, start=1):
        moments = []
        for i, clip_id in enumerate(row.get("clip_ids") or []):
            snippet = snippets.get(str(clip_id)) or {}
            moments.append({"clip_id": str(clip_id), "letter": "ABC"[i],
                            "words": str(snippet.get("transcript") or ""),
                            "audio_ref": snippet_clip_playback(snippet, database)["audio_ref"],
                            "start_offset_ms": _ms(snippet.get("start_offset_ms")),
                            "duration_ms": _ms(snippet.get("duration_ms"))})
        items.append({"sheet_id": str(row.get("id")), "moments": moments, "n": n, "of": len(rows)})
    return 200, {"items": items, "wording": WORDING["pick"]}


def pick_answer(database: Any, *, rater_id: str, sheet_id: str, body: Any) -> tuple[int, dict]:
    """Body {clip_id} or {none_needs_it: true}: one answer, once."""
    fields: dict = body if isinstance(body, dict) else {}
    none = fields.get("none_needs_it") is True
    clip = fields.get("clip_id")
    if none == bool(clip):
        return 400, {"code": "INVALID_INPUT", "error": "pick one moment, or say none needs it"}
    row = database.get_v4_pick_sheet(str(sheet_id), rater_id)
    if not isinstance(row, dict) or not _admitted(database, row.get("take_session_id")):
        return 404, {"code": "NOT_FOUND", "error": "sheet not found"}
    if row.get("answered_at"):
        return 409, {"code": "ALREADY_ANSWERED", "error": "That block is already answered."}
    if clip and str(clip) not in {str(c) for c in row.get("clip_ids") or []}:
        return 400, {"code": "INVALID_INPUT", "error": "clip_id is not on this sheet"}
    saved = database.answer_v4_pick_sheet(str(sheet_id), rater_id,
                                          str(clip) if clip else None, none)
    if not isinstance(saved, dict):
        return 500, {"code": "V2_ERROR", "error": "Could not save the pick."}
    return 200, {"recorded": True}


# ── the founder's reading (never a payload to a coach) ────────────────────

def golden_agreement(rows: Iterable[dict]) -> dict:
    """Per block the founder answered: does V4's moment, V3's moment and
    each coach's pick match the founder's? None needs it matches no pick
    (V18 A: both None is agreement; a machine always picks on an
    improvable block, so None from the founder is a miss for it). Pure."""
    founder: dict[tuple[str, str], Optional[str]] = {}
    machine: dict[tuple[str, str], tuple[Optional[str], Optional[str]]] = {}
    coaches: list[tuple[tuple[str, str], Optional[str]]] = []
    for r in rows:
        if not isinstance(r, dict) or not r.get("answered_at") or r.get("slice") == "repick":
            continue
        key = (str(r.get("take_session_id")), str(r.get("block_id")))
        answer = None if r.get("none_needs_it") else str(r.get("answer_snippet_id"))
        machine[key] = (r.get("v4_snippet_id"), r.get("v3_snippet_id"))
        if r.get("rater_role") == "founder":
            founder[key] = answer
        else:
            coaches.append((key, answer))
    golden = len(founder)
    v4 = sum(1 for k, a in founder.items() if machine[k][0] == a)
    v3 = sum(1 for k, a in founder.items() if machine[k][1] == a)
    shared = [(k, a) for k, a in coaches if k in founder]
    return {"golden_blocks": golden,
            "v4_agreement": v4 / golden if golden else None,
            "v3_agreement": v3 / golden if golden else None,
            "coach_agreement": (sum(1 for k, a in shared if founder[k] == a) / len(shared)
                                if shared else None)}

