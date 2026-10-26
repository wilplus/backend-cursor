"""Prompt for the tempo step's topic (founder 2026-10-26, N162, N166).

Names what a stretch of the speaker's Take was about in a few words, said
back in Will's line "Tell me more about {topic}, and keep the ball in the
green." The service keeps the call and the output guard
(services/tempo_stretch.py). Editing the text below is a prompt change:
regenerate prompts.lock.json.
"""
from __future__ import annotations

SYSTEM = (
    "A speaker said the passage below in a talk. Name what it is about in "
    "2 to 6 words, as a noun phrase that fits after 'Tell me more about': "
    "for example 'the beds for sale' or 'your hiring plan'. Use the "
    "speaker's own subject and words; speak to them as 'your' where it is "
    "theirs. No verb, no full stop, no quotes, no numbers.\n"
    "Answer with the phrase only."
)

REGISTER = {
    "tempo_topic.system": SYSTEM,
}
