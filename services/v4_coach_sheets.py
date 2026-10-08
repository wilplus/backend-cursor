"""V4's two blind coach sheets (V4 Phase 1, B1.8 and B1.9; build plan
D-ML-13; founder S-B8 A, Q-B8 A, QG4 B, QG9 A, QB7 B, QB8 A, V18 A, V19 A,
V20 A, M9, H7; migration 0453), dark behind
``Config.V4_COACH_SHEETS_ENABLED``.

B1.8 "PICK THE MOMENT FOR FEEDBACK". Up to three moments (clips) of one
block, each with its words and audio, in random order; the rater picks the
one that most needs work, or "None needs it" (QB7 B: praise is not asked).
The blocks come from V4's dark picks (0452): mostly where V4 is least sure,
plus a random share (``RANDOM_SHARE``); about ten a week each (H7). For a
coach, about one in ten is a block they answered two to three weeks before,
unmarked (QG9 A). The founder answers the same sheet and the founder's
answers alone are the golden set (QG4 B); "None needs it" from both is
agreement (V18 A).

B1.9 "WHICH SOUNDS SURER". The speaker's own words beside a machine version
(V20 A) that changes one word quality: the unambiguous fillers or the
unambiguous hedges are taken out (rule ``surer-pair-v1-lexical``; the same
lexicon as willfidence's signals), the quality the panel has answered least
about first ("the system varies only the word qualities it is least sure
of"). "Is the new version surer? Yes / No / Can't tell" (V19 A). The queue is
40% passages above the reached bar, 40% below, 20% random (P6, QB8 A),
shuffled. A Yes or No is stored with its preference pair (chosen, rejected);
training stays off (M10).

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
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from services import pair_consent, verbal_markers
from services import willfidence as wf

_log = logging.getLogger(__name__)

POLICY_VERSION = "take-feedback-policy-v3-universal-dark-v3"
PICKER_VERSION = "v4-picker-v1"
PAIR_RULE = "surer-pair-v1-lexical"
#: H7, M9: about ten blocks a week each, for each sheet.
WEEKLY_CAP = 10
#: B1.8: the rest of the week's blocks are where V4 is least sure.
RANDOM_SHARE = 0.3
#: QG9 A: about one in ten of a coach's blocks is a re-pick, 14 to 21 days on.
REPICK_SHARE = 0.1
REPICK_AFTER = timedelta(days=14)
REPICK_BEFORE = timedelta(days=21)
SHEET_SIZE = 3
#: P6: 40% above the bar, 40% below, 20% random.
SLICE_WEIGHTS = (("above", 0.4), ("below", 0.4), ("random", 0.2))

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
    "surer": {
        "queue_line": "Also waiting · blind",
        "row": "Which sounds surer",
        "title": "Which sounds surer",
        "caption": "Words only. No names, no hint of which change the machine is testing.",
        "said": "The words said",
        "new": "The new version",
        "question": "Is the new version surer?",
        "yes": "Yes",
        "no": "No",
        "cant_tell": "Can't tell",
        "progress": "Pair {n} of {of}",
        "kept": "Thank you. That one is kept.",
    },
}


def sheets_enabled() -> bool:
    from config import Config
    return bool(getattr(Config, "V4_COACH_SHEETS_ENABLED", False))


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
    row = database.insert_v4_pick_sheet({
        "rater_id": rater_id, "rater_role": role,
        "take_session_id": candidate["take_session_id"],
        "policy_version": POLICY_VERSION, "picker_version": PICKER_VERSION,
        "block_id": str(candidate["block"].get("block_id")), "clip_ids": chosen,
        "v4_snippet_id": candidate["v4"] if candidate["v4"] in chosen else None,
        "v3_snippet_id": candidate["v3"] if candidate["v3"] in chosen else None,
        "slice": slice_, "repick_of": repick_of, "week": week,
    })
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
    if not sheets_enabled():
        return []
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
    pool = [c for c in candidate_blocks(frames, picks)
            if (c["take_session_id"], str(c["block"].get("block_id"))) not in asked]
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

def _strip(text: str, terms: Iterable[str]) -> str:
    out = text
    for term in sorted(terms, key=len, reverse=True):
        out = re.sub(r"(?i)\b" + re.escape(term) + r"\b,?", "", out)
    out = re.sub(r"\s+([,.;:!?])", r"\1", re.sub(r"\s{2,}", " ", out)).strip()
    out = re.sub(r"^[,;:\s]+", "", out)
    return out[:1].upper() + out[1:] if out else out


def machine_version(said: str, quality: str) -> Optional[str]:
    """The said words with one quality's unambiguous terms taken out, or
    None when there is nothing to take out. Pure."""
    terms = wf.FILLER_TERMS if quality == "filler" else wf.HEDGE_TERMS
    counted = verbal_markers.count(said)[
        verbal_markers.TIC if quality == "filler" else verbal_markers.HEDGE]
    if not counted["strict"]:
        return None
    new = _strip(said, terms)
    return new if new and new != said.strip() else None


def least_sure_quality(answer_counts: Counter) -> list[str]:
    """The qualities, the one with the fewest answered pairs first."""
    return sorted(("filler", "hedging"), key=lambda q: (answer_counts.get(q, 0), q))


def slice_of(level: Optional[float], bar: float, rng: Any) -> str:
    draw = rng.random()
    acc = 0.0
    for name, weight in SLICE_WEIGHTS:
        acc += weight
        if draw < acc:
            want = name
            break
    else:
        want = "random"
    if want == "random" or level is None:
        return "random"
    return "above" if level >= bar else "below"


def _block_level(read: dict) -> Optional[float]:
    level = read.get("willfident")
    return float(level) if level is not None else None


def _pair_for_clip(said: str, take: str, block_id: str, asked: set, answered: Counter
                   ) -> Optional[str]:
    """The quality this clip's pair varies: the least answered one with a
    machine version and not yet asked on this block."""
    return next((q for q in least_sure_quality(answered)
                 if (take, block_id, q) not in asked and machine_version(said, q)), None)


def _surer_for_block(database: Any, ctx: dict, take: str, block: dict, level: Optional[float],
                     clips: dict[str, dict]) -> Optional[dict]:
    """At most one pair from a block: its first clip with a pair to offer."""
    from services.coach_exposure import exposed_clip_ids, record_exposure
    from services.v4_reached_bar import BAR, BAR_VERSION
    block_id = str(block.get("block_id"))
    for clip_id in block.get("snippet_ids") or []:
        said = str((clips.get(str(clip_id)) or {}).get("transcript") or "").strip()
        if not said or exposed_clip_ids(database, ctx["rater_id"], [str(clip_id)]):
            continue
        quality = _pair_for_clip(said, take, block_id, ctx["asked"], ctx["answered"])
        if quality is None:
            continue
        row = database.insert_v4_surer_sheet({
            "rater_id": ctx["rater_id"], "rater_role": ctx["role"], "take_session_id": take,
            "block_id": block_id, "said_text": said,
            "new_text": machine_version(said, quality), "varied_quality": quality,
            "version_rule": PAIR_RULE, "slice": slice_of(level, BAR, ctx["rng"]),
            "level": level, "bar": BAR, "bar_version": BAR_VERSION, "week": ctx["week"],
        })
        if not isinstance(row, dict):
            return None
        ctx["asked"].add((take, block_id, quality))
        record_exposure(database, coach_id=ctx["rater_id"], clip_id=str(clip_id), via="block_pick")
        return row
    return None


def _surer_for_take(database: Any, ctx: dict, frame_row: dict, room: int) -> list[dict]:
    take = str(frame_row["take_session_id"])
    reads = {str(r.get("block_id")): r for r in database.list_v4_willfidence_reads(take) or []}
    clips = {str(s.get("id")): s for s in database.get_snippets_by_session(take) or []
             if isinstance(s, dict)}
    out: list[dict] = []
    for block in (frame_row.get("frame") or {}).get("blocks") or []:
        if len(out) >= room:
            break
        level = _block_level(reads.get(str(block.get("block_id"))) or {})
        row = _surer_for_block(database, ctx, take, block, level, clips)
        out.extend([row] if row else [])
    return out


def fill_surer_sheets(database: Any, *, rater_id: str, week: str, rng: Any = None) -> list[dict]:
    """Fill this rater's week of pairs up to WEEKLY_CAP, the 40/40/20 mix
    drawn per pair. [] off or when full."""
    if not sheets_enabled():
        return []
    rng = rng or random.Random()
    mine = [r for r in database.list_v4_surer_sheets(rater_id) or [] if isinstance(r, dict)]
    room = _week_room(mine, week)
    if room <= 0:
        return []
    ctx = {
        "rater_id": rater_id, "role": rater_role(rater_id), "week": week, "rng": rng,
        "answered": Counter(str(r.get("varied_quality"))
                            for r in database.list_v4_surer_answers() or [] if isinstance(r, dict)),
        "asked": {(str(r.get("take_session_id")), str(r.get("block_id")), str(r.get("varied_quality")))
                  for r in mine},
    }
    frames = _open_frames(database, rater_id)
    rng.shuffle(frames)
    written: list[dict] = []
    for frame_row in frames:
        if len(written) >= room:
            break
        written.extend(_surer_for_take(database, ctx, frame_row, room - len(written)))
    return written


# ── the sheets and the answers ────────────────────────────────────────────

_OFF = (404, {"code": "NOT_FOUND", "error": "not found"})


def _ms(value: Any) -> Optional[int]:
    """Where a clip sits in its recording: a position, never a score."""
    return int(value) if isinstance(value, (int, float)) and value >= 0 else None


def pick_queue(database: Any, *, rater_id: str) -> tuple[int, dict]:
    """Pending blocks: words, audio, letters. Nothing the machine chose."""
    from services.snippet_audio_url import snippet_clip_playback
    if not sheets_enabled():
        return _OFF
    memo: dict = {}
    rows = [r for r in database.list_v4_pick_sheets(rater_id) or []
            if isinstance(r, dict) and not r.get("answered_at")
            and _admitted(database, r.get("take_session_id"), memo)]
    items = []
    for n, row in enumerate(rows, start=1):
        moments = []
        for i, clip_id in enumerate(row.get("clip_ids") or []):
            snippet = database.get_snippet_by_id(str(clip_id)) or {}
            moments.append({"clip_id": str(clip_id), "letter": "ABC"[i],
                            "words": str(snippet.get("transcript") or ""),
                            "audio_ref": snippet_clip_playback(snippet, database)["audio_ref"],
                            "start_offset_ms": _ms(snippet.get("start_offset_ms")),
                            "duration_ms": _ms(snippet.get("duration_ms"))})
        items.append({"sheet_id": str(row.get("id")), "moments": moments, "n": n, "of": len(rows)})
    return 200, {"items": items, "wording": WORDING["pick"]}


def pick_answer(database: Any, *, rater_id: str, sheet_id: str, body: Any) -> tuple[int, dict]:
    """Body {clip_id} or {none_needs_it: true}: one answer, once."""
    if not sheets_enabled():
        return _OFF
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


def surer_queue(database: Any, *, rater_id: str) -> tuple[int, dict]:
    """Pending pairs: the two texts, in a fixed order. No slice, no level."""
    if not sheets_enabled():
        return _OFF
    memo: dict = {}
    rows = [r for r in database.list_v4_surer_sheets(rater_id) or []
            if isinstance(r, dict) and not r.get("answered_at")
            and _admitted(database, r.get("take_session_id"), memo)]
    items = [{"sheet_id": str(r.get("id")), "said": str(r.get("said_text") or ""),
              "new": str(r.get("new_text") or ""), "n": n, "of": len(rows)}
             for n, r in enumerate(rows, start=1)]
    return 200, {"items": items, "wording": WORDING["surer"]}


def surer_answer(database: Any, *, rater_id: str, sheet_id: str, body: Any) -> tuple[int, dict]:
    """Body {answer: yes | no | cant_tell}: one answer, once."""
    if not sheets_enabled():
        return _OFF
    answer = (body if isinstance(body, dict) else {}).get("answer")
    if answer not in ("yes", "no", "cant_tell"):
        return 400, {"code": "INVALID_INPUT", "error": "answer must be yes, no or cant_tell"}
    row = database.get_v4_surer_sheet(str(sheet_id), rater_id)
    if not isinstance(row, dict) or not _admitted(database, row.get("take_session_id")):
        return 404, {"code": "NOT_FOUND", "error": "sheet not found"}
    if row.get("answered_at"):
        return 409, {"code": "ALREADY_ANSWERED", "error": "That pair is already answered."}
    chosen = {"yes": row.get("new_text"), "no": row.get("said_text")}.get(answer)
    rejected = {"yes": row.get("said_text"), "no": row.get("new_text")}.get(answer)
    saved = database.answer_v4_surer_sheet(str(sheet_id), rater_id, answer, chosen, rejected)
    if not isinstance(saved, dict):
        return 500, {"code": "V2_ERROR", "error": "Could not save the answer."}
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


def repick_consistency(rows: Iterable[dict]) -> dict:
    """QG9 A, founder-only: how often a coach picked the same again. Pure."""
    by_id = {str(r.get("id")): r for r in rows if isinstance(r, dict)}
    pairs: list[tuple[dict, dict]] = []
    for r in by_id.values():
        first = by_id.get(str(r.get("repick_of")))
        if r.get("slice") == "repick" and r.get("answered_at") and first and first.get("answered_at"):
            pairs.append((first, r))
    same = sum(1 for a, b in pairs
               if (a.get("none_needs_it"), a.get("answer_snippet_id"))
               == (b.get("none_needs_it"), b.get("answer_snippet_id")))
    return {"repicks": len(pairs), "same": same,
            "share": same / len(pairs) if pairs else None}
