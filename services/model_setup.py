"""Starting a model: the setup's rules and words (N528 item 4, N566 items 2
to 6, N570, N571, N582, N585; the locked prototype
``docs/design/model-launchpad-2026-11-09/``, version 8, and its test drive
for N570's and N571's drafted steps).

Like ``services/model_launchpad.py``, this module has no storage of its own:
every function takes plain dicts and returns plain dicts.
``services/model_setup_store.py`` reads and writes ``ai_models.setup`` (0517)
and ``ai_models.recipe`` (0516) and hands them here.

THE DRAFT (``ai_models.setup``, what the owner said and chose):

  {
    "problem": str, "today": str, "teach": str,      # Describe (N528 item 4)
    "from_first_take": bool,                          # N571: filled, not asked
    "name": str, "unit": str,                         # "a pitch clip of about 30 seconds"
    "input": "voice" | "text" | "image",
    "parts": {"score": bool, "pick": bool, "answer": bool},
    "part_titles": {"score": str, "pick": str, "answer": str},
    "part_lines": {"score": str, "pick": str, "answer": str},
    "scale": [{"t": str, "d": str}, ...],             # a word for every point
    "question": str, "pick_question": str, "options": [str, ...],   # N570
    "rules": [{"text", "src", "measured_on", "on", "measure", "op", "cut", "unit"}],
    "strictness": "clear" | "fairly_clear",           # N585 item 4
    "rules_decided": bool,
    "data": {"name", "columns", "rows", "map", "check", "consent", "decided"},
    "exam": {"experts": [owner_id, expert_id], "asked_at"},
    "journey": [str, ...], "journey_parts": [...],
    "first_ten": [{"example_id", "answer"}],
    "visibility": "private" | "public",
    "invited": [user_id, ...], "invited_team": bool,
    "done": [step, ...],                              # steps the owner finished
  }

The steps, in order, each one action a screen (N528 item 4): Describe
(problem, today, teach), Shape (kind, scale, question, ai, rules, data,
columns, check, exam, journey, first10), Share (share, invite). "public" is
the disclaimer that slides over "share"; "ready" is the end.

Never 1: none of this reaches a speaker. Never 2: the owner's first 10 are
answered without the model's guess, as every teacher's are (N585 item 5).
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
from collections import Counter
from typing import Any, Iterable, Optional

# ── The steps (N566 item 2; the prototype's order) ──────────────────────────
ORDER = ("problem", "today", "teach", "kind", "scale", "question", "ai", "rules", "data",
         "columns", "check", "exam", "journey", "first10", "share", "invite")
CHAPTERS = ("Describe", "Shape", "Share")
_CHAPTER = {"problem": "Describe", "today": "Describe", "teach": "Describe",
            "share": "Share", "public": "Share", "invite": "Share", "ready": "Share"}
_DESCRIBE = ("problem", "today", "teach")
_SHAPE = ("kind", "scale", "question", "ai", "rules", "data", "columns", "check", "exam",
          "journey", "first10")
_SHARE = ("share", "invite", "ready")
OPTIONAL = frozenset({"rules", "data"})
STEPS = frozenset(ORDER) | {"public", "ready"}

#: The owner's first answers (N570 item 3, N582 item 5).
FIRST_TEN = 10
#: The re-rate an upload waits for before it counts (N566 item 4).
RERATE = 60
#: A study's rule is checked against this many first ratings (MOD-30).
RULE_CHECK = 50
#: The final exam (N566 item 5).
EXAM_CASES = 100
#: An uploaded file's limits: enough for a real sheet, small enough for one request.
MAX_UPLOAD_BYTES = 2_000_000
MAX_UPLOAD_ROWS = 5_000
MAX_STUDY_BYTES = 8_000_000
#: A scale has a word for every point; three to seven points (N520 item 4,
#: N582 item 2's three answers at the least).
MIN_POINTS, MAX_POINTS = 3, 7
MIN_OPTIONS, MAX_OPTIONS = 2, 12

# ── Signed words (N566 item 1: the locked prototype's words) ────────────────
WORDS: dict[str, str] = {
    "describe": "Describe", "shape": "Shape", "share": "Share", "optional": "Optional",
    "next": "Next",
    "q_problem": "What problem should your model solve?",
    "q_today": "How do you solve it today?",
    "q_teach": "How will you teach your model?",
    # the sheet over the third answer (MOD-26)
    "similar_title": "A model like yours already exists",
    "similar_line": "If you teach it, it learns faster, and you share what it earns.",
    "teach_this_one": "Teach this one",
    "set_up_mine": "Set up mine anyway",
    # what it will do (MOD-27)
    "kinds_three": "From your answers, your model will do three things. Untick what it should not do.",
    "kind_score": "It gives a score on a scale",
    "kind_pick": "It picks from a list",
    "kind_answer": "It learns to answer like you",
    "thats_right": "That’s right",
    # the scale (MOD-28)
    "scale_line": "One example is {unit}. Your teachers will rate each clip on this scale.",
    "scale_help": "Clear words for each point help your teachers agree. When they agree, the model learns faster.",
    "use_this_scale": "Use this scale",
    "start_now": "Start with this, finish the rest later",
    # the AI for each part (MOD-29)
    "ai_intro": "Each part of your model needs a different kind of AI. We chose one for each.",
    "ai_voice_scorer": ("WillpowerLab’s voice scorer: it learns from how the voice sounds, "
                        "not only from the words"),
    "ai_pick": "GPT-4o mini, choosing only from your list",
    "ai_answer": "GPT-4o mini",
    "ai_others": "Other AIs to answer like you:",
    "soon": "Soon",
    # starting rules (MOD-30)
    "rules_intro": ("Do you have research your model should start from? It will work from day "
                    "one on the rules you keep."),
    "rules_check": ("A study’s numbers may not fit your speakers. We check each rule against your "
                    "teachers’ first 50 ratings. If they disagree with a rule, we stop using it and "
                    "tell you why."),
    "use_these_rules": "Use these rules", "skip": "Skip",
    # existing data (MOD-31)
    "data_intro": ("Do you already have examples of this work? Upload them, and your model starts "
                   "with more than rules."),
    "data_kinds": ("A spreadsheet (CSV or Excel), a JSON file, or a folder of recordings with a "
                   "spreadsheet that describes them."),
    "use_this_data": "Use this data", "no_data": "I don’t have any",
    "columns_intro": "Tell us what each column holds. We guessed; change any that are wrong.",
    "col_example": "→ The example: {unit}",
    "col_score": "→ The score on your scale, 1 to {n}",
    "col_pick": "→ The pick from your list",
    "col_answer": "→ Your answer",
    "col_out": "→ Left out: it names a person",
    "checked": "We checked your data.",
    "rows_usable": "Rows we can use", "rows_repeats": "Repeats removed",
    "rows_near": "Near repeats removed", "rows_no_score": "Rows with no score, skipped",
    "rows_mislabelled": "Rows that look mislabelled", "rows_names": "Names and places removed",
    "checked_first": "{n} · checked first",
    "spread": ("Most of your examples sit at {a} or {b}. Your model will learn little about "
               "{word} ({least}) until your teachers add some."),
    "mislabelled_line": ("A row looks mislabelled when its score is far from the scores of clips "
                         "that sound alike. Your teachers hear those {n} first."),
    "rerate": ("Before your data counts, your teachers re-rate 60 of its examples. If they agree "
               "with it often enough, all of it counts. If not, we show you which part to check. "
               "None of it goes into the final exam, which stays new."),
    "data_consent": ("I have the right to use this data, and the people in it agreed to its use "
                     "for training."),
    "upload_it": "Upload it", "fix_file": "Fix the file first",
    # the final exam (MOD-32)
    "exam_intro": ("Before anyone teaches it, two experts set aside a final exam: 100 clips your "
                   "model never learns from."),
    "exam_sold": "It can be sold only when it does clearly better on this exam than it does today.",
    "you": "You", "owner": "Owner", "ask": "Ask {name}",
    # the teachers' journey (MOD-33)
    "journey_intro": "Here is what each teacher will do. Make it shorter or longer.",
    "shorter": "Shorter", "longer": "Longer", "looks_good": "Looks good",
    # who can see it (MOD-34)
    "who_sees": "Who can see your model?",
    "private": "Private", "private_line": "Only you and the people you invite",
    "public": "Public", "public_line": "Anyone can see it and teach it",
    "public_caption": "Before you make it public",
    "public_1": "Anyone will be able to see your model and teach it.",
    "public_2": ("Once it passes its final exam, businesses can pay to use it. You and its "
                 "teachers share what it earns."),
    "public_3": ("Before anything reaches the company whose AI it uses, we remove names and "
                 "places. Recordings never leave WillpowerLab."),
    "public_4": "You can make it private again at any time. What it has learned stays.",
    "make_public": "Make it public", "keep_private": "Keep it private",
    # inviting teachers (MOD-35)
    "who_teaches": "Who should teach it with you?",
    "everyone_in": "Everyone in {team}",
    "team_line": "{n} people · each one chooses whether to join",
    "invite_them": "Invite them", "copy_link": "Copy an invite link",
    # ready to learn (MOD-36)
    "ready": "{name} is ready to learn. Today it answers from your starting rules and examples.",
    "to_finish": "To finish setting it up",
    "sell_title": "Sell it through an API",
    "sell_line": "This opens once its first training beats today’s version on the final exam.",
    "sell_needs": "It needs about {n} ratings from trusted teachers first.",
    "try_it": "Try it", "back_to_list": "Back to the list",
    "check_scale": "The scale", "check_kind": "What it will do",
    "check_rules": "Starting rules · optional", "check_data": "Your existing data · optional",
    "check_exam": "The final exam", "check_invite": "Invite teachers",
    # the owner's page (MOD-37)
    "needs_you": "Needs you now",
    "disagree": ("Your teachers disagree most between {a} ({ta}) and {b} ({tb}). Clearer words "
                 "for those two points would help."),
    "make_clearer": "Make those two clearer",
    "way_range": ("{name} is {pct}% of the way to its first training: about {lo} to {hi} weeks "
                  "more. The slowest jar decides: {jar}."),
    "way": "{name} is {pct}% of the way to its first training.",
    "agree_title": "How often your teachers agree",
    "agree_value": "Within one point {w} times in 10 · exactly {e} in 10",
    "agree_ok": ("That is enough to learn from. If they agreed within one point fewer than 7 "
                 "times in 10, the scale would need clearer words first."),
    "ratings_row": "Ratings from trusted teachers", "exam_row": "Final exam",
    "exam_sealed": "100 of 100 · sealed", "upload_row": "Your uploaded examples",
    "sources_title": "Where its examples come from",
    "src_takes": "WillpowerLab speakers who said yes", "src_upload": "Your uploaded data",
    "src_business": "Questions it wasn’t sure about", "src_teacher": "Examples your teachers added",
    "src_teacher_value": "{n} · never more than 1 in 5 of what it learns from",
    "none_yet": "none yet",
    "runs_title": "What runs by itself",
    "runs_line": ("The trust check, the practice clips, how often teachers agree, the sealed exam "
                  "and the test against today’s version. Agreement is measured on 1 example in 10 "
                  "picked at random, so the hard ones served first don’t make it look worse than "
                  "it is. We tell you when something needs you."),
    "decide_title": "What you decide",
    "decide_line": ("The words of the scale, who you invite, the price, and when to release a "
                    "version that passed."),
    "fair_title": "A fair exam",
    "fair_line": ("No speaker in the exam is in its training, and the exam covers all {n} points "
                  "of the scale."),
    "rules_title": "Your starting rules, checked",
    "rule_kept": "“{rule}”: your teachers agree {k} times in 50. Kept.",
    "rule_stopped": "“{rule}”: your teachers agree {k} times in 50. We stopped using it.",
    "jar_voices": "different voices",
}

#: Words not yet signed: N570's and N571's steps (shown in the test drive for
#: the founder's OK), N585's strictness and signs, and the lines this build
#: needed that no prototype shows. Listed in the PR's "Words to sign"
#: (Never 4).
DRAFTED_WORDS: dict[str, str] = {
    "filled": "Filled from your first Take. Change any word.",
    "kinds_some": "From your answers, your model will do {n}. Tick what else it should do.",
    "its_name": "Its name",
    "give_every_point": "Give every point a word.",
    "scale_line_text": "One example is {unit}. Your teachers will rate each one on this scale.",
    "q_intro": ("Your teachers will be asked this about each clip. We wrote it from your answers; "
                "change any word."),
    "q_intro_text": ("Your teachers will be asked this about each example. We wrote it from your "
                     "answers; change any word."),
    "q_list": "They pick from this list. Write each option your teachers may choose.",
    "add_option": "Add an option",
    "two_options": "Write at least two options.",
    "q_help": ("Clear words help your teachers agree, and the same words let one answer count "
               "for every model that asks it."),
    "use_this_question": "Use this question",
    "ai_text_scorer": "WillpowerLab’s text scorer: it learns from your teachers’ ratings of the words",
    "ai_image_scorer": "WillpowerLab’s image scorer: it learns from your teachers’ ratings of the picture",
    "strict_title": "How sure should it be before it answers?",
    "strict_clear": "Only when it’s clear",
    "strict_fairly": "When it’s fairly clear",
    "col_unused": "→ Not used",
    "choose_expert": "Choose the second expert",
    "first_intro": "Now answer the first 10 yourself, the way your teachers will.",
    "first_done": "You answered your first 10.",
    "first_reads": ("Your model reads your answers from today, so it answers like you from the "
                    "start. Each one trains it once another teacher agrees with you."),
    "first_not_exam": "None of these 10 goes into the final exam.",
    "first_caption": "Your first 10 · {i} of 10",
    "first_none": "Your first 10 come once your model has its first examples.",
    "start": "Start", "later": "Do it later",
    "check_question": "The question your teachers answer",
    "check_first": "Your first 10 answers",
    "disagree_low": ("Your teachers agree within one point fewer than 7 times in 10. Give the "
                     "scale clearer words first."),
    "not_measured": "Not measured yet",
    "exam_not_yet": "Not set aside yet",
    "upload_waiting": "{n} · waiting for your teachers to re-rate 60",
    "upload_counts": "{n} · they count: teachers agreed with {k} in 10",
    "upload_not_yet": "{n} · they don’t count yet: teachers agreed with {k} in 10",
    "none": "none",
    "src_first": "Your first answers",
    "src_first_value": "{n} · read from day one · {k} train it",
    "rules_none": "You have no starting rules.",
    "rules_waiting": "We check your rules against your teachers’ first 50 ratings.",
    "jar_ratings": "ratings from trusted teachers",
    "jar_exam": "the final exam",
    "draft_name": "Your model",
    "listen_to": "Listen to {unit}",
    "read": "Read {unit}",
    "say_answer": "Say how you would answer, in your own words",
    "scale_fallback_1": "Not at all", "scale_fallback_2": "A little",
    "scale_fallback_3": "Somewhat", "scale_fallback_4": "Mostly", "scale_fallback_5": "Completely",
    "unit_voice": "a short clip", "unit_text": "a short written case", "unit_image": "a photo",
    "q_fallback_score": "How does it sound?", "q_fallback_score_text": "How well does it do it?",
    "q_fallback_pick": "Which one fits?", "q_fallback_answer": "What would you tell them?",
    "one_thing": "one thing", "two_things": "two things",
}

STRICTNESS = ("clear", "fairly_clear")


def word(key: str, **values: Any) -> str:
    """A signed word, else a drafted one, filled in."""
    text = WORDS[key] if key in WORDS else DRAFTED_WORDS[key]
    return text.format(**values) if values else text


# ── Small helpers ───────────────────────────────────────────────────────────
_STOP = frozenset("""a an the and or but if of to in on at for with by from as is are was were be
been it its this that these those i you we they he she them my your our their me us his her
do does did how what when where which who why will would can could should so than then not no
yes very more most much many some any each every all one two three just only also into about
over under up down out off again too own same other such own there here have has had get got
make makes made say says said tell tells told""".split())


def _clean(value: Any, most: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:most]


def _words_of(*texts: Any) -> set[str]:
    out: set[str] = set()
    for text in texts:
        for w in re.findall(r"[a-ząćęłńóśźż]{3,}", str(text or "").lower()):
            if w not in _STOP:
                out.add(w[:-1] if w.endswith("s") and len(w) > 4 else w)
    return out


def parts_on(draft: dict) -> list[str]:
    parts = draft.get("parts") or {}
    return [p for p in ("score", "pick", "answer") if parts.get(p)]


def _is_done(draft: dict, step: str) -> bool:
    return step in set(draft.get("done") or [])


# ── Which steps a draft walks (MOD-24; N566 item 2) ─────────────────────────
def walk(draft: dict) -> list[str]:
    """The steps this draft walks, in order: no scale without a score, no
    columns or check without uploaded data."""
    parts = draft.get("parts") or {}
    has_data = bool((draft.get("data") or {}).get("columns"))
    out = []
    for step in ORDER:
        if step == "scale" and parts and not parts.get("score"):
            continue
        if step in ("columns", "check") and not has_data:
            continue
        out.append(step)
    return out


def next_step(draft: dict, step: str) -> str:
    """The step after ``step``; "ready" after the last."""
    steps = walk(draft)
    if step == "public":
        step = "share"
    if step not in steps:
        return steps[0]
    i = steps.index(step)
    return steps[i + 1] if i + 1 < len(steps) else "ready"


def frame(draft: dict, step: str) -> dict:
    """The chapter, its caption ("Describe · 1 of 3", "Shape · 5 of 11
    Optional") and the thin bar that fills as you go (MOD-24)."""
    chapter = _CHAPTER.get(step, "Shape")
    if chapter == "Describe":
        of, at = 3, _DESCRIBE.index(step) + 1
    elif chapter == "Share":
        of, at = 3, _SHARE.index("share" if step == "public" else step) + 1
    else:
        of, at = len(_SHAPE), _SHAPE.index(step) + 1 if step in _SHAPE else 1
    steps = walk(draft)
    here = "share" if step == "public" else step
    pos = steps.index(here) + 1 if here in steps else len(steps) + 1
    return {
        "chapter": chapter,
        "chapters": [{"name": c, "on": c == chapter} for c in CHAPTERS],
        "caption": f"{chapter} · {at} of {of}",
        "optional": WORDS["optional"] if step in OPTIONAL else None,
        "bar": min(100, round(100 * pos / (len(steps) + 1))),
    }


# ── The three answers fill the rest (MOD-27, MOD-38, MOD-54; N570, N571) ────
def guess_input(draft: dict) -> str:
    """Voice, text or an image, from the three answers; the drafting model
    decides first, this is its fallback."""
    t = " ".join(str(draft.get(k) or "") for k in _DESCRIBE).lower()
    if re.search(r"photo|image|picture|scan|x-ray|skin|scalp", t):
        return "image"
    if re.search(r"voice|sound|speak|speech|pitch|talk|call|clip|record|accent|pronounc", t):
        return "voice"
    return "text"


def suggest_parts(draft: dict) -> dict:
    """What the model will do, proposed from the three answers (MOD-27): a
    score, a pick, an answer like the owner's. At least one."""
    t = " ".join(str(draft.get(k) or "") for k in _DESCRIBE).lower()
    parts = {
        "score": bool(re.search(r"rate|score|scale|how much|sounds|rushed|level|confiden|grade|judge|assess", t)),
        "pick": bool(re.search(r"pick|choose|exercise|list|which|recommend|select", t)),
        "answer": bool(re.search(r"\bsay\b|tell|answer|reply|explain|write|advice|feedback", t)),
    }
    if not any(parts.values()):
        parts["score"] = True
    return parts


def fallback_draft(draft: dict) -> dict:
    """The drafting model's work, by rules, when it cannot be asked: a
    name, what one example is, the scale, the question, the journey. Every
    word is the owner's to change (N570 item 1)."""
    kind = draft.get("input") or guess_input(draft)
    parts = draft.get("parts") or suggest_parts(draft)
    t = " ".join(str(draft.get(k) or "") for k in _DESCRIBE).lower()
    if parts.get("score"):
        adj = next((a for k, a in (("rush", "rushed"), ("confiden", "confident"), ("calm", "calm"),
                                    ("clear", "clear"), ("nervous", "nervous"), ("warm", "warm"))
                    if k in t), None)
        question = (f"How {adj} does it sound?" if adj and kind == "voice"
                    else DRAFTED_WORDS["q_fallback_score"] if kind == "voice"
                    else DRAFTED_WORDS["q_fallback_score_text"])
    elif parts.get("pick"):
        question = "Which exercise fits?" if "exercise" in t else DRAFTED_WORDS["q_fallback_pick"]
    else:
        question = DRAFTED_WORDS["q_fallback_answer"]
    first = _clean(draft.get("problem"), 80).split(".")[0]
    name = " ".join(first.split()[:4]).strip(" ,;:") or DRAFTED_WORDS["draft_name"]
    return {
        "name": name[:1].upper() + name[1:],
        "input": kind,
        "unit": DRAFTED_WORDS[f"unit_{kind}"],
        "parts": parts,
        "scale": [{"t": DRAFTED_WORDS[f"scale_fallback_{i}"], "d": ""} for i in range(1, 6)],
        "question": question,
        "pick_question": DRAFTED_WORDS["q_fallback_pick"] if parts.get("pick") else "",
        "options": [],
    }


def apply_drafted(draft: dict, drafted: Optional[dict]) -> dict:
    """The drafting model's reply (or the fallback), checked, into the draft;
    what the owner already wrote wins."""
    base = fallback_draft(draft)
    got = drafted if isinstance(drafted, dict) else {}
    out = dict(draft)
    for key in ("name", "unit", "question", "pick_question"):
        mine = _clean(out.get(key), 200)
        theirs = _clean(got.get(key), 200)
        out[key] = mine or theirs or base[key]
    out["name"] = out["name"][:80]
    if out.get("input") not in ("voice", "text", "image"):
        out["input"] = got.get("input") if got.get("input") in ("voice", "text", "image") else base["input"]
    if not out.get("parts"):
        p = got.get("parts")
        out["parts"] = ({k: bool(p.get(k)) for k in ("score", "pick", "answer")}
                        if isinstance(p, dict) and any(p.get(k) for k in ("score", "pick", "answer"))
                        else base["parts"])
    if not out.get("scale"):
        scale = clean_scale(got.get("scale"))
        out["scale"] = scale if scale_ok(scale) else base["scale"]
    if not out.get("options"):
        out["options"] = clean_options(got.get("options"))
    for key in ("part_titles", "part_lines"):
        raw = got.get(key)
        if not out.get(key) and isinstance(raw, dict):
            out[key] = {k: _clean(raw.get(k), 90) for k in ("score", "pick", "answer") if raw.get(k)}
    if not out.get("teach") and got.get("teach"):
        out["teach"] = _clean(got.get("teach"), 600)
    if not out.get("journey"):
        out["journey"] = journey_for(out, got.get("journey"))
    return out


# ── The scale and the question (MOD-28, MOD-38; N570 items 1 and 2) ─────────
def clean_scale(raw: Any) -> list[dict]:
    if not isinstance(raw, list):
        return []
    out = []
    for point in raw[:MAX_POINTS]:
        if isinstance(point, dict):
            out.append({"t": _clean(point.get("t"), 40), "d": _clean(point.get("d"), 120)})
        elif isinstance(point, str):
            out.append({"t": _clean(point, 40), "d": ""})
    return out


def scale_ok(scale: list[dict]) -> bool:
    """A word for every point, three to seven points."""
    return MIN_POINTS <= len(scale) <= MAX_POINTS and all(p.get("t") for p in scale)


def clean_options(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    seen: list[str] = []
    for o in raw[:MAX_OPTIONS]:
        text = _clean(o, 80)
        if text and text.lower() not in {s.lower() for s in seen}:
            seen.append(text)
    return seen


def question_ok(draft: dict) -> bool:
    """The teachers' question, and for a picking model a list of at least two."""
    if not _clean(draft.get("question"), 200):
        return False
    return not (draft.get("parts") or {}).get("pick") or len(clean_options(draft.get("options"))) >= MIN_OPTIONS


def recipe_of(draft: dict) -> dict:
    """The recipe card the teachers' screens follow (N563 item 2), from the
    draft: the input, the steps in order, the question, the scale's words
    and the list."""
    parts = draft.get("parts") or {}
    steps = [s for p, s in (("score", "rate"), ("pick", "pick"), ("answer", "words")) if parts.get(p)]
    shorter = set(draft.get("journey_off") or [])
    steps = [s for s in steps if s not in shorter] or steps[:1]
    scale = clean_scale(draft.get("scale")) if parts.get("score") else []
    recipe: dict[str, Any] = {
        "input": draft.get("input") or "voice",
        "steps": steps or ["rate"],
        "question": _clean(draft.get("question"), 200),
        "unit": _clean(draft.get("unit"), 120),
    }
    if scale:
        recipe["scale"] = [p["t"] for p in scale]
        recipe["scale_lines"] = [p.get("d") or "" for p in scale]
    if parts.get("pick"):
        recipe["pick_question"] = _clean(draft.get("pick_question") or draft.get("question"), 200)
        recipe["options"] = clean_options(draft.get("options"))
    if draft.get("rules_decided") and draft.get("rules"):
        recipe["rules"] = [r for r in draft["rules"] if r.get("on")]
        recipe["strictness"] = draft.get("strictness") if draft.get("strictness") in STRICTNESS else "clear"
    return recipe


# ── The AI for each part (MOD-29; N566 item 3, N582 item 2) ─────────────────
#: Shown faded, "Soon" (N528 item 4, N566 item 3).
COMING = ("GPT-4o", "Mistral", "Llama")


def ai_for(draft: dict) -> list[dict]:
    """Each part with the AI that fits it: a score from the voice is learned
    by WillpowerLab's own voice scorer from the start; picking and answering
    in words use GPT-4o mini."""
    parts = draft.get("parts") or {}
    titles = draft.get("part_titles") or {}
    kind = draft.get("input") or "voice"
    rows = []
    if parts.get("score"):
        line = (WORDS["ai_voice_scorer"] if kind == "voice"
                else DRAFTED_WORDS["ai_image_scorer"] if kind == "image" else DRAFTED_WORDS["ai_text_scorer"])
        rows.append({"part": "score", "title": titles.get("score") or WORDS["kind_score"],
                     "line": line, "ai": "willpowerlab_scorer"})
    if parts.get("pick"):
        rows.append({"part": "pick", "title": titles.get("pick") or WORDS["kind_pick"],
                     "line": WORDS["ai_pick"], "ai": "gpt-4o-mini"})
    if parts.get("answer"):
        rows.append({"part": "answer", "title": titles.get("answer") or WORDS["kind_answer"],
                     "line": WORDS["ai_answer"], "ai": "gpt-4o-mini"})
    return rows


# ── The teachers' journey (MOD-33) ──────────────────────────────────────────
def journey_for(draft: dict, drafted: Any = None) -> list[str]:
    """What each teacher will do, one line a step: the example, then each
    part the model does."""
    if isinstance(drafted, list) and drafted and all(isinstance(s, str) and s.strip() for s in drafted):
        return [_clean(s, 90) for s in drafted[:4]]
    unit = _clean(draft.get("unit"), 90) or DRAFTED_WORDS[f"unit_{draft.get('input') or 'voice'}"]
    first = (DRAFTED_WORDS["listen_to"] if (draft.get("input") or "voice") == "voice"
             else DRAFTED_WORDS["read"]).format(unit=unit)
    parts = draft.get("parts") or {}
    steps = [first]
    if parts.get("score"):
        steps.append(_clean(draft.get("question"), 120))
    if parts.get("pick"):
        steps.append(_clean(draft.get("pick_question") or draft.get("question"), 120))
    if parts.get("answer"):
        steps.append(DRAFTED_WORDS["say_answer"])
    return [s for s in steps if s]


_PART_STEP = {"score": "rate", "pick": "pick", "answer": "words"}


def journey_change(draft: dict, longer: bool) -> list[str]:
    """Shorter switches the last part off; Longer switches one back on. A
    teacher always has one thing to do."""
    on = [_PART_STEP[p] for p in parts_on(draft)]
    off = [s for s in (draft.get("journey_off") or []) if s in on]
    if longer:
        return off[:-1]
    left = [s for s in on if s not in off]
    return off + left[-1:] if len(left) > 1 else off


# ── Starting rules from research (MOD-30; N585) ─────────────────────────────
#: What the app already measures, the only things a sign can become a rule
#: on (N585 item 3); a sign on anything else is judged by a general model.
MEASURES = {
    "voice": {"pace_wpm": "words a minute", "pause_s": "seconds", "fillers_per_100": "fillers per 100 words",
              "hedges_per_100": "hedges per 100 words", "pitch_range_st": "semitones"},
    "text": {"words": "words", "sentence_words": "words a sentence"},
    "image": {},
}


def clean_rules(raw: Any, kind: str) -> list[dict]:
    """A study's rules as the drafting model read them, checked: each with
    its source and who it was measured on; a cut only on something the app
    measures."""
    if not isinstance(raw, list):
        return []
    measures = MEASURES.get(kind, {})
    out = []
    for r in raw[:8]:
        if not isinstance(r, dict) or not _clean(r.get("text"), 200):
            continue
        rule = {"text": _clean(r.get("text"), 200), "src": _clean(r.get("src"), 160),
                "measured_on": _clean(r.get("measured_on"), 160), "on": True}
        measure = r.get("measure")
        if measure in measures and r.get("op") in (">", "<") and isinstance(r.get("cut"), (int, float)):
            rule.update({"measure": measure, "op": r["op"], "cut": float(r["cut"]),
                         "unit": measures[measure], "answer": _clean(r.get("answer"), 40)})
        out.append(rule)
    return out


def rule_src(rule: dict) -> str:
    """The rule's source line: "From pitch-pace-study.pdf, page 4 · a study
    of 40 English-speaking founders"."""
    return " · ".join(x for x in (rule.get("src"), rule.get("measured_on")) if x)


def rule_says(rule: dict, measures: dict) -> Optional[bool]:
    """Whether a rule fires on an example's measures; None when the example
    has no such measure."""
    value = measures.get(rule.get("measure")) if isinstance(measures, dict) else None
    if not isinstance(value, (int, float)) or rule.get("cut") is None:
        return None
    return value > rule["cut"] if rule.get("op") == ">" else value < rule["cut"]


def check_rule(rule: dict, rated: list[dict]) -> Optional[dict]:
    """A starting rule against the teachers' first 50 ratings (MOD-30): kept
    when the teachers agree with it at least 7 times in 10; until 50 ratings
    with its measure, None.

    ``rated``: [{"measures": {...}, "answer": str}] oldest first."""
    if not rule.get("answer"):
        return None
    pairs = []
    for r in rated:
        fires = rule_says(rule, r.get("measures") or {})
        if fires is None:
            continue
        pairs.append(fires == (_norm(r.get("answer")) == _norm(rule.get("answer"))))
        if len(pairs) >= RULE_CHECK:
            break
    if len(pairs) < RULE_CHECK:
        return None
    k = sum(pairs)
    return {"agree_of_50": k, "kept": k >= 35}


def _norm(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().lower()


def cuts_for(rule: dict, strictness: str) -> dict:
    """One line, two cuts (N585 item 2): past the upper cut the rule's answer,
    below the lower its opposite, between them it can't tell. "Only when it's
    clear" keeps a wider middle than "When it's fairly clear" (N585 item 4)."""
    cut = float(rule.get("cut") or 0)
    band = abs(cut) * (0.15 if strictness == "clear" else 0.05)
    return {"lower": cut - band, "upper": cut + band}


# ── Uploading existing data (MOD-31; N566 item 4) ───────────────────────────
#: A column whose name says it names a person is left out by default.
_PERSON = re.compile(r"\b(name|speaker|person|people|client|customer|student|rater|author|email|"
                     r"e-mail|phone|mobile|address|surname|first|last|user|participant|founder|"
                     r"employee|patient)\b", re.I)
_EXAMPLE = re.compile(r"(clip|audio|file|recording|text|transcript|message|example|case|question|"
                      r"pitch|sentence|image|photo|content|body|path|url)", re.I)
_SCORE = re.compile(r"(score|rating|rate|grade|level|label|mark|value)", re.I)
_PICK = re.compile(r"(pick|choice|exercise|category|class|option|tag|type)", re.I)
_ANSWER = re.compile(r"(answer|reply|response|feedback|comment|advice|note)", re.I)
ROLES = ("example", "score", "pick", "answer", "out", "unused")


def parse_file(name: str, data: bytes) -> dict:
    """A spreadsheet (CSV), a JSON file (a list of objects) or a sheet that
    describes recordings: {"columns": [...], "rows": [{col: value}]}.
    Raises ValueError with a reason the owner can act on."""
    if not data:
        raise ValueError("empty")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("too_big")
    text = data.decode("utf-8-sig", errors="replace")
    lower = (name or "").lower()
    rows: list[dict]
    if lower.endswith(".json") or text.lstrip().startswith(("[", "{")):
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as e:
            raise ValueError("bad_json") from e
        if isinstance(raw, dict):
            raw = next((v for v in raw.values() if isinstance(v, list)), [])
        rows = [r for r in raw if isinstance(r, dict)] if isinstance(raw, list) else []
    elif lower.endswith((".xlsx", ".xls")):
        raise ValueError("excel")
    else:
        try:
            dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel  # type: ignore[assignment]
        rows = list(csv.DictReader(io.StringIO(text), dialect=dialect))
    rows = rows[:MAX_UPLOAD_ROWS]
    columns: list[str] = []
    for r in rows:
        for k in r:
            if k is not None and str(k) not in columns:
                columns.append(str(k))
    if not rows or not columns:
        raise ValueError("no_rows")
    return {"columns": columns[:40],
            "rows": [{c: _cell(r.get(c)) for c in columns[:40]} for r in rows]}


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)[:2000]
    return str(value).strip()[:2000]


def map_columns(columns: list[str], parts: dict) -> list[dict]:
    """Each column with the part it fills, guessed from its name: the
    example, the score, the pick, the answer; a column that names a person
    is left out (N566 item 4). The owner changes any."""
    out: list[dict] = []
    taken: set[str] = set()
    for col in columns:
        role = "unused"
        if _PERSON.search(col.replace("_", " ")):
            role = "out"
        elif _SCORE.search(col) and parts.get("score") and "score" not in taken:
            role = "score"
        elif _PICK.search(col) and parts.get("pick") and "pick" not in taken:
            role = "pick"
        elif _ANSWER.search(col) and parts.get("answer") and "answer" not in taken:
            role = "answer"
        elif _EXAMPLE.search(col) and "example" not in taken:
            role = "example"
        if role in ("example", "score", "pick", "answer"):
            taken.add(role)
        out.append({"col": col, "role": role})
    if "example" not in taken:
        for c in out:
            if c["role"] == "unused":
                c["role"] = "example"
                break
    return out


def clean_map(raw: Any, columns: list[str]) -> list[dict]:
    """The owner's map, checked: every column once, one column a part."""
    given = {str(c.get("col")): c.get("role") for c in raw if isinstance(c, dict)} if isinstance(raw, list) else {}
    out, taken = [], set()
    for col in columns:
        role = given.get(col) if given.get(col) in ROLES else "unused"
        if role in ("example", "score", "pick", "answer"):
            if role in taken:
                role = "unused"
            taken.add(role)
        out.append({"col": col, "role": role})
    return out


_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE = re.compile(r"(?<!\w)\+?\d[\d ()-]{7,}\d")
_URL = re.compile(r"https?://\S+")


def scrub(text: str, names: Iterable[str]) -> tuple[str, int]:
    """Names and places removed (N566 item 4, N528 item 12): the values of
    the columns that name a person wherever they appear in the example, and
    emails, phone numbers and links. Returns the text and how many it
    removed."""
    n = 0
    out = text
    for pattern, mark in ((_EMAIL, "[email]"), (_URL, "[link]"), (_PHONE, "[number]")):
        out, k = pattern.subn(mark, out)
        n += k
    for name in sorted({x for x in names if len(x) >= 3}, key=len, reverse=True):
        for part in {name, *name.split()}:
            if len(part) < 3:
                continue
            out, k = re.subn(rf"\b{re.escape(part)}\b", "[name]", out, flags=re.I)
            n += k
    return out, n


def _score_of(value: Any, scale: list[dict]) -> Optional[int]:
    """A score as its point on the scale, 1..n: a number, or a point's word."""
    text = _norm(value)
    if not text:
        return None
    try:
        num = float(text.replace(",", "."))
    except ValueError:
        num = None
    if num is not None and num == int(num) and 1 <= int(num) <= len(scale):
        return int(num)
    for i, p in enumerate(scale, start=1):
        if _norm(p.get("t")) == text:
            return i
    return None


def _shingles(text: str) -> set[str]:
    words = re.findall(r"\w+", text.lower())
    return {" ".join(words[i:i + 2]) for i in range(max(1, len(words) - 1))} if words else set()


def _usable(r: dict, roles: dict, scale: list[dict], needs_score: bool) -> tuple[str, Optional[int]]:
    """A row's example and score, or ("", None) when it has no example or no
    score (no pick and no answer, for a model that gives no score)."""
    example = str(r.get(roles.get("example", ""), "") or "").strip()
    if not example:
        return "", None
    if needs_score:
        score = _score_of(r.get(roles["score"]), scale)
        return (example, score) if score is not None else ("", None)
    has = any(str(r.get(roles.get(p, ""), "") or "").strip() for p in ("pick", "answer"))
    return (example, None) if has else ("", None)


def _flag_mislabelled(kept: list[dict], sigs: list[tuple[set[str], int]]) -> int:
    """A row looks mislabelled when its score is two points or more from the
    middle score of at least two examples that read alike."""
    n = 0
    for i, row in enumerate(kept):
        sh = sigs[i][0]
        close = [s for j, (o, s) in enumerate(sigs) if j != i and s and len(sh & o) / max(1, len(sh | o)) >= 0.5]
        if len(close) >= 2 and abs(sorted(close)[len(close) // 2] - int(row["score"] or 0)) >= 2:
            row["mislabelled"] = True
            n += 1
    return n


def check_data(parsed: dict, mapping: list[dict], scale: list[dict], parts: dict) -> dict:
    """The check a data scientist would run first (MOD-31): rows it can use,
    repeats and near repeats removed, rows with no score skipped, rows that
    look mislabelled (a score far from the scores of examples that read
    alike), names removed, and how the scores spread. Returns the counts and
    the rows it keeps, each ``{"example", "score", "pick", "answer",
    "mislabelled"}``."""
    roles = {m["role"]: m["col"] for m in mapping if m["role"] in ("example", "score", "pick", "answer")}
    out_cols = [m["col"] for m in mapping if m["role"] == "out"]
    rows = parsed.get("rows") or []
    needs_score = bool(parts.get("score")) and "score" in roles
    seen: set[str] = set()
    kept: list[dict] = []
    sigs: list[tuple[set[str], int]] = []
    counts: Counter = Counter()
    for r in rows:
        example, score = _usable(r, roles, scale, needs_score)
        key = _norm(example)
        sh = _shingles(key)
        if not example:
            counts["no_score"] += 1
        elif key in seen:
            counts["repeats"] += 1
        elif len(sh) >= 4 and any(len(sh & s) / max(1, len(sh | s)) >= 0.85 for s, _ in sigs[-500:]):
            counts["near"] += 1
        else:
            seen.add(key)
            clean, k = scrub(example, [str(r.get(c) or "") for c in out_cols])
            counts["names"] += k
            kept.append({"example": clean, "score": score,
                         "pick": _clean(r.get(roles["pick"]), 80) if "pick" in roles else None,
                         "answer": _clean(r.get(roles["answer"]), 2000) if "answer" in roles else None})
            sigs.append((sh, score or 0))
    mislabelled = _flag_mislabelled(kept, sigs) if needs_score else 0
    hist = Counter(r["score"] for r in kept if r.get("score"))
    return {
        "total": len(rows), "usable": len(kept), "repeats": counts["repeats"], "near": counts["near"],
        "no_score": counts["no_score"], "mislabelled": mislabelled, "names_removed": counts["names"],
        "hist": {str(i): hist.get(i, 0) for i in range(1, len(scale) + 1)} if needs_score else {},
        "rows": kept,
    }


def rerate_sample(rows: list[dict], model_id: str) -> list[int]:
    """Which 60 rows the teachers re-rate first (N566 item 4): the ones that
    look mislabelled, then a fixed random draw (by the model's id, so a
    rerun picks the same)."""
    flagged = [i for i, r in enumerate(rows) if r.get("mislabelled")]
    rest = sorted((i for i, r in enumerate(rows) if not r.get("mislabelled")),
                  key=lambda i: hashlib.sha256(f"{model_id}:{i}".encode()).hexdigest())
    return (flagged + rest)[:RERATE]


def upload_counts(pairs: list[tuple[Any, Any]]) -> Optional[dict]:
    """Whether an upload counts, from the teachers' re-rates of its sample:
    ``pairs`` of (the uploaded label, the teachers' settled answer). Counts
    when they agree at least 7 times in 10 (within one point for a score);
    None until the sample is answered."""
    if len(pairs) < RERATE:
        return None
    agree = 0
    for theirs, ours in pairs:
        try:
            agree += abs(int(theirs) - int(ours)) <= 1
        except (TypeError, ValueError):
            agree += _norm(theirs) == _norm(ours)
    share = agree / len(pairs)
    return {"share": share, "counts": share >= 0.7}


# ── The final exam (MOD-32; N566 items 5 and 6) ─────────────────────────────
def exam_split(examples: list[dict], have: int, *, n: int = EXAM_CASES) -> set[str]:
    """Which new examples go to the sealed exam: whole speakers at a time, so
    no speaker is on both sides (N566 item 6), until it holds ``n``. Never an
    uploaded row (N566 item 4), a known clip, an added example or one of the
    owner's first 10 (N570 item 3). ``have``: cases already set aside."""
    if have >= n:
        return set()
    by_speaker: dict[str, list[str]] = {}
    for e in examples:
        if e.get("source") != "takes" or e.get("known_answer") or e.get("first_ten") or not e.get("speaker_id"):
            continue
        by_speaker.setdefault(str(e["speaker_id"]), []).append(str(e["id"]))
    picked: set[str] = set()
    for speaker in sorted(by_speaker, key=lambda s: hashlib.sha256(s.encode()).hexdigest()):
        if have + len(picked) >= n:
            break
        # One speaker in five goes to the exam until it is full.
        if int(hashlib.sha256(speaker.encode()).hexdigest(), 16) % 5 == 0:
            picked.update(by_speaker[speaker])
    return picked


def exam_settled(answers: list[dict], experts: list[str]) -> Optional[str]:
    """An exam case is settled when both experts gave the same answer."""
    mine = {str(a.get("teacher_id")): a.get("answer") for a in answers
            if str(a.get("teacher_id")) in set(experts) and a.get("answer") is not None}
    vals = list(mine.values())
    return vals[0] if len(experts) >= 2 and len(vals) >= 2 and len(set(vals)) == 1 else None


# ── Similar models (MOD-26; N528 item 4) ────────────────────────────────────
def similar_model(draft: dict, models: list[dict], owner_id: str) -> Optional[dict]:
    """A public model close to what the owner described, or None: the best
    overlap of the three answers' words with a model's name, field,
    description and question, at least three words and a fifth of them."""
    mine = _words_of(draft.get("problem"), draft.get("today"), draft.get("teach"))
    if len(mine) < 3:
        return None
    best, best_score = None, 0.0
    for m in models:
        if (m.get("visibility") != "public" or m.get("status") not in ("learning", "ready")
                or str(m.get("owner_id") or "") == owner_id):
            continue
        theirs = _words_of(m.get("name"), m.get("field"), m.get("description"),
                           (m.get("recipe") or {}).get("question"))
        shared = mine & theirs
        score = len(shared) / max(1, min(len(mine), len(theirs)))
        if len(shared) >= 3 and score >= 0.2 and score > best_score:
            best, best_score = m, score
    return best


# ── The first 10 (MOD-38, MOD-55; N570 items 3 and 4, N582 item 5) ──────────
def first_ten_pool(examples: list[dict], answered: Iterable[str]) -> list[dict]:
    """The owner's first 10, from the model's own examples, none in the exam
    and none a known clip; uploads first (they are the owner's own), then
    Takes from speakers who said yes."""
    done = set(answered)
    pool = [e for e in examples if not e.get("in_exam") and not e.get("known_answer")
            and str(e.get("id")) not in done]
    pool.sort(key=lambda e: (0 if e.get("source") == "upload" else 1, str(e.get("created_at") or "")))
    return pool


# ── The checklist (MOD-36; N566 item 2) ─────────────────────────────────────
def checklist(draft: dict) -> list[dict]:
    """What is left once a model has started: each part, done or not, with
    the step that finishes it."""
    parts = draft.get("parts") or {}
    items = []
    if parts.get("score"):
        items.append({"title": WORDS["check_scale"], "step": "scale", "done": scale_ok(clean_scale(draft.get("scale")))})
    items += [
        {"title": WORDS["check_kind"], "step": "kind", "done": bool(parts_on(draft))},
        {"title": WORDS["check_rules"], "step": "rules", "done": bool(draft.get("rules_decided"))},
        {"title": WORDS["check_data"], "step": "data", "done": bool((draft.get("data") or {}).get("decided"))},
        {"title": DRAFTED_WORDS["check_question"], "step": "question",
         "done": _is_done(draft, "question") and question_ok(draft)},
        {"title": WORDS["check_exam"], "step": "exam", "done": len((draft.get("exam") or {}).get("experts") or []) >= 2},
        {"title": DRAFTED_WORDS["check_first"], "step": "first10", "done": len(draft.get("first_ten") or []) >= FIRST_TEN},
        {"title": WORDS["check_invite"], "step": "invite", "done": _is_done(draft, "invite")},
    ]
    return items


def can_start(draft: dict) -> bool:
    """A model can start right after its scale (N566 item 2), or after what
    it does when it gives no score."""
    if not _clean(draft.get("name"), 80) or not parts_on(draft):
        return False
    if (draft.get("parts") or {}).get("score"):
        return scale_ok(clean_scale(draft.get("scale")))
    return True


def ready_screen(name: str, draft: dict, *, ratings_target: int) -> dict:
    """The last step (MOD-36): ready to learn, what is left, the API's lock."""
    items = checklist(draft)
    return {
        "step": "ready",
        "lines": [WORDS["ready"].format(name=name)],
        "checklist": ({"title": WORDS["to_finish"], "items": items}
                      if any(not i["done"] for i in items) else None),
        "locked": {"title": WORDS["sell_title"],
                   "lines": [WORDS["sell_line"], WORDS["sell_needs"].format(n=ratings_target)]},
        "actions": [WORDS["try_it"], WORDS["back_to_list"]],
    }


# ── One step's screen (MOD-24 to MOD-38, MOD-54, MOD-55) ────────────────────
def _choice(key: str, title: str, line: str = "", **flags: Any) -> dict:
    return {"key": key, "title": title, "line": line, **flags}


def _ctx_unit(draft: dict) -> str:
    return _clean(draft.get("unit"), 120) or DRAFTED_WORDS[f"unit_{draft.get('input') or 'voice'}"]


def _is_voice(draft: dict) -> bool:
    return (draft.get("input") or "voice") == "voice"


def _s_describe(draft: dict, step: str, ctx: dict) -> dict:
    out: dict[str, Any] = {"lines": [WORDS[f"q_{step}"]], "fields": {step: draft.get(step) or ""},
                           "actions": [WORDS["next"]]}
    if draft.get("from_first_take"):
        out["notes"] = [DRAFTED_WORDS["filled"]]
    if step == "teach" and ctx.get("similar"):
        out["sheet"] = {"title": WORDS["similar_title"], "card": ctx["similar"], "line": WORDS["similar_line"],
                        "actions": [WORDS["teach_this_one"], WORDS["set_up_mine"]]}
    return out


def _s_kind(draft: dict, _step: str, _ctx: dict) -> dict:
    on = parts_on(draft)
    k = len(on)
    line = WORDS["kinds_three"] if k == 3 else DRAFTED_WORDS["kinds_some"].format(
        n=DRAFTED_WORDS["one_thing"] if k == 1 else DRAFTED_WORDS["two_things"])
    lines = draft.get("part_lines") or {}
    return {"lines": [line],
            "choices": [_choice(p, WORDS[f"kind_{p}"], lines.get(p, ""), check=p in on)
                        for p in ("score", "pick", "answer")],
            "fields": {"name": draft.get("name") or "", "name_label": DRAFTED_WORDS["its_name"]},
            "actions": [WORDS["thats_right"]]}


def _s_scale(draft: dict, _step: str, _ctx: dict) -> dict:
    scale = clean_scale(draft.get("scale"))
    line = WORDS["scale_line"] if _is_voice(draft) else DRAFTED_WORDS["scale_line_text"]
    return {"lines": [line.format(unit=_ctx_unit(draft))],
            "fields": {"scale": [{"point": i + 1, **p} for i, p in enumerate(scale)]},
            "notes": [WORDS["scale_help"]] + ([] if scale_ok(scale) else [DRAFTED_WORDS["give_every_point"]]),
            "actions": [WORDS["use_this_scale"], WORDS["start_now"]]}


def _s_question(draft: dict, _step: str, _ctx: dict) -> dict:
    out: dict[str, Any] = {
        "lines": [DRAFTED_WORDS["q_intro"] if _is_voice(draft) else DRAFTED_WORDS["q_intro_text"]],
        "fields": {"question": draft.get("question") or ""}, "notes": [],
        "actions": [DRAFTED_WORDS["use_this_question"]]}
    if (draft.get("parts") or {}).get("pick"):
        options = clean_options(draft.get("options"))
        out["lines"].append(DRAFTED_WORDS["q_list"])
        out["fields"].update({"pick_question": draft.get("pick_question") or "", "options": options,
                              "add_option": DRAFTED_WORDS["add_option"]})
        if len(options) < MIN_OPTIONS:
            out["notes"].append(DRAFTED_WORDS["two_options"])
    out["notes"].append(DRAFTED_WORDS["q_help"])
    return out


def _s_ai(draft: dict, _step: str, _ctx: dict) -> dict:
    return {"lines": [WORDS["ai_intro"]],
            "choices": [_choice(r["part"], r["title"], r["line"], on=True) for r in ai_for(draft)],
            "others": {"title": WORDS["ai_others"],
                       "choices": [_choice(x, x, "", faded=True, tag=WORDS["soon"]) for x in COMING]},
            "actions": [WORDS["thats_right"]]}


def _s_rules(draft: dict, _step: str, _ctx: dict) -> dict:
    rules = draft.get("rules") or []
    out: dict[str, Any] = {
        "lines": [WORDS["rules_intro"]], "fields": {"study": draft.get("study_name")},
        "choices": [_choice(str(i), r["text"], rule_src(r), check=bool(r.get("on"))) for i, r in enumerate(rules)],
        "notes": [WORDS["rules_check"]] if rules else [],
        "actions": [WORDS["use_these_rules"], WORDS["skip"]]}
    if any(r.get("measure") for r in rules):
        strict = draft.get("strictness", "clear")
        out["strictness"] = {"title": DRAFTED_WORDS["strict_title"], "choices": [
            _choice("clear", DRAFTED_WORDS["strict_clear"], on=strict == "clear"),
            _choice("fairly_clear", DRAFTED_WORDS["strict_fairly"], on=strict == "fairly_clear")]}
    return out


def _s_data(draft: dict, _step: str, _ctx: dict) -> dict:
    data = draft.get("data") or {}
    return {"lines": [WORDS["data_intro"]], "fields": {"file": data.get("name"), "rows": len(data.get("rows") or [])},
            "notes": [WORDS["data_kinds"]], "actions": [WORDS["use_this_data"], WORDS["no_data"]]}


def _s_columns(draft: dict, _step: str, _ctx: dict) -> dict:
    n = len(clean_scale(draft.get("scale"))) or 5
    role_line = {"example": WORDS["col_example"].format(unit=_ctx_unit(draft)),
                 "score": WORDS["col_score"].format(n=n), "pick": WORDS["col_pick"],
                 "answer": WORDS["col_answer"], "out": WORDS["col_out"], "unused": DRAFTED_WORDS["col_unused"]}
    return {"lines": [WORDS["columns_intro"]],
            "choices": [_choice(c["col"], c["col"], role_line[c["role"]], role=c["role"],
                                on=c["role"] not in ("out", "unused"), faded=c["role"] in ("out", "unused"))
                        for c in (draft.get("data") or {}).get("map") or []],
            "actions": [WORDS["thats_right"]]}


def _s_exam(draft: dict, _step: str, ctx: dict) -> dict:
    experts = (draft.get("exam") or {}).get("experts") or []
    second = experts[1] if len(experts) > 1 else None
    people = ctx.get("people") or []
    pick = next((p for p in people if p["id"] == second), None)
    return {"lines": [WORDS["exam_intro"], WORDS["exam_sold"]],
            "choices": [_choice("me", WORDS["you"], WORDS["owner"], check=True)] + [
                _choice(p["id"], p["name"], p.get("line") or "", check=p["id"] == second) for p in people],
            "actions": [WORDS["ask"].format(name=str(pick["name"]).split()[0]) if pick
                        else DRAFTED_WORDS["choose_expert"]]}


def _s_journey(draft: dict, _step: str, _ctx: dict) -> dict:
    off = set(draft.get("journey_off") or [])
    steps = journey_for(draft, draft.get("journey"))
    keep = [steps[0]] + [s for s, p in zip(steps[1:], [_PART_STEP[p] for p in parts_on(draft)]) if p not in off]
    return {"lines": [WORDS["journey_intro"]], "fields": {"steps": keep},
            "choices": [_choice("shorter", WORDS["shorter"]), _choice("longer", WORDS["longer"])],
            "actions": [WORDS["looks_good"]]}


def _s_first(draft: dict, _step: str, ctx: dict) -> dict:
    return _first_screen(draft, ctx.get("first"))


def _s_share(draft: dict, _step: str, _ctx: dict) -> dict:
    vis = draft.get("visibility") or "private"
    return {"lines": [WORDS["who_sees"]],
            "choices": [_choice("private", WORDS["private"], WORDS["private_line"], on=vis == "private"),
                        _choice("public", WORDS["public"], WORDS["public_line"], on=vis == "public")],
            "actions": [WORDS["next"]]}


def _s_public(_draft: dict, _step: str, _ctx: dict) -> dict:
    return {"caption": WORDS["public_caption"],
            "lines": [WORDS["public_1"], WORDS["public_2"], WORDS["public_3"], WORDS["public_4"]],
            "actions": [WORDS["make_public"], WORDS["keep_private"]]}


def _s_invite(draft: dict, _step: str, ctx: dict) -> dict:
    invited = set(draft.get("invited") or [])
    team = ctx.get("team") or {}
    choices = []
    if team.get("name"):
        choices.append(_choice("team", WORDS["everyone_in"].format(team=team["name"]),
                               WORDS["team_line"].format(n=int(team.get("size") or 0)),
                               check=bool(draft.get("invited_team"))))
    choices += [_choice(p["id"], p["name"], p.get("line") or "", check=p["id"] in invited)
                for p in ctx.get("people") or []]
    return {"lines": [WORDS["who_teaches"]], "choices": choices,
            "actions": [WORDS["invite_them"], WORDS["copy_link"]]}


def _s_check(draft: dict, _step: str, _ctx: dict) -> dict:
    return _check_screen(draft)


def _s_ready(draft: dict, _step: str, _ctx: dict) -> dict:
    return ready_screen(draft.get("name") or "", draft, ratings_target=500)


_SCREENS = {
    "problem": _s_describe, "today": _s_describe, "teach": _s_describe, "kind": _s_kind,
    "scale": _s_scale, "question": _s_question, "ai": _s_ai, "rules": _s_rules, "data": _s_data,
    "columns": _s_columns, "check": _s_check, "exam": _s_exam, "journey": _s_journey,
    "first10": _s_first, "share": _s_share, "public": _s_public, "invite": _s_invite, "ready": _s_ready,
}


def step_screen(draft: dict, step: str, *, similar: Optional[dict] = None,
                people: Optional[list[dict]] = None, team: Optional[dict] = None,
                first: Optional[dict] = None) -> dict:
    """One step of the setup as the owner's screen shows it: the frame
    (chapter, caption, bar), the lines Will says, the choices and fields,
    and the actions. ``similar``: a public model's list row for the sheet
    over the third answer; ``people``: the people from the owner's chats;
    ``team``: {"name", "size"} for the company's community; ``first``: the
    owner's first-10 state."""
    if step not in STEPS:
        raise ValueError(step)
    screen: dict[str, Any] = {"step": step, **frame(draft, step), "lines": [], "notes": [],
                              "choices": [], "fields": {}, "actions": []}
    ctx = {"similar": similar, "people": people, "team": team, "first": first}
    screen.update(_SCREENS[step](draft, step, ctx))
    return screen


def _check_screen(draft: dict) -> dict:
    data = draft.get("data") or {}
    c = data.get("check") or {}
    scale = clean_scale(draft.get("scale"))

    def f(v: Any) -> str:
        return f"{int(v or 0):,}"
    rows = [[WORDS["rows_usable"], f"{f(c.get('usable'))} / {f(c.get('total'))}"],
            [WORDS["rows_repeats"], f(c.get("repeats"))], [WORDS["rows_near"], f(c.get("near"))],
            [WORDS["rows_no_score"], f(c.get("no_score"))],
            [WORDS["rows_mislabelled"], WORDS["checked_first"].format(n=f(c.get("mislabelled")))],
            [WORDS["rows_names"], f(c.get("names_removed"))]]
    notes = []
    hist = {int(k): int(v) for k, v in (c.get("hist") or {}).items()}
    if hist and sum(hist.values()) and len(scale) == len(hist):
        order = sorted(hist, key=lambda k: (-hist[k], k))
        a, b = sorted(order[:2])
        least = order[-1]
        notes.append(WORDS["spread"].format(a=a, b=b, least=least,
                                            word=str(scale[least - 1]["t"]).lower()))
    if c.get("mislabelled"):
        notes.append(WORDS["mislabelled_line"].format(n=f(c.get("mislabelled"))))
    return {
        "lines": [WORDS["checked"]],
        "table": rows, "hist": [{"point": k, "n": v} for k, v in sorted(hist.items())],
        "notes": notes,
        "after": [WORDS["rerate"]],
        "choices": [_choice("consent", WORDS["data_consent"], check=bool(data.get("consent")))],
        "actions": [WORDS["upload_it"], WORDS["fix_file"]],
    }


def _first_screen(draft: dict, first: Optional[dict]) -> dict:
    done = len(draft.get("first_ten") or [])
    if first and first.get("example"):
        return {"caption": DRAFTED_WORDS["first_caption"].format(i=min(FIRST_TEN, done + 1)),
                "teaching": first["example"], "lines": [], "actions": []}
    if done >= FIRST_TEN:
        return {"lines": [DRAFTED_WORDS["first_done"], DRAFTED_WORDS["first_reads"]],
                "notes": [DRAFTED_WORDS["first_not_exam"]], "actions": [WORDS["next"]]}
    lines = [DRAFTED_WORDS["first_intro"], DRAFTED_WORDS["first_reads"]]
    if first is not None and not first.get("available"):
        return {"lines": lines, "notes": [DRAFTED_WORDS["first_not_exam"], DRAFTED_WORDS["first_none"]],
                "actions": [DRAFTED_WORDS["later"]]}
    return {"lines": lines, "notes": [DRAFTED_WORDS["first_not_exam"]],
            "actions": [DRAFTED_WORDS["start"], DRAFTED_WORDS["later"]]}


# ── The owner's page (MOD-37; N566 item 6) ──────────────────────────────────
def measured(example_id: str) -> bool:
    """1 example in 10, picked at random once and for all by its id, is where
    agreement is measured (N566 item 6), so the hard ones served first don't
    make it look worse than it is."""
    return int(hashlib.sha256(str(example_id).encode()).hexdigest(), 16) % 10 == 0


def agreement(rates: dict[str, list[Any]]) -> dict:
    """How often teachers agree, within one point and exactly, over every
    pair of trusted answers on the measured examples. ``rates``: example id
    to the trusted teachers' points (1..n)."""
    within = exact = n = 0
    confused: Counter = Counter()
    for eid, points in rates.items():
        if not measured(eid):
            continue
        vals = [int(p) for p in points if str(p).isdigit()]
        for i in range(len(vals)):
            for j in range(i + 1, len(vals)):
                n += 1
                d = abs(vals[i] - vals[j])
                within += d <= 1
                exact += d == 0
                if d:
                    confused[tuple(sorted((vals[i], vals[j])))] += 1
    return {"n": n, "within": within / n if n else 0.0, "exact": exact / n if n else 0.0,
            "confused": confused.most_common(1)[0][0] if confused else None}


def weeks_left(left: int, per_week: float) -> Optional[tuple[int, int]]:
    """An honest range for what is left of a jar at this pace (N566 item 6)."""
    if left <= 0:
        return (0, 0)
    if per_week <= 0:
        return None
    return (max(1, math.floor(left / (per_week * 1.25))), max(1, math.ceil(left / (per_week * 0.8))))


def _needs_you(agree: dict, scale: list[dict]) -> Optional[dict]:
    """Where the teachers disagree most, once there is enough to say so."""
    if agree.get("n", 0) < 10 or agree.get("exact", 1) >= 0.7 or not agree.get("confused") or not scale:
        return None
    a, b = agree["confused"]
    if not (1 <= a <= len(scale) and 1 <= b <= len(scale)):
        return None
    return {"title": WORDS["needs_you"],
            "line": WORDS["disagree"].format(a=a, b=b, ta=scale[a - 1]["t"], tb=scale[b - 1]["t"]),
            "actions": [WORDS["make_clearer"]], "step": "scale"}


def _head(name: str, pct: int, jars: dict, targets: dict, pace: dict) -> str:
    """How far it is, with an honest range and the slowest jar when every
    jar has a pace."""
    ranges = {jar: weeks_left(int(targets[jar]) - int(jars.get(jar) or 0), float(pace.get(jar) or 0))
              for jar in ("ratings", "exam", "voices") if int(targets.get(jar) or 0)}
    known = {k: v for k, v in ranges.items() if v is not None}
    if not known or len(known) != len(ranges) or max(v[1] for v in known.values()) <= 0:
        return WORDS["way"].format(name=name, pct=pct)
    slowest = max(known, key=lambda k: known[k][1])
    jar_word = WORDS["jar_voices"] if slowest == "voices" else DRAFTED_WORDS[f"jar_{slowest}"]
    lo, hi = known[slowest]
    return WORDS["way_range"].format(name=name, pct=pct, lo=lo, hi=hi, jar=jar_word)


def _upload_value(upload: Optional[dict]) -> str:
    if upload is None:
        return DRAFTED_WORDS["none"]
    n = f"{int(upload['usable']):,}"
    if upload.get("result") is None:
        return DRAFTED_WORDS["upload_waiting"].format(n=n)
    k = round(upload["result"]["share"] * 10)
    return (DRAFTED_WORDS["upload_counts"] if upload["result"]["counts"]
            else DRAFTED_WORDS["upload_not_yet"]).format(n=n, k=k)


def _panel_rows(jars: dict, targets: dict, agree: dict, upload: Optional[dict]) -> list[list[str]]:
    agree_value = (WORDS["agree_value"].format(w=round(agree["within"] * 10), e=round(agree["exact"] * 10))
                   if agree.get("n") else DRAFTED_WORDS["not_measured"])
    ratings_target = int(targets.get("ratings") or 500)
    sealed = int(jars.get("exam") or 0) >= int(targets.get("exam") or EXAM_CASES)
    return [[WORDS["agree_title"], agree_value],
            [WORDS["ratings_row"], f"{min(int(jars.get('ratings') or 0), ratings_target)} / {ratings_target}"],
            [WORDS["exam_row"], WORDS["exam_sealed"] if sealed else DRAFTED_WORDS["exam_not_yet"]],
            [WORDS["upload_row"], _upload_value(upload)]]


def _source_rows(sources: dict) -> list[list[Any]]:
    src: list[list[Any]] = [
        [WORDS["src_takes"], int(sources.get("takes") or 0)],
        [WORDS["src_upload"], int(sources.get("upload_counted") or 0)],
        [WORDS["src_business"], int(sources.get("business") or 0) or WORDS["none_yet"]],
        [WORDS["src_teacher"], WORDS["src_teacher_value"].format(n=int(sources.get("teacher") or 0))]]
    if sources.get("first_total"):
        src.append([DRAFTED_WORDS["src_first"], DRAFTED_WORDS["src_first_value"].format(
            n=sources["first_total"], k=int(sources.get("first_settled") or 0))])
    return src


def _rule_lines(draft: dict, rules_checked: list[dict]) -> list[str]:
    rules = [r for r in draft.get("rules") or [] if r.get("on")]
    if not rules:
        return [DRAFTED_WORDS["rules_none"]]
    checked = {c["text"]: c for c in rules_checked}
    lines = []
    for r in rules:
        c = checked.get(r["text"])
        if c is None:
            lines.append(DRAFTED_WORDS["rules_waiting"])
        else:
            lines.append((WORDS["rule_kept"] if c["kept"] else WORDS["rule_stopped"]).format(
                rule=r["text"].rstrip("."), k=c["agree_of_50"]))
    return list(dict.fromkeys(lines))


def owner_panel(model: dict, draft: dict, *, pct: int, jars: dict, targets: dict,
                pace: dict, agree: dict, sources: dict, upload: Optional[dict],
                rules_checked: list[dict]) -> dict:
    """What the owner sees on top of their model's page: "Needs you now",
    how far it is with an honest range and the slowest jar, how often the
    teachers agree, where its examples come from, what runs by itself, a
    fair exam and its starting rules checked. Totals only, never a person
    (N526 item 3)."""
    scale = clean_scale(draft.get("scale")) or [{"t": t, "d": ""} for t in (model.get("recipe") or {}).get("scale") or []]
    notes = []
    if agree.get("n"):
        notes.append(WORDS["agree_ok"] if agree["within"] >= 0.7 else DRAFTED_WORDS["disagree_low"])
    items = checklist(draft)
    return {
        "needs_you": _needs_you(agree, scale),
        "head": _head(model.get("name") or "", pct, jars, targets, pace),
        "rows": _panel_rows(jars, targets, agree, upload),
        "notes": notes,
        "folds": [
            {"title": WORDS["sources_title"], "rows": _source_rows(sources)},
            {"title": WORDS["runs_title"], "lines": [WORDS["runs_line"]],
             "then": {"title": WORDS["decide_title"], "lines": [WORDS["decide_line"]]}},
            {"title": WORDS["fair_title"], "lines": [WORDS["fair_line"].format(n=_count_word(len(scale) or 5))]},
            {"title": WORDS["rules_title"], "lines": _rule_lines(draft, rules_checked)},
        ],
        "checklist": {"title": WORDS["to_finish"], "items": items} if any(not i["done"] for i in items) else None,
    }


def _count_word(n: int) -> str:
    return ("zero", "one", "two", "three", "four", "five", "six", "seven")[n] if 0 <= n <= 7 else str(n)
