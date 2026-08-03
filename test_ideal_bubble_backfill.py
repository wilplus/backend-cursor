"""willab — back-fill the ideal-text version bubbles on guest claim
(founder bug 2026-07-18).

THE BUG the founder hit live: the per-version bubbles fire in the analysis
worker only for a KNOWN owner. A guest has no lounge thread, so their takes
produced NO bubbles — and signing in afterwards never back-filled them, so
the chat (which IS the version history: 1.0 unverified → N.0 verified)
started empty.

Pinned here: what gets back-filled per arc state, idempotency, and that a
failure can never unwind the claim.

Run: python3 -m unittest test_ideal_bubble_backfill
"""
from __future__ import annotations

import unittest

from services.arc_notifications import backfill_ideal_bubbles

ARC = "a1"
UID = "u1"


class _Db:
    def __init__(self, row):
        self.row = row
        self.inserted = []

    def get_coach_arc_ideal_text(self, arc_id):
        return self.row

    def insert_lounge_messages(self, uid, msgs):
        self.inserted.extend(msgs)
        return msgs


def _row(**over):
    r = {"arc_id": ARC, "text": "machine text", "auto_text": "machine text",
         "updated_by": None, "approved_at": None, "version": 3,
         "verified_version": None, "verified_text": None}
    r.update(over)
    return r


class BackfillTests(unittest.TestCase):

    def test_unverified_arc_backfills_ready_only(self):
        db = _Db(_row(version=3))
        self.assertEqual(backfill_ideal_bubbles(db, UID, ARC), 1)
        m = db.inserted[0]
        self.assertEqual(m["kind"], "ideal_text")
        self.assertEqual(m["metadata"]["variant"], "ready")
        self.assertEqual(m["metadata"]["version"], 3)
        self.assertEqual(m["metadata"]["arc_id"], ARC)

    def test_verified_arc_backfills_ready_and_verified(self):
        db = _Db(_row(version=3, verified_version=3,
                      verified_text="the verified block"))
        self.assertEqual(backfill_ideal_bubbles(db, UID, ARC), 2)
        variants = [m["metadata"]["variant"] for m in db.inserted]
        self.assertEqual(variants, ["ready", "verified"])

    def test_stale_verification_does_not_backfill_verified(self):
        # coach verified v2, a new take bumped to v3 → only 'ready'
        db = _Db(_row(version=3, verified_version=2,
                      verified_text="older block"))
        self.assertEqual(backfill_ideal_bubbles(db, UID, ARC), 1)
        self.assertEqual(db.inserted[0]["metadata"]["variant"], "ready")

    def test_idempotent_client_ids_across_reclaims(self):
        db1, db2 = _Db(_row(version=3)), _Db(_row(version=3))
        backfill_ideal_bubbles(db1, UID, ARC)
        backfill_ideal_bubbles(db2, UID, ARC)
        # same (arc, version) → same client_id → the insert dedupes
        self.assertEqual(db1.inserted[0]["client_id"],
                         db2.inserted[0]["client_id"])

    def test_coach_owned_row_without_machine_copy_still_versions(self):
        db = _Db(_row(auto_text=None, text="coach block",
                      updated_by="coach1", version=4))
        self.assertEqual(backfill_ideal_bubbles(db, UID, ARC), 1)
        self.assertEqual(db.inserted[0]["metadata"]["version"], 4)

    def test_no_ideal_text_yet_is_a_noop(self):
        self.assertEqual(backfill_ideal_bubbles(_Db(None), UID, ARC), 0)
        # a row with no text and no version → nothing honest to announce
        db = _Db(_row(text="", auto_text="", version=None))
        self.assertEqual(backfill_ideal_bubbles(db, UID, ARC), 0)
        self.assertEqual(db.inserted, [])

    def test_missing_ids_noop(self):
        self.assertEqual(backfill_ideal_bubbles(_Db(_row()), None, ARC), 0)
        self.assertEqual(backfill_ideal_bubbles(_Db(_row()), UID, None), 0)

    def test_never_raises_into_the_claim_path(self):
        class _Boom:
            def get_coach_arc_ideal_text(self, a):
                raise RuntimeError("db down")
        self.assertEqual(backfill_ideal_bubbles(_Boom(), UID, ARC), 0)

    def test_dropped_insert_counts_honestly(self):
        # insert_lounge_messages swallows a DB refusal and returns []
        class _Dropping(_Db):
            def insert_lounge_messages(self, uid, msgs):
                return []
        with self.assertLogs("services.arc_notifications", level="ERROR"):
            self.assertEqual(
                backfill_ideal_bubbles(_Dropping(_row()), UID, ARC), 0)


if __name__ == "__main__":
    unittest.main()
