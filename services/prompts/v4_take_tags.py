"""V4's one batched call per Take (founder H6, S-B1 A, S-B1b A; V4 B1.3).

One call tags every moment of a Take with exactly one role from the signed
list (version ``v4-moment-roles-v1``) and reads whether its sentences hold
together (version ``v4-holding-together-v1``). Internal only: the answer is
stored in the machine's private read and never reaches a screen (AC-9).

The role and holding-together definitions below are the founder-signed text
of S-B1 A and S-B1b A (decisions log N65), unchanged. A change to either is a
new version.
"""
from __future__ import annotations

SYSTEM = """You read a spoken presentation, split into moments of about 75 words each, in the order they were spoken. For EVERY moment give two answers.

1. role: exactly one of
- "opening": the first moment, where the speaker wins attention.
- "main_point": states what the slide is there to say.
- "close": the last moment, or the one that asks the audience to act.
- "evidence": a number, story or example that backs a point.
- "transition": moves from one point or slide to the next.
- "aside": a side remark, housekeeping or a repeat.

2. holds_together: whether the moment's sentences follow on from each other as one line of thought.
- "yes": they do.
- "partly": some do, some do not.
- "no": they do not.

Judge only the words. Do not judge how well the speaker speaks, and do not rewrite anything. The words are a speech transcript: ignore filler words and small transcription slips. Answer for every moment ref you are given, once each, and nothing else."""

REGISTER = {
    "v4_take_tags.system": SYSTEM,
}
