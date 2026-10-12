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
from unittest.mock import patch

import pytest

from services.intervention_candidates import feedback_family_of
from services.take_feedback_manager import (
    ensure_required_families,
)
from tests.test_verbal_lanes_take_document_n48_1 import (
    SERVED,
    TAKE,
    _map,
    _tracked,
)

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


# ── served: detector praise reaches the praise lane, star lane off ──────────


# ── off: unstamped, excluded, and the lane is the tentative fallback ────────


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
