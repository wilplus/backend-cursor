"""
STORY    As a speaker, I want praise for good delivery or structure to show
         even when the star lane is off, so that my Yes answers come with a
         card naming what I did well.
OUTCOME
  O1  With PRAISE_DETECTORS_ENABLED on (star lane off), detector praise is
      stamped, competes in the praise lane, and is served with its cue keys
      and no number (Never-1: no scores shown to speakers).
  O2  With it off, the detector praise is excluded and the lane falls back
      to the Manager's tentative praise.
  O3  The worker's praise-only pass writes only praise rows, never an issue.
PROVES   O1 -> test_switch_on_serves_detector_praise_without_numbers,
               test_with_detector_praise_no_tentative_fallback_is_added
         O2 -> test_switch_off_excludes_detector_praise_and_falls_back
         O3 -> test_the_praise_only_pass_writes_only_praise
WHY      Founder 2026-10-06, QA3 A: praise detectors get their own switch.
"""
from __future__ import annotations

import importlib
from unittest.mock import patch

import pytest

from services.intervention_candidates import feedback_family_of
from services.take_feedback_manager import (
    TakeDocumentMap,
    ensure_required_families,
    strip_internal_evidence,
    verbal_exclusion,
)
from services.tracked_changes import build_tracked_changes
from services.transcript_document import relocate_pieces
from tests.test_verbal_lanes_take_document_n48_1 import (
    DOC,
    SERVED,
    TAKE,
    _placed_document,
)

CUES = ["full_volume", "landed_ending"]


def _map() -> TakeDocumentMap:
    return TakeDocumentMap.for_document(_placed_document(), SERVED, take_id=TAKE)


def _tracked(suggestion: dict, sid: str) -> list[dict]:
    pieces = relocate_pieces(SERVED, DOC["pieces"], paragraph_fallback=True,
                             slide_regions={})
    return build_tracked_changes(SERVED, pieces, {sid: suggestion})


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


@pytest.fixture
def praise_off():
    config = _config()
    with patch.object(config, "MOMENT_SUGGESTIONS_ENABLED", False), \
            patch.object(config, "PRAISE_DETECTORS_ENABLED", False):
        yield


def _tentative(rows: list[dict]) -> list[dict]:
    return [r for r in rows if r["feedback_family"] == "great_formulation"
            and (r.get("_manager_evidence") or {}).get("fallback")]


def _numbers(value, top=True):
    """Every number outside the location coordinates the client reads."""
    if isinstance(value, dict):
        for key, item in value.items():
            if not (top and key in ("span", "evidence")):
                yield from _numbers(item, False)
    elif isinstance(value, list):
        for item in value:
            yield from _numbers(item, False)
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        yield value


# ── on: stamped, competing, served with its cues and no number ─────────────

def test_switch_on_serves_detector_praise_without_numbers(lane_off_praise_on):
    praise = _impeccable()
    assert verbal_exclusion(praise, _map())[0] is None
    [served] = strip_internal_evidence([praise])
    assert served["cue_keys"] == CUES and served["quote"]
    assert served["feedback_family"] == feedback_family_of(praise)
    assert list(_numbers(served)) == []
    assert not any(key.startswith("_manager_") or key == "detector_version"
                   for key in served)


def test_with_detector_praise_no_tentative_fallback_is_added(
        lane_off_praise_on):
    out = ensure_required_families(
        SERVED, [_impeccable()], take_session_id=TAKE, snippet_id="s1a",
        document_map=_map())
    assert out[0]["cue_keys"] == CUES
    assert not _tentative(out)


# ── off: excluded, and the lane is the tentative fallback ──────────────────

def test_switch_off_excludes_detector_praise_and_falls_back(praise_off):
    praise = _impeccable()
    assert verbal_exclusion(praise, _map())[0] == "missing_evidence_metadata"
    out = ensure_required_families(
        SERVED, [praise], take_session_id=TAKE, snippet_id="s1a",
        document_map=_map())
    [fallback] = _tentative(out)
    assert fallback["quote"] in SERVED and fallback["tentative"] is True


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
