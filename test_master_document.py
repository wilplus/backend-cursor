"""Compatibility tests for the retired master-document experiment.

Run: python3 -m unittest test_master_document
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.master_document import (
    _quarter_split,
    assemble_master_document,
    block_additions,
    build_skeleton,
    decide_block,
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
        # A block boundary is a PARAGRAPH boundary (SPEC §11.1) — the old
        # " ".join served the whole master as one wall-of-text chunk.
        self.assertEqual(out["text"],
                         "The opening words.\n\nThen the middle words.")
        badges = [(p["take_index"], p["block_key"])
                  for p in out["document"]["pieces"]]
        self.assertEqual(badges, [(1, 0), (2, 10)])
        for p in out["document"]["pieces"]:
            self.assertEqual(out["text"][p["start"]:p["end"]], p["text"])
        # One provenance row per "\n\n" paragraph, block_key carried.
        paras = out["document"]["paragraphs"]
        self.assertEqual(len(paras), len(out["text"].split("\n\n")))
        self.assertEqual([p["block_key"] for p in paras], [0, 10])
        for p in paras:
            self.assertEqual(out["text"][p["start"]:p["end"]].strip(),
                             out["text"][p["start"]:p["end"]])

    def test_a_long_block_splits_at_the_cap_never_inside_a_piece(self):
        # SPEC §11.1: within a block, pieces pack greedily up to
        # PARAGRAPH_CAP_CHARS; piece boundaries are the only cut points,
        # so the joined words are IDENTICAL — only separators change.
        words = [f"piece {i} carries about enough words to be a real "
                 f"spoken fragment of the talk here" for i in range(6)]
        db = _Db(blocks=[{
            "arc_id": ARC, "block_key": 0, "label": None,
            "active": True, "status": "settled",
            "incumbent_take_session_id": T1, "incumbent_take_index": 1,
            "incumbent_pieces": [
                {"snippet_id": f"s{i}", "text": w}
                for i, w in enumerate(words)],
            "challenger_take_session_id": None,
            "challenger_take_index": None,
            "challenger_pieces": None, "challenger_why": None,
            "rejected_take_session_ids": []}])
        out = assemble_master_document(ARC, database=db)
        paras = out["text"].split("\n\n")
        self.assertGreater(len(paras), 1)
        from services.slide_word_split import PARAGRAPH_CAP_CHARS
        # Every multi-piece paragraph respects the cap (a single
        # sentence-extended piece may legally exceed it; none here does).
        for para in paras:
            self.assertLessEqual(len(para), PARAGRAPH_CAP_CHARS + 1)
        # Provenance rows stay 1:1 with the served paragraphs, all on the
        # same block.
        prows = out["document"]["paragraphs"]
        self.assertEqual(len(prows), len(paras))
        self.assertEqual({p["block_key"] for p in prows}, {0})
        # Verbatim: the words survive with only separators/casing/terminal
        # marks differing — every piece span still reads back exactly.
        for p in out["document"]["pieces"]:
            self.assertEqual(out["text"][p["start"]:p["end"]], p["text"])
        self.assertEqual(len(out["document"]["pieces"]), len(words))

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

    def test_a_candidate_is_NOT_a_tracked_change(self):
        """It used to ride here as a zero-width `insert` and reached NOBODY —
        dropped by the FE's kind vocabulary, by its `end > start` span check,
        and by the manager gate's zero-width guard. All three were right; the
        mistake was upstream. Additions are their own lane now."""
        row = _block(10, text="brand new closing", status="candidate",
                     active=False, sess=T2, take=2)
        db = _Db(blocks=[_block(0), row])
        out = upgrade_changes(ARC, "The master words.", db)
        self.assertEqual([c for c in out if c.get("kind") == "insert"], [])


class BlockAdditionsTests(unittest.TestCase):
    """Material the speaker SAID that is not in the master document at all — a
    decked slide the skeleton never saw. Words on a slide of the student's own
    deck, currently missing from their script: F1 piece (b), not scaffolding."""

    def test_a_candidate_is_offered_with_no_span_at_all(self):
        row = _block(10, text="brand new closing", status="candidate",
                     active=False, sess=T2, take=2)
        db = _Db(blocks=[_block(0), row])
        out = block_additions(ARC, "The master words.", db)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["text"], "brand new closing")
        self.assertEqual(out[0]["take_index"], 2)
        self.assertEqual(out[0]["take_session_id"], T2)
        self.assertEqual(out[0]["block_key"], 10)
        # No span, no quote, no kind: there is nothing in the document to
        # anchor to, and inventing an anchor is what broke this before.
        for absent in ("span", "quote", "kind", "proposed_text"):
            self.assertNotIn(absent, out[0])

    def test_material_already_in_the_master_is_not_re_offered(self):
        row = _block(10, text="brand new closing", status="candidate",
                     active=False, sess=T2, take=2)
        db = _Db(blocks=[_block(0), row])
        self.assertEqual(
            block_additions(ARC, "Before. BRAND NEW CLOSING. After.", db), [])

    def test_only_candidates_are_additions(self):
        db = _Db(blocks=[_block(0), _block(10, status="settled")])
        self.assertEqual(block_additions(ARC, "The master words.", db), [])

    def test_an_empty_candidate_is_dropped(self):
        row = _block(10, text="", status="candidate", active=False,
                     sess=T2, take=2)
        row["incumbent_pieces"] = []
        db = _Db(blocks=[row])
        self.assertEqual(block_additions(ARC, "The master words.", db), [])

    def test_additions_come_back_in_block_order(self):
        rows = [_block(30, text="third bit", status="candidate",
                       active=False, sess=T2, take=2),
                _block(20, text="second bit", status="candidate",
                       active=False, sess=T2, take=2)]
        out = block_additions(ARC, "The master words.", _Db(blocks=rows))
        self.assertEqual([a["text"] for a in out], ["second bit", "third bit"])

    def test_no_blocks_is_empty(self):
        self.assertEqual(block_additions(ARC, "doc", _Db(blocks=[])), [])

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
@unittest.skip("retired incumbent/challenger endpoint")
class SaveEndpointTests(unittest.TestCase):
    """SAVE = accept-and-freeze: unactioned offers resolve as kept-mine,
    the version is stamped, the FE gates the re-read on it."""

    def setUp(self):
        self.app = Flask(__name__)

    def _post(self, *, blocks, version=3, flags=None):
        with self.app.test_request_context(json={}):
            request.user_id = "u1"
            with patch.dict("os.environ", flags or _FLAGS), \
                 patch("routes.v2.explore_ideal_text._arc_owned_by_caller",
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
@unittest.skip("retired incumbent/challenger endpoint")
class DecideEndpointTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def _post(self, body, *, row):
        with self.app.test_request_context(json=body):
            request.user_id = "u1"
            with patch.dict("os.environ", _FLAGS), \
                 patch("routes.v2.explore_ideal_text._arc_owned_by_caller",
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
@unittest.skip("retired incumbent/challenger endpoint")
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
