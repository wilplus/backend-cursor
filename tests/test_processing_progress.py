"""
STORY    As a speaker waiting for my take, I want the progress bar to move on
         real work and the messages to talk about my take, never a score, so
         that the wait feels alive and honest.
OUTCOME
  O1  Each stage the run's ledger starts moves the bar once, in run order,
      to a strictly higher point between the job's first (5) and last (90)
      coarse emits; a finished stage does not move it again.
  O2  A stage with no position (post-serve, unknown, misspelt) reports
      nothing: the bar is never guessed.
  O3  What the speaker reads while waiting is about their take and names no
      score, rank, percent or number (Never-1).
PROVES   O1 -> test_the_ledger_moves_the_bar_up_on_real_stages_only
         O2 -> test_the_ledger_moves_the_bar_up_on_real_stages_only
         O3 -> test_no_message_names_a_score_a_rank_or_a_number
WHY      Founder 2026-09-19: "it feels like it's stale"; the bar sat still
         from 15 to 55 through the longest part of the run.
"""
from __future__ import annotations

import re

from services.processing_stages import ProcessingStageRecorder

RUN_ORDER = (
    "upload", "transcription", "alignment", "feature_extraction",
    "candidate_generation", "manager_selection", "exposure",
)


def _run(stages) -> list[tuple]:
    """Drive the stage ledger the way the run does; return what the bar got."""
    bar: list[tuple] = []
    recorder = ProcessingStageRecorder(
        database=None, owner_principal_id="", project_id="", take_id="t1",
        progress=lambda stage, percent, message: bar.append((stage, percent, message)))
    for stage in stages:
        if stage == "feature_extraction":
            with recorder.stage(stage):
                pass
        else:
            recorder.record(stage, "running")
            recorder.record(stage, "completed")
    return bar


def test_the_ledger_moves_the_bar_up_on_real_stages_only():
    bar = _run(("upload", "transcription", "alignment", "mystery",
                "feature_extraction", "candidate_generation", "Transcription",
                "manager_selection", "exposure", "human_decisions",
                "derived_state"))
    assert [stage for stage, _p, _m in bar] == list(RUN_ORDER)
    percents = [percent for _s, percent, _m in bar]
    assert percents == sorted(set(percents))
    assert 5 < percents[0] and percents[-1] < 90


def test_no_message_names_a_score_a_rank_or_a_number():
    """These lines are shown to a speaker mid-wait: about their take, never
    about how well they did it."""
    banned = re.compile(
        r"\bscore|\brating|\brank|\bpercent|\bout of\b|\bgrade\b|\d", re.I)
    messages = [message for _s, _p, message in _run(RUN_ORDER)]
    assert len(messages) == len(RUN_ORDER)
    for line in messages:
        assert re.search(r"\byour?\b", line, re.I), line
        assert not banned.search(line), line
        assert line.strip() == line and line.endswith("…")
