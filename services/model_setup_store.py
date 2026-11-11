"""Starting a model: the store behind the setup (N528 item 4, N566 items 2 to
6, N570, N571, N582, N585). It reads and writes ``ai_models.setup`` (0520)
and ``ai_models.recipe`` (0516); the rules and words are
``services/model_setup.py``.

  * ``begin``         "Start your own": a draft model, owned by the caller;
                      after a first Take, Describe opens filled from its
                      answers (MOD-24, MOD-54)
  * ``state``         the draft at its step, or at the step asked (Continue,
                      MOD-25; a checklist item, MOD-36)
  * ``save``          one step's answer, then the next step; after the third
                      answer the app drafts the rest and may slide up "A
                      model like yours already exists" (MOD-26 to MOD-35,
                      MOD-38)
  * ``start_now``     "Start with this, finish the rest later" (MOD-28, MOD-36)
  * ``read_study``    a study read into starting rules (MOD-30)
  * ``read_data``     an existing dataset read, mapped and checked (MOD-31)
  * ``first_ten``     the owner's first 10, on the teachers' screen (MOD-38, MOD-55)
  * ``owner_view``    the owner's part of a model's page (MOD-36, MOD-37)

Inviting teachers (N598): "Copy an invite link" is the owner's own chat link
(``chat_link`` on the invite step; GET /v2/chats/link makes it), never a
link of its own; the people ticked from the owner's chats get an invite in
the list, which they accept or put off.

Ring row ``ai_models`` (ring 6): anyone else gets 404, as for the list. A
draft is the owner's alone: anyone else gets 404 for it.

PROVIDER CALLS. Two, both text only, both under the caller's processing
authorization (the request's own scope when there is one, else one built
the way the chat's is, ``_authorized``), and both with a rule-based fallback
when not authorized or the call fails:
  * ``model_setup_draft``: the three answers (and, after a first Take, its
    five answers) to a draft of the rest: the name, what one example is, the
    parts, the scale's words, the teachers' question, the list, the journey;
  * ``model_setup_rules``: a study's text to starting rules, each with its
    source and who it was measured on.
No recording passes through here. An uploaded dataset is read here and never
sent to a provider; its rows become the model's private examples.
"""
from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from services import model_launchpad as rules
from services import model_launchpad_store as lp
from services import model_setup as S
from services.chats import ChatsError, _not_found, _rows, _table, _uuid

logger = logging.getLogger(__name__)

MODELS, TEACHERS, EXAMPLES, ANSWERS, INVITES = (lp.MODELS, lp.TEACHERS, lp.EXAMPLES, lp.ANSWERS, lp.INVITES)
_FIELDS = "id,name,owner_id,owner_name,visibility,status,field,description,draft_step,recipe,targets,setup"
_SURFACE_DRAFT = "model_setup_draft"
_SURFACE_RULES = "model_setup_rules"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bad(code: str, message: str) -> ChatsError:
    return ChatsError(code, message)


def _owned(database: Any, me: str, model_id: Any) -> dict:
    """The caller's own model with its setup, or 404 (a model that is not
    theirs and one that does not exist answer the same)."""
    mid = _uuid(model_id)
    rows = _rows(_table(database, MODELS).select(_FIELDS).eq("id", mid).limit(1)) if mid else []
    if not rows or str(rows[0].get("owner_id") or "") != me:
        raise _not_found()
    row = rows[0]
    row["setup"] = with_people(database, row)
    return row


#: Keys of the draft that name people. They are never written to
#: ai_models.setup (``_write`` strips them): they are read each time from
#: ai_models.owner_id and ai_model_invites, which the purge registry clears
#: and deletes when an account is erased, so an erased person's id is
#: nowhere in a model's setup.
_PEOPLE_KEYS = ("invited",)


def with_people(database: Any, model: dict) -> dict:
    """The stored draft, with the people it names read from their own rows:
    ``exam.experts`` (the owner and the expert whose invite it keeps) and
    ``invited`` (everyone the owner invited who has not left)."""
    raw = model.get("setup")
    draft = dict(raw) if isinstance(raw, dict) else {}
    invites = _rows(_table(database, INVITES).select("id,invitee_id").eq("model_id", model["id"]))
    draft["invited"] = sorted({str(i["invitee_id"]) for i in invites})
    exam = dict(draft.get("exam") or {})
    expert = next((str(i["invitee_id"]) for i in invites if str(i["id"]) == str(exam.get("invite_id") or "")), None)
    owner = str(model.get("owner_id") or "")
    if exam:
        exam["experts"] = [x for x in (owner, expert) if x]
        draft["exam"] = exam
    return draft


def _stored(draft: dict) -> dict:
    """The draft as it is kept: no user id anywhere in it."""
    out = {k: v for k, v in draft.items() if k not in _PEOPLE_KEYS}
    if isinstance(out.get("exam"), dict):
        out["exam"] = {k: v for k, v in out["exam"].items() if k != "experts"}
    return out


def _write(database: Any, model: dict, draft: dict, *, step: Optional[str] = None,
           status: Optional[str] = None) -> None:
    """The draft kept, and the model's row kept in step with it: its name,
    what it is about, its recipe card, who can see it, where it stopped.
    The moment it first goes public is kept in the draft (N615 item 2)."""
    kept = lp.mark_public(draft, draft.get("visibility") == "public")
    draft.clear()
    draft.update(kept)
    change: dict[str, Any] = {
        "setup": _stored(draft), "updated_at": _now(),
        "name": (S._clean(draft.get("name"), 80) or model.get("name") or rules.WORDS["your_draft"]),
        "description": S._clean(draft.get("problem"), 600) or None,
        "recipe": S.recipe_of(draft) if S.parts_on(draft) else (model.get("recipe") or {}),
        "visibility": draft.get("visibility") if draft.get("visibility") in ("public", "private") else "private",
    }
    if step is not None:
        change["draft_step"] = step if step != "ready" else None
    if status is not None:
        change["status"] = status
    _table(database, MODELS).update(change).eq("id", model["id"]).execute()
    model.update({**change, "setup": draft})


def _view(database: Any, me: str, model: dict, step: str, **extra: Any) -> dict:
    draft = model["setup"]
    kw: dict[str, Any] = {}
    if step in ("exam", "invite"):
        kw["people"] = people_for(database, me)
    if step == "first10" and "first" not in extra:
        kw["first"] = {"available": bool(_first_pool(database, model))}
    kw.update(extra)
    screen = S.step_screen(draft, step, **kw)
    if step == "invite":
        # "Copy an invite link" copies the owner's own chat link (N598).
        screen["chat_link"] = _chat_link(database, me)
    if step == "ready":
        screen.update(S.ready_screen(model.get("name") or "", draft,
                                     ratings_target=_targets(model)["ratings"]))
    return {"model_id": str(model["id"]), "status": model.get("status"), "screen": screen}


def _targets(model: dict) -> dict:
    t = model.get("targets") or {}
    return {"ratings": int(t.get("counted_answers") or rules.DEFAULT_TARGETS["counted_answers"]),
            "exam": int(t.get("exam_cases") or rules.DEFAULT_TARGETS["exam_cases"]),
            "voices": int(t.get("voices") or 0)}


# ── Who the owner may ask (MOD-32, MOD-35) ──────────────────────────────────
def people_for(database: Any, me: str) -> list[dict]:
    """The people from the owner's chats, real people only, nobody blocked
    either way (the list "Send to" uses, services/take_sends.py)."""
    try:
        from services import take_sends
        found = take_sends._people(database, me)
    except Exception:
        logger.warning("model setup: the people could not be read", exc_info=True)
        return []
    return [{"id": p["user_id"], "name": p.get("name") or "", "line": p.get("title") or ""}
            for p in found if p.get("user_id") and p["user_id"] != me and p.get("name")]


# ── Begin (MOD-24, MOD-54; N571) ────────────────────────────────────────────
def _first_take_answers(database: Any, me: str) -> list[tuple[str, str]]:
    """The first Take's answers, as Will's notes keep them (N462): [(the
    slide's question, what the person said)] in the slides' order."""
    from services.plan import FIRST_TAKE_SLIDES
    try:
        events = database.list_speaker_memory_events(me, limit=200) or []
    except Exception:
        logger.warning("model setup: the first Take's answers could not be read", exc_info=True)
        return []
    said: dict[str, str] = {}
    for e in events:
        payload = e.get("payload") if isinstance(e.get("payload"), dict) else {}
        if e.get("kind") == "answer" and payload.get("question") and payload.get("said"):
            said.setdefault(str(payload["question"]), str(payload["said"]))
    return [(q, said[q]) for _k, q, _h, _kind in FIRST_TAKE_SLIDES if said.get(q)]


def begin(database: Any, user_id: Any) -> dict:
    """ "Start your own": a new draft. After a first Take its answers fill
    Describe (the problem from "Your field", how they solve it today from
    "Worth sharing"), and the app drafts the rest from all five; nothing is
    asked twice (N571 items 2 and 3)."""
    me = lp._require(database, user_id)
    from services.plan import FIRST_TAKE_SLIDES
    answers = _first_take_answers(database, me)
    said = dict(answers)
    draft: dict[str, Any] = {"visibility": "private", "done": []}
    field_q, sharing_q = FIRST_TAKE_SLIDES[0][1], FIRST_TAKE_SLIDES[1][1]
    if said.get(field_q) and said.get(sharing_q):
        draft.update({"problem": S._clean(said[field_q], 600), "today": S._clean(said[sharing_q], 600),
                      "from_first_take": True})
        draft = S.apply_drafted(draft, _drafted(database, me, draft, answers))
        draft["drafted"] = True
        draft["parts"] = {}          # proposed again on "kind", from the owner's corrections
    owner_name = _owner_name(database, me)
    made = _rows(_table(database, MODELS).insert({
        "name": rules.WORDS["your_draft"], "owner_id": me, "owner_name": owner_name,
        "visibility": "private", "status": "draft", "draft_step": "problem",
        "description": draft.get("problem") or None, "setup": draft}))
    if not made:
        raise ChatsError("V2_ERROR", "The draft could not be kept.", 500)
    model = made[0]
    model["setup"] = draft
    _table(database, TEACHERS).insert({"model_id": model["id"], "user_id": me, "role": "owner",
                                       "door_accepted_at": _now(), "trust_status": "counts"}).execute()
    return _view(database, me, model, "problem")


#: What people send in a chat (services/chat_recipes.py) as a model's input.
_CHAT_INPUT = {"rec": "voice", "text": "text", "photo": "image", "file": "text"}


def begin_from_blocks(database: Any, user_id: Any, body: Any) -> dict:
    """"Start your own" on the AI models page, made in blocks (N636 items 6
    and 7): the same model as a chat's own card makes (``begin_from_chat``),
    outside a chat, named by its question. {"question", "answers": [3],
    "gives"?: "pick", "base"?: "gpt", "sends"?: "rec" | "text" | "file"}: what
    people send, as a chat's ``send`` names it, sets what one example is (a
    recording: voice; else text); none is "text". A photo is refused: no
    model reads one yet (N616 item 9). A choice not ready yet is refused, as
    on the card."""
    from services.chat_recipes import READY_BASES, READY_GIVES
    body = body if isinstance(body, dict) else {}
    question = S._clean(body.get("question"), 200)
    answers = body.get("answers")
    if not question:
        raise _bad("NOT_READY", "The model needs its question.")
    answers = clean_answers(answers)
    if (body.get("base") or "gpt") not in READY_BASES:
        raise _bad("NOT_READY_YET", "It can be built on GPT only, for now.")
    if (body.get("gives") or "pick") not in READY_GIVES:
        raise _bad("NOT_READY_YET", "It can give back a pick for now.")
    sends = body.get("sends") or "text"
    if sends not in ("rec", "text", "file"):
        raise _bad("NOT_READY_YET", "No model reads a photo yet.")
    return begin_from_chat(database, user_id, question=question, answers=answers, sends=sends)


def clean_answers(answers: Any) -> list[str]:
    """A model's own answers as a person typed them (N646 item 2): two or
    three, each 1 to 24 characters, no two the same; a fourth is refused
    (TOO_MANY_ANSWERS), fewer than two or a blank or repeated one too
    (BAD_ANSWERS)."""
    if not isinstance(answers, list):
        raise _bad("BAD_ANSWERS", "Give two or three answers.")
    if len(answers) > S.MAX_ANSWERS:
        raise _bad("TOO_MANY_ANSWERS", f"At most {S.MAX_ANSWERS} answers.")
    kept = [" ".join(a.split()) if isinstance(a, str) else "" for a in answers]
    if len(kept) < S.MIN_ANSWERS or not all(0 < len(a) <= ANSWER_LONGEST for a in kept) \
            or len({a.lower() for a in kept}) != len(kept):
        raise _bad("BAD_ANSWERS", "Give two or three different answers.")
    return kept


#: The longest answer a person types.
ANSWER_LONGEST = 24


def begin_from_chat(database: Any, user_id: Any, *, question: str, answers: list[str],
                    sends: str = "text") -> dict:
    """A model the host makes in their chat's blank setup (N618 item 6):
    one question with three answers, started as "Start your own" starts one
    (owned by the host, private, the host its first teacher), with the
    question as its name and the three answers as its scale, so it is ready
    to learn and "Teach it" opens on it (the first-ten routes). No provider
    call: nothing is drafted. The same ``{"model_id", "status", "screen"}``
    as ``begin``."""
    me = lp._require(database, user_id)
    scale = S.clean_scale(answers)
    draft: dict[str, Any] = {"visibility": "private", "name": S._clean(question, 80),
                             "question": S._clean(question, 200), "parts": {"score": True},
                             "scale": scale, "input": _CHAT_INPUT.get(sends, "text"),
                             "from_chat": True, "done": ["problem", "kind", "scale", "question"]}
    if not S.can_start(draft):
        raise _bad("NOT_READY", "The model needs its question and two or three answers.")
    made = _rows(_table(database, MODELS).insert({
        "name": draft["name"], "owner_id": me, "owner_name": _owner_name(database, me),
        "visibility": "private", "status": "draft", "draft_step": "ready", "setup": draft}))
    if not made:
        raise ChatsError("V2_ERROR", "The model could not be kept.", 500)
    model = made[0]
    model["setup"] = draft
    _table(database, TEACHERS).insert({"model_id": model["id"], "user_id": me, "role": "owner",
                                       "door_accepted_at": _now(), "trust_status": "counts"}).execute()
    _write(database, model, draft, step="ready", status="learning")
    return _view(database, me, model, "ready")


def _owner_name(database: Any, me: str) -> Optional[str]:
    rows = _rows(_table(database, "people_profiles").select("name").eq("user_id", me).limit(1))
    return (rows[0].get("name") or None) if rows else None


def state(database: Any, user_id: Any, model_id: Any, step: Optional[str] = None) -> dict:
    """The draft where it stopped ("Continue", MOD-25), or the step asked."""
    me = lp._require(database, user_id)
    model = _owned(database, me, model_id)
    at = step or model.get("draft_step") or ("ready" if model.get("status") != "draft" else "problem")
    if at not in S.STEPS:
        raise _bad("BAD_STEP", "Unknown step.")
    return _view(database, me, model, at)


# ── One step's answer (MOD-24 to MOD-35, MOD-38) ────────────────────────────
def save(database: Any, user_id: Any, model_id: Any, step: str, body: Any) -> dict:
    me = lp._require(database, user_id)
    model = _owned(database, me, model_id)
    if step not in S.STEPS or step == "ready":
        raise _bad("BAD_STEP", "Unknown step.")
    body = body if isinstance(body, dict) else {}
    draft = dict(model["setup"])
    handler = _HANDLERS.get(step, _plain)
    stay = handler(database, me, model, draft, body)
    if stay is not None:          # the same step again, or a sheet over it
        _write(database, model, draft, step=stay["step"])
        return _view(database, me, model, stay["step"], **stay.get("extra", {}))
    draft["done"] = sorted(set(draft.get("done") or []) | {step if step != "public" else "share"})
    after = S.next_step(draft, step)
    live = model.get("status") != "draft"
    if after == "ready" and not live:
        if not S.can_start(draft):
            raise _bad("NOT_READY", "The model needs what it does and its scale first.")
        _write(database, model, draft, step="ready", status="learning")
        return _view(database, me, model, "ready")
    _write(database, model, draft, step=after if not live else None)
    return _view(database, me, model, after if not live else "ready")


def _text(body: dict, key: str = "value", most: int = 600) -> str:
    text = S._clean(body.get(key), most)
    if not text:
        raise _bad("EMPTY", "Write a few words first.")
    return text


def _plain(_db: Any, _me: str, _model: dict, _draft: dict, _body: dict) -> None:
    return None


def _describe(step: str):
    def handle(database: Any, me: str, model: dict, draft: dict, body: dict) -> Optional[dict]:
        draft[step] = _text(body)
        if step != "teach":
            return None
        if not draft.get("drafted"):
            fresh = {k: draft.get(k) for k in ("problem", "today", "teach", "visibility", "done",
                                               "from_first_take")}
            drafted = S.apply_drafted(fresh, _drafted(database, me, fresh, []))
            for key in ("name", "unit", "input", "scale", "question", "pick_question", "options",
                        "part_titles", "part_lines", "journey"):
                if not draft.get(key) and drafted.get(key):
                    draft[key] = drafted[key]
            draft["drafted"] = True
        if not draft.get("parts"):
            draft["parts"] = S.suggest_parts(draft)
        if body.get("anyway") or draft.get("similar_seen"):
            return None
        similar = S.similar_model(draft, lp._models(database), me)
        if similar is None:
            return None
        draft["similar_seen"] = str(similar["id"])
        return {"step": "teach", "extra": {"similar": rules._listed_row(similar)}}
    return handle


def _kind(_db: Any, _me: str, _model: dict, draft: dict, body: dict) -> None:
    given = body.get("parts")
    raw: dict = given if isinstance(given, dict) else {}
    parts = {k: bool(raw.get(k)) for k in ("score", "pick", "answer")}
    if not any(parts.values()):
        raise _bad("NO_PART", "Keep at least one thing it does.")
    if parts != draft.get("parts"):
        draft["journey"] = S.journey_for({**draft, "parts": parts})
    draft["parts"] = parts
    draft["name"] = _text(body, "name", 80)
    draft["journey_off"] = [s for s in draft.get("journey_off") or []
                            if s in [S._PART_STEP[p] for p in S.parts_on(draft)]]
    return None


def _scale(database: Any, _me: str, model: dict, draft: dict, body: dict) -> None:
    draft["scale"] = _answers_kept(database, model, draft, body.get("scale"))
    return None


def _counted(database: Any, model_id: Any) -> bool:
    """Has any answer to this model counted yet (N646 Open)?"""
    return bool(_rows(_table(database, ANSWERS).select("id").eq("model_id", str(model_id))
                      .eq("counted", True).limit(1)))


def _answers_kept(database: Any, model: dict, draft: dict, raw: Any) -> list[dict]:
    """The model's answers as the person changed them, checked (N646 items
    2 and 3): every point a word; a model made from a question (a chat's
    card, blocks) at most three; and none changed once an answer counted:
    until the founder decides (N646 Open), they may not, 409
    ANSWERS_LOCKED."""
    scale = S.clean_scale(raw)
    if draft.get("from_chat") and len(scale) > S.MAX_ANSWERS:
        raise _bad("TOO_MANY_ANSWERS", f"At most {S.MAX_ANSWERS} answers.")
    if not S.scale_ok(scale, draft):
        raise _bad("BAD_SCALE", "Give every point a word.")
    if [p["t"] for p in scale] != [p.get("t") for p in S.clean_scale(draft.get("scale"))] \
            and _counted(database, model["id"]):
        raise ChatsError("ANSWERS_LOCKED", "Its answers can't change once teaching has counted.", 409)
    return scale


def set_answers(database: Any, user_id: Any, model_id: Any, answers: list[str]) -> None:
    """The answers of the host's own model made from their chat's card, kept
    as the card says them (N646 item 4: the chat's reply reads the card,
    teaching and the check read the model). Unchanged is nothing."""
    me = lp._require(database, user_id)
    model = _owned(database, me, model_id)
    draft = dict(model["setup"])
    if [p.get("t") for p in S.clean_scale(draft.get("scale"))] == list(answers):
        return
    draft["scale"] = _answers_kept(database, model, draft, answers)
    _write(database, model, draft)


def _question(_db: Any, _me: str, _model: dict, draft: dict, body: dict) -> None:
    question = _text(body, "question", 200)
    if question != draft.get("question"):
        draft["journey"] = []     # the journey says the question; it is drafted again
    draft["question"] = question
    if (draft.get("parts") or {}).get("pick"):
        draft["pick_question"] = S._clean(body.get("pick_question"), 200) or draft.get("pick_question") or ""
        draft["options"] = S.clean_options(body.get("options"))
    if not S.question_ok(draft):
        raise _bad("BAD_LIST", "Write at least two options.")
    draft["journey"] = draft.get("journey") or S.journey_for(draft)
    return None


def _rules(_db: Any, _me: str, _model: dict, draft: dict, body: dict) -> None:
    """"Use these rules" keeps the ticked ones; "Skip" keeps none. Either way
    the step is decided (the checklist's "Starting rules · optional")."""
    found = draft.get("rules") or []
    if body.get("use"):
        given = body.get("on")
        ticks: list = given if isinstance(given, list) else [True] * len(found)
        draft["rules"] = [{**r, "on": bool(ticks[i]) if i < len(ticks) else bool(r.get("on"))}
                          for i, r in enumerate(found)]
        if body.get("strictness") in S.STRICTNESS:
            draft["strictness"] = body["strictness"]
    else:
        draft["rules"] = []
    draft["rules_decided"] = True
    return None


def _data(_db: Any, _me: str, _model: dict, draft: dict, body: dict) -> None:
    data = dict(draft.get("data") or {})
    if body.get("use"):
        if not data.get("columns"):
            raise _bad("NO_FILE", "Upload a file first.")
    else:
        data = {"decided": True}
    draft["data"] = data
    return None


def _columns(_db: Any, _me: str, _model: dict, draft: dict, body: dict) -> None:
    data = dict(draft.get("data") or {})
    if not data.get("columns"):
        raise _bad("NO_FILE", "Upload a file first.")
    data["map"] = S.clean_map(body.get("map"), data["columns"]) if body.get("map") else data.get("map") or []
    if not any(c["role"] == "example" for c in data["map"]):
        raise _bad("NO_EXAMPLE", "Choose the column that holds the example.")
    data["check"] = _check_of(draft, data)
    draft["data"] = data
    return None


def _check_of(draft: dict, data: dict) -> dict:
    check = S.check_data({"rows": data.get("rows") or []}, data.get("map") or [],
                         S.clean_scale(draft.get("scale")), draft.get("parts") or {})
    return {k: v for k, v in check.items() if k != "rows"}


def _check(database: Any, me: str, model: dict, draft: dict, body: dict) -> None:
    """"Upload it", only with the tick (N566 item 4): the checked rows become
    the model's private examples (an upload is the owner's own data, N563
    item 3), their labels kept where no teacher sees them, and 60 of them
    are what the teachers re-rate first. None goes to the exam."""
    data = dict(draft.get("data") or {})
    if not body.get("consent"):
        raise _bad("NO_CONSENT", "Tick that you may use this data first.")
    if not data.get("rows"):
        raise _bad("NO_FILE", "Upload a file first.")
    checked = S.check_data({"rows": data["rows"]}, data.get("map") or [],
                           S.clean_scale(draft.get("scale")), draft.get("parts") or {})
    kept = checked["rows"]
    sample = set(S.rerate_sample(kept, str(model["id"])))
    rows = [{"model_id": model["id"], "source": "upload", "private": True, "added_by": me, "in_exam": False,
             "kind": "rerate" if i in sample else None,
             "content": {"text": r["example"]},
             "machine": {"uploaded": {"score": r.get("score"), "pick": r.get("pick"),
                                      "answer": r.get("answer")},
                         "mislabelled": bool(r.get("mislabelled"))}}
            for i, r in enumerate(kept)]
    for start in range(0, len(rows), 500):
        _table(database, EXAMPLES).insert(rows[start:start + 500]).execute()
    data.update({"consent": True, "decided": True, "rows": [], "uploaded_at": _now(),
                 "check": {k: v for k, v in checked.items() if k != "rows"}})
    draft["data"] = data
    return None


def _exam(database: Any, me: str, model: dict, draft: dict, body: dict) -> None:
    """The second expert of the final exam (N566 item 5): someone from the
    owner's chats, asked with an invite that stays (N528 item 3)."""
    expert = _uuid(body.get("expert"))
    if not expert or expert not in {p["id"] for p in people_for(database, me)}:
        raise _bad("NO_EXPERT", "Choose the second expert.")
    draft["exam"] = {"invite_id": _invite(database, me, model, expert), "asked_at": _now(),
                     "experts": [me, expert]}
    return None


def _journey(_db: Any, _me: str, _model: dict, draft: dict, body: dict) -> Optional[dict]:
    if body.get("change") in ("shorter", "longer"):
        draft["journey_off"] = S.journey_change(draft, body["change"] == "longer")
        return {"step": "journey"}
    return None


def _share(_db: Any, _me: str, _model: dict, draft: dict, body: dict) -> Optional[dict]:
    """Private goes on; Public first shows its disclaimer (MOD-34)."""
    vis = body.get("visibility")
    if vis not in ("private", "public"):
        raise _bad("BAD_VISIBILITY", "Choose who can see it.")
    if vis == "public" and draft.get("visibility") != "public":
        return {"step": "public"}
    draft["visibility"] = vis
    return None


def _public(_db: Any, _me: str, _model: dict, draft: dict, body: dict) -> None:
    """"Make it public" or "Keep it private", after the disclaimer."""
    draft["visibility"] = "public" if body.get("confirm") else "private"
    return None


def _invites(database: Any, me: str, model: dict, draft: dict, body: dict) -> None:
    """Each person chosen gets an invite in their chat with the owner; each
    one chooses whether to join (N563 item 6). Nobody is made to teach."""
    allowed = {p["id"] for p in people_for(database, me)}
    chosen = [p for p in (body.get("people") or []) if _uuid(p) in allowed]
    for person in chosen:
        _invite(database, me, model, str(_uuid(person)))
    draft["invited"] = sorted(set(draft.get("invited") or []) | {str(_uuid(p)) for p in chosen})
    return None


def _invite(database: Any, me: str, model: dict, invitee: str) -> Optional[str]:
    """The invite's id: the one that exists, or a new one."""
    found = _rows(_table(database, INVITES).select("id").eq("model_id", model["id"])
                  .eq("invitee_id", invitee).limit(1))
    if found:
        return str(found[0]["id"])
    made = _rows(_table(database, INVITES).insert({"model_id": model["id"], "inviter_id": me,
                                                   "invitee_id": invitee, "status": "open"}))
    return str(made[0]["id"]) if made else None


_HANDLERS = {
    "problem": _describe("problem"), "today": _describe("today"), "teach": _describe("teach"),
    "kind": _kind, "scale": _scale, "question": _question, "rules": _rules, "data": _data,
    "columns": _columns, "check": _check, "exam": _exam, "journey": _journey,
    "share": _share, "public": _public, "invite": _invites,
}


def _chat_link(database: Any, me: str) -> Optional[str]:
    """The owner's own chat link (N598 item 1: inviting a teacher is sharing
    it; there is no separate link for teachers), when they have one; the app
    makes it with GET /v2/chats/link, as everywhere."""
    try:
        from services.chat_links import _live
        link = _live(database, me)
    except Exception:
        logger.warning("model setup: the chat link could not be read", exc_info=True)
        return None
    return f"/c/{link['token']}" if link else None


# ── "Start with this, finish the rest later" (MOD-28, MOD-36) ───────────────
def start_now(database: Any, user_id: Any, model_id: Any, body: Any = None) -> dict:
    me = lp._require(database, user_id)
    model = _owned(database, me, model_id)
    draft = dict(model["setup"])
    body = body if isinstance(body, dict) else {}
    if body.get("scale") is not None:
        _scale(database, me, model, draft, body)
        draft["done"] = sorted(set(draft.get("done") or []) | {"scale"})
    if not S.can_start(draft):
        raise _bad("NOT_READY", "The model needs what it does and its scale first.")
    _write(database, model, draft, step="ready",
           status="learning" if model.get("status") == "draft" else None)
    return _view(database, me, model, "ready")


# ── A study (MOD-30; N585) ──────────────────────────────────────────────────
def read_study(database: Any, user_id: Any, model_id: Any, name: str, data: bytes) -> dict:
    """A study's text read into starting rules, each with its source and who
    it was measured on; the owner keeps the ones they tick. A PDF or a text
    file; nothing of it is kept but the rules."""
    me = lp._require(database, user_id)
    model = _owned(database, me, model_id)
    if not data or len(data) > S.MAX_STUDY_BYTES:
        raise _bad("BAD_FILE", "Upload a PDF or a text file under 8 MB.")
    text = _study_text(name, data)
    if not text.strip():
        raise _bad("BAD_FILE", "We could not read any words in this file.")
    draft = dict(model["setup"])
    reply = _authorized(database, me, f"model-rules:{model['id']}",
                        lambda: _rules_reply(text, name, draft, me)) or {}
    draft["rules"] = S.clean_rules(reply.get("rules"), draft.get("input") or "voice")
    draft["study_name"] = S._clean(name, 120)
    _write(database, model, draft, step="rules")
    return _view(database, me, model, "rules")


def _study_text(name: str, data: bytes) -> str:
    if (name or "").lower().endswith(".pdf") or data[:4] == b"%PDF":
        try:
            from io import BytesIO

            from pypdf import PdfReader
            reader = PdfReader(BytesIO(data))
            pages = [f"[page {i + 1}] {(p.extract_text() or '').strip()}" for i, p in enumerate(reader.pages[:60])]
            return "\n".join(pages)[:60_000]
        except Exception:
            logger.warning("model setup: the study's PDF could not be read", exc_info=True)
            return ""
    return data.decode("utf-8", errors="replace")[:60_000]


# ── An existing dataset (MOD-31) ────────────────────────────────────────────
def read_data(database: Any, user_id: Any, model_id: Any, name: str, data: bytes) -> dict:
    """The file read and its columns guessed; the owner confirms the map
    next, then the check. Nothing counts until "Upload it" with the tick."""
    me = lp._require(database, user_id)
    model = _owned(database, me, model_id)
    draft = dict(model["setup"])
    try:
        parsed = S.parse_file(name, data)
    except ValueError as e:
        reason = {"too_big": "The file is over 2 MB.", "excel": "Save the sheet as CSV first.",
                  "bad_json": "The JSON file could not be read."}.get(str(e), "We found no rows in this file.")
        raise _bad("BAD_FILE", reason) from e
    mapping = S.map_columns(parsed["columns"], draft.get("parts") or {})
    data_ = {"name": S._clean(name, 120), "columns": parsed["columns"], "rows": parsed["rows"],
             "map": mapping}
    data_["check"] = _check_of(draft, data_)
    draft["data"] = data_
    _write(database, model, draft, step="columns")
    return _view(database, me, model, "columns")


# ── The first 10 (MOD-38, MOD-55; N570 items 3 and 4) ───────────────────────
def _first_pool(database: Any, model: dict) -> list[dict]:
    examples = _rows(_table(database, EXAMPLES).select(
        "id,model_id,source,private,kind,content,in_exam,known_answer,created_at,speaker_id,snippet_id")
        .eq("model_id", model["id"]))
    done = [f.get("example_id") for f in model["setup"].get("first_ten") or []]
    return S.first_ten_pool(examples, done)


def first_ten(database: Any, user_id: Any, model_id: Any) -> dict:
    """The next of the owner's first 10, on the screen the teachers use,
    without the model's guess (Never 2, N585 item 5)."""
    me = lp._require(database, user_id)
    model = _owned(database, me, model_id)
    if len(model["setup"].get("first_ten") or []) >= S.FIRST_TEN:
        return _view(database, me, model, "first10")
    pool = _first_pool(database, model)
    if not pool:
        return _view(database, me, model, "first10", first={"available": False})
    screen = rules.teaching_screen({**model, "recipe": model.get("recipe") or {}},
                                   lp.with_clips(database, pool[:1])[0])
    return _view(database, me, model, "first10", first={"available": True, "example": screen})


def first_ten_answer(database: Any, user_id: Any, model_id: Any, example_id: Any, body: Any) -> dict:
    """The owner's answer, kept like any teacher's (the model reads it from
    day one); it trains the model once a second teacher agrees (N570 item 4)."""
    me = lp._require(database, user_id)
    model = _owned(database, me, model_id)
    body = body if isinstance(body, dict) else {}
    eid = _uuid(example_id)
    pool = {str(e["id"]) for e in _first_pool(database, model)}
    if not eid or eid not in pool:
        raise _not_found()
    step = str(body.get("step") or "rate")
    if step not in ("rate", "pick", "words"):
        raise _bad("BAD_STEP", "Unknown step.")
    answer = None if body.get("answer") is None else str(body.get("answer"))[:4000]
    lp._save_answer(database, eid, str(model["id"]), me, step, answer)
    if step in ("rate", "pick") and answer:
        # The owner's answer is the model's reference (N523 item 6): a known
        # answer the quiet trust check measures newcomers against. It trains
        # the model only once a second teacher agrees (``recount``).
        _table(database, EXAMPLES).update({"known_answer": answer}).eq("id", eid) \
            .eq("model_id", model["id"]).eq("in_exam", False).execute()
    lp.recount(database, str(model["id"]), [eid])
    draft = dict(model["setup"])
    first = list(draft.get("first_ten") or [])
    if eid not in {f.get("example_id") for f in first}:
        first.append({"example_id": eid, "answer": answer, "at": _now()})
    draft["first_ten"] = first
    _write(database, model, draft, step=None if model.get("status") != "draft" else "first10")
    return first_ten(database, me, model_id)


# ── The owner's part of a model's page (MOD-36, MOD-37) ─────────────────────
def _pointer(model: dict):
    """An answer as its point on the model's scale, 1..n, or None."""
    scale = list((model.get("recipe") or {}).get("scale") or [])

    def point(answer: Any) -> Optional[int]:
        text = str(answer or "").strip()
        if text.isdigit():
            return int(text)
        return scale.index(text) + 1 if text in scale else None
    return point


def _agreement(answers: list[dict], trusted: set[str], point) -> dict:
    rates: dict[str, list[int]] = defaultdict(list)
    for a in answers:
        p = point(a.get("answer")) if a.get("step") == "rate" else None
        if p is not None and str(a.get("teacher_id")) in trusted:
            rates[str(a["example_id"])].append(p)
    return S.agreement(rates)


def _jars_and_pace(model: dict, examples: list[dict], answers: list[dict]) -> tuple[dict, dict]:
    """The jars as they stand, and each jar's pace a week over the last two."""
    since = (datetime.now(timezone.utc) - timedelta(days=14)).isoformat()
    exam_ids = {str(e["id"]) for e in examples if e.get("in_exam")}
    counted = [a for a in answers if a.get("counted") and str(a.get("example_id")) not in exam_ids]
    taught = [e for e in examples if e.get("speaker_id") and not e.get("in_exam")]
    recent = [e for e in examples if str(e.get("created_at") or "") >= since]
    jars = {"ratings": len(counted), "exam": int((model.get("jars") or {}).get("exam_cases") or 0),
            "voices": len({str(e["speaker_id"]) for e in taught})}
    pace = {"ratings": sum(1 for a in counted if str(a.get("created_at") or "") >= since) / 2,
            "exam": sum(1 for e in recent if e.get("in_exam")) / 2,
            "voices": len({str(e["speaker_id"]) for e in recent if e.get("speaker_id")}) / 2}
    return jars, pace


def _upload_state(examples: list[dict], answers: list[dict], me: str, trusted: set[str], point) -> Optional[dict]:
    """An upload's rows, and whether the teachers' re-rates agree with it."""
    uploads = [e for e in examples if e.get("source") == "upload"]
    if not uploads:
        return None
    settled = _settled_by_teachers(answers, me, trusted)
    pairs = []
    for e in uploads:
        if e.get("kind") == "rerate" and str(e["id"]) in settled:
            label = (e.get("machine") or {}).get("uploaded") or {}
            ours = settled[str(e["id"])]
            pairs.append((label.get("score") if label.get("score") is not None else label.get("pick"),
                          point(ours) or ours))
    return {"usable": len(uploads), "result": S.upload_counts(pairs)}


def _sources(examples: list[dict], answers: list[dict], draft: dict, upload: Optional[dict], me: str) -> dict:
    first_ids = {str(f.get("example_id")) for f in draft.get("first_ten") or []}
    others: dict[str, set] = defaultdict(set)
    for a in answers:
        if str(a.get("teacher_id")) != me:
            others[str(a["example_id"])].add(str(a.get("teacher_id")))
    counts = upload is not None and bool((upload.get("result") or {}).get("counts"))
    return {
        "takes": sum(1 for e in examples if e.get("source") == "takes" and not e.get("in_exam")),
        "upload_counted": upload["usable"] if upload is not None and counts else 0,
        "business": sum(1 for e in examples if e.get("source") == "business"),
        "teacher": sum(1 for e in examples if e.get("source") == "teacher"),
        "first_total": len(first_ids),
        "first_settled": sum(1 for x in first_ids if others.get(x)),
    }


def owner_view(database: Any, me: str, model: dict) -> Optional[dict]:
    """The owner's panel for their own model, or None for anyone else."""
    if str(model.get("owner_id") or "") != me:
        return None
    rows = _rows(_table(database, MODELS).select("id,owner_id,setup").eq("id", model["id"]).limit(1))
    draft = with_people(database, rows[0]) if rows else {}
    examples = _rows(_table(database, EXAMPLES).select(
        "id,source,in_exam,speaker_id,kind,machine,created_at,added_by").eq("model_id", model["id"]))
    answers = _rows(_table(database, ANSWERS).select(
        "example_id,teacher_id,answer,counted,created_at,step").eq("model_id", model["id"]))
    team = _rows(_table(database, TEACHERS).select("user_id,trust_status").eq("model_id", model["id"]))
    trusted = {str(t["user_id"]) for t in team if t.get("trust_status") == "counts"}
    point = _pointer(model)
    jars, pace = _jars_and_pace(model, examples, answers)
    upload = _upload_state(examples, answers, me, trusted, point)
    return S.owner_panel(model, draft, pct=rules.percent_of_the_way(model), jars=jars,
                         targets=_targets(model), pace=pace, agree=_agreement(answers, trusted, point),
                         sources=_sources(examples, answers, draft, upload, me), upload=upload,
                         rules_checked=_rules_checked(draft, examples, answers, me))


def _settled_by_teachers(answers: list[dict], owner: str, trusted: set[str]) -> dict[str, Any]:
    """An example's answer once two trusted teachers other than the owner
    gave the same one (label_quorum's two matching votes)."""
    votes: dict[str, list] = defaultdict(list)
    for a in answers:
        if str(a.get("teacher_id")) != owner and str(a.get("teacher_id")) in trusted and a.get("answer") is not None:
            votes[str(a["example_id"])].append(a["answer"])
    out = {}
    for eid, vals in votes.items():
        common = max(set(vals), key=vals.count)
        if vals.count(common) >= 2:
            out[eid] = common
    return out


def _rules_checked(draft: dict, examples: list[dict], answers: list[dict], owner: str) -> list[dict]:
    """Each kept rule against the teachers' first 50 ratings of examples that
    carry its measure (MOD-30); a rule not yet checked is left out."""
    on = [r for r in draft.get("rules") or [] if r.get("on") and r.get("measure")]
    if not on:
        return []
    measures = {str(e["id"]): (e.get("machine") or {}).get("measures") or {} for e in examples}
    rated = [{"measures": measures.get(str(a["example_id"]), {}), "answer": a.get("answer")}
             for a in sorted(answers, key=lambda a: str(a.get("created_at") or ""))
             if a.get("step") == "rate" and str(a.get("teacher_id")) != owner]
    out = []
    for r in on:
        c = S.check_rule(r, rated)
        if c is not None:
            out.append({"text": r["text"], **c})
    return out


# ── The provider calls, under the caller's authority ────────────────────────
_DRAFT_SYSTEM = """You help a person start an AI model that learns one skill from people who know it well.
They answered three questions: the problem it should solve, how they solve it today, how they will teach it.
Sometimes the answers come from their first recorded Take instead; then also draft "teach" from them.

Draft the rest of the setup, in the person's language, plain and concrete, people as the subjects, one idea a sentence.
Reply with JSON only:
{"name": a short name for the model (2 to 4 words),
 "input": "voice" | "text" | "image" (what one example is: a recording, a written case, or a photo),
 "unit": what one example is, e.g. "a pitch clip of about 30 seconds",
 "parts": {"score": bool, "pick": bool, "answer": bool} (a score on a scale; a pick from a list; answering like the person),
 "part_lines": {"score": e.g. "How rushed a pitch sounds, from calm to racing", "pick": e.g. "Which of your exercises fits", "answer": e.g. "From your answers set beside its own drafts"},
 "part_titles": {"score": e.g. "Score how rushed it sounds", "pick": e.g. "Pick the exercise", "answer": "Answer like you"},
 "scale": five points from low to high, each {"t": one or two words, "d": what that point sounds or looks like},
 "question": the one question every teacher answers about each example, e.g. "How rushed does it sound?",
 "pick_question": the question for the pick, or "",
 "options": the list to pick from if they named one, else [],
 "journey": what each teacher does, one short line a step, e.g. ["Listen to a short pitch", "Rate how rushed it sounds"],
 "teach": how they will teach it, only when the answers come from a Take, else ""}
Never invent facts about the person. Never score the person."""

_RULES_SYSTEM = """You read a study and propose starting rules for an AI model that recognises one thing.
Only rules the study supports, each with where it says so (file name and page) and who it was measured on (how many people, which language, which group).
A rule is a cut on something the app measures. For voice: pace_wpm (words a minute), pause_s (seconds), fillers_per_100, hedges_per_100, pitch_range_st (semitones). For text: words, sentence_words.
Reply with JSON only: {"rules": [{"text": one plain sentence, e.g. "A pitch faster than 170 words a minute sounds rushed.", "src": e.g. "From study.pdf, page 4", "measured_on": e.g. "a study of 40 English-speaking founders", "measure": one of the measures or null, "op": ">" or "<" or null, "cut": a number or null, "answer": the scale's word the rule gives when it fires, or ""}]}
At most five rules. None when the study has none."""


def _drafted(database: Any, me: str, draft: dict, answers: list[tuple[str, str]]) -> Optional[dict]:
    payload = {"problem": draft.get("problem"), "today": draft.get("today"), "teach": draft.get("teach")}
    if answers:
        payload["first_take"] = [{"question": q, "said": s} for q, s in answers]
    return _authorized(database, me, f"model-draft:{uuid.uuid4()}",
                       lambda: _complete(_DRAFT_SYSTEM, payload, _SURFACE_DRAFT, me))


def _rules_reply(text: str, name: str, draft: dict, me: str) -> Optional[dict]:
    payload = {"file": name, "model": {"question": draft.get("question"),
                                       "scale": [p.get("t") for p in S.clean_scale(draft.get("scale"))],
                                       "input": draft.get("input") or "voice"},
               "study": text}
    return _complete(_RULES_SYSTEM, payload, _SURFACE_RULES, me)


def _complete(system: str, payload: dict, surface: str, me: str) -> Optional[dict]:
    from services.llm import chat_complete
    from services.llm_config import SPEC_MODEL_SETUP
    result = chat_complete(spec=SPEC_MODEL_SETUP, system=system,
                           user=json.dumps(payload, ensure_ascii=False), surface=surface, user_id=me)
    parsed = getattr(result, "parsed", None) if result else None
    return parsed if isinstance(parsed, dict) else None


def _authorized(database: Any, me: str, key: str, call) -> Optional[dict]:
    """``call`` under the caller's processing authority: the request's own
    scope when there is one, else one built the way the chat's is. Not
    authorized, or the call fails: None, and the rules' fallback stands."""
    from services.authorized_provider import (
        AuthorizedProviderAdapter, ProviderCoordinates, protected_provider_scope, scoped_adapter)
    from services.processing_authorization import (
        ProcessingAuthorizationError, ProcessingAuthorizationService)
    try:
        authorization = ProcessingAuthorizationService(database)
        if scoped_adapter() is not None or not authorization.enforced:
            return call()
        from services.rings import principal_for_user
        owner = principal_for_user(me, database=database)
        if not owner:
            return None
        principal = authorization.resolve_acquisition_principal(owner, user_id=me)
        authorization.require_current(principal, operation="ai_conversation")
        adapter = AuthorizedProviderAdapter(
            database, ProviderCoordinates(principal, None, None), authorization=authorization)
        with protected_provider_scope(adapter, idempotency_prefix=key):
            return call()
    except ProcessingAuthorizationError as error:
        logger.info("model setup: not authorized user=%s: %s", me, error.code)
        return None
    except Exception:
        logger.warning("model setup: the draft could not be written; the rules' draft stands",
                       exc_info=True)
        return None
