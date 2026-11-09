"""The speaking way in, while Take 1 is processed and right after it
(N453, N572's tree, N573's choice, N564, N590, N592). Home doc: frontend
docs/flows/the-plan.md §2 ("The first Take is the onboarding").

The first Take is recorded (N401, N462). While it is processed, Will's chat
(the speaking chat, Artur's, N590) carries one beat at a time, each a row
of the one Lounge thread written through ``plan_flow._write`` with
``metadata.way_in`` naming the beat:

  opener      "While your feedback is being prepared, check what I heard."
  profile     "Here's how others will see you:" and the card (slide 1 only:
              the role, one line of About, up to three topics as "Ask about
              {topic}", the name from sign-up), "That's right" / "Change it";
              "Change it" brings "Tell me what to change.", answered out loud
  choice      "What would you like to do here first?" with "Something else"
              (first; it opens the typing box), "Learn from others", "Share
              what I know", "Prepare a talk"; several, then "Send" (N573)
  talk_date   "Prepare a talk" only: "When is it?" with "Pick a date" and
              "No date yet", once (N564 item 1)
  share       "Share what I know" only: the questions for people who join
              (``join_setup``, N487), in the wait (N572 item 6)
  plan_card   everyone: the plan card, from the first Take's reading
  agreement   in a team, or sharing: "Do you accept it?" with "I agree"
              (N572 item 4)
  set         one "You're set.", for sharers with "Copy my link ›" and
              "Your questions for people who join ›"
  next        N592: one bubble by state: the feedback still being prepared,
              or ready with "Open your feedback ›"; after the walk, one
              bubble by what they chose

Nothing waits for the beats: the walk's row turns orange when the walk is
ready whatever beat is open, and the beats go on after the walk if the
person opens it first (N453 item 7).

The way in starts only when the app asks for it (``POST /v2/plan/way-in``),
so until the app draws it, the first Take ends as before (``plan_flow``
``_from_first_take``). The first Take's reading (the plan's facts and the
profile card) runs inside that route, under the caller's processing
authorization (``phase1_provider_route``); nothing here calls a provider
from anywhere else.

A speaking coach's link goes the coach's own way (N521) and meets none of
the choice's beats. A member's link whose business has a community
(N559's Join / Not now) is not built: there is no community data yet.

State lives in the plan's ``facts.way_in``; no migration.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from services import plan as P

logger = logging.getLogger(__name__)

# ── The words (signed: N453, N564, N572, N573; N592 approved) ─────────────
OPENER = "While your feedback is being prepared, check what I heard."
PROFILE = "Here's how others will see you:"
THATS_RIGHT, CHANGE_IT = "That's right", "Change it"
WHAT_TO_CHANGE = "Tell me what to change."
ASK_ABOUT = "Ask about {topic}"
CHOICE_Q = "What would you like to do here first?"
SOMETHING_ELSE = "Something else"
LEARN = "Learn from others"
SHARE = "Share what I know"
TALK = "Prepare a talk"
#: "Something else" first: it opens the typing box (N573 item 1).
CHOICES = (SOMETHING_ELSE, LEARN, SHARE, TALK)
SEND = "Send"
WHEN_Q = "When is it?"
PICK_DATE = P.COPY["pick_date"]
NO_DATE = P.COPY["no_date"]
AGREE_Q = "Do you accept it?"
I_AGREE = "I agree"
SET = "You're set."
COPY_LINK = "Copy my link ›"
JOIN_QUESTIONS = "Your questions for people who join ›"
ALMOST = "Your feedback is almost ready. It will appear at the top of this chat."
READY = "Your feedback is ready."
OPEN_FEEDBACK = "Open your feedback ›"
#: After the walk, by what they chose (N592 item 2): the talk first, then
#: sharing; "Something else" last, the only one that asks.
AFTER_WALK = {
    TALK: "Next, record Take 2 of your talk.",
    SHARE: "Next, set up your assistant, so people who join you are met your way.",
    LEARN: "Next, ask someone who knows. Tap + to start.",
    SOMETHING_ELSE: "Tell me what you'd like to do, and I'll show you where.",
}
AFTER_WALK_ORDER = (TALK, SHARE, LEARN, SOMETHING_ELSE)

MAX_SAID = 400
MAX_TOPICS = 3

#: The speaking chat, the only one with this way in (N590).
SPEAKING_CHAT = "artur"


class WayInError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


# ── The tree (N572 item 1, N573) ─────────────────────────────────────────

def path(known: dict, chosen: Optional[list]) -> list[str]:
    """Every beat this person meets, in order, from the facts the app knows
    and the answers to the one question. ``chosen`` None: not answered yet,
    so the beats after the choice are not known yet."""
    beats = ["opener", "profile"]
    if known.get("coach_link"):
        return beats  # the coach's own way (N521), and nothing below
    beats.append("choice")
    if chosen is None:
        return beats
    picked = set(chosen)
    if TALK in picked:
        beats.append("talk_date")
    if SHARE in picked:
        beats.append("share")
    beats.append("plan_card")
    if known.get("team") or SHARE in picked:
        beats.append("agreement")
    return beats + ["set", "next"]


# ── Reading it ───────────────────────────────────────────────────────────

def _flow():
    from services import plan_flow
    return plan_flow


def _state(plan: dict) -> Optional[dict]:
    raw = (plan.get("facts") or {}).get("way_in")
    return dict(raw) if isinstance(raw, dict) else None


def on(plan: Optional[dict]) -> bool:
    """The way in has begun on this plan."""
    return bool(plan) and _state(plan) is not None  # type: ignore[arg-type]


def view(plan: dict) -> Optional[dict]:
    """What the app draws from it: the open beat, the choice, whether the
    walk is done ("Record Take 2" stays faded until it is, N592 item 3)."""
    w = _state(plan)
    if w is None:
        return None
    return {"asking": w.get("asking"), "done": list(w.get("done") or []),
            "chosen": w.get("chosen"), "talk_date": w.get("talk_date"),
            "walk_ready": bool(w.get("walk_ready")), "walk_done": bool(w.get("walk_done")),
            "record_next": bool(w.get("walk_done"))}


def profile_card(database: Any, user_id: str) -> Optional[dict]:
    """The card others may see: only after "That's right" (N453 item 2)."""
    plan = database.get_open_plan(str(user_id)) or database.get_latest_plan(str(user_id))
    w = _state(plan) if plan else None
    if not w or not w.get("profile_ok"):
        return None
    return w.get("profile")


# ── Writing it ───────────────────────────────────────────────────────────

def _save(database: Any, user_id: str, plan: dict, w: dict, **facts: Any) -> dict:
    F = _flow()
    return F._save(database, user_id, plan, {"facts": {**F._facts(plan), **facts, "way_in": w}})


def _bot(body: str, key: str, beat: str, **meta: Any) -> tuple:
    return _flow()._bot(body, f"way_in:{key}", way_in=beat, **meta)


def _me(body: str, key: str, beat: str) -> tuple:
    return _flow()._me(body, f"way_in:{key}", way_in=beat, way_in_answer=True)


def _card_rows(profile: dict, n: int) -> list[tuple]:
    topics = [ASK_ABOUT.format(topic=t) for t in profile.get("topics") or []][:MAX_TOPICS]
    card = {"name": profile.get("name"), "role": profile.get("role"),
            "about": profile.get("about"), "topics": topics}
    return [_bot(PROFILE, f"profile:{n}", "profile"),
            _bot("", f"profile_card:{n}", "profile", way_in_profile=card,
                 chips=[THATS_RIGHT, CHANGE_IT])]


def _walk_ready(database: Any, user_id: str, plan: dict, w: dict) -> bool:
    """The first Take's processing is done (``plan_flow.after_processing``
    kept its answers, or the walk has come)."""
    if w.get("walk_ready") or w.get("walk_done"):
        return True
    return (plan.get("facts") or {}).get("first_take") in ("kept", "read")


def _after_walk_row(chosen: list) -> tuple:
    picked = [c for c in AFTER_WALK_ORDER if c in set(chosen or [])] or [SOMETHING_ELSE]
    body = " ".join(AFTER_WALK[c] for c in picked)
    meta: dict[str, Any] = {"way_in_next": picked}
    if SHARE in picked:
        meta["opens"] = "setup_chat"  # N578 item 4
    if picked[-1] == SOMETHING_ELSE:
        meta["way_in_asks"] = "else"  # answered by voice or text
    return _bot(body, "after_walk", "next", **meta)


def _beat_rows(database: Any, user_id: str, plan: dict, w: dict, beat: str) -> Optional[list[tuple]]:
    """The rows of one beat, or None when it is not ready yet (the reading
    has not come). A beat that asks sets ``w["asking"]``."""
    if beat == "opener":
        return [_bot(OPENER, "opener", "opener")]
    if beat == "profile":
        if not w.get("read"):
            return None
        profile = w.get("profile")
        if not profile or not (profile.get("role") or profile.get("topics")):
            w["profile_ok"] = False
            return []  # nothing heard on slide 1: no card to check
        w["asking"] = "profile"
        return _card_rows(profile, int(w.get("profile_n") or 0))
    if beat == "choice":
        w["asking"] = "choice"
        return [_bot(CHOICE_Q, "choice", "choice", chips=list(CHOICES), multi=True,
                     send=SEND, types=SOMETHING_ELSE)]
    if beat == "talk_date":
        w["asking"] = "talk_date"
        return [_bot(WHEN_Q, "talk_date", "talk_date", chips=[PICK_DATE, NO_DATE],
                     plan_ask="way_in_date")]
    if beat == "share":
        from services import join_setup
        if join_setup.is_set(database, user_id):
            return []
        join_setup.begin(database, user_id)
        w["asking"] = "share"
        return []
    if beat == "plan_card":
        if not w.get("read"):
            return None
        return []  # written by ``_plan_card``, which makes the plan
    if beat == "agreement":
        w["asking"] = "agreement"
        return [_bot(AGREE_Q, "agreement", "agreement", chips=[I_AGREE],
                     agreement="data_processing")]
    if beat == "set":
        sharer = SHARE in set(w.get("chosen") or [])
        links = [COPY_LINK, JOIN_QUESTIONS] if sharer else []
        return [_bot(SET, "set", "set", **({"links": links} if links else {}))]
    if beat == "next":
        if w.get("walk_done"):
            w["after_walk_said"] = True
            return [_after_walk_row(w.get("chosen") or [])]
        if _walk_ready(database, user_id, plan, w):
            w["ready_said"] = True
            return [_bot(READY, "ready", "next", chips=[OPEN_FEEDBACK], opens="feedback")]
        w["almost_said"] = True
        return [_bot(ALMOST, "almost", "next")]
    return []


def _plan_card(database: Any, user_id: str, plan: dict, w: dict) -> tuple[dict, list[tuple]]:
    """The plan and its card (N564): a date only from "When is it?"; no
    "You're all set." line, since the way in has one "You're set."."""
    F = _flow()
    today = F.today_in(plan.get("time_zone"))
    talk = F._parse_day(w.get("talk_date")) if w.get("talk_date") else None
    deadline = talk or P.given_deadline(today)
    j = P.journey(today, deadline)
    plan = _save(database, user_id, plan, w)
    plan, rows = F._questions_done(database, user_id, plan, {
        "deadline": deadline.isoformat(), "deadline_given": talk is None,
        "every_day": j.every_day, "total": j.total}, F._diagnose_first_take)
    rows = [r for r in rows if r[3] != "all_set"]
    return plan, rows


def _advance(database: Any, user_id: str, plan: dict) -> tuple[dict, list[dict]]:
    """Every beat that is due, in order, until one asks or waits for the
    reading. Idempotent: a beat is written once (its row's key)."""
    F = _flow()
    w = _state(plan) or {}
    out: list[dict] = []
    if w.get("asking") == "share":
        from services import join_setup
        if join_setup.is_set(database, user_id):
            w["asking"] = None
            w["done"] = [*w.get("done", []), "share"]
    for beat in path(w.get("known") or {}, w.get("chosen")):
        if w.get("asking"):
            break
        if beat in (w.get("done") or []):
            continue
        if beat == "plan_card":
            if not w.get("read") or "profile" not in (w.get("done") or []):
                break  # the card waits for the reading and the profile's check
            w["done"] = [*w.get("done", []), beat]
            plan, card = _plan_card(database, user_id, plan, w)
            out += F._write(database, user_id, plan["id"], card)
            continue
        rows = _beat_rows(database, user_id, plan, w, beat)
        if rows is None:
            if beat == "profile":
                continue  # the choice does not wait for the reading
            break
        if not w.get("asking"):
            w["done"] = [*w.get("done", []), beat]
        plan = _save(database, user_id, plan, w)
        out += F._write(database, user_id, plan["id"], rows)
    plan = _save(database, user_id, plan, w)
    return plan, out


# ── The first Take's reading, in the wait ────────────────────────────────

def _profile_prompt(said: str, change: Optional[str], was: Optional[dict]) -> str:
    lines = [
        "You read what a new member of WillpowerLab said about their field, out loud, "
        "answering \"What do you know better than most people you meet?\". Write the "
        "card others will see for them, in their own words.",
        f"They said: {said or '(nothing)'}",
    ]
    if change and was:
        lines += [f"The card was: {was}", f"They asked to change it: {change}",
                  "Write the card again with their change."]
    lines += [
        "Answer with JSON only: {\"role\": string|null, \"about\": string|null, "
        "\"topics\": [string]}",
        "\"role\" is what they do, a few words (\"Reporter on the politics desk\"); "
        "\"about\" one short line in their words; \"topics\" up to three things they "
        "know, the ones they said most first, two to four words each, each fitting "
        "after \"Ask about\". Null or [] for what they did not say. Never invent.",
    ]
    return "\n".join(lines)


def _read_profile(user_id: str, said: str, change: Optional[str] = None,
                  was: Optional[dict] = None) -> Optional[dict]:
    from services.llm import chat_complete
    from services.llm_config import SPEC_PLAN_TURN
    from services.processing_authorization import rethrow_processing_authorization
    try:
        result = chat_complete(spec=SPEC_PLAN_TURN, system=_profile_prompt(said, change, was),
                               user="Write the card now, as the JSON asked for.",
                               surface="way_in_profile", user_id=str(user_id))
    except Exception as error:  # noqa: BLE001 -- no card is checked rather than a wrong one
        rethrow_processing_authorization(error)
        logger.warning("way in: the profile not read user=%s: %s", user_id, error)
        return None
    parsed = getattr(result, "parsed", None) if result else None
    return parsed if isinstance(parsed, dict) else None


def _clean_profile(raw: Optional[dict], name: Optional[str]) -> dict:
    raw = raw if isinstance(raw, dict) else {}

    def text(v: Any, n: int) -> Optional[str]:
        s = " ".join(str(v).split())[:n] if isinstance(v, str) else ""
        return s or None

    topics = [t for t in (text(x, 60) for x in (raw.get("topics") or [])
                          if isinstance(raw.get("topics"), list)) if t]
    return {"name": name, "role": text(raw.get("role"), 80), "about": text(raw.get("about"), 160),
            "topics": list(dict.fromkeys(topics))[:MAX_TOPICS]}


def _read(database: Any, user_id: str, plan: dict, w: dict, first_name: Optional[str]) -> dict:
    """The first Take, read while it is processed, once its slides' words
    are stored: the plan's facts (``plan_flow._read_first_take``) and the
    profile card. Before that, nothing (the beats that need it wait)."""
    F = _flow()
    if w.get("read"):
        return plan
    take_id = str(F._latest_take(database, user_id).get("id") or "")
    clips = (database.get_snippets_by_session(take_id) or []) if take_id else []
    slides = F._first_take_slides(clips)
    said = F._said(slides)
    if not any(said):
        return plan  # the words are not stored yet
    today = F.today_in(plan.get("time_zone"))
    read = F._read_first_take(user_id, said, today)
    facts = {**F._facts(plan)}
    facts.update(P.clean_facts((read or {}).get("facts"), facts))
    if not facts.get("key_line") and said[P.FIRST_TAKE_KEY]:
        facts["key_line"] = said[P.FIRST_TAKE_KEY][:300]
    # The answers themselves are kept at the end of the Take's processing,
    # each with its voice for the coach (``plan_flow.after_processing``),
    # or at the walk's end without it (``_keep``).
    facts["first_take_session"] = take_id
    w["read"] = True
    w["profile"] = _clean_profile(_read_profile(user_id, said[0]) if said[0] else None, first_name)
    return F._save(database, user_id, plan, {"facts": {**facts, "way_in": w}})


def _keep(database: Any, user_id: str, plan: dict) -> dict:
    """At the walk's end: the answers, if the Take's processing could not
    keep them; the plan no longer waits for that Take (N262 item 1)."""
    F = _flow()
    facts = F._facts(plan)
    take_id = str(facts.get("first_take_session") or F._latest_take(database, user_id).get("id") or "")
    if facts.get("first_take") == "waiting" and take_id:
        slides = F._first_take_slides(database.get_snippets_by_session(take_id) or [])
        said = F._said(slides)
        if any(said):
            facts.update(F._keep_first_take(database, user_id, plan, slides, said, facts.get("key_line")))
    facts.update({"first_take": "read", "first_take_session": take_id or None,
                  "takes_seen": len(F._takes(database, user_id))})
    return F._save(database, user_id, plan, {"facts": facts})


# ── In and out ───────────────────────────────────────────────────────────

def _plan(database: Any, user_id: str) -> dict:
    F = _flow()
    if not F.enabled(database, user_id):
        raise WayInError("NOT_FOUND", "Not found.", 404)
    plan = database.get_open_plan(str(user_id))
    if not plan:
        raise WayInError("NO_PLAN", "No plan.", 404)
    return plan


def _first_take_sent(database: Any, user_id: str, plan: dict) -> bool:
    F = _flow()
    return F._facts(plan).get("first_take") in ("waiting", "kept", "read") and bool(F._takes(database, user_id))


def step(database: Any, user_id: str, *, chat: Any = None, known: Any = None,
         answer: Any = None, first_name: Optional[str] = None) -> dict:
    """The app's one call: begins the way in once Take 1 is sent, takes the
    answer to the open beat, reads the Take when its words are stored, and
    writes the beats that are due. {"plan", "messages"}."""
    if chat not in (None, "", SPEAKING_CHAT):
        raise WayInError("NOT_HERE", "The way in is in the speaking chat only.", 409)  # N590
    plan = _plan(database, user_id)
    w = _state(plan)
    if w is None:
        if plan.get("status") != "asking" or not _first_take_sent(database, user_id, plan):
            raise WayInError("NOT_NOW", "Not now.", 409)
        k = known if isinstance(known, dict) else {}
        w = {"known": {"coach_link": bool(k.get("coach_link")), "team": bool(k.get("team"))},
             "done": [], "asking": None, "chosen": None,
             "started": datetime.now(timezone.utc).isoformat()}
        plan = _save(database, user_id, plan, w)
    out: list[dict] = []
    if answer is not None:
        plan, mine = _answer(database, user_id, plan, answer, first_name)
        out += mine
    plan = _read(database, user_id, plan, _state(plan) or {}, first_name)
    plan, more = _advance(database, user_id, plan)
    return {"plan": plan, "messages": out + more}


def _done(w: dict, beat: str) -> None:
    w["asking"] = None
    w["done"] = [*w.get("done", []), beat]


def _on_profile(database: Any, user_id: str, plan: dict, w: dict, body: dict,
                said: str, first_name: Optional[str]) -> list[tuple]:
    F = _flow()
    n = int(w.get("profile_n") or 0)
    if w.get("changing"):
        if not said:
            raise WayInError("SAY_IT", "Tell me what to change.")
        take = str(F._facts(plan).get("first_take_session") or "")
        slide_1 = F._said(F._first_take_slides(database.get_snippets_by_session(take) or []))[0]
        fresh = _read_profile(user_id, slide_1, said, w.get("profile"))
        if fresh:
            w["profile"] = _clean_profile(fresh, (w.get("profile") or {}).get("name") or first_name)
        w["changing"] = False
        w["profile_n"] = n + 1
        return [_me(said, f"change:{n}", "profile"), *_card_rows(w["profile"], n + 1)]
    if body.get("picked") == THATS_RIGHT:
        w["profile_ok"] = True
        _done(w, "profile")
        _keep_topics(database, user_id, w.get("profile") or {})
        return [_me(THATS_RIGHT, f"right:{n}", "profile")]
    if body.get("picked") == CHANGE_IT:
        w["changing"] = True
        return [_me(CHANGE_IT, f"change_it:{n}", "profile"),
                _bot(WHAT_TO_CHANGE, f"what:{n}", "profile", plan_ask="way_in_voice")]
    raise WayInError("PICK_ONE", "Tap one of the answers.")


def _on_choice(database: Any, user_id: str, w: dict, body: dict, said: str) -> list[tuple]:
    raw = body.get("picked")
    picks = [p for p in CHOICES if isinstance(raw, list) and p in raw]
    if not picks:
        raise WayInError("PICK_ONE", "Tap one of the answers.")
    if SOMETHING_ELSE in picks and not said:
        raise WayInError("SAY_IT", "Type what you'd like to do.")
    w["chosen"] = picks
    w["else_said"] = said or None
    _done(w, "choice")
    shown = ", ".join([p for p in picks if p != SOMETHING_ELSE] + ([said] if said else []))
    from services import speaker_memory
    speaker_memory.record(database, str(user_id), "answer", {"question": CHOICE_Q, "said": shown})
    return [_me(shown, "choice:answer", "choice")]


def _on_talk_date(plan: dict, w: dict, body: dict) -> list[tuple]:
    F = _flow()
    raw = body.get("date")
    if raw in (None, ""):
        w["talk_date"] = None
        shown = NO_DATE
    else:
        day = F._parse_day(raw)
        if day is None or day <= F.today_in(plan.get("time_zone")):
            raise WayInError("INVALID_DATE", "Pick a day after today.")
        w["talk_date"] = day.isoformat()
        shown = P.fmt_day(day)
    _done(w, "talk_date")
    return [_me(shown, "talk_date:answer", "talk_date")]


def _on_agreement(w: dict, body: dict) -> list[tuple]:
    if body.get("picked") != I_AGREE:
        raise WayInError("PICK_ONE", "Tap one of the answers.")
    w["agreed_at"] = datetime.now(timezone.utc).isoformat()
    _done(w, "agreement")
    return [_me(I_AGREE, "agreement:answer", "agreement")]


def _on_else(database: Any, user_id: str, said: str) -> list[tuple]:
    """The answer to "Tell me what you'd like to do, and I'll show you
    where.", kept in Will's notes (N592 item 2)."""
    if not said:
        raise WayInError("SAY_IT", "Say or type it.")
    from services import speaker_memory
    speaker_memory.record(database, str(user_id), "answer",
                          {"question": AFTER_WALK[SOMETHING_ELSE], "said": said})
    return [_me(said, f"else:{datetime.now(timezone.utc).isoformat()}", "next")]


def _answer(database: Any, user_id: str, plan: dict, answer: Any,
            first_name: Optional[str]) -> tuple[dict, list[dict]]:
    F = _flow()
    body = answer if isinstance(answer, dict) else {}
    w = _state(plan) or {}
    beat = str(body.get("beat") or "")
    said = " ".join(str(body.get("said") or "").split())[:MAX_SAID]
    if beat == "else" and w.get("after_walk_said"):
        return plan, F._write(database, user_id, plan["id"], _on_else(database, user_id, said))
    if not beat or beat != w.get("asking"):
        raise WayInError("NOT_NOW", "Not now.", 409)
    if beat == "profile":
        rows = _on_profile(database, user_id, plan, w, body, said, first_name)
    elif beat == "choice":
        rows = _on_choice(database, user_id, w, body, said)
    elif beat == "talk_date":
        rows = _on_talk_date(plan, w, body)
    elif beat == "agreement":
        rows = _on_agreement(w, body)
    else:
        raise WayInError("NOT_NOW", "Not now.", 409)
    plan = _save(database, user_id, plan, w)
    return plan, F._write(database, user_id, plan["id"], rows)


def _keep_topics(database: Any, user_id: str, profile: dict) -> None:
    """The topics, once confirmed, in Will's notes on the person; on their
    profile once the profile's topics have their migration (N453 item 2)."""
    try:
        from services import speaker_memory
        speaker_memory.record(database, str(user_id), "answer", {
            "question": PROFILE, "said": "; ".join(
                x for x in [profile.get("role"), profile.get("about"),
                            ", ".join(profile.get("topics") or [])] if x)})
    except Exception:  # noqa: BLE001 -- the card stands either way
        logger.warning("way in: the topics not kept user=%s", user_id, exc_info=True)


# ── Called from the Take's pipeline and the walk ─────────────────────────

def walk_ready(database: Any, user_id: str) -> list[dict]:
    """The first Take's processing is done: after "Your feedback is almost
    ready.", "Your feedback is ready." with "Open your feedback ›" (N592
    item 1). Best-effort; no provider call."""
    try:
        plan = database.get_open_plan(str(user_id))
        w = _state(plan) if plan else None
        if w is None:
            return []
        w["walk_ready"] = True
        rows: list[tuple] = []
        if w.get("almost_said") and not w.get("ready_said") and not w.get("walk_done"):
            w["ready_said"] = True
            rows.append(_bot(READY, "ready", "next", chips=[OPEN_FEEDBACK], opens="feedback"))
        plan = _save(database, user_id, plan, w)  # type: ignore[arg-type]
        return _flow()._write(database, user_id, plan["id"], rows)
    except Exception as error:  # noqa: BLE001 -- the Take stands either way
        logger.warning("way in: the walk's readiness not written user=%s: %s", user_id, error)
        return []


def after_walk(database: Any, user_id: str, plan: dict, *,
               first_name: Optional[str] = None) -> list[dict]:
    """The first Take's walk is done (``plan_flow.after_take``): the reading,
    if the wait never got to it; the beats still due; and, once "You're
    set." has come, one bubble by what they chose (N592 item 2)."""
    w = _state(plan) or {}
    w["walk_done"] = True
    w["walk_ready"] = True
    plan = _save(database, user_id, plan, w)
    plan = _read(database, user_id, plan, _state(plan) or {}, first_name)
    plan = _keep(database, user_id, plan)
    plan, out = _advance(database, user_id, plan)
    w = _state(plan) or {}
    if "set" in (w.get("done") or []) and not w.get("after_walk_said"):
        w["after_walk_said"] = True
        if "next" not in w.get("done", []):
            w["done"] = [*w.get("done", []), "next"]
        plan = _save(database, user_id, plan, w)
        out += _flow()._write(database, user_id, plan["id"], [_after_walk_row(w.get("chosen") or [])])
    return out


def after_share(database: Any, user_id: str) -> list[dict]:
    """The questions for people who join are set (``join_setup``, "That's
    right"): the way in goes on from there, with no second "You're set."."""
    plan = database.get_open_plan(str(user_id))
    if not plan or _state(plan) is None or (_state(plan) or {}).get("asking") != "share":
        return []
    return _advance(database, user_id, plan)[1]


def in_share(database: Any, user_id: str) -> bool:
    """The questions for people who join are being set inside the way in."""
    try:
        plan = database.get_open_plan(str(user_id))
        return bool(plan) and (_state(plan) or {}).get("asking") == "share"
    except Exception:  # noqa: BLE001 -- unread is outside the way in
        return False
