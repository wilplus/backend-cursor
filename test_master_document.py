"""willab — the MASTER DOCUMENT (founder decisions 2026-07-22).

The flip, pinned decision by decision:
  1. MASTER PERSISTS — one evolving document per project; a new take
     never replaces it;
  2. APPROVE-GATED upgrades — a winning new-take block WAITS; losing or
     skipped blocks are silence; rejected offers never return;
  3. SAVE = accept-and-freeze;
  4. the skeleton locks on take 1 — slides when decked, LLM boundaries
     (INDICES ONLY, hard-validated) else the deterministic quarter split.

Run: python3 -m unittest test_master_document
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.master_document import (
    _quarter_split,
    assemble_master_document,
    build_skeleton,
    decide_block,
    process_new_take,
    upgrade_changes,
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

    def get_arc_sessions(self, arc_id):
        return self.sessions

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


def _snip(sid, offset, text, *, slide=None, score=None, f0=10.0):
    m = {"f0_sd": f0}
    if score is not None:
        m["overall_score"] = score
    if slide is not None:
        m["piece"] = {"slide_index": slide}
    return {"id": sid, "start_offset_ms": offset, "language": "en",
            "transcript": text, "metrics": m}


class QuarterSplitTests(unittest.TestCase):
    def test_framework_cover_and_labels(self):
        out = _quarter_split(10)
        self.assertEqual([b[2] for b in out],
                         ["Hook", "Context", "Core Message", "Closer"])
        # contiguous, covering all ten
        self.assertEqual(out[0][0], 0)
        self.assertEqual(out[-1][1], 9)
        for a, b in zip(out, out[1:]):
            self.assertEqual(b[0], a[1] + 1)

    def test_tiny_take(self):
        self.assertEqual(len(_quarter_split(2)), 2)
        self.assertEqual(_quarter_split(0), [])


class SkeletonTests(unittest.TestCase):
    def test_decked_one_block_per_slide(self):
        db = _Db(snips_by_session={T1: [
            _snip("s1", 0, "slide one words", slide=0),
            _snip("s2", 1000, "more slide one", slide=0),
            _snip("s3", 2000, "slide two words", slide=1),
        ]})
        rows = build_skeleton(ARC, db)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["label"], "Slide 1")
        self.assertEqual(rows[1]["label"], "Slide 2")
        self.assertEqual([r["block_key"] for r in rows], [0, 10])
        self.assertEqual(rows[0]["incumbent_take_index"], 1)
        self.assertEqual(
            [p["snippet_id"] for p in rows[0]["incumbent_pieces"]],
            ["s1", "s2"])

    def test_deckless_falls_back_to_quarter_split(self):
        snips = [_snip(f"s{i}", i * 1000, f"sentence number {i} here")
                 for i in range(8)]
        db = _Db(snips_by_session={T1: snips})
        with patch("services.master_document._llm_boundaries",
                   return_value=None):
            rows = build_skeleton(ARC, db)
        self.assertEqual([r["label"] for r in rows],
                         ["Hook", "Context", "Core Message", "Closer"])

    def test_llm_boundaries_used_when_valid(self):
        snips = [_snip(f"s{i}", i * 1000, f"sentence number {i} here")
                 for i in range(4)]
        db = _Db(snips_by_session={T1: snips})
        with patch("services.master_document._llm_boundaries",
                   return_value=[(0, 1, "Opening"), (2, 3, "Close")]):
            rows = build_skeleton(ARC, db)
        self.assertEqual([r["label"] for r in rows], ["Opening", "Close"])
        self.assertEqual(len(rows[0]["incumbent_pieces"]), 2)

    def test_no_takes_builds_nothing(self):
        self.assertEqual(build_skeleton(ARC, _Db(sessions=[])), [])


class ReadOnlyAssemblyTests(unittest.TestCase):
    """The serving path NEVER builds the skeleton — the take-1 LLM pass
    belongs to the worker alone; a missing skeleton assembles empty (the
    serve layer falls back to the living-transcript document)."""

    def test_assemble_never_writes_or_chunks(self):
        db = _Db(snips_by_session={T1: [
            _snip("s1", 0, "some take one words")]})
        with patch("services.master_document._llm_boundaries") as m_llm:
            out = assemble_master_document(ARC, database=db)
        self.assertFalse(out["ready"])
        self.assertEqual(db.writes, [])
        m_llm.assert_not_called()

    def test_read_failure_assembles_empty_never_rebuilds(self):
        db = _Db(blocks_fail=True)
        out = assemble_master_document(ARC, database=db)
        self.assertFalse(out["ready"])
        self.assertEqual(db.writes, [])


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


class AssembleMasterTests(unittest.TestCase):
    def test_master_is_stable_blocks_in_order_with_badges(self):
        db = _Db(blocks=[
            _block(10, text="then the middle words", take=2, sid="s2"),
            _block(0, text="the opening words", take=1, sid="s1"),
        ])
        out = assemble_master_document(ARC, database=db)
        self.assertEqual(out["text"],
                         "The opening words then the middle words.")
        badges = [(p["take_index"], p["block_key"])
                  for p in out["document"]["pieces"]]
        self.assertEqual(badges, [(1, 0), (2, 10)])
        for p in out["document"]["pieces"]:
            self.assertEqual(out["text"][p["start"]:p["end"]], p["text"])

    def test_candidates_and_inactive_blocks_are_excluded(self):
        db = _Db(blocks=[
            _block(0, text="the real text"),
            _block(10, text="a pending candidate", status="candidate",
                   active=False),
            _block(20, text="a removed block", active=False),
        ])
        out = assemble_master_document(ARC, database=db)
        self.assertEqual(out["text"], "The real text.")

    def test_no_blocks_not_ready(self):
        out = assemble_master_document(ARC, database=_Db(sessions=[]))
        self.assertFalse(out["ready"])


class ProcessNewTakeTests(unittest.TestCase):
    def _db(self, *, master_score=0.4, new_score=0.9, rejected=None,
            new_text="the newer stronger words"):
        sessions = [
            {"id": T1, "take_index": 1, "recording_kind": "spoken"},
            {"id": T2, "take_index": 2, "recording_kind": "spoken"},
        ]
        db = _Db(
            sessions=sessions,
            snips_by_session={
                T2: [_snip("n1", 0, new_text, score=new_score, f0=14.0)]},
            snippet_rows={
                "s1": {"metrics": {"overall_score": master_score,
                                   "f0_sd": 8.0}},
                "n1": {"metrics": {"overall_score": new_score,
                                   "f0_sd": 14.0}}},
            blocks=[_block(0, text="the master words tell the story",
                           rejected=rejected)])
        return db

    def test_winning_new_block_pends_approve_gated(self):
        db = self._db()
        n = process_new_take(ARC, T2, db)
        self.assertEqual(n, 1)
        row = db.get_ideal_text_block(ARC, 0)
        self.assertEqual(row["status"], "pending_upgrade")
        self.assertEqual(row["challenger_take_session_id"], T2)
        self.assertEqual(row["challenger_take_index"], 2)
        # THE PIN: the master's incumbent did not move.
        self.assertEqual(row["incumbent_pieces"][0]["text"],
                         "the master words tell the story")
        self.assertIn(row["challenger_why"],
                      ("energy", "steadiness", "coverage", "overall"))

    def test_losing_new_block_is_silence(self):
        db = self._db(master_score=0.9, new_score=0.4)
        self.assertEqual(process_new_take(ARC, T2, db), 0)
        self.assertEqual(db.get_ideal_text_block(ARC, 0)["status"],
                         "settled")

    def test_unmeasured_sides_never_compare(self):
        db = self._db()
        # The new side loses its measurement AT THE SOURCE (the session
        # snippet feeds the resolver first).
        db.snips_by_session[T2][0]["metrics"].pop("overall_score", None)
        db.snippet_rows["n1"] = {"metrics": {"f0_sd": 14.0}}  # no score
        self.assertEqual(process_new_take(ARC, T2, db), 0)

    def test_rejected_take_never_reoffers(self):
        db = self._db(rejected=[T2])
        self.assertEqual(process_new_take(ARC, T2, db), 0)

    def test_deckless_different_material_is_judged_not_orphaned(self):
        # REDESIGN (review #1/#3/#26): deckless maps by ordinal position,
        # so different wording in the same slot is an UPGRADE comparison —
        # never an end-of-document orphan candidate.
        db = self._db(new_text="a completely different closing topic")
        n = process_new_take(ARC, T2, db)
        self.assertEqual(n, 1)
        row = db.get_ideal_text_block(ARC, 0)
        self.assertEqual(row["status"], "pending_upgrade")
        self.assertEqual(row["challenger_pieces"][0]["text"].lower(),
                         "a completely different closing topic")

    def test_decked_new_slide_becomes_a_candidate(self):
        sessions = [
            {"id": T1, "take_index": 1, "recording_kind": "spoken"},
            {"id": T2, "take_index": 2, "recording_kind": "spoken"},
        ]
        block = _block(0, text="slide one words")
        block["slide_index"] = 0
        db = _Db(
            sessions=sessions,
            snips_by_session={T2: [
                _snip("n1", 0, "slide one words", slide=0, score=0.5),
                _snip("n2", 1000, "a brand new slide two", slide=1,
                      score=0.5)]},
            snippet_rows={"s1": {"metrics": {"overall_score": 0.5}},
                          "n1": {"metrics": {"overall_score": 0.5}},
                          "n2": {"metrics": {"overall_score": 0.5}}},
            blocks=[block])
        n = process_new_take(ARC, T2, db)
        cand = db.get_ideal_text_block(ARC, 10)
        self.assertIsNotNone(cand)
        self.assertEqual(cand["status"], "candidate")
        self.assertEqual(cand["slide_index"], 1)
        self.assertFalse(cand["active"])
        # idempotent: a worker retry does not duplicate the candidate
        process_new_take(ARC, T2, db)
        self.assertIsNone(db.get_ideal_text_block(ARC, 20))

    def test_skeleton_take_is_never_judged_against_itself(self):
        db = self._db()
        self.assertEqual(process_new_take(ARC, T1, db), 0)

    def test_read_failure_writes_nothing(self):
        db = self._db()
        db.blocks_fail = True
        self.assertEqual(process_new_take(ARC, T2, db), 0)
        self.assertEqual(db.writes, [])


class ReviewRegressionTests(unittest.TestCase):
    """The four executed-repro scenarios from the adversarial review —
    each was a confirmed critical/major on the similarity mapper; the
    block-to-block redesign must hold them forever."""

    def test_slide_eight_retake_lands_on_slide_eight(self):
        # Review #1 (critical): an 8-slide deck, take 2 re-records ONLY
        # slide 8 — the old window-4 similarity mapped it onto slide 1
        # and offered to REPLACE the opening with the closing.
        sessions = [
            {"id": T1, "take_index": 1, "recording_kind": "spoken"},
            {"id": T2, "take_index": 2, "recording_kind": "spoken"},
        ]
        blocks = []
        for si in range(8):
            b = _block(si * 10, text=f"slide {si + 1} spoken words",
                       sid=f"s{si}")
            b["slide_index"] = si
            blocks.append(b)
        rows = {f"s{si}": {"metrics": {"overall_score": 0.5}}
                for si in range(8)}
        rows["n1"] = {"metrics": {"overall_score": 0.95}}
        db = _Db(sessions=sessions,
                 snips_by_session={T2: [_snip(
                     "n1", 0, "on slide number eight we cover the "
                     "closing part", slide=7, score=0.95)]},
                 snippet_rows=rows, blocks=blocks)
        n = process_new_take(ARC, T2, db)
        self.assertEqual(n, 1)
        self.assertEqual(db.get_ideal_text_block(ARC, 0)["status"],
                         "settled")           # slide 1 untouched
        self.assertEqual(db.get_ideal_text_block(ARC, 70)["status"],
                         "pending_upgrade")   # slide 8 got the offer

    def test_long_block_retake_is_a_replace_offer_not_a_duplicate(self):
        # Review #3 (major): a 6-piece block was mathematically
        # unmatchable by piece-vs-block ratio; a full retake became a
        # whole-block duplicate insert. Block-to-block mapping makes it
        # a straight upgrade offer carrying the WHOLE segment.
        sessions = [
            {"id": T1, "take_index": 1, "recording_kind": "spoken"},
            {"id": T2, "take_index": 2, "recording_kind": "spoken"},
        ]
        inc = [{"snippet_id": f"s{i}",
                "text": f"original sentence number {i} of the long block"}
               for i in range(6)]
        block = _block(0)
        block["incumbent_pieces"] = inc
        new_snips = [_snip(f"n{i}", i * 1000,
                           f"reworded sentence number {i} of the block",
                           score=0.9) for i in range(6)]
        rows = {f"s{i}": {"metrics": {"overall_score": 0.4}}
                for i in range(6)}
        rows.update({f"n{i}": {"metrics": {"overall_score": 0.9}}
                     for i in range(6)})
        db = _Db(sessions=sessions, snips_by_session={T2: new_snips},
                 snippet_rows=rows, blocks=[block])
        n = process_new_take(ARC, T2, db)
        self.assertEqual(n, 1)
        row = db.get_ideal_text_block(ARC, 0)
        self.assertEqual(row["status"], "pending_upgrade")
        # the WHOLE segment challenges — nothing dropped (review #4/#27)
        self.assertEqual(len(row["challenger_pieces"]), 6)
        # and no orphan duplicate candidate was minted
        self.assertIsNone(db.get_ideal_text_block(ARC, 10))

    def test_skeleton_seeds_from_the_latest_take(self):
        # Review #20/#24 (critical): seeding from take 1 regressed a
        # flipped-on live arc to its oldest text.
        sessions = [
            {"id": "t1", "take_index": 1, "recording_kind": "spoken"},
            {"id": "t3", "take_index": 3, "recording_kind": "spoken"},
        ]

        class _D(_Db):
            def get_snippets_by_session(self, sid):
                return [_snip(f"{sid}-p", 0, f"words from {sid}")]

        db = _D(sessions=sessions)
        rows = build_skeleton(ARC, db)
        self.assertEqual(rows[0]["incumbent_take_session_id"], "t3")
        self.assertEqual(rows[0]["incumbent_take_index"], 3)

    def test_self_skip_is_per_block_after_accepts(self):
        # After an accept, a take can OWN one block and still challenge
        # another — the whole-take skip starved later comparisons.
        sessions = [
            {"id": T1, "take_index": 1, "recording_kind": "spoken"},
            {"id": T2, "take_index": 2, "recording_kind": "spoken"},
        ]
        owned = _block(0, text="already owned by take two", sid="a1",
                       sess=T2, take=2)
        owned["slide_index"] = 0
        other = _block(10, text="still from take one", sid="b1")
        other["slide_index"] = 1
        rows = {"a1": {"metrics": {"overall_score": 0.5}},
                "b1": {"metrics": {"overall_score": 0.3}},
                "n1": {"metrics": {"overall_score": 0.5}},
                "n2": {"metrics": {"overall_score": 0.9}}}
        db = _Db(sessions=sessions,
                 snips_by_session={T2: [
                     _snip("n1", 0, "already owned by take two",
                           slide=0, score=0.5),
                     _snip("n2", 1000, "a stronger second block",
                           slide=1, score=0.9)]},
                 snippet_rows=rows, blocks=[owned, other])
        n = process_new_take(ARC, T2, db)
        self.assertEqual(n, 1)
        self.assertEqual(db.get_ideal_text_block(ARC, 0)["status"],
                         "settled")            # no self-duel
        self.assertEqual(db.get_ideal_text_block(ARC, 10)["status"],
                         "pending_upgrade")    # but B is challenged


class UpgradeChangesTests(unittest.TestCase):
    def test_pending_upgrade_serves_span_anchored_offer(self):
        row = _block(0, text="the master words")
        row.update({"status": "pending_upgrade",
                    "challenger_take_session_id": T2,
                    "challenger_take_index": 2,
                    "challenger_pieces": [{"snippet_id": "n1",
                                           "text": "the newer words"}],
                    "challenger_why": "energy"})
        db = _Db(blocks=[row])
        doc = "The master words."
        out = upgrade_changes(ARC, doc, db)
        c = out[0]
        self.assertEqual(c["kind"], "replace")
        self.assertEqual(c["source"], "new_take")
        self.assertEqual(doc[c["span"]["start"]:c["span"]["end"]],
                         c["quote"])
        self.assertEqual(c["proposed_text"], "the newer words")
        self.assertEqual(c["take_index"], 2)
        self.assertEqual(c["why_key"], "energy")
        self.assertEqual(c["take_session_id"], T2)

    def test_candidate_serves_zero_width_insert(self):
        row = _block(10, text="brand new closing", status="candidate",
                     active=False, sess=T2, take=2)
        db = _Db(blocks=[_block(0), row])
        doc = "The master words."
        out = upgrade_changes(ARC, doc, db)
        ins = [c for c in out if c["kind"] == "insert"][0]
        self.assertEqual(ins["span"], {"start": len(doc), "end": len(doc)})
        self.assertEqual(ins["proposed_text"], "brand new closing")
        self.assertEqual(ins["source"], "new_take")

    def test_missing_incumbent_text_drops_the_offer(self):
        row = _block(0, text="words no longer in the doc")
        row.update({"status": "pending_upgrade",
                    "challenger_take_session_id": T2,
                    "challenger_pieces": [{"snippet_id": "n1",
                                           "text": "x"}]})
        db = _Db(blocks=[row])
        self.assertEqual(upgrade_changes(ARC, "A different doc.", db), [])


class DecideBlockTests(unittest.TestCase):
    def _pending(self):
        row = _block(0, text="the master words")
        row.update({"status": "pending_upgrade",
                    "challenger_take_session_id": T2,
                    "challenger_take_index": 2,
                    "challenger_pieces": [{"snippet_id": "n1",
                                           "text": "the newer words"}],
                    "challenger_why": "energy"})
        return _Db(blocks=[row])

    def test_accept_flips_the_block_and_badge(self):
        db = self._pending()
        ok, err = decide_block(ARC, 0, "accept", T2, db)
        self.assertTrue(ok)
        row = db.get_ideal_text_block(ARC, 0)
        self.assertEqual(row["status"], "settled")
        self.assertEqual(row["incumbent_take_session_id"], T2)
        self.assertEqual(row["incumbent_take_index"], 2)
        self.assertEqual(row["incumbent_pieces"][0]["text"],
                         "the newer words")
        self.assertIsNone(row["challenger_take_session_id"])

    def test_keep_remembers_and_never_reoffers(self):
        db = self._pending()
        ok, _ = decide_block(ARC, 0, "keep", T2, db)
        self.assertTrue(ok)
        row = db.get_ideal_text_block(ARC, 0)
        self.assertEqual(row["status"], "settled")
        self.assertIn(T2, row["rejected_take_session_ids"])
        self.assertEqual(row["incumbent_pieces"][0]["text"],
                         "the master words")
        # …and the take never re-offers (the generation-side guard):
        self.assertEqual(process_new_take(ARC, T2, db), 0)

    def test_stale_echo_and_not_pending(self):
        db = self._pending()
        ok, err = decide_block(ARC, 0, "accept", "some-other-take", db)
        self.assertEqual((ok, err), (False, "STALE_OFFER"))
        db2 = _Db(blocks=[_block(0)])
        ok, err = decide_block(ARC, 0, "accept", T2, db2)
        self.assertEqual((ok, err), (False, "NOT_PENDING"))
        ok, err = decide_block(ARC, 99, "accept", T2, db2)
        self.assertEqual((ok, err), (False, "NOT_FOUND"))

    def test_candidate_accept_activates_keep_discards(self):
        cand = _block(10, text="new closing", status="candidate",
                      active=False, sess=T2, take=2)
        db = _Db(blocks=[_block(0), cand])
        ok, _ = decide_block(ARC, 10, "accept", T2, db)
        self.assertTrue(ok)
        row = db.get_ideal_text_block(ARC, 10)
        self.assertEqual((row["status"], row["active"]),
                         ("settled", True))
        db2 = _Db(blocks=[_block(0), dict(cand)])
        decide_block(ARC, 10, "keep", T2, db2)
        # keep DELETES the candidate — a parked settled-inactive row was
        # an invisible ghost that swallowed later takes (review #2).
        self.assertIsNone(db2.get_ideal_text_block(ARC, 10))


class MasterBakeTests(unittest.TestCase):
    """Approved star/tracked decisions keep applying under the master
    flag — without the bake in assemble_master_document every approval
    would silently stop working (pre-review fix, pinned)."""

    def test_approved_ledger_row_bakes_into_the_master(self):
        from services.ideal_decision_ledger import normalize_phrase

        class _LedgerDb(_Db):
            def list_ideal_decisions(self, arc_id):
                return [{"kind": "replace",
                         "target_phrase": normalize_phrase(
                             "The master words"),
                         "display_phrase": "The master words",
                         "replacement_text": "The stronger words",
                         "decision": "approved", "source": "user_star"}]

        db = _LedgerDb(blocks=[_block(0, text="the master words")])
        out = assemble_master_document(ARC, database=db)
        self.assertIn("The stronger words", out["text"])
        self.assertNotIn("master", out["text"])


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


try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
    _IMPORT_ERROR = e

_FLAGS = {"MASTER_DOCUMENT_ENABLED": "1", "LIVING_TRANSCRIPT_ENABLED": "1"}


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SaveEndpointTests(unittest.TestCase):
    """SAVE = accept-and-freeze: unactioned offers resolve as kept-mine,
    the version is stamped, the FE gates the re-read on it."""

    def setUp(self):
        self.app = Flask(__name__)

    def _post(self, *, blocks, version=3, flags=None):
        with self.app.test_request_context(json={}):
            request.user_id = "u1"
            with patch.dict("os.environ", flags or _FLAGS), \
                 patch.object(v2, "_single_deliverable_enabled",
                              return_value=True), \
                 patch.object(v2, "_arc_owned_by_caller",
                              return_value=(True, [])), \
                 patch.object(v2.db, "list_ideal_text_blocks",
                              return_value=blocks), \
                 patch.object(v2.db, "get_ideal_text_block",
                              side_effect=lambda a, k: next(
                                  (dict(b) for b in blocks
                                   if b["block_key"] == k), None)), \
                 patch.object(v2.db, "upsert_ideal_text_block",
                              return_value=True) as m_up, \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value={"version": version}), \
                 patch.object(v2.db, "insert_ideal_text_save",
                              return_value=True) as m_save:
                out = v2.v2_explore_save_ideal_text.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, m_up, m_save

    def test_save_resolves_pending_offers_and_stamps_the_version(self):
        row = _block(0)
        row.update({"status": "pending_upgrade",
                    "challenger_take_session_id": T2,
                    "challenger_pieces": [{"snippet_id": "n1",
                                           "text": "x"}]})
        body, status, m_up, m_save = self._post(blocks=[row])
        self.assertEqual(status, 200)
        self.assertEqual(body["saved_version"], 3)
        # the pending offer resolved as kept-mine (dismissed-remembered)
        _, fields = m_up.call_args.args[1], m_up.call_args.args[2]
        self.assertEqual(fields["status"], "settled")
        self.assertIn(T2, fields["rejected_take_session_ids"])
        m_save.assert_called_once_with(ARC, 3)

    def test_flag_off_404(self):
        _, status, _, _ = self._post(
            blocks=[], flags={"MASTER_DOCUMENT_ENABLED": "0",
                              "LIVING_TRANSCRIPT_ENABLED": "1"})
        self.assertEqual(status, 404)

    def test_no_version_409(self):
        body, status, _, _ = self._post(blocks=[], version=None)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "NOTHING_TO_SAVE")


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class DecideEndpointTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def _post(self, body, *, row):
        with self.app.test_request_context(json=body):
            request.user_id = "u1"
            with patch.dict("os.environ", _FLAGS), \
                 patch.object(v2, "_single_deliverable_enabled",
                              return_value=True), \
                 patch.object(v2, "_arc_owned_by_caller",
                              return_value=(True, [])), \
                 patch.object(v2.db, "get_ideal_text_block",
                              return_value=row), \
                 patch.object(v2.db, "upsert_ideal_text_block",
                              return_value=True) as m_up, \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value={"version": 3}), \
                 patch("services.ideal_text_block.maybe_assemble_ideal_text",
                       return_value=True) as m_asm, \
                 patch("services.arc_notifications.fire_ideal_version_ready",
                       return_value=True):
                out = v2.v2_explore_decide_block.__wrapped__(ARC, 0)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, m_up, m_asm

    def _pending_row(self):
        row = _block(0)
        row.update({"status": "pending_upgrade",
                    "challenger_take_session_id": T2,
                    "challenger_take_index": 2,
                    "challenger_pieces": [{"snippet_id": "n1",
                                           "text": "the newer words"}]})
        return row

    def test_accept_flips_and_reassembles(self):
        body, status, m_up, m_asm = self._post(
            {"action": "accept", "take_session_id": T2},
            row=self._pending_row())
        self.assertEqual(status, 200)
        fields = m_up.call_args.args[2]
        self.assertEqual(fields["incumbent_take_session_id"], T2)
        m_asm.assert_called_once()

    def test_keep_never_reassembles(self):
        _, status, m_up, m_asm = self._post(
            {"action": "keep", "take_session_id": T2},
            row=self._pending_row())
        self.assertEqual(status, 200)
        self.assertIn(T2,
                      m_up.call_args.args[2]["rejected_take_session_ids"])
        m_asm.assert_not_called()

    def test_stale_echo_409(self):
        body, status, _, _ = self._post(
            {"action": "accept", "take_session_id": "other-take"},
            row=self._pending_row())
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "STALE_OFFER")

    def test_bad_action_400_and_missing_echo_400(self):
        for bad in ({"action": "maybe", "take_session_id": T2},
                    {"action": "accept"}):
            _, status, _, _ = self._post(bad, row=self._pending_row())
            self.assertEqual(status, 400)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SaveStateServeTests(unittest.TestCase):
    def test_save_state_shape_and_is_saved(self):
        with patch.dict("os.environ", _FLAGS), \
             patch.object(v2.db, "get_latest_ideal_text_save",
                          return_value={"version": 3,
                                        "saved_at": "2026-07-22T08:00:00Z"}):
            out = v2._ideal_save_state(ARC, 3)
            self.assertTrue(out["is_saved"])
            out2 = v2._ideal_save_state(ARC, 4)
            self.assertFalse(out2["is_saved"])   # a new take supersedes

    def test_flag_off_or_never_saved_is_absent(self):
        with patch.dict("os.environ", {"MASTER_DOCUMENT_ENABLED": "0"}):
            self.assertEqual(v2._ideal_save_state(ARC, 3), {})
        with patch.dict("os.environ", _FLAGS), \
             patch.object(v2.db, "get_latest_ideal_text_save",
                          return_value=None):
            self.assertEqual(v2._ideal_save_state(ARC, 3), {})


if __name__ == "__main__":
    unittest.main()
