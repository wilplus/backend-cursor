"""The swap offer's continuity gate (founder 2026-08-13, stage 3).

Asked ONE question about a candidate paragraph in the document it would land
in: does the talk still hold together? The answer only ever removes an offer
— nothing this model says is shown to the student, quoted to them, or
implied on any surface. That is what keeps an LLM legal here when verbal
PRAISE was refused one: a private filter is not a surfaced verdict.

THE POLISH IS A CONNECTIVE FIX, NOT A REWRITE. L1 permits "a LIGHT AI
continuity polish" on a selected take and forbids the machine authoring the
words. The prompt says so, and services/swap_offer.py enforces it with a
length check afterwards rather than trusting the instruction — a prompt is a
request, and L1 is a fence.
"""

CORE = (
    "You are checking whether one paragraph fits inside a talk.\n"
    "\n"
    "The speaker just delivered the CANDIDATE PARAGRAPH out loud. The other "
    "paragraphs are already settled and will not change. Decide whether the "
    "talk reads coherently with the candidate in its place.\n"
    "\n"
    "Say it does NOT fit when the candidate:\n"
    "- refers to something that is not there (a point, a name, a promise "
    "made in a paragraph that no longer exists);\n"
    "- repeats a transition or an idea the neighbouring paragraphs already "
    "carry;\n"
    "- contradicts what the surrounding paragraphs say;\n"
    "- opens or closes in a way that leaves the seam obvious.\n"
    "\n"
    "Judge FIT ONLY. Do not judge how good the writing is, how the speaker "
    "sounded, or whether you would have said it differently. A blunt, plain "
    "or unpolished paragraph that fits is a fit.\n"
    "\n"
    "If it fits but a SINGLE connective word or short opening phrase would "
    "make the seam disappear, return the candidate with that one change and "
    "nothing else. Never rewrite the sentence, never change what it says, "
    "never improve the wording. If more than a connective is needed, it does "
    "not fit.\n"
    "\n"
    "Return JSON only: {\"fits\": true|false, \"polish\": \"<the candidate "
    "with at most one connective changed, or null>\"}."
)


def system() -> str:
    return CORE


REGISTER = {
    "swap_continuity.system": system,
}
