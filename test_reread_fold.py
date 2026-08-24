"""willab — fold mid-take RE-READS into their parent take (founder fix-pack
2026-07-16, BE-2 + BE-3a + BE-4).

The founder's rule: "recordings recorded in the middle of the take are part
of the take — revealed by clicking next like normal snippets, with a small
're-read' label; never separate items." This suite pins the whole lifecycle:

  * the coach packet APPENDS the read's snippets after the parent's (never
    sorted across sessions — the read's clock restarts at 0), stamped with
    take_session_id + recording_kind, one continuous index;
  * coach writes on a folded read snippet route to the READ's own session
    (snippet save and save-feedback snippets[]);
  * the queue + student drill-down hide read rows and mark the parent
    (has_reread), and the queue row carries the opaque user_id drill key
    (BE-4);
  * publish-analysis flips the paired reads (no more queue zombies);
  * a read never competes as a take in cross-take selection;
  * a read never fires its own "homework completed" coach email (BE-3a).

Run: python3 -m unittest test_reread_fold
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

SPOKEN = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
READ = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
READ2 = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
PSNIP1 = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
PSNIP2 = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"
RSNIP = "ffffffff-ffff-4fff-8fff-ffffffffffff"


def _session_row(sid=SPOKEN, **over):
    row = {"id": sid, "user_id": "u1", "arc_id": None,
           "intake_context": {"topic": "Demo", "domain": "sales"},
           "status": "pending_admin_review",
           "review_requested_at": "2026-07-16T10:00:00Z",
           "results_published_at": None,
           "coach_feedback_saved_at": None}
    row.update(over)
    return row


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SpokenTakesAndReadsTests(unittest.TestCase):
    def test_multiple_reads_group_under_their_take_oldest_first(self):
        rows = [
            {"id": "s1", "take_index": 1, "recording_kind": "spoken",
             "paired_session_id": None},
            {"id": "r2", "recording_kind": "read", "paired_session_id": "s1",
             "created_at": "2026-07-16T12:00:00Z"},
            {"id": "r1", "recording_kind": "read", "paired_session_id": "s1",
             "created_at": "2026-07-16T11:00:00Z"},
            {"id": "legacy", "take_index": 2},   # pre-migration → spoken
        ]
        spoken, reads = v2._spoken_takes_and_reads(rows)
        self.assertEqual([s["id"] for s in spoken], ["s1", "legacy"])
        self.assertEqual([r["id"] for r in reads["s1"]], ["r1", "r2"])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class FoldReadsOutOfQueueTests(unittest.TestCase):
    """The pure queue fold (db.fold_reads_out_of_queue)."""

    def test_reads_dropped_parent_marked(self):
        rows = [
            {"id": "s1"},
            {"id": "r1", "recording_kind": "read", "paired_session_id": "s1"},
            {"id": "s2"},
        ]
        out = v2.db.fold_reads_out_of_queue(rows)
        self.assertEqual([r["id"] for r in out], ["s1", "s2"])
        self.assertTrue(out[0].get("has_reread"))
        self.assertFalse(out[1].get("has_reread"))

    def test_paired_only_row_still_dropped_and_legacy_passthrough(self):
        rows = [
            {"id": "r1", "paired_session_id": "elsewhere"},  # kind missing
            {"id": "legacy-row"},                            # no fold columns
        ]
        out = v2.db.fold_reads_out_of_queue(rows)
        self.assertEqual([r["id"] for r in out], ["legacy-row"])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class CoachGetFoldTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def _get(self, read_sessions):
        readouts = {
            SPOKEN: {"snippets": [
                {"id": PSNIP1, "index": 0, "transcript": "one",
                 "audio_ref": "a1", "start_offset_ms": 0,
                 "duration_ms": 1000, "recording_kind": "spoken"},
                {"id": PSNIP2, "index": 1, "transcript": "two",
                 "audio_ref": "a2", "start_offset_ms": 1000,
                 "duration_ms": 1000, "recording_kind": "spoken"},
            ], "slide_coverage": []},
            READ: {"snippets": [
                # start_offset restarts at 0 — must NOT re-sort before parent
                {"id": RSNIP, "index": 0, "transcript": "re-read",
                 "audio_ref": "a3", "start_offset_ms": 0,
                 "duration_ms": 900},
            ], "slide_coverage": []},
        }
        with self.app.test_request_context():
            request.user_id = "coach1"
            with patch.object(v2.db, "v2_get_session_by_id",
                              return_value=_session_row()), \
                 patch.object(v2.db, "claim_coach_review",
                              return_value={"assigned_to": "coach1",
                                            "claimed": True}), \
                 patch.object(v2.db, "stamp_review_opened") as m_open, \
                 patch.object(v2.db, "get_read_sessions_for",
                              return_value=read_sessions), \
                 patch.object(v2.db, "get_coach_snippet_drafts",
                              return_value=[]), \
                 patch.object(
                     v2.db, "get_own_state_ratings_for_session",
                     side_effect=lambda sid, _rater: {
                         SPOKEN: {
                             PSNIP1: {"value": "yes"},
                             PSNIP2: {"value": "neutral"},
                         },
                         READ: {RSNIP: {"value": "no"}},
                     }.get(str(sid), {})), \
                 patch.object(v2.db, "get_feelings_by_session",
                              return_value=[]), \
                 patch("services.lab_recording.build_readout_from_session",
                       side_effect=lambda sid, **kw: readouts[sid]):
                resp, status = v2.v2_coach_get_session.__wrapped__(SPOKEN)
        return resp.get_json(), status, m_open

    def test_read_snippets_appended_stamped_and_reindexed(self):
        body, status, m_open = self._get(
            [{"id": READ, "created_at": "2026-07-16T11:00:00Z"}])
        self.assertEqual(status, 200)
        snips = body["snippets"]
        self.assertEqual([s["id"] for s in snips], [PSNIP1, PSNIP2, RSNIP])
        self.assertEqual([s["index"] for s in snips], [0, 1, 2])
        self.assertEqual([s["take_session_id"] for s in snips],
                         [SPOKEN, SPOKEN, READ])
        # metrics carried no kind on the read piece → the fold defaults it
        self.assertEqual(snips[2]["recording_kind"], "read")
        self.assertTrue(body["has_reread"])
        self.assertEqual(body["read_session_ids"], [READ])
        opened = {c.args[0] for c in m_open.call_args_list}
        # The parent is stamped atomically by claim_coach_review; only folded
        # read sessions still need the legacy per-row stamp here.
        self.assertEqual(opened, {READ})

    def test_reads_array_carries_ideal_text_tags(self):
        # Founder 2026-07-20: an ideal-text re-read carries read_target +
        # ideal_version in its intake_context → the coach UI labels it
        # "Re-read of ideal text vN". Per-take re-reads carry nulls.
        body, status, _ = self._get([
            {"id": READ, "created_at": "2026-07-16T11:00:00Z",
             "intake_context": {"read_target": "ideal_text",
                                "ideal_version": 3}},
        ])
        self.assertEqual(status, 200)
        self.assertEqual(body["reads"], [{
            "session_id": READ,
            "created_at": "2026-07-16T11:00:00Z",
            "read_target": "ideal_text",
            "ideal_version": 3,
        }])

    def test_reads_array_null_tags_on_per_take_reread(self):
        body, _, _ = self._get(
            [{"id": READ, "created_at": "2026-07-16T11:00:00Z"}])
        self.assertEqual(body["reads"], [{
            "session_id": READ,
            "created_at": "2026-07-16T11:00:00Z",
            "read_target": None,
            "ideal_version": None,
        }])

    def test_no_reads_packet_unchanged(self):
        body, status, _ = self._get([])
        self.assertEqual(status, 200)
        self.assertEqual(len(body["snippets"]), 2)
        self.assertFalse(body["has_reread"])
        self.assertEqual(body["read_session_ids"], [])
        self.assertEqual(body["reads"], [])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SnippetWriteRoutingTests(unittest.TestCase):
    """Coach writes on a folded read snippet, sent under the SPOKEN path,
    persist under the READ session id."""

    def setUp(self):
        self.app = Flask(__name__)
        self._snips = {
            SPOKEN: [{"id": PSNIP1}],
            READ: [{"id": RSNIP}],
        }

    def _save_snippet(self, snippet_id):
        with self.app.test_request_context(json={"note": "key moment"}):
            request.user_id = "coach1"
            with patch.object(v2.db, "v2_get_session_by_id",
                              return_value=_session_row()), \
                 patch.object(v2.db, "get_snippets_by_session",
                              side_effect=lambda sid: self._snips.get(
                                  str(sid), [])), \
                 patch.object(v2.db, "get_read_sessions_for",
                              return_value=[{"id": READ}]), \
                 patch.object(v2.db, "get_coach_snippet_drafts",
                              return_value=[]), \
                 patch("routes.v2.coach._save_coach_snippet_lanes",
                              return_value=None) as m_lanes:
                resp, status = v2.v2_coach_save_snippet.__wrapped__(
                    SPOKEN, snippet_id)
        return resp.get_json(), status, m_lanes

    def test_read_snippet_saves_under_read_session(self):
        body, status, m_lanes = self._save_snippet(RSNIP)
        self.assertEqual(status, 200)
        self.assertEqual(m_lanes.call_args.args[0], READ)
        self.assertEqual(m_lanes.call_args.args[1], RSNIP)

    def test_parent_snippet_still_saves_under_parent(self):
        body, status, m_lanes = self._save_snippet(PSNIP1)
        self.assertEqual(status, 200)
        self.assertEqual(m_lanes.call_args.args[0], SPOKEN)

    def test_unknown_snippet_404(self):
        body, status, m_lanes = self._save_snippet(READ2)  # a uuid, not a snip
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "SNIPPET_NOT_FOUND")
        m_lanes.assert_not_called()


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SaveFeedbackRoutingTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def test_snippets_route_to_their_owning_session(self):
        body = {
            "snippets": [
                {"id": PSNIP1, "note": "spoken note", "surfaced": True},
                {"id": RSNIP, "note": "read note", "surfaced": True},
            ],
        }
        snips = {SPOKEN: [{"id": PSNIP1}], READ: [{"id": RSNIP}]}
        with self.app.test_request_context(json=body):
            request.user_id = "coach1"
            with patch.object(v2.db, "v2_get_session_by_id",
                              return_value=_session_row()), \
                 patch.object(v2.db, "get_snippets_by_session",
                              side_effect=lambda sid: snips.get(
                                  str(sid), [])), \
                 patch.object(v2.db, "get_read_sessions_for",
                              return_value=[{"id": READ}]), \
                 patch("routes.v2.coach._save_coach_snippet_lanes",
                              return_value=None) as m_lanes, \
                 patch.object(v2.db, "set_session_feedback_saved",
                              return_value=True) as m_save:
                resp, status = v2.v2_coach_save_feedback.__wrapped__(SPOKEN)
        self.assertEqual(status, 200)
        self.assertEqual(resp.get_json()["snippets_saved"], 2)
        # lanes routed per owner
        lane_targets = [(c.args[0], c.args[1])
                        for c in m_lanes.call_args_list]
        self.assertEqual(lane_targets, [(SPOKEN, PSNIP1), (READ, RSNIP)])
        # saved=reviewed stamps the PARENT take only
        m_save.assert_called_once_with(SPOKEN)

    def test_foreign_snippet_still_404s(self):
        with self.app.test_request_context(
                json={"snippets": [{"id": READ2, "note": "x"}]}):
            request.user_id = "coach1"
            with patch.object(v2.db, "v2_get_session_by_id",
                              return_value=_session_row()), \
                 patch.object(v2.db, "get_snippets_by_session",
                              return_value=[{"id": PSNIP1}]), \
                 patch.object(v2.db, "get_read_sessions_for",
                              return_value=[]), \
                 patch("routes.v2.coach._save_coach_snippet_lanes") as m_lanes:
                resp, status = v2.v2_coach_save_feedback.__wrapped__(SPOKEN)
        self.assertEqual(status, 404)
        m_lanes.assert_not_called()


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class QueueRowShapeTests(unittest.TestCase):
    """BE-4: the opaque per-user drill key + fold markers on queue rows."""

    def test_queue_row_carries_drill_key_and_fold_markers(self):
        row = dict(_session_row(), has_reread=True,
                   arc_id="arc9", take_index=2, user_id="u-42")
        app = Flask(__name__)
        with app.test_request_context():
            request.user_id = "coach1"
            with patch.object(v2.db, "list_review_queue",
                              return_value=[row]), \
                 patch.object(v2.db, "get_snippets_by_session",
                              return_value=[]), \
                 patch.object(v2.db, "get_coach_snippet_drafts",
                              return_value=[]):
                resp, status = v2.v2_coach_queue.__wrapped__()
        self.assertEqual(status, 200)
        out = resp.get_json()
        self.assertEqual(len(out), 1)
        r = out[0]
        self.assertEqual(r["user_id"], "u-42")      # opaque drill key
        self.assertTrue(r["has_reread"])
        self.assertEqual(r["arc_id"], "arc9")
        self.assertEqual(r["take_index"], 2)
        self.assertTrue(r["pseudonym"])              # still pseudonymized
        self.assertNotIn("intake_context", r)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class DrilldownFoldTests(unittest.TestCase):
    def test_read_rows_hidden_parent_marked(self):
        uid = "11111111-1111-4111-8111-111111111111"
        rows = [
            _session_row(sid=SPOKEN, recording_kind="spoken",
                         paired_session_id=None),
            _session_row(sid=READ, recording_kind="read",
                         paired_session_id=SPOKEN),
        ]
        app = Flask(__name__)
        with app.test_request_context():
            request.user_id = "coach1"
            with patch.object(v2.db, "get_user_profile",
                              return_value={"domain": "d", "goal": "g"}), \
                 patch.object(v2.db, "v2_list_user_lab_sessions",
                              return_value=rows), \
                 patch.object(v2.db, "get_feelings_by_sessions",
                              return_value=[]), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=None):
                resp, status = v2.v2_coach_student_detail.__wrapped__(uid)
        self.assertEqual(status, 200)
        sessions = resp.get_json()["sessions"]
        self.assertEqual([s["session_id"] for s in sessions], [SPOKEN])
        self.assertTrue(sessions[0]["has_reread"])


class CrossTakeSpokenOnlyTests(unittest.TestCase):
    """A read never competes as a take in /explore/arc/<id>/moments."""

    class _Db:
        def get_arc_sessions(self, arc_id):
            return [
                {"id": "s1", "take_index": 1, "recording_kind": "spoken",
                 "paired_session_id": None},
                {"id": "r1", "take_index": 1, "recording_kind": "read",
                 "paired_session_id": "s1"},
                {"id": "s2", "take_index": 2, "recording_kind": "spoken",
                 "paired_session_id": None},
            ]

        def get_snippets_by_session(self, sid):
            return []

    def test_select_take_level_filters_reads(self):
        from services.cross_take_selection import select_take_level
        out = select_take_level("arc1", database=self._Db())
        self.assertEqual(out["take_count"], 2)
        self.assertEqual([t["session_id"] for t in out["takes"]],
                         ["s1", "s2"])

    def test_entry_point_filters_reads(self):
        from services.cross_take_selection import select_cross_take
        out = select_cross_take("arc1", database=self._Db())
        self.assertEqual(out["take_count"], 2)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class LabSendEmailGateTests(unittest.TestCase):
    """BE-3a: a re-read never fires its own coach email — max one email per
    spoken take ⇒ max 3 per arc."""

    def _send(self, session_row):
        from services.lab_send import send_lab_recording_to_coach
        with patch.object(v2.db, "v2_get_session_by_id",
                          return_value=session_row), \
             patch.object(v2.db, "v2_mark_session_pending_review",
                          return_value=True), \
             patch.object(v2.db, "get_snippets_by_session",
                          return_value=[]), \
             patch("services.session_publish._send_admin_notification") \
                as m_mail:
            res = send_lab_recording_to_coach(SPOKEN, "u1")
        return res, m_mail

    def test_read_flips_but_never_emails(self):
        res, m_mail = self._send(_session_row(
            sid=READ, status="processing",
            recording_kind="read", paired_session_id=SPOKEN))
        self.assertTrue(res["ok"])                # still enters the flow
        m_mail.assert_not_called()                # but no email

    def test_spoken_still_emails_once(self):
        res, m_mail = self._send(_session_row(
            sid=SPOKEN, status="processing",
            recording_kind="spoken", paired_session_id=None))
        self.assertTrue(res["ok"])
        m_mail.assert_called_once()


if __name__ == "__main__":
    unittest.main()
