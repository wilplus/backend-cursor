"""Will's one question after a Take (founder 2026-10-20, N82; the words
signed in chat the same day, prototype
<https://claude.ai/artifact/HSRfvDZLDRQizmGJDxMUJz>).

Will asks only when something is off or missing, once per Take, as the
Take's one ask (``after_take``: from Take 2 the CEO panel's ask comes first,
then Will, then "Did this help?" when the Take looks off; WhatsApp and the
home screen wait for the next visit, N294 item 8). The first that holds
(``plan``):

  pause      the practice did not land, or the voice dipped, two Takes in a
             row: a breather
  not_used   the clearer line practised last Take did not come back in this
             one ("On purpose?"); when it did, the summary says so instead
  audience   the talk has no audience; Will checks ("Right?") when this Take
             names one twice, else asks
  goal       the talk has no call to action
  key_line   with both in place, the talk has no key line: the plan's signed
             question, "If {who} remembers one sentence from you, what is it?
             Say it the way you'll say it.", answered by voice, no tap
             answers (founder 2026-10-31, N294 item 2)
  vision ... from Take 3, with all three in place: one deeper question, own
             words

The question is about the moment the walk just worked on (founder
2026-10-31, N294 item 1): it opens on the speaker's own words of the last
moment the walk showed (``moment_of``), "When you said “…”, " where the
question reads on from it, else "We just worked on “…”. ". "On purpose?"
already quotes the line it asks about and opens on nothing more.

The tap answers come from what Will knows, the recording first (N297 item
2): the words this Take said (one small call, ``heard``: gpt-4o-mini under
the Take's authority, copied word for word or nothing), what the speaker
answered on an earlier talk, then the signed answers for their field. Who
the talk is for has no "Someone else" (N406 item 2, was N319 item 8): their
own words go into "Something else" in the Lounge's bar (N371); the check
("Right?") keeps "Someone else", which opens "Who is it for, then? 👀". A
follow-up has no tap answers (N294 item 3). Every answer is kept for Will
(``speaker_memory``); who the talk is for and what they should do also fill
the talk's own setup fields (``audience``; ``strategic_context``'s "Desired
call to action:"), so every later Take of the talk and its clearer version
hear them. A typed message under the question is the answer
(``chat_turn``). Will says back who the talk is for ("{who}. I'll keep them
in mind.", N294 item 5) from the speaker's side, "my team" as "Your team"
(``their_side``, N406 item 3), and a talk to themself as "I'll keep you in
mind."; every other answer gets "Got it, thanks 🙏". For a talk to themself
what they should do is "When you finish, what do you want to do? Or feel?
🤔", with no taps, and the key line keeps "your audience" (N406 item 4).

One at a time (N294 item 4): who the talk is for, answered, may be followed
by what they should do when that is missing too, as the next ask of the
chain (``after_take``, "will_next"), and what they should do, answered, by
the key line when that is missing too; not answering, or Skip, ends them.
A typed answer, a voice answer (``answer_voice``) or a tap that needs no
follow-up lets the chain after the Take go on.

An answer by voice (founder 2026-10-31, N294 items 2 and 3; N314, N319 item
1): the recording is transcribed under the caller's processing authorization
(the plan's own transcriber call), its words are the answer, as typed words
are, and the thread keeps the words as the speaker's voice bubble
(``will_voice``); the recording itself is not kept (the Lounge thread is
text only). The key line answered is kept as the talk's key line, sure
(``take_context``), in the Take's setup and the open plan that has none.

No number, score or verdict reaches the speaker. No new words but those
below, signed on 2026-10-20. Will says each question with a light touch
(founder 2026-10-20, N86: ``vary``, one small call under the Take's
authority, kept only when it still means the signed question and keeps the
speaker's own words in it), else as written; the tap answers always as
written.
"""
from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

_NAMESPACE = uuid.UUID("3c8f1e27-9b54-4d0a-a6e3-52f7d9c1b08e")

OFFER = "will_question"
#: The signed words (founder 2026-10-20; who the talk is for, N347 item 1,
#: was "Quick one: who's this talk really for? 🎯"). ``{heard}`` and
#: ``{words}`` are the speaker's own words.
QUESTIONS = {
    "pause": "You've put real work into this one 💪 Need a breather, or does something feel missing?",
    "not_used": "Last time we practised “{words}”. It didn't make it into this Take. On purpose? 😏",
    "audience_check": "Sounds like this one's for {heard}. Right? 🎯",
    "audience": "Who were you talking to? 🎯",
    "goal": "When you finish, what do you want them to do? Or feel? 🤔",
    "vision": "Zoom out with me 🔭 Does this talk take you where you want to go?",
    "most_you": "Which part of this talk is most you?",
    "why_matters": "Why does this one matter to you?",
    "changes": "If this talk goes perfectly, what changes for you?",
    "slot_1": "",
    "slot_2": "",
}
CHIPS = {
    "pause": ("A breather", "Something's missing", "All good, keep going"),
    "not_used": ("Yes, on purpose", "I forgot", "It didn't feel like me"),
    "audience_check": ("Yes", "Someone else"),
    "vision": ("Yes", "Not sure", "Not really"),
}
#: The signed audience answers by the speaker's field (``domains``); business
#: for executive presence and for a speaker with no field.
AUDIENCE_BY_FIELD = {
    "executive_presence": ("My team", "Leadership", "A client"),
    "public_speaking": ("A big room", "Colleagues", "Friends and family"),
    "sales": ("A buyer", "Their team", "The decision maker"),
    "customer_service": ("A customer", "A caller", "My team"),
    "interview_prep": ("The hiring manager", "A panel", "A recruiter"),
}
GOAL_CHIPS = ("Say yes", "Trust me", "Get it")
#: One follow-up, once, after the tap answer in this place (founder's
#: words may rename the answer; its place keeps its follow-up).
FOLLOW_AT = {
    "audience_check": {1: "Who is it for, then? 👀"},
    "pause": {1: "Tell me more 👀 What's missing?"},
    "not_used": {2: "What would feel more like you?"},
    "vision": {1: "What would make it a yes?", 2: "Where do you want it to take you?"},
}
#: The check's second answer. Who the talk is for, asked openly, no longer
#: ends on it (N406 item 2, was N319 item 8); a question asked before still
#: carries it, and it still opens the check's follow-up (``follow_up``).
SOMEONE_ELSE = CHIPS["audience_check"][1]
THANKS = "Got it, thanks 🙏"
#: Will says back who the talk is for (founder 2026-10-31, N294 item 5),
#: from the speaker's side (N406 item 3, ``their_side``).
KEEP_IN_MIND = "{who}. I'll keep them in mind."
#: A talk to themself, said back (N406 item 3).
KEEP_YOU_IN_MIND = "I'll keep you in mind."
#: What they should do, for a talk to themself: no "them", no taps (N406
#: item 4).
GOAL_SELF = "When you finish, what do you want to do? Or feel? 🤔"
#: The question opens on the moment the walk just worked on (founder
#: 2026-10-31, N294 item 1): read on from it, or said before it.
WHEN_YOU_SAID = "When you said “{moment}”, "
WE_JUST_WORKED_ON = "We just worked on “{moment}”. "
#: A question that starts so reads on from "When you said “…”, ".
_READS_ON = ("sounds like ",)
#: "On purpose?" quotes the line it asks about: no second quote.
_NO_MOMENT = ("not_used",)
#: Longer than this, the moment's words are not quoted (a clip that ran on).
_MAX_MOMENT = 220
#: Longer than this, a typed answer is not said back.
_MAX_WHO = 80
#: The signed "Skip" (the Lounge's chip vocabulary, as under "What would help?").
SKIP = "Skip"
#: The key line (founder 2026-10-31, N294 item 2): the plan's signed question,
#: with who the talk is for in place of "your audience" when Will knows it.
KEY_LINE = "key_line"
_KEY_LINE_WHO = "your audience"
#: The deeper questions, in the order Will asks them; the two slots are the
#: founder's own (N83), asked once filled.
PRINCIPLES = ("vision", "most_you", "why_matters", "changes", "slot_1", "slot_2")
#: Asked at most once per talk; the others belong to the Take that shows them.
_ONCE_PER_TALK = ("audience", "audience_check", "goal", KEY_LINE) + PRINCIPLES
CALL_TO_ACTION = "Desired call to action:"

_MAX_CHIPS = 3
_MAX_WORDS = 4
_MAX_CHIP_CHARS = 40
_MAX_SAID = 300
_SCAN = 500
_LOOKBACK = 6
#: How long the answer waits for the heard call once the summary is written.
_HEARD_BUDGET = 3.0
_DIGIT = re.compile(r"\d")
_NOT_AN_AUDIENCE = {"you", "we", "us", "they", "them", "everyone", "everybody",
                    "people", "guys", "folks", "all"}
_LOWER_FIRST = {"the", "our", "my", "your", "a", "an", "their"}


class QuestionError(Exception):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


# ------------------------------------------------------------------ words


def _norm(text: str) -> str:
    return " ".join(re.sub(r"[^\w' ]+", " ", str(text or "").lower()).split())


def chip(text: Any) -> Optional[str]:
    """A tap answer in its signed shape: a few words, no number, first letter
    up; None when the words cannot be one. Pure."""
    words = " ".join(str(text or "").strip().strip(".,;:!?\"“”'").split())
    if (not words or _DIGIT.search(words) or len(words.split()) > _MAX_WORDS
            or len(words) > _MAX_CHIP_CHARS):
        return None
    return words[0].upper() + words[1:]


def _in_sentence(phrase: str) -> str:
    """``the board`` inside "Sounds like this one's for …": a leading
    article stays small, a name keeps its capital. Pure."""
    head, _, rest = phrase.partition(" ")
    return f"{head.lower()} {rest}".strip() if head.lower() in _LOWER_FIRST else phrase


#: A talk to themself, as the speaker says it (N406 item 3).
_SELF = re.compile(r"^(?:just |only |to |for )?(?:me|myself|my self|i)(?: only| alone)?$")
#: The speaker's words for their own side, as Will says them back (N406 item 3).
_MINE = re.compile(r"\b(myself|mine|my|ours|our|me|us)\b", re.I)
_YOURS = {"myself": "yourself", "mine": "yours", "my": "your", "ours": "yours",
          "our": "your", "me": "you", "us": "you"}


def to_self(who: Any) -> bool:
    """Whether who the talk is for is the speaker themself: "Myself", "me",
    "just me" (N406 item 3). Pure."""
    return bool(_SELF.match(_norm(who)))


def their_side(who: str) -> str:
    """Who the talk is for as Will says it to the speaker: "my team" is
    "your team", "people like me" "people like you" (N406 item 3). A word
    in capitals ("US") is a name and stays. Pure."""
    def swap(found: "re.Match[str]") -> str:
        word = found.group(0)
        if len(word) > 1 and word.isupper():
            return word
        yours = _YOURS[word.lower()]
        return yours[0].upper() + yours[1:] if word[0].isupper() else yours
    return _MINE.sub(swap, who)


def _chips(*groups: Any) -> list[str]:
    """The first three distinct tap answers across ``groups``. Pure."""
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        for raw in group or ():
            c = chip(raw)
            if c and c.lower() not in seen:
                seen.add(c.lower())
                out.append(c)
    return out[:_MAX_CHIPS]


# ------------------------------------------------------------------ heard

#: The heard call's instructions (drift-locked: services/prompts/pending.py).
_HEARD_SYSTEM = (
    "You read the title and the transcript of a talk someone is practising. "
    "Find two things, only when the speaker's own words say them:\n"
    "- audience: who the talk is for (for example \"the board\", \"new "
    "customers\").\n"
    "- ask: what the speaker wants the audience to do or feel (for example "
    "\"approve the budget\").\n"
    "Copy each one word for word from the title or the transcript: at most "
    "four words, no numbers. \"We\", \"you\", \"everyone\" and \"people\" are "
    "not an audience. When the words do not say it clearly, give an empty "
    "string. Never guess.\n"
    "Answer with JSON only: {\"audience\": \"...\", \"ask\": \"...\"}"
)
_SURFACE = "will_question_heard"
_HEARD_CHARS = 6000


def verbatim(phrase: Any, *sources: str) -> Optional[str]:
    """``phrase`` when it is a short run of words that one of ``sources``
    says, word for word (case and punctuation aside); else None. Pure."""
    words = " ".join(str(phrase or "").strip().strip(".,;:!?\"“”'").split())
    norm = _norm(words)
    if (not norm or _DIGIT.search(words) or len(norm.split()) > _MAX_WORDS
            or norm in _NOT_AN_AUDIENCE):
        return None
    padded = f" {norm} "
    return words if any(padded in f" {_norm(s)} " for s in sources if s) else None


def times_said(phrase: str, title: str, said: str) -> int:
    """How often the Take says ``phrase``, the title counting once. Pure."""
    padded = f" {_norm(phrase)} "
    return f" {_norm(said)} ".count(padded) + (1 if padded in f" {_norm(title)} " else 0)


def read_heard(text: Optional[str], title: str, said: str) -> dict:
    """The heard call's answer, kept only where the Take says it word for
    word: {"audience", "audience_times", "ask"}. Pure."""
    try:
        body = json.loads(text or "{}")
    except (TypeError, ValueError):
        body = {}
    body = body if isinstance(body, dict) else {}
    audience = verbatim(body.get("audience"), title, said)
    ask = verbatim(body.get("ask"), title, said)
    return {"audience": audience, "ask": ask,
            "audience_times": times_said(audience, title, said) if audience else 0}


def heard(title: str, said: str, *, user_id: Optional[str], take: Optional[str],
          arc_id: Optional[str]) -> dict:
    """gpt-4o-mini reads who the talk is for and what it asks. Runs inside
    the Take's protected provider scope (the caller's)."""
    from services.llm import chat_complete
    from services.llm_config import SPEC_WILL_QUESTION_HEARD
    user = f"Title: \"{title}\"\nTranscript: {said[:_HEARD_CHARS]}"
    result = chat_complete(spec=SPEC_WILL_QUESTION_HEARD, system=_HEARD_SYSTEM, user=user,
                           surface=_SURFACE, user_id=user_id, session_id=take, arc_id=arc_id)
    return read_heard(getattr(result, "text", None) if result else None, title, said)


def start_heard(database: Any, *, user_id: str, arc_id: str, take: str, title: str,
                said: str) -> Callable[[], dict]:
    """Starts the heard call off the request, beside the summary's own call,
    and returns the call that collects it, waiting at most ``_HEARD_BUDGET``.
    Too slow, refused or failed: nothing heard, and Will asks openly."""
    nothing: dict = {"audience": None, "ask": None, "audience_times": 0}
    if not said.strip():
        return lambda: nothing
    try:
        from concurrent.futures import ThreadPoolExecutor
        from contextvars import copy_context
        from services.take_summary import _under_authority
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="will-question-heard")
        future = pool.submit(copy_context().run, lambda: _under_authority(
            database, take, lambda: heard(title, said, user_id=user_id, take=take,
                                          arc_id=arc_id)))
        pool.shutdown(wait=False)
    except Exception as error:  # noqa: BLE001 -- Will asks openly
        logger.warning("will question: heard not started take=%s: %s", take, error)
        return lambda: nothing

    def collect() -> dict:
        try:
            got = future.result(timeout=_HEARD_BUDGET)
        except Exception as error:  # noqa: BLE001 -- too slow or failed: ask openly
            logger.warning("will question: nothing heard take=%s: %r", take, error)
            return nothing
        if not isinstance(got, dict):
            return nothing
        _keep_heard(database, take, got)
        return got
    return collect


def _keep_heard(database: Any, take: str, got: dict) -> None:
    """What the Take was heard to be for and to ask, kept in its setup under
    ``heard``: a guess the picker reads until the speaker says it (N293,
    ``services.take_context``). A merge; never raises."""
    found = {k: str(got[k])[:200] for k in ("audience", "ask") if got.get(k)}
    if not found:
        return
    try:
        ctx = dict(database.takes.get_session_intake_context(take) or {})
        ctx["heard"] = found
        database.takes.set_session_intake_context(take, ctx)
    except Exception as error:  # noqa: BLE001 -- Will asks either way
        logger.warning("will question: heard not kept take=%s: %s", take, error)


# ------------------------------------------------------------------ varied

#: The light touch (founder 2026-10-20, N86; drift-locked: services/prompts/pending.py).
_VARY_SYSTEM = (
    "You are Will, a speaking coach and a curious, cheeky colleague. You are "
    "given one question Will asks a speaker right after a practice Take, in "
    "its signed wording. Say the same question in slightly different words: "
    "the same meaning, the same tone, about the same length, still one "
    "friendly question. Keep most of its words.\n"
    "- Keep any {placeholder} exactly as written, once.\n"
    "- No numbers, no new facts, no advice, no greeting.\n"
    "- Keep the emoji if there is one, where it was.\n"
    "Answer with the question only."
)
_VARY_SURFACE = "will_question_vary"
#: How many of the signed question's words a light touch keeps, at least.
_VARY_NEAR = 0.45
_BRACE = re.compile(r"[{}]")


def _shared(a: str, b: str) -> float:
    one = set(re.findall(r"[a-z']+", a.lower()))
    two = set(re.findall(r"[a-z']+", b.lower()))
    return len(one & two) / len(one | two) if one and two else 0.0


def read_varied(key: str, text: Optional[str], signed: str) -> Optional[str]:
    """The varied question when it is still the signed one said with a light
    touch: most words shared, the speaker's own words kept in place once, no
    number, one line that fits two, still a question. Else None, and Will
    says the signed words. Pure."""
    body = " ".join(str(text or "").strip().strip('"“”').split())
    if not body or body == signed or len(body) > _MAX_QUESTION:
        return None
    if _DIGIT.search(body) or "?" not in body:
        return None
    inner = _SHOWN.get(key, ("", ""))[0]
    if inner and body.count(inner) != 1:
        return None
    if _BRACE.search(body.replace(inner, "") if inner else body):
        return None
    if _shared(body, signed) < _VARY_NEAR:
        return None
    return body


def vary(key: str, signed: str, *, user_id: Optional[str], take: Optional[str],
         arc_id: Optional[str]) -> Optional[str]:
    """gpt-4o-mini says the signed question with a light touch; code keeps it
    only when ``read_varied`` does. Runs inside the Take's protected provider
    scope (the caller's)."""
    from services.llm import chat_complete
    from services.llm_config import SPEC_WILL_QUESTION_VARY
    result = chat_complete(spec=SPEC_WILL_QUESTION_VARY, system=_VARY_SYSTEM,
                           user=f"Question: {signed}", surface=_VARY_SURFACE,
                           user_id=user_id, session_id=take, arc_id=arc_id)
    return read_varied(key, getattr(result, "text", None) if result else None, signed)


# ------------------------------------------------------------------ lead-in

#: Will's lead-in to an ask after the Take (founder 2026-10-20, N89: "Will
#: asks a well-balanced reflection question based on liaising the Take",
#: "these messages are already written but Will can be creative around
#: them"; drift-locked: services/prompts/pending.py).
_LEAD_IN_SYSTEM = (
    "You are Will, a speaking coach and a curious, cheeky colleague. Right "
    "after a speaker reviewed a recording of their talk, Will has one small "
    "ask for them; its signed wording is given, and a few plain facts about "
    "this Take. Write Will's message: one friendly sentence, two at most, "
    "that ties the ask to this Take or to them (a reflection, never a grade, "
    "never advice), then the ask itself in its signed wording said with a "
    "light touch: the same meaning, most of its words kept; its buttons "
    "follow. Like a friend at work: 'you', contractions, warm; at most one "
    "emoji.\n"
    "- No numbers, scores, percentages or verdicts; never 'cue' or the names "
    "of measurements.\n"
    "- Only say what the facts support; invent nothing about them.\n"
    "- No greeting, no advice, and no question other than the ask's own.\n"
    "Answer with the message only."
)
_LEAD_IN_SURFACE = "will_lead_in"
_LEAD_IN_MAX = 320
#: What each ask must still say, whatever Will's words around it.
_LEAD_IN_KEEPS = {
    "whatsapp": ("whatsapp", "number"),
    "feedback_check": ("help",),
}
_LEAD_IN_BANNED = re.compile(r"\d|%|\bcue\b|\bscore\b|\bmetric|\bwillfidence\b|\bpercent", re.I)
_LEAD_IN_EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")


def read_lead_in(ask: str, text: Optional[str], signed: str) -> Optional[str]:
    """Will's lead-in when it keeps the rules: two or three sentences, the
    ask still said (its key words there, a question still a question), no
    number or banned word, one emoji at most, not too long. Else None, and
    the ask is said as written. Pure."""
    body = " ".join(str(text or "").strip().strip('"“”').split())
    if not body or body == signed or len(body) > _LEAD_IN_MAX:
        return None
    if _LEAD_IN_BANNED.search(body) or len(_LEAD_IN_EMOJI.findall(body)) > 1:
        return None
    sentences = [s for s in re.split(r"(?<=[.?!])\s+", body) if s]
    if not 2 <= len(sentences) <= 3:
        return None
    low = body.lower()
    if not any(k in low for k in _LEAD_IN_KEEPS.get(ask, ())):
        return None
    if "?" in signed and "?" not in body:
        return None
    return body


def lead_in(ask: str, signed: str, facts: list[str], *, user_id: Optional[str],
            take: Optional[str], arc_id: Optional[str]) -> Optional[str]:
    """gpt-4o-mini writes Will's lead-in to one ask from the Take's facts;
    code keeps it only when ``read_lead_in`` does. Runs inside the Take's
    protected provider scope (the caller's)."""
    from services.llm import chat_complete
    from services.llm_config import SPEC_WILL_LEAD_IN
    user = (f"Ask (signed wording): {signed}\nFacts about this Take:\n"
            + "\n".join(f"- {f}" for f in facts[:6]))
    result = chat_complete(spec=SPEC_WILL_LEAD_IN, system=_LEAD_IN_SYSTEM, user=user,
                           surface=_LEAD_IN_SURFACE, user_id=user_id, session_id=take,
                           arc_id=arc_id)
    return read_lead_in(ask, getattr(result, "text", None) if result else None, signed)


def start_lead_ins(database: Any, *, user_id: str, arc_id: str, take: str,
                   signed: dict, facts: list[str]) -> Callable[[], dict]:
    """Starts Will's lead-in for each ask in ``signed`` (ask -> its signed
    words) off the request, beside the summary's own call, and returns the
    call that collects them, waiting at most ``_HEARD_BUDGET`` in all. Too
    slow, refused or failed: that ask is said as written."""
    def one(ask: str, text: str) -> Callable[[], Optional[str]]:
        return lambda: lead_in(ask, text, facts, user_id=user_id, take=take, arc_id=arc_id)
    return _start_calls(database, take=take, label="lead-in",
                        calls={ask: one(ask, text) for ask, text in signed.items() if text})


def _start_calls(database: Any, *, take: str, label: str,
                 calls: dict[str, Callable[[], Optional[str]]]) -> Callable[[], dict]:
    """Runs each of ``calls`` on its own thread under the Take's authority
    and returns the call that collects the words that came back in time."""
    if not calls:
        return lambda: {}
    try:
        from concurrent.futures import ThreadPoolExecutor
        from contextvars import copy_context
        from services.take_summary import _under_authority
        pool = ThreadPoolExecutor(max_workers=len(calls), thread_name_prefix=f"will-{label}")
        futures = {k: pool.submit(copy_context().run,
                                  lambda call=call: _under_authority(database, take, call))
                   for k, call in calls.items()}
        pool.shutdown(wait=False)
    except Exception as error:  # noqa: BLE001 -- said as written
        logger.warning("will question: %s not started take=%s: %s", label, take, error)
        return lambda: {}

    def collect() -> dict:
        import time
        out: dict = {}
        until = time.monotonic() + _HEARD_BUDGET
        for k, future in futures.items():
            try:
                got = future.result(timeout=max(0.0, until - time.monotonic()))
                if isinstance(got, str) and got:
                    out[k] = got
            except Exception as error:  # noqa: BLE001 -- too slow or failed: as written
                logger.info("will question: %s said as written key=%s take=%s: %r",
                            label, k, take, error)
        return out
    return collect


def start_vary(database: Any, *, user_id: str, arc_id: str, take: str, keys: list[str],
               words: dict) -> Callable[[], dict]:
    """Starts the light touch for each of ``keys`` off the request, beside
    the summary's own call, and returns the call that collects them, waiting
    at most ``_HEARD_BUDGET`` in all. Too slow, refused or failed: that
    question is said as written."""
    templates = {k: str((words or {}).get(k, {}).get("question") or "") for k in keys}
    templates = {k: t for k, t in templates.items() if t}
    if not templates:
        return lambda: {}
    try:
        from concurrent.futures import ThreadPoolExecutor
        from contextvars import copy_context
        from services.take_summary import _under_authority
        pool = ThreadPoolExecutor(max_workers=len(templates), thread_name_prefix="will-question-vary")
        futures = {k: pool.submit(copy_context().run, lambda k=k, t=t: _under_authority(
            database, take, lambda: vary(k, t, user_id=user_id, take=take, arc_id=arc_id)))
            for k, t in templates.items()}
        pool.shutdown(wait=False)
    except Exception as error:  # noqa: BLE001 -- said as written
        logger.warning("will question: light touch not started take=%s: %s", take, error)
        return lambda: {}

    def collect() -> dict:
        import time
        out: dict = {}
        until = time.monotonic() + _HEARD_BUDGET
        for k, future in futures.items():
            try:
                got = future.result(timeout=max(0.0, until - time.monotonic()))
                if isinstance(got, str) and got:
                    out[k] = got
            except Exception as error:  # noqa: BLE001 -- too slow or failed: as written
                logger.info("will question: said as written key=%s take=%s: %r", k, take, error)
        return out
    return collect


# ------------------------------------------------------------------ the talk


def _ctx(take: dict) -> dict:
    ctx = take.get("intake_context")
    return ctx if isinstance(ctx, dict) else {}


def talk_audience(takes: list[dict]) -> str:
    """The talk's audience: the newest Take's that has one. Pure."""
    return next((str(_ctx(t).get("audience")).strip() for t in reversed(takes)
                 if str(_ctx(t).get("audience") or "").strip()), "")


def call_to_action(strategic: Any) -> str:
    """What the speaker wants the audience to do, from the setup's note. Pure."""
    for line in str(strategic or "").splitlines():
        if line.startswith(CALL_TO_ACTION):
            return line[len(CALL_TO_ACTION):].strip()
    return ""


def talk_goal(takes: list[dict]) -> str:
    """The talk's call to action: the newest Take's that has one. Pure."""
    return next((goal for goal in (call_to_action(_ctx(t).get("strategic_context"))
                                   for t in reversed(takes)) if goal), "")


def talk_key_line(takes: list[dict]) -> str:
    """The talk's key line as Will heard it: the newest Take's setup that
    has one (N294 item 2). Pure."""
    return next((str(_ctx(t).get(KEY_LINE)).strip() for t in reversed(takes)
                 if str(_ctx(t).get(KEY_LINE) or "").strip()), "")


def _open_plan(database: Any, user_id: str) -> dict:
    try:
        return database.get_open_plan(str(user_id)) or {}
    except Exception:  # noqa: BLE001 -- no plan read: Will asks as without one
        return {}


def known_key_line(database: Any, user_id: str, takes: list[dict]) -> str:
    """The key line the talk already has: Will's answer kept in its setup,
    else the open plan's (N294 item 2). "" when missing."""
    return talk_key_line(takes) or str((_open_plan(database, user_id).get("facts") or {})
                                       .get(KEY_LINE) or "").strip()


def key_line_question(who: Optional[str]) -> str:
    """The plan's signed key-line question, "If {who} remembers one sentence
    from you, what is it? Say it the way you'll say it.", with who the talk
    is for in place of "your audience" when known, from the speaker's side;
    a talk to themself keeps "your audience" (N406 items 3 and 4). Pure."""
    from services.plan import BANK
    signed = str(BANK["key"][0])
    who = " ".join(str(who or "").split()).strip(" .,;:!?\"“”'")
    if not who or len(who) > _MAX_WHO or to_self(who):
        return signed
    return signed.replace(_KEY_LINE_WHO, _in_sentence(their_side(who)), 1)


def with_goal(strategic: Any, goal: str) -> str:
    """The setup's note with ``goal`` as its call to action, the rest kept.
    Pure."""
    rest = [line for line in str(strategic or "").splitlines()
            if line.strip() and not line.startswith(CALL_TO_ACTION)]
    return "\n".join([f"{CALL_TO_ACTION} {goal}"] + rest)[:2000]


# ------------------------------------------------------------------ the plan


@dataclass
class Plan:
    """What Will asks after this Take, before the words are put together."""
    key: str
    arc_id: str
    take: str
    passage: Optional[str] = None
    heard: Callable[[], dict] = field(default=lambda: {})
    field_name: Optional[str] = None
    earlier: list[str] = field(default_factory=list)
    words: dict = field(default_factory=dict)
    varied: Callable[[], dict] = field(default=lambda: {})
    #: The speaker's words of the moment the walk just worked on (N294 item 1).
    moment: Optional[str] = None
    #: The context question that may follow this one once it is answered
    #: (N294 item 4): "goal" after who the talk is for, when both are missing.
    then: Optional[str] = None
    #: What the speaker answered to ``then`` on an earlier talk.
    then_earlier: list[str] = field(default_factory=list)
    #: Who the talk is for, for the key-line question (N294 item 2).
    who: Optional[str] = None


def two_off(now: tuple, before: tuple) -> bool:
    """The practice did not land, or the voice dipped, in this Take and the
    one before: ``(practice, moved)`` each. Pure."""
    return ((now[0] == "not_yet" and before[0] == "not_yet")
            or (now[1] == "dipped" and before[1] == "dipped"))


def choose_key(*, take_index: int, now: tuple, before: Optional[tuple],
               carried: Optional[dict], audience: str, goal: str,
               asked: set[str], asked_last: Optional[str], key_line: str = "",
               deeper: tuple = PRINCIPLES[:4]) -> Optional[str]:
    """The first that holds (module table), or None: nothing is off or
    missing. Pure."""
    if before is not None and asked_last != "pause" and two_off(now, before):
        return "pause"
    if carried and carried.get("used") is False:
        return "not_used"
    if not audience and not asked & {"audience", "audience_check"}:
        return "audience"
    if not goal and "goal" not in asked:
        return "goal"
    if key_wanted(audience=audience, goal=goal, key_line=key_line, asked=asked):
        return KEY_LINE
    if take_index >= 3 and audience and goal and key_line:
        return next((k for k in deeper if k not in asked), None)
    return None


def key_wanted(*, audience: str, goal: str, key_line: str, asked: set[str]) -> bool:
    """The key line is asked once who the talk is for and what they should
    do are known and it is missing, once per talk (N294 item 2). Pure."""
    return bool(audience and goal and not key_line and KEY_LINE not in asked)


def _thread(database: Any, user_id: str, limit: int) -> list[dict]:
    try:
        return database.get_lounge_messages_page(str(user_id), limit=limit) or []
    except Exception as error:  # noqa: BLE001 -- an unread thread asks nothing twice
        logger.warning("will question: thread unread user=%s: %s", user_id, error)
        return []


def asked_on_talk(rows: list[dict], arc_id: str) -> tuple[set[str], Optional[str]]:
    """The questions Will already asked on this talk, and the newest one;
    ``rows``: the thread, newest first. Pure."""
    metas = [r.get("metadata") or {} for r in rows]
    keys: list[str] = [str(m["will_question"]) for m in metas
                       if m.get("offer") == OFFER and m.get("will_question_step") == "ask"
                       and str(m.get("arc_id")) == str(arc_id)
                       and isinstance(m.get("will_question"), str)]
    return set(keys), (keys[0] if keys else None)


def earlier_answers(database: Any, user_id: str, slot: str = "audience") -> list[str]:
    """What the speaker said for their other talks, newest first: who each
    was for (``audience``) or what they wanted them to do (``goal``)."""
    try:
        events = database.list_speaker_memory_events(str(user_id), limit=200) or []
    except Exception:  # noqa: BLE001 -- nothing earlier
        return []
    said = [(e.get("payload") or {}).get(slot) for e in reversed(events)
            if e.get("kind") == "answer"]
    return [s for s in said if isinstance(s, str) and s.strip()]


def moment_of(rows: list[dict], take: str, snippets: list[dict]) -> Optional[str]:
    """The speaker's own words of the last moment the walk showed on this
    Take (N294 item 1): the clip its newest moment step played, as the
    Take's transcript has it. ``rows``: the thread, newest first. None when
    the walk showed no clip, or its words ran too long to quote. Pure."""
    said = {str(s.get("id")): str(s.get("transcript") or "") for s in snippets or []
            if isinstance(s, dict) and s.get("id")}
    for row in rows:
        meta = row.get("metadata") or {}
        clip = meta.get("clip")
        snippet = clip.get("snippet_id") if isinstance(clip, dict) else None
        if row.get("kind") != "walk_step" or str(meta.get("take_session_id")) != str(take) or not snippet:
            continue
        words = " ".join(said.get(str(snippet), "").split()).strip(" .,;:!?\"“”'")
        return words if words and len(words) <= _MAX_MOMENT else None
    return None


def with_moment(key: str, question: str, moment: Optional[str]) -> str:
    """The question opened on the moment the walk just worked on (N294 item
    1): "When you said “…”, " when it reads on from it, else "We just worked
    on “…”. "; as it is with no moment, and for "On purpose?". Pure."""
    if not moment or not question or key in _NO_MOMENT:
        return question
    if question.lower().startswith(_READS_ON):
        return WHEN_YOU_SAID.format(moment=moment) + question[0].lower() + question[1:]
    return WE_JUST_WORKED_ON.format(moment=moment) + question


def said_back(key: str, said: Optional[str]) -> str:
    """Will's reply to an answer: who the talk is for, said back from the
    speaker's side (N294 item 5, N406 item 3), "I'll keep you in mind." for
    a talk to themself; else "Got it, thanks 🙏". A long or many-line answer
    is not said back. Pure."""
    who = " ".join(str(said or "").split()).strip(" .,;:!?\"“”'")
    if (key not in ("audience", "audience_check") or not who or len(who) > _MAX_WHO
            or "\n" in str(said)):
        return THANKS
    if to_self(who):
        return KEEP_YOU_IN_MIND
    who = their_side(who)
    return KEEP_IN_MIND.format(who=who[0].upper() + who[1:])


def _field(database: Any, user_id: str) -> Optional[str]:
    try:
        return (database.get_user_profile(str(user_id)) or {}).get("domain")
    except Exception:  # noqa: BLE001 -- business, the default
        return None


def carried_over(database: Any, *, user_id: str, takes: list[dict], take_index: int,
                 snippets: list[dict]) -> Optional[dict]:
    """The clearer line practised on the Take before, and whether this Take
    says it (the practice attempt's own match, no AI guess):
    {"passage", "used"}; None when there was none."""
    if take_index < 2:
        return None
    before = str(takes[take_index - 2].get("id"))
    try:
        rows = (database.client.table("confident_voice_practice")
                .select("id,kind,exact_passage,status")
                .eq("take_session_id", before).eq("owner_user_id", str(user_id))
                .eq("kind", "rewrite").execute().data or [])
        ids = [str(r["id"]) for r in rows if r.get("exact_passage") and r.get("status") != "dismissed"]
        tried = {str(a.get("practice_id")) for a in (
            database.client.table("confident_voice_practice_attempt")
            .select("practice_id").in_("practice_id", ids).execute().data or [])} if ids else set()
    except Exception as error:  # noqa: BLE001 -- unknown: nothing to say about it
        logger.warning("will question: last practice unread take=%s: %s", before, error)
        return None
    practised = next((r for r in rows if str(r.get("id")) in tried), None)
    if not practised:
        return None
    from services.exercise_held import _find_passage
    passage = str(practised["exact_passage"]).strip()
    return {"passage": passage, "used": _find_passage(passage, snippets) is not None}


def carried_fact(carried: Optional[dict]) -> list[str]:
    """For the summary: the line they practised last Take came back. Pure."""
    if not carried or not carried.get("used"):
        return []
    return [f"They used the clearer line they practised last Take in this Take: "
            f"\"{str(carried['passage'])[:300]}\". Worth saying in words."]


def plan(database: Any, *, user_id: str, arc_id: str, take: str, take_index: int,
         now: tuple, before: Optional[tuple], takes: list[dict],
         carried: Optional[dict], heard_call: Callable[[], dict],
         snippets: Optional[list[dict]] = None) -> Optional[Plan]:
    """What Will asks after this Take, or None. Best-effort: never raises."""
    try:
        rows = _thread(database, user_id, _SCAN)
        asked, asked_last = asked_on_talk(rows, arc_id)
        words = bank(database)
        goal, audience = talk_goal(takes), talk_audience(takes)
        key_line = known_key_line(database, user_id, takes)
        key = choose_key(take_index=take_index, now=now, before=before, carried=carried,
                         audience=audience, goal=goal, key_line=key_line,
                         asked=asked, asked_last=asked_last,
                         deeper=tuple(k for k in PRINCIPLES if words[k]["question"]))
        if not key:
            return None
        found = Plan(key=key, arc_id=str(arc_id), take=str(take), heard=heard_call,
                     passage=(carried or {}).get("passage"), words=words,
                     moment=moment_of(rows, str(take), snippets or []), who=audience or None)
        # The key line follows an answered first question when, with it,
        # both are known (N294 items 2 and 4); its who is read when it comes.
        key_next = not key_line and KEY_LINE not in asked
        if key == "audience":
            found.field_name = _field(database, user_id)
            found.earlier = earlier_answers(database, user_id, "audience")
            if not goal and "goal" not in asked:
                found.then = "goal"
                found.then_earlier = earlier_answers(database, user_id, "goal")
            elif goal and key_next:
                found.then = KEY_LINE
        if key == "goal":
            found.earlier = earlier_answers(database, user_id, "goal")
            if audience and key_next:
                found.then = KEY_LINE
        return found
    except Exception as error:  # noqa: BLE001 -- the Take's other asks go on
        logger.warning("will question: no plan take=%s: %s", take, error, exc_info=True)
        return None


def words_for(found: Plan) -> tuple[str, str, list[str], dict]:
    """The key, the question opened on the walk's moment, its tap answers
    and what it rests on. Pure but for collecting the heard call and the
    light touch."""
    key, text, chips, rest = _asked_words(found)
    return key, with_moment(key, text, found.moment), chips, rest


def next_words(found: Plan) -> Optional[tuple[str, str, list[str]]]:
    """The context question that follows an answered first one (N294 item
    4): what they should do, its taps from the recording first, then their
    earlier answers, then the signed ones; or the key line, no taps (N294
    item 2). It reads on from the answer, so it opens on no moment. None
    when nothing follows. Pure but for collecting the heard call and the
    light touch."""
    if found.then == KEY_LINE:
        return KEY_LINE, key_line_question(found.who), []
    if found.then != "goal":
        return None
    words = found.words or signed_bank()
    text = str((found.varied() or {}).get("goal") or words["goal"]["question"])
    got = found.heard() or {}
    return "goal", text, _chips([got.get("ask")], found.then_earlier, words["goal"]["chips"])


def _asked_words(found: Plan) -> tuple[str, str, list[str], dict]:
    key, words = found.key, found.words or signed_bank()
    if key == KEY_LINE:
        # The plan's signed words, said as signed: no tap answers, by voice.
        return key, key_line_question(found.who), [], {}
    said = {k: words[k]["question"] for k in words}
    for k, text in (found.varied() or {}).items():
        if k in said and text:
            said[k] = text
    if key in ("audience", "goal"):
        got = found.heard() or {}
        if key == "audience" and got.get("audience") and got.get("audience_times", 0) >= 2:
            phrase = str(got["audience"])
            return ("audience_check",
                    said["audience_check"].replace("{heard}", _in_sentence(their_side(phrase))),
                    list(words["audience_check"]["chips"]), {"heard": phrase})
        if key == "audience":
            signed = (AUDIENCE_BY_FIELD.get(found.field_name or "")
                      if found.field_name not in (None, "executive_presence") else None)
            taps = _chips([got.get("audience")], found.earlier, signed or words["audience"]["chips"])
            # No "Someone else": their own words go into "Something else"
            # in the bar (N406 item 2, N371; was N319 item 8).
            return key, said[key], [t for t in taps if t != SOMEONE_ELSE], {}
        if to_self(found.who):
            # A talk to themself: no "them", no taps (N406 item 4).
            return key, GOAL_SELF, [], {}
        return key, said[key], _chips([got.get("ask")], found.earlier, words["goal"]["chips"]), {}
    if key == "not_used":
        return key, said[key].replace("{words}", found.passage or ""), list(words[key]["chips"]), {}
    return key, said[key], list(words[key]["chips"]), {}


# ------------------------------------------------------------------ the bank

#: The questions the founder edits on the coach panel (N83), in the panel's
#: groups, each with when Will asks it.
LAYOUT = (
    ("Who it's for", (("audience_check", "The Take names it twice"),
                      ("audience", "Not known yet · the Take's own words come first"))),
    ("What they should do", (("goal", "Not known yet"),)),
    ("When something is off", (("pause", "Tries missed two Takes in a row"),
                               ("not_used", "Last practised line not used"))),
    ("Deeper, from Take 3", tuple((k, "Basics known") for k in PRINCIPLES)),
)
EDITABLE = tuple(k for _, items in LAYOUT for k, _ in items)
#: What the editor shows for the speaker's own words inside a question.
_SHOWN = {"audience_check": ("{heard}", "{the board}"), "not_used": ("{words}", "…")}
_MAX_QUESTION = 200


def signed_bank() -> dict:
    """The signed words, before any change of the founder's. Pure."""
    chips = {**CHIPS, "audience": AUDIENCE_BY_FIELD["executive_presence"], "goal": GOAL_CHIPS}
    return {k: {"question": QUESTIONS.get(k, ""), "chips": tuple(chips.get(k, ()))} for k in EDITABLE}


def bank(database: Any) -> dict:
    """The words Will asks: the founder's where they changed one, else the
    signed ones. Never raises."""
    words = signed_bank()
    try:
        rows = database.list_will_question_bank() or []
    except Exception as error:  # noqa: BLE001 -- the signed words
        logger.warning("will question: bank unread: %s", error)
        rows = []
    for row in rows:
        key = str(row.get("key") or "")
        if key in words:
            words[key] = {"question": str(row.get("question") or ""),
                          "chips": tuple(c for c in (row.get("chips") or []) if isinstance(c, str))}
    return words


def _shown(key: str, question: str) -> str:
    inner, shown = _SHOWN.get(key, ("", ""))
    return question.replace(inner, shown) if inner else question


def _stored(key: str, question: str) -> str:
    inner, shown = _SHOWN.get(key, ("", ""))
    return question.replace(shown, inner) if inner else question


def admin_view(database: Any) -> dict:
    """The editor's page: each group's questions, how often each was asked,
    and how many are filled. Founder only (the route)."""
    words = bank(database)
    groups = []
    for label, items in LAYOUT:
        groups.append({"label": label, "items": [{
            "key": key, "when": when, "question": _shown(key, words[key]["question"]),
            "chips": list(words[key]["chips"]), "own_words": not signed_bank()[key]["chips"],
            "empty": not words[key]["question"], "asked": _asked(database, key)}
            for key, when in items]})
    filled = sum(1 for k in EDITABLE if words[k]["question"])
    return {"groups": groups, "questions": filled, "empty": len(EDITABLE) - filled}


def _asked(database: Any, key: str) -> int:
    try:
        return int(database.count_will_questions_asked(key) or 0)
    except Exception:  # noqa: BLE001 -- the editor works without the count
        return 0


def _checked(key: str, question: Any, chips: Any) -> dict:
    """One question as the founder wrote it, checked against what Will can
    ask; raises ``QuestionError`` with what is wrong. Pure."""
    signed = signed_bank()[key]
    text = " ".join(str(question or "").split())
    if not text and not key.startswith("slot_"):
        raise QuestionError("INVALID_WORDS", "A question can't be empty.")
    if len(text) > _MAX_QUESTION or _DIGIT.search(text):
        raise QuestionError("INVALID_WORDS", "A question has no numbers and fits in two lines.")
    stored = _stored(key, text)
    inner = _SHOWN.get(key, ("", ""))
    if inner[0] and inner[0] not in stored:
        raise QuestionError("INVALID_WORDS", f"Keep {inner[1]} in this question: it is the speaker's own words.")
    raw = [str(c) for c in (chips or []) if str(c).strip()]
    clean = [chip(c) for c in raw]
    if len(clean) != len(signed["chips"]) or any(c is None for c in clean):
        raise QuestionError("INVALID_WORDS",
                            f"This question has {len(signed['chips'])} tap answers, each a few words, no numbers.")
    return {"key": key, "question": stored, "chips": clean}


def save_bank(database: Any, items: Any) -> dict:
    """The founder's words, checked, then kept; Will asks them from the next
    Take. Raises ``QuestionError``."""
    if not isinstance(items, list):
        raise QuestionError("INVALID_WORDS", "Nothing to save.")
    rows = [_checked(str(i.get("key")), i.get("question"), i.get("chips"))
            for i in items if isinstance(i, dict) and i.get("key") in EDITABLE]
    if rows and not database.save_will_question_bank(rows):
        raise QuestionError("V2_ERROR", "Could not save.", 500)
    return admin_view(database)


# ------------------------------------------------------------------ rows


def _cid(user_id: str, take: str, part: str) -> str:
    return str(uuid.uuid5(_NAMESPACE, f"{user_id}:{take}:{part}"))


def _part(name: str, rnd: int = 1) -> str:
    """A row's part in the Take's thread: the first question's as it always
    was, the one that follows it (N294 item 4) with its round. Pure."""
    return name if rnd <= 1 else f"{name}{rnd}"


def _round(meta: Optional[dict]) -> int:
    try:
        return max(1, int((meta or {}).get("will_round") or 1))
    except (TypeError, ValueError):
        return 1


def _row(client_id: str, role: str, body: str, meta: dict, at: str) -> dict:
    return {"client_id": client_id, "role": role, "kind": "text", "body": body,
            "metadata": meta, "client_created_at": at}


def ask_rows(found: Optional[Plan], *, user_id: str, at: str) -> list[dict]:
    """The question, in the shape the Lounge draws as an offer, its tap
    answers in ``metadata.chips``. Best-effort: never raises."""
    if not found:
        return []
    try:
        from services.feedback_check import _after
        key, text, chips, rest = words_for(found)
        meta = {"offer": OFFER, "will_question": key, "will_question_step": "ask",
                "chips": chips, "arc_id": found.arc_id, "take_session_id": found.take, **rest}
        return [_row(_cid(user_id, found.take, "ask"), "bot", text, meta, _after(at, 5))]
    except Exception as error:  # noqa: BLE001 -- the summary is written either way
        logger.warning("will question: not asked take=%s: %s", found.take, error, exc_info=True)
        return []


def next_rows(found: Optional[Plan], *, user_id: str, at: str) -> list[dict]:
    """The context question that follows an answered first one (N294 item
    4), put together with the summary and written when the chain reaches it
    (``after_take``, "will_next"). Best-effort: never raises."""
    if not found:
        return []
    try:
        words = next_words(found)
        if not words:
            return []
        key, text, chips = words
        meta = {"offer": OFFER, "will_question": key, "will_question_step": "ask", "will_round": 2,
                "chips": chips, "arc_id": found.arc_id, "take_session_id": found.take}
        return [_row(_cid(user_id, found.take, _part("ask", 2)), "bot", text, meta, at)]
    except Exception as error:  # noqa: BLE001 -- the first question stands alone
        logger.warning("will question: no next question take=%s: %s", found.take, error, exc_info=True)
        return []


def at_release(database: Any, rows: list[dict]) -> list[dict]:
    """Will's next question as it comes (``after_take.rows_for``), read
    again with who the answer before it said the talk is for (N294 items 2
    and 4): the key line names them; what they should do, for a talk to
    themself, has no "them" and no taps (N406 item 4). The rows. Never
    raises."""
    for row in rows:
        meta = row.get("metadata") or {}
        key = meta.get("will_question")
        if key not in (KEY_LINE, "goal") or not meta.get("take_session_id"):
            continue
        try:
            ctx = database.takes.get_session_intake_context(str(meta["take_session_id"])) or {}
        except Exception as error:  # noqa: BLE001 -- the words as put together
            logger.warning("will question: setup unread take=%s: %s", meta.get("take_session_id"), error)
            continue
        who = str((ctx if isinstance(ctx, dict) else {}).get("audience") or "").strip()
        if not who:
            continue
        if key == KEY_LINE:
            row["body"] = key_line_question(who)
        elif to_self(who):
            row["body"] = GOAL_SELF
            row["metadata"] = {**meta, "chips": []}
    return rows


def skipped(database: Any, user_id: str, take: str) -> bool:
    """Whether the speaker skipped the Take's first question or its
    follow-up: nothing more is asked after it (N294 item 4)."""
    return any(database.get_lounge_message_by_client_id(str(user_id), _cid(user_id, take, part))
               for part in ("skip-ask", "skip-follow"))


def answered_first(database: Any, user_id: str, take: str) -> bool:
    """Whether the speaker answered the Take's first question: Will's reply
    to an answer ("thanks") is in the thread, whether the answer was a tap,
    typed words (the chat's reply row, ``chat_turn``) or their voice
    (``answer_voice``). A "#" note, distress or a tap that opened the
    follow-up and nothing after it is no answer: his next question does not
    follow it (N294 item 4). Unread: not answered."""
    take = str(take)
    return any(r.get("role") == "bot"
               and (r.get("metadata") or {}).get("will_question_step") == "thanks"
               and str((r.get("metadata") or {}).get("take_session_id") or "") == take
               and _round(r.get("metadata")) == 1
               for r in _thread(database, user_id, _SCAN))


# ------------------------------------------------------------------ answers


def _save(database: Any, *, user_id: str, take: str, key: str, said: Optional[str],
          settled: bool = True, **fields: Any) -> None:
    """Kept for Will; a settled answer to who the talk is for or what they
    should do also goes into the talk's setup. Never raises."""
    payload = {"question": key, **({"said": said} if said else {}), **fields}
    if settled and said and key in ("audience", "audience_check"):
        payload["audience"] = said
        _into_setup(database, take, audience=said)
    if settled and said and key == "goal":
        payload["goal"] = said
        _into_setup(database, take, goal=said)
    if settled and said and key == KEY_LINE:
        payload[KEY_LINE] = said
        _into_setup(database, take, key_line=said)
        _into_plan(database, user_id, said)
    from services import speaker_memory
    speaker_memory.record(database, user_id, "answer", payload, take)


def _into_setup(database: Any, take: str, *, audience: Optional[str] = None,
                goal: Optional[str] = None, key_line: Optional[str] = None) -> None:
    """The talk's setup hears the answer: the next Take carries it. A merge,
    so the blob's other keys stay. Never raises."""
    try:
        ctx = dict(database.takes.get_session_intake_context(take) or {})
        if audience:
            ctx["audience"] = audience[:200]
        if goal:
            ctx["strategic_context"] = with_goal(ctx.get("strategic_context"), goal[:300])
        if key_line:
            ctx[KEY_LINE] = key_line[:300]
        database.takes.set_session_intake_context(take, ctx)
    except Exception as error:  # noqa: BLE001 -- Will still keeps the answer
        logger.warning("will question: setup not written take=%s: %s", take, error, exc_info=True)


def _into_plan(database: Any, user_id: str, key_line: str) -> None:
    """An open plan with no key line takes the one said to Will (N294 item
    2): its practice days and its walk read it from there. Never raises."""
    plan = _open_plan(database, user_id)
    facts = dict(plan.get("facts") or {}) if plan.get("id") else None
    if facts is None or str(facts.get(KEY_LINE) or "").strip():
        return
    try:
        database.update_plan(str(user_id), plan["id"], {"facts": {**facts, KEY_LINE: key_line[:300]}})
    except Exception as error:  # noqa: BLE001 -- the setup keeps it either way
        logger.warning("will question: plan not told the key line user=%s: %s", user_id, error)


def follow_up(key: str, choice: str, chips: list) -> Optional[str]:
    """The one follow-up a tap opens, by its place among the answers. Who
    the talk is for, asked before N406, may still carry "Someone else": it
    opens the check's follow-up. Pure."""
    if choice not in chips:
        return None
    if key == "audience":
        return FOLLOW_AT["audience_check"][1] if choice == SOMEONE_ELSE else None
    return FOLLOW_AT.get(key, {}).get(chips.index(choice))


def resolved(key: str, choice: str, meta: dict) -> Optional[str]:
    """What a tap says: the first answer to the check is the audience it
    heard; a tap that opens the follow-up says nothing yet. Pure."""
    if follow_up(key, choice, list(meta.get("chips") or [])):
        return None
    if key == "audience_check":
        return str(meta.get("heard") or "").strip() or None
    return choice


def _question_row(database: Any, user_id: str, take: str, rnd: int = 1) -> Optional[dict]:
    return database.get_lounge_message_by_client_id(str(user_id), _cid(user_id, take, _part("ask", rnd)))


def _answered(database: Any, user_id: str, take: str, step: str = "ask", rnd: int = 1) -> bool:
    parts = ("answer", "skip-ask") if step == "ask" else ("skip-follow",)
    return any(database.get_lounge_message_by_client_id(str(user_id), _cid(user_id, take, _part(part, rnd)))
               for part in parts)


def answer(database: Any, *, user_id: str, arc_id: str, take_session_id: str,
           choice: str) -> list[dict]:
    """A tap on one of the question's answers, or Skip: kept, then the
    thread's rows (the tap, then Will's reply or the one follow-up). A
    repeat tap writes nothing and returns []. Raises ``QuestionError``."""
    from services.feedback_check import _after
    from services.lounge_messages import thread_stamp
    take = str(take_session_id)
    still = open_question(database, user_id)
    if still and still["take_session_id"] != take:
        still = None
    # The open question's round; with none open, the Take's newest asked.
    rnd = _round(still) if still else (2 if _question_row(database, user_id, take, 2) else 1)
    asked = _question_row(database, user_id, take, rnd)
    meta = (asked or {}).get("metadata") or {}
    if not asked or meta.get("offer") != OFFER:
        raise QuestionError("NOT_FOUND", "No question for this Take.", 404)
    if choice != SKIP and choice not in (meta.get("chips") or []):
        raise QuestionError("INVALID_CHOICE", "Unknown answer.")
    if not still:
        return []  # answered, typed or passed already
    step = str(still["will_question_step"])
    if step == "follow" and choice != SKIP:
        return []  # the follow-up takes their own words
    key = str(meta.get("will_question"))
    base = {"will_question": key, "arc_id": arc_id, "take_session_id": take,
            **({"will_round": rnd} if rnd > 1 else {})}
    at = thread_stamp(database, user_id)
    if choice == SKIP:
        return _skip(database, user_id=user_id, take=take, key=key, step=step, base=base, at=at,
                     rnd=rnd)
    said = resolved(key, choice, meta)
    follow = follow_up(key, choice, list(meta.get("chips") or []))
    _save(database, user_id=user_id, take=take, key=key, said=said or choice,
          settled=said is not None, tapped=True)
    mine = _row(_cid(user_id, take, _part("answer", rnd)), "user", choice,
                {**base, "will_question_step": "answer"}, at)
    reply = (_row(_cid(user_id, take, _part("follow", rnd)), "bot", follow,
                  {**base, "offer": OFFER, "will_question_step": "follow", "chips": []},
                  _after(at, 1)) if follow
             else _row(_cid(user_id, take, _part("thanks", rnd)), "bot", said_back(key, said),
                       {**base, "will_question_step": "thanks"}, _after(at, 1)))
    rows = database.insert_lounge_messages(user_id, [mine, reply]) or []
    return rows if follow else rows + _let_go(database, user_id, take)


def _skip(database: Any, *, user_id: str, take: str, key: str, step: str, base: dict,
          at: str, rnd: int = 1) -> list[dict]:
    """Skip under the question or its follow-up: kept, nothing more is
    asked, and the message after the Take comes."""
    _save(database, user_id=user_id, take=take, key=key, said=None, skipped=True,
          **({"follow_up": True} if step == "follow" else {}))
    rows = database.insert_lounge_messages(user_id, [_row(
        _cid(user_id, take, _part(f"skip-{step}", rnd)), "user", SKIP,
        {**base, "will_question_step": "skip"}, at)]) or []
    return rows + _let_go(database, user_id, take)


def _let_go(database: Any, user_id: str, take: str) -> list[dict]:
    """The chain after the Take goes on under the answer (N89): the next
    question when one follows, else the message after the Take."""
    from services import after_take
    if after_take.held(database, user_id, take) is None:
        return []
    return after_take.release(database, user_id, take=take)


def _review_card(row: dict) -> bool:
    return row.get("kind") == "walk_step" and (row.get("metadata") or {}).get("step") == "end"


def waits(database: Any, user_id: str, take: str) -> bool:
    """Will's question on ``take`` was asked and nothing has answered it yet
    (N406 item 1, N544): more questions than closings among that Take's
    rows, a closing being his reply to an answer ("thanks", for a tap, typed
    words or the voice alike) or a Skip; a follow-up keeps it open. Read
    without the rows' order, which a typed answer's phone clock can bend.
    Unread: no."""
    take = str(take)
    steps = [(r.get("metadata") or {}).get("will_question_step")
             for r in _thread(database, user_id, _SCAN)
             if str((r.get("metadata") or {}).get("take_session_id") or "") == take]
    return steps.count("ask") > steps.count("thanks") + steps.count("skip")


def open_question(database: Any, user_id: str) -> Optional[dict]:
    """The newest bot row when it is Will's question or its follow-up, still
    open; None otherwise. The speaker's own rows are skipped (the client
    stores the turn before asking), and so is the review's card."""
    rows = _thread(database, user_id, _LOOKBACK)
    bot = next((r for r in rows if r.get("role") == "bot" and not _review_card(r)), None)
    meta = (bot or {}).get("metadata") or {}
    step, take = meta.get("will_question_step"), meta.get("take_session_id")
    if meta.get("offer") != OFFER or step not in ("ask", "follow") or not take:
        return None
    if _answered(database, user_id, str(take), step, _round(meta)):
        return None
    return {**meta, "take_session_id": str(take)}


def _said_as_chip(text: str, chips: list[str]) -> Optional[str]:
    said = _norm(text)
    return next((c for c in chips if _norm(c) == said), None)


def _not_an_answer(text: str) -> bool:
    """Words that are never an answer to Will: distress (the chat's safety
    reply answers it, never a thank-you) and a "#" note (the founder's
    notebook)."""
    from services.chat_intents import detect_chat_intent
    return text.lstrip().startswith("#") or (detect_chat_intent(text) or {}).get("intent") == "crisis"


def chat_turn(database: Any, user_id: str, question: str) -> Optional[dict]:
    """The chat's intercept: what the speaker types under Will's question
    (or its follow-up) is their answer. {"answer", "row_metadata"}, or None
    when no question is open (the turn goes on to the next voice)."""
    if not user_id or not question.strip() or _not_an_answer(question):
        return None
    open_q = open_question(database, str(user_id))
    if not open_q:
        return None
    return _taken(database, str(user_id), open_q, question, typed=True)


def _taken(database: Any, user_id: str, open_q: dict, text: str, **how: Any) -> dict:
    """The speaker's own words (typed or said) under the open question,
    kept: {"answer": Will's reply, "row_metadata": the reply row's}. Words
    that say one of the tap answers are that tap (its follow-up included)."""
    take, key = open_q["take_session_id"], str(open_q.get("will_question"))
    rnd = _round(open_q)
    base = {"will_question": key, "arc_id": open_q.get("arc_id"), "take_session_id": take,
            **({"will_round": rnd} if rnd > 1 else {})}
    tapped = _said_as_chip(text, list(open_q.get("chips") or []))
    follow = follow_up(key, tapped, list(open_q.get("chips") or [])) if tapped else None
    if open_q["will_question_step"] == "ask" and follow:
        _save(database, user_id=user_id, take=take, key=key, said=tapped, settled=False, **how)
        return {"answer": follow,
                "row_metadata": {**base, "offer": OFFER, "will_question_step": "follow", "chips": []}}
    said = (resolved(key, tapped, open_q) or tapped) if tapped else text.strip()[:_MAX_SAID]
    if key == "audience_check" and not tapped:
        key = "audience"  # their own words name who it is for
    _save(database, user_id=user_id, take=take, key=key, said=said, **how,
          **({"follow_up": True} if open_q["will_question_step"] == "follow" else {}))
    return {"answer": said_back(key, said), "row_metadata": {**base, "will_question_step": "thanks"}}


# ------------------------------------------------------------------ by voice

#: A voice answer is a short recording: up to five minutes, as the plan's.
_VOICE_MAX_SECONDS = 300
_VOICE_MAX_BYTES = 12 * 1024 * 1024
#: The words the speaker's voice bubble keeps.
_VOICE_WORDS = 2000
_VOICE_SURFACE = "will_question_answer"


def answer_voice(database: Any, adapter: Any, audio: bytes, *, user_id: str, arc_id: str,
                 take_session_id: str, filename: str,
                 duration_ms: Optional[int] = None) -> list[dict]:
    """An answer to Will's open question by voice (N294 items 2 and 3, N319
    item 1): transcribed under the caller's processing authorization
    (``adapter``, the route's ``phase1_provider_route``), kept as typed
    words are, and written as the speaker's voice bubble with the words
    heard, then Will's reply, then the chain after the Take. The recording
    is not kept. Raises ``QuestionError``."""
    take = str(take_session_id)
    open_q = open_question(database, str(user_id))
    if not open_q or open_q["take_session_id"] != take:
        raise QuestionError("NOT_FOUND", "No question for this Take.", 404)
    words, duration = _heard_words(adapter, audio, user_id=str(user_id), take=take,
                                   filename=filename, duration_ms=duration_ms)
    from services.feedback_check import _after
    from services.lounge_messages import thread_stamp
    rnd, step = _round(open_q), str(open_q["will_question_step"])
    at = thread_stamp(database, user_id)
    mine = _row(_cid(user_id, take, _part("said" if step == "ask" else "said-follow", rnd)), "user", words,
                {"will_question": open_q.get("will_question"), "arc_id": open_q.get("arc_id") or arc_id,
                 "take_session_id": take, "will_question_step": "answer", "will_voice": True,
                 **({"duration_ms": duration} if duration else {}),
                 **({"will_round": rnd} if rnd > 1 else {})}, at)
    if _not_an_answer(words):
        return database.insert_lounge_messages(user_id, [mine] + _safety_rows(user_id, take, rnd, words, at)) or []
    turn = _taken(database, str(user_id), open_q, words, voice=True)
    meta = turn["row_metadata"]
    follows = meta.get("will_question_step") == "follow"
    part = "follow" if follows else ("thanks" if step == "ask" else "thanks-follow")
    reply = _row(_cid(user_id, take, _part(part, rnd)), "bot", turn["answer"], meta, _after(at, 1))
    rows = database.insert_lounge_messages(user_id, [mine, reply]) or []
    return rows if follows else rows + _let_go(database, user_id, take)


def _heard_words(adapter: Any, audio: bytes, *, user_id: str, take: str, filename: str,
                 duration_ms: Optional[int]) -> tuple[str, Optional[int]]:
    """The words of a voice answer and its length, heard under the caller's
    authorization (the plan's own transcriber call). Raises
    ``QuestionError`` when it is empty, too long, or no words are heard."""
    if not audio:
        raise QuestionError("EMPTY_AUDIO", "No audio.")
    if len(audio) > _VOICE_MAX_BYTES or (duration_ms or 0) > (_VOICE_MAX_SECONDS + 5) * 1000:
        raise QuestionError("TOO_LONG", "Up to five minutes.", 413)
    from services.plan_flow import _heard, _words
    if not _heard(audio):
        raise QuestionError("NO_WORDS", "No words heard.", 422)
    result = adapter.transcribe_audio(audio, filename, usage_surface=_VOICE_SURFACE,
                                      usage_user_id=user_id, usage_session_id=take) or {}
    words = " ".join(_words(result).split())[:_VOICE_WORDS]
    if not words:
        raise QuestionError("NO_WORDS", "No words heard.", 422)
    return words, duration_ms or int(float(result.get("duration") or 0) * 1000) or None


def _safety_rows(user_id: str, take: str, rnd: int, words: str, at: str) -> list[dict]:
    """Distress is never an answer: the chat's safety reply, and the asks
    wait until the speaker writes again (N94)."""
    from services.chat_intents import detect_chat_intent
    from services.feedback_check import _after
    safety = str((detect_chat_intent(words) or {}).get("answer") or "")
    return [_row(_cid(user_id, take, _part("said-safety", rnd)), "bot", safety,
                 {"intent": "crisis"}, _after(at, 1))] if safety else []


#: What the chat knows about Will's question (founder 2026-10-20), as facts
#: for Will's prompt block; never shown as they are.
CHAT_FACTS = (
    "  • After a Take, you may ask the speaker one question when something is "
    "off or missing: who the talk is for, what they want the audience to do "
    "or feel, whether leaving out a line they practised was on purpose, "
    "whether they need a breather, or why the talk matters to them. "
    "Answering is optional and never needed to record the next Take.\n"
    "  • Their answers are private: you learn from them (your note on this "
    "speaker) and never repeat them back.\n"
)
