"""Coach Yes/No answers about errors, blind (founder 2026-10-01, F6; task 1
and Phase 6a), dark behind ``Config.ERROR_PRESENCE_AUDIT_ENABLED``.

F6: "Coaches may answer blind Yes/No questions about errors on speakers'
moments. The answers are stored for measuring and improving the error
detector. They are never shown to speakers and never mixed with confidence
labels, owner answers or detector verdicts."

THE QUEUE is the coach's own line: one moment plays, and for one error the
library's own question (``speaking_error.asks``, word for word): Yes, No,
Can't tell. Blind: no verdict, no request kind, no confidence read, no
earlier answer, no stratum. Sampling is stratified per error (fired and not
fired, from the shadow observations of the detector versions in force),
across many speakers with a per-speaker cap, practice attempts as well as
original moments (Phase 5), never a clip the coach was exposed to or has
already answered; the sampling probability rides each row so the report
can weight. About one in ten answered clips goes to a second coach,
unannounced, for agreement. The weekly cap (20 per coach) is shared with
the blind block pick (Phase 8).

THE STORAGE (migration 0411, ``error_presence_audit``) is append-only:
sampled rows carry no answer until the coach answers once. Provenance
``coach_audit``; never mixed with detector verdicts, named errors,
confidence labels or owner answers (L3). Purged with the speaker's Take and
with the coach.

THE REPORT CARD is founder-only (AC-9): per error and detector version the
four boxes (caught, false alarm, missed, rightly quiet) with rates weighted
by sampling probability and a speaker-resampled interval, counts by
speaker, fast against slow speakers, coach-against-coach agreement on the
overlap; below 30 Yes and 30 No per error it says "not enough answers
yet". ``false_alarm_rate`` fills the half ``verbal_cue_validation`` could
not measure.
"""
from __future__ import annotations

import logging
import random
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

_log = logging.getLogger(__name__)

ERRORS = ("rushing", "word_compression", "ending_compression")
VERBAL_ERRORS = ("hedging", "filler_cluster", "restart_repair")
ANSWERS = ("yes", "no", "cant_tell")
CLIP_KINDS = ("snippet", "practice_attempt")
#: Blind answers per coach per week, shared with the block pick (Phase 8).
WEEKLY_CAP = 20
#: The share of answered clips that goes to a second coach, unannounced.
OVERLAP_SHARE = 0.10
#: Clips of one speaker a coach meets in one week's sample.
PER_SPEAKER_CAP = 3
#: Below this many Yes AND this many No per error the card says so.
MIN_PER_BOX = 30
BOOTSTRAP_DRAWS = 200
PROVENANCE = "coach_audit"
#: Proposed wording, held for the founder's sign-off; served only under the
#: switch, never composed.
WORDING = {
    "queue_line": "Also waiting · blind",
    "title": "Do you hear it?",
    "question": "{asks}",
    "yes": "Yes", "no": "No", "cant_tell": "Can't tell",
    "private": "Private · training · one moment",
    "done": "Thank you. That one is kept.",
}


def audit_enabled() -> bool:
    from config import Config
    return bool(getattr(Config, "ERROR_PRESENCE_AUDIT_ENABLED", False))


def verbal_errors_enabled() -> bool:
    from config import Config
    return bool(getattr(Config, "ERROR_PRESENCE_AUDIT_VERBAL_ENABLED", False))


def errors_in_scope() -> tuple[str, ...]:
    return ERRORS + (VERBAL_ERRORS if verbal_errors_enabled() else ())


def week_key(now: Optional[datetime] = None) -> str:
    when = now or datetime.now(timezone.utc)
    year, week, _ = when.isocalendar()
    return f"{year}-W{week:02d}"


# ── sampling ───────────────────────────────────────────────────────────────

def sampling_plan(candidates: Iterable[dict], *, size: int,
                  rng: Any = None) -> list[dict]:
    """Stratified per (error, fired): equal draws from each stratum, round
    robin until `size`; each pick carries its sampling probability (picks
    from its stratum over the stratum's size). Pure."""
    rng = rng or random.Random()
    strata: dict[tuple[str, bool], list[dict]] = defaultdict(list)
    for c in candidates:
        if isinstance(c, dict) and c.get("clip_id") and c.get("error_id"):
            strata[(str(c["error_id"]), bool(c.get("fired")))].append(c)
    for rows in strata.values():
        rng.shuffle(rows)
    counts: Counter = Counter()
    picks: list[dict] = []
    keys = sorted(strata)
    while len(picks) < max(0, int(size)) and any(counts[k] < len(strata[k]) for k in keys):
        for k in keys:
            if len(picks) >= size:
                break
            if counts[k] < len(strata[k]):
                picks.append(strata[k][counts[k]])
                counts[k] += 1
    out = []
    for pick in picks:
        k = (str(pick["error_id"]), bool(pick.get("fired")))
        out.append({**pick, "sampling_probability": round(counts[k] / len(strata[k]), 4)})
    return out


def _per_speaker_cap(rows: list[dict]) -> list[dict]:
    seen: Counter = Counter()
    out = []
    for r in rows:
        who = str(r.get("speaker_user_id") or r.get("take_session_id") or "")
        if seen[who] >= PER_SPEAKER_CAP:
            continue
        seen[who] += 1
        out.append(r)
    return out


def sample_for_coach(database: Any, *, coach_id: str, now: Optional[datetime] = None,
                     rng: Any = None) -> list[dict]:
    """Fill this coach's week up to the shared cap, blind. The rows are
    written with no answer and the coach's exposure to each clip is
    recorded (task 4). [] off, or when the cap is spent."""
    from services.coach_exposure import record_exposure, unexposed
    if not audit_enabled():
        return []
    rng = rng or random.Random()
    week = week_key(now)
    spent = int(database.count_coach_blind_answers(str(coach_id), week) or 0)
    room = WEEKLY_CAP - spent
    pending = database.list_error_presence_audit_pending(str(coach_id)) or []
    room -= len(pending)
    if room <= 0:
        return []
    answered_by_me = {(str(r.get("clip_id")), str(r.get("error_id")))
                      for r in (database.list_error_presence_audit_by_coach(str(coach_id)) or [])
                      if isinstance(r, dict)}
    candidates = [c for c in (database.list_audit_candidates(list(errors_in_scope())) or [])
                  if isinstance(c, dict) and (str(c.get("clip_id")), str(c.get("error_id"))) not in answered_by_me]
    candidates = unexposed(database, str(coach_id), candidates)
    plan = _per_speaker_cap(sampling_plan(candidates, size=room * 3, rng=rng))[:room]
    written = []
    for pick in plan:
        audited_before = int(pick.get("answered_count") or 0)
        if audited_before >= 2 or (audited_before == 1 and rng.random() >= OVERLAP_SHARE):
            continue
        row = database.insert_error_presence_audit({
            "coach_id": str(coach_id), "clip_id": str(pick["clip_id"]),
            "clip_kind": str(pick.get("clip_kind") or "snippet"),
            "take_session_id": pick.get("take_session_id"),
            "speaker_user_id": pick.get("speaker_user_id"),
            "error_id": str(pick["error_id"]),
            "fired_at_sampling": bool(pick.get("fired")),
            "detector_version": pick.get("detector_version"),
            "signal_rules_version": pick.get("signal_rules_version"),
            "measurements": pick.get("measurements") or {},
            "sampling_probability": pick.get("sampling_probability"),
            "overlap": audited_before == 1,
            "week": week, "provenance": PROVENANCE,
        })
        if isinstance(row, dict):
            written.append(row)
            record_exposure(database, coach_id=str(coach_id), clip_id=str(pick["clip_id"]),
                            clip_kind=str(pick.get("clip_kind") or "snippet"), via="audit")
    return written


# ── the queue and the answer ──────────────────────────────────────────────

def queue(database: Any, *, coach_id: str) -> tuple[int, dict]:
    """The coach's pending items, blind: the clip, the error's own question,
    nothing else. 404 off."""
    from services.audio_ref_resolver import resolve_playable_ref
    if not audit_enabled():
        return 404, {"code": "NOT_FOUND", "error": "not found"}
    asks = {str(r.get("error_id")): r for r in (database.list_speaking_errors() or [])
            if isinstance(r, dict) and r.get("error_id")}
    items = []
    for row in database.list_error_presence_audit_pending(str(coach_id)) or []:
        if not isinstance(row, dict):
            continue
        library = asks.get(str(row.get("error_id")), {})
        audio = database.audit_clip_audio(str(row.get("clip_id")), str(row.get("clip_kind") or "snippet"))
        items.append({
            "audit_id": str(row.get("id")),
            "clip_id": str(row.get("clip_id")),
            "audio_ref": resolve_playable_ref(audio) if audio else None,
            "error_id": str(row.get("error_id")),
            "label": library.get("label") or str(row.get("error_id")),
            "asks": library.get("asks") or "",
        })
    return 200, {"items": items, "wording": WORDING}


def answer(database: Any, *, coach_id: str, audit_id: str, body: Any) -> tuple[int, dict]:
    """One answer, once; the row's measurements stay as sampled."""
    if not audit_enabled():
        return 404, {"code": "NOT_FOUND", "error": "not found"}
    fields: dict = body if isinstance(body, dict) else {}
    value = fields.get("answer")
    if value not in ANSWERS:
        return 400, {"code": "INVALID_INPUT", "error": "answer must be yes, no or cant_tell"}
    row = database.answer_error_presence_audit(audit_id=str(audit_id), coach_id=str(coach_id),
                                               answer=str(value))
    if not isinstance(row, dict):
        return 409, {"code": "ALREADY_ANSWERED", "error": "That one is already answered."}
    return 200, {"recorded": True}


# ── the report card ────────────────────────────────────────────────────────

def _boxes(rows: Iterable[dict]) -> dict:
    """The four boxes for one error, weighted by 1 / sampling probability.
    Can't tell is left out. Pure."""
    w = {"caught": 0.0, "false_alarm": 0.0, "missed": 0.0, "rightly_quiet": 0.0}
    n = {"caught": 0, "false_alarm": 0, "missed": 0, "rightly_quiet": 0}
    for r in rows:
        a, fired = r.get("answer"), bool(r.get("fired_at_sampling"))
        if a not in ("yes", "no"):
            continue
        box = ("caught" if fired and a == "yes" else "false_alarm" if fired
               else "missed" if a == "yes" else "rightly_quiet")
        p = r.get("sampling_probability")
        weight = 1.0 / float(p) if isinstance(p, (int, float)) and p > 0 else 1.0
        w[box] += weight
        n[box] += 1
    catch = (w["caught"] / (w["caught"] + w["missed"])) if (w["caught"] + w["missed"]) else None
    false_alarm = (w["false_alarm"] / (w["false_alarm"] + w["rightly_quiet"])) \
        if (w["false_alarm"] + w["rightly_quiet"]) else None
    return {"counts": n, "catch_rate": None if catch is None else round(catch, 3),
            "false_alarm_rate": None if false_alarm is None else round(false_alarm, 3)}


def _speaker_interval(rows: list[dict], key: str, rng: Any) -> Optional[list[float]]:
    """A speaker-resampled 90% interval for one rate: speakers drawn with
    replacement, the rate recomputed each draw. None below two speakers."""
    by: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by[str(r.get("speaker_user_id") or r.get("take_session_id") or "?")].append(r)
    speakers = list(by)
    if len(speakers) < 2:
        return None
    draws = []
    for _ in range(BOOTSTRAP_DRAWS):
        sample = [r for s in rng.choices(speakers, k=len(speakers)) for r in by[s]]
        value = _boxes(sample).get(key)
        if value is not None:
            draws.append(value)
    if len(draws) < 20:
        return None
    draws.sort()
    return [round(draws[int(0.05 * len(draws))], 3), round(draws[int(0.95 * len(draws)) - 1], 3)]


def _speed_split(rows: list[dict]) -> dict:
    wpms = [float(r["measurements"]["wpm"]) for r in rows
            if isinstance(r.get("measurements"), dict)
            and isinstance(r["measurements"].get("wpm"), (int, float))]
    if len(wpms) < 4:
        return {"fast": None, "slow": None, "split_wpm": None}
    median = statistics.median(wpms)
    fast = [r for r in rows if isinstance(r.get("measurements"), dict)
            and isinstance(r["measurements"].get("wpm"), (int, float)) and r["measurements"]["wpm"] >= median]
    slow = [r for r in rows if r not in fast]
    return {"fast": _boxes(fast), "slow": _boxes(slow), "split_wpm": round(median, 1)}


def _agreement(rows: list[dict]) -> dict:
    """Coach against coach on the overlap: pairs of answers on one (clip,
    error) by two coaches."""
    by: dict[tuple[str, str], list[str]] = defaultdict(list)
    for r in rows:
        if r.get("answer") in ("yes", "no"):
            by[(str(r.get("clip_id")), str(r.get("error_id")))].append(str(r["answer"]))
    pairs = [v for v in by.values() if len(v) >= 2]
    agree = sum(1 for v in pairs if len(set(v[:2])) == 1)
    return {"pairs": len(pairs), "agree": agree,
            "rate": round(agree / len(pairs), 3) if pairs else None}


def report_card(rows: Iterable[dict], *, rng: Any = None) -> dict:
    """Per error (and detector version): the four boxes, the rates with
    speaker-resampled intervals, speakers, speed split, overlap agreement;
    "not enough answers yet" below the floor. Pure; founder-only."""
    rng = rng or random.Random(7)
    by_error: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if isinstance(r, dict) and r.get("error_id") and r.get("answer"):
            by_error[str(r["error_id"])].append(r)
    out: dict[str, dict] = {}
    for error, items in sorted(by_error.items()):
        yes = sum(1 for r in items if r.get("answer") == "yes")
        no = sum(1 for r in items if r.get("answer") == "no")
        boxes = _boxes(items)
        enough = yes >= MIN_PER_BOX and no >= MIN_PER_BOX
        out[error] = {
            **boxes,
            "answers": {"yes": yes, "no": no,
                        "cant_tell": sum(1 for r in items if r.get("answer") == "cant_tell")},
            "speakers": len({str(r.get("speaker_user_id") or r.get("take_session_id")) for r in items}),
            "enough": enough,
            "note": None if enough else "not enough answers yet",
            "catch_interval": _speaker_interval(items, "catch_rate", rng) if enough else None,
            "false_alarm_interval": _speaker_interval(items, "false_alarm_rate", rng) if enough else None,
            "speed": _speed_split(items),
            "agreement": _agreement(items),
            "detector_versions": sorted({str(r.get("detector_version")) for r in items
                                         if r.get("detector_version")}),
        }
    return out


def false_alarm_rate(database: Any, *, error_id: str,
                     detector_version: Optional[str] = None) -> Optional[float]:
    """The half verbal_cue_validation cannot measure, from blind answers;
    None below the floor or off."""
    if not audit_enabled():
        return None
    rows = [r for r in (database.list_error_presence_audit_answered(str(error_id)) or [])
            if isinstance(r, dict)
            and (detector_version is None or str(r.get("detector_version")) == str(detector_version))]
    card = report_card(rows).get(str(error_id))
    return card.get("false_alarm_rate") if card and card.get("enough") else None
