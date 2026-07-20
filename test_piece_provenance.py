"""willab — the discernment system (founder 2026-07-20, "it is critical").

Pinned here, decision by decision:
  * provenance: every piece knows its take (the version badge);
  * INCUMBENT STAYS: a better-ranked challenger NEVER swaps silently —
    the piece pends with a deterministic why-key until the student
    accepts (swap lands, version bumps) or rejects (pinned, remembered);
  * a take that doesn't beat the incumbent changes nothing;
  * flag OFF = byte-for-byte today's behavior.

Run: python3 -m unittest test_piece_provenance
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.piece_provenance import (
    WHY_KEYS,
    persist_piece_meta,
    resolve_discernment,
    swap_why_key,
)

try:
    from flask import Flask, request
    from routes import v2_routes as v2
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    v2 = None
    _IMPORT_ERROR = e

ARC = "a1"
S_V1 = "aaaa1111-aaaa-1111-aaaa-111111111111"
S_V2 = "cccc3333-cccc-3333-cccc-333333333333"
T1 = "bbbb2222-bbbb-2222-bbbb-222222222222"
T2 = "dddd4444-dddd-4444-dddd-444444444444"


def _slide(idx=0, snip=S_V2, sess=T2, take=2, verbatim="the new words"):
    return {"index": idx, "snippet_id": snip, "session_id": sess,
            "take_index": take, "verbatim": verbatim, "text": verbatim,
            "polished": False, "breakthrough": False, "key_phrases": []}


def _row(idx=0, *, inc=S_V1, rejected=None, status="settled"):
    return {"arc_id": ARC, "piece_key": idx, "incumbent_snippet_id": inc,
            "incumbent_session_id": T1, "incumbent_take_index": 1,
            "incumbent_text": "the old words", "status": status,
            "rejected_snippet_ids": rejected or []}


class ResolveDiscernmentTests(unittest.TestCase):
    def test_first_sight_pins_the_winner_settled(self):
        slides, meta = resolve_discernment([_slide()], [], object(), ARC)
        self.assertEqual(slides[0]["snippet_id"], S_V2)   # winner displayed
        m = meta[0]
        self.assertEqual(m["status"], "settled")
        self.assertIsNone(m["challenger"])
        self.assertEqual(m["_row_write"]["incumbent_snippet_id"], S_V2)
        self.assertEqual(m["_row_write"]["incumbent_take_index"], 2)

    def test_incumbent_holds_its_ground(self):
        slides, meta = resolve_discernment(
            [_slide(snip=S_V1, sess=T1, take=1, verbatim="the old words")],
            [_row()], object(), ARC)
        self.assertEqual(slides[0]["snippet_id"], S_V1)
        self.assertEqual(meta[0]["status"], "settled")
        self.assertIsNone(meta[0]["challenger"])
        # any stale challenger clears on the way through
        self.assertIsNone(meta[0]["_row_write"]["challenger_snippet_id"])

    def test_better_challenger_pends_and_incumbent_displays(self):
        slides, meta = resolve_discernment(
            [_slide()], [_row()], object(), ARC)
        # THE PIN: the displayed slide is the INCUMBENT, not the winner.
        self.assertEqual(slides[0]["snippet_id"], S_V1)
        self.assertEqual(slides[0]["verbatim"], "the old words")
        self.assertEqual(slides[0]["take_index"], 1)
        self.assertFalse(slides[0]["polished"])
        m = meta[0]
        self.assertEqual(m["status"], "pending_swap")
        self.assertEqual(m["challenger"]["snippet_id"], S_V2)
        self.assertEqual(m["challenger"]["take_index"], 2)
        self.assertEqual(m["challenger"]["text"], "the new words")
        self.assertIn(m["challenger"]["why"], WHY_KEYS)

    def test_rejected_challenger_never_reoffers(self):
        slides, meta = resolve_discernment(
            [_slide()], [_row(rejected=[S_V2])], object(), ARC)
        self.assertEqual(slides[0]["snippet_id"], S_V1)   # pinned
        self.assertEqual(meta[0]["status"], "settled")
        self.assertIsNone(meta[0]["challenger"])

    def test_filler_slot_passes_through(self):
        filler = {"index": 3, "snippet_id": None, "text": ""}
        slides, meta = resolve_discernment([filler], [], object(), ARC)
        self.assertEqual(slides, [filler])
        self.assertEqual(meta, [])


class SwapWhyKeyTests(unittest.TestCase):
    def _snip(self, **metrics):
        return {"metrics": metrics}

    def test_energy_dominates(self):
        why = swap_why_key(self._snip(f0_sd=10.0, pause_ratio=10.0),
                           self._snip(f0_sd=15.0, pause_ratio=10.2))
        self.assertEqual(why, "energy")

    def test_steadiness_dominates(self):
        why = swap_why_key(self._snip(f0_sd=10.0, pause_ratio=10.0),
                           self._snip(f0_sd=10.1, pause_ratio=14.0))
        self.assertEqual(why, "steadiness")

    def test_coverage_dominates(self):
        why = swap_why_key(
            {"metrics": {"f0_sd": 10.0, "slide_stickiness": 0.4}},
            {"metrics": {"f0_sd": 10.1, "slide_stickiness": 0.8}})
        self.assertEqual(why, "coverage")

    def test_no_dominance_or_missing_is_overall(self):
        self.assertEqual(swap_why_key(self._snip(f0_sd=10.0),
                                      self._snip(f0_sd=10.5)), "overall")
        self.assertEqual(swap_why_key(None, None), "overall")
        self.assertEqual(swap_why_key({}, {"metrics": {"f0_sd": 99}}),
                         "overall")


class PersistMetaTests(unittest.TestCase):
    class _Db:
        def __init__(self):
            self.writes = []

        def upsert_ideal_piece_provenance(self, arc, key, fields):
            self.writes.append((arc, key, fields))
            return True

    def test_display_text_rides_the_write(self):
        db = self._Db()
        n = persist_piece_meta(db, ARC, [{
            "piece_key": 0, "text": "final baked words",
            "_row_write": {"status": "settled"}}])
        self.assertEqual(n, 1)
        arc, key, fields = db.writes[0]
        self.assertEqual((arc, key), (ARC, 0))
        self.assertEqual(fields["display_text"], "final baked words")

    def test_broken_db_never_raises(self):
        self.assertEqual(persist_piece_meta(object(), ARC, [
            {"piece_key": 0, "_row_write": {}}]), 0)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class AssemblyDiscernmentTests(unittest.TestCase):
    """Flag ON: a pending slot serves the INCUMBENT in the flat text and
    persists the piece meta. Flag OFF: byte-for-byte today's winner."""

    class _Db:
        def __init__(self, rows):
            self._rows = rows
            self.piece_writes = []

        def list_ideal_piece_provenance(self, arc_id):
            return self._rows

        def list_ideal_decisions(self, arc_id):
            return []

        def get_snippet_by_id(self, sid):
            return {"id": sid, "metrics": {"f0_sd": 10.0}}

        def upsert_ideal_piece_provenance(self, arc, key, fields):
            self.piece_writes.append((key, fields))
            return True

    def _assemble(self, rows, *, flag):
        import services.ideal_text_block as mod
        bp = {"ready": True, "slides": [_slide()]}
        db = self._Db(rows)
        env = {"DISCERNMENT_PROVENANCE_ENABLED": "1" if flag else "0"}
        with patch("services.best_presentation.build_best_presentation",
                   return_value=bp), \
             patch.object(mod, "_polish_as_suggestions_enabled",
                          return_value=True), \
             patch.dict("os.environ", env):
            return mod.assemble_ideal_text_block(ARC, database=db), db

    def test_flag_on_pending_serves_incumbent(self):
        out, db = self._assemble([_row()], flag=True)
        self.assertIn("the old words", out["text"])
        self.assertNotIn("the new words", out["text"])
        key, fields = db.piece_writes[0]
        self.assertEqual(key, 0)
        self.assertEqual(fields["status"], "pending_swap")
        self.assertEqual(fields["challenger_snippet_id"], S_V2)
        self.assertEqual(fields["display_text"], "the old words")

    def test_flag_off_is_todays_behavior(self):
        out, db = self._assemble([_row()], flag=False)
        self.assertIn("the new words", out["text"])
        self.assertEqual(db.piece_writes, [])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SwapEndpointTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def _call(self, body, *, row, owned=True, flag=True):
        env = {"DISCERNMENT_PROVENANCE_ENABLED": "1" if flag else "0"}
        with self.app.test_request_context(json=body):
            request.user_id = "u1"
            with patch.dict("os.environ", env), \
                 patch.object(v2, "_single_deliverable_enabled",
                              return_value=True), \
                 patch.object(v2, "_arc_owned_by_caller",
                              return_value=(owned, [])), \
                 patch.object(v2.db, "get_ideal_piece_provenance",
                              return_value=row), \
                 patch.object(v2.db, "upsert_ideal_piece_provenance",
                              return_value=True) as m_up, \
                 patch.object(v2.db, "list_ideal_piece_provenance",
                              return_value=[]), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value={"version": 3}), \
                 patch("services.ideal_text_block.maybe_assemble_ideal_text",
                       return_value=True) as m_asm, \
                 patch("services.arc_notifications.fire_ideal_version_ready",
                       return_value=True) as m_fire:
                out = v2.v2_explore_piece_swap.__wrapped__(ARC, 0)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, m_up, m_asm, m_fire

    def _pending_row(self):
        r = _row(status="pending_swap")
        r.update({"challenger_snippet_id": S_V2,
                  "challenger_session_id": T2,
                  "challenger_take_index": 2,
                  "challenger_text": "the new words",
                  "challenger_why": "energy"})
        return r

    def test_accept_lands_the_swap_and_reassembles(self):
        body, status, m_up, m_asm, m_fire = self._call(
            {"action": "accept", "challenger_snippet_id": S_V2},
            row=self._pending_row())
        self.assertEqual(status, 200)
        self.assertTrue(body["saved"])
        _, _, fields = (ARC, 0, m_up.call_args.args[2])
        self.assertEqual(fields["incumbent_snippet_id"], S_V2)
        self.assertEqual(fields["incumbent_take_index"], 2)
        self.assertEqual(fields["status"], "settled")
        self.assertIsNone(fields["challenger_snippet_id"])
        m_asm.assert_called_once()          # version bump path
        m_fire.assert_called_once()         # idempotent ready bubble

    def test_reject_pins_and_remembers(self):
        body, status, m_up, m_asm, m_fire = self._call(
            {"action": "reject", "challenger_snippet_id": S_V2},
            row=self._pending_row())
        self.assertEqual(status, 200)
        fields = m_up.call_args.args[2]
        self.assertEqual(fields["status"], "settled")
        self.assertIn(S_V2, fields["rejected_snippet_ids"])
        m_asm.assert_not_called()           # nothing changed → no bump

    def test_stale_echo_409s(self):
        body, status, *_ = self._call(
            {"action": "accept", "challenger_snippet_id": "wrong-id"},
            row=self._pending_row())
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "STALE_SWAP")

    def test_not_pending_409s(self):
        body, status, *_ = self._call(
            {"action": "accept", "challenger_snippet_id": S_V2},
            row=_row())
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "NOT_PENDING")

    def test_unowned_and_flag_off_404(self):
        _, status, *_ = self._call(
            {"action": "accept", "challenger_snippet_id": S_V2},
            row=self._pending_row(), owned=False)
        self.assertEqual(status, 404)
        _, status, *_ = self._call(
            {"action": "accept", "challenger_snippet_id": S_V2},
            row=self._pending_row(), flag=False)
        self.assertEqual(status, 404)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ServePiecesTests(unittest.TestCase):
    def test_pieces_block_shape_and_ac9(self):
        import json as _json
        rows = [self._served_row()]
        with patch.dict("os.environ",
                        {"DISCERNMENT_PROVENANCE_ENABLED": "1"}), \
             patch.object(v2.db, "list_ideal_piece_provenance",
                          return_value=rows):
            out = v2._discernment_pieces(ARC)
        p = out["pieces"][0]
        self.assertEqual(p["take_index"], 1)          # the badge
        self.assertEqual(p["status"], "pending_swap")
        self.assertEqual(p["challenger"]["why"], "energy")
        raw = _json.dumps(out)
        for banned in ("score", "power_score", "_score", "potentiometer",
                       "charisma", "threat"):
            self.assertNotIn(banned, raw)

    def test_flag_off_or_no_rows_is_absent(self):
        with patch.dict("os.environ",
                        {"DISCERNMENT_PROVENANCE_ENABLED": "0"}):
            self.assertEqual(v2._discernment_pieces(ARC), {})
        with patch.dict("os.environ",
                        {"DISCERNMENT_PROVENANCE_ENABLED": "1"}), \
             patch.object(v2.db, "list_ideal_piece_provenance",
                          return_value=[]):
            self.assertEqual(v2._discernment_pieces(ARC), {})

    def test_unknown_why_key_serves_overall(self):
        row = self._served_row()
        row["challenger_why"] = "charisma_delta"   # never on the wire
        with patch.dict("os.environ",
                        {"DISCERNMENT_PROVENANCE_ENABLED": "1"}), \
             patch.object(v2.db, "list_ideal_piece_provenance",
                          return_value=[row]):
            out = v2._discernment_pieces(ARC)
        self.assertEqual(out["pieces"][0]["challenger"]["why"], "overall")

    @staticmethod
    def _served_row():
        return {"piece_key": 0, "incumbent_snippet_id": S_V1,
                "incumbent_session_id": T1, "incumbent_take_index": 1,
                "incumbent_text": "the old words",
                "display_text": "the old words", "status": "pending_swap",
                "challenger_snippet_id": S_V2,
                "challenger_take_index": 2,
                "challenger_text": "the new words",
                "challenger_why": "energy",
                "rejected_snippet_ids": []}


if __name__ == "__main__":
    unittest.main()
