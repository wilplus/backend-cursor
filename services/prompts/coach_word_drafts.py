"""Prompts for the coach's own words (founder 2026-10-01, C5-a; Phase 7 of
the coach panel). Two surfaces, two prompts, so the pairs of one never
train the other:
  * coach_moment_line — the coach's personal line on one moment (C1)
  * coach_take_word   — the coach's one word for a Take (35g-6)
TEXT ONLY, BLIND: the inputs are the transcript and the coach's own notes;
never acoustics, never the machine's read. Every prompt forbids scores,
ratios, numbers and judgements about the person (AC-9), forbids stating or
implying how the machine read the delivery, and forbids facts the passage
did not carry. The draft sits in the field the coach edits and is never
shown to a speaker as drafted. Editing ANY text below is a prompt change:
regenerate prompts.lock.json and expect the golden evals to run.
"""
from __future__ import annotations

from typing import Optional

_NEVER = (
    " Never give a score, a rating, a percentage or a number about the "
    "speaker. Never say or imply how a machine read the delivery. Never "
    "judge the speaker as a person. Never invent facts, names or figures the "
    "passage does not contain."
)

COACH_MOMENT_LINE_SYSTEM = (
    "You draft one personal line a public-speaking coach may say to a "
    "speaker about one moment of their own talk, from the words that were "
    "spoken and the coach's notes. Second person, plain, warm, at most 30 "
    "words, no exclamation marks. The coach will edit every word." + _NEVER
)

COACH_TAKE_WORD_SYSTEM = (
    "You draft a short message a public-speaking coach may send a speaker "
    "about one whole run of their talk, from the transcript and the coach's "
    "notes. Second person, plain, warm, two or three sentences, at most 70 "
    "words, no exclamation marks. Say one thing to keep and, if the coach's "
    "notes name it, one thing to try next time. The coach will edit every "
    "word." + _NEVER
)

SYSTEM = {
    "coach_moment_line": COACH_MOMENT_LINE_SYSTEM,
    "coach_take_word": COACH_TAKE_WORD_SYSTEM,
}


def user(*, surface: str, transcript: str, coach_text: Optional[str] = None) -> str:
    """The words as spoken and the coach's own notes, nothing else."""
    lines = []
    if coach_text:
        lines.append(f"Coach's notes: {coach_text}")
    what = "The moment, as spoken" if surface == "coach_moment_line" else "The talk, as spoken"
    lines.append(f"{what}: \"{transcript}\"")
    lines.append("Write the line." if surface == "coach_moment_line" else "Write the message.")
    return "\n".join(lines)


REGISTER = {
    "coach_moment_line.system": COACH_MOMENT_LINE_SYSTEM,
    "coach_moment_line.user": user,
    "coach_take_word.system": COACH_TAKE_WORD_SYSTEM,
    "coach_take_word.user": user,
}
