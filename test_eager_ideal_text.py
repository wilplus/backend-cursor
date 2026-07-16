"""willab — eager ideal-text assembly + saved=reviewed (founder 2026-07-15).

The founder's bug: the coach assembler was invisible (silent lazy compute) →
never reviewed → never approved → publish blocked → the student got ZERO
bubbles. This suite pins the whole chain:

  * spoken-only readiness/candidates (a read never counts / never competes);
  * eager assembly at spoken take 3, persisted, coach-edit-safe;
  * the coach GET's observable states (pending w/ counts → ready);
  * saved = REVIEWED (review_state) on the coach surfaces;
  * BE-C: the END-TO-END smoke — 3 takes → eager draft → save ×3 → approve →
    publish-analysis → EXACTLY the 4 ordered bubbles.

Run: python3 -m unittest test_eager_ideal_text
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

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


def _spoken(i, saved=True):
    return {"id": f"s{i}", "user_id": "u1", "arc_id": ARC, "take_index": i,
            "created_at": f"2026-07-1{i}T10:00:00Z",
            "intake_context": {"topic": "Demo"},
            "results_published_at": None,
            "recording_kind": "spoken", "paired_session_id": None,
            "coach_feedback_saved_at":
                (f"2026-07-1{i}T11:00:00Z" if saved else None)}


def _read(paired="s1"):
    return {"id": f"r-{paired}", "user_id": "u1", "arc_id": ARC,
            "take_index": 1, "created_at": "2026-07-11T12:00:00Z",
            "intake_context": {"topic": "Demo"},
            "results_published_at": None,
            "recording_kind": "read", "paired_session_id": paired,
            "coach_feedback_saved_at": None}


class SpokenFilterTests(unittest.TestCase):
    def test_reads_filtered_legacy_kept(self):
        from services.best_presentation import spoken_arc_sessions
        rows = [_spoken(1), _read("s1"), _spoken(2),
                {"id": "legacy", "take_index": 3}]   # pre-migration row
        out = spoken_arc_sessions(rows)
        self.assertEqual([s["id"] for s in out], ["s1", "s2", "legacy"])
        self.assertEqual(spoken_arc_sessions(None), [])


class EagerAssemblyTests(unittest.TestCase):
    """maybe_assemble_ideal_text — the take-3 trigger."""

    def _run(self, sessions, existing_row=None, auto=None):
        import services.ideal_text_block as mod
        calls = {}

        class _Db:
            def get_arc_sessions(self, a):
                return sessions

            def get_coach_arc_ideal_text(self, a):
                return existing_row

            def persist_auto_ideal_text(self, a, text):
                calls["persisted"] = text
                return True

        with patch.object(mod, "assemble_ideal_text_block",
                          return_value=(auto or {
                              "text": "assembled block",
                              "key_moments": [], "ready": True})):
            ok = mod.maybe_assemble_ideal_text(ARC, database=_Db())
        return ok, calls

    def test_three_spoken_takes_assembles_and_persists(self):
        ok, calls = self._run([_spoken(1), _spoken(2), _spoken(3), _read()])
        self.assertTrue(ok)
        self.assertEqual(calls["persisted"], "assembled block")

    def test_two_spoken_plus_read_is_not_ready(self):
        # THE founder bug: a read must never complete the 3-take trigger.
        ok, calls = self._run([_spoken(1), _spoken(2), _read("s1")])
        self.assertFalse(ok)
        self.assertNotIn("persisted", calls)

    def test_coach_owned_row_never_touched(self):
        ok, calls = self._run(
            [_spoken(1), _spoken(2), _spoken(3)],
            existing_row={"text": "coach edit", "updated_by": "coach1",
                          "approved_at": None})
        self.assertFalse(ok)
        self.assertNotIn("persisted", calls)

    def test_machine_row_refreshed_on_rerecord(self):
        ok, calls = self._run(
            [_spoken(1), _spoken(2), _spoken(3)],
            existing_row={"text": "old machine draft", "updated_by": None,
                          "approved_at": None})
        self.assertTrue(ok)
        self.assertEqual(calls["persisted"], "assembled block")

    def test_not_ready_assembly_never_persists(self):
        ok, calls = self._run(
            [_spoken(1), _spoken(2), _spoken(3)],
            auto={"text": "", "key_moments": [], "ready": False})
        self.assertFalse(ok)
        self.assertNotIn("persisted", calls)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class CoachIdealGetStatesTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def _get(self, sessions, row=None):
        with self.app.test_request_context():
            request.user_id = "coach1"
            with patch.object(v2.db, "get_arc_sessions",
                              return_value=sessions), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=row), \
                 patch("services.ideal_text_block.maybe_assemble_ideal_text",
                       return_value=False), \
                 patch("services.ideal_text_block.assemble_ideal_text_block",
                       return_value={"text": "cold fallback",
                                     "key_moments": [], "ready": True}):
                resp, status = v2.v2_coach_get_ideal_text.__wrapped__(ARC)
                return resp.get_json(), status

    def test_pending_below_three_spoken_with_counts(self):
        body, status = self._get([_spoken(1), _spoken(2), _read("s1")])
        self.assertEqual(status, 200)
        self.assertEqual(body["assembly_state"], "pending")
        self.assertEqual(body["takes_done"], 2)   # the read didn't count
        self.assertEqual(body["takes_target"], 3)
        self.assertFalse(body["ready"])
        self.assertEqual(body["text"], "")

    def test_persisted_machine_draft_served_instantly(self):
        body, status = self._get(
            [_spoken(1), _spoken(2), _spoken(3)],
            row={"text": "machine draft", "updated_by": None,
                 "approved_at": None})
        self.assertEqual(body["assembly_state"], "ready")
        self.assertEqual(body["source"], "machine")
        self.assertEqual(body["text"], "machine draft")
        self.assertFalse(body["approved"])

    def test_coach_edited_row_reads_source_coach(self):
        body, _ = self._get(
            [_spoken(1), _spoken(2), _spoken(3)],
            row={"text": "coach block", "updated_by": "coach1",
                 "approved_at": None})
        self.assertEqual(body["source"], "coach")

    def test_cold_fallback_still_serves(self):
        body, _ = self._get([_spoken(1), _spoken(2), _spoken(3)], row=None)
        self.assertEqual(body["text"], "cold fallback")
        self.assertEqual(body["assembly_state"], "ready")
        self.assertEqual(body["source"], "auto")


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ReviewStateTests(unittest.TestCase):
    """Founder: saved = REVIEWED. Three states on the drill-down."""

    def setUp(self):
        self.app = Flask(__name__)

    def test_drilldown_three_states_and_ideal_badge(self):
        uid = "11111111-1111-4111-8111-111111111111"
        rows = [
            dict(_spoken(1), results_published_at="2026-07-15T12:00:00Z"),
            _spoken(2, saved=True),
            _spoken(3, saved=False),
        ]
        with self.app.test_request_context():
            request.user_id = "coach1"
            with patch.object(v2.db, "get_user_profile",
                              return_value={"domain": "d", "goal": "g"}), \
                 patch.object(v2.db, "v2_list_user_lab_sessions",
                              return_value=rows), \
                 patch.object(v2.db, "get_feelings_by_sessions",
                              return_value=[]), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value={"text": "machine draft",
                                            "updated_by": None,
                                            "approved_at": None}):
                resp, status = v2.v2_coach_student_detail.__wrapped__(uid)
                body = resp.get_json()
        self.assertEqual(status, 200)
        states = {s["session_id"]: s["review_state"] for s in body["sessions"]}
        self.assertEqual(states["s1"], "delivered")
        self.assertEqual(states["s2"], "reviewed")   # saved = reviewed
        self.assertEqual(states["s3"], "to_review")
        self.assertEqual(body["ideal_ready_arc_ids"], [ARC])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class GuestProgressTests(unittest.TestCase):
    """GET /explore/arc/<id>/progress — guest-capable for fully-unclaimed
    arcs (2026-07-16: the signed-out instant readout polls it; was 401)."""

    def _call(self, sessions, caller=None):
        app = Flask(__name__)
        with app.test_request_context():
            request.user_id = caller
            with patch.object(v2.db, "get_arc_sessions",
                              return_value=sessions), \
                 patch.object(v2.db, "get_coach_best_presentation_edits",
                              return_value={}):
                resp, status = v2.v2_explore_arc_progress.__wrapped__(ARC)
                return resp.get_json(), status

    def test_guest_reads_fully_unclaimed_arc(self):
        unclaimed = [dict(_spoken(i), user_id=None) for i in (1, 2)]
        body, status = self._call(unclaimed, caller=None)
        self.assertEqual(status, 200)
        self.assertEqual(body["takes_done"], 2)

    def test_claimed_arc_hidden_from_guest_and_stranger(self):
        claimed = [_spoken(1)]  # user_id u1
        _, s_guest = self._call(claimed, caller=None)
        _, s_other = self._call(claimed, caller="intruder")
        self.assertEqual((s_guest, s_other), (404, 404))

    def test_owner_still_reads_and_reads_dont_count(self):
        body, status = self._call([_spoken(1), _spoken(2), _read("s1")],
                                  caller="u1")
        self.assertEqual(status, 200)
        self.assertEqual(body["takes_done"], 2)   # spoken-only


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class FourBubbleEndToEndTests(unittest.TestCase):
    """BE-C — the crystal-clean guarantee: the whole chain to 4 bubbles."""

    def test_full_chain_emits_exactly_four_ordered_bubbles(self):
        app = Flask(__name__)
        sessions = [_spoken(1), _spoken(2), _spoken(3), _read("s1")]
        captured = {}
        with app.test_request_context(json={}):
            request.user_id = "coach1"
            with patch.object(v2.db, "get_arc_sessions",
                              return_value=sessions), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value={"text": "approved block",
                                            "updated_by": "coach1",
                                            "approved_at":
                                                "2026-07-15T13:00:00Z"}), \
                 patch.object(v2.db, "get_coach_snippet_drafts",
                              side_effect=lambda sid: [{
                                  "snippet_id": f"{sid}-p0",
                                  "surfaced": True, "note": "key moment",
                                  "tag": "strong"}]), \
                 patch.object(v2, "_apply_willab_publish_contract",
                              return_value=None) as m_contract, \
                 patch.object(v2.db, "v2_update_session_status_unscoped"), \
                 patch.object(v2.db, "v2_publish_session_results") as m_pub, \
                 patch.object(v2.db, "insert_lounge_messages",
                              side_effect=lambda uid, msgs: captured.update(
                                  {"uid": uid, "msgs": msgs}) or msgs), \
                 patch.object(v2.db, "mark_arc_batch_delivered",
                              return_value=True):
                resp, status = v2.v2_coach_publish_analysis.__wrapped__(ARC)
                body = resp.get_json()
        self.assertEqual(status, 200)
        self.assertTrue(body["published"])
        self.assertEqual(body["bubbles"], 4)
        # 3 spoken takes + the paired read's lifecycle flip (2026-07-16 —
        # folded reads close at publish so the queue never keeps zombies).
        self.assertEqual(m_pub.call_count, 4)
        self.assertEqual(m_contract.call_count, 3)     # contract = spoken only
        _flipped = {c.args[0] for c in m_pub.call_args_list}
        self.assertIn("r-s1", _flipped)
        msgs = captured["msgs"]
        self.assertEqual([m["kind"] for m in msgs],
                         ["feedback", "feedback", "feedback", "ideal_text"])
        self.assertEqual([m["metadata"].get("take_index") for m in msgs[:3]],
                         [1, 2, 3])
        self.assertTrue(msgs[0]["metadata"]["free"])
        self.assertFalse(msgs[2]["metadata"]["free"])
        stamps = [m["client_created_at"] for m in msgs]
        self.assertEqual(stamps, sorted(stamps))       # 1 → 2 → 3 → purple


if __name__ == "__main__":
    unittest.main()
