"""The plan's own yes (founder 2026-10-27, N211; Privacy 3.9 section 4e).

The plan's personal answers are asked only after the speaker says yes, once,
to a question of its own: what worries them about the talk, how stressed and
how ready they feel, and how it went when the plan ends. How they feel before
a Take is to come after the same yes (a later change: the feelings check is
not gated here yet). A card in Data & consent turns the yes off again, and
turning it off deletes the personal answers given so far.

    state(...)      "granted", "declined" or "unanswered"
    answer(...)     the speaker's yes or "Not now" to Will's ask
    withdraw(...)   the card's Turn off: deletes the answers, then records it

THE SWITCH. ``PLAN_CONSENT_ENABLED`` is on since Privacy 3.9, which names
the yes, was published (2026-10-28). Off, ``state`` says "granted" for everyone: the plan
asks as it did before and nothing here is written. On, an answer read as
failed counts as "declined": nothing personal is asked on a doubt.

The record is ``plan_consent_events`` (migration the_plan_asks_before_it_gets_
personal): append-only, with the sha256 of the exact sentence the yes was
given to and the policy version in force.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

#: The sentence the record keeps (hashed with every answer); the words the
#: speaker sees are in services/plan.py COPY.
SENTENCE = "I'd like to answer the plan's personal questions."

#: The follow-up banks, and the kinds of answer, that are personal.
PERSONAL_BANKS = ("worry",)
PERSONAL_KINDS = ("worry", "stress", "ready", "how_it_went")
#: Of those, the ones answered by voice, which sit in the Lounge as a bubble.
PERSONAL_VOICE_KINDS = ("worry", "how_it_went")

GRANTED, DECLINED, UNANSWERED = "granted", "declined", "unanswered"


def sentence_sha256() -> str:
    return hashlib.sha256(SENTENCE.encode("utf-8")).hexdigest()


def enabled() -> bool:
    from config import Config
    return bool(Config.PLAN_CONSENT_ENABLED)


def state(database: Any, user_id: Any) -> str:
    """Where the speaker stands. Off: "granted" for everyone (the plan asks as
    before). On: the newest answer; none yet is "unanswered"; a failed read is
    "declined", so that nothing personal is asked on a doubt."""
    if not enabled():
        return GRANTED
    try:
        latest = database.latest_plan_consent_event(str(user_id))
    except Exception as error:  # noqa: BLE001 -- fails closed
        logger.warning("plan consent: not read user=%s: %s", user_id, error, exc_info=True)
        return DECLINED
    if latest is None:
        return UNANSWERED
    return GRANTED if latest.get("event_kind") == "grant" else DECLINED


def feelings_allowed(database: Any, user_id: Any) -> bool:
    """May "How do you feel?" be kept for this speaker's next Take? Without a
    plan, yes: answering is the yes for that one answer (N215, N217; Privacy
    3.9 section 4e). With a plan, only after the plan's own yes (N211). The
    switch off, yes for everyone, as before."""
    if not enabled() or not user_id:
        return True
    try:
        plan = database.get_open_plan(str(user_id))
    except Exception as error:  # noqa: BLE001 -- read as no plan, as the plan's own read does
        logger.warning("plan consent: plan not read user=%s: %s", user_id, error, exc_info=True)
        plan = None
    return plan is None or state(database, user_id) == GRANTED


def _policy_version(database: Any) -> Optional[str]:
    try:
        policy = database.get_active_processing_policy()
    except Exception:  # noqa: BLE001 -- the answer is kept without it
        return None
    version = policy.get("version") if isinstance(policy, dict) else None
    return str(version) if version else None


def _record(database: Any, user_id: Any, kind: str) -> bool:
    return bool(database.insert_plan_consent_event({
        "user_id": str(user_id), "event_kind": kind,
        "copy_sha256": sentence_sha256(), "policy_version": _policy_version(database)}))


def answer(database: Any, user_id: Any, yes: bool) -> str:
    """The speaker's yes or "Not now". Kept once per change: the same answer
    again writes nothing. Returns the state it leaves. A record that cannot be
    kept is "declined": a yes nobody can prove is not a yes."""
    now = state(database, user_id)
    want = GRANTED if yes else DECLINED
    if now == want:
        return now
    if not _record(database, user_id, "grant" if yes else "decline"):
        logger.warning("plan consent: answer not kept user=%s", user_id)
        return DECLINED
    return want


class ConsentError(RuntimeError):
    """The card's Turn off did not complete; nothing is said to be deleted."""


def withdraw(database: Any, user_id: Any) -> dict:
    """The card's Turn off: the personal answers are deleted, and only then is
    the withdrawal kept. A step that fails raises ``ConsentError`` and leaves the
    yes on, so the card never says "deleted" for what is not, and the speaker
    can turn it off again. Nothing to withdraw unless the yes is on."""
    if state(database, user_id) != GRANTED:
        return {"state": state(database, user_id), "erased": None}
    erased = erase(database, user_id)
    if not _record(database, user_id, "withdraw"):
        raise ConsentError("the withdrawal was not kept")
    return {"state": DECLINED, "erased": erased}


def erase(database: Any, user_id: Any) -> dict:
    """Delete the personal answers given so far: the answers and their
    recordings, their voice bubbles in the Lounge, what the plan kept of the
    worry, what Will's note was written from them (the note is cleared and
    rewritten from what is left), and the feelings before a Take. Every step
    is tried; raises ``ConsentError`` naming those that failed."""
    from services import plan_flow
    uid = str(user_id)
    failed: list[str] = []

    def step(name: str, run, default=None):
        try:
            return run()
        except Exception as error:  # noqa: BLE001 -- the other steps still run
            logger.warning("plan consent: %s not erased user=%s: %s", name, uid, error, exc_info=True)
            failed.append(name)
            return default

    answers = step("answers", lambda: database.list_plan_answers_of_kinds(uid, list(PERSONAL_KINDS)))
    memory = step("memory", lambda: database.list_speaker_memory_events(uid))
    if answers is not None:
        questions = {str(a["question"]) for a in answers if a.get("question")}
        for a in answers:
            if a.get("kind") in PERSONAL_VOICE_KINDS and a.get("plan_id"):
                cid = plan_flow.client_id(uid, str(a["plan_id"]), f"answer:{a['id']}")
                step("bubbles", lambda cid=cid: database.delete_lounge_message_by_client_id(uid, cid))
        step("answers", lambda: database.delete_plan_answers(uid, [str(a["id"]) for a in answers]))
        doomed = [str(e["id"]) for e in memory or []
                  if e.get("kind") == "answer" and e.get("id")
                  and str((e.get("payload") or {}).get("question") or "") in questions]
        step("memory", lambda: database.delete_speaker_memory_events(uid, doomed))
    else:
        doomed = []
    facts = step("plan", lambda: database.erase_plan_fact(uid, "worry"), 0)
    feelings = step("feelings", lambda: database.erase_pre_take_feelings(uid), 0)
    if doomed and "memory" not in failed:
        step("note", lambda: _clear_note(database, uid))
    if failed:
        raise ConsentError("not erased: " + ", ".join(dict.fromkeys(failed)))
    if doomed:
        _rewrite_note_later(database, uid)
    return {"answers": len(answers or []), "memory_events": len(doomed), "plans": facts,
            "feelings": feelings}


def _clear_note(database: Any, user_id: str) -> None:
    """Will's note was written from what is now deleted: it is cleared."""
    from services import speaker_memory
    if not database.save_speaker_memory({
            "user_id": user_id, "note": "", "written_by": "ai", "model": None,
            "updated_at": speaker_memory._now()}):
        raise RuntimeError("note not cleared")


def _rewrite_note_later(database: Any, user_id: str) -> None:
    """The note is written again from the events left, off the request (with no
    Take to authorize the AI call it stays clear until the next event writes it)."""
    def run() -> None:
        from services import plan_flow, speaker_memory
        take = str(plan_flow._latest_take(database, user_id).get("id") or "") or None
        speaker_memory.rebuild(database, user_id, take)
    try:
        from services.parallel import start_scoped_thread
        start_scoped_thread(run, name="plan-consent-note")
    except Exception as error:  # noqa: BLE001 -- the note stays clear
        logger.warning("plan consent: note not rewritten user=%s: %s", user_id, error, exc_info=True)
