"""The model launchpad's rules: the list of AI models, a model's page,
teaching it, and the one queue (N520, N521, N523, N526, N528, N531, N563,
N566, N570, N571, N577, N580, N581; the locked prototype
``docs/design/model-launchpad-2026-11-09/``, version 8).

This module is the launchpad's business logic, with no storage of its own.
Every function takes plain dicts and returns plain dicts, so the tables that
hold models (their own migration, with its outside review) and the routes
that serve them only read rows and hand them here. The rules live once.

THE SHAPES (what a storage layer hands in):

  model = {
    "id": str, "name": str, "owner_id": str, "owner_name": str,
    "visibility": "public" | "private",
    "status": "draft" | "learning" | "ready" | "archived",
    "field": str, "description": str,
    "draft_step": str | None,          # where the owner stopped, for a draft
    "recipe": {                         # the recipe card (N563 item 2, N570)
      "input": "voice" | "text" | "image",
      "steps": ["rate"] | ["pick", "words"] | ...,   # in the order asked
      "question": str,                  # the teachers' question (N570 item 1)
      "scale": [str, ...],              # rate: the answers, in order
      "pick_question": str, "options": [str, ...],   # pick (N570 item 2)
    },
    "jars": {"counted_answers": int, "exam_cases": int},
    "targets": {"counted_answers": int, "exam_cases": int},   # optional
    "teachers": int,                    # people whose answers count
    "owner_ids": [str], "contributor_ids": [str],
  }

  example = {
    "id": str, "model_id": str,
    "source": "takes" | "upload" | "business" | "teacher",   # N563 item 4
    "private": bool,                    # a company's own data (N563 item 3)
    "added_by": str | None,             # a teacher who added it (N563 item 4)
    "sureness": float | None,           # how sure the model is, 0..1
    "kind": str | None,                 # the kind of case, for "kinds it lacks"
    # what the machine read; NEVER shown before the teacher answers (Never 2)
    "machine_label": ..., "machine_score": ..., "draft": ..., "what_happened": ...,
  }

WHAT A SPEAKER SEES (N526 item 3, Never 1): every number here is about a
model and its data, never a read on a person. No function returns a
teacher's reliability, a speaker's anything, or a score about the viewer.
The one number about a teacher is the count of their own answers that
counted, on their own profile (the prototype's "86 answers counted this
month"), which is a count of their work, not a verdict on them.
"""
from __future__ import annotations

import logging
import math
import re
from collections import defaultdict
from statistics import median
from typing import Any, Iterable

logger = logging.getLogger(__name__)

# ── Signed words (N566 item 1: the locked prototype's words are signed) ─────
WORDS: dict[str, str] = {
    # the list of chats (MOD-04, N528 item 1)
    "row_models": "AI models",
    "row_models_line": "Teach one, or start your own",
    "row_queue": "Your queue",
    # the list (MOD-05, N566 items 2 and 11)
    "list_intro": ("Each model learns one skill from people who know it well. "
                   "The ones furthest along are at the top."),
    "filter_for_you": "For you",
    "filter_ready": "Ready to use",
    "filter_learning": "Still learning",
    "what_do_i_get": "What do I get?",
    "your_draft": "Your draft",
    "continue": "Continue",
    "teach_it": "Teach it",
    "use_it": "Use it",
    "open": "Open",
    "try_it": "Try it",
    "start_your_own": "Start your own",
    "public": "Public",
    "private": "Private",
    # the empty search (MOD-13)
    "search_empty_title": "No models here yet.",
    "search_empty_line": "Nobody has started a model about this. You could be the first.",
    "search_empty_start": "Start the first one",
    "search_empty_clear": "Clear the search",
    # the door (MOD-07, N528 items 2 and 10)
    "door_title": "Before you teach",
    "door_why": "Everyone who uses this model relies on what it learns from you.",
    "door_field": ("Teach it only what you know well. If this is not your field, "
                   "your answers would make it worse for all of us."),
    "door_recordings": ("It learns from your ratings and the words of your answers. "
                        "Your voice recordings stay with WillpowerLab."),
    "door_yes": "This is my field",
    "door_no": "Not now",
    # teaching (MOD-08, MOD-19, MOD-20)
    "judge_title": "Judge this moment",
    "audio_unclear": "Audio unclear",
    "skip": "Skip",
    "words_step": "Now say how you would answer them, in your own words.",
    "record_answer": "Record your answer",
    # the quiet trust check (MOD-10, N520 item 8, N523 item 2)
    "trust_in": "Your answers now count.",
    "trust_in_tokens": ("You earn a token for each answer that counts. When businesses "
                        "start paying to use this model, you also get a share of what it earns."),
    "keep_teaching": "Keep teaching",
    "back_to_list": "Back to the list",
    # What do I get? (MOD-12)
    "get_teach": "Teach a model",
    "get_teach_line": ("Earn a token for every answer that counts, and a share of what "
                       "the model earns once businesses pay for it."),
    "get_start": "Start a model",
    "get_start_line": ("Keep a fixed share from the first day. What you know keeps "
                       "working while you sleep."),
    "get_use": "Use a model in your business",
    "get_use_line": "Try it free, create a key, and pay only for the answers you use.",
    # the queue (MOD-15, MOD-23)
    "queue_header_tail": "The ones that help most come first.",
    "queue_hint": ("Pause a model to stop its examples for a while. "
                   "Tap a model to teach only it."),
    "queue_start": "Start",
    "queue_add": "Add an example you know well",
    "pause": "Pause",
    "you_started_it": "You started it",
    "you_teach_it": "You teach it",
    "your_company": "Your company",
    "queue_empty_title": "Nothing waits for you.",
    "queue_empty_line": "Thank you. New examples come when your models need you.",
    "queue_empty_back": "Back to your chats",
    # adding an example (MOD-21)
    "add_title": "Add an example",
    "add_intro": ("Do you know a case this model should learn from? "
                  "Add it, then answer it yourself."),
    "add_record": "Record one",
    "add_record_line": "Say the case in your own voice",
    "add_upload": "Upload a file",
    "add_upload_line": "A recording, a photo or a written case",
    "add_counts_once": "It counts once another teacher agrees with your answer.",
    # release (MOD-22)
    "release_exam_intro": "On the 100 exam cases:",
    "release_not_yet_clear": "Not clearly better yet",
    "release_choice": ("Releasing it is your choice. Businesses on version {old} keep it "
                       "until they decide to switch."),
    "release_not_yet": "Not yet",
    # the invite in a chat (MOD-49, N528 item 3)
    "invite_said_not_now": "You said not now. The invite stays here; open it whenever you like.",
    # the profile (MOD-50)
    "profile_section": "AI models",
    "make_public": "Make public",
    "archive": "Archive",
    "download_data": "Download its data",
}

#: Words this module drafts where the prototype shows only a sample in one
#: grammatical number or names a person's pronoun. Listed in the PR under
#: "Words to sign"; each follows the signed sample's shape exactly.
DRAFTED: frozenset[str] = frozenset({
    "one example waits", "one model", "one teacher", "invite_with_them",
})

#: N528 item 8 and N566 item 5: a starting point of 500 counted answers and
#: a final exam of 100 cases set aside by two experts. A model may carry its
#: own targets (a host's simple recognizer learns at about 200, N582 item 5).
DEFAULT_TARGETS = {"counted_answers": 500, "exam_cases": 100}

#: The answers a voice model's Judge offers (the coach panel's, N563 item 2).
JUDGE_ANSWERS = ("Yes", "In-between", "No")


# ── Small helpers ───────────────────────────────────────────────────────────
def _plural(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def _join_names(names: list[str]) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + " and " + names[-1]


def _norm(text: Any) -> str:
    return re.sub(r"[\s\W_]+", " ", str(text or "")).strip().lower()


def _ids(values: Iterable[Any] | None) -> set[str]:
    return {str(v) for v in (values or []) if v is not None}


# ── How far a model is (MOD-05, MOD-06; N528 item 1, N566 item 6) ───────────
def percent_of_the_way(model: dict) -> int:
    """How far a model is toward its first training, 0 to 100. The slowest
    jar decides (the owner's page: "The slowest jar decides"). A model that
    passed its final exam is at 100."""
    if model.get("status") == "ready":
        return 100
    jars = model.get("jars") or {}
    targets = {**DEFAULT_TARGETS, **(model.get("targets") or {})}
    shares = []
    for jar, target in targets.items():
        if target and target > 0:
            shares.append(min(1.0, max(0, int(jars.get(jar) or 0)) / target))
    if not shares:
        return 0
    return int(math.floor(min(shares) * 100))


def teachers_words(n: int) -> str:
    return _plural(n, "teacher", "teachers")


def progress_line(model: dict) -> str:
    """The list's line under a model: "62% of the way to its first training
    · 6 teachers", or "Passed its final exam · 9 teachers" once ready."""
    teachers = teachers_words(int(model.get("teachers") or 0))
    if model.get("status") == "ready":
        return f"Passed its final exam · {teachers}"
    return f"{percent_of_the_way(model)}% of the way to its first training · {teachers}"


_NUMBER_WORDS = ("No one", "One person", "Two people", "Three people", "Four people",
                 "Five people", "Six people", "Seven people", "Eight people",
                 "Nine people", "Ten people")


def page_summary(model: dict) -> str:
    """A public model's page, in totals only: "Speaking confidence is 62% of
    the way to its first training. Six people teach it." (MOD-06)."""
    n = int(model.get("teachers") or 0)
    who = _NUMBER_WORDS[n] if n < len(_NUMBER_WORDS) else f"{n} people"
    verb = "teaches" if n == 1 else "teach"
    if model.get("status") == "ready":
        return f"{model['name']} passed its final exam. {who} {verb} it."
    return (f"{model['name']} is {percent_of_the_way(model)}% of the way to its "
            f"first training. {who} {verb} it.")


# ── Who sees a model (MOD-03, MOD-06; N526 items 2 and 3) ────────────────────
def viewer_role(model: dict, viewer_id: Any) -> str | None:
    """'owner', 'contributor', 'public', or None when the viewer may not see
    the model at all (a private model is in no directory, N526 item 2; an
    archived one is in no list, N528 item 5, but its owner still reaches it)."""
    vid = str(viewer_id) if viewer_id is not None else None
    owners = _ids(model.get("owner_ids")) | _ids([model.get("owner_id")])
    if vid and vid in owners:
        return "owner"
    if model.get("status") in ("archived", "draft"):
        return None
    if vid and vid in _ids(model.get("contributor_ids")):
        return "contributor"
    if model.get("visibility") == "public":
        return "public"
    return None


#: What each role's page holds. Totals for the public; the jars, the stage
#: and their own part for a contributor; everything for the owner. Nothing
#: in any of them reads on a person (no reliability, no speaker).
_PUBLIC_FIELDS = ("id", "name", "owner_name", "visibility", "status", "description", "field")


def model_page(model: dict, viewer_id: Any, *, own_part: dict | None = None,
               owner_extra: dict | None = None) -> dict | None:
    """A model's page for this viewer, or None (a 404) when they may not see it."""
    role = viewer_role(model, viewer_id)
    if role is None:
        return None
    page: dict[str, Any] = {k: model.get(k) for k in _PUBLIC_FIELDS}
    page["role"] = role
    page["summary"] = page_summary(model)
    page["percent"] = percent_of_the_way(model)
    page["teachers"] = int(model.get("teachers") or 0)
    page["actions"] = [WORDS["teach_it"], WORDS["try_it"]]
    if role in ("owner", "contributor"):
        page["jars"] = dict(model.get("jars") or {})
        page["targets"] = {**DEFAULT_TARGETS, **(model.get("targets") or {})}
        page["recipe"] = dict(model.get("recipe") or {})
        page["own_part"] = dict(own_part or {})
    if role == "owner":
        page["owner"] = dict(owner_extra or {})
    return page


# ── The list (MOD-05, MOD-12, MOD-13; N566 items 2 and 11) ──────────────────
FILTERS = ("for_you", "ready", "learning")


def _matches(model: dict, query: str) -> bool:
    words = _norm(query).split()
    hay = _norm(" ".join(str(model.get(k) or "") for k in ("name", "field", "description", "owner_name")))
    return all(w in hay for w in words)


def _for_you(model: dict, viewer_id: str | None, viewer_fields: set[str]) -> bool:
    if viewer_role(model, viewer_id) in ("owner", "contributor"):
        return True
    field = set(_norm(model.get("field")).split())
    return bool(field & viewer_fields)


def _draft_row(model: dict) -> dict:
    return {"id": model.get("id"), "name": model.get("name"), "badge": WORDS["your_draft"],
            "line": draft_line(model.get("draft_step")), "actions": [WORDS["continue"]]}


def _shown_in_list(model: dict, vid: str | None, query: str, filter_: str | None,
                   fields: set[str]) -> bool:
    """Whether a listed (not draft) model shows for this viewer, search and filter."""
    if viewer_role(model, vid) is None or (query and not _matches(model, query)):
        return False
    if filter_ in ("ready", "learning"):
        return model.get("status") == filter_
    return filter_ != "for_you" or _for_you(model, vid, fields)


def _listed_row(model: dict) -> dict:
    ready = model.get("status") == "ready"
    return {
        "id": model.get("id"), "name": model.get("name"),
        "badge": WORDS["filter_ready"] if ready else WORDS[model.get("visibility") or "public"],
        "started_by": f"Started by {model.get('owner_name') or ''}".rstrip(),
        "line": progress_line(model),
        "actions": [WORDS["use_it"], WORDS["teach_it"]] if ready else [WORDS["teach_it"], WORDS["open"]],
    }


def _maturity(model: dict) -> tuple:
    """Most mature first: ready to use, then how far along, then teachers."""
    return (0 if model.get("status") == "ready" else 1, -percent_of_the_way(model),
            -int(model.get("teachers") or 0), str(model.get("name") or ""))


def model_list(models: list[dict], viewer_id: Any, *, query: str = "",
               filter_: str | None = None, viewer_fields: Iterable[str] = ()) -> dict:
    """The list of models for this viewer: their own drafts on top, then the
    most mature first (ready to use, then by how far along), with search and
    the three filters. An empty result carries the empty state."""
    vid = str(viewer_id) if viewer_id is not None else None
    fields = {w for f in viewer_fields for w in _norm(f).split()}
    drafts = [_draft_row(m) for m in models
              if m.get("status") == "draft" and viewer_role(m, vid) == "owner"
              and (not query or _matches(m, query))]
    listed = sorted((m for m in models if m.get("status") != "draft"
                     and _shown_in_list(m, vid, query, filter_, fields)), key=_maturity)
    rows = [_listed_row(m) for m in listed]
    result: dict[str, Any] = {
        "intro": WORDS["list_intro"],
        "filters": [WORDS["filter_for_you"], WORDS["filter_ready"], WORDS["filter_learning"]],
        "what_do_i_get": WORDS["what_do_i_get"],
        "drafts": drafts,
        "models": rows,
        "start": WORDS["start_your_own"],
    }
    if not rows and not drafts and (query or filter_):
        result["empty"] = {
            "title": WORDS["search_empty_title"], "line": WORDS["search_empty_line"],
            "actions": [WORDS["search_empty_start"], WORDS["search_empty_clear"]],
        }
    return result


#: Where an owner stopped in the setup, as the list says it (N566 item 2).
#: Only "the scale" is signed (the prototype's sample); the others follow it.
_DRAFT_STEPS = {
    "problem": "the problem", "today": "how you solve it today", "teach": "how you will teach it",
    "kind": "the kind of model", "scale": "the scale", "question": "the question",
    "exam": "the final exam", "share": "who can see it",
    "ai": "the AI for each part", "rules": "the starting rules", "data": "your data",
    "columns": "your data", "check": "your data", "journey": "the teachers’ steps",
    "first10": "your first 10", "public": "who can see it", "invite": "who teaches it",
}


def draft_line(step: str | None) -> str:
    where = _DRAFT_STEPS.get(str(step or ""), "the scale")
    return f"You stopped at {where}. Nothing is lost."


def what_do_i_get() -> dict:
    """The three short cards (MOD-12)."""
    return {
        "title": WORDS["what_do_i_get"],
        "cards": [
            {"title": WORDS["get_teach"], "line": WORDS["get_teach_line"]},
            {"title": WORDS["get_start"], "line": WORDS["get_start_line"]},
            {"title": WORDS["get_use"], "line": WORDS["get_use_line"]},
        ],
        "back": WORDS["back_to_list"],
    }


def door() -> dict:
    """The disclaimer at the door before anyone teaches (MOD-07)."""
    return {
        "title": WORDS["door_title"],
        "lines": [WORDS["door_why"], WORDS["door_field"], WORDS["door_recordings"]],
        "actions": [WORDS["door_yes"], WORDS["door_no"]],
    }


def chat_rows(queue_waiting: int, queue_models: int, *, teaches_any: bool) -> list[dict]:
    """The two rows under the people in the list of chats (MOD-04, MOD-14):
    "Your queue" for whoever teaches a model, then "AI models" for everyone.
    N580 item 2 moves the queue inside Will's chat once Will's split is
    built (with the MVP, N580 item 6); until then it is this row."""
    rows = []
    if teaches_any:
        rows.append({"name": WORDS["row_queue"], "line": queue_row_line(queue_waiting, queue_models)})
    rows.append({"name": WORDS["row_models"], "line": WORDS["row_models_line"]})
    return rows


# ── The training yes decides whether a Take can teach (MOD-02) ──────────────
def takes_offered_to_teachers(takes: list[dict], consent: dict | None) -> list[dict]:
    """The speaker's Takes a voice model may offer its teachers: only while
    their training yes ("Help improve WillpowerLab") is on, and only Takes
    recorded after they turned it on (N563 item 4, N575). Off, none are; a
    withdrawal ("Turn off training?") takes every one out again.

    ``consent`` is ``{"active": bool, "granted_at": iso str | None}``, as the
    training-consent status reads it."""
    if not consent or not consent.get("active"):
        return []
    since = str(consent.get("granted_at") or "")
    return [t for t in takes if since and str(t.get("recorded_at") or "") >= since]


def take_consent(database: Any, owner_id: Any) -> dict:
    """The speaker's training yes as ``takes_offered_to_teachers`` reads it,
    from the consent status that already exists (migration 0373)."""
    try:
        status = database.get_mlc2_training_consent_status(owner_id) or {}
    except Exception:
        logger.warning("model launchpad: the training yes could not be read; offering nothing",
                       exc_info=True)
        return {"active": False, "granted_at": None}
    return {"active": status.get("active") is True, "granted_at": status.get("granted_at")}


# ── Teaching screens follow the recipe card (MOD-08, MOD-09, MOD-19, MOD-20) ─
#: What a teacher's screen may receive about an example: the case itself and
#: where it is from, nothing else. An allowlist, so the machine's read (its
#: label, score, draft, "what happened", how sure it is), a known clip's
#: hidden answer, whether it is in the exam, and the speaker it came from
#: never reach a teacher before, or instead of, their answer (Never 2, N518
#: item 4, N520 item 8).
TEACHER_FIELDS = frozenset({"id", "model_id", "kind", "content", "private", "source"})


def example_for_teacher(example: dict) -> dict:
    """An example as a teacher's screen receives it: only ``TEACHER_FIELDS``."""
    return {k: v for k, v in example.items() if k in TEACHER_FIELDS}


def teaching_screen(model: dict, example: dict, step: int = 0) -> dict:
    """One teaching step, as the model's recipe card asks it (N563 item 2):
    a voice model rates a clip on the Judge; a text model shows the written
    case; "pick" shows its list (N570 item 2); "words" asks for a spoken
    answer (N520 item 7)."""
    recipe = model.get("recipe") or {}
    steps = list(recipe.get("steps") or ["rate"])
    kind = steps[min(step, len(steps) - 1)]
    screen: dict[str, Any] = {
        "model": model.get("name"), "step": kind, "example": example_for_teacher(example),
        "source_note": private_example_note(model) if example.get("private") else None,
    }
    if kind == "rate":
        scale = list(recipe.get("scale") or JUDGE_ANSWERS)
        if recipe.get("input", "voice") == "voice" and tuple(scale) == JUDGE_ANSWERS:
            screen["title"] = WORDS["judge_title"]
        screen["question"] = recipe.get("question")
        screen["answers"] = scale + [WORDS["audio_unclear"], WORDS["skip"]] \
            if recipe.get("input", "voice") == "voice" else scale + [WORDS["skip"]]
    elif kind == "pick":
        screen["question"] = recipe.get("pick_question") or recipe.get("question")
        screen["answers"] = list(recipe.get("options") or [])
    else:  # words
        screen["question"] = WORDS["words_step"]
        screen["answers"] = [WORDS["record_answer"], WORDS["skip"]]
    return screen


def private_example_note(model: dict) -> str:
    """MOD-18: "Your company’s own example: it teaches only RASP sales replies.\""""
    return f"Your company’s own example: it teaches only {model.get('name')}."


# ── One answer, which models it counts for (MOD-16, MOD-17, MOD-18) ─────────
def _question_key(model: dict) -> tuple[str, tuple[str, ...]]:
    recipe = model.get("recipe") or {}
    return _norm(recipe.get("question")), tuple(_norm(s) for s in (recipe.get("scale") or []))


def counts_for(example: dict, answered: dict, wanting: list[dict]) -> dict:
    """Which models one answer counts for, and which questions follow on the
    same example (N563 item 3, N566 item 7).

    A private example counts only for its own model, never a public one. A
    public example counts for every model that wants it AND asks the same
    question on the same scale; a model that asks something else follows
    right after, on the same example, without loading it again."""
    if example.get("private"):
        return {"counts_for": [answered], "note": private_example_note(answered), "follow": []}
    key = _question_key(answered)
    same: list[dict] = [answered]
    follow: list[dict] = []
    for model in wanting:
        if model.get("id") == answered.get("id") or model.get("visibility") != "public":
            continue
        (same if _question_key(model) == key and key[0] else follow).append(model)
    note = None
    if len(same) > 1:
        note = f"Counts for {_join_names([m['name'] for m in same])}: both ask this question" \
            if len(same) == 2 else \
            f"Counts for {_join_names([m['name'] for m in same])}: they all ask this question"
    return {
        "counts_for": same, "note": note,
        "follow": [{"model": m, "line": follow_line(m, example)} for m in follow],
    }


def follow_line(model: dict, example: dict) -> str:
    """MOD-17: "Pitch Coach asks something else about the same clip: how
    rushed does it sound?\""""
    what = "clip" if (model.get("recipe") or {}).get("input", "voice") == "voice" else "example"
    question = str((model.get("recipe") or {}).get("question") or "").strip()
    question = question[:1].lower() + question[1:] if question else question
    return f"{model.get('name')} asks something else about the same {what}: {question}"


# ── Examples teachers add (MOD-21; N563 item 4, N566 item 6) ────────────────
def added_example_counts(example: dict, answers: list[dict]) -> bool:
    """An example a teacher added counts once ANOTHER teacher agrees with
    the adder's answer. Nobody teaches a model alone (N570 item 4)."""
    adder = str(example.get("added_by") or "")
    mine = [a for a in answers if str(a.get("teacher_id")) == adder and a.get("answer") is not None]
    if not mine:
        return False
    theirs = mine[-1]["answer"]
    return any(str(a.get("teacher_id")) != adder and a.get("answer") == theirs for a in answers)


def training_mix(examples: list[dict]) -> list[dict]:
    """What a model learns from, with examples teachers added never more than
    1 in 5 of it (N566 item 6). The newest added examples beyond the cap wait."""
    added = [e for e in examples if e.get("source") == "teacher"]
    others = [e for e in examples if e.get("source") != "teacher"]
    allowed = len(others) // 4          # added / (others + added) <= 1/5
    added.sort(key=lambda e: str(e.get("added_at") or ""))
    return others + added[:allowed]


# ── The quiet trust check (MOD-10; N520 items 8 and 12) ─────────────────────
MIN_ANSWERS = 20
MIN_KNOWN = 5
FLOOR = 0.20
ADMIT_SHARE = 0.70
REMOVE_SHARE = 0.50
_Z80 = 1.2815515655446004   # the two-sided 80% range


def _wilson(k: int, n: int, z: float = _Z80) -> tuple[float, float]:
    if n <= 0:
        return 0.0, 1.0
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (c - r) / d), min(1.0, (c + r) / d)


def reliability(answers: list[dict]) -> dict:
    """A rater's chance-corrected agreement with the consensus that leaves
    their own answer out, with its 80% range.

    Each answer is ``{"answer": x, "consensus": y, "known": bool}``: the
    consensus is of the OTHER raters (or a known clip's answer). Chance is
    what two raters with these answer shares would agree on by luck."""
    pairs = [(a.get("answer"), a.get("consensus")) for a in answers
             if a.get("answer") is not None and a.get("consensus") is not None]
    n = len(pairs)
    if not n:
        return {"n": 0, "kappa": 0.0, "low": -1.0, "high": 1.0}
    agree = sum(1 for x, y in pairs if x == y)
    mine: dict[Any, int] = defaultdict(int)
    theirs: dict[Any, int] = defaultdict(int)
    for x, y in pairs:
        mine[x] += 1
        theirs[y] += 1
    chance = sum(mine[c] * theirs[c] for c in set(mine) | set(theirs)) / (n * n)
    lo, hi = _wilson(agree, n)

    def kappa(p: float) -> float:
        return (p - chance) / (1 - chance) if chance < 1 else 0.0
    return {"n": n, "kappa": kappa(agree / n), "low": kappa(lo), "high": kappa(hi)}


def trust_status(answers: list[dict], trusted_kappas: list[float], *, was_trusted: bool = False) -> str:
    """'learning' (not decided), 'counts', or 'stopped' (N520 item 12):
    admitted when the cautious edge reaches 70% of the median of the model's
    trusted raters, never below 0.20, after 20 answers with 5 on known
    clips; removed only when the hopeful edge falls below 50% of it."""
    rel = reliability(answers)
    ref = median(trusted_kappas) if trusted_kappas else 0.0
    if was_trusted:
        return "stopped" if rel["high"] < REMOVE_SHARE * ref else "counts"
    known = sum(1 for a in answers if a.get("known"))
    if len(answers) < MIN_ANSWERS or known < MIN_KNOWN:
        return "learning"
    return "counts" if rel["low"] >= max(FLOOR, ADMIT_SHARE * ref) else "learning"


def known_clip_due(answer_index: int) -> bool:
    """Whether the answer at this index (0-based) is a hidden known clip: 1
    in 4 of a newcomer's first 20, then 1 in 10 for good (N520 item 12)."""
    if answer_index < MIN_ANSWERS:
        return answer_index % 4 == 3
    return (answer_index - MIN_ANSWERS) % 10 == 9


def trust_screen(status: str, *, just_changed: bool) -> dict | None:
    """What the teacher is told. Nothing while the check runs (no screen
    says they are on trial and no score is shown); once their answers count,
    once: "Your answers now count." A stop is never announced."""
    if status == "counts" and just_changed:
        return {"lines": [WORDS["trust_in"], WORDS["trust_in_tokens"]],
                "actions": [WORDS["keep_teaching"], WORDS["back_to_list"]]}
    return None


# ── The one queue (MOD-14, MOD-15, MOD-23; N563 item 1) ─────────────────────
def queue_row_line(waiting: int, models: int) -> str:
    """The queue row's line in the list of chats: "12 examples wait · 3
    models"."""
    ex = "1 example waits" if waiting == 1 else f"{waiting} examples wait"
    return f"{ex} · {_plural(models, 'model', 'models')}"


def _helpfulness(example: dict, lacking: set[str]) -> tuple[int, float]:
    """Lower is more helpful: the kinds a model lacks first, then the
    examples it is least sure about (sureness near 0.5 for a guess; unknown
    is least sure of all)."""
    s = example.get("sureness")
    unsure = 0.0 if s is None else abs(float(s) - 0.5)
    return (0 if example.get("kind") in lacking else 1, unsure)


def build_queue(models: list[dict], examples: list[dict], teacher_id: Any, *,
                paused: Iterable[Any] = (), only: Any = None,
                lacking: dict[str, set[str]] | None = None,
                company_line: dict[str, str] | None = None) -> dict:
    """The one queue across every model this person teaches: the examples
    that help most come first, taken in turn from each model so none is
    starved; a paused model sends nothing; "only" opens one model alone."""
    tid = str(teacher_id)
    paused_ids = _ids(paused)
    by_model: dict[str, list[dict]] = defaultdict(list)
    for e in examples:
        by_model[str(e.get("model_id"))].append(e)
    lacking = lacking or {}
    rows, lanes = [], []
    for m in models:
        mid = str(m.get("id"))
        waiting = sorted(by_model.get(mid, []), key=lambda e: _helpfulness(e, lacking.get(mid, set())))
        is_paused = mid in paused_ids
        if tid in (_ids(m.get("owner_ids")) | _ids([m.get("owner_id")])):
            who = WORDS["you_started_it"]
        elif m.get("visibility") == "private":
            who = (company_line or {}).get(mid) or WORDS["your_company"]
        else:
            who = WORDS["you_teach_it"]
        rows.append({"id": m.get("id"), "name": m.get("name"), "line": who,
                     "badge": WORDS[m.get("visibility") or "public"],
                     "waiting": len(waiting), "paused": is_paused, "action": WORDS["pause"]})
        if not is_paused and (only is None or str(only) == mid):
            lanes.append([example_for_teacher(e) for e in waiting])
    order: list[dict] = []
    while any(lanes):                    # round robin: no model starved
        for lane in lanes:
            if lane:
                order.append(lane.pop(0))
    total = len(order)
    if not total:
        return {"empty": {"title": WORDS["queue_empty_title"], "line": WORDS["queue_empty_line"],
                          "action": WORDS["queue_empty_back"]}, "models": rows, "examples": []}
    head = "1 example is waiting." if total == 1 else f"{total} examples are waiting."
    return {
        "header": f"{head} {WORDS['queue_header_tail']}",
        "models": rows, "hint": WORDS["queue_hint"],
        "actions": [WORDS["queue_start"], WORDS["queue_add"]],
        "examples": order,
    }


def add_example_sheet() -> dict:
    """MOD-21's sheet."""
    return {
        "title": WORDS["add_title"], "intro": WORDS["add_intro"],
        "choices": [{"title": WORDS["add_record"], "line": WORDS["add_record_line"]},
                    {"title": WORDS["add_upload"], "line": WORDS["add_upload_line"]}],
        "note": WORDS["add_counts_once"],
    }


# ── Release (MOD-22; N566 item 5, N563 item 5) ──────────────────────────────
#: A difference is "clearly not luck" when the exact two-sided sign test on
#: the cases one version won puts the chance of a gap this large below 5%.
RELEASE_ALPHA = 0.05


def sign_test(better: int, worse: int) -> float:
    """The exact two-sided sign test: the chance of a split at least this
    uneven if both versions were equally good (ties left out)."""
    n = better + worse
    if n == 0:
        return 1.0
    k = min(better, worse)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return min(1.0, 2 * tail)


def release_screen(model: dict, version: int, better: int, worse: int, same: int) -> dict:
    """The owner's screen when a new version finishes its final exam. The
    Release button appears only when the new version is clearly better;
    releasing is the founder's choice; businesses keep their version."""
    old = version - 1
    clear = better > worse and sign_test(better, worse) < RELEASE_ALPHA
    screen: dict[str, Any] = {
        "title": f"Version {version} is ready",
        "line": f"Version {version} of {model.get('name')} passed its final exam.",
        "exam": {"intro": WORDS["release_exam_intro"], "better": better, "worse": worse, "same": same,
                 "labels": [f"version {version} better", f"version {old} better", "the same"]},
        "release": clear,
    }
    if clear:
        screen["verdict"] = (f"Version {version} is clearly better: a gap of {better} against "
                             f"{worse} is very unlikely to be luck.")
        screen["choice"] = WORDS["release_choice"].format(old=old)
        screen["actions"] = [f"Release version {version}", WORDS["release_not_yet"]]
    else:
        screen["verdict"] = WORDS["release_not_yet_clear"]
        screen["actions"] = []
    return screen


# ── The invite that stays (MOD-49; N528 item 3) ─────────────────────────────
def invite_card(inviter_name: str, model_name: str, *, said_not_now: bool) -> dict:
    """An invite to teach, as it stays in the chat. After "Not now" it says
    so and can be opened at any time. The prototype's "with her" names a
    pronoun the app does not know, so it reads "with them" (drafted)."""
    lines = [f"{inviter_name} invited you to teach {model_name} with them."]
    if said_not_now:
        lines.append(WORDS["invite_said_not_now"])
    return {"lines": lines, "action": WORDS["open"]}


# ── The profile's AI models (MOD-50; N528 items 1 and 5) ────────────────────
def profile_models(models: list[dict], person_id: Any, counted_this_month: dict[str, int]) -> dict | None:
    """The section "AI models" on a person's profile: the models they
    started (with Make public, Archive, Download its data) and the ones
    they teach (with their answers counted this month). None when empty."""
    pid = str(person_id)
    rows = []
    for m in models:
        owners = _ids(m.get("owner_ids")) | _ids([m.get("owner_id")])
        badge = WORDS[m.get("visibility") or "public"]
        if pid in owners and m.get("status") != "draft":
            actions = ([WORDS["make_public"]] if m.get("visibility") == "private" else []) + \
                [WORDS["archive"], WORDS["download_data"]]
            pct = percent_of_the_way(m)
            way = "passed its final exam" if m.get("status") == "ready" else f"{pct}% of the way"
            rows.append({"name": m.get("name"), "badge": badge,
                         "line": f"{WORDS['you_started_it']} · {way} · {teachers_words(int(m.get('teachers') or 0))}",
                         "actions": actions})
        elif pid in _ids(m.get("contributor_ids")):
            n = int(counted_this_month.get(str(m.get("id")), 0))
            counted = "1 answer counted" if n == 1 else f"{n} answers counted"
            rows.append({"name": m.get("name"), "badge": badge,
                         "line": f"{WORDS['you_teach_it']} · {counted} this month", "actions": []})
    if not rows:
        return None
    return {"title": WORDS["profile_section"], "models": rows}
