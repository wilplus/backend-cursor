"""The wait bar moves on work that actually happened.

FOUNDER, 2026-09-19: "The loading doesn't show the percentages, it just shows
that it builds and then shows the ideal text — there is no continuity there and
it feels like it's stale."

The run reported five points across its whole length, and the widest gap — 15
to 55 — was `process_lab_recording`, the longest part of it. Forty points of
nothing while the hardest work happened, then a jump.

The fix is NOT interpolation. `lib/willab/waitProgress.ts` already settled
that: elapsed time against a cap reads as "94% done", which is a claim nothing
can make. It named the version worth building — the backend reporting real
boundaries — and these tests hold that line.
"""
from __future__ import annotations

import pytest

from services.processing_progress import (
    STAGE_MESSAGE,
    STAGE_PERCENT,
    message_for_stage,
    percent_for_stage,
)
from services.processing_stages import CANONICAL_STAGES, ProcessingStageRecorder


# ── the ladder ─────────────────────────────────────────────────────────────


def test_every_position_names_a_real_canonical_stage():
    """A position for a stage that does not exist is a position nothing can
    ever reach — a bar that promises a step the run will never take."""
    assert set(STAGE_PERCENT) <= CANONICAL_STAGES
    assert set(STAGE_MESSAGE) == set(STAGE_PERCENT)


def test_the_long_silence_is_where_the_new_points_are():
    """The defect was the gap between 15 (transcribing) and 55 (ideal_text).

    That stretch is transcription, alignment and acoustics — the longest part
    of the run and the emptiest part of the bar. If the new points do not land
    inside it, this change has not fixed what the founder reported.
    """
    inside = [name for name, at in STAGE_PERCENT.items() if 15 < at < 55]
    assert set(inside) == {"transcription", "alignment", "feature_extraction"}


def test_the_ladder_only_ever_climbs():
    """Interleaved with the coarse emits (5, 15, 55, 72, 90) so the two
    sources compose into one ascending sequence rather than fighting."""
    coarse = [5, 15, 55, 72, 90]
    ladder = sorted([*coarse, *STAGE_PERCENT.values()])
    assert ladder == sorted(set(ladder)), "two points share a position"
    assert ladder[0] >= 0 and ladder[-1] <= 100


@pytest.mark.parametrize(("stage", "at"), sorted(STAGE_PERCENT.items()))
def test_each_position_is_a_sane_percent(stage, at):
    assert isinstance(at, int) and not isinstance(at, bool)
    assert 0 < at < 100, stage


def test_post_serve_stages_have_no_position():
    """`human_decisions` and `derived_state` happen after the speaker is
    already reading their document. A bar position for them would describe a
    wait nobody is having."""
    assert percent_for_stage("human_decisions") is None
    assert percent_for_stage("derived_state") is None


# ── the lookups refuse to guess ────────────────────────────────────────────


@pytest.mark.parametrize("stage", [
    "", "   ", "unknown_stage", "TRANSCRIPTION", None, 7, [], {},
])
def test_an_unmapped_stage_reports_nothing(stage):
    """None is the honest answer, and the caller then says nothing at all.
    Guessing a position for a stage nobody placed is the invented percentage
    this whole design exists to avoid."""
    assert percent_for_stage(stage) is None
    assert message_for_stage(stage) is None


def test_surrounding_whitespace_still_resolves():
    assert percent_for_stage("  alignment  ") == STAGE_PERCENT["alignment"]
    assert message_for_stage("  alignment  ") == STAGE_MESSAGE["alignment"]


def test_no_message_names_a_score_a_rank_or_a_number():
    """AC-9 lives elsewhere, but these lines are shown to a speaker mid-wait
    and the register has to match the rest: about their take, never about how
    well they did it."""
    import re
    banned = re.compile(
        r"\bscore|\brating|\brank|\bpercent|\bout of\b|\bgrade\b", re.I)
    for line in STAGE_MESSAGE.values():
        assert not banned.search(line), line
        assert line.strip() == line and line.endswith("…")


# ── the bridge from the ledger to the bar ──────────────────────────────────


class _Ledger:
    def __init__(self, raises=False):
        self.raises = raises
        self.rows: list[tuple] = []

    def record_canonical_processing_stage(self, **kwargs):
        if self.raises:
            raise RuntimeError("ledger is down")
        self.rows.append((kwargs["stage"], kwargs["status"]))
        return {"id": "row"}


def _recorder(ledger, seen, **kwargs):
    return ProcessingStageRecorder(
        database=ledger,
        owner_principal_id="owner-1",
        project_id="project-1",
        take_id="take-1",
        progress=lambda stage, percent, message: seen.append(
            (stage, percent, message)),
        **kwargs,
    )


def test_a_running_stage_moves_the_bar():
    seen: list[tuple] = []
    recorder = _recorder(_Ledger(), seen)
    with recorder.stage("alignment"):
        pass
    assert seen == [(
        "alignment", STAGE_PERCENT["alignment"], STAGE_MESSAGE["alignment"],
    )]


def test_it_reports_once_per_stage_not_on_the_terminal_writes():
    """Three ledger writes, one bar move. A bar that ticks on 'succeeded'
    too would advance twice for one piece of work."""
    seen: list[tuple] = []
    ledger = _Ledger()
    recorder = _recorder(ledger, seen)
    with recorder.stage("transcription"):
        pass
    assert [row[1] for row in ledger.rows] == ["running", "succeeded"]
    assert len(seen) == 1


def test_a_failing_stage_still_reported_its_start_and_still_raises():
    seen: list[tuple] = []
    recorder = _recorder(_Ledger(), seen)
    with pytest.raises(ValueError):
        with recorder.stage("feature_extraction"):
            raise ValueError("the work failed")
    # The speaker saw the stage begin, which was true when it was said.
    assert len(seen) == 1


def test_the_ready_wave_path_moves_the_bar_too():
    """`run_ready_stages` drives the three longest stages and calls `record`
    directly — it never touches `stage()`. If the hook lived only in the
    context manager, the longest part of the run would stay dark, which is
    exactly the defect."""
    seen: list[tuple] = []
    recorder = _recorder(_Ledger(), seen)
    recorder.record("transcription", "running")
    recorder.record("transcription", "succeeded")
    assert [row[0] for row in seen] == ["transcription"]


def test_a_ledger_that_cannot_write_still_moves_the_bar():
    """A legacy row with no canonical ownership disables the ledger. That is
    no reason to leave the speaker watching a frozen bar."""
    seen: list[tuple] = []
    recorder = ProcessingStageRecorder(
        database=None, owner_principal_id="", project_id="", take_id="",
        progress=lambda stage, percent, message: seen.append(stage),
    )
    assert recorder.enabled is False
    recorder.record("alignment", "running")
    assert seen == ["alignment"]


def test_an_unmapped_canonical_stage_says_nothing():
    seen: list[tuple] = []
    recorder = _recorder(_Ledger(), seen)
    recorder.record("derived_state", "running")
    recorder.record("human_decisions", "running")
    assert seen == []


def test_a_broken_progress_callback_cannot_break_the_run():
    """Same rule as `_emit` in the analysis worker: a cosmetic fault must
    never stop record -> process -> Ideal Text (LIVE LOOP)."""
    ledger = _Ledger()

    def boom(*_args):
        raise RuntimeError("the bar is down")

    recorder = ProcessingStageRecorder(
        database=ledger, owner_principal_id="owner-1",
        project_id="project-1", take_id="take-1", progress=boom,
    )
    with recorder.stage("alignment"):
        pass
    # The ledger still got both writes; the failure went to the log.
    assert [row[1] for row in ledger.rows] == ["running", "succeeded"]


def test_no_callback_behaves_exactly_as_before():
    ledger = _Ledger()
    recorder = ProcessingStageRecorder(
        database=ledger, owner_principal_id="owner-1",
        project_id="project-1", take_id="take-1",
    )
    with recorder.stage("upload"):
        pass
    assert [row[1] for row in ledger.rows] == ["running", "succeeded"]
