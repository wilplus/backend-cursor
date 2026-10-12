"""Compatibility tests for the retired master-document experiment.

Run: python3 -m unittest tests.test_master_document
"""
from __future__ import annotations

import unittest

from services.master_document import (
    assemble_master_document,
    decide_block,
)

ARC = "a1"
T1 = "take-1-sess"
T2 = "take-2-sess"


class _Db:
    """Fake db: blocks + takes + snippets, recording every write."""

    def __init__(self, *, sessions=None, snips_by_session=None,
                 snippet_rows=None, blocks=None, blocks_fail=False):
        self.sessions = sessions if sessions is not None else [
            {"id": T1, "take_index": 1, "recording_kind": "spoken"}]
        self.snips_by_session = snips_by_session or {}
        self.snippet_rows = snippet_rows or {}
        self.blocks = {} if blocks is None else {
            (b["arc_id"], b["block_key"]): dict(b) for b in blocks}
        self.blocks_fail = blocks_fail
        self.writes = []

    @property
    def ideal_text(self):
        # audit Q-A2: production now calls database.ideal_text.<method>();
        # this fake implements those methods directly on itself.
        return self

    def get_arc_sessions(self, arc_id):
        return self.sessions

    @property
    def takes(self):
        # audit Q-A2: production now calls db.takes.<method>();
        # this fake implements those methods directly on itself.
        return self

    def v2_get_session_by_id(self, sid):
        for s in self.sessions:
            if str(s.get("id")) == str(sid):
                return s
        return {"id": sid, "take_index": None}

    def get_snippets_by_session(self, sid):
        return self.snips_by_session.get(str(sid), [])

    def get_coach_snippet_drafts(self, sid):
        return []

    def get_user_transcript_edits(self, sid):
        return []

    def get_snippet_by_id(self, sid):
        return self.snippet_rows.get(str(sid))

    def list_ideal_decisions(self, arc_id):
        return []

    def list_ideal_text_blocks(self, arc_id):
        if self.blocks_fail:
            return None
        return sorted((dict(v) for k, v in self.blocks.items()
                       if k[0] == str(arc_id)),
                      key=lambda r: r["block_key"])

    def get_ideal_text_block(self, arc_id, block_key):
        row = self.blocks.get((str(arc_id), block_key))
        return dict(row) if row else None

    def get_snippets_by_ids(self, ids):
        return [dict(self.snippet_rows[str(i)], id=str(i))
                for i in ids if str(i) in self.snippet_rows]

    def delete_ideal_text_block(self, arc_id, block_key):
        self.blocks.pop((str(arc_id), block_key), None)
        self.writes.append((block_key, {"__deleted__": True}))
        return True

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


def _block(key, *, text="the master words", sid="s1", take=1,
           status="settled", active=True, sess=T1, rejected=None,
           label=None):
    return {"arc_id": ARC, "block_key": key, "label": label,
            "active": active, "status": status,
            "incumbent_take_session_id": sess,
            "incumbent_take_index": take,
            "incumbent_pieces": [{"snippet_id": sid, "text": text}],
            "challenger_take_session_id": None,
            "challenger_take_index": None,
            "challenger_pieces": None, "challenger_why": None,
            "rejected_take_session_ids": rejected or []}


class AcceptedUpgradeRoundTripTests(unittest.TestCase):
    def test_accept_changes_the_master_document(self):
        row = _block(0, text="the master words")
        row.update({"status": "pending_upgrade",
                    "challenger_take_session_id": T2,
                    "challenger_take_index": 2,
                    "challenger_pieces": [{"snippet_id": "n1",
                                           "text": "the newer words"}]})
        db = _Db(blocks=[row])
        before = assemble_master_document(ARC, database=db)["text"]
        self.assertIn("master", before)
        decide_block(ARC, 0, "accept", T2, db)
        after = assemble_master_document(ARC, database=db)
        self.assertIn("newer", after["text"])
        self.assertNotIn("master", after["text"])
        self.assertEqual(after["document"]["pieces"][0]["take_index"], 2)


if __name__ == "__main__":
    unittest.main()
