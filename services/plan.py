"""The plan: from the first questions to the deadline (frontend
docs/flows/the-plan.md; N129 onward, built one to one with the prototype,
N203; ring row ``plan`` at ring 5, N204).

This module is the plan's own logic, kept free of the database so it can be
read and tested on its own: the journey a deadline gives, the levels and
their signed lines, the order of the follow-up questions, the check on the
AI's words, and the dates as the chat writes them. ``services/plan_flow.py``
holds the conversation in the Lounge and the database calls.

Nothing here is a score or a verdict shown to the speaker (Never 1): a level
is named as the next step of excellence, and the readings that choose it are
never shown as numbers.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Mapping, Optional, Sequence

FEATURE = "plan"

# ── the signed words (Never 4; frontend the-plan.md §1 K) ──────────────────

#: The five levels, each named as the next step of excellence (N132, N134).
LEVELS: dict[str, str] = {
    "say_once": "Say it once, and it lands",
    "key_line": "Let your key line land",
    "pauses": "Pauses that hold the room",
    "voice_moves": "A voice that moves",
    "make_it_yours": "Make it yours",
}
#: The levels whose walk has the pace game (the tempo step, N162, N163).
PACE_LEVELS = ("key_line", "pauses")

#: A practice day's one thing, by level (N167, N173).
TODAY_ONE: dict[str, str] = {
    "key_line": "Today, one thing: say your key line a little slower than the rest. You've got this 💪",
    "pauses": "Today, one thing: a short pause between your ideas. You've got this 💪",
    "say_once": "Today, one thing: say each idea once, without the extras. You've got this 💪",
    "voice_moves": "Today, one thing: lean on your numbers. You've got this 💪",
    "make_it_yours": "Today, one thing: say it like your best moment. You've got this 💪",
}

COPY = {
    "hello_first": "A few quick questions before your first practice.",
    "deadline_q": "When is your deadline?",
    "pick_date": "Pick a date",
    "no_date": "No date yet",
    "two_months": "That's fine. Let's give it two months, until {date}.",
    "why_1": "I assume you came here to practise for some important event in your life.",
    "why_2": "Please tell me, why does it matter and what is it about?",
    "record": "Record your answer",
    "heard": "I can already hear your main vocal cues and verbal habits.",
    "draft": "Let me draft your plan. A few more questions first.",
    "plain_ack": "Thank you. Now I can hear you talking about your goal and why it matters.",
    "ratings_intro": "Two quick taps before your plan.",
    "stress_q": "How stressed do you feel about it right now?",
    "ready_q": "How ready do you feel for it right now?",
    "stress_lo": "Calm",
    "stress_hi": "Very stressed",
    "ready_lo": "Not ready",
    "ready_hi": "Fully ready",
    "kickoff_ask": ("Before I show you your plan, pick a time for a 15-minute call with "
                    "your coach. It's your kickoff call."),
    "summary_ask": ("Would you also like to book your summary call? It's after your "
                    "deadline, to look back and plan what's next."),
    "booked": "Booked: {when}.",
    "all_set": "You're all set. Here's your plan.",
    "runs_to": "Done. Your plan now runs to {date}.",
    "every_day": "Your deadline is close, so you practise every day.",
    "days_done": "Done. You'll practise on {days}.",
    "told_coach": "I've told your coach. You can talk it over on your next call.",
    "practice_n": "Today is practice {n} of {total}: {level}.",
    "done_next": "{n} of {total} practices done. Next: {day}.",
    "fifteen_1": "That's your 15 minutes for today.",
    "fifteen_2": "Now go and live it, away from the phone.",
    "deadline_was": "Your deadline was {date}.",
    "how_did_it_go": "How did it go? Tell me in a voice message.",
    "thanks_told": "Thank you for telling me.",
    "whats_next": "What's next?",
    "keep_practising": "Keep practising",
    "new_event": "I have a new event",
    "next_plan": "Here's your next plan.",
    "is_this_for": "Is this for {date}?",
    "yes": "Yes",
    "no": "No",
    # The plan's own yes (founder 2026-10-27, N211: "approved as drawn", on
    # the prototype https://claude.ai/artifact/3GtUo7eVdf9SAhZQCDsTR7): asked
    # once, before the personal questions. Will's words, then the two taps.
    # "Settings", the page's name since N196 (founder 2026-10-28, N249).
    "consent_ask": ("A few of my questions are personal: how stressed and how ready you feel, "
                    "what worries you, and how you feel before each Take. I only ask with your "
                    "yes. Your coach and I use your answers to shape your plan. You can turn "
                    "this off in Settings."),
    "consent_yes": "Yes, ask me",
    "consent_no": "Not now",
    # A voice answer with no speech in it, and a correction taken (founder
    # 2026-10-29, N262 items 2 and 3: "Will: didn't quite catch it", "Will
    # hears it and agrees").
    "not_heard": "Sorry, I didn't quite catch that. Could you say it again?",
    "put_right": "Got it, thank you for putting me right.",
}

#: What the transcriber writes when it hears no words in a clip (N274): its
#: stock lines, from the videos it learnt on. A voice answer that is only
#: these is "not heard"; inside a longer answer they are the speaker's own.
NOT_WORDS = frozenset({
    "you", "bye", "bye bye", "thank you", "thanks", "thank you very much",
    "thank you so much", "thank you for watching", "thanks for watching",
    "thank you so much for watching", "thank you for listening",
    "thanks for listening", "please subscribe", "like and subscribe",
    "subscribe to my channel", "see you next time", "see you in the next video",
})


def heard_nothing(text: str) -> bool:
    """Is the transcript only the transcriber's stock lines (N274)?"""
    t = text.lower()
    if "amara.org" in t:  # "Subtitles by the Amara.org community", in any language
        return True
    parts = [" ".join(re.sub(r"[^\w' ]+", " ", p).split()) for p in re.split(r"[.!?,\n]+", t)]
    parts = [p for p in parts if p]
    return bool(parts) and all(p in NOT_WORDS for p in parts)


#: Why this line (N154): the sentence under "Why this line?", by level.
WHY_LINE = {
    "key_line": ("It's the sentence you want {who} to remember, and you said it a little "
                 "faster than the rest. Give it more room, and it lands."),
    "pauses": ("It's the sentence you want {who} to remember, and you said it with hardly "
               "a pause around it. A pause before it, and it stays with them."),
    "other": "It's the sentence you want {who} to remember. Give it more room, and it lands.",
}

# ── the follow-up questions (N138, N139, N140 item 9, N145, N150) ──────────

#: Each bank: (the plain template, the anchor words a fitted question must
#: keep). The key line is always first; then the first of BANK_ORDER this
#: speaker hasn't answered. At most three follow-ups.
BANK: dict[str, tuple[Optional[str], str]] = {
    "key": ("If your audience remembers one sentence from you, what is it? "
            "Say it the way you'll say it.", "remembers one sentence from you"),
    "audience": (None, "Who will be in the room"),
    "length": ("How long will you speak, and will you have slides?", "How long will you speak"),
    "worry": ("What worries you most about it?", "worries you most"),
    "experience": ("Have you given a talk like this before? How did it go?", "like this before"),
    "success": ("What has to happen for you to call it a success?", "call it a success"),
    "opening": ("How will you open? Say your first sentence.", "How will you open"),
}
BANK_ORDER = ("audience", "length", "worry", "experience", "success", "opening")
MAX_FOLLOWUPS = 3
FACT_KEYS = ("event", "why", "topic", "audience", "length", "slides", "key_line",
             "worry", "experience", "success", "opening", "who")

MONTHS = ("January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December")
DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
DEFAULT_DAYS = (1, 3, 5)  # Mon, Wed, Fri, as 0 = Sunday … 6 = Saturday
NO_DATE_DAYS = 56          # "two months": eight weeks (N135, N140)
EVERY_DAY_WITHIN = 14      # two weeks or less: every day (G1)


# ── dates, as the chat writes them ─────────────────────────────────────────

def _js_weekday(d: date) -> int:
    """0 = Sunday … 6 = Saturday, as the app and the stored days count."""
    return (d.weekday() + 1) % 7


def fmt_day(d: date) -> str:
    """"14 November"."""
    return f"{d.day} {MONTHS[d.month - 1]}"


def fmt_long(d: date) -> str:
    """"Monday 26 October" (the day line, N169)."""
    return f"{DAYS[d.weekday()]} {d.day} {MONTHS[d.month - 1]}"


def fmt_short(d: date) -> str:
    """"Sat 14 Nov" (the plan's list, N164)."""
    return f"{DAYS[d.weekday()][:3]} {d.day} {MONTHS[d.month - 1][:3]}"


def fmt_when(at: datetime) -> str:
    """"Tuesday 27 October, 10:00" (Booked: …, N173)."""
    return f"{fmt_long(at.date())}, {at:%H:%M}"


def fmt_when_short(at: datetime) -> str:
    """"Tue 27 Oct, 10:00" (a booked call in the plan's list)."""
    return f"{fmt_short(at.date())}, {at:%H:%M}"


def days_text(days: Sequence[int], *, joined: bool = False) -> str:
    """"Mon, Wed, Fri", or "Mon, Wed and Fri" for "You'll practise on …"."""
    order = (1, 2, 3, 4, 5, 6, 0)
    names = [DAYS[(d - 1) % 7][:3] for d in order if d in set(days)]
    if joined and len(names) > 1:
        return f"{', '.join(names[:-1])} and {names[-1]}"
    return ", ".join(names)


def clean_days(raw: Any) -> Optional[tuple[int, ...]]:
    """Three distinct weekdays (0 = Sunday … 6 = Saturday), or None."""
    if not isinstance(raw, (list, tuple)):
        return None
    try:
        days = tuple(sorted({int(x) for x in raw}))
    except (TypeError, ValueError):
        return None
    if len(days) != 3 or any(d < 0 or d > 6 for d in days):
        return None
    return days


# ── the journey (G1, N135, N140) ───────────────────────────────────────────

@dataclass(frozen=True)
class Journey:
    every_day: bool
    weeks: int
    total: int


def given_deadline(today: date) -> date:
    """No date yet gives a date two months away (N135)."""
    return today + timedelta(days=NO_DATE_DAYS)


def journey(today: date, deadline: date) -> Journey:
    """Two weeks or less: every day; otherwise three practices a week. The
    total counts practices from today; it is what "practice n of total"
    reads (one practice is one Take with its walk, N131)."""
    days = max(1, (deadline - today).days)
    weeks = max(1, math.ceil(days / 7))
    if days <= EVERY_DAY_WITHIN:
        return Journey(every_day=True, weeks=weeks, total=days)
    return Journey(every_day=False, weeks=weeks, total=weeks * 3)


def is_practice_day(d: date, deadline: date, days: Sequence[int], every_day: bool) -> bool:
    """A day before the deadline that is one of the plan's days."""
    if d >= deadline:
        return False
    return every_day or _js_weekday(d) in set(days)


def next_practice_day(after: date, deadline: date, days: Sequence[int],
                      every_day: bool) -> Optional[date]:
    """The plan's next practice day after ``after``, before the deadline."""
    d = after + timedelta(days=1)
    while d < deadline:
        if every_day or _js_weekday(d) in set(days):
            return d
        d += timedelta(days=1)
    return None


def next_day_text(after: date, deadline: date, days: Sequence[int], every_day: bool) -> Optional[str]:
    """"Next: Wednesday." reads the weekday; every day reads "tomorrow"."""
    nxt = next_practice_day(after, deadline, days, every_day)
    if nxt is None:
        return None
    if nxt == after + timedelta(days=1):
        return "tomorrow"
    return DAYS[nxt.weekday()]


def practice_number(takes_done: int, total: int) -> int:
    """"practice n of total": the Takes done plus one, never past the total."""
    return max(1, min(total, takes_done + 1))


# ── the level (C, N132 to N134, N145) ──────────────────────────────────────

#: How much faster the key line must be than the rest to name it (8 %).
KEY_LINE_FASTER = 1.08
#: Fewer pauses than this a minute, or shorter than this on average.
FEW_PAUSES_PER_MIN = 4.0
SHORT_PAUSE_MS = 350
#: Filler words a minute ("um" and "uh" don't count, N134).
MANY_FILLERS_PER_MIN = 4.0
#: A flat voice: pitch varying less than this share of its mean, measured
#: on at least FLAT_PITCH_FRAMES voiced frames (as services.acoustic_cues).
FLAT_PITCH_RATIO = 0.06
FLAT_PITCH_FRAMES = 30


@dataclass(frozen=True)
class Diagnosis:
    level: str
    reason: str


#: The levels a check picks, strongest first; "Make it yours" is what is
#: left when none fires (C3).
PICK_ORDER = ("key_line", "pauses", "say_once", "voice_moves")
PICK_REASONS = {
    "key_line": "the key line came out faster than the rest",
    "pauses": "few, short pauses",
    "say_once": "filler and repeated words",
    "voice_moves": "a narrow pitch range",
}


def fires(level: str, readings: Mapping[str, Any]) -> Optional[bool]:
    """Does the check that picks ``level`` fire on these readings? None when
    the reading it needs was not measured, so nothing is guessed.

    ``readings`` holds ``wpm`` (all the words), ``key_wpm`` (the key line),
    ``pauses_per_min``, ``mean_pause_ms``, ``fillers_per_min`` (without "um"
    and "uh"), ``flat_pitch``; a reading that wasn't measured is absent."""
    if level == "key_line":
        wpm, key_wpm = _num(readings.get("wpm")), _num(readings.get("key_wpm"))
        return key_wpm >= wpm * KEY_LINE_FASTER if wpm and key_wpm else None
    if level == "pauses":
        ppm, mean_ms = _num(readings.get("pauses_per_min")), _num(readings.get("mean_pause_ms"))
        if ppm is None and mean_ms is None:
            return None
        return (ppm is not None and ppm < FEW_PAUSES_PER_MIN) or (
            mean_ms is not None and 0 < mean_ms < SHORT_PAUSE_MS)
    if level == "say_once":
        fpm = _num(readings.get("fillers_per_min"))
        return None if fpm is None else fpm >= MANY_FILLERS_PER_MIN
    if level == "voice_moves":
        flat = readings.get("flat_pitch")
        return flat if isinstance(flat, bool) else None
    return None


def pick_level(readings: Mapping[str, Any]) -> Diagnosis:
    """The level from what was measured today, strongest first (C2, C3):
    the first check in ``PICK_ORDER`` that fires. With nothing measured, or
    nothing past its line, "Make it yours", never a guess."""
    for level in PICK_ORDER:
        if fires(level, readings):
            return Diagnosis(level, PICK_REASONS[level])
    return Diagnosis("make_it_yours", "nothing stood out more than the speaker's own best moment")


# ── a level on each Take (G10; N134 items 3 and 4, N209) ──────────────────

#: Two Takes in a row that reach the level start the next one.
REACH_IN_A_ROW = 2
#: Three Takes on a level without moving are noted for the coach's queue.
STUCK_AFTER = 3


def reached(level: Optional[str], readings: Mapping[str, Any]) -> Optional[bool]:
    """A Take reaches its level when the check that picked the level no
    longer fires on it (N209 item 1). None when it can't be read, and for
    "Make it yours", which stays."""
    if level not in PICK_ORDER:
        return None
    on = fires(level, readings)  # type: ignore[arg-type]
    return None if on is None else not on


def next_level(readings: Mapping[str, Any], had: Sequence[str]) -> str:
    """The next thing heard, strongest first, skipping the levels this plan
    already had; "Make it yours" when no other check fires (N209 item 3)."""
    for level in PICK_ORDER:
        if level not in had and fires(level, readings):
            return level
    return "make_it_yours"


_WORD = re.compile(r"[a-z']+")
#: The share of the key line's words a clip must hold to be the one that
#: says it.
KEY_LINE_MATCH = 0.6


def key_line_at(texts: Sequence[Any], key_line: Any) -> Optional[int]:
    """Which clip of a Take says the key line: the one holding most of its
    words, at least ``KEY_LINE_MATCH`` of them; None when none does, or when
    the key line has fewer than three words to look for."""
    want = {w for w in _WORD.findall(str(key_line or "").lower()) if len(w) > 2}
    if len(want) < 3:
        return None
    best, at = 0.0, None
    for i, text in enumerate(texts):
        share = len(want & set(_WORD.findall(str(text or "").lower()))) / len(want)
        if share > best:
            best, at = share, i
    return at if best >= KEY_LINE_MATCH else None


def level_days(start: date, deadline: date) -> Optional[int]:
    """The longest a level runs, by the plan's length (the treatment
    picker's journey table, N134): two weeks or less, one level for the
    whole plan (None); up to six weeks, a week; longer, two weeks."""
    days = (deadline - start).days
    if days <= EVERY_DAY_WITHIN:
        return None
    return 7 if days <= 42 else 14


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def level_name(level: Optional[str]) -> str:
    return LEVELS.get(level or "", LEVELS["make_it_yours"])


def today_one(level: Optional[str]) -> str:
    return TODAY_ONE.get(level or "", TODAY_ONE["make_it_yours"])


def why_line(level: Optional[str], who: Optional[str]) -> str:
    template = WHY_LINE.get(level or "", WHY_LINE["other"])
    who = (who or "").strip()
    return template.format(who="them" if not who or _SLOT.search(who) else who)


# ── the questions (N138, N139, N145, N150) ─────────────────────────────────

def audience_question(deadline: Optional[date], deadline_given: bool) -> str:
    if deadline and not deadline_given:
        return f"Who will be in the room on {fmt_day(deadline)}, and how many?"
    return "Who will be in the room, and how many?"


def plain_question(bank: str, deadline: Optional[date], deadline_given: bool) -> str:
    if bank == "audience":
        return audience_question(deadline, deadline_given)
    return BANK[bank][0] or ""


def next_plain_bank(asked: Sequence[str], facts: Mapping[str, Any],
                    skip: Sequence[str] = ()) -> Optional[str]:
    """The key line first; then the first bank not asked whose fact isn't
    known yet (a named worry still gets its question, N150). ``skip`` names
    banks not to ask at all: the personal one, without the speaker's yes
    (N211)."""
    if len(asked) >= MAX_FOLLOWUPS:
        return None
    if "key" not in asked:
        return "key"
    for bank in BANK_ORDER:
        if bank in asked or bank in skip:
            continue
        if bank == "worry" or not facts.get(bank):
            return bank
    return None


_BAD = re.compile(r"[!%{}]|\d+\s*/\s*10")
#: A template's slot the AI left unfilled ("{who they will speak to}").
_SLOT = re.compile(r"[{}]")


def fitted_question(nx: Any, asked: Sequence[str], skip: Sequence[str] = ()) -> Optional[dict]:
    """The AI's next question, kept only when it matches its signed
    template: a known bank not asked yet, the key line first, its anchor
    words kept, short, no "!" or "%", and no slot left unfilled ("{…}").
    Otherwise None, and Will says the plain template."""
    if not isinstance(nx, Mapping):
        return None
    bank, question = nx.get("bank"), nx.get("question")
    if bank not in BANK or bank in asked or bank in skip or not isinstance(question, str):
        return None
    if not asked and bank != "key":
        return None
    q = question.strip()
    if not q or len(q) > 220 or BANK[bank][1] not in q or _BAD.search(q):
        return None
    opener = nx.get("opener")
    op = None
    if bank != "key" and isinstance(opener, str):
        o = opener.strip()
        if o and len(o) <= 110 and not _BAD.search(o):
            op = o
    return {"bank": bank, "question": q, "opener": op, "ai": True}


def fitted_ack(ack: Any) -> Optional[str]:
    """Will's reply naming the event, kept only in its signed shape."""
    if not isinstance(ack, str):
        return None
    a = ack.strip()
    if a.startswith("Thank you.") and len(a) <= 260 and not _BAD.search(a):
        return a
    return None


def fitted_correction(raw: Any, answered: Sequence[str]) -> Optional[dict]:
    """A correction the AI heard (N262 item 3): what it corrects, one of the
    answers already given, and Will's one sentence saying back what he now
    has, kept only within N150's rules; else None, and the answer counts as
    an answer."""
    if not isinstance(raw, Mapping):
        return None
    of, back = raw.get("of"), raw.get("said_back")
    if of not in answered or not isinstance(back, str):
        return None
    b = back.strip()
    if not b or len(b) > 260 or _BAD.search(b) or b.startswith("Thank you"):
        return None
    return {"of": str(of), "said_back": b}


def clean_facts(raw: Any, known: Optional[Mapping[str, Any]] = None) -> dict:
    """The facts the AI read, short strings or nothing, over what was known."""
    out = {k: v for k, v in dict(known or {}).items() if k in FACT_KEYS and v}
    if isinstance(raw, Mapping):
        for k in FACT_KEYS:
            v = raw.get(k)
            if isinstance(v, str) and v.strip() and not _SLOT.search(v):
                out[k] = v.strip()[:300]
    return out


def who_from_key_question(question: str) -> Optional[str]:
    """"If the board remembers one sentence …" → "the board"."""
    m = re.match(r"^If (.+?) remembers one sentence from you", question.strip())
    if not m:
        return None
    who = m.group(1).strip()
    return None if who.lower() == "your audience" or _SLOT.search(who) else who


def question_text(q: Mapping[str, Any]) -> str:
    opener = q.get("opener")
    return f"{opener} {q['question']}" if opener else str(q["question"])


def turn_prompt(*, deadline: Optional[date], deadline_given: bool,
                transcript: Sequence[tuple[str, str]], asked: Sequence[str]) -> str:
    """The AI's brief for Will's next message (N150): the prototype's rules,
    word for word. ``transcript`` is (who, text) pairs in order. Once Will
    has asked a follow-up, the speaker's last message may be a correction
    instead of an answer (N262 item 3)."""
    n = len(asked)
    lines = [f"{who}: {text}" for who, text in transcript]
    date_bit = (f", its date ({fmt_day(deadline)})" if deadline and not deadline_given else "")
    return "\n".join([
        "You write the next chat message for Will, the coach inside WillpowerLab, an app where "
        "people practise speaking for an important event in their life. A new speaker is "
        "answering Will's first questions by voice; the transcript so far is below. Will must "
        "show it listened: use what this speaker said.",
        "",
        "Fixed rules, never broken:",
        "1. Only the speaker's own words and facts. Never add a detail they did not say.",
        "2. No judgement of them or of how they spoke: no praise and no criticism (not \"great\", "
        "\"lovely\", \"powerful\", \"nervous\").",
        "3. No numbers about them: no scores, ratings or percentages. A date or a length they "
        "said is fine.",
        "4. No promises (not \"you'll nail it\", \"we'll get you there\").",
        "5. Nothing about fixing them or about a problem of theirs.",
        "6. Short, plain and warm. British spelling. No emoji, no exclamation marks.",
        "7. Speak to them as \"you\": their \"my sister\" becomes \"your sister\".",
        "",
        "The question bank. Each question is a signed template: copy it word for word. You may "
        "only fill a {slot} with the speaker's own words, and leave out a part that cannot apply "
        "to their event (a toast has no slides, so: \"How long will you speak?\"). Never write "
        "any other question.",
        "- key: \"If {who they will speak to} remembers one sentence from you, what is it? "
        "Say it the way you'll say it.\"",
        f"- audience: \"{audience_question(deadline, deadline_given)}\"",
        "- length: \"How long will you speak, and will you have slides?\"",
        "- worry: \"What worries you most about it?\" If they already named a worry, the opener "
        "names it in their words, for example opener \"You said you don't want to cry halfway "
        "through.\" and question \"What worries you most about it?\"",
        "- experience: \"Have you given a talk like this before? How did it go?\"",
        "- success: \"What has to happen for you to call it a success?\"",
        "- opening: \"How will you open? Say your first sentence.\"",
        "",
        "Which one next: \"key\" first, always. After it, the first of audience, length, worry, "
        "experience, success, opening that the transcript has not answered yet (a worry they "
        "named but Will has not asked about still counts as not asked). At most 3 questions in "
        f"all. Will has asked {n} so far{f' ({chr(44).join(asked)})' if n else ''}. If nothing "
        "is missing, \"next\" is null.",
        "A question other than key may have an opener: a few words (at most 12) naming what the "
        "speaker just said, in their words and with no judgement, for example \"Five board "
        "members and your CEO.\" Otherwise the opener is null.",
        (f"Also write \"ack\": one sentence that starts \"Thank you.\" and names their event"
         f"{date_bit} and why it matters to them, in their words, speaking to them as \"you\". "
         "Example: \"Thank you. On 14 November you'll ask the board for two more hires, and "
         "your team's funding for next year rides on it.\""
         + ("" if date_bit else " They have no event date, so leave the date out.")
         + " If they gave no reason, name the event only.")
        if n == 0 else "Leave \"ack\" out.",
        *([] if n == 0 else [
            "",
            "A correction: the speaker's last voice message may not answer Will's last question "
            "but put Will right about something said before (\"No, that's not what I meant\", "
            "\"I said it wrong\", a fact said again differently). Then \"correction\" is "
            "{\"of\": what it corrects, \"said_back\": one sentence}. \"of\" is \"why\" for "
            "their event and why it matters, else the bank of the question whose answer it "
            f"corrects, one of: {', '.join(['why', *asked[:-1]])}. \"said_back\" says back what "
            "Will now has, in their words, speaking to them as \"you\", under the fixed rules; "
            "it does not start \"Thank you\". The facts then follow the correction. When the last "
            "message answers the question, even partly, or you are not sure, \"correction\" is null.",
        ]),
        "",
        "Transcript:",
        *lines,
        "",
        "Reply with only this JSON: {\"ack\": string|null, \"facts\": {\"event\", \"why\", "
        "\"topic\", \"audience\", \"length\", \"slides\", \"key_line\", \"worry\", "
        "\"experience\", \"success\", \"opening\", \"who\": string|null}, \"next\": {\"bank\": "
        "string, \"opener\": string|null, \"question\": string} | null"
        + ("" if n == 0 else ", \"correction\": {\"of\": string, \"said_back\": string} | null")
        + "}",
        "facts are what the speaker has said so far, short and in their words; null when not "
        "said. \"who\" is who they will speak to, as the key question names them (\"the "
        "board\", \"your sister\").",
    ])
