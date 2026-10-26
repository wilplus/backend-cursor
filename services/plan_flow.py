"""The plan's conversation in the Lounge (frontend docs/flows/the-plan.md;
N129 onward; built one to one with the prototype, N203; ring row ``plan``
at ring 5, N204). The pure rules are in ``services/plan.py``.

What it writes, as rows of the one Lounge thread (``lounge_messages``,
kind "text"; the app draws a row by its ``metadata``):

  * the questions before the first Take (B): the deadline, the voice
    message, up to three follow-ups (the key line first), the two ratings
    (never shown back, N178), the two calls, then "You're all set. Here's
    your plan." and the plan card (``metadata.plan_card``);
  * a practice day's hello and today's one thing (G4 to G6), once a day, the
    first time the app opens on a practice day;
  * after a Take's walk (``after_take``, called once per Take where the
    walk's summary is written): the 15 minutes lines on a practice day
    (G13), the last practice's ratings (D1), a new event's questions, and a
    speaker with Takes but no plan asked "When is your deadline?" (A2);
  * the plan's end (I): "Your deadline was …", "How did it go?" by voice,
    the summary call, "What's next?".

Every recording is transcribed under the caller's processing authorization
(the route's ``phase1_provider_route``), and every AI call runs inside it.
Every answer is kept for Will (``speaker_memory``, kind "answer").

Tables: speaker_plans, plan_answers, plan_answer_audio, plan_level_events
(migration the_plan_keeps_each_speakers_plan). Until that migration runs,
the ring row doesn't exist, ``enabled`` is False for everyone, and nothing
here is reached.
"""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from services import plan as P

logger = logging.getLogger(__name__)

_NS = uuid.UUID("5c0f4e2a-7d1b-4a36-9b8e-3f2d6c1a9e47")
#: A voice answer of up to five minutes in browser audio is well under this.
MAX_BYTES = 12 * 1024 * 1024
MAX_SECONDS = 300
STEP_SCALE = {"stress": ("stress_q", "stress_lo", "stress_hi"),
              "ready": ("ready_q", "ready_lo", "ready_hi")}


class PlanError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def enabled(database: Any, user_id: Any) -> bool:
    """Is the plan on for this person? Fails closed (rings)."""
    from services import rings
    return bool(user_id) and rings.feature_is_on_for_user(P.FEATURE, user_id, database=database)


# ── time ───────────────────────────────────────────────────────────────────

def zone(name: Any) -> ZoneInfo:
    try:
        return ZoneInfo(str(name)) if name else ZoneInfo("UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def valid_zone(name: Any) -> Optional[str]:
    if not isinstance(name, str) or not name or len(name) > 64:
        return None
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return None
    return name


def _now() -> datetime:
    return datetime.now(timezone.utc)


def today_in(name: Any) -> date:
    return _now().astimezone(zone(name)).date()


def _parse_dt(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_day(raw: Any) -> Optional[date]:
    try:
        return date.fromisoformat(str(raw)[:10]) if raw else None
    except ValueError:
        return None


# ── rows ───────────────────────────────────────────────────────────────────

def _write(database: Any, user_id: str, plan_id: str, items: list[tuple]) -> list[dict]:
    """Rows at the bottom of the thread, in order: ``(role, body, meta, key)``.
    The key names the row inside its plan, so a row written twice is kept
    once (``insert_lounge_messages`` is idempotent on the client id)."""
    if not items:
        return []
    from services.lounge_messages import stamp_after, thread_stamp
    at = thread_stamp(database, user_id)
    rows = []
    for i, (role, body, meta, key) in enumerate(items):
        rows.append({
            "client_id": str(uuid.uuid5(_NS, f"{user_id}:{plan_id}:{key}")),
            "role": role, "kind": "text", "body": body,
            "metadata": {"plan": plan_id, **(meta or {})},
            "client_created_at": stamp_after(at, gap_ms=i) if i else at,
        })
    return database.insert_lounge_messages(str(user_id), rows) or []


def _bot(body: str, key: str, **meta: Any) -> tuple:
    return ("bot", body, meta, key)


def _me(body: str, key: str, **meta: Any) -> tuple:
    return ("user", body, meta, key)


def _hi(first_name: Optional[str]) -> str:
    return f"Hi {first_name}!" if first_name else "Hi!"


def _greeting(first_name: Optional[str]) -> str:
    """The walk's signed hello (N120): "Hi Artur, good to see you back!"."""
    return f"Hi {first_name}, good to see you back!" if first_name else "Hi, good to see you back!"


# ── reads ──────────────────────────────────────────────────────────────────

def _takes(database: Any, user_id: str) -> list[datetime]:
    """When each of the person's spoken Takes was recorded, oldest first (a
    read is a paired variant, not a Take of its own)."""
    try:
        rows = database.takes.list_user_arc_sessions(str(user_id)) or []
    except Exception:  # noqa: BLE001 -- no Takes read is no Takes counted
        return []
    out = []
    for r in rows:
        if r.get("recording_kind") == "read" or r.get("paired_session_id"):
            continue
        at = _parse_dt(r.get("created_at"))
        if at:
            out.append(at)
    return sorted(out)


def _done(plan: dict, takes: list[datetime]) -> int:
    started = _parse_dt(plan.get("started_at"))
    return sum(1 for t in takes if started and t >= started)


def _facts(plan: dict) -> dict:
    return dict(plan.get("facts") or {})


def _deadline(plan: dict) -> Optional[date]:
    return _parse_day(plan.get("deadline"))


def _days(plan: dict) -> tuple[int, ...]:
    return P.clean_days(plan.get("practice_days")) or P.DEFAULT_DAYS


def _calls(database: Any, user_id: str, plan: dict) -> dict:
    """The two calls as booked and still confirmed, in the speaker's time."""
    calls = dict(plan.get("calls") or {})
    ids = [c.get("booking_id") for c in calls.values() if isinstance(c, dict) and c.get("booking_id")]
    live = {str(b["id"]): b for b in database.list_user_bookings(str(user_id), ids=ids)} if ids else {}
    tz = zone(plan.get("time_zone"))
    out: dict[str, Optional[dict]] = {"kickoff": None, "summary": None}
    for which in out:
        c = calls.get(which)
        b = live.get(str(c.get("booking_id"))) if isinstance(c, dict) else None
        start = _parse_dt((b or {}).get("start_at"))
        if start:
            local = start.astimezone(tz)
            out[which] = {"starts_at": start.isoformat(), "text": P.fmt_when(local),
                          "short": P.fmt_when_short(local)}
    return out


def view(database: Any, user_id: str, plan: dict) -> dict:
    """The plan as the app draws it."""
    facts = _facts(plan)
    deadline = _deadline(plan)
    days = _days(plan)
    every_day = bool(plan.get("every_day"))
    today = today_in(plan.get("time_zone"))
    done = _done(plan, _takes(database, user_id))
    level = plan.get("level")
    return {
        "id": plan["id"], "status": plan["status"], "step": plan["step"],
        "deadline": deadline.isoformat() if deadline else None,
        "deadline_given": bool(plan.get("deadline_given")),
        "deadline_short": P.fmt_short(deadline) if deadline else None,
        "deadline_day": P.fmt_day(deadline) if deadline else None,
        "days": list(days), "days_text": P.days_text(days), "every_day": every_day,
        "total": int(plan.get("total") or 0), "done": done,
        "level": level, "level_name": P.level_name(level) if level else None,
        "pace_week": level in P.PACE_LEVELS,
        "key_line": facts.get("key_line"),
        "why_line": P.why_line(level, facts.get("who")) if facts.get("key_line") else None,
        "key_answer_id": facts.get("key_answer_id"),
        "calls": _calls(database, user_id, plan),
        "first_take_done": done > 0,
        "next_day": (P.next_day_text(today, deadline, days, every_day) if deadline else None),
        "topic": facts.get("topic") or facts.get("event"),
        "waiting": bool(facts.get("wait_take")),
    }


def _open(database: Any, user_id: str) -> dict:
    plan = database.get_open_plan(str(user_id))
    if not plan:
        raise PlanError("NO_PLAN", "No plan.", 404)
    return plan


def _save(database: Any, user_id: str, plan: dict, fields: dict) -> dict:
    stored = database.update_plan(str(user_id), plan["id"], fields)
    if not stored:
        raise PlanError("V2_ERROR", "Failed to keep the plan", 500)
    return stored


def _need_step(plan: dict, *steps: str) -> None:
    if plan.get("step") not in steps:
        raise PlanError("NOT_NOW", "Not now.", 409)


# ── the state, read when the Lounge opens ──────────────────────────────────

def state(database: Any, user_id: str, *, tz: Any = None,
          first_name: Optional[str] = None) -> dict:
    """``{enabled, plan, wrote}``. A new speaker with no plan and no Take
    gets the questions (A1, B1); an active plan writes today's hello on a
    practice day (G4) or, after the deadline, its end (I2). ``wrote`` tells
    the app to read the thread again."""
    if not enabled(database, user_id):
        return {"enabled": False, "plan": None, "wrote": False}
    zone_name = valid_zone(tz)
    plan = database.get_open_plan(str(user_id))
    wrote = False
    if plan is None:
        if database.get_latest_plan(str(user_id)) is None and not _takes(database, user_id):
            plan, rows = begin(database, user_id, tz=zone_name, first_name=first_name)
            wrote = bool(rows)
    else:
        if zone_name and plan.get("time_zone") != zone_name:
            plan = database.update_plan(str(user_id), plan["id"], {"time_zone": zone_name}) or plan
        if plan.get("status") == "active":
            plan, wrote = _visit(database, user_id, plan, first_name)
    return {"enabled": True, "plan": view(database, user_id, plan) if plan else None,
            "wrote": wrote}


def begin(database: Any, user_id: str, *, tz: Optional[str], first_name: Optional[str],
          mode: str = "new") -> tuple[Optional[dict], list[dict]]:
    """A new plan, asking: "Hi! A few quick questions before your first
    practice." and "When is your deadline?" (B1, B2). A speaker who already
    has Takes (``mode`` "takes", A2) is asked only the deadline."""
    facts: dict[str, Any] = {"mode": mode, **({"rate_after_first": True} if mode == "takes" else {})}
    plan = database.insert_plan({
        "user_id": str(user_id), "status": "asking", "step": "deadline",
        "time_zone": tz, "facts": facts,
    })
    if not plan:
        return database.get_open_plan(str(user_id)), []
    return plan, _write(database, user_id, plan["id"], _opening(plan, first_name))


def _opening(plan: dict, first_name: Optional[str]) -> list[tuple]:
    first = _facts(plan).get("mode") == "new" and not _facts(plan).get("again")
    rows = [_bot(f"{_hi(first_name)} {P.COPY['hello_first']}", "hello")] if first else []
    return rows + [_bot(P.COPY["deadline_q"], "deadline_q", plan_ask="deadline")]


def _visit(database: Any, user_id: str, plan: dict, first_name: Optional[str]) -> tuple[dict, bool]:
    """An active plan, opened: its end after the deadline; else on a practice
    day, after the first Take, today's hello and one thing, once a day, never
    on a day a Take was already recorded (G4)."""
    today = today_in(plan.get("time_zone"))
    deadline = _deadline(plan)
    if deadline and today > deadline:
        return _end(database, user_id, plan, first_name), True
    takes = _takes(database, user_id)
    done = _done(plan, takes)
    tz = zone(plan.get("time_zone"))
    took_today = any(t.astimezone(tz).date() == today for t in takes)
    if (not deadline or done == 0 or took_today or str(plan.get("hello_on") or "") == today.isoformat()
            or not P.is_practice_day(today, deadline, _days(plan), bool(plan.get("every_day")))):
        return plan, False
    plan = _save(database, user_id, plan, {"hello_on": today.isoformat()})
    return plan, bool(_write(database, user_id, plan["id"],
                             _hello(database, user_id, plan, done, today, first_name)))


def _latest_take(database: Any, user_id: str) -> dict:
    try:
        rows = database.takes.list_user_arc_sessions(str(user_id)) or []
    except Exception:  # noqa: BLE001 -- the bubble keeps its words without the button
        return {}
    spoken = [r for r in rows if r.get("recording_kind") != "read" and not r.get("paired_session_id")]
    return spoken[-1] if spoken else {}


def _hello(database: Any, user_id: str, plan: dict, done: int, today: date,
           first_name: Optional[str]) -> list[tuple]:
    total = int(plan.get("total") or 1)
    n = P.practice_number(done, total)
    level = P.level_name(plan.get("level"))
    hello = f"{_greeting(first_name)} {P.COPY['practice_n'].format(n=n, total=total, level=level)}"
    take = _latest_take(database, user_id)
    one: dict[str, Any] = {"plan_one": True}
    if take.get("arc_id") and isinstance(take.get("take_index"), int):
        one.update({"arc_id": str(take["arc_id"]), "take_index": int(take["take_index"])})
    day = today.isoformat()
    return [_bot(hello, f"hello:{day}", plan_hello=True, day_line=P.fmt_long(today)),
            _bot(P.today_one(plan.get("level")), f"one:{day}", **one)]


# ── the deadline (B2) ──────────────────────────────────────────────────────

def answer_deadline(database: Any, user_id: str, raw: Any, *, tz: Any = None) -> dict:
    """"Pick a date" (an ISO date after today) or "No date yet" (None): the
    speaker's answer, then the voice message's question; a speaker with
    Takes goes on to the calls (A2)."""
    plan = _open(database, user_id)
    _need_step(plan, "deadline")
    zone_name = valid_zone(tz) or plan.get("time_zone")
    today = today_in(zone_name)
    picked = _parse_day(raw) if raw else None
    if raw and (picked is None or picked <= today):
        raise PlanError("INVALID_DATE", "Pick a day after today.")
    deadline = picked or P.given_deadline(today)
    j = P.journey(today, deadline)
    rows = [_me(P.fmt_day(deadline) if picked else P.COPY["no_date"], "deadline_a")]
    if not picked:
        rows.append(_bot(P.COPY["two_months"].format(date=P.fmt_day(deadline)), "two_months"))
    fields = {"deadline": deadline.isoformat(), "deadline_given": not picked,
              "every_day": j.every_day, "total": j.total, "time_zone": zone_name}
    if _facts(plan).get("mode") == "takes":
        fields["step"] = "kickoff"
        plan = _save(database, user_id, plan, fields)
        _diagnose_from_takes(database, user_id, plan)
        rows += _kickoff_rows(plan)
    else:
        fields["step"] = "why"
        plan = _save(database, user_id, plan, fields)
        rows += [_bot(P.COPY["why_1"], "why_1"), _bot(P.COPY["why_2"], "why_2", plan_ask="voice")]
    return {"plan": plan, "messages": _write(database, user_id, plan["id"], rows)}


# ── a voice answer (B3 to B6, I2) ──────────────────────────────────────────

def answer_voice(database: Any, user_id: str, adapter: Any, audio: bytes, *,
                 filename: str, content_type: str, duration_ms: Optional[int],
                 first_name: Optional[str] = None) -> dict:
    """The voice message, a follow-up's answer, or "How did it go?":
    transcribed under the caller's authorization, kept with its recording
    and its readings, shown as the speaker's voice bubble; then Will's next
    words."""
    plan = _open(database, user_id)
    _need_step(plan, "why", "followup", "how_it_went")
    if not audio:
        raise PlanError("EMPTY_AUDIO", "No audio.")
    if len(audio) > MAX_BYTES or (duration_ms or 0) > (MAX_SECONDS + 5) * 1000:
        raise PlanError("TOO_LONG", "Up to five minutes.", 413)
    result = adapter.transcribe_audio(
        audio, filename, usage_surface="plan_answer", usage_user_id=str(user_id),
        usage_session_id=str(plan["id"])) or {}
    raw = (result.get("text") or "").strip()
    if not raw:
        raise PlanError("NO_WORDS", "No words heard.", 422)
    kind, question = _answering(plan)
    duration = duration_ms or int(float(result.get("duration") or 0) * 1000) or None
    readings = _readings(audio, raw, duration, result.get("language"))
    answer = database.insert_plan_answer({
        "plan_id": plan["id"], "user_id": str(user_id), "kind": kind,
        "question": question, "transcript": raw[:20000], "duration_ms": duration,
        "readings": readings})
    if not answer:
        raise PlanError("V2_ERROR", "Failed to keep the answer", 500)
    if not database.insert_plan_answer_audio(answer["id"], str(user_id),
                                             content_type or "audio/webm", audio):
        logger.warning("plan: audio not kept answer=%s", answer.get("id"))
    from services import speaker_memory
    speaker_memory.record(database, str(user_id), "answer", {"question": question, "said": raw})
    rows = [_me(raw, f"answer:{answer['id']}", plan_voice=answer["id"], duration_ms=duration)]
    if plan["step"] == "how_it_went":
        plan, more = _after_how_it_went(database, user_id, plan)
    else:
        plan, more = _next_question(database, user_id, plan, answer, raw)
    return {"plan": plan, "messages": _write(database, user_id, plan["id"], rows + more)}


def _answering(plan: dict) -> tuple[str, str]:
    """Which question this voice answer answers."""
    if plan["step"] == "why":
        return "why", f"{P.COPY['why_1']} {P.COPY['why_2']}"
    if plan["step"] == "how_it_went":
        return "how_it_went", P.COPY["how_did_it_go"]
    asked = list(plan.get("asked") or [])
    last = asked[-1] if asked else {"bank": "key", "text": P.BANK["key"][0]}
    return str(last.get("bank")), str(last.get("text") or "")


def _readings(audio: bytes, transcript: str, duration_ms: Optional[int],
              language: Any) -> dict:
    """What the voice gives today (C1), never shown as numbers. Best-effort:
    a reading that can't be measured is left out."""
    out: dict[str, Any] = {}
    minutes = max((duration_ms or 0) / 60000.0, 1 / 60)
    try:
        from services.audio_metrics import analyze_audio
        m = analyze_audio(audio, transcript=transcript, duration_sec=(duration_ms or 0) / 1000.0) or {}
    except Exception as error:  # noqa: BLE001 -- the answer is kept either way
        logger.warning("plan: readings not taken: %s", error)
        m = {}
    if m.get("wpm"):
        out["wpm"] = float(m["wpm"])
    if m.get("pause_count") is not None:
        out["pauses_per_min"] = round(float(m["pause_count"]) / minutes, 2)
    if m.get("pause_ms"):
        out["mean_pause_ms"] = float(m["pause_ms"])
    f0_mean, f0_sd = m.get("f0_mean"), m.get("f0_sd")
    if f0_mean and f0_sd is not None and int(m.get("pitch_frame_count") or 0) >= P.FLAT_PITCH_FRAMES:
        out["flat_pitch"] = float(f0_sd) / float(f0_mean) < P.FLAT_PITCH_RATIO
    try:
        from services.verbal_markers import count
        tics = count(transcript, language=language).get("tic", {}).get("strict", 0)
        out["fillers_per_min"] = round(float(tics) / minutes, 2)
    except Exception:  # noqa: BLE001 -- the reading is left out
        pass
    return out


def _transcript(database: Any, user_id: str, plan: dict) -> list[tuple[str, str]]:
    deadline = _deadline(plan)
    said = ("No date yet" if plan.get("deadline_given") else
            P.fmt_day(deadline) if deadline else "No date yet")
    lines = [("Will", P.COPY["deadline_q"]), ("Speaker", said)]
    if plan.get("deadline_given") and deadline:
        lines.append(("Will", P.COPY["two_months"].format(date=P.fmt_day(deadline))))
    for a in database.list_plan_answers(str(user_id), plan["id"]):
        if a.get("transcript"):
            lines += [("Will", str(a.get("question") or "")),
                      ("Speaker (voice message)", str(a["transcript"]))]
    return lines


def _turn(database: Any, user_id: str, plan: dict, asked: list[str]) -> Optional[dict]:
    """The AI's reading of what was said and Will's next question, within
    the N150 rules; None when it failed (Will then says the plain words)."""
    from services.llm import chat_complete
    from services.llm_config import SPEC_PLAN_TURN
    from services.processing_authorization import rethrow_processing_authorization
    prompt = P.turn_prompt(deadline=_deadline(plan), deadline_given=bool(plan.get("deadline_given")),
                           transcript=_transcript(database, user_id, plan), asked=asked)
    try:
        result = chat_complete(spec=SPEC_PLAN_TURN, system=prompt,
                               user="Write Will's next message now, as the JSON asked for.",
                               surface="plan_turn", user_id=str(user_id))
    except Exception as error:  # noqa: BLE001 -- the plain template is said instead
        rethrow_processing_authorization(error)
        logger.warning("plan: the AI turn failed user=%s: %s", user_id, error)
        return None
    parsed = getattr(result, "parsed", None) if result else None
    return parsed if isinstance(parsed, dict) else None


def _choose(turn: Optional[dict], asked: list[str], facts: dict, plan: dict) -> Optional[dict]:
    """The next question: the AI's when it fits its template; else the plain
    template, unless the AI said nothing is missing (N150)."""
    if len(asked) >= P.MAX_FOLLOWUPS:
        return None
    nx = (turn or {}).get("next") if turn else None
    q = P.fitted_question(nx, asked)
    if q:
        return q
    if turn is not None and "next" in turn and nx is None and asked:
        return None
    bank = P.next_plain_bank(asked, facts)
    if not bank:
        return None
    return {"bank": bank, "question": P.plain_question(bank, _deadline(plan), bool(plan.get("deadline_given"))),
            "opener": None, "ai": False}


def _next_question(database: Any, user_id: str, plan: dict, answer: dict,
                   said: str) -> tuple[dict, list[tuple]]:
    asked_rows = list(plan.get("asked") or [])
    asked = [str(a.get("bank")) for a in asked_rows]
    facts = _facts(plan)
    if answer["kind"] == "key":
        facts.update({"key_line": said[:300], "key_answer_id": answer["id"]})
    turn = _turn(database, user_id, plan, asked)
    facts = P.clean_facts((turn or {}).get("facts"), facts)
    rows: list[tuple] = []
    if plan["step"] == "why":
        ack = P.fitted_ack((turn or {}).get("ack")) or P.COPY["plain_ack"]
        rows += [_bot(f"{ack} {P.COPY['heard']}", "ack"), _bot(P.COPY["draft"], "draft")]
    q = _choose(turn, asked, facts, plan)
    if q:
        text = P.question_text(q)
        if q["bank"] == "key":
            facts["who"] = P.who_from_key_question(q["question"]) or facts.get("who")
        asked_rows.append({"bank": q["bank"], "text": text, "ai": q["ai"]})
        plan = _save(database, user_id, plan, {"step": "followup", "asked": asked_rows, "facts": facts})
        return plan, rows + [_bot(text, f"q:{q['bank']}", plan_ask="voice")]
    plan = _save(database, user_id, plan, {"step": "stress", "facts": {**facts, "rating_moment": "first"}})
    return plan, rows + _ratings_rows("first")


def _ratings_rows(moment: str) -> list[tuple]:
    intro = [_bot(P.COPY["ratings_intro"], "ratings_intro")] if moment == "first" else []
    return intro + [_scale_row("stress", moment)]


def _scale_row(step: str, moment: str) -> tuple:
    q, lo, hi = STEP_SCALE[step]
    return _bot(P.COPY[q], f"{step}:{moment}", plan_ask="scale",
                plan_scale={"lo": P.COPY[lo], "hi": P.COPY[hi]})


# ── the two ratings (D) ────────────────────────────────────────────────────

def answer_rating(database: Any, user_id: str, value: Any) -> dict:
    """A tap on the 1 to 10 scale: kept for the founder and the coach, never
    shown back (N178); then the next question."""
    plan = _open(database, user_id)
    _need_step(plan, "stress", "ready")
    try:
        v = int(value)
    except (TypeError, ValueError):
        raise PlanError("INVALID_VALUE", "From 1 to 10.")
    if v < 1 or v > 10:
        raise PlanError("INVALID_VALUE", "From 1 to 10.")
    facts = _facts(plan)
    moment = facts.get("rating_moment") or "first"
    q = STEP_SCALE[plan["step"]][0]
    if not database.insert_plan_answer({"plan_id": plan["id"], "user_id": str(user_id),
                                        "kind": plan["step"], "moment": moment,
                                        "question": P.COPY[q], "value": v}):
        raise PlanError("V2_ERROR", "Failed to keep the answer", 500)
    if plan["step"] == "stress":
        plan = _save(database, user_id, plan, {"step": "ready"})
        rows = [_scale_row("ready", moment)]
    elif plan.get("status") == "asking":
        plan = _save(database, user_id, plan, {"step": "kickoff"})
        _diagnose(database, user_id, plan)
        rows = _kickoff_rows(plan)
    else:
        plan = _save(database, user_id, plan, {"step": "done", "facts": {**facts, f"rated_{moment}": True}})
        rows = []
    return {"plan": plan, "messages": _write(database, user_id, plan["id"], rows)}


# ── the level (C) ──────────────────────────────────────────────────────────

def _diagnose(database: Any, user_id: str, plan: dict) -> Optional[str]:
    """The level from the voice message and the key line's answer."""
    answers = database.list_plan_answers(str(user_id), plan["id"])
    why = next((a.get("readings") or {} for a in answers if a.get("kind") == "why"), {})
    key = next((a.get("readings") or {} for a in answers if a.get("kind") == "key"), {})
    readings = dict(why)
    if key.get("wpm"):
        readings["key_wpm"] = key["wpm"]
    return _set_level(database, user_id, plan, P.pick_level(readings))


def _diagnose_from_takes(database: Any, user_id: str, plan: dict) -> Optional[str]:
    """A speaker with Takes (A2): their plan starts from their own best
    moment until their next Takes are read."""
    return _set_level(database, user_id, plan, P.Diagnosis("make_it_yours", "a plan from their Takes"))


def _set_level(database: Any, user_id: str, plan: dict, d: P.Diagnosis) -> Optional[str]:
    if plan.get("level_by") == "coach":
        return plan.get("level")  # a coach's change always wins (C5)
    database.update_plan(str(user_id), plan["id"], {"level": d.level, "level_by": "machine"})
    database.insert_plan_level_event({"plan_id": plan["id"], "user_id": str(user_id),
                                      "level": d.level, "reason": "diagnosis",
                                      "by_who": "machine", "note": d.reason})
    plan["level"] = d.level
    return d.level


# ── the two calls (F) ──────────────────────────────────────────────────────

def _kickoff_rows(plan: dict) -> list[tuple]:
    if (plan.get("calls") or {}).get("kickoff"):
        return _summary_rows(plan)
    return [_bot(P.COPY["kickoff_ask"], "kickoff_ask", plan_ask="book", plan_book="kickoff")]


def _summary_rows(plan: dict) -> list[tuple]:
    return [_bot(P.COPY["summary_ask"], "summary_ask", plan_ask="book", plan_book="summary")]


def call_slots(database: Any, user_id: str, which: str, start: datetime,
               end: datetime) -> list[str]:
    """Open times for a call: the kickoff before the deadline, the summary
    after it (F1, F2), from the booking page's own hours."""
    plan = _open(database, user_id)
    if which not in ("kickoff", "summary"):
        raise PlanError("INVALID_CALL", "Which call?")
    from services import booking
    try:
        slots = booking.open_slots(booking.get_settings(), start.astimezone(timezone.utc),
                                   end.astimezone(timezone.utc))
    except booking.BookingError as e:
        raise PlanError(e.code, str(e), e.status)
    deadline = _deadline(plan)
    tz = zone(plan.get("time_zone"))

    def fits(s: datetime) -> bool:
        day = s.astimezone(tz).date()
        return deadline is None or (day < deadline if which == "kickoff" else day > deadline)

    return [s.isoformat().replace("+00:00", "Z") for s in slots if fits(s)]


def book_call(database: Any, user_id: str, which: str, start: Any, *, tz: Any = None,
              name: str = "", email: str = "") -> dict:
    """Book a call at ``start`` or Skip it (None). Booked as the booking
    page books: no payment now, what is due is remembered (N157)."""
    plan = _open(database, user_id)
    if which not in ("kickoff", "summary"):
        raise PlanError("INVALID_CALL", "Which call?")
    calls = dict(plan.get("calls") or {})
    rows: list[tuple] = []
    if start:
        calls[which] = _book(database, user_id, plan, which, str(start), tz=tz, name=name, email=email)
        local = _parse_dt(calls[which]["start"]).astimezone(zone(plan.get("time_zone")))  # type: ignore[union-attr]
        rows.append(_bot(P.COPY["booked"].format(when=P.fmt_when(local)), f"booked:{which}:{calls[which]['booking_id']}"))
    elif not calls.get(which):
        calls[which] = {"skipped": True}
    plan = _save(database, user_id, plan, {"calls": calls})
    if plan.get("step") == "kickoff" and which == "kickoff":
        plan = _save(database, user_id, plan, {"step": "summary"})
        rows += [] if calls.get("summary") else _summary_rows(plan)
        if calls.get("summary"):
            plan, more = _all_set(database, user_id, plan)
            rows += more
    elif plan.get("step") == "summary" and which == "summary":
        plan, more = _all_set(database, user_id, plan)
        rows += more
    return {"plan": plan, "messages": _write(database, user_id, plan["id"], rows)}


def _book(database: Any, user_id: str, plan: dict, which: str, start: str, *, tz: Any,
          name: str, email: str) -> dict:
    from services import booking
    at = _parse_dt(start)
    deadline = _deadline(plan)
    if at is None:
        raise PlanError("INVALID_TIME", "That time is not valid.")
    day = at.astimezone(zone(plan.get("time_zone"))).date()
    if deadline and ((which == "kickoff" and day >= deadline) or (which == "summary" and day <= deadline)):
        raise PlanError("OUTSIDE_PLAN", "Pick a time that fits the deadline.")
    try:
        settings = booking.get_settings()
        booking.start_checkout(slug=str(settings.get("slug") or ""), user_id=str(user_id),
                               start_iso=at.isoformat(), name=name, email=email,
                               guest_timezone=valid_zone(tz) or plan.get("time_zone") or "UTC",
                               note=f"The plan's {which} call", skip_payment=True)
    except booking.BookingError as e:
        raise PlanError(e.code, str(e), e.status)
    utc = at.astimezone(timezone.utc).isoformat()
    found = database.list_user_bookings(str(user_id), start_at=utc)
    booking_id = str(found[0]["id"]) if found else None
    if not booking_id:
        raise PlanError("V2_ERROR", "The call was not booked", 500)
    return {"booking_id": booking_id, "start": utc}


def _all_set(database: Any, user_id: str, plan: dict) -> tuple[dict, list[tuple]]:
    """"You're all set. Here's your plan." and the card (E1); the plan
    begins now."""
    today = today_in(plan.get("time_zone"))
    deadline = _deadline(plan) or P.given_deadline(today)
    j = P.journey(today, deadline)
    plan = _save(database, user_id, plan, {
        "status": "active", "step": "done", "started_at": _now().isoformat(),
        "total": j.total, "every_day": j.every_day})
    return plan, [_bot(P.COPY["all_set"], "all_set"), _bot("", "card", plan_card=True)]


# ── changing the plan (H, F7) ──────────────────────────────────────────────

def change(database: Any, user_id: str, *, deadline: Any = None, days: Any = None,
           tz: Any = None) -> dict:
    """The deadline (Edit, Change your plan) or the practice days; the plan
    recalculates and Will says what changed."""
    plan = _open(database, user_id)
    rows: list[tuple] = []
    if deadline is not None:
        plan, more = _move_deadline(database, user_id, plan, deadline, tz)
        rows += more
    if days is not None:
        picked = P.clean_days(days)
        if picked is None:
            raise PlanError("INVALID_DAYS", "Pick 3 days.")
        plan = _save(database, user_id, plan, {"practice_days": list(picked)})
        rows.append(_bot(P.COPY["days_done"].format(days=P.days_text(picked, joined=True)),
                         f"days:{'-'.join(map(str, picked))}:{_now().isoformat()}"))
    return {"plan": plan, "messages": _write(database, user_id, plan["id"], rows)}


def _move_deadline(database: Any, user_id: str, plan: dict, raw: Any, tz: Any) -> tuple[dict, list[tuple]]:
    today = today_in(valid_zone(tz) or plan.get("time_zone"))
    new = _parse_day(raw)
    if new is None or new <= today:
        raise PlanError("INVALID_DATE", "Pick a day after today.")
    calls = _calls(database, user_id, plan)
    tzi = zone(plan.get("time_zone"))
    kick, summ = calls.get("kickoff"), calls.get("summary")
    if kick and _parse_dt(kick["starts_at"]).astimezone(tzi).date() >= new:  # type: ignore[union-attr]
        raise PlanError("OUTSIDE_PLAN", "The deadline stays after the kickoff call.")
    if summ and _parse_dt(summ["starts_at"]).astimezone(tzi).date() <= new:  # type: ignore[union-attr]
        raise PlanError("OUTSIDE_PLAN", "The deadline stays before the summary call.")
    was_daily = bool(plan.get("every_day"))
    j = P.journey(today, new)
    done = _done(plan, _takes(database, user_id)) if plan.get("status") == "active" else 0
    plan = _save(database, user_id, plan, {"deadline": new.isoformat(), "deadline_given": False,
                                           "every_day": j.every_day, "total": done + j.total})
    rows = [_bot(P.COPY["runs_to"].format(date=P.fmt_day(new)), f"runs_to:{new.isoformat()}:{_now().isoformat()}")]
    if j.every_day and not was_daily:
        rows.append(_bot(P.COPY["every_day"], f"every_day:{new.isoformat()}:{_now().isoformat()}"))
    return plan, rows


def ask_coach(database: Any, user_id: str) -> dict:
    """"Ask your coach": the coach is told; the level stays theirs (H1)."""
    plan = _open(database, user_id)
    database.insert_plan_level_event({"plan_id": plan["id"], "user_id": str(user_id),
                                      "level": plan.get("level") or "make_it_yours",
                                      "reason": "ask_coach", "by_who": "speaker"})
    rows = [_bot(P.COPY["told_coach"], f"told_coach:{_now().isoformat()}")]
    return {"plan": plan, "messages": _write(database, user_id, plan["id"], rows)}


# ── after a Take's walk (G13, D1, A2, A3) ──────────────────────────────────

def after_take(database: Any, user_id: str, *, first_name: Optional[str] = None) -> list[dict]:
    """Once per Take, where its walk's summary is written. Best-effort:
    never raises, never in the way of the Take."""
    try:
        if not enabled(database, user_id):
            return []
        plan = database.get_open_plan(str(user_id))
        if plan is None:
            if database.get_latest_plan(str(user_id)) is None:
                return begin(database, user_id, tz=None, first_name=first_name, mode="takes")[1]
            return []
        if plan.get("status") == "asking" and _facts(plan).get("wait_take"):
            plan = _save(database, user_id, plan, {"facts": {**_facts(plan), "wait_take": False}})
            return _write(database, user_id, plan["id"], _opening(plan, first_name))
        if plan.get("status") == "active":
            return _after_active_take(database, user_id, plan)
    except Exception as error:  # noqa: BLE001 -- the Take and its walk stand either way
        logger.warning("plan: after the Take not written user=%s: %s", user_id, error, exc_info=True)
    return []


def _after_active_take(database: Any, user_id: str, plan: dict) -> list[dict]:
    facts = _facts(plan)
    takes = _takes(database, user_id)
    done = _done(plan, takes)
    today = today_in(plan.get("time_zone"))
    deadline = _deadline(plan)
    rows: list[tuple] = []
    fields: dict[str, Any] = {}
    practice_day = bool(deadline) and P.is_practice_day(today, deadline, _days(plan),  # type: ignore[arg-type]
                                                       bool(plan.get("every_day")))
    if practice_day and str(plan.get("done_on") or "") != today.isoformat():
        rows += [_bot(P.COPY["fifteen_1"], f"fifteen:{today.isoformat()}"),
                 _bot(P.COPY["fifteen_2"], f"fifteen2:{today.isoformat()}")]
        fields["done_on"] = today.isoformat()
    moment = _ratings_due(plan, facts, done)
    if moment:
        fields.update({"step": "stress", "facts": {**facts, "rating_moment": moment}})
        rows += _ratings_rows(moment)
    if fields:
        plan = _save(database, user_id, plan, fields)
    return _write(database, user_id, plan["id"], rows)


def _ratings_due(plan: dict, facts: dict, done: int) -> Optional[str]:
    """The ratings after a Take: the last practice's (D1), and a plan made
    from Takes or "Keep practising" gets its first ones after its first
    Take (I2)."""
    total = int(plan.get("total") or 0)
    if facts.get("rate_after_first") and done == 1 and not facts.get("rated_first"):
        return "first"
    if total and done >= total and not facts.get("rated_last"):
        return "last"
    return None


# ── the plan's end (I) ─────────────────────────────────────────────────────

def _end(database: Any, user_id: str, plan: dict, first_name: Optional[str]) -> dict:
    deadline = _deadline(plan)
    plan = _save(database, user_id, plan, {"status": "ending", "step": "how_it_went"})
    was = P.COPY["deadline_was"].format(date=P.fmt_day(deadline)) if deadline else ""
    _write(database, user_id, plan["id"], [
        _bot(f"{_greeting(first_name)} {was}".strip(), "deadline_was",
             day_line=P.fmt_long(today_in(plan.get("time_zone")))),
        _bot(P.COPY["how_did_it_go"], "how_did_it_go", plan_ask="voice"),
    ])
    return plan


def _after_how_it_went(database: Any, user_id: str, plan: dict) -> tuple[dict, list[tuple]]:
    plan = _save(database, user_id, plan, {"step": "whats_next"})
    return plan, [_bot(P.COPY["thanks_told"], "thanks_told"),
                  _bot("", "summary_card", plan_summary_call=True),
                  _bot(P.COPY["whats_next"], "whats_next", plan_ask="next")]


def next_plan(database: Any, user_id: str, choice: str, *, tz: Any = None,
              first_name: Optional[str] = None) -> dict:
    """"Keep practising": a new two-month plan from the next level, no
    questions, its first ratings after its first Take. "I have a new event":
    the questions again, after the next Take (N178)."""
    plan = _open(database, user_id)
    _need_step(plan, "whats_next")
    if choice not in ("keep_practising", "new_event"):
        raise PlanError("INVALID_CHOICE", "Unknown answer.")
    label = P.COPY["keep_practising"] if choice == "keep_practising" else P.COPY["new_event"]
    _write(database, user_id, plan["id"], [_me(label, f"next:{choice}")])
    _save(database, user_id, plan, {"status": "ended", "ended_at": _now().isoformat(), "step": "done"})
    zone_name = valid_zone(tz) or plan.get("time_zone")
    if choice == "new_event":
        return {"plan": _waiting_plan(database, user_id, zone_name), "messages": []}
    return _keep_practising(database, user_id, plan, zone_name)


def _waiting_plan(database: Any, user_id: str, zone_name: Optional[str]) -> Optional[dict]:
    """A new event's plan: its questions come after the next Take (N178)."""
    return database.insert_plan({"user_id": str(user_id), "status": "asking", "step": "deadline",
                                 "time_zone": zone_name,
                                 "facts": {"mode": "new", "again": True, "wait_take": True}})


def new_event(database: Any, user_id: str, *, tz: Any = None) -> dict:
    """"I have a new event" in Change your plan (H1): the plan stays in the
    history, and the questions for a new one come after the next Take."""
    plan = _open(database, user_id)
    rows = [_me(P.COPY["new_event"], f"new_event:{_now().isoformat()}")]
    written = _write(database, user_id, plan["id"], rows)
    _save(database, user_id, plan, {"status": "replaced", "ended_at": _now().isoformat()})
    fresh = _waiting_plan(database, user_id, valid_zone(tz) or plan.get("time_zone"))
    return {"plan": fresh, "messages": written}


def _keep_practising(database: Any, user_id: str, old: dict, zone_name: Optional[str]) -> dict:
    today = today_in(zone_name)
    deadline = P.given_deadline(today)
    j = P.journey(today, deadline)
    order = list(P.LEVELS)
    level = old.get("level") or "make_it_yours"
    nxt = order[(order.index(level) + 1) % len(order)] if level in order else "make_it_yours"
    keep = {k: v for k, v in _facts(old).items() if k in ("key_line", "key_answer_id", "who", "event", "topic")}
    fresh = database.insert_plan({
        "user_id": str(user_id), "status": "active", "step": "done", "time_zone": zone_name,
        "deadline": deadline.isoformat(), "deadline_given": True, "every_day": j.every_day,
        "total": j.total, "practice_days": list(_days(old)), "level": nxt, "level_by": "machine",
        "started_at": _now().isoformat(),
        "facts": {**keep, "mode": "keep", "rate_after_first": True}})
    if not fresh:
        raise PlanError("V2_ERROR", "Failed to keep the plan", 500)
    database.insert_plan_level_event({"plan_id": fresh["id"], "user_id": str(user_id), "level": nxt,
                                      "reason": "time", "by_who": "machine",
                                      "note": "Keep practising: the next level"})
    rows = [_bot(P.COPY["next_plan"], "next_plan"), _bot("", "card", plan_card=True)]
    return {"plan": fresh, "messages": _write(database, user_id, fresh["id"], rows)}


# ── a voice answer, played back ────────────────────────────────────────────

def answer_audio(database: Any, user_id: str, answer_id: str) -> dict:
    if not enabled(database, user_id):
        raise PlanError("NOT_FOUND", "Not found.", 404)
    got = database.get_plan_answer_audio(str(user_id), str(answer_id))
    if not got:
        raise PlanError("NOT_FOUND", "Not found.", 404)
    return got
