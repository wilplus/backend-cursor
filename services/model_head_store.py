"""A model that learns, in storage: it reads the tables of migration
a_model_learns_from_its_settled_examples into the shapes
``services/model_head.py`` takes, and writes the kept vectors and the
versions. The rules are all there.

THE READER (N616 items 8 and 9). Each example is read ONCE into a vector,
which is kept (``ai_model_example_vectors``) and never read again by the
provider. Text: the example's words through the shared reader
(``llm_config.READER_MODEL``). Voice: the clip's words through the same
reader, and the voice measures already stored for the clip (the snippet's
``metrics``) appended. A photo has no reader: no model that reads one is
fitted, offered or answered from (LEARN-06). Every reader call is one
provider call (``services.llm.embed``) with a maximum length, under a
processing authority: the model owner's for the background fit
(``user_provider_scope``), the asker's or the buyer's for an answer (bound
by their route).

THE FIT runs in the periodic sweep (``services/pipeline_jobs.py``), never in
a web request: ``sweep``. It reads only the model's SETTLED examples
(``model_head.learnable``): never an exam case, never another model's
example, never a speaker who may no longer teach (checked again here, not
only at the next let-go). Each version records the ids it was fitted on
(PIPE-06); a deleted or withdrawn example marks every version that learned
from it (``mark_retrain``, and the migration's trigger for every other
deletion), and the next fit leaves it out.

  * ``sweep``             fit every model that needs it (bounded a run)
  * ``fit_model``         one model's fit, its exam, its version
  * ``head_answer``       one answer from a version's head (one reader call)
  * ``chat_answers``      the heads' answers for a visitor's message (one reader call)
  * ``check_for``, ``check_answer``   the owner's check (LEARN-03)
  * ``learning_for``      where the model is: its head, its gates
  * ``mark_retrain``      PIPE-06, before an example is deleted
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from services import model_head as rules
from services import model_launchpad as launchpad
from services import model_launchpad_store as models
from services.chats import ChatsError, _not_found, _rows, _table, _uuid

logger = logging.getLogger(__name__)

VECTORS, VERSIONS = "ai_model_example_vectors", "ai_model_versions"
#: The voice measures appended to a voice clip's vector, each over a rough
#: scale so none outweighs the words (migration add_charisma_snippets_metrics_column).
VOICE_MEASURES = (("wpm", 200.0), ("pause_ms", 1000.0), ("dynamic_db", 20.0),
                  ("emphasis_per_min", 20.0), ("energy_ratio", 1.0), ("pitch_center_st", 12.0))
#: Texts sent to the reader in one call, at most.
BATCH = 100
#: Models fitted a sweep, at most.
FIT_LIMIT = 5


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def kind_of(model: dict) -> str:
    return str((model.get("recipe") or {}).get("input") or "voice")


def readable(model: dict) -> bool:
    """A model a reader exists for: voice and text, never a photo (LEARN-06)."""
    return kind_of(model) in ("voice", "text")


def _text(example: dict) -> str:
    raw = example.get("content")
    content: dict = raw if isinstance(raw, dict) else {}
    return str(content.get("text") or content.get("words") or "").strip()


# ── The reader ──────────────────────────────────────────────────────────────
def _measures(database: Any, snippet_ids: list[str]) -> dict[str, list[float]]:
    if not snippet_ids:
        return {}
    from services.snippet_tables import SNIPPETS_TABLE
    out: dict[str, list[float]] = {}
    for i in range(0, len(snippet_ids), 200):
        try:
            rows = _rows(_table(database, SNIPPETS_TABLE).select("id,metrics")
                         .in_("id", snippet_ids[i:i + 200]))
        except Exception:  # noqa: BLE001 -- the words alone, then
            logger.warning("model head: voice measures could not be read", exc_info=True)
            rows = []
        for r in rows:
            out[str(r["id"])] = measures_of(r.get("metrics"))
    return out


def measures_of(metrics: Any) -> list[float]:
    m = metrics if isinstance(metrics, dict) else {}
    out = []
    for key, scale in VOICE_MEASURES:
        value = m.get(key)
        try:
            out.append(float(value) / scale if value is not None else 0.0)
        except (TypeError, ValueError):
            out.append(0.0)
    return out


def read(texts: list[str], *, surface: str) -> Optional[list[list[float]]]:
    """The shared reader: one provider call for up to ``BATCH`` texts."""
    from services import llm
    return llm.embed(texts, surface=surface)


def vectors_for(database: Any, model: dict, examples: list[dict]) -> dict[str, list[float]]:
    """Each example's vector: the kept one, else read ONCE now and kept."""
    ids = [str(e["id"]) for e in examples]
    kept: dict[str, list[float]] = {}
    for i in range(0, len(ids), 200):
        for r in _rows(_table(database, VECTORS).select("example_id,vector").in_("example_id", ids[i:i + 200])):
            kept[str(r["example_id"])] = [float(v) for v in r.get("vector") or []]
    fresh = [e for e in examples if str(e["id"]) not in kept and _text(e)]
    voice = kind_of(model) == "voice"
    from services.llm_config import READER_MODEL
    for i in range(0, len(fresh), BATCH):
        part = fresh[i:i + BATCH]
        got = read([_text(e) for e in part], surface="model_reader")
        if not got:
            logger.warning("model head: the reader gave nothing model=%s", model.get("id"))
            break
        measured = _measures(database, [str(e["snippet_id"]) for e in part if e.get("snippet_id")]) if voice else {}
        for e, vec in zip(part, got):
            if voice:
                vec = list(vec) + measured.get(str(e.get("snippet_id")), [0.0] * len(VOICE_MEASURES))
            kept[str(e["id"])] = vec
            try:
                _table(database, VECTORS).insert({"example_id": str(e["id"]), "reader": READER_MODEL,
                                                  "vector": vec}).execute()
            except Exception:  # noqa: BLE001 -- kept by another run already
                logger.warning("model head: a vector was not kept example=%s", e["id"], exc_info=True)
    return kept


def message_vector(model: dict, text: str, *, surface: str) -> Optional[list[float]]:
    """A new message read once, in the same shape as the model's examples
    (a voice model's measures are unknown for words alone: zeros)."""
    got = read([text], surface=surface)
    if not got:
        return None
    return extend(model, got[0])


def extend(model: dict, vec: list[float]) -> list[float]:
    return list(vec) + ([0.0] * len(VOICE_MEASURES) if kind_of(model) == "voice" else [])


# ── What a fit may read (LEARN-01) ──────────────────────────────────────────
_EX_FIELDS = "id,model_id,source,private,speaker_id,snippet_id,content,known_answer,in_exam,created_at"


def _examples(database: Any, model_id: str) -> list[dict]:
    from services.model_api_store import _all
    return _all(lambda: _table(database, models.EXAMPLES).select(_EX_FIELDS).eq("model_id", model_id))


def settled_examples(database: Any, model: dict, examples: Optional[list[dict]] = None) -> list[dict]:
    """The model's own settled examples a head may learn from: never an exam
    case, never another model's, never a speaker who may no longer teach."""
    from services.model_examples_from_takes import speaker_may_teach
    examples = examples if examples is not None else _examples(database, model["id"])
    answers = set(rules.answers_of(model.get("recipe")))
    own = [e for e in examples if str(e.get("model_id")) == str(model["id"])
           and str(e.get("known_answer")) in answers]
    speakers = sorted({str(e["speaker_id"]) for e in own if e.get("source") == "takes" and e.get("speaker_id")})
    may = {s: bool(speaker_may_teach(database, s).get("ok")) for s in speakers}
    return [e for e in own if rules.learnable(e, may_teach=may)]


# ── Versions ────────────────────────────────────────────────────────────────
_V_FIELDS = ("id,model_id,number,status,base_model,provider_model,founder_id,card,exam,created_at,"
             "released_at,head,confidence,example_ids,retrain_at,owner_check,owner_checked_at")


def versions(database: Any, model_id: str) -> list[dict]:
    rows = _rows(_table(database, VERSIONS).select(_V_FIELDS).eq("model_id", model_id))
    return sorted(rows, key=lambda v: int(v.get("number") or 0))


def latest_with_head(vs: list[dict]) -> Optional[dict]:
    with_head = [v for v in vs if v.get("head") and v.get("status") != "retired"]
    return with_head[-1] if with_head else None


def _exam(database: Any, model: dict, head_version: dict, before: Optional[dict]) -> dict:
    """The app's exam (LEARN-05): the head on the cases both experts settled."""
    from services import model_setup as S
    from services.model_setup_store import with_people
    found = _rows(_table(database, models.MODELS).select("id,owner_id,setup").eq("id", model["id"]).limit(1))
    experts = (with_people(database, found[0]).get("exam") or {}).get("experts") or [] if found else []
    cases = [e for e in _examples(database, model["id"]) if e.get("in_exam")]
    answers = _rows(_table(database, models.ANSWERS).select("example_id,teacher_id,answer")
                    .eq("model_id", model["id"])) if cases else []
    truth: dict[str, str] = {}
    for c in cases:
        got = S.exam_settled([a for a in answers if str(a["example_id"]) == str(c["id"])], experts)
        if got is not None:
            truth[str(c["id"])] = got
    settled_cases = [c for c in cases if str(c["id"]) in truth]
    vecs = vectors_for(database, model, settled_cases) if settled_cases else {}
    scored = []
    for c in settled_cases:
        a = rules.answer(head_version, vecs.get(str(c["id"])))
        if a is not None:
            scored.append({"example_id": str(c["id"]), "truth": truth[str(c["id"])], "guess": a["answer"]})
    target = int((model.get("targets") or {}).get("exam") or S.EXAM_CASES)
    if before is None:
        # The first version must beat the untrained one (N528 item 8): the
        # recipe card's answer on the same cases, asked once, at this fit.
        return rules.exam_result(scored, target, {"right": untrained(model, settled_cases, truth)}, first=True)
    return rules.exam_result(scored, target, before.get("exam"))


def untrained(model: dict, cases: list[dict], truth: dict[str, str]) -> dict[str, bool]:
    """The untrained version on the exam: the recipe card's answer (one
    cheap-model call a case, once per model, under the owner's authority
    bound by the sweep). A case it gives no answer to counts as wrong."""
    from services.model_api_store import _ask
    out: dict[str, bool] = {}
    for c in cases:
        try:
            got = _ask(model, None, _text(c))
        except Exception:  # noqa: BLE001 -- no answer: wrong
            logger.warning("model head: the untrained answer failed example=%s", c["id"], exc_info=True)
            got = None
        said = str((got or {}).get("answer") or "").strip().lower()
        out[str(c["id"])] = bool(said) and said == truth[str(c["id"])].lower()
    return out


def fit_model(database: Any, model: dict) -> Optional[dict]:
    """One model's fit: its settled examples' vectors, the head, its
    confidence, the exam against the version before, and a new version that
    records what it learned from. None when there is not enough to learn."""
    if not readable(model):
        return None
    answers = rules.answers_of(model.get("recipe"))
    settled = settled_examples(database, model)
    if not rules.enough([str(e["known_answer"]) for e in settled], answers):
        return None
    vecs = vectors_for(database, model, settled)
    use = [e for e in settled if str(e["id"]) in vecs]
    fitted = rules.fit([vecs[str(e["id"])] for e in use], [str(e["known_answer"]) for e in use], answers)
    if fitted is None:
        return None
    vs = versions(database, model["id"])
    before = latest_with_head(vs)
    probe = {"head": fitted["head"], "confidence": fitted["confidence"]}
    exam = _exam(database, model, probe, before)
    from services.model_api_store import record_version
    made = record_version(database, model["id"], provider_model=None, card=(before or {}).get("card") or {},
                          exam=exam, head=fitted["head"], confidence=fitted["confidence"],
                          example_ids=[str(e["id"]) for e in use])
    _table(database, models.MODELS).update({"retrain_at": None}).eq("id", model["id"]).execute()
    return {**made, "learned_from": len(use), "passed": bool(exam.get("passed"))}


def _needs(database: Any, model: dict) -> bool:
    vs = versions(database, model["id"])
    settled = len(settled_examples(database, model))
    return rules.needs_fit(latest_with_head(vs), settled, queued=bool(model.get("retrain_at")))


def sweep(*, database: Any = None, limit: int = FIT_LIMIT) -> dict:
    """Fit every model that needs it, up to ``limit`` a run, each under its
    owner's processing authority. Never raises."""
    if database is None:
        from services.db import db as database
    out = {"fitted": 0, "checked": 0}
    try:
        from services.model_api_store import _all
        rows = _all(lambda: _table(database, models.MODELS).select("id,owner_id,status,recipe,targets,retrain_at"))
    except Exception:
        logger.warning("model head: the models could not be read", exc_info=True)
        return out
    for m in rows:
        if out["fitted"] >= limit:
            break
        if m.get("status") not in ("learning", "ready") or not readable(m) or not m.get("owner_id"):
            continue
        try:
            out["checked"] += 1
            if not _needs(database, m):
                continue
            from routes.v2.processing_authorization import user_provider_scope
            with user_provider_scope(str(m["owner_id"]), operation="ai_conversation", prefix="model-head"):
                if fit_model(database, m):
                    out["fitted"] += 1
        except Exception:
            logger.warning("model head: a fit failed model=%s", m.get("id"), exc_info=True)
    return out


def queue_fit(database: Any, model_id: Any) -> dict:
    """WillpowerLab's founder asks for a new fit; the sweep runs it."""
    model = models._model(database, model_id)
    _table(database, models.MODELS).update({"retrain_at": _now()}).eq("id", model["id"]).execute()
    return {"queued": True}


# ── PIPE-06 ─────────────────────────────────────────────────────────────────
def mark_retrain(database: Any, example_ids: list[str], model_ids: list[str]) -> int:
    """Every version that learned from one of these examples is marked to
    retrain. Called before the examples are deleted; the migration's
    trigger does the same for any other deletion."""
    gone = {str(e) for e in example_ids}
    if not gone:
        return 0
    marked = 0
    for mid in sorted({str(m) for m in model_ids}):
        for v in _rows(_table(database, VERSIONS).select("id,example_ids,retrain_at").eq("model_id", mid)):
            if not v.get("retrain_at") and gone & {str(e) for e in v.get("example_ids") or []}:
                _table(database, VERSIONS).update({"retrain_at": _now()}).eq("id", v["id"]).execute()
                marked += 1
    return marked


# ── Answering ───────────────────────────────────────────────────────────────
def head_answer(model: dict, version: Optional[dict], text: str, *, surface: str) -> Optional[dict]:
    """{answer, sure} from the version's head with one reader call, or None
    when the version has no head (the caller falls back to the recipe card)."""
    if not version or not version.get("head") or not readable(model):
        return None
    vec = message_vector(model, text, surface=surface)
    if vec is None:
        return {"answer": "", "sure": False}
    got = rules.answer(version, vec)
    return {"answer": got["answer"], "sure": got["sure"]} if got else {"answer": "", "sure": False}


def chat_answers(database: Any, host_id: str, recipe_models: list[dict], text: str) -> dict[int, dict]:
    """The heads' answers for a visitor's message, by the recipe model's
    place: ONE reader call for all of them (N620: two provider calls at
    most, with the chat's own). A host's own model answers once its owner's
    check passed (gate one); another person's only after a passed exam
    (gate two). A model with neither answers nothing here. An answer that
    is not sure is returned as such: its line is left out of the chat."""
    picked: list[tuple[int, dict, dict]] = []
    for i, m in enumerate(recipe_models):
        mid = _uuid(m.get("model_id"))
        if not mid:
            continue
        found = _rows(_table(database, models.MODELS).select("id,owner_id,recipe").eq("id", mid).limit(1))
        if not found or not readable(found[0]):
            continue
        model = found[0]
        vs = versions(database, mid)
        own = str(model.get("owner_id")) == str(host_id)
        open_ = [v for v in vs if v.get("head") and v.get("status") != "retired"
                 and rules.gates(v)["owner_chat" if own else "share"]]
        if open_:
            picked.append((i, model, open_[-1]))
    if not picked:
        return {}
    got = read([text], surface="model_reader")
    if not got:
        return {}
    out: dict[int, dict] = {}
    for i, model, version in picked:
        a = rules.answer(version, extend(model, got[0]))
        if a:
            out[i] = {"answer": a["answer"], "sure": bool(a["sure"])}
    return out


# ── The owner's check (LEARN-03) and the gates (LEARN-04) ───────────────────
def _owner_model(database: Any, user_id: Any, model_id: Any) -> tuple[str, dict]:
    me = models._require(database, user_id)
    model = models._model(database, model_id)
    if launchpad.viewer_role(model, me) != "owner":
        raise _not_found()
    return me, model


def _first_ten(database: Any, model_id: str) -> list[str]:
    found = _rows(_table(database, models.MODELS).select("setup").eq("id", model_id).limit(1))
    setup = (found[0].get("setup") if found else None) or {}
    return [str(f.get("example_id")) for f in setup.get("first_ten") or [] if isinstance(f, dict)]


def _check_screen(model: dict, version: dict, examples: dict[str, dict]) -> dict:
    check = version.get("owner_check") or {}
    items = []
    for it in check.get("items") or []:
        ex = examples.get(str(it["example_id"]))
        if ex is None:
            continue
        items.append({"example_id": it["example_id"], "example": launchpad.example_for_teacher(ex),
                      "guess": it.get("guess"), "kept": it.get("kept"), "answer": it.get("answer")})
    return {"version": int(version["number"]), "answers": rules.answers_of(model.get("recipe")),
            "items": items, "done": bool(items) and all(i["kept"] is not None for i in items),
            "passed": bool(version.get("owner_checked_at"))}


def check_for(database: Any, user_id: Any, model_id: Any) -> dict:
    """The owner's check of the newest version with a head: ten examples it
    was not fitted on, chosen once (N620: once per version), the head's
    guess first. The reader runs once for those ten, and only the first time."""
    _me, model = _owner_model(database, user_id, model_id)
    version = latest_with_head(versions(database, model["id"]))
    if version is None:
        raise _not_found()
    examples = {str(e["id"]): e for e in _examples(database, model["id"])}
    check = version.get("owner_check") or {}
    if not check.get("items"):
        ids = rules.check_pool(list(examples.values()), version.get("example_ids") or [],
                               _first_ten(database, model["id"]), str(version["id"]))
        vecs = vectors_for(database, model, [examples[i] for i in ids])
        items = []
        for i in ids:
            a = rules.answer(version, vecs.get(i))
            if a:
                items.append({"example_id": i, "guess": a["answer"], "kept": None, "answer": None})
        check = {"items": items}
        _table(database, VERSIONS).update({"owner_check": check}).eq("id", version["id"]).execute()
        version["owner_check"] = check
    return _check_screen(model, version, examples)


def check_answer(database: Any, user_id: Any, model_id: Any, body: Any) -> dict:
    """Keep or Change on one of the ten. The owner's answer also goes in
    through the ordinary teacher-answer path, with every refusal it has."""
    me, model = _owner_model(database, user_id, model_id)
    body = body if isinstance(body, dict) else {}
    version = latest_with_head(versions(database, model["id"]))
    if version is None:
        raise _not_found()
    check = dict(version.get("owner_check") or {})
    items = [dict(i) for i in check.get("items") or []]
    eid = str(_uuid(body.get("example_id")) or body.get("example_id") or "")
    item = next((i for i in items if str(i["example_id"]) == eid), None)
    if item is None:
        raise _not_found()
    answers = rules.answers_of(model.get("recipe"))
    keep = body.get("keep") is True
    chosen = item["guess"] if keep else str(body.get("answer") or "")
    if chosen not in answers:
        raise ChatsError("BAD_ANSWER", "Choose one of the answers.", 400)
    item.update({"kept": keep, "answer": chosen})
    check["items"] = items
    update: dict[str, Any] = {"owner_check": check}
    if rules.check_passed(items) and not version.get("owner_checked_at"):
        update["owner_checked_at"] = _now()
        version["owner_checked_at"] = update["owner_checked_at"]
    _table(database, VERSIONS).update(update).eq("id", version["id"]).execute()
    version["owner_check"] = check
    steps = (model.get("recipe") or {}).get("steps") or []
    step = "rate" if (model.get("recipe") or {}).get("scale") and "rate" in steps else "pick"
    try:
        models.answer(database, me, eid, model["id"], step, chosen)
    except ChatsError:
        pass  # refused there (an example they added, say): the check keeps it all the same
    examples = {str(e["id"]): e for e in _examples(database, model["id"])}
    return _check_screen(model, version, examples)


def learning_for(database: Any, user_id: Any, model_id: Any) -> dict:
    _me, model = _owner_model(database, user_id, model_id)
    vs = versions(database, model["id"])
    v = latest_with_head(vs)
    open_ = {"owner_chat": any(rules.gates(x)["owner_chat"] for x in vs),
             "share": any(rules.gates(x)["share"] for x in vs)}
    exam = (v or {}).get("exam") or {}
    return {"version": int(v["number"]) if v else None, "has_head": v is not None,
            "retrain": bool((v or {}).get("retrain_at") or model.get("retrain_at")),
            "gates": open_,
            "exam": ({k: exam.get(k) for k in ("passed", "better", "worse", "same")}
                     if exam.get("computed") else None)}
