"""willab — the VARIANT POOL + COMPOSITIONS (founder 2026-08-03).

Pinned here: every mapped segment of a take pools, losers and displaced
offers included; compositions are append-only revisions + a head pointer.
The picker, select, restore and user-edit capture were deleted 2026-09-29
with their tests: nothing had called them since audit C2 retired the master
document.

Run: python3 -m unittest tests.test_ideal_text_variants
"""
from __future__ import annotations

import unittest

from services.ideal_text_variants import (
    capture_take_variants,
    snapshot_composition,
)

ARC = "a1"
T1 = "take-1-sess"
T2 = "take-2-sess"
T3 = "take-3-sess"


class _Db:
    """Fake db: blocks + the pool + compositions + head, recording every
    write. Mirrors the real helpers' contracts (None on read-fail,
    duplicate take-variant insert → None, append-only revisions)."""

    def __init__(self, *, blocks=None):
        self.blocks = {(b["arc_id"], b["block_key"]): dict(b)
                       for b in (blocks or [])}
        self.variants = []            # rows with generated ids
        self.compositions = {}        # (arc, revision) -> row
        self.head = {}                # arc -> revision
        self._next_id = 0
        self.blocks_fail = False
        self.writes = []

    @property
    def ideal_text(self):
        # audit Q-A2: production now calls database.ideal_text.<method>();
        # this fake implements those methods directly on itself.
        return self

    # blocks (same shapes as test_master_document's fake)
    def list_ideal_text_blocks(self, arc_id):
        if self.blocks_fail:
            return None
        return sorted((dict(v) for k, v in self.blocks.items()
                       if k[0] == str(arc_id)),
                      key=lambda r: r["block_key"])

    def get_ideal_text_block(self, arc_id, block_key):
        row = self.blocks.get((str(arc_id), block_key))
        return dict(row) if row else None

    def upsert_ideal_text_block(self, arc_id, block_key, fields):
        key = (str(arc_id), block_key)
        row = self.blocks.get(key) or {
            "arc_id": str(arc_id), "block_key": block_key,
            "active": True, "rejected_take_session_ids": [],
            "status": "settled"}
        row.update(fields)
        self.blocks[key] = row
        self.writes.append((block_key, dict(fields)))
        return True

    # the pool
    def insert_ideal_text_block_variant(self, arc_id, block_key, fields):
        if fields.get("source_kind") == "take":
            for v in self.variants:
                if v["arc_id"] == str(arc_id) \
                        and v["block_key"] == block_key \
                        and v["source_kind"] == "take" \
                        and v.get("take_session_id") == \
                        fields.get("take_session_id"):
                    return None          # the partial unique index
        self._next_id += 1
        row = dict(fields, arc_id=str(arc_id), block_key=block_key,
                   id=f"v{self._next_id}",
                   created_at=f"2026-08-03T00:00:{self._next_id:02d}Z")
        self.variants.append(row)
        return dict(row)

    def list_ideal_text_block_variants(self, arc_id):
        return [dict(v) for v in self.variants
                if v["arc_id"] == str(arc_id)]

    def get_ideal_text_block_variant(self, arc_id, variant_id):
        for v in self.variants:
            if v["arc_id"] == str(arc_id) and v["id"] == str(variant_id):
                return dict(v)
        return None

    # compositions + head
    def insert_ideal_text_composition(self, arc_id, revision, selections,
                                      reason, created_by):
        key = (str(arc_id), revision)
        if key in self.compositions:
            return False                 # append-only conflict
        self.compositions[key] = {
            "arc_id": str(arc_id), "revision": revision,
            "selections": selections, "reason": reason,
            "created_by": created_by}
        return True

    def get_ideal_text_composition(self, arc_id, revision):
        row = self.compositions.get((str(arc_id), revision))
        return dict(row) if row else None

    def list_ideal_text_compositions(self, arc_id, limit=50):
        rows = sorted((dict(v) for k, v in self.compositions.items()
                       if k[0] == str(arc_id)),
                      key=lambda r: -r["revision"])
        return rows[:limit]

    def get_ideal_text_composition_head(self, arc_id):
        rev = self.head.get(str(arc_id))
        return {"arc_id": str(arc_id), "head_revision": rev} \
            if rev else None

    def set_ideal_text_composition_head(self, arc_id, revision):
        self.head[str(arc_id)] = revision
        return True


def _block(key, sid, take_index, pieces, *, label=None, status="settled",
           active=True, challenger=None):
    row = {
        "arc_id": ARC, "block_key": key, "label": label, "active": active,
        "slide_index": None, "status": status,
        "incumbent_take_session_id": sid,
        "incumbent_take_index": take_index,
        "incumbent_pieces": pieces,
        "challenger_take_session_id": None,
        "challenger_take_index": None,
        "challenger_pieces": None,
        "challenger_why": None,
        "rejected_take_session_ids": [],
    }
    if challenger:
        row.update(challenger)
    return row


def _pieces(*texts, prefix="s"):
    return [{"snippet_id": f"{prefix}{i}", "text": t}
            for i, t in enumerate(texts)]


class TakeCaptureTests(unittest.TestCase):
    def test_losing_segment_still_pools(self):
        """Fear #1: a take's segment that loses the duel (or is later
        displaced by a newer offer) is in the pool regardless."""
        db = _Db()
        n = capture_take_variants(db, ARC, T2, 2, {
            0: _pieces("worse opening words"),
            10: _pieces("a better middle"),
        })
        self.assertEqual(n, 2)
        keys = {v["block_key"] for v in db.variants}
        self.assertEqual(keys, {0, 10})
        self.assertTrue(all(v["source_kind"] == "take"
                            for v in db.variants))

    def test_recapture_is_idempotent(self):
        db = _Db()
        capture_take_variants(db, ARC, T2, 2, {0: _pieces("same words")})
        n = capture_take_variants(db, ARC, T2, 2,
                                  {0: _pieces("same words")})
        self.assertEqual(n, 0)
        self.assertEqual(len(db.variants), 1)


class SnapshotTests(unittest.TestCase):
    def test_seed_snapshot_creates_pool_and_head(self):
        db = _Db(blocks=[
            _block(0, T1, 1, _pieces("the opening")),
            _block(10, T1, 1, _pieces("the middle")),
        ])
        rev = snapshot_composition(db, ARC, reason="seed")
        self.assertEqual(rev, 1)
        self.assertEqual(db.head[ARC], 1)
        sels = db.compositions[(ARC, 1)]["selections"]
        self.assertEqual([s["block_key"] for s in sels], [0, 10])
        # find-or-create healed the pool from the incumbents
        self.assertEqual(len(db.variants), 2)

    def test_candidate_blocks_stay_out(self):
        db = _Db(blocks=[
            _block(0, T1, 1, _pieces("the opening")),
            _block(10, T2, 2, _pieces("new material"),
                   status="candidate", active=False),
        ])
        snapshot_composition(db, ARC, reason="seed")
        sels = db.compositions[(ARC, 1)]["selections"]
        self.assertEqual([s["block_key"] for s in sels], [0])

    def test_revisions_append_never_overwrite(self):
        db = _Db(blocks=[_block(0, T1, 1, _pieces("words"))])
        r1 = snapshot_composition(db, ARC, reason="seed")
        r2 = snapshot_composition(db, ARC, reason="accept")
        self.assertEqual((r1, r2), (1, 2))
        self.assertIn((ARC, 1), db.compositions)
        self.assertIn((ARC, 2), db.compositions)


if __name__ == "__main__":
    unittest.main()
