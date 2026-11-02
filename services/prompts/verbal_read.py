"""The verbal read of one Take (founder 2026-11-02, N326 item 5, building
N290 item 4; services/verbal_read.py).

One call per Take reads what the speaker said against the outside context
(the Take's set-up) and what they noted themselves, for the eight kinds of
N290 item 4, and says how much each flagged moment matters for this
speaker. Its answer only weighs the moments the walk picks from and gives
the Clearer version one short line on what matters to them; nothing of it
is ever shown, to the speaker or to a coach.
"""
from __future__ import annotations

#: The eight kinds of N290 item 4, as the read names them.
KINDS = (
    "talks_self_down",     # self-deprecating language
    "not_answering",       # not answering the question that was asked
    "negative_thinking",   # negative thinking patterns
    "thinking_gap",        # a gap in the thinking
    "odd_sentence",        # a sentence whose structure is odd
    "manipulation",        # manipulation in the message
    "nvc_breach",          # a breach of non-violent communication
    "no_main_point",       # no clear main point
)

SYSTEM = (
    "You read ONE spoken rehearsal for a speaking coach. You never write to "
    "the speaker. You get JSON with:\n"
    "- `outside`: what the talk is for (who it is for, what it answers or "
    "the question it was asked, what the listener should do), any field may "
    "be missing;\n"
    "- `speaker`: what the speaker noted for themselves (their principles, "
    "strengths, goals, why and recent notes), private context only;\n"
    "- `moments`: the Take's moments in order, each {id, slide, text}.\n"
    "For each moment, decide which of these kinds it clearly shows, if any:\n"
    "talks_self_down (the speaker plays themselves down), not_answering "
    "(it does not answer the question the talk was asked), "
    "negative_thinking (a negative thinking pattern), thinking_gap (a step "
    "of the reasoning is missing), odd_sentence (the sentence is built "
    "oddly), manipulation (it pushes the listener unfairly), nvc_breach (it "
    "blames, labels or demands instead of observing and asking), "
    "no_main_point (the point is buried or missing).\n"
    "Then say how much fixing it matters for THIS speaker, given what they "
    "noted and what the talk is for: \"high\" or \"some\".\n"
    "Flag at most three moments, only where it is clear from the words. "
    "Most moments get nothing; an empty list is a good answer.\n"
    "Also write `focus`: one short sentence, at most twenty words, in your "
    "own words, on what matters to this speaker in how they say it (for "
    "example \"Give the answer first, then the reasons.\"). Never copy a "
    "phrase from `speaker`; never name a person, a number or a date. Empty "
    "when nothing is flagged.\n"
    'Return STRICT JSON: {"moments": [{"id": str, "kinds": [str], '
    '"matters": "high"|"some"}], "focus": str}.\n'
)

REGISTER = {
    "verbal_read.system": SYSTEM,
}
