"""V4 B1.3: willfidence-v1-machine, the pure rules (build plan D-ML-8;
founder S-B1 A, S-B1b A, V4 A, V5 B, V6 A, W1, W2, H3). The database's
copy is pinned equal in tests/test_the_machine_reads_willfidence_postgres.py.
"""
from __future__ import annotations

from services import willfidence as wf

# ── S (V4 A) ────────────────────────────────────────────────────────────────


# ── Filler and Hedging (S-B1 A, V5 B) ──────────────────────────────────────


# ── Slide fit (S-B1 A) ─────────────────────────────────────────────────────


# ── W, boxes, spread, status (H3, W1, W2) ──────────────────────────────────


# ── the Take's reads ───────────────────────────────────────────────────────

def test_take_reads_send_every_block_with_its_word_signals_only():
    frame = {"blocks": [
        {"block_id": "b1", "snippet_ids": ["c1", "c2"]},
        {"block_id": "b2", "snippet_ids": ["c3"]},
    ]}
    snippets = [
        {"id": "c1", "transcript": "um we grew", "metrics": {
            "slide_stickiness": {"composite": 0.5},
            "voice_confidence": {"version": wf.SOUND_VERSION, "score": 0.9}}},
        {"id": "c2", "transcript": "fast this year", "metrics": {}},
        {"id": "c3", "transcript": "", "metrics": {}},
    ]
    reads = wf.take_reads(frame, snippets, {"b1": {"role": "main_point",
                                                   "holding_together": 1.0}})
    assert [r["block_id"] for r in reads] == ["b1", "b2"]
    assert reads[0]["slide_fit"] == 0.5
    assert reads[0]["role"] == "main_point"
    assert reads[0]["holding_together"] == 1.0
    assert reads[1] == {"block_id": "b2", "filler": None, "hedging": None,
                        "slide_fit": None, "holding_together": None, "role": None}
    # S is the database's to compute from the clips; the app never sends it.
    assert all(not {"s", "w", "willfident"} & set(r) for r in reads)


# ── the one call per Take (S-B1b A) ────────────────────────────────────────


# ── wiring and fences ──────────────────────────────────────────────────────
