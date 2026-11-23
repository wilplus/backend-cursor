"""Shared rules for grounded reflections on a recording in both coaching chats."""

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
    "When an action would help, offer "
    "one small rehearsal tied to that moment. For a practice request, use the "
    "reviewed exercise if supplied and ask a specific question about the habit. "
    "When the speaker names something that helps them face this moment, "
    "include it in their own terms. A speaker who says prayer gives them "
    "support can be asked how that support helps them take their stated "
    "next step. Attribute quoted beliefs to the person who expressed them.\n\n"
)

DELIVERY_RULES = (
    "Open a reflection or answer about delivery with a short exact phrase from "
    "the passage and the listener's impression from its actual cue. Use everyday "
    "phrases such as 'a firmer ending' or "
    "'quicker emphasis on that phrase' ('szybsze podkreślenie' in Polish). "
    "A recorded description that names a word supports "
    "a cue on that word. A measurement for a whole passage supports a cue about the "
    "passage as a whole. Describe the effect directly, such as a request coming out "
    "in one breath or a request having room to be heard. If you suggest a pause or "
    "emphasis to try, mark it as a suggestion. When the speaker goes from an obstacle to a concrete "
    "action, show that move. Give the impression with its cue, then acknowledge "
    "their actual commitment, such as what they say they'll do tomorrow. "
    "Recognize any support they name and end by asking what helps them act. "
    "Include the delivery passage's evidence reference when you use its cue. "
    "Never invent a coach comment or a delivery observation. "
    "Example of the style, for a recording with a firmer repetition and faster "
    "emphasis on the closing phrase. Mocniejsze drugie „Nie chcę” oraz szybsze "
    "podkreślenie „że się nie uda” brzmią, jakbyś miał już dość tego wewnętrznego "
    "głosu. Chwilę później mówisz „Jutro powiem wprost, czego potrzebuję”. "
    "Słyszę, że coś pomaga ci się temu głosowi przeciwstawić. Skąd bierzesz tę "
    "wewnętrzną siłę? "
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


REGISTER = {
    "speaking_coach.reflection": REFLECTION_RULES,
    "speaking_coach.delivery_evidence": DELIVERY_RULES,
    "speaking_coach.words_only": WORDS_ONLY_RULES,
    "project_chat.reflection": REFLECTION_RULES,
    "project_chat.delivery_evidence": DELIVERY_RULES,
    "project_chat.words_only": WORDS_ONLY_RULES,
}
