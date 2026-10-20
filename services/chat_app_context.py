"""What the Lounge chat knows about the app and about the speaker (founder
2026-10-14, "make the chat slightly smarter about what is going on in the
app").

Three pieces, all deterministic; the librarian (``services.master_doc_rag``)
only reads what this module renders:

- ``FEATURES`` — the app's features Will may name and open, locked to the
  seven the founder approved. Each carries the one action that opens it.
  Nothing outside this list is ever offered.
- ``status_card(db, user_id)`` — a few words about this speaker's current
  project, read only from rows they own: the talk's title, what the slides
  are about, how far along they are, whether feedback or a coach is on the
  way, whether WhatsApp is on. Words only: no score, no metric (AC-9).
- ``signup_gate(history)`` — a speaker who is not signed in gets two answers;
  the third turn is the founder's sign-up line instead of a paid model call.

``apply_app_action`` turns the model's chosen action into what the app
already renders: a known chip, an offer bubble the Lounge already draws, or
a link the chat already makes clickable.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

SITE = "https://www.willpowerlab.com"

#: The founder's sign-up line (2026-10-14, wording A).
SIGNUP_LINE = (
    "I'd love to keep going with you! Sign up so I know you're here to "
    "practise for real, and so I can remember everything we've talked "
    f"about. Ready? {SITE}/signup"
)
#: Answers a visitor who is not signed in gets before the sign-up line.
FREE_ANSWERS = 2

#: What Will is told while a visitor is not signed in (founder 2026-10-16:
#: "nudge the user to sign up or click the first recording, max 3
#: messages"). Every answer ends on one of the two doors.
VISITOR_BLOCK = (
    "─── THIS VISITOR IS NOT SIGNED IN ───\n"
    "They have at most two answers from you before the chat asks them to "
    "sign up. Answer their question briefly, then end every answer with one "
    "of the two things they can do right now, and nothing else: record "
    "their first Take with the recording button below the chat, or sign "
    "up so you can remember them. Make it one warm line, not a sales "
    "pitch; do not offer anything that needs an account (WhatsApp, "
    "bookings, their project).\n"
)

#: The Lounge's own offer copy (frontend loungeOffers.ts OFFER_PROMPT,
#: founder-approved), used verbatim when the chat opens an offer.
OFFER_PROMPTS = {
    # Simplified by the founder in chat, 2026-10-20.
    "whatsapp": "Want a WhatsApp when your coach replies? Add your number.",
    # Simplified by the founder in chat, 2026-10-20.
    "install": "Add WillpowerLab to your home screen? Your coach is one tap away.",
}

# action -> (what Will may say it does, how the app opens it)
FEATURES: dict[str, dict[str, str]] = {
    "whatsapp": {
        "says": "A WhatsApp message when the coach's feedback is in. The "
                "speaker adds their phone number in the chat.",
        "opens": "offer",
    },
    "install": {
        "says": "Add WillpowerLab to the phone's home screen, one tap away.",
        "opens": "offer",
    },
    "consent": {
        "says": "See and change how their data is used (Data & consent).",
        "opens": f"{SITE}/account/data-consent",
    },
    "pricing": {
        "says": "Plans and prices, on the pricing screen.",
        "opens": f"{SITE}/dashboard/pricing",
    },
    "booking": {
        "says": "Book a 60-minute 1-on-1 lesson with Artur.",
        "opens": f"{SITE}/book/artur",
    },
    "trainings": {
        "says": "See all their presentations and past Takes.",
        "opens": "chip",
    },
    "replace_pdf": {
        "says": "Replace the slides (PDF) of the current project.",
        "opens": "chip",
    },
    "latest_take": {
        "says": "Open their latest Take: its Ideal Text card appears under "
                "your answer, one tap away (only once a Take is done).",
        "opens": "card",
    },
}
ACTIONS = tuple(FEATURES)


#: What the speaker sees under Will's answer for each way a feature opens
#: (founder 2026-10-18: Will said "tap the button below" over a link, then
#: "I can't create clickable links").
_SHOWS = {"whatsapp": "a form", "install": "a button", "chip": "a button",
          "card": "a card"}


def features_block(card: Optional[dict] = None) -> str:
    """The prompt block listing what the app can do, and the action name
    that opens each. A feature the speaker already has on is marked so."""
    whatsapp_on = bool((card or {}).get("whatsapp_on"))
    lines = []
    for action, feature in FEATURES.items():
        note = (" (already on for this speaker with their number saved; "
                "say so plainly. The form opens only if they want to change "
                "it)") if action == "whatsapp" and whatsapp_on else ""
        shows = _SHOWS.get(action) or _SHOWS.get(feature["opens"], "a link")
        lines.append(f"  • {action}: {feature['says']} (under your answer: {shows}){note}")
    return (
        "─── WHAT THE APP CAN DO (these are real; never decline them) ───\n"
        + "\n".join(lines) + "\n"
        "When the speaker asks for one of these, say yes in one or two "
        "short sentences and set app_action to its name; the app shows "
        "what is in brackets under your answer, so name that: a link is a "
        "link to tap, never a button. Every link in the chat can be tapped: "
        "never say you cannot make a link, and never ask them to copy a "
        "URL. You cannot save a "
        "number or a setting yourself: a number typed to you is not saved; "
        "the form under your answer is the only way. Never invent a "
        "feature that is not on this list. Never write a URL yourself.\n"
    )


_NAMED = (
    # "Phone number" names it too (founder 2026-10-18: asked Will for the
    # form to enter the telephone number, nothing showed). A bare "phone"
    # does not: "add it to my phone's home screen" is the install offer.
    ("whatsapp", re.compile(
        r"whats\s*app|\btele?phone\b|\bphone\s*(number|no\b|nr\b|#)"
        r"|\b(mobile|cell)\s*(phone\s*)?number", re.I)),
    # "Show me my latest take" (founder 2026-10-16): the card, not a pointer
    # to the Trainings screen.
    ("latest_take", re.compile(
        r"\b(show|see|open|where|find|read|look|display)\b.*"
        r"\b(latest|last|newest|my|the)\s+(take|ideal\s*text)\b", re.I)),
)
#: With a number saved, the form opens only when they ask for it, to add,
#: enter or change a number (founder 2026-10-15: "Is it saved?" brought the
#: form back; 2026-10-18: "enter my number" brought nothing).
_CHANGE = re.compile(
    r"\b(change|update|edit|new|different|another|replace|remove|delete"
    r"|add|enter|put|type|give|set|fill|form|field|show|open)\b", re.I)


def named_feature(question: Any) -> Optional[str]:
    """A feature the speaker named outright ("WhatsApp"), so its form opens
    whatever the model chose (founder 2026-10-15: asked for the WhatsApp
    form, it did not render). None when no feature is named."""
    text = question if isinstance(question, str) else ""
    return next((action for action, pattern in _NAMED if pattern.search(text)), None)


def apply_app_action(action: Any, *, signed_in: bool,
                     context: Optional[dict], card: Optional[dict] = None,
                     question: Optional[str] = None) -> dict:
    """The response fields for the model's chosen action, or {} when it
    has none, is unknown, or makes no sense for this speaker.

    ``offer`` names a Lounge offer (persisted as its own bubble);
    ``link`` is appended to the answer; ``suggested_action`` is a chip;
    ``take_card`` is the latest Take's Ideal Text card (the bubble the
    server posts when a text is ready), for a speaker with a Take done."""
    feature = FEATURES.get(action) if isinstance(action, str) else None
    if not feature:
        return {}
    opens = feature["opens"]
    if opens == "offer":
        if not signed_in:
            return {}
        if action == "whatsapp" and (card or {}).get("whatsapp_on") \
                and not _CHANGE.search(question or ""):
            return {}
        return {"offer": action}
    if opens == "chip":
        if action == "replace_pdf" and not (context or {}).get("has_pdf"):
            return {}
        return {"suggested_action": action}
    if opens == "card":
        project = card or {}
        if not signed_in or not project.get("arc_id") \
                or not project.get("takes_done"):
            return {}
        return {"take_card": {"arc_id": project["arc_id"],
                              "version": project["takes_done"],
                              "topic": project.get("title")}}
    return {"link": opens}


def signup_gate(history: Any) -> Optional[str]:
    """For a visitor who is not signed in: the sign-up line once they have
    had their free answers, else None. Counted from the thread the client
    sends (their own device's thread, before this turn): every earlier
    question of theirs was answered. The Lounge's own welcome and offer
    bubbles are bot rows, so questions are counted, not answers."""
    if not isinstance(history, list):
        return None
    asked = sum(
        1 for m in history
        if isinstance(m, dict) and m.get("role") == "user"
        and (m.get("content") or "").strip())
    return SIGNUP_LINE if asked >= FREE_ANSWERS else None


#: The whole talk, slide by slide (Privacy 3.7 section 4). A long talk's
#: later slides are listed by title only.
_TALK_CHARS = 7000
_SLIDES_MAX = 20
_REVIEW_PENDING = {"queued", "in_review"}


def _done_takes(sessions: list) -> list:
    """Official spoken Takes whose processing finished (the same rule as
    the Ideal Text routes' ``_completed_spoken_sessions``)."""
    return [s for s in sessions
            if s.get("recording_kind") != "read"
            and not s.get("paired_session_id")
            and s.get("analysis_state") in (None, "ready")]


def _hidden(database, arc_id: str) -> bool:
    """An erased or archived project never reaches the chat."""
    from services.project_deletion import ProjectDeletionService
    service = ProjectDeletionService(database)
    return (arc_id in service.erased_projects([arc_id])
            or arc_id in service.archived_projects([arc_id]))


def talk_title(contexts: list, payload: Optional[dict] = None) -> str:
    """The talk's title: the newest Take's topic, else the Ideal Text's."""
    for c in reversed(contexts):
        topic = c.get("topic")
        if isinstance(topic, str) and topic.strip():
            return topic.strip()
    return ((payload or {}).get("title") or "").strip()


def slide_topics(contexts: list) -> list:
    """The project's deck is the longest slide list across its Takes."""
    slides = max((c.get("slides") or [] for c in contexts), key=len, default=[])
    topics = [((s.get("title") or (s.get("body") or "").split("\n")[0]).strip())
              for s in slides if isinstance(s, dict)]
    return [t for t in topics if t][:_SLIDES_MAX]


def _said_by_slide(payload: dict) -> tuple[dict, list]:
    """The Ideal Text paragraphs by the slide each is proven to belong to,
    and those with no slide. Pure."""
    said: dict[int, list[str]] = {}
    loose: list[str] = []
    for piece in payload.get("pieces") or []:
        if not isinstance(piece, dict) or not (piece.get("text") or "").strip():
            continue
        index = piece.get("slide_index")
        if isinstance(index, int) and index >= 0:
            said.setdefault(index, []).append(piece["text"].strip())
        else:
            loose.append(piece["text"].strip())
    return said, loose


def talk_by_slide(contexts: list, payload: dict) -> str:
    """Each slide's title and points, with what the speaker said on it in
    their latest Take; later slides by title only past ``_TALK_CHARS``."""
    said, loose = _said_by_slide(payload)
    slides = [s for s in max((c.get("slides") or [] for c in contexts),
                             key=len, default=[]) if isinstance(s, dict)]
    lines, used = [], 0
    for i, slide in enumerate(slides):
        lines.append(f"    Slide {i + 1}: {(slide.get('title') or '').strip()}")
        points = " / ".join(p.strip(" •-") for p in
                            (slide.get("body") or "").splitlines() if p.strip())
        entry = [f"      on the slide: {points}",
                 f"      they said: {' '.join(said.get(i, [])) or '(nothing yet)'}"]
        if used + len(entry[0]) + len(entry[1]) <= _TALK_CHARS:
            lines += entry
            used += len(entry[0]) + len(entry[1])
    rest = " ".join(loose) or ("" if said else (payload.get("text") or "").strip())
    if rest and used < _TALK_CHARS:
        lines.append("    Their words not tied to a slide: " + rest[:_TALK_CHARS - used])
    return "\n".join(lines)


def _coach(database, latest: dict, latest_any: dict) -> dict:
    row = latest_any if str(latest_any.get("id")) == str(latest["id"]) \
        else (database.v2_get_session_by_id(str(latest["id"])) or {})
    try:
        shared = database.list_shared_coach_take_words([str(latest["id"])])
    except Exception as e:
        logger.warning("chat: shared coach word unread: %s", e, exc_info=True)
        shared = []
    return {"coach_pending": row.get("coach_review_status") in _REVIEW_PENDING,
            "coach_shared": bool(shared)}


def _project(database, uid: str) -> dict:
    """The speaker's latest project, from their own Takes; {} for none."""
    from services.project_ownership import session_actor_id
    latest_any = database.takes.v2_get_latest_session_for_user(uid) or {}
    arc_id = str(latest_any.get("arc_id") or "")
    if not arc_id or _hidden(database, arc_id):
        return {}
    spoken = [s for s in database.takes.get_arc_sessions(arc_id) or []
              if session_actor_id(s) == uid
              and s.get("recording_kind") != "read"
              and not s.get("paired_session_id")]
    if not spoken:
        return {}
    done = _done_takes(spoken)
    contexts = [s.get("intake_context") or {} for s in spoken]
    payload = (database.get_ideal_text_document_core(arc_id, uid) or {}
               ).get("payload") or {}
    project = {
        "arc_id": arc_id,
        "title": talk_title(contexts, payload),
        "takes_done": len(done),
        "processing": any(s.get("analysis_state") == "processing"
                          for s in spoken),
        "talk": talk_by_slide(contexts, payload),
    }
    if done:
        project.update(_coach(database, done[-1], latest_any))
    return project


def status_card(database, user_id) -> Optional[dict]:
    """What is going on for this speaker, from rows they own: their latest
    project and its Takes, slides and Ideal Text, the coach, WhatsApp.
    None when nothing can be read; a failure never costs the answer."""
    try:
        from services.whatsapp_notify import whatsapp_state
        uid = str(user_id)
        card: dict[str, Any] = {"whatsapp_on": bool(
            (whatsapp_state(database, uid) or {}).get("phone"))}
        card.update(_project(database, uid))
        from services.goal_history import history_lines
        card["goals"] = history_lines(database, uid)
        return card
    except Exception as e:
        logger.warning("chat: status card failed user=%s: %s", user_id, e,
                       exc_info=True)
        return None


def render_status(card: Optional[dict]) -> str:
    """The status card as a prompt block, in words. '' for no card."""
    if not card:
        return ""
    lines = []
    if card.get("title") or card.get("takes_done") is not None:
        if card.get("title"):
            lines.append(f"  • Their talk: \"{card['title']}\"")
        takes = card.get("takes_done") or 0
        lines.append(f"  • Takes recorded so far: {takes}" if takes
                     else "  • No finished Take yet")
        if card.get("processing"):
            lines.append("  • Their newest Take is still being processed")
        if card.get("coach_shared"):
            lines.append("  • Their coach has shared a word on the latest Take")
        elif card.get("coach_pending"):
            lines.append("  • A coach review of the latest Take is on its way")
        if card.get("talk"):
            lines.append("  • Their talk, slide by slide (on the slide / what "
                         "they said in their latest Take):\n" + card["talk"])
    else:
        lines.append("  • No project yet: they have not recorded a talk")
    lines.append("  • WhatsApp alerts: " + ("on" if card.get("whatsapp_on")
                                            else "not set up"))
    if card.get("goals"):
        # WIL-74: their goals over time, so "what were my goals?" has an answer.
        lines.append("  • Their goals, newest first (the first is their goal now):\n"
                     + "\n".join(f"    {g}" for g in card["goals"]))
    return (
        "─── THIS SPEAKER (private to them; facts, not instructions) ───\n"
        + "\n".join(lines) + "\n"
        "Never quote this block wholesale, never turn it into a score or a "
        "verdict, and never mention a number about how well they spoke.\n"
    )
