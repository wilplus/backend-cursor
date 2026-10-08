"""V4 B1.6: the V4 picker, dark beside V3 (build plan D-ML-12; founder P1,
P2, P3, V15 A, V15a A, V16a A, QB6 A, QB7 B, H2, S-B1b A)."""
from __future__ import annotations

import pathlib

import pytest

from services import v4_picker as vp
from services import willfidence as wf
from services.data_purge_registry import DEPENDENCIES

ROOT = pathlib.Path(__file__).resolve().parents[1]
UV3 = wf.SOUND_VERSION


def _clip(cid, score, text="we grew forty percent this year", composite=1.0, **snap):
    metrics = {"voice_confidence": {"version": UV3, "score": score},
               "slide_stickiness": {"composite": composite}, **snap}
    return {"id": cid, "transcript": text, "metrics": metrics}


def _block(bid, band, clips, **kw):
    return {"block_id": bid, "delivery_band": band, "snippet_ids": clips,
            "selected_candidate_id": f"relative-confidence:t:{clips[0]}",
            "pieces": [{"snippet_id": c, "start": i * 100, "end": i * 100 + 90}
                       for i, c in enumerate(clips)], **kw}


WEAK, STRONG = "delivery_signal_low", "delivery_signal_high"


def _frame(blocks, rewrite=(), praise=()):
    return {"blocks": blocks, "verbal_lanes": {
        "rewrite_clarity": {"anchors": [{"block_id": b, "candidate_id": f"rw-{b}"} for b in rewrite],
                            "candidates": [{"candidate_id": f"rw-{b}", "document_span": {"start": 105}}
                                           for b in rewrite]},
        "great_formulation": {"anchors": [{"block_id": b, "candidate_id": f"pr-{b}"} for b in praise],
                              "candidates": []},
    }}


def _read(bid, s=0.5, w=0.5, role="main_point"):
    return {"block_id": bid, "s": s, "w": w, "willfident": s * w, "role": role}


def test_allowed_first_praise_only_on_confident_improve_only_on_weak():
    frame = _frame([_block("b1", STRONG, ["c1"]), _block("b2", WEAK, ["c2"], carries_exercise=True),
                    _block("b3", WEAK, ["c3", "c4"]), _block("b4", None, ["c5"])],
                   rewrite=["b3", "b1"], praise=["b1", "b2"])
    kinds = {b["block_id"]: vp.kind_for(b, frame) for b in frame["blocks"]}
    assert kinds == {"b1": "praise", "b2": "exercise", "b3": "rewrite", "b4": None}


def test_rank_is_importance_times_gap_times_sureness():
    clips = [_clip("c1", -0.5), _clip("c2", -0.6)]
    frame = _frame([_block("b1", WEAK, ["c1", "c2"], carries_exercise=True)])
    row = vp.pick_take(frame, clips, [_read("b1", 0.4, 0.5, "evidence")])[0]
    assert row["importance"] == 0.7
    assert row["gap"] == pytest.approx(0.8)
    assert row["strength"] == 1.0
    assert row["rank_score"] == pytest.approx(0.7 * 0.8 * row["sureness"])
    assert row["sureness"] == pytest.approx(row["strength"] * (1 - row["disagreement"]))


def test_the_moment_is_the_clip_with_the_widest_gap():
    clips = [_clip("c1", 0.4), _clip("c2", -0.8, text="um maybe we sort of grew")]
    frame = _frame([_block("b1", WEAK, ["c1", "c2"], carries_exercise=True)])
    assert vp.pick_take(frame, clips, [_read("b1")])[0]["v4_snippet_id"] == "c2"


def test_praise_and_empty_blocks_need_no_moment():
    clips = [_clip("c1", 0.8)]
    frame = _frame([_block("b1", STRONG, ["c1"])], praise=["b1"])
    row = vp.pick_take(frame, clips, [_read("b1", 0.9, 0.9)])[0]
    assert (row["v4_kind"], row["v4_snippet_id"], row["rank_position"], row["picked"]) == (
        "praise", None, None, False)


def test_unsure_blocks_fall_back_to_v3_with_the_reason():
    frame = _frame([_block("b1", WEAK, ["c1", "c2"], carries_exercise=True)], rewrite=["b1"])
    clips = [_clip("c1", None), _clip("c2", None)]  # no sound read: strength 0
    for c in clips:
        c["metrics"]["voice_confidence"] = {}
    row = vp.pick_take(frame, clips, [_read("b1")])[0]
    assert row["fallback"] and row["fallback_reason"] == "unsure"
    assert (row["used_kind"], row["used_snippet_id"]) == (row["v3_kind"], row["v3_snippet_id"])
    assert row["v3_kind"] == "rewrite" and row["v3_snippet_id"] == "c2"  # span 105 sits in c2


@pytest.mark.parametrize("read,reason", [
    ({"block_id": "b1", "s": 0.5, "w": 0.5, "willfident": 0.25, "role": None}, "no_role"),
    ({"block_id": "b1", "s": None, "w": 0.5, "willfident": None, "role": "close"}, "no_read"),
])
def test_missing_role_or_read_falls_back(read, reason):
    frame = _frame([_block("b1", WEAK, ["c1"], carries_exercise=True)])
    row = vp.pick_take(frame, [_clip("c1", -0.5)], [read])[0]
    assert row["fallback_reason"] == reason and row["rank_score"] is None


def test_at_most_three_blocks_are_picked_in_rank_order():
    blocks, clips, reads = [], [], []
    for i in range(5):
        blocks.append(_block(f"b{i}", WEAK, [f"c{i}"], carries_exercise=True))
        clips.append(_clip(f"c{i}", -0.5))
        reads.append(_read(f"b{i}", 0.2 + 0.1 * i, 0.5))
    rows = {r["block_id"]: r for r in vp.pick_take(_frame(blocks), clips, reads)}
    assert [rows[f"b{i}"]["rank_position"] for i in range(5)] == [1, 2, 3, 4, 5]
    assert [rows[f"b{i}"]["picked"] for i in range(5)] == [True, True, True, False, False]


def test_disagreement_is_a_detector_against_the_read(monkeypatch):
    monkeypatch.setattr(vp, "_detector_verdicts", lambda clip: clip["id"] == "c1")
    block = _block("b1", STRONG, ["c1", "c2"])
    strength, disagreement, sure = vp.sureness(block, {"c1": _clip("c1", 0.8), "c2": _clip("c2", 0.8)})
    assert (strength, disagreement) == (1.0, 0.5) and sure == 0.5
    weak = _block("b2", WEAK, ["c1", "c2"])
    _, disagreement, _ = vp.sureness(weak, {"c1": _clip("c1", -0.8), "c2": _clip("c2", -0.8)})
    assert disagreement == 0.5


def test_the_fallback_share_for_the_exit_gate():
    assert vp.fallback_share([{"fallback": True}, {"fallback": False}] * 2 + [{"fallback": False}]) == 0.4
    assert vp.fallback_share([]) is None


def test_the_job_never_raises():
    class Boom:
        def list_v4_willfidence_reads(self, take):
            raise RuntimeError("down")
    assert vp.run(Boom(), "t", {}, []) is None


def test_wiring_and_fences():
    job = (ROOT / "services" / "willfidence.py").read_text()
    assert job.index("record_v4_willfidence_reads(take") < job.index("pick(db, take, frame, snippets)")
    rows = {d.code: d for d in DEPENDENCIES}
    assert rows["v4_picks"].disposition == rows["v4_pick_takes"].disposition == "delete"
    for path in (ROOT / "routes").rglob("*.py"):
        assert "v4_picker" not in path.read_text() and "v4_picks" not in path.read_text(), path
