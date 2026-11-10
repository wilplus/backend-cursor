"""The model launchpad's storage: it reads the models' tables (migration
a_person_can_teach_and_start_ai_models) into the shapes
``services/model_launchpad.py`` takes, and writes a teacher's door, Pause
and answers. The rules are all there; nothing here decides anything a
person sees.

Ring row ``ai_models`` (ring 6, the founder and the people the founder adds
first): anyone else gets 404, as for the chats. No provider call and no
recording here: an answer in words is recorded through the chats' own
recording path, which passes the processing-authorization path, and only
its words reach a model (N528 item 10).

  * ``list_for``      the list of models, the drafts on top (MOD-05, MOD-13)
  * ``page_for``      a model's page for the caller, or 404 (MOD-03, MOD-06)
  * ``enter``         "This is my field" at the door (MOD-07)
  * ``queue_for``     the one queue across the models the caller teaches
                      (MOD-14, MOD-15, MOD-23)
  * ``set_paused``    Pause, per model (MOD-15)
  * ``answer``        a teacher's answer: saved for every model it counts
                      for, and only then the follow-up question and, once,
                      "Your answers now count." (MOD-09, MOD-10, MOD-16 to MOD-18)
  * ``chat_rows_for`` the rows under the people (MOD-04, MOD-14)
  * ``profile_for``   the profile's section (MOD-50)
  * ``invite_for``    an invite to teach as it stays in the chat (MOD-49)
  * ``invites_for``   the caller's invites, open or put off (MOD-49)
  * ``answer_invite`` "Not now" (it stays) or accept (MOD-49)
  * ``add_example``   "Add an example you know well" (MOD-21)
  * ``archive``, ``make_public``  the owner's actions (MOD-50, MOD-51)
  * ``teaches``, ``transcribe``  a spoken answer or case to its words (MOD-20, MOD-21)
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Optional

from services import model_launchpad as rules
from services.chats import ChatsError, _not_found, _rows, _table, _uuid

logger = logging.getLogger(__name__)

FEATURE = "ai_models"
MODELS, TEACHERS, EXAMPLES, ANSWERS, INVITES = (
    "ai_models", "ai_model_teachers", "ai_model_examples", "ai_model_answers", "ai_model_invites")
_MODEL_FIELDS = "id,name,owner_id,owner_name,visibility,status,field,description,draft_step,recipe,targets"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def enabled(database: Any, user_id: Any) -> bool:
    """Does this person have the AI models? Fails closed (rings)."""
    from services import rings
    try:
        return bool(user_id) and rings.feature_is_on_for_user(FEATURE, user_id, database=database)
    except Exception:
        logger.warning("ai_models: the rings could not be read; closed", exc_info=True)
        return False


def _require(database: Any, user_id: Any) -> str:
    if not enabled(database, user_id):
        raise _not_found()
    return str(user_id)


def _models(database: Any, ids: Optional[list[str]] = None) -> list[dict]:
    """The models with their teachers and jars, in the rules' shape."""
    query = _table(database, MODELS).select(_MODEL_FIELDS)
    if ids is not None:
        if not ids:
            return []
        query = query.in_("id", ids)
    models = _rows(query)
    if not models:
        return []
    mids = [str(m["id"]) for m in models]
    teachers = _rows(_table(database, TEACHERS).select("model_id,user_id,role,trust_status")
                     .in_("model_id", mids))
    counted = _rows(_table(database, ANSWERS).select("model_id").in_("model_id", mids).eq("counted", True))
    exam = _rows(_table(database, EXAMPLES).select("model_id").in_("model_id", mids).eq("in_exam", True))
    by_model: dict[str, list[dict]] = defaultdict(list)
    for t in teachers:
        by_model[str(t["model_id"])].append(t)
    n_counted: dict[str, int] = defaultdict(int)
    for a in counted:
        n_counted[str(a["model_id"])] += 1
    n_exam: dict[str, int] = defaultdict(int)
    for e in exam:
        n_exam[str(e["model_id"])] += 1
    out = []
    for m in models:
        mid = str(m["id"])
        team = by_model.get(mid, [])
        out.append({
            **m, "id": mid,
            "owner_id": str(m["owner_id"]) if m.get("owner_id") else None,
            "recipe": m.get("recipe") or {}, "targets": m.get("targets") or {},
            "owner_ids": [str(t["user_id"]) for t in team if t.get("role") == "owner"],
            "contributor_ids": [str(t["user_id"]) for t in team if t.get("role") == "contributor"],
            "teachers": sum(1 for t in team if t.get("trust_status") == "counts"),
            "jars": {"counted_answers": n_counted.get(mid, 0), "exam_cases": n_exam.get(mid, 0)},
        })
    return out


def _model(database: Any, model_id: Any) -> dict:
    mid = _uuid(model_id)
    found = _models(database, [mid]) if mid else []
    if not found:
        raise _not_found()
    return found[0]


def _my_fields(database: Any, user_id: str) -> list[str]:
    rows = _rows(_table(database, "people_profiles").select("role,about").eq("user_id", user_id).limit(1))
    return [v for v in ((rows[0].get("role"), rows[0].get("about")) if rows else ()) if v]


def list_for(database: Any, user_id: Any, *, query: str = "", filter_: Optional[str] = None) -> dict:
    me = _require(database, user_id)
    if filter_ is not None and filter_ not in rules.FILTERS:
        raise ChatsError("BAD_FILTER", "Unknown filter.")
    return rules.model_list(_models(database), me, query=(query or "")[:80], filter_=filter_,
                            viewer_fields=_my_fields(database, me))


def page_for(database: Any, user_id: Any, model_id: Any) -> dict:
    me = _require(database, user_id)
    model = _model(database, model_id)
    own_part = None
    if rules.viewer_role(model, me) in ("owner", "contributor"):
        mine = _rows(_table(database, ANSWERS).select("id").eq("model_id", model["id"])
                     .eq("teacher_id", me).eq("counted", True))
        own_part = {"answers_counted": len(mine)}
    page = rules.model_page(model, me, own_part=own_part)
    if page is None:
        raise _not_found()
    if rules.viewer_role(model, me) == "owner":
        from services import model_setup_store
        page["owner"] = model_setup_store.owner_view(database, me, model)
    return page


def enter(database: Any, user_id: Any, model_id: Any) -> dict:
    """ "This is my field": the caller joins a public model as a teacher.
    Their answers count only once the quiet trust check admits them."""
    me = _require(database, user_id)
    model = _model(database, model_id)
    role = rules.viewer_role(model, me)
    if role is None:
        raise _not_found()
    if role == "public":
        _table(database, TEACHERS).insert({
            "model_id": model["id"], "user_id": me, "role": "contributor",
            "door_accepted_at": _now()}).execute()
    return {"joined": True}


def set_paused(database: Any, user_id: Any, model_id: Any, paused: bool) -> dict:
    me = _require(database, user_id)
    mid = _uuid(model_id)
    rows = _rows(_table(database, TEACHERS).select("model_id").eq("model_id", mid).eq("user_id", me)) if mid else []
    if not rows:
        raise _not_found()
    _table(database, TEACHERS).update({"paused_at": _now() if paused else None}) \
        .eq("model_id", mid).eq("user_id", me).execute()
    return {"paused": bool(paused)}


def _teaching(database: Any, me: str) -> list[dict]:
    return _rows(_table(database, TEACHERS).select("model_id,role,paused_at,company_line").eq("user_id", me))


def queue_for(database: Any, user_id: Any, *, only: Any = None) -> dict:
    me = _require(database, user_id)
    mine = _teaching(database, me)
    models = _models(database, [str(t["model_id"]) for t in mine])
    mids = [m["id"] for m in models if m.get("status") in ("learning", "ready")]
    examples = _rows(_table(database, EXAMPLES)
                     .select("id,model_id,source,private,kind,content,sureness,speaker_id,added_by,snippet_id")
                     .in_("model_id", mids).eq("in_exam", False)) if mids else []
    # An upload waits for its 60 re-rates; the rest of it never needs a
    # teacher (N566 item 4).
    examples = [e for e in examples if e.get("source") != "upload" or e.get("kind") == "rerate"]
    examples += _exam_cases_for(database, me, mids)
    answered = {(str(a["example_id"]), str(a["model_id"])) for a in _rows(
        _table(database, ANSWERS).select("example_id,model_id").eq("teacher_id", me))} if mids else set()
    sees = _sees_private(database, me, models)
    waiting = [e for e in examples
               if (str(e["id"]), str(e["model_id"])) not in answered
               and str(e.get("speaker_id") or "") != me and str(e.get("added_by") or "") != me
               and (not e.get("private") or str(e["model_id"]) in sees)]
    return rules.build_queue(
        [m for m in models if m["id"] in mids], with_clips(database, waiting), me,
        paused=[t["model_id"] for t in mine if t.get("paused_at")], only=_uuid(only) if only else None,
        company_line={str(t["model_id"]): t["company_line"] for t in mine if t.get("company_line")})


def _sees_private(database: Any, me: str, models: list[dict]) -> set[str]:
    """The models whose private examples (a company's own data, N563 item 3)
    the caller may be sent: every model that is still private, and of the
    public ones, those the caller owns or was invited to teach. Someone who
    came in at the door of a public model is never sent a private example,
    whenever the model went public."""
    out = {m["id"] for m in models
           if m.get("visibility") != "public" or rules.viewer_role(m, me) == "owner"}
    rest = [m["id"] for m in models if m["id"] not in out]
    if rest:
        out |= {str(i["model_id"]) for i in _rows(
            _table(database, INVITES).select("model_id,status").eq("invitee_id", me).in_("model_id", rest))
            if i.get("status") == "accepted"}
    return out


def _exam_cases_for(database: Any, me: str, mids: list[str]) -> list[dict]:
    """The exam's cases for the two experts who set it aside (N566 item 5),
    and for nobody else."""
    if not mids:
        return []
    from services.model_setup_store import with_people
    setups = _rows(_table(database, MODELS).select("id,owner_id,setup").in_("id", mids))
    mine = [str(m["id"]) for m in setups
            if me in ((with_people(database, m).get("exam") or {}).get("experts") or [])]
    if not mine:
        return []
    return _rows(_table(database, EXAMPLES)
                 .select("id,model_id,source,private,kind,content,sureness,speaker_id,added_by,snippet_id")
                 .in_("model_id", mine).eq("in_exam", True))


def with_clips(database: Any, examples: list[dict]) -> list[dict]:
    """A voice example's clip for the teacher's screen (MOD-08): a short-lived
    signed link and the moment's window, through the path the blind coach
    sheets use (``services/snippet_audio_url.py``), audio and offsets only.
    The speaker, the Take and the snippet are never in what the teacher
    receives; recordings never leave WillpowerLab (N528 item 10)."""
    ids = [str(e["snippet_id"]) for e in examples if e.get("snippet_id") and e.get("source") == "takes"]
    if not ids:
        return examples
    from services.snippet_audio_url import snippet_clip_playback, snippet_rows_by_id
    rows = snippet_rows_by_id(database, ids)
    out = []
    for e in examples:
        row = rows.get(str(e.get("snippet_id") or ""))
        if row is not None:
            play = snippet_clip_playback(row, database)
            if play.get("audio_ref"):
                e = {**e, "content": {**(e.get("content") or {}), "audio_url": play["audio_ref"],
                                      "start_offset_ms": play["start_offset_ms"],
                                      "duration_ms": play["duration_ms"]}}
        out.append(e)
    return out


def chat_rows_for(database: Any, user_id: Any) -> dict:
    me = _require(database, user_id)
    mine = _teaching(database, me)
    if not mine:
        return {"rows": rules.chat_rows(0, 0, teaches_any=False)}
    q = queue_for(database, me)
    return {"rows": rules.chat_rows(len(q["examples"]), sum(1 for r in q["models"] if not r["paused"]),
                                    teaches_any=True)}


def answer(database: Any, user_id: Any, example_id: Any, model_id: Any, step: str, value: Any) -> dict:
    """Save one answer for every model it counts for (N566 item 7), then
    return what follows: the note, the next model's question on the same
    example, and once, "Your answers now count." The machine's read is
    never returned here (Never 2)."""
    me = _require(database, user_id)
    if step not in ("rate", "pick", "words"):
        raise ChatsError("BAD_STEP", "Unknown step.")
    model = _model(database, model_id)
    if rules.viewer_role(model, me) not in ("owner", "contributor"):
        raise _not_found()
    eid = _uuid(example_id)
    rows = _rows(_table(database, EXAMPLES).select("id,model_id,private,snippet_id,known_answer")
                 .eq("id", eid).eq("model_id", model["id"]).limit(1)) if eid else []
    if not rows:
        raise _not_found()
    example = rows[0]
    if example.get("private") and model["id"] not in _sees_private(database, me, [model]):
        raise _not_found()
    wanting: list[dict] = []
    twins: list[dict] = []
    if not example.get("private") and example.get("snippet_id"):
        twins = _rows(_table(database, EXAMPLES).select("id,model_id").eq("snippet_id", example["snippet_id"])
                      .eq("private", False).eq("in_exam", False))
        twin_models = _models(database, sorted({str(t["model_id"]) for t in twins} - {model["id"]}))
        wanting = [m for m in twin_models if rules.viewer_role(m, me) in ("owner", "contributor")]
    plan = rules.counts_for(example, model, wanting)
    text = None if value is None else str(value)[:4000]
    twin_ids = {str(t["model_id"]): str(t["id"]) for t in twins}
    for m in plan["counts_for"]:
        ex_id = str(example["id"]) if m["id"] == model["id"] else twin_ids[m["id"]]
        _save_answer(database, ex_id, m["id"], me, step, text)
    told = _trust_after_answer(database, me, model)
    for m in plan["counts_for"]:
        recount(database, m["id"], [str(example["id"]) if m["id"] == model["id"] else twin_ids[m["id"]]])
    return {"saved": True, "note": plan["note"],
            "follow": [{"model_id": f["model"]["id"], "line": f["line"],
                        "screen": rules.teaching_screen(f["model"], {"id": twin_ids.get(f["model"]["id"])})}
                       for f in plan["follow"]],
            "trust": told}


def _save_answer(database: Any, example_id: str, model_id: str, me: str, step: str,
                 text: Optional[str]) -> None:
    """One row per teacher, example, model and step; a second answer replaces
    the first."""
    found = _rows(_table(database, ANSWERS).select("id").eq("example_id", example_id)
                  .eq("model_id", model_id).eq("teacher_id", me).eq("step", step).limit(1))
    if found:
        _table(database, ANSWERS).update({"answer": text}).eq("id", found[0]["id"]).execute()
    else:
        _table(database, ANSWERS).insert({"example_id": example_id, "model_id": model_id,
                                          "teacher_id": me, "step": step, "answer": text,
                                          "counted": False}).execute()


def _trust_after_answer(database: Any, me: str, model: dict) -> Optional[dict]:
    """Recompute the caller's trust for this model from all their answers;
    tell them once when their answers start to count. A stop is silent."""
    mine = _rows(_table(database, ANSWERS).select("example_id,answer").eq("model_id", model["id"])
                 .eq("teacher_id", me).eq("step", "rate"))
    if not mine:
        return None
    ids = [str(a["example_id"]) for a in mine]
    known = {str(e["id"]): e.get("known_answer") for e in _rows(
        _table(database, EXAMPLES).select("id,known_answer").in_("id", ids))}
    others = [o for o in _rows(_table(database, ANSWERS).select("example_id,answer,teacher_id")
                               .in_("example_id", ids).eq("model_id", model["id"]).eq("step", "rate"))
              if str(o.get("teacher_id")) != me]
    votes: dict[str, dict[Any, int]] = defaultdict(lambda: defaultdict(int))
    for o in others:
        votes[str(o["example_id"])][o.get("answer")] += 1
    scored = []
    for a in mine:
        eid = str(a["example_id"])
        consensus = known.get(eid) or (max(votes[eid].items(), key=lambda kv: kv[1])[0] if votes.get(eid) else None)
        scored.append({"answer": a.get("answer"), "consensus": consensus, "known": bool(known.get(eid))})
    team = _rows(_table(database, TEACHERS).select("user_id,trust_status,trust_kappa,trust_told_at")
                 .eq("model_id", model["id"]))
    me_row = next((t for t in team if str(t["user_id"]) == me), {})
    ref = [float(t["trust_kappa"]) for t in team
           if t.get("trust_status") == "counts" and t.get("trust_kappa") is not None and str(t["user_id"]) != me]
    status = rules.trust_status(scored, ref, was_trusted=me_row.get("trust_status") == "counts")
    kappa = rules.reliability(scored)["kappa"]
    change: dict[str, Any] = {"trust_kappa": kappa}
    just = status != me_row.get("trust_status")
    if just:
        change.update({"trust_status": status, "trust_changed_at": _now()})
    screen = rules.trust_screen(status, just_changed=just and not me_row.get("trust_told_at"))
    if screen:
        change["trust_told_at"] = _now()
    _table(database, TEACHERS).update(change).eq("model_id", model["id"]).eq("user_id", me).execute()
    if just and status == "counts":
        recount(database, model["id"], [str(a["example_id"]) for a in mine])
    return screen


def _agrees(a: dict, answers: list[dict], trusted: set[str], known: Any, owner: str) -> bool:
    """Another trusted teacher gave the same answer, or it is the known one
    (the owner's own answer never agrees with itself: their first 10 set it)."""
    if a.get("answer") is None:
        return False
    if known is not None and str(a["answer"]) == str(known) and str(a.get("teacher_id")) != owner:
        return True
    return any(str(o.get("teacher_id")) != str(a.get("teacher_id")) and str(o.get("teacher_id")) in trusted
               and o.get("step") == a.get("step") and str(o.get("answer")) == str(a["answer"]) for o in answers)


def recount(database: Any, model_id: str, example_ids: list[str]) -> None:
    """Which answers on these examples count (N523 item 2, N570 item 4): a
    trusted teacher's, once another trusted teacher gave the same answer or
    it matches the example's known answer; a spoken answer in words, once
    its teacher is trusted. Never an answer on a sealed exam case. Nobody
    teaches a model alone. Two matching trusted answers also settle an
    example: its known answer, which the quiet trust check then measures
    newcomers against (N520 items 8 and 12)."""
    ids = sorted({str(e) for e in example_ids if e})
    if not ids:
        return
    examples = {str(e["id"]): e for e in _rows(_table(database, EXAMPLES).select("id,in_exam,known_answer")
                                                .in_("id", ids))}
    trusted = {str(t["user_id"]) for t in _rows(_table(database, TEACHERS).select("user_id,trust_status")
                                                 .eq("model_id", model_id)) if t.get("trust_status") == "counts"}
    answers = _rows(_table(database, ANSWERS).select("id,example_id,teacher_id,step,answer,counted")
                    .eq("model_id", model_id).in_("example_id", ids))
    found = _rows(_table(database, MODELS).select("owner_id").eq("id", model_id).limit(1))
    owner = str((found[0].get("owner_id") if found else "") or "")
    by_example: dict[str, list[dict]] = defaultdict(list)
    for a in answers:
        by_example[str(a["example_id"])].append(a)
    for eid, theirs in by_example.items():
        example = examples.get(eid) or {}
        known = example.get("known_answer")
        for a in theirs:
            ok = (not example.get("in_exam") and str(a.get("teacher_id")) in trusted
                  and (a.get("step") == "words" or _agrees(a, theirs, trusted, known, owner)))
            if bool(a.get("counted")) != ok:
                _table(database, ANSWERS).update({"counted": ok}).eq("id", a["id"]).execute()
        if known is None and not example.get("in_exam"):
            settled = _settled(theirs, trusted)
            if settled is not None:
                _table(database, EXAMPLES).update({"known_answer": settled}).eq("id", eid).execute()


def _settled(answers: list[dict], trusted: set[str]) -> Optional[str]:
    """Two trusted teachers' matching rating or pick (label_quorum's two votes)."""
    votes: dict[str, set[str]] = defaultdict(set)
    for a in answers:
        if a.get("step") in ("rate", "pick") and a.get("answer") is not None and str(a.get("teacher_id")) in trusted:
            votes[str(a["answer"])].add(str(a["teacher_id"]))
    agreed = [v for v, who in votes.items() if len(who) >= 2]
    return agreed[0] if len(agreed) == 1 else None


def profile_for(database: Any, user_id: Any, person_id: Any) -> Optional[dict]:
    me = _require(database, user_id)
    pid = _uuid(person_id)
    if not pid:
        raise _not_found()
    mine = _rows(_table(database, TEACHERS).select("model_id").eq("user_id", pid))
    owned = _rows(_table(database, MODELS).select("id").eq("owner_id", pid))
    ids = sorted({str(t["model_id"]) for t in mine} | {str(m["id"]) for m in owned})
    models = [m for m in _models(database, ids)
              if pid == me or rules.viewer_role(m, me) is not None]
    month = datetime.now(timezone.utc).strftime("%Y-%m-01")
    counted = [a for a in _rows(_table(database, ANSWERS).select("model_id,created_at")
                                .eq("teacher_id", pid).eq("counted", True))
               if str(a.get("created_at") or "") >= month]
    per: dict[str, int] = defaultdict(int)
    for a in counted:
        per[str(a["model_id"])] += 1
    section = rules.profile_models(models, pid, per)
    if section and pid != me:      # the actions are the owner's alone
        for row in section["models"]:
            row["actions"] = []
    return section


def invite_for(database: Any, user_id: Any, invite_id: Any) -> dict:
    me = _require(database, user_id)
    iid = _uuid(invite_id)
    rows = _rows(_table(database, INVITES).select("id,model_id,inviter_id,invitee_id,status")
                 .eq("id", iid).limit(1)) if iid else []
    if not rows or str(rows[0]["invitee_id"]) != me:
        raise _not_found()
    inv = rows[0]
    model = _model(database, inv["model_id"])
    prof = _rows(_table(database, "people_profiles").select("name").eq("user_id", str(inv["inviter_id"])).limit(1))
    who = (prof[0].get("name") if prof else None) or (
        model.get("owner_name") if str(model.get("owner_id")) == str(inv["inviter_id"]) else None) or "Someone"
    card = rules.invite_card(who, model["name"], said_not_now=inv.get("status") == "not_now")
    card["chat_link"] = _chat_link_of(database, str(inv["inviter_id"]))
    return card


def _chat_link_of(database: Any, user_id: str) -> Optional[str]:
    """The inviter's own chat link: an invitation to teach goes through it,
    and the teacher teaches by using that chat (N598 items 1 and 2). Opening
    it joins the chat the two already share (services/chat_links.py, one
    chat a pair). None when the inviter has no live link."""
    try:
        from services.chat_links import _live
        link = _live(database, user_id)
    except Exception:
        logger.warning("ai_models: the inviter's chat link could not be read", exc_info=True)
        return None
    return f"/c/{link['token']}" if link else None


# ── The invites (MOD-49; N528 item 3) ───────────────────────────────────────
def invites_for(database: Any, user_id: Any) -> dict:
    """The caller's invites, open or put off ("Not now" keeps them)."""
    me = _require(database, user_id)
    rows = [r for r in _rows(_table(database, INVITES).select("id,model_id,status").eq("invitee_id", me))
            if r.get("status") in ("open", "not_now")]
    return {"invites": [{"id": str(r["id"]), "model_id": str(r["model_id"]),
                         **invite_for(database, me, r["id"])} for r in rows]}


def answer_invite(database: Any, user_id: Any, invite_id: Any, accept: bool) -> dict:
    """ "Not now": the invite stays and can be opened at any time. Accept: the
    caller teaches the model; their answers count once the quiet trust check
    admits them, as at the door."""
    me = _require(database, user_id)
    iid = _uuid(invite_id)
    rows = _rows(_table(database, INVITES).select("id,model_id,inviter_id,invitee_id,status")
                 .eq("id", iid).limit(1)) if iid else []
    if not rows or str(rows[0]["invitee_id"]) != me:
        raise _not_found()
    inv = rows[0]
    _table(database, INVITES).update({"status": "accepted" if accept else "not_now", "answered_at": _now()}) \
        .eq("id", inv["id"]).execute()
    if accept and not _rows(_table(database, TEACHERS).select("user_id").eq("model_id", inv["model_id"])
                            .eq("user_id", me).limit(1)):
        _table(database, TEACHERS).insert({"model_id": inv["model_id"], "user_id": me, "role": "contributor",
                                           "door_accepted_at": _now()}).execute()
    return {"status": "accepted" if accept else "not_now", "model_id": str(inv["model_id"]),
            "chat_link": _chat_link_of(database, str(inv["inviter_id"])) if accept else None}


# ── Add an example (MOD-21; N563 item 4, N566 item 6) ───────────────────────
MAX_ADDED_TEXT = 4000


def add_example(database: Any, user_id: Any, model_id: Any, body: Any) -> dict:
    """A case a teacher knows well, in words: typed, a written file's text,
    or what they said in "Record one" (recorded through the chats' recording
    path, which takes the processing-authorization path; only its words
    arrive here). The adder answers it at once; it counts once another
    teacher agrees (``rules.added_example_counts``)."""
    me = _require(database, user_id)
    model = _model(database, model_id)
    if rules.viewer_role(model, me) not in ("owner", "contributor"):
        raise _not_found()
    body = body if isinstance(body, dict) else {}
    text = str(body.get("text") or body.get("transcript") or "").strip()[:MAX_ADDED_TEXT]
    if not text:
        raise ChatsError("EMPTY", "Write or say the case first.")
    step = str(body.get("step") or "rate")
    if step not in ("rate", "pick", "words"):
        raise ChatsError("BAD_STEP", "Unknown step.")
    made = _rows(_table(database, EXAMPLES).insert({
        "model_id": model["id"], "source": "teacher", "private": model.get("visibility") == "private",
        "added_by": me, "in_exam": False, "content": {"text": text}}))
    if not made:
        raise ChatsError("V2_ERROR", "The example could not be kept.", 500)
    if body.get("answer") is not None:
        _save_answer(database, str(made[0]["id"]), model["id"], me, step, str(body["answer"])[:4000])
    return {"example_id": str(made[0]["id"]), "note": rules.WORDS["add_counts_once"]}


# ── The owner's actions (MOD-50, MOD-51; N528 items 5 and 12) ───────────────
def _owner(database: Any, me: str, model_id: Any) -> dict:
    model = _model(database, model_id)
    if rules.viewer_role(model, me) != "owner":
        raise _not_found()
    return model


def archive(database: Any, user_id: Any, model_id: Any) -> dict:
    """Archive hides a model from every list and deletes nothing (N528 item 5)."""
    me = _require(database, user_id)
    model = _owner(database, me, model_id)
    _table(database, MODELS).update({"status": "archived", "updated_at": _now()}).eq("id", model["id"]).execute()
    return {"status": "archived"}


def make_public(database: Any, user_id: Any, model_id: Any, confirmed: bool) -> dict:
    """Public at once, but only after its disclaimer (N528 item 5): without
    ``confirm`` nothing changes."""
    me = _require(database, user_id)
    model = _owner(database, me, model_id)
    if not confirmed:
        raise ChatsError("CONFIRM", "Read what making it public means first.")
    _table(database, MODELS).update({"visibility": "public", "updated_at": _now()}).eq("id", model["id"]).execute()
    return {"visibility": "public"}


def teaches(database: Any, user_id: Any, model_id: Any) -> dict:
    """The model, when the caller is its owner or a teacher; else 404."""
    me = _require(database, user_id)
    model = _model(database, model_id)
    if rules.viewer_role(model, me) not in ("owner", "contributor"):
        raise _not_found()
    return model


def transcribe(audio: bytes, content_type: Any, filename: str, *, adapter: Any, user_id: str,
               model_id: Any, most: int) -> dict:
    """What was said, under the caller's authorization (``adapter``, bound by
    the route's processing-authorization path). The recording is not kept
    anywhere: only its words are returned (N528 item 10)."""
    kind = str(content_type or "").strip()
    if not audio:
        raise ChatsError("NOT_ALLOWED", "No recording.")
    if not kind.startswith("audio/"):
        raise ChatsError("NOT_ALLOWED", "Only an audio recording.")
    if len(audio) > most:
        raise ChatsError("TOO_LARGE", "A recording is at most 12 MB.", 413)
    result = adapter.transcribe_audio(audio, filename, usage_surface="model_spoken_answer",
                                      usage_user_id=user_id, usage_session_id=str(model_id)) or {}
    words = str(result.get("text") or "").strip()[:4000]
    if not words:
        raise ChatsError("NO_WORDS", "We could not hear any words. Try again.")
    return {"transcript": words}
