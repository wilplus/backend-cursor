"""willab — the SINGLE-DELIVERABLE re-shape (founder 2026-07-17).

The product delivers ONE thing: the ideal text. Record a take → instant
ideal text vN (unverified) → the coach verifies in the background, always →
the verified text displays FREE. The ONLY paid item: opening the key-moment
explanations (5 credits, one-time per presentation). Everything behind
SINGLE_DELIVERABLE_ENABLED (default OFF → byte-for-byte legacy).

Pinned here, token by token:
  BE-1  version bump on a CHANGED machine copy only; migration fallbacks;
        the L1 seam-smoothing pass exists and its contract is pinned.
  BE-2  the 3-take batch cap lifts (takes append forever).
  BE-3  VERIFY: snapshot + idempotency + the per-version verified bubble.
  BE-4  the student GET: both states FREE, never a 402; the coach's working
        text NEVER leaks unverified.
  BE-5  the 5-credit moments unlock (atomic; no grandfathering) + the gated
        explanations GET.
  BE-6  the $25 unlock and publish-analysis answer 410 under the flag.

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
class VersionBumpTests(unittest.TestCase):
    """BE-1 — version increments only when the machine copy CHANGES."""

    def _persist(self, row, text, missing=()):
        client = _Client(missing=missing)
        fake = SimpleNamespace(client=client,
                               get_coach_arc_ideal_text=lambda a: row)
        ok = DatabaseService.persist_auto_ideal_text(fake, ARC, text)
        return ok, client.upserts

    def test_new_row_starts_at_version_1(self):
        ok, ups = self._persist(None, "first text")
        self.assertTrue(ok)
        self.assertEqual(ups[0]["version"], 1)

    def test_changed_text_bumps_version(self):
        ok, ups = self._persist(_row(version=3), "a different text")
        self.assertTrue(ok)
        self.assertEqual(ups[0]["version"], 4)

    def test_unchanged_text_keeps_version(self):
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
            with patch.object(v2, "_arc_owned_by_caller",
                              return_value=(True, [])), \
                 patch.object(v2, "_single_deliverable_enabled",
                              return_value=True), \
                 patch.object(v2, "_moments_entitled",
                              return_value=entitled_moments), \
                 patch.object(v2, "_moment_explanations_map",
                              return_value=(expl or {})), \
                 patch.object(v2.db, "get_coach_arc_ideal_text",
                              return_value=row), \
                 patch.object(v2.db, "get_user_arc_ideal_notes",
                              return_value="notes"), \
                 patch.object(v2, "_arc_payment_gate") as m_gate:
                out = v2.v2_explore_get_ideal_text.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                # The payment gate must never even be CONSULTED — the text
                # is free by construction, not by a gate returning None.
                m_gate.assert_not_called()
                return resp.get_json(), status

    def test_unverified_serves_machine_copy_free(self):
        body, status = self._get(_row(version=2))
        self.assertEqual(status, 200)
        self.assertEqual(body["status"], "unverified")
        self.assertEqual(body["version"], 2)
        self.assertEqual(body["text"], "machine text")
        self.assertFalse(body["moments_unlocked"])
        self.assertEqual(body["notes_text"], "notes")
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

    def test_key_moments_carry_has_explanation(self):
        text = ("[[moment:aaaa1111-aaaa-1111-aaaa-111111111111|"
                "bbbb2222-bbbb-2222-bbbb-222222222222]]hello[[/moment]]")
        body, _ = self._get(
            _row(auto_text=text, text=text),
            expl={"aaaa1111-aaaa-1111-aaaa-111111111111": True})
        self.assertEqual(len(body["key_moments"]), 1)
        m = body["key_moments"][0]
        self.assertEqual(m["id"], "aaaa1111-aaaa-1111-aaaa-111111111111")
        self.assertTrue(m["has_explanation"])

    def test_ac9_score_free(self):
        body, _ = self._get(_row())
        raw = json.dumps(body)
        for banned in ("potentiometer", "acoustic_read", "overall_score",
                       "slide_stickiness", "rank", "power_score"):
            self.assertNotIn(banned, raw)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class MomentsUnlockTests(unittest.TestCase):
    """BE-5 — the 5-credit unlock, atomic, no grandfathering."""

    def setUp(self):
        self.app = Flask(__name__)

    def _post(self, *, entitled=False, balance=7, insert_row={"id": "u"},
              owned=True):
        with self.app.test_request_context(json={}):
            request.user_id = UID
            with patch.object(v2, "_arc_owned_by_caller",
                              return_value=(owned, [])), \
                 patch.object(v2.db, "get_moment_unlock",
                              return_value=({"arc_id": ARC} if entitled
                                            else None)), \
                 patch.object(v2.db, "deduct_credits_strict",
                              return_value=balance) as m_deduct, \
                 patch.object(v2.db, "insert_moment_unlock",
                              return_value=insert_row) as m_ins, \
                 patch.object(v2.db, "v2_increment_student_credits") \
                    as m_refund, \
                 patch.object(v2.db, "v2_get_student_details",
                              return_value={"credits": 2}):
                out = v2.v2_unlock_moments.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status, m_deduct, m_ins, m_refund

    def test_unlock_deducts_five_and_claims(self):
        body, status, m_deduct, m_ins, m_refund = self._post()
        self.assertEqual(status, 200)
        self.assertTrue(body["unlocked"])
        self.assertEqual(body["credits_remaining"], 7)
        self.assertEqual(m_deduct.call_args.args[1], 5)   # the price
        m_ins.assert_called_once()
        m_refund.assert_not_called()

    def test_already_entitled_never_charges(self):
        body, status, m_deduct, m_ins, _ = self._post(entitled=True)
        self.assertEqual(status, 200)
        self.assertTrue(body["already_entitled"])
        m_deduct.assert_not_called()
        m_ins.assert_not_called()

    def test_insufficient_credits_402(self):
        body, status, *_ = self._post(balance=None)
        self.assertEqual(status, 402)
        self.assertEqual(body["code"], "INSUFFICIENT_CREDITS")
        self.assertEqual(body["required"], 5)

    def test_raced_claim_refunds(self):
        # insert conflicts → refund; the re-check still sees no entitlement
        # in this fixture, so the caller gets the 500-with-refund path.
        body, status, _d, _i, m_refund = self._post(insert_row=None)
        self.assertIn(status, (409, 500))
        m_refund.assert_called_once()
        self.assertEqual(m_refund.call_args.args[1], 5)

    def test_unowned_404(self):
        body, status, *_ = self._post(owned=False)
        self.assertEqual(status, 404)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class MomentExplanationGetTests(unittest.TestCase):
    """The FE contract pin: per-moment GET at
    /v2/explore/arc/<id>/moments/<moment_id>; the 402 carries price_credits."""

    def setUp(self):
        self.app = Flask(__name__)

    def _get(self, *, entitled, moment_id="sn1"):
        sessions = [{"id": "s1", "user_id": "u1", "take_index": 1,
                     "recording_kind": "spoken", "paired_session_id": None}]
        with self.app.test_request_context():
            request.user_id = "u1"
            with patch.object(v2, "_arc_owned_by_caller",
                              return_value=(True, sessions)), \
                 patch.object(v2, "_moments_entitled",
                              return_value=entitled), \
                 patch.object(v2, "_take_key_moments",
                              return_value=[{
                                  "snippet_id": "sn1",
                                  "take_session_id": "s1",
                                  "slide_index": 0,
                                  "recording_kind": "spoken",
                                  "transcript": "the turn",
                                  "audio_ref": "https://x/a.webm",
                                  "start_offset_ms": 0, "duration_ms": 900,
                                  "comment_text": "This is the turn.",
                                  "comment_video_ref": "https://x/v.mp4",
                              }]):
                out = v2.v2_get_moment_explanation.__wrapped__(ARC, moment_id)
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status

    def test_locked_402_with_price(self):
        body, status = self._get(entitled=False)
        self.assertEqual(status, 402)
        self.assertEqual(body["code"], "MOMENTS_LOCKED")
        self.assertEqual(body["price_credits"], 5)

    def test_entitled_serves_the_one_explanation_label_free(self):
        body, status = self._get(entitled=True)
        self.assertEqual(status, 200)
        m = body["moment"]
        self.assertEqual(m["id"], "sn1")
        self.assertEqual(m["comment_text"], "This is the turn.")
        self.assertEqual(m["comment_video_ref"], "https://x/v.mp4")
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
    """BE-6 — the $25 unlock + publish answer 410 under the flag."""

    def setUp(self):
        self.app = Flask(__name__)

    def test_arc_unlock_410(self):
        with self.app.test_request_context(json={}):
            request.user_id = UID
            with patch.object(v2, "_single_deliverable_enabled",
                              return_value=True):
                out = v2.v2_arc_unlock.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
        self.assertEqual(status, 410)

    def test_publish_analysis_410(self):
        with self.app.test_request_context(json={}):
            request.user_id = "coach1"
            with patch.object(v2, "_single_deliverable_enabled",
                              return_value=True):
                out = v2.v2_coach_publish_analysis.__wrapped__(ARC)
                resp, status = out if isinstance(out, tuple) else (out, 200)
        self.assertEqual(status, 410)
        self.assertIn("verify", resp.get_json()["error"].lower())


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class BatchCapLiftTests(unittest.TestCase):
    """BE-2 — takes append forever under the flag."""

    def _continue(self, *, flag):
        sessions = [
            {"arc_id": "arc-full", "intake_context": {
                "slides": [{"title": "One", "body": "b"}]}}
            for _ in range(3)                     # a FULL legacy batch
        ]
        with patch.object(v2, "_single_deliverable_enabled",
                          return_value=flag), \
             patch.object(v2, "_presentation_id_from_slides",
                          return_value="deck-hash"), \
             patch.object(v2.db, "v2_list_user_lab_sessions",
                          return_value=sessions):
            return v2._continue_deck_arc(
                "u1", [{"title": "One", "body": "b"}], "fresh-arc", 1)

    def test_flag_on_joins_the_full_arc_forever(self):
        arc, take = self._continue(flag=True)
        self.assertEqual(arc, "arc-full")
        self.assertEqual(take, 4)                 # take 4 of the SAME arc

    def test_flag_off_keeps_the_batch_cap(self):
        arc, take = self._continue(flag=False)
        self.assertEqual(arc, "fresh-arc")        # full batch → new arc


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


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SeamSmoothingContractPinTests(unittest.TestCase):
    """BE-1's L1 boundary — the consistency pass ALREADY exists (the compose
    LLM), and its prompt pins exactly the founder-approved contract:
    seam-smoothing of selected verbatim pieces, never free rewriting."""

    def test_compose_prompt_pins_verbatim_and_no_new_claims(self):
        import inspect
        from services import best_presentation as bp
        src = inspect.getsource(bp._render_composition)
        self.assertIn("MOSTLY VERBATIM", src)
        self.assertIn("NEVER add new claims", src)
        self.assertIn("continuity", src)


if __name__ == "__main__":
    unittest.main()
