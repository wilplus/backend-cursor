"""Prompts for the coach's answer drafts (founder 2026-09-30, C2; build plan
P2-2). One draft per request kind, shown to the coach only, edited before
anyone else sees a word, and paired with the coach's final for the learning
ledger (services.feedback_pairs). Three surfaces, three prompts, so the
pairs of one never train the other:

  * exercise_script  — an error moment: a short practice exercise
  * praise_line      — a praise moment: one sentence naming what worked
  * clearer_version  — a rewrite moment: the passage said more clearly

Every prompt forbids scores, ratios and judgements about the person
(AC-9), and forbids adding facts the passage did not carry (the clearer
version says what was said, better). Editing ANY text below is a prompt
change: regenerate prompts.lock.json and expect the golden evals to run.
"""
from __future__ import annotations

from typing import Optional

_NEVER = (
    " Never give a score, a rating, a percentage or a number about the "
    "speaker. Never judge the speaker as a person. Never invent facts, "
    "names or figures the passage does not contain."
)

EXERCISE_SCRIPT_SYSTEM = (
    "You write short practice exercises for a public-speaking coach. The "
    "coach reads the exercise for one moment of a speaker's own talk, edits "
    "every word, and may record a video following it. Write in the second "
    "person, plainly. Name the one delivery pattern the exercise addresses, "
    "say what to do differently on the next attempt of this exact passage, "
    "and keep it under 120 words." + _NEVER
)

PRAISE_LINE_SYSTEM = (
    "You write one sentence of praise for a public-speaking coach to give a "
    "speaker about one moment of their own talk. Name the one thing that "
    "worked in how it was delivered, in plain words, in the second person, "
    "at most 25 words, no exclamation marks, no flattery about the person." + _NEVER
)

CLEARER_VERSION_SYSTEM = (
    "You rewrite one passage of a speaker's own talk so it is said more "
    "clearly. Keep the speaker's meaning, facts and voice; remove hedges, "
    "filler and restarts; keep it about the same length or shorter. Return "
    "only the rewritten passage, nothing else." + _NEVER
)


def user(*, surface: str, passage: str, spotted: list[str],
         kind: str, notes: Optional[str] = None) -> str:
    """The moment as the coach sees it: the passage, what the machine
    spotted (by its library name), and the coach's own notes if any."""
    lines = [f"The moment reached the coach as: {kind}."]
    if spotted:
        lines.append("Delivery pattern(s) spotted in it: " + "; ".join(spotted) + ".")
    if notes:
        lines.append(f"Coach's notes: {notes}")
    lines.append(f"The passage, as spoken: \"{passage}\"")
    ask = {
        "exercise_script": "Write the exercise.",
        "praise_line": "Write the one sentence.",
        "clearer_version": "Write the clearer version of the passage.",
    }.get(surface, "Write it.")
    lines.append(ask)
    return "\n".join(lines)


REGISTER = {
    "exercise_script.system": EXERCISE_SCRIPT_SYSTEM,
    "exercise_script.user": user,
    "praise_line.system": PRAISE_LINE_SYSTEM,
    "praise_line.user": user,
    "clearer_version.system": CLEARER_VERSION_SYSTEM,
    "clearer_version.user": user,
}
