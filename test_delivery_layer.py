"""willab — the delivery layer (founder 2026-07-15).

Route-level tests (test_arc_unlock.py harness): the per-take FEEDBACK page,
the one-block IDEAL TEXT (coach review/approve + student notebook), the coach
Save/Publish flow with the 4-bubble delivery, and the async-analysis state
fold on the readout GETs.

FENCES verified: feedback carries NO scores / potentiometer / acoustic_read;
a locked take leaks NO content; the student never sees an unapproved ideal
text; the user's notebook save never touches the coach canonical (L1).

Run: python3 -m unittest test_delivery_layer
"""
from __future__ import annotations

import json
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
T1, T2, T3 = "s1", "s2", "s3"
READ1 = "r1"


def _sessions():
    rows = []
    for i, sid in enumerate((T1, T2, T3), start=1):
        rows.append({
            "id": sid, "user_id": "u1", "arc_id": ARC, "take_index": i,
            "created_at": f"2026-07-1{i}T10:00:00Z",
            "intake_context": {"topic": "Demo",
                               "slides": [{"title": "One"}]},
            "results_published_at": None,
            "recording_kind": "spoken", "paired_session_id": None,
            "coach_feedback_saved_at": f"2026-07-1{i}T11:00:00Z",
        })
    rows.append({
        "id": READ1, "user_id": "u1", "arc_id": ARC, "take_index": 1,
        "created_at": "2026-07-11T12:00:00Z",
        "intake_context": {"topic": "Demo"},
        "results_published_at": None,
        "recording_kind": "read", "paired_session_id": T1,
        "coach_feedback_saved_at": None,
    })
    return rows


def _snips(sid):
    # The real pipeline stamps metrics.recording_kind per session — the READ
    # session's pieces carry 'read' (this is what labels its key moments).
    kind = "read" if sid == READ1 else "spoken"
    return [{
        "id": f"{sid}-p0", "session_id": sid,
        "transcript": f"raw words of {sid}",
        "audio_segment_path": "https://x/p.webm",
        "start_offset_ms": 0, "duration_ms": 4000,
        "metrics": {"piece": {"index": 0, "slide_index": 0},
                    "recording_kind": kind,
                    "acoustic_read": {"potentiometer": 0.8,
                                      "outside_normal_range": True},
                    "overall_score": 0.9},
    }]


class _FeedbackHarness(unittest.TestCase):
    """Shared harness for GET /explore/arc/<id>/feedback route tests.

    ``confidence`` / ``surfaced`` / ``video_ref`` parameterize the blind panel
    verdict and the coach's draft on EVERY snippet, so tests can steer what the
    key-moments SELECT sees.

    RE-POINTED 2026-08-14 (founder): the knob used to be ``label_value``, a
    `training_labels` direction over challenge/threat. That construct is
    retired and its coach control was deleted 2026-08-07, so the selector it
    fed had been returning nothing on every real session since — this page's
    key moments were empty in production while these tests passed. A key
    moment is now confidence quorum = yes (`conf-q-v1`), so the fixture states
    a panel verdict instead of a direction."""

    @staticmethod
    def _panel(value):
        """Two QUORUM-lane raters agreeing — a settled verdict. `None` = the
        panel never rated it, which settles nothing."""
        if value is None:
            return []
        return [{"rater_id": "coach1", "lane": "coach", "value": value},
                {"rater_id": "peer1", "lane": "game_peer", "value": value}]

    def setUp(self):
        self.app = Flask(__name__)
        self._p = [patch("routes.v2.arcs._arc_owned_by_caller",
                                lambda a: (True, _sessions()))]
        for p in self._p:
            p.start()

    def tearDown(self):
        for p in self._p:
            p.stop()

    def _call(self, entitled=False, caller="u1", confidence="yes",
              surfaced=True, video_ref=None):
        with self.app.test_request_context():
            request.user_id = caller
            with patch("services.arc_entitlement.is_arc_entitled",
                       return_value=entitled), \
                 patch.object(v2, "is_admin", return_value=False), \
                 patch.object(v2, "is_coach", return_value=False), \
                 patch.object(v2.db, "get_snippets_by_session",
                              side_effect=lambda sid: _snips(sid)), \
                 patch.object(v2.db, "get_coach_snippet_drafts",
                              side_effect=lambda sid: [{
                                  "snippet_id": f"{sid}-p0",
                                  "surfaced": surfaced,
                                  "note": "This is the turn.",
                                  "transcript_corrected": f"corrected {sid}",
                                  "breakthrough_video_ref": video_ref,
                              }]), \
                 patch.object(v2.db, "get_confidence_labels_by_snippet_ids",
                              side_effect=lambda ids: {
                                  str(i): self._panel(confidence)
                                  for i in ids}), \
                 patch.object(v2.db, "get_user_transcript_edits",
                              return_value=[]), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=None), \
                 patch.object(v2.db, "v2_get_student_details",
                              return_value={"credits": 7}):
                resp, status = v2.v2_explore_arc_feedback.__wrapped__(ARC)
                return resp.get_json(), status


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class FeedbackRouteTests(_FeedbackHarness):

    def test_entitled_unlocks_all_and_folds_read_moments(self):
        body, status = self._call(entitled=True)
        takes = {t["take_index"]: t for t in body["takes"]}
        for ti in (1, 2, 3):
            self.assertFalse(takes[ti].get("locked", False))
        # full text prefers the coach correction (A1)
        self.assertEqual(takes[2]["full_text"], "corrected s2")
        # take 1's key moments include the paired READ's moment
        kinds = {m["recording_kind"] for m in takes[1]["key_moments"]}
        self.assertIn("spoken", kinds)
        self.assertIn("read", kinds)
        m = takes[1]["key_moments"][0]
        self.assertEqual(m["comment_text"], "This is the turn.")
        self.assertEqual(m["slide_index"], 0)
        self.assertEqual(m["audio_ref"], "https://x/p.webm")

    def test_no_scores_or_potentiometer_anywhere(self):
        body, _ = self._call(entitled=True)
        raw = json.dumps(body)
        for banned in ("potentiometer", "acoustic_read", "overall_score",
                       "outside_normal_range", "rank"):
            self.assertNotIn(banned, raw)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class CoachVideoOnAKeyMomentTests(_FeedbackHarness):
    """BE-6 (founder fix-pack 2026-07-16), re-pointed 2026-08-14: a
    coach-SURFACED key moment carries the coach's video on the feedback page
    (same fields, same comment_video_ref lane, no badge). The panel verdict
    only SELECTS — it is never serialized (AC-9 / blind coach).

    This class used to be ThreatKeyMomentTests and turned on threat-vs-
    challenge, a distinction that no longer exists: the two surfaces reading
    that construct did not even agree on it (the game counted challenge only,
    this page counted challenge OR threat, so one moment was a key moment here
    and a wrong answer there). One construct now, so there is one rule."""

    VIDEO = "https://x/coach-video.webm"

    def test_key_moment_with_video_surfaces(self):
        body, status = self._call(entitled=True, video_ref=self.VIDEO)
        self.assertEqual(status, 200)
        takes = {t["take_index"]: t for t in body["takes"]}
        moments = takes[1]["key_moments"]
        self.assertTrue(moments)
        for m in moments:
            self.assertEqual(m["comment_video_ref"], self.VIDEO)
            self.assertEqual(m["comment_text"], "This is the turn.")
        # the paired READ's key moment folds in too
        kinds = {m["recording_kind"] for m in moments}
        self.assertEqual(kinds, {"spoken", "read"})

    def test_the_coach_video_goes_out_RESOLVED_not_raw(self):
        """Deck slice 4 (founder 2026-08-11): the coach's video now plays
        inside the chunk modal, over the student's own text — so a dead one
        is dead in front of their words.

        It was the last ref still served raw. A coach video is stored as a
        PUBLIC url on the coach bucket's base, and R2 only answers on that
        base once the bucket's dev URL is on or a custom domain is attached:
        the healthy-looking row that 403s on every play — exactly the class
        audio_ref_resolver was written for, and which the audio beside it
        has been signed against since 2026-08-10."""
        from unittest.mock import patch
        seen = []

        def _fake(ref, **kw):
            seen.append(ref)
            return f"signed::{ref}" if ref else ref

        with patch("services.audio_ref_resolver.resolve_playable_ref", _fake):
            body, status = self._call(entitled=True, video_ref=self.VIDEO)
        self.assertEqual(status, 200)
        takes = {t["take_index"]: t for t in body["takes"]}
        for m in takes[1]["key_moments"]:
            self.assertEqual(m["comment_video_ref"], f"signed::{self.VIDEO}")
        # …and it went through the SAME resolver as the audio beside it.
        self.assertIn(self.VIDEO, seen)

    def test_a_moment_with_no_video_stays_none_never_a_signed_nothing(self):
        body, _ = self._call(entitled=True, video_ref=None)
        takes = {t["take_index"]: t for t in body["takes"]}
        for m in takes[1]["key_moments"]:
            self.assertIsNone(m["comment_video_ref"])

    def test_key_moment_without_surfaced_stays_hidden(self):
        body, _ = self._call(entitled=True, surfaced=False,
                             video_ref=self.VIDEO)
        for t in body["takes"]:
            self.assertEqual(t.get("key_moments"), [])
        # nothing leaks around the surfaced gate — not even the video ref
        self.assertNotIn(self.VIDEO, json.dumps(body))

    def test_only_a_settled_YES_is_a_key_moment(self):
        # "no" and the ambiguous class are settled verdicts too — they are
        # simply not this one. None = never rated.
        for value in ("no", "neutral", None):
            body, _ = self._call(entitled=True, confidence=value,
                                 video_ref=self.VIDEO)
            for t in body["takes"]:
                self.assertEqual(t.get("key_moments"), [], value)

    def test_the_verdict_is_never_serialized(self):
        # the panel verdict SELECTS the moment but never ships (AC-9 / blind
        # coach): no verdict field, no confidence value, no retired construct.
        for value in ("yes",):
            body, _ = self._call(entitled=True, confidence=value,
                                 video_ref=self.VIDEO)
            raw = json.dumps(body)
            for banned in ("threat", "challenge", "confidence", "quorum"):
                self.assertNotIn(banned, raw)
            takes = {t["take_index"]: t for t in body["takes"]}
            for m in takes[1]["key_moments"]:
                self.assertEqual(set(m.keys()), {
                    "snippet_id", "take_session_id", "slide_index",
                    "recording_kind", "transcript", "audio_ref",
                    "start_offset_ms", "duration_ms", "comment_text",
                    "comment_video_ref",
                })

    def test_breakthrough_badge_remains_challenge_only(self):
        # BE-6 widens the key-moments SELECT, not the badge: a threat mark
        # is still never a breakthrough (services/challenge_threat.py).
        from services.challenge_threat import detect_breakthroughs
        self.assertEqual(detect_breakthroughs([
            {"id": "t1", "direction": "threat"},
            {"id": "c1", "direction": "challenge"},
        ]), {"c1"})


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class IdealTextRoutesTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)

    def test_coach_get_prefers_saved_block_over_auto(self):
        # updated_by set = a human owns the block → source "coach"
        # (updated_by NULL would be the eager MACHINE draft → "machine").
        with self.app.test_request_context():
            request.user_id = "coach1"
            with patch.object(v2.db, "get_arc_sessions",
                              return_value=_sessions()), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value={"text": "coach block",
                                            "updated_by": "coach1",
                                            "approved_at": None}):
                resp, status = v2.v2_coach_get_ideal_text.__wrapped__(ARC)
                body = resp.get_json()
        self.assertEqual(status, 200)
        self.assertEqual(body["source"], "coach")
        self.assertEqual(body["text"], "coach block")
        self.assertEqual(body["assembly_state"], "ready")
        self.assertFalse(body["approved"])

    def test_coach_get_falls_back_to_auto(self):
        # ≥3 spoken takes + no persisted row → the cold lazy fallback still
        # serves (and eager-persists for next open) — the panel is never dead.
        with self.app.test_request_context():
            request.user_id = "coach1"
            with patch.object(v2.db, "get_arc_sessions",
                              return_value=_sessions()), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=None), \
                 patch("services.ideal_text_block.maybe_assemble_ideal_text",
                       return_value=True), \
                 patch("services.ideal_text_block.assemble_ideal_text_block",
                       return_value={"text": "auto block",
                                     "key_moments": [], "ready": True}):
                resp, status = v2.v2_coach_get_ideal_text.__wrapped__(ARC)
                body = resp.get_json()
        self.assertEqual(status, 200)
        self.assertEqual(body["source"], "auto")
        self.assertEqual(body["text"], "auto block")
        self.assertEqual(body["assembly_state"], "ready")

    def test_approve_persists_auto_when_no_block_saved(self):
        with self.app.test_request_context():
            request.user_id = "coach1"
            with patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=None), \
                 patch("services.ideal_text_block.assemble_ideal_text_block",
                       return_value={"text": "auto block",
                                     "key_moments": [], "ready": True}), \
                 patch.object(v2.db, "upsert_coach_arc_ideal_text",
                              return_value=True) as m_up:
                resp, status = v2.v2_coach_approve_ideal_text.__wrapped__(ARC)
        self.assertEqual(status, 200)
        kw = m_up.call_args.kwargs
        self.assertTrue(kw["approve"])
        self.assertEqual(m_up.call_args.args[1], "auto block")

    def test_approve_409_when_nothing_assembled(self):
        with self.app.test_request_context():
            request.user_id = "coach1"
            with patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=None), \
                 patch("services.ideal_text_block.assemble_ideal_text_block",
                       return_value={"text": "", "key_moments": [],
                                     "ready": False}):
                resp, status = v2.v2_coach_approve_ideal_text.__wrapped__(ARC)
        self.assertEqual(status, 409)
        self.assertEqual(resp.get_json()["code"], "IDEAL_TEXT_EMPTY")

    def test_notes_put_never_touches_canonical(self):
        with self.app.test_request_context(json={"text": "my edited copy"}):
            request.user_id = "u1"
            with patch("routes.v2.explore_ideal_text._arc_owned_by_caller",
                              lambda a: (True, _sessions())), \
                 patch.object(v2.db, "upsert_user_arc_ideal_notes",
                              return_value=True) as m_notes, \
                 patch.object(v2.db, "upsert_coach_arc_ideal_text") as m_canon:
                resp, status = v2.v2_explore_put_ideal_notes.__wrapped__(ARC)
        self.assertEqual(status, 200)
        m_notes.assert_called_once_with(ARC, "u1", "my edited copy")
        m_canon.assert_not_called()   # L1 — the canonical is untouched


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SavePublishTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)

    def test_save_feedback_persists_body_then_stamps(self):
        # The FE sends the OLD publish body at Save (snippets + labels +
        # insights_payload) — snippets/labels must PERSIST (the coach's work
        # is otherwise lost); insights_payload is ignored (publish-time only —
        # persisting it early would leak the coach layer to the readout).
        sid = "11111111-1111-4111-8111-111111111111"
        snip = "22222222-2222-4222-8222-222222222222"
        body = {
            "snippets": [{"id": snip, "note": "Key turn.", "tag": "strong",
                          "surfaced": True, "direction": "challenge"}],
            "labels": [{"snippet_id": snip, "value": "challenge"}],
            "insights_payload": {"overall_message": "ignored",
                                 "snippet_notes": []},
            "notify_client": False,
        }
        with self.app.test_request_context(json=body):
            request.user_id = "coach1"
            with patch.object(v2.db, "v2_get_session_by_id",
                              return_value={"id": sid}), \
                 patch.object(v2.db, "get_snippets_by_session",
                              return_value=[{"id": snip}]), \
                 patch("routes.v2.coach._save_coach_snippet_lanes",
                              return_value=None) as m_lanes, \
                 patch("services.training_labels.validate_publish_labels",
                       side_effect=lambda raw, ids, require_all: raw), \
                 patch.object(v2.db, "upsert_training_labels",
                              return_value=1) as m_labels, \
                 patch.object(v2.db, "set_session_insights_payload") as m_ip, \
                 patch.object(v2.db, "set_session_feedback_saved",
                              return_value=True) as m_save:
                resp, status = v2.v2_coach_save_feedback.__wrapped__(sid)
        self.assertEqual(status, 200)
        out = resp.get_json()
        self.assertTrue(out["saved"])
        self.assertEqual(out["snippets_saved"], 1)
        # the snippet went through the shared two-lane helper (direction alias
        # folded, id stripped)
        args = m_lanes.call_args.args
        self.assertEqual(args[1], snip)
        self.assertEqual(args[2]["direction_label"], "challenge")
        self.assertNotIn("id", args[2])
        m_labels.assert_called_once()
        m_ip.assert_not_called()      # insights NEVER persisted at Save
        m_save.assert_called_once_with(sid)

    def test_save_feedback_no_body_still_stamps(self):
        sid = "11111111-1111-4111-8111-111111111111"
        with self.app.test_request_context(json={}):
            request.user_id = "coach1"
            with patch.object(v2.db, "v2_get_session_by_id",
                              return_value={"id": sid}), \
                 patch("routes.v2.coach._save_coach_snippet_lanes") as m_lanes, \
                 patch.object(v2.db, "set_session_feedback_saved",
                              return_value=True) as m_save:
                resp, status = v2.v2_coach_save_feedback.__wrapped__(sid)
        self.assertEqual(status, 200)
        m_lanes.assert_not_called()
        m_save.assert_called_once_with(sid)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class PublishRouteContractTests(unittest.TestCase):
    """The publish contract points after the 2026-07-17 FE handoff:
    /publish-analysis is THE door (the FE relay targets it since their
    63be223); the briefly-restored legacy /publish alias is retired; the
    review-state read + approve-without-publish routes stand."""

    def _rules(self):
        app = Flask(__name__)
        app.register_blueprint(v2.v2_bp, url_prefix="/v2")
        return {r.rule: r.endpoint for r in app.url_map.iter_rules()}

    def test_publish_analysis_is_the_only_publish_door(self):
        rules = self._rules()
        self.assertIn("/v2/coach/arc/<arc_id>/publish-analysis", rules)
        self.assertNotIn("/v2/coach/arc/<arc_id>/publish", rules)  # retired

    def test_wrapup_contract_points_stand(self):
        rules = self._rules()
        self.assertIn("/v2/coach/arc/<arc_id>/review-state", rules)
        self.assertIn("/v2/coach/arc/<arc_id>/ideal-text/approve", rules)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class AsyncReadoutStateTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)

    def _guest(self, session):
        sid = "33333333-3333-4333-8333-333333333333"
        with self.app.test_request_context():
            request.user_id = None
            with patch.object(v2.db, "v2_get_session_by_id",
                              return_value=dict(session, id=sid)):
                resp, status = \
                    v2.v2_guest_get_recording_readout.__wrapped__(sid)
                return resp.get_json(), status

    def test_processing_state_served_without_readout(self):
        body, status = self._guest(
            {"user_id": None, "analysis_state": "processing"})
        self.assertEqual(status, 200)
        self.assertEqual(body["state"], "processing")
        self.assertEqual(body["analysis_state"], "processing")
        self.assertIsNone(body["readout"])

    def test_failed_state_served(self):
        body, status = self._guest(
            {"user_id": None, "analysis_state": "failed"})
        self.assertEqual(body["state"], "failed")
        self.assertEqual(body["analysis_state"], "failed")

    def test_terminal_serves_analysis_state_ready(self):
        # Past processing|failed the poll's terminal is analysis_state=ready —
        # the lifecycle `state` stays readout_ready/review_pending/… (the FE
        # must NOT need to enumerate those to stop polling).
        from unittest.mock import MagicMock
        import services.lab_recording as lab
        orig = lab.build_readout_from_session
        lab.build_readout_from_session = MagicMock(
            return_value={"snippets": []})
        try:
            body, status = self._guest(
                {"user_id": None, "analysis_state": "ready",
                 "results_published_at": None, "status": "x"})
        finally:
            lab.build_readout_from_session = orig
        self.assertEqual(status, 200)
        self.assertEqual(body["analysis_state"], "ready")
        self.assertEqual(body["state"], "readout_ready")

    def test_async_flag_default_off(self):
        import os
        old = os.environ.pop("ASYNC_ANALYSIS_ENABLED", None)
        try:
            self.assertFalse(v2._async_analysis_enabled())
            os.environ["ASYNC_ANALYSIS_ENABLED"] = "1"
            self.assertTrue(v2._async_analysis_enabled())
        finally:
            if old is None:
                os.environ.pop("ASYNC_ANALYSIS_ENABLED", None)
            else:
                os.environ["ASYNC_ANALYSIS_ENABLED"] = old


if __name__ == "__main__":
    unittest.main()
