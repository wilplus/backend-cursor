"""V4 B1.6: the V4 picker, dark beside V3 (build plan D-ML-12; founder P1,
P2, P3, V15 A, V15a A, V16a A, QB6 A, QB7 B, H2, S-B1b A)."""
from __future__ import annotations

from services import v4_picker as vp
from services import willfidence as wf

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


def test_unsure_blocks_fall_back_to_v3_with_the_reason():
    frame = _frame([_block("b1", WEAK, ["c1", "c2"], carries_exercise=True)], rewrite=["b1"])
    clips = [_clip("c1", None), _clip("c2", None)]  # no sound read: strength 0
    for c in clips:
        c["metrics"]["voice_confidence"] = {}
    row = vp.pick_take(frame, clips, [_read("b1")])[0]
    assert row["fallback"] and row["fallback_reason"] == "unsure"
    assert (row["used_kind"], row["used_snippet_id"]) == (row["v3_kind"], row["v3_snippet_id"])
    assert row["v3_kind"] == "rewrite" and row["v3_snippet_id"] == "c2"  # span 105 sits in c2
