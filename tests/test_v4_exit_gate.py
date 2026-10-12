"""V4 BEXIT: the exit-gate report on a fixture (build plan D-ML-16; founder
V21 A, V15a A, O4, O5)."""
from __future__ import annotations

from services import v4_exit_gate as eg


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
