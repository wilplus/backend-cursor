"""THE Key Moment — one definition, one home (SPEC §17 `key-moment-v1`,
founder ruling 2026-08-14).

WHY THIS MODULE EXISTS
----------------------
"Key moment" was live on five surfaces — the voice game, the feedback page,
the paid key-moment unlock, the breakthrough badge and the breakthroughs
overlay — with NO §17 entry at all, so nothing could say what was being
claimed. Each surface re-derived the rule locally, and two of them disagreed:

  * the game counted ``training_labels.value == 'challenge'`` only;
  * the feedback page and the paywall counted ``'challenge' OR 'threat'``.

So a `threat` moment was simultaneously a key moment behind the paywall and
a WRONG ANSWER in the game. Worse, both rules read the RETIRED
challenge/threat construct, whose coach control was deleted from the FE on
2026-08-07 — freezing the corpus. Every session reviewed after that date
produced zero key moments, on every surface, silently.

THE DEFINITION (§17 `key-moment-v1`)
------------------------------------
A key moment is a moment the COACH JUDGED: a **surfaced** coach draft
carrying a **tag**. The tag's VALUE is the direction, exactly as
challenge/threat were the direction on a labelled moment:

    judged (tag present)   -> a key moment
    tag == 'strong'        -> the POSITIVE direction  (was: 'challenge')
    tag == 'to_work_on'    -> the negative direction  (was: 'threat')

Surfaces take the slice they always took, and now they take it from here:

    the game            -> POSITIVE key moments are the rounds' keys
    feedback + unlock   -> ANY key moment (either direction)

LEGACY VOCABULARY, HONOURED ON THE READ PATH ONLY
-------------------------------------------------
Rows written before the cutover carry a `training_labels` direction instead
of a tag. They are honoured here — the underlying artefact is the same
coach-authored note and video, and dropping them would delete key moments
from arcs a user may already have paid to unlock. NOTHING WRITES THAT
VOCABULARY ANY MORE: this is a read-path vocabulary migration, not a
reinterpretation. A `challenge` label is not a `strong` tag and neither is
re-labelled as the other (SPEC §3.2 — the corpus is versioned, never
rewritten).

FENCES
------
AC-9: this module SELECTS moments and never scores them. The count is never
surfaced, and "no key moments" is never rendered as a verdict on a speaker.
BLIND COACH: a tag is invisible before ``results_published_at`` — publication
is what makes a key moment exist for the student, and that gate lives at the
call sites that serve students (the album already enforces the same rule).

Pure: no DB, no I/O, unit-tested.
"""
from __future__ import annotations

from typing import Any, Optional

# The coach's tag vocabulary — the live one.
POSITIVE_TAG = "strong"
NEGATIVE_TAG = "to_work_on"
TAGS = (POSITIVE_TAG, NEGATIVE_TAG)

# The retired direction vocabulary, read-only. Kept as its own constant so a
# grep for either word lands on this comment rather than on a live rule.
LEGACY_POSITIVE = "challenge"
LEGACY_NEGATIVE = "threat"
LEGACY_DIRECTIONS = (LEGACY_POSITIVE, LEGACY_NEGATIVE)

# ⭐ THE ONE LINE THE FOUNDER'S RULING MOVES.
#
# True  = "judged" — any tag makes it a key moment (strong OR to_work_on),
#         which is what the feedback page and the paywall have always served
#         and the exact analogue of "has a direction label".
# False = only `strong` is a key moment at all.
#
# Either way the GAME keys on the POSITIVE direction only, so this setting
# changes what the feedback page and the unlock serve, never the game.
ANY_TAG_IS_A_KEY_MOMENT = True


def _tag_of(draft: Any) -> Optional[str]:
    if not isinstance(draft, dict):
        return None
    tag = draft.get("tag")
    return tag if isinstance(tag, str) and tag in TAGS else None


def _legacy_of(direction: Any) -> Optional[str]:
    return direction if direction in LEGACY_DIRECTIONS else None


def is_surfaced(draft: Any) -> bool:
    """The coach's explicit push. Nothing reaches a student unsurfaced, and
    that has always been true — it is not part of what changed."""
    return bool(isinstance(draft, dict) and draft.get("surfaced"))


def is_key_moment(draft: Any, *, legacy_direction: Any = None) -> bool:
    """Is this surfaced draft a key moment?

    ``legacy_direction`` is the snippet's ``training_labels.value`` when one
    exists — passed in rather than read here, so this module stays DB-free
    and the retired vocabulary has exactly one entry point.
    """
    if not is_surfaced(draft):
        return False
    tag = _tag_of(draft)
    if tag is not None:
        return True if ANY_TAG_IS_A_KEY_MOMENT else tag == POSITIVE_TAG
    legacy = _legacy_of(legacy_direction)
    if legacy is None:
        return False
    return True if ANY_TAG_IS_A_KEY_MOMENT else legacy == LEGACY_POSITIVE


def is_positive_key_moment(draft: Any, *, legacy_direction: Any = None) -> bool:
    """The POSITIVE direction — "this one was strong".

    The voice game's keys, and the breakthrough badge. A negative key moment
    (`to_work_on`, or a legacy `threat`) is a real judgment and a real key
    moment, but it is not this.
    """
    if not is_surfaced(draft):
        return False
    tag = _tag_of(draft)
    if tag is not None:
        return tag == POSITIVE_TAG
    return _legacy_of(legacy_direction) == LEGACY_POSITIVE


def key_moment_direction(draft: Any, *,
                         legacy_direction: Any = None) -> Optional[str]:
    """``POSITIVE_TAG`` / ``NEGATIVE_TAG`` / None — normalised across both
    vocabularies, so a caller never has to know which era a row came from.
    INTERNAL: never serialize this toward a student (the direction selects,
    it is never shown)."""
    if not is_key_moment(draft, legacy_direction=legacy_direction):
        return None
    tag = _tag_of(draft)
    if tag is not None:
        return tag
    return (POSITIVE_TAG if _legacy_of(legacy_direction) == LEGACY_POSITIVE
            else NEGATIVE_TAG)
