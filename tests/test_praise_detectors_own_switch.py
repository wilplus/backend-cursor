"""D-ML-4: the praise detectors get their own switch (QA3 A).

Founder 2026-10-06, Navigation Panel QA3 A: "praise detectors get their own
switch, turned on in a reviewed change"; ledger A045, A053b. Detector praise
(the structural device and the impeccable delivery read) was written only by
the star lane, MOMENT_SUGGESTIONS_ENABLED, default off, so by default no Take
carried a praise naming its cue and most Yes answers showed no card.

`Config.PRAISE_DETECTORS_ENABLED` (default ON in code) now gates only that
praise, independently of the star lane: the worker runs the two detectors on
their own (`moment_suggestions.generate_praise_for_session`) and the read
path stamps their evidence (`tracked_changes._detector_praise_evidence`).
The praise stays Manager-gated (one per block read confident, V3's budget
unchanged), the payload carries no number (AC-9), and where no detector
evidence exists the lane is the Manager's tentative fallback.
"""
from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from services.intervention_candidates import feedback_family_of
from services.take_feedback_manager import (
    ensure_required_families,
    exposure_snapshot,
    strip_internal_evidence,
    verbal_exclusion,
)
from services.take_feedback_policy_v3 import build_service_candidate_frame
from services.take_feedback_policy_v3_service import prepare_v3_service_inventory
from services.tracked_changes import DELIVERY_IMPECCABLE_DETECTOR_VERSION
from tests.test_verbal_lanes_take_document_n48_1 import (
    RECORDING,
    SERVED,
    TAKE,
    _block_of,
    _frame,
    _lane,
    _map,
    _numeric_leaves,
    _placed_document,
    _snippets,
    _tracked,
)

REPO = Path(__file__).resolve().parents[1]
CUES = ["full_volume", "landed_ending"]


def _impeccable(sid: str = "s2b") -> dict:
    """A cue-named impeccable praise row as the read path serves it."""
    [row] = _tracked({"kind": "delivery", "trigger": "impeccable",
                      "cue_keys": CUES}, sid)
    row["feedback_family"] = feedback_family_of(row)
    return row


def _config():
    """The `Config` the code reads at call time. Looked up per test: a test
    elsewhere in the suite may re-import `config`, and patching a stale
    class would then change nothing the code under test sees."""
    return importlib.import_module("config").Config


@pytest.fixture
def lane_off_praise_on():
    config = _config()
    with patch.object(config, "MOMENT_SUGGESTIONS_ENABLED", False), \
            patch.object(config, "PRAISE_DETECTORS_ENABLED", True):
        yield


# ── the switch itself ───────────────────────────────────────────────────────

def _read_flags(env: dict) -> str:
    code = ("from config import Config; "
            "print(Config.PRAISE_DETECTORS_ENABLED, "
            "Config.MOMENT_SUGGESTIONS_ENABLED)")
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, env=env,
                         capture_output=True, text=True, check=True)
    return out.stdout.strip().splitlines()[-1]


def test_the_switch_is_on_when_a_service_never_got_the_variable():
    # CONFIG-FIRST: web, worker or cron without the variable reads it ON;
    # the star lane stays off. Only an explicit "0" turns praise off.
    env = {k: v for k, v in os.environ.items()
           if k not in ("PRAISE_DETECTORS_ENABLED",
                        "MOMENT_SUGGESTIONS_ENABLED")}
    assert _read_flags(env) == "True False"
    assert _read_flags({**env, "PRAISE_DETECTORS_ENABLED": "0"}) == \
        "False False"


def test_the_boot_line_names_both_switches():
    from services.gate_flags import GATE_FLAGS
    assert "PRAISE_DETECTORS_ENABLED" in GATE_FLAGS
    assert "MOMENT_SUGGESTIONS_ENABLED" in GATE_FLAGS


# ── served: detector praise reaches the praise lane, star lane off ──────────

def test_detector_praise_reaches_the_lane_with_the_star_lane_off(
        lane_off_praise_on):
    row = _impeccable()
    assert row["feedback_family"] == "great_formulation"
    assert row["detector_version"] == DELIVERY_IMPECCABLE_DETECTOR_VERSION
    assert row["_manager_evidence"] == {
        "detector": "delivery_impeccable", "cue_count": 2}
    assert verbal_exclusion(row, _map())[0] is None
    frame = _frame([row])
    assert _lane(frame, "great_formulation")["anchors"] == [
        {"block_id": _block_of(frame, 2)["block_id"], "candidate_id": "s2b"}]


def test_a_cue_named_praise_is_served_with_no_number(lane_off_praise_on):
    pool = exposure_snapshot(ensure_required_families(
        SERVED, [_impeccable()], take_session_id=TAKE, snippet_id="s1a",
        document_map=_map()))
    document = _placed_document(parts=True)
    frame = build_service_candidate_frame(
        take_document=document, snippets=_snippets(), suggestions={},
        feedback_candidates=pool, take_index=2,
        expected_recording_id=RECORDING, served_text=SERVED)
    inventory = prepare_v3_service_inventory(
        frame=frame, take_document=document, served_text=SERVED,
        feedback_candidates=pool)
    assert inventory is not None
    praise = [row for row in inventory["visible_rows"]
              if row["feedback_family"] == "great_formulation"]
    assert [row["id"] for row in praise] == ["s2b"]
    [visible] = strip_internal_evidence(praise)
    assert visible["cue_keys"] == CUES
    assert not any(key.startswith("_manager") for key in visible)
    assert "detector_version" not in visible
    assert list(_numeric_leaves(visible)) == []


def test_the_v3_budget_is_unchanged_one_praise_per_confident_block(
        lane_off_praise_on):
    # Two detector praise rows inside the one block read confident: the
    # Manager anchors one, never two; the weak block carries no praise.
    frame = _frame([_impeccable("s2a"), _impeccable("s2b")])
    anchors = _lane(frame, "great_formulation")["anchors"]
    assert len(anchors) == 1
    assert anchors[0]["block_id"] == _block_of(frame, 2)["block_id"]


# ── off: unstamped, excluded, and the lane is the tentative fallback ────────

def test_off_the_praise_stays_excluded_and_the_fallback_is_tentative():
    with patch.object(_config(), "PRAISE_DETECTORS_ENABLED", False):
        row = _impeccable()
    assert "_manager_evidence" not in row
    assert "detector_version" not in row
    assert verbal_exclusion(row, _map())[0] == "missing_evidence_metadata"
    out = ensure_required_families(
        SERVED, [row], take_session_id=TAKE, snippet_id="s1a",
        document_map=_map())
    [fallback] = [r for r in out if r["feedback_family"] == "great_formulation"
                  and (r.get("_manager_evidence") or {}).get("fallback")]
    assert fallback["tentative"] is True
    assert fallback["device"] == "tentative_formulation"


def test_with_detector_praise_no_tentative_fallback_is_added(
        lane_off_praise_on):
    out = ensure_required_families(
        SERVED, [_impeccable()], take_session_id=TAKE, snippet_id="s1a",
        document_map=_map())
    assert not [r for r in out if r["feedback_family"] == "great_formulation"
                and (r.get("_manager_evidence") or {}).get("fallback")]


# ── generated: the worker's praise-only pass ────────────────────────────────

class _Db:
    def __init__(self) -> None:
        self.rows: list[tuple] = []

    def upsert_moment_suggestion(self, snippet_id, arc_id, kind,
                                 replacement_text, why, trigger, *,
                                 emphasis_quote=None, cue_keys=None):
        self.rows.append((snippet_id, kind, replacement_text, why, trigger,
                          cue_keys))
        return True


def _context(snippets: list[dict]):
    from services.moment_suggestions import _GenerationContext
    return _GenerationContext(
        cap=8, sticky_max=0.15, readout={"snippets": snippets},
        metrics_by_id={s["id"]: {"snippet": s["id"]} for s in snippets},
        session={"user_id": "u1"}, audience=None, strategic_context=None,
        confidence_baseline={"baseline": True}, context_document=None,
        decided_keys=set(), intent_keys=set(), take_texts=[])


def test_the_praise_only_pass_writes_only_praise(monkeypatch):
    import services.delivery_cues as cues
    import services.delivery_stars as stars
    import services.moment_suggestions as ms

    snippets = [{"id": "a", "transcript": "We did it.", "features": {}},
                {"id": "b", "transcript": "Not speed, but care.",
                 "features": {}},
                {"id": "c", "transcript": "Plain words here.",
                 "features": {}}]
    monkeypatch.setattr(ms, "_load_generation_context",
                        lambda sid, arc, db: _context(snippets))
    monkeypatch.setattr(stars, "resolve_delivery_baseline",
                        lambda *a, **k: {"f0_sd": (1.0, 0.1)})
    monkeypatch.setattr(stars, "emphasis_z", lambda feats, base: 0.0)
    # Snippet "a" is the one moment read impeccable.
    monkeypatch.setattr(
        cues, "is_impeccable",
        lambda pm, base, confidence_score=None: pm.get("snippet") == "a")
    monkeypatch.setattr(cues, "cue_keys_for_piece",
                        lambda pm, base: list(CUES))

    def _no_issue(*_a, **_k):
        raise AssertionError("the issue detector never runs praise-only")

    monkeypatch.setattr(stars, "detect_delivery_issue", _no_issue)
    monkeypatch.setattr(
        ms, "detect_structural_device",
        lambda transcript, user_id=None: (
            {"device": "contrast", "quote": transcript}
            if transcript.startswith("Not") else None))
    database = _Db()
    stored = ms.generate_praise_for_session("take-1", "arc-1",
                                            database=database)
    assert stored == 2
    assert database.rows == [
        ("a", "delivery", None, None, "impeccable", CUES),
        ("b", "structure", None, "Not speed, but care.", "contrast", None),
    ]


def test_the_praise_only_pass_never_raises(monkeypatch):
    import services.moment_suggestions as ms

    def _boom(*_a, **_k):
        raise RuntimeError("readout unavailable")

    monkeypatch.setattr(ms, "_load_generation_context", _boom)
    assert ms.generate_praise_for_session("take-1", "arc-1",
                                          database=_Db()) == 0


class _Deg:
    def __init__(self) -> None:
        self.stages: list[str] = []

    def run(self, stage, fn, default=None):
        self.stages.append(stage)
        return None


@pytest.mark.parametrize("star, praise, expected", [
    (False, True, ["praise_detectors"]),
    (True, True, []),
    (True, False, []),
    (False, False, []),
])
def test_the_worker_runs_the_praise_pass_only_with_the_star_lane_off(
        monkeypatch, star, praise, expected):
    import services.analysis_worker as worker

    monkeypatch.setattr(worker, "_moment_suggestions_enabled", lambda: star)
    monkeypatch.setattr(worker, "_praise_detectors_enabled", lambda: praise)
    deg = _Deg()
    worker._praise_detectors_alone("take-1", "arc-1", deg)
    assert deg.stages == expected
    # The star lane keeps its own stage in the worker; this pass sits next
    # to it, so a Take never runs both.
    import inspect
    src = inspect.getsource(worker._run_full_analysis_impl)
    assert src.index('_deg.run("moment_suggestions"') < src.index(
        "_praise_detectors_alone(session_id, arc_id, _deg)")
