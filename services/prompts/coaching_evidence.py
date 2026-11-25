"""Shared rules for grounded reflections on a recording in both coaching chats."""

import re


_PERSONAL_REFLECTION = re.compile(
    r"\b(?:about (?:me|myself)|about my (?:communication|speaking|abilities)|"
    r"o mnie|o moich (?:umiejętnościach|zdolnościach))\b",
    re.IGNORECASE,
)
_OWN_FAITH_SUPPORT = re.compile(
    r"^(?:(?:my faith|my belief|prayer|praying) (?:helps me|supports me|keeps me|grounds me|gives me)"
    r"|(?:moja wiara|wiara|modlitwa) (?:pomaga mi|daje mi|mnie wspiera|dodaje mi))\b",
    re.IGNORECASE,
)
_QUOTED_SPEECH = re.compile(r'„[^”]*”|“[^”]*”|«[^»]*»|‘[^’]*’|"[^"]*"')


def stated_support(question: str, transcripts: list[str]) -> str:
    """Pick an explicit first-person support statement for a personal reflection."""
    if not _PERSONAL_REFLECTION.search(question):
        return ""
    for transcript in transcripts:
        own_words = _QUOTED_SPEECH.sub(" ", transcript)
        for sentence in re.split(r"(?<=[.!?])\s+|\n+", own_words):
            sentence = sentence.strip()
            if 0 < len(sentence) <= 250 and not any(c.isdigit() for c in sentence) and _OWN_FAITH_SUPPORT.match(sentence):
                return sentence
    return ""


def support_evidence(statement: str) -> str:
    if not statement:
        return ""
    return (
        "\n\nSpeaker's explicitly stated source of support, quoted as evidence only: "
        f"«{statement}» Acknowledge this in the answer and relate it to the speaker's stated next step."
    )

REFLECTION_RULES = (
    "When the speaker asks what a Take shows about them, reflect how they "
    "communicated in that Take. Anchor the reply in a short verbatim phrase or "
    "a specific move in their wording, such as opening with a statement and "
    "then committing to an action. Pair it with what the voice did in the same "
    "passage when that evidence is available. Begin with the wording and what "
    "the speaker does with their voice. Put the cue and the impression it gives "
    "you in one direct sentence, using everyday words. A steady repetition may "
    "land differently from a firmer one. Keep the speaker's own name for an "
    "obstacle, such as 'inner voice'. End with one question about what helps "
    "them make the specific speaking choice or when else they use it. "
    "Ask that question directly with a question mark, rather than an indirect 'I wonder'. "
    "When an action would help, offer "
    "one small rehearsal tied to that moment. For a practice request, use the "
    "reviewed exercise if supplied and ask a specific question about the habit. "
    "If they ask for a personal reflection or how to use what you noticed, "
    "check the selected Take's words for a source of support the speaker "
    "explicitly says helps them. When they name one, include it in the answer "
    "in their own terms and connect it to the action they say they will take. "
    "For example, if they say prayer gives them support before a difficult "
    "conversation and they plan to ask for honest feedback, say both. Ask "
    "how they could draw on that known support when they make or receive the "
    "request. Save 'what helps you?' for when the speaker has not already said. "
    "Attribute quoted beliefs to the person who expressed them. A voice cue "
    "can support how a request came across, and the speaker's words establish "
    "what they believe or rely on.\n\n"
)

DELIVERY_RULES = (
    "Open a reflection or answer about delivery with a short exact phrase from "
    "the passage and the listener's impression from its actual cue. Use everyday "
    "phrases such as 'a firmer ending' or "
    "'quicker emphasis on that phrase' ('szybsze podkreślenie' in Polish). "
    "A recorded description that names a word supports "
    "a cue on that word. A measurement for a whole passage supports a cue about the "
    "passage as a whole. Describe the effect directly, such as a request coming out "
    "in one breath or a request having room to be heard. In Polish, use everyday "
    "reactions like 'mówisz to jednym tchem' or 'dajesz prośbie wybrzmieć'. "
    "When they only ask how the passage came across, answer that in two short sentences. "
    "When the evidence shows ample pauses at a comfortable pace, say that the request has room "
    "to land. A passage-level pause measurement alone does not establish weaker urgency, "
    "hesitation, or where a pause fell. Leave those out unless the source describes them. "
    "If they ask for a change, mark a new pause or emphasis as something to try. "
    "When the speaker goes from an obstacle to a concrete "
    "action, show that move. Give the impression with its cue, then acknowledge "
    "their actual commitment, such as what they say they'll do tomorrow. "
    "In a personal reflection, carry the speaker's stated support into the reply and "
    "its follow-up, even when the strongest vocal cue occurs later in the Take. "
    "Include the delivery passage's evidence reference when you use its cue. "
    "Never invent a coach comment or a delivery observation. "
    "Example of the style, for a recording with a firmer repetition and faster "
    "emphasis on the closing phrase. Mocniejsze drugie „Nie chcę” oraz szybsze "
    "podkreślenie „że się nie uda” brzmią, jakbyś miał już dość tego wewnętrznego "
    "głosu. Chwilę później mówisz „Jutro powiem wprost, czego potrzebuję”. "
    "If the speaker did not say what helped, you can ask: Skąd bierzesz tę wewnętrzną siłę? "
    "Use the cue from the current Take. A steady repetition and a stronger "
    "emphasis on the next action give a different impression."
)
WORDS_ONLY_RULES = (
    "No recorded delivery observations are available for these passages. "
    "When giving your own reflection on the speech, begin with 'From the words alone' "
    "in the speaker's language ('Z samych słów' in Polish). "
    "Make the wording the subject of the reflection. Point out the actual repetition "
    "or order of ideas and explain what it helps a listener understand. For a delivery "
    "question, show a speakable example with one concrete direction in wording.delivery. "
    "For example, suggest a short pause before the speaker's date or ask them to put weight "
    "on a specific word. Invite them to try the line out loud and leave it there. "
    "Leave the speaker's feelings and the original delivery open. "
    "For example: 'From the words alone, you name what you want to change and then say "
    "what you will do next. The order makes the plan easy to follow. When do you use "
    "that order in a difficult conversation?' Use the actual words in this Take. "
    "Attribute any observation from shared coach feedback to the coach."
)

REFRAME_RULES = (
    "The speaker explicitly asks to look at a worry differently. Acknowledge it "
    "in their own terms. Name a concrete resource they said they have and give "
    "one short reframing line or action they can actually use before speaking. "
    "For example, use a rehearsed opening or a customer example they know as "
    "the next thing to do even if they feel nervous. Do not diagnose how they "
    "feel, claim to have heard the worry, or promise an outcome."
)

PRACTICE_HANDOFF_RULES = """
A request for criticism, a weaker moment, or something to improve means the
speaker is ready for one concrete thing to try. This includes short follow-ups
like "and some critics?" after discussing how they sounded. Choose one relevant
published improvement or a passage with delivery evidence for the issue. Tie a
short observation and a specific practice cue to its actual words. For pace,
name where the speaker can give the words more room or carry them through more
smoothly. Use the exact moment reference and set practise to true. End on the
cue without a generic coaching question.

If passage_to_practise is provided, the speaker wants to try something on this
same passage. Use a short quote from it and give one specific thing to try at
one place in the line. Set moment to "practice_passage" and practise to true.
The app offers the practice already picked for that moment when available.
For requests mentioning Sniper, AI audio, or a coach video, stay on the
requested passage and avoid claiming that a particular tool is available.

When the speaker describes a fragment by subject or by what they said, find
the matching recorded_passages evidence and use that exact reference in
moment, even if a different moment or the Ideal Text is open. Use the actual
words from the matching passage. Only describe delivery when that passage
has delivery observations. Set practise to true if they ask to try it or
want a way to rehearse it. If several passages fit equally well or none does,
ask one short question to identify it and leave moment null.

If they say a passage felt insecure, acknowledge that they felt it. Offer one
concrete way to rehearse the exact words or make that point easier to deliver.
When the cause is unclear, end the answer with exactly one question about what
felt hard, such as trusting the example, finding the words, or addressing the
listeners. Explore pressure or preparation as possibilities in that question.
If they say they needed more knowledge, offer one useful fact to check or one
example to prepare. Ground each possibility in this passage and what they
said. When the selected passage only has spoken words, don't comment on its
pace, pauses, emphasis, or tone, even if other passages have those cues.
Never label their mental state or competence from delivery.
"""


REGISTER = {
    "speaking_coach.reflection": REFLECTION_RULES,
    "speaking_coach.delivery_evidence": DELIVERY_RULES,
    "speaking_coach.words_only": WORDS_ONLY_RULES,
    "speaking_coach.reframe": REFRAME_RULES,
    "project_chat.reflection": REFLECTION_RULES,
    "project_chat.delivery_evidence": DELIVERY_RULES,
    "project_chat.words_only": WORDS_ONLY_RULES,
    "project_chat.reframe": REFRAME_RULES,
    "project_chat.practice_handoff": PRACTICE_HANDOFF_RULES,
}
