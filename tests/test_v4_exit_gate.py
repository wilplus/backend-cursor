"""V4 BEXIT: the exit-gate report on a fixture (build plan D-ML-16; founder
V21 A, V15a A, O4, O5)."""
from __future__ import annotations

import pathlib

from services import v4_exit_gate as eg

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _passing(**override):
    rises = ({"measured": 120, "rose": 60, "share": 0.5}, {"measured": 150, "rose": 60, "share": 0.4})
    inputs = dict(
        golden={"golden_blocks": 110, "v4_agreement": 0.62, "v3_agreement": 0.55},
        rises=rises,
        coverage=[{"floor_met": True}] * 99 + [{"floor_met": False}],
        practise={"meets_o5": True, "p90_ms": 4100, "tries": 300},
        bar={"status": "calibrated", "bar": 0.58, "answers": 220},
        pick_takes=[{"blocks": 10, "fallback_blocks": 1}] * 20,
    )
    inputs.update(override)
    return inputs


def test_every_line_passing_passes_the_gate():
    report = eg.evaluate(**_passing())
    assert report["passed"] and eg.missing(report) is None
    assert all(line.startswith("PASS") for line in eg.plain_words(report))


def test_too_few_golden_blocks_fail_even_when_v4_leads():
    report = eg.evaluate(**_passing(golden={"golden_blocks": 99, "v4_agreement": 0.9, "v3_agreement": 0.1}))
    assert eg.missing(report) == ["golden_agreement"]


def test_v4_must_beat_v3_on_both():
    tie = eg.evaluate(**_passing(golden={"golden_blocks": 110, "v4_agreement": 0.5, "v3_agreement": 0.5}))
    assert "golden_agreement" in eg.missing(tie)
    behind = ({"measured": 120, "rose": 30, "share": 0.25}, {"measured": 150, "rose": 60, "share": 0.4})
    assert eg.missing(eg.evaluate(**_passing(rises=behind))) == ["next_take_rise"]


def test_falling_back_on_more_than_one_block_in_five_fails():
    report = eg.evaluate(**_passing(pick_takes=[{"blocks": 10, "fallback_blocks": 3}]))
    assert eg.missing(report) == ["stands_on_its_own"]


def test_a_slow_practise_read_or_a_placeholder_bar_fails():
    assert eg.missing(eg.evaluate(**_passing(practise={"meets_o5": False}))) == ["practise_read_p90"]
    assert eg.missing(eg.evaluate(**_passing(bar={"status": "placeholder"}))) == ["reached_bar_calibrated"]


def test_coverage_must_hold():
    report = eg.evaluate(**_passing(coverage=[{"floor_met": True}] * 9 + [{"floor_met": False}]))
    assert eg.missing(report) == ["coverage_holds"]


def test_no_data_is_not_a_pass():
    report = eg.evaluate(golden={"golden_blocks": 0}, rises=eg.rise_lines([], []), coverage=[],
                         practise={}, bar={}, pick_takes=[])
    assert not report["passed"] and len(eg.missing(report)) == 6


def test_the_rise_lines_count_v4s_picks_and_v3s_improvement_picks():
    outcomes = [
        {"take_session_id": "t", "block_id": "b1", "outcome": "rose", "v3_picks": ["rewrite"]},
        {"take_session_id": "t", "block_id": "b2", "outcome": "did_not_rise", "v3_picks": ["exercise"]},
        {"take_session_id": "t", "block_id": "b3", "outcome": "rose", "v3_picks": ["praise"]},
        {"take_session_id": "t", "block_id": "b4", "outcome": "not_measured", "v3_picks": ["rewrite"]},
    ]
    picks = [{"take_session_id": "t", "block_id": "b1", "picked": True},
             {"take_session_id": "t", "block_id": "b3", "picked": True},
             {"take_session_id": "t", "block_id": "b2", "picked": False}]
    v4, v3 = eg.rise_lines(outcomes, picks)
    assert v4 == {"measured": 2, "rose": 2, "share": 1.0}
    assert v3 == {"measured": 2, "rose": 1, "share": 0.5}


def test_the_report_names_how_the_rise_was_measured():
    before = eg.evaluate(**_passing())
    after = eg.evaluate(**_passing(), served_by="v4")
    measured = lambda r: next(x for x in r["lines"] if x["line"] == "next_take_rise")["measured_on"]  # noqa: E731
    assert "would have picked" in measured(before) and "see V4" in measured(after)


def test_nothing_switches_v4_on_and_no_route_reads_it():
    source = (ROOT / "services" / "v4_exit_gate.py").read_text()
    assert "Config." not in source and ".rpc(" not in source and ".insert(" not in source
    for path in (ROOT / "routes").rglob("*.py"):
        assert "v4_exit_gate" not in path.read_text(), path
