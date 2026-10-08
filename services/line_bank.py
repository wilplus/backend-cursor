"""Signed lines the app may say after praise, a clearer version, or a practise try.

The source of truth is ``docs/SIGNED-line-bank-2026-10-06.md`` (founder
2026-10-06, decisions log N54). A line not in that file does not ship.
Rotation (never the same line twice in a row within a bank) and the
"later only when true, from Take 2 on" rule belong to the caller. No
number other than the Take number ever appears (AC-9). The test
``tests/test_line_bank.py`` holds parity.
"""

from __future__ import annotations

from typing import Final

TAKE_PLACEHOLDER: Final = "{n}"

PRAISE_BANKS: Final[tuple[str, ...]] = (
    "B01",
    "B02",
    "B03",
    "B04",
    "B05",
    "B06",
    "B07",
    "B08",
    "B09",
)
CLEARER_BANKS: Final[tuple[str, ...]] = ("B10", "B11", "B12", "B13", "B14")
PRACTISE_BANKS: Final[tuple[str, ...]] = ("NX3a", "CM3b")

# Bullet text after "- ", byte-identical to the signed markdown. A "Later:"
# bullet is not a sayable line; it lives in LATER.
BANKS: Final[dict[str, tuple[str, ...]]] = {
    "B01": (
        "Sounded more confident than usual!",
        "You sounded more sure of yourself than usual!",
        "There it is: more confidence than usual!",
        "That came out bold and sure. More than usual!",
        "You sounded like you really believed it this time!",
    ),
    "B02": (
        "Your voice danced up and down. That kept it alive!",
        "No flat line here: your voice went up and down and pulled me in!",
        "Your voice had real melody. It sounded alive!",
        "Up and down, like music. That's how a confident voice moves!",
    ),
    "B03": (
        "You made some words loud and some soft. That gave it shape!",
        "You pushed the big words and let the small ones rest. Great!",
        "Loud where it mattered, soft where it didn't. That landed!",
        "Your volume moved with your meaning. Very strong!",
    ),
    "B04": (
        "You kept going without stopping. It flowed like a river!",
        "Hardly any stops. You just kept talking, sure of yourself!",
        "Smooth and steady, no stumbling. That sounded confident!",
        "You didn't stop to search for words. You just knew!",
    ),
    "B05": (
        "This delivery was calm and steady",
        "Calm and grounded. Your voice sat low and steady here!",
        "Your voice was calm and smooth. It sounded like you were in charge!",
        "Nice and steady. Nothing could shake you here!",
        "Grounded and calm, like someone who knows exactly what they mean.",
    ),
    "B06": (
        "You weren't rushing, but your pace was good and rhythmic. This part sounded confident and right on time.",
        "Good rhythm! You kept your pace and didn't drag.",
        "Right on time: no rushing, no dragging, just the right pace!",
        "Your pace held steady all through this part. Confident!",
        "You moved like a clock here: steady and sure!",
    ),
    "B07": (
        "That was great. You weren't asking me, you were simply saying what you mean. At the end you were just saying it straight!",
        "You ended it like a statement, not a question. Straight and sure!",
        "No question mark at the end. You just said it!",
        "You landed the ending. It sounded like you meant every word!",
        "You finished strong, like you were sure of it!",
    ),
    "B08": (
        "The energy at the beginning was great. It was like the North Star of your presentation.",
        "What a start! That energy set the tone for what came after.",
        "You came in with energy from the very first word!",
        "Strong opening! That energy pulls people right in.",
        "You started with fire. Everyone would want to keep listening!",
    ),
    "B09": (
        "Wow, it was one of the most confident moments of your presentation",
        "This was one of your more confident moments. There's more in you!",
        "Good moment! You're heading the right way.",
        "This one sounded surer. Keep building on it!",
        "I can hear your confident voice starting to come through here!",
    ),
    "B10": (
        "Say what you mean. Don't dance around it, just say it straight.",
        "Skip the warm-up. Go straight to your point!",
        "Start with what matters. No run-up needed!",
        "Get right to it. Your point is strong enough on its own.",
        "Drop the extra words and say the thing. It hits harder!",
    ),
    "B11": (
        "Try saying it as two short sentences, with a small pause between.",
        "Two short sentences land better than one long one.",
        "Break it in two and pause in the middle.",
        "Two short sentences hit harder than one long one. Try it!",
        "Cut it in two and take a breath between. Let each part land!",
        "Say the first part, pause, then the second. Much clearer!",
        "Give each idea its own sentence. People can follow you easily!",
    ),
    "B12": (
        "Don't cut it into pieces. Say it as one whole thing, so it lands all together and makes an impact.",
        "Keep it in one go, so the idea hits all at once.",
        "One sentence, one breath. Let it land together!",
        "Don't break it up. Say it whole and it lands harder.",
        "Put the pieces together so your idea comes out as one strong thought!",
    ),
    "B13": (
        "Here is a slightly more polished option:",
        "Here's a clearer way to say it:",
        "Try it this way:",
        "Here's a way to say it even clearer:",
        "Try saying it like this:",
        "This version might land even better:",
        "Here's a stronger way to say it:",
    ),
    "B14": (
        "Do you accept and want to practise it?",
        "Want to take it and practise?",
        "Shall we practise this version?",
        "Do you want to try saying it this way?",
        "Shall we practise this one together?",
        "Ready to practise this version?",
        "Want to give this version a go?",
    ),
    "NX3a": (
        "Let's try it once more. I have another practice for you!",
        "Let's give it another go. I have one more practice for you!",
        "Not quite yet. Here's another practice to try!",
        "Keep going! I have another practice for you to try.",
    ),
    "CM3b": (
        "Great effort! Let's move on and come back to this one later.",
        "Thanks for giving it your all. On to the next step!",
        "You worked hard on this one. Let's keep going!",
        "Nice persistence! We'll move on for now.",
    ),
}

# Text after "Later: " for B01-B09. {n} stays literal until the caller fills it.
# B09's signed later line names no earlier Take, so it has no placeholder.
LATER: Final[dict[str, str]] = {
    "B01": "This sounded more confident than on Take {n}.",
    "B02": "Your voice moved more here than on Take {n}.",
    "B03": "You used loud and soft more than on Take {n}.",
    "B04": "Fewer stops here than on Take {n}.",
    "B05": "Your voice sat lower than on Take {n}. It sounded calm.",
    "B06": "You kept your pace better than on Take {n}.",
    "B07": "Your ending came down more than on Take {n}.",
    "B08": "You started with more energy than on Take {n}.",
    "B09": "This keeps getting surer. Keep going.",
}

# Cue keys are the ones services/delivery_cues.py emits for the confident
# direction, plus the two reads (confident with no single named cue, and
# tentative when no single cue stands out).
CUE_BANK: Final[dict[str, str]] = {
    "wide_range": "B02",
    "full_volume": "B03",
    "no_hesitation": "B04",
    "settled_pitch": "B05",
    "kept_moving": "B06",
    "landed_ending": "B07",
    "opened_strong": "B08",
    "confident": "B01",
    "tentative": "B09",
}


def line(bank: str, index: int) -> str:
    """Return one signed line. No wrap: a bad index is a caller bug, not a rotation."""
    return BANKS[bank][index]


def later_line(bank: str, take: int) -> str:
    """Fill the Take number into a signed later-line.

    The caller decides whether the comparison is true and whether this is
    from Take 2 on. This only refuses a Take that cannot name an earlier one.
    """
    if take < 1:
        raise ValueError("a later line names an earlier Take, so take must be >= 1")
    return LATER[bank].replace(TAKE_PLACEHOLDER, str(take))


def bank_for_cue(cue: str | None) -> str:
    """Map a confident-delivery cue to its praise bank.

    An unknown or missing cue gets B09, the gentle general line, never an invented one.
    """
    return CUE_BANK.get(cue or "", "B09")
