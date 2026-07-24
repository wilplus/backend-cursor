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

    def test_coach_owned_row_still_refreshes_machine_copy(self):
        # Instant lane (2026-07-17): a coach edit no longer stops the eager
        # assembly — the frozen MACHINE copy (auto_text) keeps refreshing so
        # the free instant surface improves on re-record. The never-clobber
        # of the coach's WORKING text moved into persist_auto_ideal_text
        # (pinned in test_instant_ideal_text.py).
        ok, calls = self._run(
            [_spoken(1), _spoken(2), _spoken(3)],
            existing_row={"text": "coach edit", "updated_by": "coach1",
                          "approved_at": None})
        self.assertTrue(ok)
        self.assertEqual(calls["persisted"], "assembled block")

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

    def _get(self, sessions, row=None, auto=None):
        with self.app.test_request_context():
            request.user_id = "coach1"
            with patch.object(v2.db, "get_arc_sessions",
                              return_value=sessions), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=row), \
                 patch("services.ideal_text_block.maybe_assemble_ideal_text",
                       return_value=False), \
                 patch("services.ideal_text_block.assemble_ideal_text_block",
                       return_value=(auto or {"text": "cold fallback",
                                              "key_moments": [],
                                              "ready": True})):
                resp, status = v2.v2_coach_get_ideal_text.__wrapped__(ARC)
                return resp.get_json(), status

    def test_three_takes_but_nothing_assembled_reads_empty_not_ready(self):
        # Founder 2026-07-17: serving assembly_state "ready" with an empty
        # block hands the coach a dead panel. The honest state is "empty".
        body, status = self._get(
            [_spoken(1), _spoken(2), _spoken(3)],
            auto={"text": "", "key_moments": [], "ready": True})
        self.assertEqual(status, 200)
        self.assertEqual(body["assembly_state"], "empty")
        self.assertFalse(body["ready"])
        self.assertEqual(body["text"], "")
        self.assertEqual(body["takes_done"], 3)   # not a take-count problem

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
class ArcReviewStateTests(unittest.TestCase):
    """GET /coach/arc/<id>/review-state (founder 2026-07-17) — the one read
    the post-last-take screen renders from: Open the ideal text → PUBLISH.
    Its can_publish must mirror publish-analysis' own 409 preconditions."""

    def setUp(self):
        self.app = Flask(__name__)

    def _get(self, sessions, ideal_row=None):
        with self.app.test_request_context():
            request.user_id = "coach1"
            with patch.object(v2.db, "get_arc_sessions",
                              return_value=sessions), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=ideal_row):
                out = v2.v2_coach_arc_review_state.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status

    def test_unknown_arc_404s(self):
        _body, status = self._get([])
        self.assertEqual(status, 404)

    def test_all_saved_and_approved_can_publish(self):
        body, status = self._get(
            [_spoken(1), _spoken(2), _spoken(3), _read("s1")],
            {"text": "block", "updated_by": "coach1",
             "approved_at": "2026-07-16T12:00:00Z"})
        self.assertEqual(status, 200)
        self.assertTrue(body["can_publish"])
        self.assertEqual(body["blockers"], [])
        self.assertEqual(body["takes_saved"], 3)
        self.assertEqual(body["takes_total"], 3)   # the read is never a take
        self.assertEqual(body["ideal"]["assembly_state"], "ready")
        self.assertTrue(body["ideal"]["approved"])
        self.assertEqual(body["ideal"]["source"], "coach")
        # the read folds into take 1's row, it does not become its own
        takes = {t["take_index"]: t for t in body["takes"]}
        self.assertTrue(takes[1]["has_reread"])
        self.assertFalse(takes[2]["has_reread"])
        self.assertEqual(takes[1]["review_state"], "reviewed")

    def test_unsaved_take_blocks_and_names_it(self):
        body, _ = self._get(
            [_spoken(1), _spoken(2, saved=False), _spoken(3)],
            {"text": "b", "approved_at": "2026-07-16T12:00:00Z"})
        self.assertFalse(body["can_publish"])
        self.assertIn("TAKES_NOT_SAVED", body["blockers"])
        self.assertEqual(body["pending_session_ids"], ["s2"])
        self.assertEqual(body["takes_saved"], 2)

    def test_unapproved_ideal_blocks(self):
        body, _ = self._get(
            [_spoken(1), _spoken(2), _spoken(3)],
            {"text": "machine draft", "updated_by": None,
             "approved_at": None})
        self.assertFalse(body["can_publish"])
        self.assertEqual(body["blockers"], ["IDEAL_TEXT_NOT_APPROVED"])
        self.assertEqual(body["ideal"]["source"], "machine")
        self.assertTrue(body["ideal"]["ready"])   # there IS a block to open

    def test_no_ideal_row_reads_pending_and_blocks(self):
        body, _ = self._get([_spoken(1), _spoken(2), _spoken(3)], None)
        self.assertEqual(body["ideal"]["assembly_state"], "pending")
        self.assertFalse(body["ideal"]["ready"])
        self.assertIsNone(body["ideal"]["source"])
        self.assertIn("IDEAL_TEXT_NOT_APPROVED", body["blockers"])

    def test_published_arc_reports_published(self):
        rows = [dict(_spoken(i), results_published_at="2026-07-16T13:00:00Z")
                for i in (1, 2, 3)]
        body, _ = self._get(rows, {"text": "b",
                                   "approved_at": "2026-07-16T12:00:00Z"})
        self.assertTrue(body["published"])
        self.assertEqual({t["review_state"] for t in body["takes"]},
                         {"delivered"})


if __name__ == "__main__":
    unittest.main()
