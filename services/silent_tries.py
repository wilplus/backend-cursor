"""Silent tries before a change (founder, N647 item 3; N648 item 8).

A person taps "Catch more" or "Catch fewer" on one thing the walk notices.
The change runs SILENTLY beside the live setting: every recording is judged
twice, by the live setting and by the candidate, and only the live verdict
reaches anyone. Later the person sees what the candidate caught that live
did not (or dropped that live caught), and how many of those cases coaches
agreed with. Only "Use it" makes the candidate live; "Go back" drops it.
Nothing a speaker sees changes before "Use it".

WHERE A TRY LIVES. One runtime_config row per thing, key
``silent_try:<thing>``, JSON value ``{"current": try | null, "history": [...]}``.
One key per thing is what keeps one try per thing at a time; a write is a
compare-and-swap on the row's ``updated_at``, so two starts cannot both win.
No new table, no migration (coordinator, 2026-11-11).

WHAT A TRY STORES. Only clip ids and two yes/no verdicts per clip where the
two settings DIFFER, plus counts. Never a speaker's words, never a number
about a speaker. A finished try keeps its result counts in the history and
drops its clip list.

WHAT THIS MODULE DOES NOT DO. It does not evaluate a clip, read a threshold
or write a live setting: the caller passes ``evaluate`` and ``write_live``
(services/noticing_settings, the neighbour's seam). It does not read coach
answers: the caller passes the SETTLED quorum labels (docs/LEARNING-AND-QUORUM.md
section C), so a singleton, a clash or a Not sure never counts. Coaches stay
blind: nothing here reaches a coach.

The counts are for the host only (N647 item 7).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping, Optional

KEY_PREFIX = "silent_try:"
DIRECTIONS = ("more", "fewer")
#: The prototype's count: "I'll try catching more on the next 20 recordings".
RECORDINGS_NEEDED = 20
#: Ready after 20 recordings or 14 days, whichever comes first (coordinator).
READY_AFTER_DAYS = 14
#: A try nobody answers ends by itself, and changes nothing.
EXPIRES_AFTER_DAYS = 60
#: "Use it" stays off below this many settled coach answers on the cases
#: that differ; the result then says coaches have not answered enough yet.
SETTLED_NEEDED = 10
#: Bounds on what one row holds.
MAX_DIFFERING = 200
MAX_HISTORY = 20

logger = logging.getLogger(__name__)

RUNNING, READY = "running", "ready"
USED, DROPPED, EXPIRED = "used", "dropped", "expired"


class TryRefused(Exception):
    """A start, use or drop that the rules do not allow. ``reason`` is a
    short code for the route, never words for a screen."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).isoformat()


def _parse(moment: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(moment).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def key_for(thing: str) -> str:
    if not isinstance(thing, str) or not thing.strip():
        raise TryRefused("thing_missing")
    return KEY_PREFIX + thing.strip()


# ---------- the row ----------

def _read(database: Any, thing: str) -> tuple[dict, Optional[str]]:
    entry = database.get_runtime_config_entry(key_for(thing))
    if not entry:
        return {"current": None, "history": []}, None
    try:
        state = json.loads(entry.get("value") or "{}")
    except (TypeError, ValueError):
        state = {}
    if not isinstance(state, dict):
        state = {}
    state.setdefault("current", None)
    if not isinstance(state.get("history"), list):
        state["history"] = []
    return state, entry.get("updated_at")


def _write(database: Any, thing: str, state: dict, expected: Optional[str],
           *, by: Optional[str]) -> None:
    state["history"] = state["history"][-MAX_HISTORY:]
    ok = database.put_runtime_config_entry(
        key_for(thing), json.dumps(state, sort_keys=True),
        updated_by=by, expected_updated_at=expected)
    if not ok:
        raise TryRefused("changed_meanwhile")


def _close(state: dict, outcome: str, *, by: Optional[str], at: datetime) -> dict:
    current = dict(state["current"])
    summary = summarize(current, {})
    current.pop("differing", None)
    current.update({"state": outcome, "ended_at": _iso(at), "ended_by": by,
                    "seen": summary["seen"], "differing_count": summary["differing"]})
    state["history"].append(current)
    state["current"] = None
    return current


def _settle_age(state: dict, at: datetime) -> bool:
    """Move an old try on: ready at 14 days, ended at 60. True if changed."""
    current = state.get("current")
    if not current:
        return False
    started = _parse(current.get("started_at")) or at
    if at - started >= timedelta(days=EXPIRES_AFTER_DAYS):
        _close(state, EXPIRED, by=None, at=at)
        return True
    if (current.get("state") == RUNNING and current.get("seen", 0) > 0
            and at - started >= timedelta(days=READY_AFTER_DAYS)):
        current["state"] = READY
        return True
    return False


# ---------- what the routes call ----------

def start(database: Any, *, thing: str, direction: str, candidate: Mapping,
          candidate_version: str, live_version: str, started_by: str,
          at: Optional[datetime] = None) -> dict:
    """Begin a silent try. ``candidate`` is the overrides dict the settings
    seam stepped from live; it is stored, never shown. Refused while another
    try on the same thing is running or waiting for "Use it"."""
    if direction not in DIRECTIONS:
        raise TryRefused("direction_unknown")
    if not candidate or not isinstance(candidate, Mapping):
        raise TryRefused("candidate_missing")
    if not candidate_version or candidate_version == live_version:
        raise TryRefused("candidate_is_live")
    if not started_by:
        raise TryRefused("starter_missing")
    if thing in DIALS and any(name not in DIALS[thing] for name in candidate):
        # A name the dial does not own would be dropped by the settings
        # seam, and the try would judge live against itself.
        raise TryRefused("candidate_not_this_dial")
    at = at or _now()
    state, expected = _read(database, thing)
    _settle_age(state, at)
    if state["current"]:
        raise TryRefused("try_in_progress")
    state["current"] = {
        "id": uuid.uuid4().hex[:12],
        "thing": thing,
        "direction": direction,
        "candidate": dict(candidate),
        "candidate_version": candidate_version,
        "live_version": live_version,
        "started_by": started_by,
        "started_at": _iso(at),
        "state": RUNNING,
        "seen": 0,
        "takes": [],
        "clips": [],
        "differing": [],
    }
    _write(database, thing, state, expected, by=started_by)
    return state["current"]


def current(database: Any, thing: str, *, at: Optional[datetime] = None) -> Optional[dict]:
    """The try in progress on ``thing``, aged (14 days → ready, 60 → ended)."""
    at = at or _now()
    state, expected = _read(database, thing)
    if _settle_age(state, at):
        _write(database, thing, state, expected, by=None)
    return state["current"]


def history(database: Any, thing: str) -> list[dict]:
    return list(_read(database, thing)[0]["history"])


def add_recordings(database: Any, thing: str, clips: Iterable[Mapping],
                   evaluate: Callable[[Mapping, Mapping], tuple[Optional[bool], Optional[bool]]],
                   *, at: Optional[datetime] = None) -> int:
    """Judge clips under the running try, silently. ``evaluate(clip,
    candidate)`` returns (live verdict, candidate verdict), each None when
    the clip cannot be measured; such a clip does not count. Each clip is
    judged once, and ``seen`` counts the Takes (``take_session_id``) the
    judged clips came from. Used both by the re-score of the last stored recordings
    and by each new Take. Returns how many clips were new."""
    at = at or _now()
    state, expected = _read(database, thing)
    _settle_age(state, at)
    current_try = state["current"]
    if not current_try or current_try.get("state") not in (RUNNING, READY):
        return 0
    known = set(current_try.get("clips") or [])
    takes = set(current_try.get("takes") or [])
    added = 0
    for clip in clips:
        clip_id = str(clip.get("snippet_id") or "")
        if not clip_id or clip_id in known:
            continue
        live, cand = evaluate(clip, current_try["candidate"])
        if live is None or cand is None:
            continue
        known.add(clip_id)
        added += 1
        takes.add(str(clip.get("take_session_id") or clip_id))
        if bool(live) != bool(cand) and len(current_try["differing"]) < MAX_DIFFERING:
            current_try["differing"].append(
                {"snippet_id": clip_id, "live": bool(live), "candidate": bool(cand)})
    # A recording is a Take: its clips are judged one by one, and the Take
    # counts once. Ids are kept only while the try runs.
    current_try["clips"] = sorted(known)[-(RECORDINGS_NEEDED * 40):]
    current_try["takes"] = sorted(takes)
    current_try["seen"] = len(takes)
    if current_try["state"] == RUNNING and current_try["seen"] >= RECORDINGS_NEEDED:
        current_try["state"] = READY
    if added:
        _write(database, thing, state, expected, by=None)
    return added


def differing_clips(try_record: Mapping) -> list[str]:
    """The clips the coaches' blind sheets may weight up. The sheet never
    carries which setting caught a case."""
    return [d["snippet_id"] for d in try_record.get("differing") or []]


def summarize(try_record: Mapping, settled: Mapping[str, str]) -> dict:
    """The result. ``settled`` maps clip id → the SETTLED quorum value
    ("yes", "in_between", "no"); only settled labels may be passed.

    "more": ``changed`` = clips the candidate caught that live did not;
    ``agreed`` = those coaches settled as Yes.
    "fewer": ``changed`` = clips live caught that the candidate would drop;
    ``agreed`` = those coaches settled as Yes, i.e. the real ones it drops.
    """
    more = try_record.get("direction") == "more"
    changed = [d["snippet_id"] for d in try_record.get("differing") or []
               if d["candidate"] == more]
    answered = [c for c in changed if c in settled]
    agreed = sum(1 for c in answered if settled[c] == "yes")
    return {
        "state": try_record.get("state"),
        "direction": try_record.get("direction"),
        "seen": int(try_record.get("seen") or 0),
        "needed": RECORDINGS_NEEDED,
        "differing": len(try_record.get("differing") or []),
        "changed": len(changed),
        "settled": len(answered),
        "agreed": agreed,
        "enough_answers": len(answered) >= SETTLED_NEEDED,
    }


def use(database: Any, thing: str, *, try_id: str, settled: Mapping[str, str],
        write_live: Callable[[Mapping, str], Any], by: str,
        live_version: Optional[str] = None,
        at: Optional[datetime] = None) -> dict:
    """"Use it": the candidate becomes live through ``write_live(candidate,
    by)`` (a new noticing_settings version; the old one stays in its
    history). Refused before the try is ready, below the settled-answer
    floor, or when nothing would change."""
    at = at or _now()
    state, expected = _read(database, thing)
    _settle_age(state, at)
    current_try = state["current"]
    if not current_try or current_try.get("id") != try_id:
        raise TryRefused("no_such_try")
    if current_try.get("state") != READY:
        raise TryRefused("not_ready")
    if live_version is not None and live_version != current_try.get("live_version"):
        # The live setting moved while the try ran: its counts compare the
        # candidate with a setting that is no longer in force.
        raise TryRefused("live_changed")
    result = summarize(current_try, settled)
    if result["changed"] == 0:
        raise TryRefused("nothing_changes")
    if not result["enough_answers"]:
        raise TryRefused("not_enough_answers")
    # Live first: a try marked "used" whose setting never went live would
    # be the silent failure. If the close below loses a race, the try stays
    # ready and a second "Use it" writes the same candidate again.
    write_live(current_try["candidate"], by)
    closed = _close(state, USED, by=by, at=at)
    closed["result"] = result
    _write(database, thing, state, expected, by=by)
    return closed


def drop(database: Any, thing: str, *, try_id: str, by: str,
         settled: Optional[Mapping[str, str]] = None,
         at: Optional[datetime] = None) -> dict:
    """"Go back": the try ends and nothing live changes."""
    at = at or _now()
    state, expected = _read(database, thing)
    _settle_age(state, at)
    current_try = state["current"]
    if not current_try or current_try.get("id") != try_id:
        raise TryRefused("no_such_try")
    result = summarize(current_try, settled or {})
    closed = _close(state, DROPPED, by=by, at=at)
    closed["result"] = result
    _write(database, thing, state, expected, by=by)
    return closed


# ---------- the verbal cues: judged beside live (PR2) ----------
#
# The first dials are the three verbal cues (coordinator, 2026-11-11):
# "rushed" waits until a settled coach label for it exists. Each thing names
# the settings a try on it may move (services/noticing_settings).

DIALS: dict[str, tuple[str, ...]] = {
    "filler_cluster": ("verbal_cues.FILLER_MIN_COUNT",
                       "verbal_cues.FILLER_MIN_PER_100_WORDS"),
    "hedging": ("verbal_cues.HEDGE_MIN_COUNT",),
    "restart_repair": ("verbal_cues.RESTART_MIN_COUNT",),
}

_AUDIT_TO_QUORUM = {"yes": "yes", "no": "no", "cant_tell": "not_sure"}


def candidate_values(overrides: Mapping) -> dict:
    """The full set a try judges with: the live values, with the try's own
    overrides on top (``noticing_settings.candidate`` starts from live)."""
    from services import noticing_settings as ns
    return ns.candidate(dict(overrides))


def _verbal_pair(thing: str, clip: Mapping, values: Mapping) -> tuple[Optional[bool], Optional[bool]]:
    from services import noticing_settings as ns
    from services import verbal_cues
    live = verbal_cues.measure(clip.get("transcript"), clip.get("language"))
    if live is None:
        return None, None
    with ns.trying(values):
        tried = verbal_cues.measure(clip.get("transcript"), clip.get("language"))
    if tried is None:
        return None, None
    return bool(live[thing]["fired"]), bool(tried[thing]["fired"])


def _candidate_rows(thing: str, clips: list[dict], values: Mapping,
                    take_session_id: str, try_id: str) -> list[dict]:
    """The candidate's own verdicts for the shadow log, under its own
    detector version (``verbal_cues.detector_version`` inside ``trying``,
    marked ``~try-<id>``), so they are never mixed with live ones, never
    drawn by the blind audit, and never served."""
    from services import noticing_settings as ns
    from services import verbal_cues
    with ns.trying(values):
        rows = verbal_cues.take_observations(
            clips, take_session_id=take_session_id,
            language_of=lambda rid: next((c.get("language") for c in clips
                                          if str(c.get("recording_id") or "") == rid), None))
    mark = f"{verbal_cues.TRY_MARK}{try_id}"
    return [{**r, "detector_version": f"{r['detector_version']}{mark}"}
            for r in rows if r["error_id"] == thing]


def _clips_of(database: Any, take_session_id: str) -> list[dict]:
    """A Take's clips with the language each was transcribed in."""
    languages: dict[str, Optional[str]] = {}
    out = []
    for snippet in database.get_snippets_by_session(str(take_session_id)) or []:
        if not isinstance(snippet, dict) or not snippet.get("id"):
            continue
        rid = str(snippet.get("recording_id") or "")
        if rid not in languages:
            row = database.get_recording(rid) if rid else None
            languages[rid] = row.get("transcription_language") if isinstance(row, dict) else None
        out.append({**snippet, "snippet_id": str(snippet["id"]),
                    "take_session_id": str(take_session_id), "language": languages[rid]})
    return out


def running_tries(database: Any) -> dict[str, dict]:
    """thing → the try in progress, for every dial, in one read."""
    keys = [key_for(thing) for thing in DIALS]
    found = database.get_runtime_configs(keys) or {}
    out = {}
    for thing in DIALS:
        try:
            state = json.loads(found.get(key_for(thing)) or "{}")
        except (TypeError, ValueError):
            continue
        current_try = state.get("current") if isinstance(state, dict) else None
        if isinstance(current_try, dict) and current_try.get("state") in (RUNNING, READY):
            out[thing] = current_try
    return out


def observe_take(database: Any, take_session_id: str, clips: list[dict]) -> int:
    """Judge one new Take under every running try, after its live verdicts
    were logged. Writes only the try's own record and candidate rows in the
    shadow log; reads and returns nothing a speaker, coach or host sees.
    ``clips`` carry ``language`` (see ``_clips_of``). Returns clips added."""
    tries = running_tries(database)
    added = 0
    for thing, current_try in tries.items():
        values = candidate_values(current_try.get("candidate") or {})
        added += _judge(database, thing, clips, values, str(take_session_id),
                        str(current_try["id"]))
    return added


def _judge(database: Any, thing: str, clips: list[dict], values: Mapping,
           take_session_id: str, try_id: str) -> int:
    """One Take's clips under one try: the try's record, then the
    candidate's rows in the shadow log."""
    def pair(clip: Mapping, _candidate: Mapping) -> tuple[Optional[bool], Optional[bool]]:
        return _verbal_pair(thing, clip, values)

    n = add_recordings(database, thing, clips, pair)
    if n:
        rows = _candidate_rows(thing, clips, values, take_session_id, try_id)
        if rows:
            database.record_verbal_cue_shadow(rows)
    return n


def rescore(database: Any, thing: str, *, takes: int = RECORDINGS_NEEDED,
            permitted: Optional[Callable[[Any, str], bool]] = None) -> int:
    """Judge the last ``takes`` stored Takes at once (coordinator, (b)
    yes): the ones the live cue was logged on, newest first, each asked
    again for the speaker's practice yes. Their stored transcripts are read
    again; no provider is called."""
    from services import verbal_cues
    permitted = permitted or verbal_cues._practice_permitted
    current_try = current(database, thing)
    if not current_try:
        return 0
    seen_rows = database.list_verbal_cue_shadow_observations(
        thing, verbal_cues.detector_version()) or []
    newest = sorted((r for r in seen_rows if isinstance(r, dict) and r.get("take_session_id")),
                    key=lambda r: str(r.get("created_at") or ""), reverse=True)
    picked: list[str] = []
    for row in newest:
        take = str(row["take_session_id"])
        if take not in picked and permitted(database, take):
            picked.append(take)
        if len(picked) >= takes:
            break
    values = candidate_values(current_try.get("candidate") or {})
    added = 0
    for take in picked:
        added += _judge(database, thing, _clips_of(database, take), values, take,
                        str(current_try["id"]))
    return added


def settled_labels(database: Any, thing: str, clip_ids: Iterable[str]) -> dict[str, str]:
    """clip id → the SETTLED value from the coaches' blind audit answers,
    by the quorum's own rule (``label_quorum.resolve``: two matching
    answers; Can't tell never settles). Unsettled clips are left out."""
    from services import label_quorum
    wanted = set(clip_ids)
    if not wanted:
        return {}
    by_clip: dict[str, list[dict]] = {}
    for row in database.list_error_presence_audit_answered(thing) or []:
        clip = str(row.get("clip_id") or "")
        value = _AUDIT_TO_QUORUM.get(str(row.get("answer") or ""))
        if clip in wanted and value:
            by_clip.setdefault(clip, []).append(
                {"value": value, "lane": "coach", "blind": True,
                 "rater_id": row.get("coach_id")})
    out = {}
    for clip, rows in by_clip.items():
        verdict = label_quorum.resolve(rows)
        if verdict.get("settled") and verdict.get("value"):
            out[clip] = str(verdict["value"])
    return out


def result(database: Any, thing: str) -> Optional[dict]:
    """The try in progress on ``thing`` and what it found so far."""
    current_try = current(database, thing)
    if not current_try:
        return None
    settled = settled_labels(database, thing, differing_clips(current_try))
    return {"id": current_try["id"], **summarize(current_try, settled)}


def trial_clips(database: Any) -> set[tuple[str, str]]:
    """(clip id, thing) of every case a running try sees differently from
    live: the blind audit gives them their own stratum and a second coach.
    The sheet never carries which setting caught a case. Never raises."""
    try:
        tries = running_tries(database)
    except Exception as exc:  # the audit must fill its sheet regardless
        logger.warning("silent_tries: tries unreadable for the audit (%s)", exc, exc_info=True)
        return set()
    return {(clip, thing) for thing, t in tries.items() for clip in differing_clips(t)}
