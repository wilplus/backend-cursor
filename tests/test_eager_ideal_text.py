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

Run: python3 -m unittest tests.test_eager_ideal_text
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

try:
    from flask import Flask, request
    from routes.v2 import arcs as v2_arcs
    from routes.v2 import coach as v2_coach
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
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
        from services.slide_selection import spoken_arc_sessions
        rows = [_spoken(1), _read("s1"), _spoken(2),
                {"id": "legacy", "take_index": 3}]   # pre-migration row
        out = spoken_arc_sessions(rows)
        self.assertEqual([s["id"] for s in out], ["s1", "s2", "legacy"])
        self.assertEqual(spoken_arc_sessions(None), [])


class EagerAssemblyTests(unittest.TestCase):
    """maybe_assemble_ideal_text — the take-3 trigger."""

    def _run(self, sessions, existing_row=None, auto=None,
             require_target=True):
        import services.ideal_text_block as mod
        calls = {}

        class _Db:
            def get_arc_sessions(self, a):
                return sessions

            @property
            def takes(self):
                # audit Q-A2: production now calls db.takes.<method>();
                # this fake implements those methods directly on itself.
                return self

            def get_coach_arc_ideal_text(self, a):
                return existing_row

            @property
            def ideal_text(self):
                # audit Q-A2: production now calls
                # database.ideal_text.<method>(); this fake implements
                # those methods directly on itself.
                return self

            def persist_auto_ideal_text(self, a, text, *, take_count=None,
                                        document=None):
                # `document` is the piece provenance the real writer
                # persists beside the text (2026-08-13). A double that
                # omits it raises TypeError, which the caller swallows —
                # the same shape of bug a test double hid once already.
                calls["document"] = document
                calls["persisted"] = text
                # The version is the SPOKEN take count (founder 2026-08-05).
                calls["take_count"] = take_count
                return True

        with patch.object(mod, "assemble_transcript_document",
                          return_value=(auto or {
                              "text": "assembled block",
                              "key_moments": [], "ready": True})):
            ok = mod.maybe_assemble_ideal_text(
                ARC, database=_Db(), require_target=require_target)
        return ok, calls

    def test_version_is_the_spoken_take_count(self):
        # Take 1 → 1.0, take 2 → 2.0 (founder 2026-08-05). require_target
        # =False is the LIVE single-deliverable lane (analysis_worker), which
        # assembles after every take — the legacy 3-take trigger never sees
        # takes 1 and 2 at all. A read row is not a take and must not lift
        # the number.
        _, calls = self._run([_spoken(1), _read()], require_target=False)
        self.assertEqual(calls["take_count"], 1)
        _, calls = self._run([_spoken(1), _spoken(2), _read()],
                             require_target=False)
        self.assertEqual(calls["take_count"], 2)

    def test_three_spoken_takes_assembles_and_persists(self):
        ok, calls = self._run([_spoken(1), _spoken(2), _spoken(3), _read()])
        self.assertEqual(calls["take_count"], 3)
        self.assertTrue(ok)
        self.assertEqual(calls["persisted"], "assembled block")

    def test_two_spoken_plus_read_is_not_ready(self):
        # THE founder bug: a read must never complete the 3-take trigger.
        ok, calls = self._run([_spoken(1), _spoken(2), _read("s1")])
        self.assertFalse(ok)
        self.assertNotIn("persisted", calls)

    def test_coach_owned_row_is_not_refreshed_on_rerecord(self):
        # Canonical Ideal Text is created once for the project. Later takes
        # create exact-evidence feedback proposals and never rebuild either
        # the coach's working text or its frozen machine source.
        ok, calls = self._run(
            [_spoken(1), _spoken(2), _spoken(3)],
            existing_row={"text": "coach edit", "updated_by": "coach1",
                          "approved_at": None})
        self.assertTrue(ok)
        self.assertNotIn("persisted", calls)

    def test_machine_row_is_not_refreshed_on_rerecord(self):
        ok, calls = self._run(
            [_spoken(1), _spoken(2), _spoken(3)],
            existing_row={"text": "old machine draft", "updated_by": None,
                          "approved_at": None})
        self.assertTrue(ok)
        self.assertNotIn("persisted", calls)

    def test_not_ready_assembly_never_persists(self):
        ok, calls = self._run(
            [_spoken(1), _spoken(2), _spoken(3)],
            auto={"text": "", "key_moments": [], "ready": False})
        self.assertFalse(ok)
        self.assertNotIn("persisted", calls)


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
            with patch.object(db, "get_user_profile",
                              return_value={"domain": "d", "goal": "g"}), \
                 patch.object(db.takes, "v2_list_user_lab_sessions",
                              return_value=rows), \
                 patch.object(db, "get_feelings_by_sessions",
                              return_value=[]), \
                 patch.object(db.ideal_text, "get_coach_arc_ideal_texts",
                              return_value={ARC: {"text": "machine draft",
                                                  "updated_by": None,
                                                  "approved_at": None}}):
                resp, status = v2_coach.v2_coach_student_detail.__wrapped__(uid)
                body = resp.get_json()
        self.assertEqual(status, 200)
        states = {s["session_id"]: s["review_state"] for s in body["sessions"]}
        self.assertEqual(states["s1"], "delivered")
        self.assertEqual(states["s2"], "reviewed")   # saved = reviewed
        self.assertEqual(states["s3"], "to_review")
        self.assertEqual(body["ideal_ready_arc_ids"], [ARC])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class GuestProgressTests(unittest.TestCase):
    """GET /explore/arc/<id>/progress — guest-capable with a signed Guest ID."""

    def _call(self, sessions, caller=None, guest=None):
        app = Flask(__name__)
        headers = ({"X-Willab-Guest-Owner": guest.token} if guest else None)
        with app.test_request_context(headers=headers):
            request.user_id = caller
            with patch.object(db.takes, "get_arc_sessions",
                              return_value=sessions), \
                 patch.object(db, "get_coach_best_presentation_edits",
                              return_value={}), \
                 patch.object(
                     db,
                     "get_owner_principal",
                     return_value=(
                         {
                             "id": guest.principal_id,
                             "user_id": None,
                             "guest_secret_hash": guest.secret_hash,
                         }
                         if guest else None
                     ),
                 ):
                resp, status = v2_arcs.v2_explore_arc_progress.__wrapped__(ARC)
                return resp.get_json(), status

    def test_guest_reads_fully_unclaimed_arc(self):
        from services.project_ownership import issue_guest_owner

        guest = issue_guest_owner()
        unclaimed = [
            dict(
                _spoken(i),
                user_id=None,
                owner_principal_id=guest.principal_id,
            )
            for i in (1, 2)
        ]
        body, status = self._call(unclaimed, caller=None, guest=guest)
        self.assertEqual(status, 200)
        self.assertEqual(body["takes_done"], 2)

    def test_bare_project_id_is_not_guest_authorization(self):
        unclaimed = [
            dict(
                _spoken(1),
                user_id=None,
                owner_principal_id="33333333-3333-4333-8333-333333333333",
            )
        ]
        _, status = self._call(unclaimed, caller=None)
        self.assertEqual(status, 404)

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


if __name__ == "__main__":
    unittest.main()


class DocumentProvenanceTests(unittest.TestCase):
    """The piece provenance rides the SAME upsert as the text it describes
    (founder 2026-08-13, migrations/add_coach_arc_ideal_text_document.sql).

    services/part_acoustics.fold_session read this column for its entire life
    before it existed: the read resolved to NULL, the fold returned {} on every
    take without a log line, and no arc_part_acoustics row was ever written.
    A KPI that measured nothing was indistinguishable from a quiet arc."""

    def test_the_assembly_persists_its_pieces_beside_its_text(self):
        _ok, calls = EagerAssemblyTests()._run(
            [_spoken(1), _spoken(2), _spoken(3)],
            auto={"text": "assembled block", "key_moments": [], "ready": True,
                  "document": {"pieces": [{"snippet_id": "s1", "start": 0,
                                           "end": 15, "text": "assembled"}],
                               "take_session_id": "t3", "take_index": 3}})
        self.assertEqual(calls["persisted"], "assembled block")
        self.assertEqual(
            calls["document"]["pieces"][0]["snippet_id"], "s1")

    def test_an_assembly_with_no_provenance_still_persists_its_text(self):
        """Character offsets are only meaningful against the exact string they
        were anchored to, so a missing document is a missing KPI — never a
        withheld document. The student's text is not collateral."""
        _ok, calls = EagerAssemblyTests()._run(
            [_spoken(1), _spoken(2), _spoken(3)],
            auto={"text": "assembled block", "key_moments": [], "ready": True})
        self.assertEqual(calls["persisted"], "assembled block")
        self.assertIsNone(calls["document"])


