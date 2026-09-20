"""Where the wait bar stands, from work that actually happened.

FOUNDER, 2026-09-19: "The loading doesn't show the percentages, it just shows
that it builds and then shows the ideal text — there is no continuity there and
it feels like it's stale."

It was not stale. The run had five progress points across its whole length:

    5   processing_recording   the job starts
    15  transcribing           before the provider call
    55  ideal_text             after the recording is processed
    72  feedback_moments
    90  speaking_anchors

Between 15 and 55 sits ``process_lab_recording`` — transcription, alignment,
acoustics, snippet persistence — which is the LONGEST part of the run and the
widest gap in the bar. Forty points of nothing while the hardest work happens.
Then a jump. A speaker reads a bar that sits still for a minute and then leaps
as broken, and for that speaker it is.

THE FIX IS NOT INTERPOLATION, and `lib/willab/waitProgress.ts` already argued
why: the frontend once advanced the bar on elapsed time against a cap, and the
gate refused it. "The code may call it 'how long we have waited', but 94% on a
screen is read as '94% done', which is a claim nothing here can make." That
file ends by naming the version worth building — "a moving bar needs the
BACKEND to report progress there" — and this is that.

SO EVERY POINT HERE IS A REAL BOUNDARY. `ProcessingStageRecorder` already
wraps the run's canonical stages for the provenance ledger: it is called at
exactly the moments real work starts, with a fixed vocabulary, and it has been
recording them all along without anyone telling the speaker. This maps that
same vocabulary to the bar. Nothing new is measured and nothing is estimated —
the claim is only "this named stage has begun", which is true when it is made.

THE NUMBERS ARE AN ORDERING, NOT A CLOCK. They say how far through the named
sequence the run is, not how long is left. That is the honest reading of a
progress bar built this way, and it is why a stage that takes ten seconds and
one that takes ninety can sit the same distance apart.

INTERLEAVED WITH THE EXISTING EMITS ON PURPOSE. Every value below falls
between the two coarse points that bracket it, so the two sources compose into
one ascending ladder rather than fighting. The frontend holds the last real
percent and never lowers it (`nextWaitPercent`), so even an out-of-order stage
cannot make the bar fall — but the ladder is built not to need that.

AC-9 is not in play: this is a number about a job, never about a speaker.
"""
from __future__ import annotations

from typing import Optional

# The canonical stage vocabulary lives in `processing_stages.CANONICAL_STAGES`;
# this is where each one sits on the bar. A stage absent here reports nothing
# rather than guessing — see `percent_for_stage`.
#
#   10  upload               fetching the audio object
#   20  transcription        the provider call, the single longest step
#   35  alignment            words -> slides, the two-clocks boundary
#   45  feature_extraction   per-piece acoustics
#   65  candidate_generation detectors propose
#   78  manager_selection    arbitration picks what surfaces
#   85  exposure             the chosen items are written for serving
#
# `human_decisions` and `derived_state` are deliberately absent: they happen
# after the speaker is already looking at the document, so a bar position for
# them would describe a wait nobody is having.
STAGE_PERCENT: dict[str, int] = {
    "upload": 10,
    "transcription": 20,
    "alignment": 35,
    "feature_extraction": 45,
    "candidate_generation": 65,
    "manager_selection": 78,
    "exposure": 85,
}

# What the speaker reads while each stage runs. Plain, present tense, about
# their take rather than the machinery — the same register as the existing
# "Transcribing your take…" and "Building your Ideal Text…".
STAGE_MESSAGE: dict[str, str] = {
    "upload": "Loading your recording…",
    "transcription": "Transcribing your take…",
    "alignment": "Matching your words to your slides…",
    "feature_extraction": "Listening to how you said it…",
    "candidate_generation": "Looking for your strongest moments…",
    "manager_selection": "Choosing what is worth showing you…",
    "exposure": "Putting your feedback together…",
}


def percent_for_stage(stage: str) -> Optional[int]:
    """Where this named stage sits on the bar, or None if it has no position.

    None is the honest answer for a stage with no mapping — a new stage, a
    misspelling, a post-serve stage nobody is waiting on. The caller reports
    nothing rather than inventing a position, which keeps the rule from this
    module's header: the bar moves on real boundaries or not at all.
    """
    if not isinstance(stage, str):
        return None
    return STAGE_PERCENT.get(stage.strip())


def message_for_stage(stage: str) -> Optional[str]:
    """The line shown while this stage runs, or None to leave it unchanged."""
    if not isinstance(stage, str):
        return None
    return STAGE_MESSAGE.get(stage.strip())
