"""willab — the SINGLE-DELIVERABLE re-shape (founder 2026-07-17).

The product delivers ONE thing: the ideal text. Record a take → instant
ideal text vN (unverified) → the coach verifies in the background, always →
the verified text displays FREE. The ONLY paid item: opening the key-moment
explanations (5 credits, one-time per presentation). This is now the ONLY
behavior — the SINGLE_DELIVERABLE_ENABLED flag was retired.

Pinned here, token by token:
  BE-1  version bump on a CHANGED machine copy only; migration fallbacks;
        the L1 seam-smoothing pass exists and its contract is pinned.
  BE-2  the 3-take batch cap lifts (takes append forever).
  BE-3  VERIFY: snapshot + idempotency + the per-version verified bubble.
  BE-4  the student GET: both states FREE, never a 402; the coach's working
        text NEVER leaks unverified.
  BE-5  the 5-credit moments unlock (atomic; no grandfathering) + the gated
        explanations GET.
  BE-6  the $25 unlock and publish-analysis routes answer 410 (retired).

Run: python3 -m unittest test_single_deliverable
"""
from __future__ import annotations

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

try:
    from flask import Flask, jsonify, request
    from routes import v2_routes as v2
    from services.db import DatabaseService
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    jsonify = None
    request = None
    v2 = None
    DatabaseService = None
    _IMPORT_ERROR = e

ARC = "a1"
UID = "11111111-1111-4111-8111-111111111111"


def _row(**over):
    row = {"arc_id": ARC, "text": "machine text", "auto_text": "machine text",
           "updated_by": None, "approved_at": None, "version": 3,
           "verified_version": None, "verified_text": None}
    row.update(over)
    return row


class _Client:
    def __init__(self, missing=()):
        self.missing = missing
        self.upserts = []
        self._pending = None

    def table(self, name):
        return self

    def upsert(self, payload, on_conflict=None):
        self._pending = payload
        return self

    def insert(self, payload):
        self._pending = payload
        return self

    def execute(self):
        for col in self.missing:
            if col in (self._pending or {}):
                raise RuntimeError(
                    f'column "{col}" of relation "x" does not exist')
        self.upserts.append(self._pending)
        return SimpleNamespace(data=[self._pending])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class EvidenceCoordinateTests(unittest.TestCase):
    def test_deckless_feedback_keeps_an_explicit_unlinked_route(self):
        from routes.v2.explore_ideal_text import _with_evidence_coordinates

        rows = [{
            "id": "confident-voice:snippet-2",
            "take_session_id": "take-2",
            "span": {"start": 0, "end": 8},
        }]
        pieces = [{
            "take_session_id": "take-2",
            "slide_index": None,
            "start": 0,
            "end": 8,
        }]

        grounded = _with_evidence_coordinates(
            rows,
            arc_id="arc-1",
            served_text="One talk",
            pieces=pieces,
        )

        self.assertEqual(len(grounded), 1)
        self.assertIsNone(grounded[0]["evidence"]["slide_index"])
        self.assertEqual(grounded[0]["evidence"]["take_session_id"], "take-2")


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class VersionBumpTests(unittest.TestCase):
    """The version IS the spoken take count (founder 2026-08-05): take 1 →
    1.0, take 2 → 2.0, each one verified on its own.

    The change-detect rule below is the FALLBACK, kept for the case where
    the caller could not count the takes (a failed read). Writing a wrong
    absolute there would un-verify real coach work, so it fails closed to
    the old behaviour instead."""

    def _persist(self, row, text, missing=(), take_count=None):
        client = _Client(missing=missing)
        fake = SimpleNamespace(client=client,
                               get_coach_arc_ideal_text=lambda a: row)
        ok = DatabaseService.persist_auto_ideal_text(
            fake, ARC, text, take_count=take_count)
        return ok, client.upserts

    def test_take_count_is_the_version(self):
        ok, ups = self._persist(_row(version=1), "take two text",
                                take_count=2)
        self.assertTrue(ok)
        self.assertEqual(ups[0]["version"], 2)

    def test_take_count_pins_rather_than_increments(self):
        # Idempotence is the whole point: reassembling the SAME take count
        # lands on the same number instead of climbing. An idle re-open
        # can no longer bump the version and silently un-verify a text
        # nobody re-recorded.
        _, ups = self._persist(_row(version=2), "text a", take_count=2)
        self.assertEqual(ups[0]["version"], 2)
        _, ups2 = self._persist(_row(version=2), "text b changed",
                                take_count=2)
        self.assertEqual(ups2[0]["version"], 2)

    def test_take_count_bumps_even_when_the_text_is_identical(self):
        # The founder's bug: take 2 that barely moved the text used to
        # leave the badge frozen at 1.0. Each take is its own version now.
        _, ups = self._persist(_row(version=1), "machine text", take_count=2)
        self.assertEqual(ups[0]["version"], 2)

    def test_zero_or_bad_take_count_falls_back_to_change_detect(self):
        for bad in (0, -1, "2", None):
            _, ups = self._persist(_row(version=3), "a different text",
                                   take_count=bad)
            self.assertEqual(ups[0]["version"], 4, f"take_count={bad!r}")

    def test_new_row_starts_at_version_1(self):
        ok, ups = self._persist(None, "first text")
        self.assertTrue(ok)
        self.assertEqual(ups[0]["version"], 1)

    def test_changed_text_bumps_version_without_a_count(self):
        # Fallback lane only (take_count=None).
        ok, ups = self._persist(_row(version=3), "a different text")
        self.assertTrue(ok)
        self.assertEqual(ups[0]["version"], 4)

    def test_unchanged_text_keeps_version_without_a_count(self):
        ok, ups = self._persist(_row(version=3), "machine text")
        self.assertTrue(ok)
        self.assertNotIn("version", ups[0])   # no bump, verify stays stable

    def test_version_column_missing_still_writes_copies(self):
        ok, ups = self._persist(_row(version=None), "a different text",
                                missing=("version",))
        self.assertTrue(ok)
        self.assertEqual(len(ups), 1)
        self.assertNotIn("version", ups[0])
        self.assertEqual(ups[0]["auto_text"], "a different text")


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class VerifyDbTests(unittest.TestCase):
    """BE-3 — the verify snapshot semantics."""

    def _verify(self, row):
        client = _Client()
        fake = SimpleNamespace(client=client,
                               get_coach_arc_ideal_text=lambda a: row)
        out = DatabaseService.verify_ideal_text(fake, ARC, "coach1")
        return out, client.upserts

    def test_machine_row_snapshots_the_machine_copy(self):
        out, ups = self._verify(_row(version=3))
        self.assertEqual(out, "verified")
        self.assertEqual(ups[0]["verified_version"], 3)
        self.assertEqual(ups[0]["verified_text"], "machine text")
        self.assertEqual(ups[0]["verified_by"], "coach1")

    def test_coach_owned_row_snapshots_the_coach_text(self):
        out, ups = self._verify(_row(text="coach polished",
                                     updated_by="coach1"))
        self.assertEqual(out, "verified")
        self.assertEqual(ups[0]["verified_text"], "coach polished")

    def test_already_verified_current_version_is_idempotent(self):
        out, ups = self._verify(_row(version=3, verified_version=3))
        self.assertEqual(out, "already")
        self.assertEqual(ups, [])

    def test_new_version_after_verify_can_verify_again(self):
        out, ups = self._verify(_row(version=4, verified_version=3))
        self.assertEqual(out, "verified")
        self.assertEqual(ups[0]["verified_version"], 4)

    def test_nothing_to_verify(self):
        out, ups = self._verify(None)
        self.assertIsNone(out)
        out, ups = self._verify(_row(text="  ", auto_text="  "))
        self.assertIsNone(out)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class VerifyRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)

    def _post(self, *, sessions, outcome, row):
        with self.app.test_request_context(json={}):
            request.user_id = "coach1"
            with patch.object(v2.db, "get_arc_sessions",
                              return_value=sessions), \
                 patch.object(v2.db, "verify_ideal_text",
                              return_value=outcome), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=row), \
                 patch("services.arc_notifications.fire_ideal_verified") \
                    as m_fire:
                out = v2.v2_coach_verify_ideal_text.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, m_fire

    def test_verify_fires_versioned_bubble_to_owner(self):
        body, status, m_fire = self._post(
            sessions=[{"id": "s1", "user_id": "u1"}],
            outcome="verified", row=_row(version=5))
        self.assertEqual(status, 200)
        self.assertTrue(body["verified"])
        self.assertEqual(body["version"], 5)
        m_fire.assert_called_once()
        self.assertEqual(m_fire.call_args.args[1:], ("u1", ARC, 5))

    def test_already_verified_no_second_bubble(self):
        body, status, m_fire = self._post(
            sessions=[{"id": "s1", "user_id": "u1"}],
            outcome="already", row=_row(version=5, verified_version=5))
        self.assertEqual(status, 200)
        self.assertTrue(body["already_verified"])
        m_fire.assert_not_called()

    def test_nothing_to_verify_409(self):
        body, status, m_fire = self._post(
            sessions=[{"id": "s1", "user_id": "u1"}],
            outcome=None, row=None)
        self.assertEqual(status, 409)
        self.assertEqual(body["code"], "NOTHING_TO_VERIFY")
        m_fire.assert_not_called()


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class StudentGetSingleDeliverableTests(unittest.TestCase):
    """BE-4 — both states FREE; the coach's working text never leaks."""

    def setUp(self):
        self.app = Flask(__name__)

    def _get(self, row, *, entitled_moments=False, expl=None):
        with self.app.test_request_context():
            request.user_id = "u1"
            with patch("routes.v2.explore_ideal_text._arc_owned_by_caller",
                              return_value=(True, [])), \
                 patch("routes.v2.explore_ideal_text._moments_entitled",
                              return_value=entitled_moments), \
                 patch("routes.v2.explore_ideal_text._moment_explanations_map",
                              return_value=(expl or {})), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=row), \
                 patch.object(v2.db, "get_user_arc_ideal_notes",
                              return_value="notes"):
                out = v2.v2_explore_get_ideal_text.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status

    def test_unverified_serves_machine_copy_free(self):
        body, status = self._get(_row(version=2))
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "unverified")
        self.assertEqual(body["version"], 2)
        self.assertEqual(body["text"], "machine text")
        self.assertFalse(body["moments_unlocked"])
        self.assertEqual(body["notes_text"], "notes")
        # TOKENS now: the body used to quote a retired currency at the
        # wrong magnitude (5 credits vs a 2,500-token charge).
        self.assertEqual(body["price_tokens"], 2_500)
        self.assertNotIn("paywall", body)

    def test_verified_serves_the_snapshot(self):
        body, _ = self._get(_row(
            version=2, verified_version=2,
            verified_text="the verified snapshot",
            text="coach still editing", updated_by="coach1"))
        self.assertEqual(body["status"], "verified")
        self.assertEqual(body["text"], "the verified snapshot")

    def test_coach_working_text_never_leaks_unverified(self):
        # Coach owns the row, no machine copy, nothing verified → empty text,
        # NOT the coach's in-progress edit.
        body, _ = self._get(_row(text="coach secret", auto_text=None,
                                 updated_by="coach1", version=2))
        self.assertEqual(body["status"], "unverified")
        self.assertNotIn("coach secret", json.dumps(body))

    def test_key_moments_carry_id_anchor_has_explanation(self):
        text = ("[[moment:aaaa1111-aaaa-1111-aaaa-111111111111|"
                "bbbb2222-bbbb-2222-bbbb-222222222222]]hello there[[/moment]]")
        body, _ = self._get(
            _row(auto_text=text, text=text),
            expl={"aaaa1111-aaaa-1111-aaaa-111111111111": True})
        self.assertEqual(len(body["key_moments"]), 1)
        m = body["key_moments"][0]
        self.assertEqual(m["id"], "aaaa1111-aaaa-1111-aaaa-111111111111")
        # anchor = the inner span, a verbatim substring of `text` the FE
        # underlines (the FE DROPS a moment with no anchor — contract pin).
        self.assertEqual(m["anchor"], "hello there")
        self.assertIn(m["anchor"], body["text"])
        self.assertTrue(m["has_explanation"])

    def test_ac9_score_free(self):
        body, _ = self._get(_row())
        raw = json.dumps(body)
        for banned in ("potentiometer", "acoustic_read", "overall_score",
                       "slide_stickiness", "rank", "power_score"):
            self.assertNotIn(banned, raw)

    def test_optional_feedback_or_delivery_failure_never_hides_text(self):
        """Document availability is independent from every enrichment lane."""
        with patch(
            "routes.v2.explore_ideal_text._moment_playback_map",
            side_effect=RuntimeError("media signer unavailable"),
        ), patch.object(
            v2.db,
            "list_intervention_decision_history",
            side_effect=RuntimeError("feedback ledger unavailable"),
        ):
            body, status = self._get(_row(version=2))
        self.assertEqual(status, 200)
        self.assertEqual(body["version"], 2)
        self.assertEqual(body["text"], "machine text")
        self.assertEqual(body["decision_history"], [])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class CrucialBubbleFieldTests(unittest.TestCase):
    """Founder 2026-07-20 — the crucial-bubble fields on the student GET:
    title (latest take's topic), updated_at, latest_take_session_id.

    reread_done / reread_processing are RETIRED (founder 2026-08-05) with
    the read-out-loud lane. What stays pinned here is that HISTORICAL read
    rows are still never counted as takes — the teardown migration is run
    by hand, so those rows outlive this deploy."""

    def setUp(self):
        self.app = Flask(__name__)

    @staticmethod
    def _spoken(sid, ti, topic=None):
        return {"id": sid, "take_index": ti, "recording_kind": "spoken",
                "paired_session_id": None,
                "intake_context": {"topic": topic} if topic else {}}

    @staticmethod
    def _read(sid, paired, ctx=None, analysis_state=None):
        return {"id": sid, "take_index": None, "recording_kind": "read",
                "paired_session_id": paired, "intake_context": ctx or {},
                "analysis_state": analysis_state}

    def _get(self, row, sessions):
        with self.app.test_request_context():
            request.user_id = "u1"
            with patch("routes.v2.explore_ideal_text._arc_owned_by_caller",
                              return_value=(True, sessions)), \
                 patch("routes.v2.explore_ideal_text._moments_entitled", return_value=False), \
                 patch("routes.v2.explore_ideal_text._moment_explanations_map",
                              return_value={}), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=row), \
                 patch.object(v2.db, "get_user_arc_ideal_notes",
                              return_value=None):
                out = v2.v2_explore_get_ideal_text.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status

    def test_title_latest_take_wins_and_reads_excluded(self):
        body, _ = self._get(_row(updated_at="2026-07-20T10:00:00Z"), [
            self._spoken("t1", 1, topic="old topic"),
            self._spoken("t2", 2, topic="new topic"),
            self._read("r1", "t2", {"topic": "read topic must not win"}),
        ])
        self.assertEqual(body["title"], "new topic")
        self.assertEqual(body["updated_at"], "2026-07-20T10:00:00Z")
        self.assertEqual(body["latest_take_session_id"], "t2")

    def test_take_count_is_per_project_official_takes_only(self):
        # Founder 2026-07-23: the badge is "<take_count>.0" — the count
        # of OFFICIAL (spoken) takes of THIS arc; reads never count, and
        # it is per-project (this arc's sessions only), never global.
        body, _ = self._get(_row(), [
            self._spoken("t1", 1),
            self._spoken("t2", 2),
            self._spoken("t3", 3),
            self._read("r1", "t3", {}),
        ])
        self.assertEqual(body["take_count"], 3)   # the 3 spoken, not the read

    def test_can_record_take_is_true_once_a_take_exists(self):
        # Founder 2026-07-24 (T1 · 1.2): "record another take" is available
        # the instant a recording completes. It used to also have to dodge
        # the re-read loading gate; that gate is gone with the lane, so the
        # rule is now simply "the project has a spoken take".
        body, _ = self._get(_row(version=3), [self._spoken("t1", 1)])
        self.assertTrue(body["can_record_take"])
        # The retired fields are gone from the payload entirely.
        self.assertNotIn("reread_done", body)
        self.assertNotIn("reread_processing", body)

        # A leftover historical read row changes nothing.
        body, _ = self._get(_row(version=3), [
            self._spoken("t1", 1),
            self._read("r1", "t1", {}, analysis_state="ready")])
        self.assertTrue(body["can_record_take"])
        self.assertEqual(body["take_count"], 1)   # the read is not a take

    def test_can_record_take_needs_a_spoken_take(self):
        # No spoken take yet → nothing to continue (mirrors /setup's rule).
        # A read never flips it — the guard is spoken-only.
        body, _ = self._get(_row(), [])
        self.assertFalse(body["can_record_take"])
        body, _ = self._get(_row(version=3), [self._read("r1", "t1", {})])
        self.assertFalse(body["can_record_take"])


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class RecordingFlowTagTests(unittest.TestCase):
    """The flat-field → session_context fold (founder 2026-07-20). The
    intake validator strips unknown keys, so these tags ONLY exist because
    _recording_flow_tags folds them — pinned so a validator refactor can't
    silently drop the star-re-record contract.

    read_target / ideal_version are RETIRED (founder 2026-08-05): they only
    ever existed to pair a re-read to the version it read."""

    SNIP = "aaaa1111-aaaa-1111-aaaa-111111111111"

    def test_read_tags_never_fold_again(self):
        # The retired lane must not be reachable by posting its old
        # fields: nothing about a read may ride into session_context.
        self.assertEqual(v2._recording_flow_tags({
            "read_target": "ideal_text", "ideal_version": "4"}), {})
        self.assertEqual(v2._recording_flow_tags({
            "read_target": "IDEAL_TEXT", "ideal_version": "soon"}), {})

    def test_unknown_target_and_no_fields_fold_nothing(self):
        self.assertEqual(v2._recording_flow_tags(
            {"read_target": "slide_7"}), {})
        self.assertEqual(v2._recording_flow_tags({}), {})

    def test_paired_snippet_uuid_guard(self):
        self.assertEqual(
            v2._recording_flow_tags({"paired_snippet_id": self.SNIP}),
            {"paired_snippet_id": self.SNIP})
        self.assertEqual(
            v2._recording_flow_tags({"paired_snippet_id": "not-a-uuid"}), {})


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class HistoricalVersionTests(unittest.TestCase):
    """?version=N (founder 2026-07-20): an old bubble opens ITS OWN step —
    frozen text + that step's reasoning, read-only; current falls through
    to the live notebook; missing snapshot → historical_unavailable."""

    SNAP_TEXT = (f"Start. [[moment:{UID}|{UID}]]the old span[[/moment]] "
                 "end.")

    def setUp(self):
        self.app = Flask(__name__)

    def _get(self, *, version_param, snap, row=None):
        with self.app.test_request_context(
                query_string={"version": version_param}):
            request.user_id = "u1"
            with patch("routes.v2.explore_ideal_text._arc_owned_by_caller",
                              return_value=(True, [])), \
                 patch("routes.v2.explore_ideal_text._moments_entitled", return_value=False), \
                 patch("routes.v2.explore_ideal_text._moment_explanations_map",
                              return_value={}), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=(row or _row(version=3))), \
                 patch.object(v2.db, "get_user_arc_ideal_notes",
                              return_value=None), \
                 patch.object(v2.db, "get_ideal_text_version",
                              return_value=snap):
                out = v2.v2_explore_get_ideal_text.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status

    def test_old_version_serves_the_frozen_step(self):
        snap = {"arc_id": ARC, "version": 1, "text": self.SNAP_TEXT,
                "created_at": "2026-07-19T10:00:00Z",
                "moments": [{"snippet_id": UID, "kind": "replace",
                             "replacement": "the new span",
                             "why": "It reads calmer.", "trigger": None}]}
        body, status = self._get(version_param="1", snap=snap)
        self.assertEqual(status, 200)
        self.assertTrue(body["historical"])
        self.assertEqual(body["status"], "superseded")
        self.assertEqual(body["version"], 1)
        self.assertEqual(body["current_version"], 3)
        self.assertNotIn("[[moment:", body["text"])   # anchors stripped
        m = body["key_moments"][0]
        self.assertEqual(m["anchor"], "the old span")
        self.assertIn(m["anchor"], body["text"])
        # Sole-gatekeeper rip (founder 2026-08-10): the historical view is
        # a frozen read-only step and no longer hand-assembles suggestion
        # payloads outside the gate. Anchors stay; stars do not.
        self.assertNotIn("star", m)
        self.assertNotIn("suggestion", m)
        raw = json.dumps(body)
        for banned in ("threat", "charisma", "potentiometer"):
            self.assertNotIn(banned, raw)   # sanitized at write, held here

    def test_unknown_device_in_snapshot_yields_no_star(self):
        # Same device guard as live: an unknown structure/delivery
        # spelling in an old snapshot must yield NO star and NO
        # suggestion (the FE renders copy purely from device).
        snap = {"arc_id": ARC, "version": 1, "text": self.SNAP_TEXT,
                "created_at": "2026-07-19T10:00:00Z",
                "moments": [{"snippet_id": UID, "kind": "structure",
                             "device": "rule_of_seven", "quote": "x"}]}
        body, _ = self._get(version_param="1", snap=snap)
        m = body["key_moments"][0]
        self.assertNotIn("star", m)
        self.assertNotIn("suggestion", m)

    def test_delivery_snapshot_serves_no_star(self):
        # Sole-gatekeeper rip: a snapshot's delivery moment renders as a
        # plain anchor — no star, whatever its device says.
        snap = {"arc_id": ARC, "version": 1, "text": self.SNAP_TEXT,
                "created_at": "2026-07-19T10:00:00Z",
                "moments": [{"snippet_id": UID, "kind": "delivery",
                             "device": "pace_fast", "quote": None}]}
        body, _ = self._get(version_param="1", snap=snap)
        m = body["key_moments"][0]
        self.assertNotIn("star", m)
        self.assertNotIn("suggestion", m)

    def test_missing_snapshot_reports_unavailable(self):
        body, status = self._get(version_param="1", snap=None)
        self.assertEqual(status, 200)
        self.assertTrue(body["historical_unavailable"])
        self.assertEqual(body["requested_version"], 1)
        self.assertEqual(body["current_version"], 3)

    def test_current_version_param_serves_the_live_notebook(self):
        body, status = self._get(version_param="3", snap=None)
        self.assertEqual(status, 200)
        self.assertNotIn("historical", body)
        self.assertEqual(body["version"], 3)
        self.assertIn("status", body)   # the live payload shape

    def test_garbage_version_400s(self):
        body, status = self._get(version_param="one", snap=None)
        self.assertEqual(status, 400)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SnapshotSanitizeTests(unittest.TestCase):
    def test_write_time_projection_mirrors_serve(self):
        from services.ideal_text_block import sanitize_suggestions_snapshot
        out = sanitize_suggestions_snapshot({
            "s1": {"kind": "replace", "replacement_text": "calmer words",
                   "why": "Lands better.", "trigger": "threat"},
            "s2": {"kind": "structure", "trigger": "contrast",
                   "why": "not about X. about Y."},
            "s3": {"kind": "delivery", "trigger": "pace_fast",
                   "why": None},
            "s4": "not-a-dict",
        })
        by = {o["snippet_id"]: o for o in out}
        self.assertIsNone(by["s1"]["trigger"])          # clamped
        self.assertEqual(by["s1"]["replacement"], "calmer words")
        self.assertEqual(by["s2"]["device"], "contrast")
        self.assertEqual(by["s2"]["quote"], "not about X. about Y.")
        self.assertEqual(by["s3"]["device"], "pace_fast")
        self.assertIsNone(by["s3"]["quote"])
        self.assertNotIn("s4", by)
        import json as _json
        self.assertNotIn("threat", _json.dumps(out))


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class MomentsUnlockTests(unittest.TestCase):
    """BE-5 — the key-moment unlock: atomic, no grandfathering.

    RE-POINTED AT TOKENS (founder 2026-08-12, the pricing pivot). The legacy
    5-credit branch is gone from the endpoint, so these pin the one charging
    path that remains: 2,500 tokens via token_account.charge, keyed on the arc
    so a re-open is free.

    THE REFUND ASSERTION IS GONE ON PURPOSE, and its absence is the point.
    The credits path was deduct → insert → refund-on-conflict, three round
    trips with two failure windows. `charge` is idempotent on (user, action,
    ref_id): a raced second claim is reported ok with charged=0 rather than
    debited and handed back, so there is no refund to make and no window in
    which the money is gone and the entitlement is not."""

    def setUp(self):
        self.app = Flask(__name__)

    def _post(self, *, entitled=False, ok=True, balance=7_500,
              charged=2_500, insert_row={"id": "u"}, owned=True):
        from services.token_account import ChargeResult
        res = ChargeResult(ok, charged if ok else 0, balance,
                           "" if ok else "insufficient", "moment_explanation")
        with self.app.test_request_context(json={}):
            request.user_id = UID
            with patch("routes.v2.arcs._arc_owned_by_caller",
                              return_value=(owned, [])), \
                 patch.object(v2.db, "get_moment_unlock",
                              return_value=({"arc_id": ARC} if entitled
                                            else None)), \
                 patch("services.token_account.charge",
                       return_value=res) as m_charge, \
                 patch.object(v2.db, "insert_moment_unlock",
                              return_value=insert_row) as m_ins:
                out = v2.v2_unlock_moments.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, m_charge, m_ins

    def test_unlock_charges_tokens_and_claims(self):
        body, status, m_charge, m_ins = self._post()
        self.assertEqual(status, 200)
        self.assertTrue(body["unlocked"])
        self.assertEqual(body["tokens_remaining"], 7_500)
        # Keyed on the ARC, which is what makes every re-open free.
        self.assertEqual(m_charge.call_args.args[1], "moment_explanation")
        self.assertEqual(m_charge.call_args.kwargs["ref_id"], ARC)
        m_ins.assert_called_once()

    def test_the_legacy_credits_path_is_GONE(self):
        """The pivot, pinned. A second charging path behind a flag nobody
        intends to flip back is how two currencies drift apart — the unused
        one stops being exercised and is still what runs the day an env var
        gets cleared."""
        import inspect
        src = inspect.getsource(v2.v2_unlock_moments)
        for legacy in ("deduct_credits_strict", "MOMENTS_UNLOCK_CREDITS",
                       "INSUFFICIENT_CREDITS", "credits_remaining",
                       "v2_increment_student_credits"):
            self.assertNotIn(legacy, src)

    def test_already_entitled_never_charges(self):
        body, status, m_charge, m_ins = self._post(entitled=True)
        self.assertEqual(status, 200)
        self.assertTrue(body["already_entitled"])
        m_charge.assert_not_called()
        m_ins.assert_not_called()

    def test_insufficient_tokens_402(self):
        body, status, *_ = self._post(ok=False, balance=100)
        self.assertEqual(status, 402)
        self.assertEqual(body["code"], "INSUFFICIENT_TOKENS")
        self.assertEqual(body["required"], 2_500)
        self.assertEqual(body["current"], 100)

    def test_a_failed_claim_after_a_charge_reports_rather_than_lies(self):
        # The insert conflicts AND the re-check still sees no entitlement.
        # Nothing is refunded — the charge is idempotent on the arc, so the
        # retry costs nothing and the entitlement lands then.
        body, status, _c, _i = self._post(insert_row=None)
        self.assertEqual(status, 500)
        self.assertEqual(body["code"], "V2_ERROR")

    def test_unowned_404(self):
        body, status, *_ = self._post(owned=False)
        self.assertEqual(status, 404)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class MomentExplanationGetTests(unittest.TestCase):
    """The FE contract pin: per-moment GET at
    /v2/explore/arc/<id>/moments/<moment_id>; the 402 carries price_tokens."""

    def setUp(self):
        self.app = Flask(__name__)

    def _get(self, *, entitled, moment_id="sn1"):
        sessions = [{"id": "s1", "user_id": "u1", "take_index": 1,
                     "recording_kind": "spoken", "paired_session_id": None}]
        with self.app.test_request_context():
            request.user_id = "u1"
            with patch("routes.v2.arcs._arc_owned_by_caller",
                              return_value=(True, sessions)), \
                 patch("routes.v2.arcs._moments_entitled",
                              return_value=entitled), \
                 patch("routes.v2.arcs._take_key_moments",
                              return_value=[{
                                  "snippet_id": "sn1",
                                  "take_session_id": "s1",
                                  "slide_index": 0,
                                  "recording_kind": "spoken",
                                  "transcript": "the turn",
                                  "audio_ref": "https://x/a.webm",
                                  "start_offset_ms": 0, "duration_ms": 900,
                                  "comment_text": "This is the turn.",
                              }]):
                out = v2.v2_get_moment_explanation.__wrapped__(ARC, moment_id)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status

    def test_locked_402_with_price(self):
        body, status = self._get(entitled=False)
        self.assertEqual(status, 402)
        self.assertEqual(body["code"], "MOMENTS_LOCKED")
        self.assertEqual(body["price_tokens"], 2_500)

    def test_entitled_serves_flat_written_note(self):
        body, status = self._get(entitled=True)
        self.assertEqual(status, 200)
        # FLAT top-level note — the per-item coach-video lane is retired.
        self.assertEqual(body["id"], "sn1")
        self.assertEqual(body["note"], "This is the turn.")
        self.assertNotIn("video_ref", body)
        self.assertNotIn("moment", body)        # not nested
        raw = json.dumps(body)
        self.assertNotIn("direction", raw)     # the label never serializes
        self.assertNotIn("challenge", raw)
        self.assertNotIn("threat", raw)

    def test_unknown_moment_404s(self):
        body, status = self._get(entitled=True, moment_id="nope")
        self.assertEqual(status, 404)
        self.assertEqual(body["code"], "MOMENT_NOT_FOUND")

    def test_route_paths_match_the_fe_pin(self):
        app = Flask(__name__)
        app.register_blueprint(v2.v2_bp, url_prefix="/v2")
        rules = {r.rule for r in app.url_map.iter_rules()}
        self.assertIn("/v2/explore/arc/<arc_id>/moments/<moment_id>", rules)
        self.assertIn("/v2/arc/<arc_id>/unlock-moments", rules)
        self.assertNotIn("/v2/presentation/<presentation_id>/moments", rules)
        self.assertNotIn(
            "/v2/presentation/<presentation_id>/unlock-moments", rules)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class LegacyRetirementTests(unittest.TestCase):
    """The $25 unlock is retired — always 410.

    THE COACH PUBLISH ROUTE IS NOT. It was a 410 tombstone here until
    2026-08-14, when the coach panel's "Publish the full analysis" button was
    found to be POSTing straight at it — so publishing was impossible from
    the app, and the only code that sets results_published_at sat behind an
    /internal route with no BFF path. Restored; see
    PublishAnalysisRestoredTests in test_eager_ideal_text.py."""

    def setUp(self):
        self.app = Flask(__name__)

    def test_arc_unlock_410(self):
        with self.app.test_request_context(json={}):
            request.user_id = UID
            out = v2.v2_arc_unlock.__wrapped__(ARC)
            resp, status = out if isinstance(out, tuple) else (out, 200)
        self.assertEqual(status, 410)

    def test_publish_analysis_is_NOT_a_tombstone_any_more(self):
        """Regression pin for the dead-end button. Whatever this route
        answers, it must never be 410 again: the FE's publish button targets
        it, and a tombstone there means the coach cannot deliver work they
        have already done."""
        with self.app.test_request_context(json={}):
            request.user_id = "coach1"
            with patch.object(v2.db, "get_arc_sessions", return_value=[]):
                out = v2.v2_coach_publish_analysis.__wrapped__(ARC)
            resp, status = out if isinstance(out, tuple) else (out, 200)
        self.assertNotEqual(status, 410)
        self.assertEqual(status, 404)   # no such arc, in this fixture


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class IdealBubbleTests(unittest.TestCase):
    def _fire(self, fn_name, version, returns):
        from services import arc_notifications as an
        captured = {}

        class _Db:
            def insert_lounge_messages(self, uid, msgs):
                captured["msgs"] = msgs
                return returns

        ok = getattr(an, fn_name)(_Db(), "u1", ARC, version)
        return ok, captured

    def test_ready_and_verified_keys_are_per_version_and_distinct(self):
        ok1, c1 = self._fire("fire_ideal_version_ready", 2, [{"id": "r"}])
        ok2, c2 = self._fire("fire_ideal_version_ready", 3, [{"id": "r"}])
        ok3, c3 = self._fire("fire_ideal_verified", 2, [{"id": "r"}])
        self.assertTrue(ok1 and ok2 and ok3)
        ids = {c["msgs"][0]["client_id"] for c in (c1, c2, c3)}
        self.assertEqual(len(ids), 3)             # all distinct
        self.assertEqual(c1["msgs"][0]["metadata"]["variant"], "ready")
        self.assertEqual(c3["msgs"][0]["metadata"]["variant"], "verified")
        self.assertEqual(c3["msgs"][0]["metadata"]["version"], 2)
        from services.lounge_messages import VALID_KINDS
        self.assertIn(c1["msgs"][0]["kind"], VALID_KINDS)

    def test_dropped_insert_reads_as_not_fired(self):
        with self.assertLogs("services.arc_notifications", level="ERROR"):
            ok, _ = self._fire("fire_ideal_version_ready", 2, [])
        self.assertFalse(ok)

    def test_obsolete_unchanged_document_result_no_longer_exists(self):
        # Every spoken Take now earns the normal versioned Ideal Text card.
        # Keeping this function around, even unused, invites the old terminal
        # bubble to be wired back in during a reconnect fix.
        from services import arc_notifications

        self.assertFalse(hasattr(arc_notifications, "fire_take_processed"))


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SeamSmoothingContractPinTests(unittest.TestCase):
    """BE-1's L1 boundary — the consistency pass ALREADY exists (the compose
    LLM), and its prompt pins exactly the founder-approved contract:
    seam-smoothing of selected verbatim pieces, never free rewriting."""

    def test_compose_prompt_pins_verbatim_and_no_new_claims(self):
        # The prompt text moved to the registry (services/prompts/,
        # 2026-08-03) — pin the contract on the RENDERED system prompt
        # (what the LLM actually receives), which is strictly stronger
        # than pinning the builder's source.
        from services.prompts import best_presentation as bp_prompts
        rendered = bp_prompts.system()
        self.assertIn("MOSTLY VERBATIM", rendered)
        self.assertIn("NEVER add new claims", rendered)
        self.assertIn("continuity", rendered)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class PaywallRetirementTests(unittest.TestCase):
    """The $25 arc model is retired: best-presentation, breakthroughs, game,
    and every take's feedback are unconditionally free — no 402, no paywall,
    no locked takes. (/unlock is a 410 tombstone.)"""

    def setUp(self):
        self.app = Flask(__name__)

    def _best_presentation(self):
        with self.app.test_request_context():
            request.user_id = UID
            with patch("routes.v2.arcs._arc_owned_by_caller",
                              return_value=(True, [])), \
                 patch("services.best_presentation.build_best_presentation",
                       return_value={"ready": True, "slides": []}):
                out = v2.v2_explore_arc_best_presentation.__wrapped__(ARC)
        resp, status = out if isinstance(out, tuple) else (out, 200)
        return resp.get_json(), status

    def test_best_presentation_free(self):
        body, status = self._best_presentation()
        self.assertEqual(status, 200)
        self.assertTrue(body.get("audit_paid"))

    def _feedback(self):
        spoken = [{"id": "s1", "take_index": 1},
                  {"id": "s2", "take_index": 2}]
        with self.app.test_request_context():
            request.user_id = UID
            with patch("routes.v2.arcs._arc_owned_by_caller",
                              return_value=(True, spoken)), \
                 patch("routes.v2.arcs._spoken_takes_and_reads",
                       return_value=(spoken, {})), \
                 patch("routes.v2.arcs._take_full_text",
                              side_effect=lambda sid: f"text-{sid}"), \
                 patch("routes.v2.arcs._take_key_moments",
                              side_effect=lambda sid, rids: []), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value={}):
                out = v2.v2_explore_arc_feedback.__wrapped__(ARC)
        resp, status = out if isinstance(out, tuple) else (out, 200)
        return resp.get_json(), status

    def test_feedback_serves_every_take_free(self):
        body, status = self._feedback()
        self.assertEqual(status, 200)
        takes = {t["take_index"]: t for t in body["takes"]}
        self.assertFalse(takes[2].get("locked"))
        self.assertIn("full_text", takes[2])      # content served, not withheld
        self.assertNotIn("paywall", body)


if __name__ == "__main__":
    unittest.main()
