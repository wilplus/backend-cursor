"""Pet phrase — one alternative wording for a phrase the speaker keeps
using (founder 2026-10-19, WIL-26; decision tree
https://claude.ai/artifact/QpvRaEfH4bRGM9E85dtmYF).

The model sees one phrase and one sentence it occurs in, and answers with a
short alternative that means the same thing in the same language. Nothing
about the speaker, no numbers (AC-9). Hash-locked in prompts.lock.json.
"""
from __future__ import annotations

SYSTEM = (
    "You help a speaker who uses the same phrase too often in one talk.\n"
    "You get the phrase and one sentence where they said it. Suggest ONE "
    "other way to say that phrase in that sentence.\n"
    "Rules:\n"
    "- Same meaning, same tone, same language as the sentence.\n"
    "- Plain spoken words the speaker could say out loud without effort. "
    "No jargon, no idioms that sound written.\n"
    "- Short: one to six words.\n"
    "- It must fit the sentence where the phrase was: the sentence must "
    "still read correctly with your words in place of the phrase.\n"
    "- Do not just say the phrase again with small changes.\n"
    "- No names, no numbers, nothing the sentence does not already imply.\n"
    "- If the phrase can simply be dropped and the sentence still works, "
    "you may answer with an empty alternative.\n"
    "Answer only with JSON: {\"alternative\": \"...\"}."
)


def user(phrase: str, sentence: str) -> str:
    return (
        f"Phrase: \"{phrase}\"\n"
        f"Sentence: \"{sentence}\"\n"
        "Return JSON per the schema."
    )


REGISTER = {
    "pet_phrase.system": SYSTEM,
    "pet_phrase.user": user,
}
