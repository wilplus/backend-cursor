"""willab — the VARIANT POOL + COMPOSITIONS (founder 2026-08-03).

The three fears, pinned as tests:
  1. a new take never loses the previous text — every mapped segment
     pools, losers and displaced offers included; the user's edit pools
     block-level instead of dying as a superseded blob;
  2. going back is repointing — compositions are append-only revisions
     + a head pointer; restore writes through and is itself a revision;
  3. mix and match — select any pooled variant per block; the displaced
     incumbent stays in the pool.

AC-9 pins: the picker payload carries provenance and text only — no
scores, no why vocabulary.

Run: python3 -m unittest test_ideal_text_variants
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.ideal_text_variants import (
    block_variants_payload,
    capture_take_variants,
    capture_user_edit_variants,
    restore_revision,
    select_block_variant,
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


class UserEditCaptureTests(unittest.TestCase):
    """The edit as a first-class variant — the fear-#1 fix for edits."""

    BASE = "The opening words here. And then the middle part follows."
    PIECES = [
        {"snippet_id": "s0", "block_key": 0, "start": 0, "end": 23,
         "text": "The opening words here."},
        {"snippet_id": "s1", "block_key": 10, "start": 24, "end": 58,
         "text": "And then the middle part follows."},
    ]

    def test_edit_attributes_to_the_touched_block_only(self):
        db = _Db()
        edited = ("The opening words here. And then the STRONGER "
                  "middle part follows.")
        n = capture_user_edit_variants(db, ARC, "u1", self.BASE,
                                       self.PIECES, edited)
        self.assertEqual(n, 1)
        v = db.variants[0]
        self.assertEqual(v["block_key"], 10)
        self.assertEqual(v["source_kind"], "user_edit")
        self.assertIn("STRONGER", v["text"])
        self.assertEqual(v["created_by"], "u1")

    def test_identical_resave_dedups(self):
        db = _Db()
        edited = self.BASE.replace("middle", "central")
        capture_user_edit_variants(db, ARC, "u1", self.BASE,
                                   self.PIECES, edited)
        n = capture_user_edit_variants(db, ARC, "u1", self.BASE,
                                       self.PIECES, edited)
        self.assertEqual(n, 0)
        self.assertEqual(len(db.variants), 1)

    def test_wholesale_rewrite_is_not_grafted(self):
        db = _Db()
        n = capture_user_edit_variants(
            db, ARC, "u1", self.BASE, self.PIECES,
            "Completely different text with nothing shared at all "
            "anywhere in any way whatsoever today.")
        self.assertEqual(n, 0)
        self.assertEqual(db.variants, [])

    def test_unchanged_text_writes_nothing(self):
        db = _Db()
        n = capture_user_edit_variants(db, ARC, "u1", self.BASE,
                                       self.PIECES, self.BASE)
        self.assertEqual(n, 0)


class SelectTests(unittest.TestCase):
    def _seeded(self):
        db = _Db(blocks=[
            _block(0, T2, 2, _pieces("take two words"), challenger={
                "status": "pending_upgrade",
                "challenger_take_session_id": T3,
                "challenger_take_index": 3,
                "challenger_pieces": _pieces("take three words"),
                "challenger_why": "energy",
            }),
        ])
        old = db.insert_ideal_text_block_variant(ARC, 0, {
            "source_kind": "take", "take_session_id": T1,
            "take_index": 1, "pieces": _pieces("take one words"),
            "text": "take one words"})
        return db, old

    def test_select_repoints_and_clears_stale_offer(self):
        """Fear #3: pick take 1's version back; the pending take-3 offer
        (judged against the OLD incumbent) clears; take 2's text stays
        in the pool — nothing is destroyed."""
        db, old = self._seeded()
        ok, err = select_block_variant(db, ARC, 0, old["id"], "u1")
        self.assertTrue(ok)
        self.assertIsNone(err)
        row = db.get_ideal_text_block(ARC, 0)
        self.assertEqual(row["incumbent_take_session_id"], T1)
        self.assertEqual(row["incumbent_take_index"], 1)
        self.assertEqual(row["status"], "settled")
        self.assertIsNone(row["challenger_take_session_id"])
        # displaced take-2 incumbent healed into the pool by the snapshot
        sids = {v.get("take_session_id") for v in db.variants
                if v["source_kind"] == "take"}
        self.assertIn(T2, sids)
        # and the composition recorded the selection
        self.assertEqual(db.head[ARC], 1)
        self.assertEqual(db.compositions[(ARC, 1)]["reason"], "select")

    def test_select_user_edit_variant(self):
        db, _ = self._seeded()
        edit = db.insert_ideal_text_block_variant(ARC, 0, {
            "source_kind": "user_edit", "take_session_id": None,
            "take_index": None, "pieces": [],
            "text": "my own restructured words", "created_by": "u1"})
        ok, err = select_block_variant(db, ARC, 0, edit["id"], "u1")
        self.assertTrue(ok)
        row = db.get_ideal_text_block(ARC, 0)
        self.assertIsNone(row["incumbent_take_session_id"])
        self.assertIsNone(row["incumbent_take_index"])
        self.assertEqual(row["incumbent_pieces"],
                         [{"snippet_id": None,
                           "text": "my own restructured words"}])

    def test_select_wrong_block_or_missing_variant_404s(self):
        db, old = self._seeded()
        self.assertEqual(select_block_variant(db, ARC, 99, old["id"], "u"),
                         (False, "NOT_FOUND"))
        self.assertEqual(select_block_variant(db, ARC, 0, "nope", "u"),
                         (False, "NOT_FOUND"))

    def test_select_current_incumbent_is_idempotent(self):
        db, _ = self._seeded()
        cur = db.insert_ideal_text_block_variant(ARC, 0, {
            "source_kind": "take", "take_session_id": T2,
            "take_index": 2, "pieces": _pieces("take two words"),
            "text": "take two words"})
        ok, err = select_block_variant(db, ARC, 0, cur["id"], "u1")
        self.assertEqual((ok, err), (True, None))
        # no write, no revision
        self.assertEqual(db.writes, [])
        self.assertEqual(db.compositions, {})


class RestoreTests(unittest.TestCase):
    def test_restore_writes_through_and_is_itself_a_revision(self):
        """Fear #2: the worse take never trapped anyone — repoint back."""
        db = _Db(blocks=[_block(0, T1, 1, _pieces("take one words"))])
        r1 = snapshot_composition(db, ARC, reason="seed")
        v1 = db.compositions[(ARC, r1)]["selections"][0]["variant_id"]
        # take 2 arrives and is accepted
        two = db.insert_ideal_text_block_variant(ARC, 0, {
            "source_kind": "take", "take_session_id": T2,
            "take_index": 2, "pieces": _pieces("take two words"),
            "text": "take two words"})
        db.upsert_ideal_text_block(ARC, 0, {
            "incumbent_take_session_id": T2,
            "incumbent_take_index": 2,
            "incumbent_pieces": _pieces("take two words")})
        snapshot_composition(db, ARC, reason="accept")
        self.assertEqual(db.head[ARC], 2)
        # regret → restore revision 1
        ok, err = restore_revision(db, ARC, r1, "u1")
        self.assertEqual((ok, err), (True, None))
        row = db.get_ideal_text_block(ARC, 0)
        self.assertEqual(row["incumbent_take_session_id"], T1)
        self.assertEqual(db.head[ARC], 3)
        self.assertEqual(db.compositions[(ARC, 3)]["reason"], "restore")
        # take 2's text still pooled — restore destroyed nothing
        self.assertIn(two["id"], {v["id"] for v in db.variants})
        # and revision 1's pointer target is intact
        self.assertEqual(
            db.get_ideal_text_block_variant(ARC, v1)["text"],
            "take one words")

    def test_restore_missing_revision_404s(self):
        db = _Db(blocks=[_block(0, T1, 1, _pieces("words"))])
        self.assertEqual(restore_revision(db, ARC, 7, "u1"),
                         (False, "NOT_FOUND"))


class PayloadTests(unittest.TestCase):
    def _pooled(self):
        db = _Db(blocks=[
            _block(0, T2, 2, _pieces("take two words"), label="Hook"),
        ])
        db.insert_ideal_text_block_variant(ARC, 0, {
            "source_kind": "take", "take_session_id": T1,
            "take_index": 1, "pieces": _pieces("take one words"),
            "text": "take one words"})
        db.insert_ideal_text_block_variant(ARC, 0, {
            "source_kind": "take", "take_session_id": T2,
            "take_index": 2, "pieces": _pieces("take two words"),
            "text": "take two words"})
        db.insert_ideal_text_block_variant(ARC, 0, {
            "source_kind": "user_edit", "take_session_id": None,
            "take_index": None, "pieces": [], "text": "older edit",
            "created_by": "u1"})
        db.insert_ideal_text_block_variant(ARC, 0, {
            "source_kind": "user_edit", "take_session_id": None,
            "take_index": None, "pieces": [], "text": "newest edit",
            "created_by": "u1"})
        return db

    def test_take_order_latest_edit_only_current_flagged(self):
        payload = block_variants_payload(self._pooled(), ARC)
        [blk] = payload["blocks"]
        self.assertEqual(blk["label"], "Hook")
        sources = [(v["source"], v.get("take_index"))
                   for v in blk["variants"]]
        self.assertEqual(sources,
                         [("take", 1), ("take", 2), ("user_edit", None)])
        # only the LATEST user edit is offered (block-level cleanliness)
        self.assertEqual(blk["variants"][2]["text"], "newest edit")
        self.assertEqual([v["is_current"] for v in blk["variants"]],
                         [False, True, False])

    def test_ac9_no_scores_anywhere(self):
        payload = block_variants_payload(self._pooled(), ARC)

        def _walk(x):
            if isinstance(x, dict):
                for k, v in x.items():
                    self.assertNotIn("score", str(k).lower())
                    self.assertNotIn("why", str(k).lower())
                    _walk(v)
            elif isinstance(x, list):
                for v in x:
                    _walk(v)
        _walk(payload)

    def test_pre_pool_incumbent_still_shows(self):
        db = _Db(blocks=[_block(0, T2, 2, _pieces("take two words"))])
        [blk] = block_variants_payload(db, ARC)["blocks"]
        [entry] = blk["variants"]
        self.assertIsNone(entry["variant_id"])
        self.assertTrue(entry["is_current"])
        self.assertEqual(entry["text"], "take two words")

    def test_read_fail_is_none_not_empty(self):
        db = _Db()
        db.blocks_fail = True
        self.assertIsNone(block_variants_payload(db, ARC))


class PipelineHookTests(unittest.TestCase):
    """process_new_take pools every mapped segment BEFORE the duel —
    winners, losers, and offers a newer take would displace."""

    def test_losing_take_still_lands_in_the_pool(self):
        from services.master_document import process_new_take

        class _PipeDb(_Db):
            def __init__(self):
                super().__init__(blocks=[_block(
                    0, T1, 1,
                    [{"snippet_id": "a0", "text": "take one words"}])])
                self.sessions = [
                    {"id": T1, "take_index": 1,
                     "recording_kind": "spoken"},
                    {"id": T2, "take_index": 2,
                     "recording_kind": "spoken"},
                ]

            def get_arc_sessions(self, arc_id):
                return self.sessions

            def get_snippets_by_session(self, sid):
                if str(sid) == T2:
                    return [{"id": "b0", "start_offset_ms": 0,
                             "language": "en",
                             "transcript": "take two words",
                             "metrics": {"overall_score": 0.1}}]
                return [{"id": "a0", "start_offset_ms": 0,
                         "language": "en",
                         "transcript": "take one words",
                         "metrics": {"overall_score": 0.9}}]

            def get_coach_snippet_drafts(self, sid):
                return []

            def get_user_transcript_edits(self, sid):
                return []

            def list_ideal_decisions(self, arc_id):
                return []

            def get_snippets_by_ids(self, ids):
                rows = {"a0": {"metrics": {"overall_score": 0.9}},
                        "b0": {"metrics": {"overall_score": 0.1}}}
                return [dict(rows[str(i)], id=str(i))
                        for i in ids if str(i) in rows]

        db = _PipeDb()
        offers = process_new_take(ARC, T2, db)
        self.assertEqual(offers, 0)      # take 2 lost the duel
        pooled = [v for v in db.variants
                  if v.get("take_session_id") == T2]
        self.assertEqual(len(pooled), 1)  # …but its words survived
        # document-cased by the finalizer — matching is case-tolerant
        self.assertEqual(pooled[0]["text"].lower(), "take two words")


if __name__ == "__main__":
    unittest.main()
