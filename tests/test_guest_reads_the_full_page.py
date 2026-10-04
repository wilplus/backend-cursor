"""A guest reads their own Ideal Text page (F1 Repair Plan Phase 0.6).

FOUNDER, 2026-10-04, after recording as a brand-new guest and getting plain
text: "it makes no sense. You need to show the full feedback ... and then
when they want to practice, then show you need to sign up."

Every route behind the page was ``require_auth`` and matched ownership on
``v2_sessions.user_id``; a guest Take carries only ``owner_principal_id``.
These tests pin the one identity rule that opens the page to its guest and to
nobody else, and the migration that lets the account keep it after sign-up.
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import auth
from flask import Flask, request

import routes.v2.explore_ideal_text  # noqa: F401 -- attaches every route
import routes.v2.user_sessions  # noqa: F401
from routes.v2 import arcs, guest_owner
from routes.v2.blueprint import v2_bp
from services import owner_feedback_answers
from services.project_ownership import _hash_secret, session_actor_id

ROOT = Path(__file__).resolve().parents[1]
ARC = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
GUEST = "3f1c2a54-9b7e-4c1d-8a2f-6e5d4c3b2a10"
OTHER_GUEST = "4f1c2a54-9b7e-4c1d-8a2f-6e5d4c3b2a10"
USER = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
SECRET = "s" * 43
TOKEN = f"{GUEST}.{SECRET}"


def _principal(principal_id=GUEST, *, user_id=None, secret=SECRET):
    return {"id": principal_id, "user_id": user_id,
            "guest_secret_hash": _hash_secret(secret)}


def _app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(v2_bp, url_prefix="/v2")
    return app


class TheDecorator(unittest.TestCase):
    """``require_owner_or_guest``: an account as before, else a proved guest."""

    def setUp(self):
        self.app = Flask(__name__)
        seen = self.seen = {}

        @self.app.route("/probe")
        @guest_owner.require_owner_or_guest
        def probe():
            seen["user_id"] = request.user_id
            seen["guest"] = guest_owner.caller_is_guest()
            return "ok"

        self._orig_verify = auth.verify_supabase_token
        auth.verify_supabase_token = lambda token: {"sub": USER}

    def tearDown(self):
        auth.verify_supabase_token = self._orig_verify

    def _get(self, headers, principal=None):
        with patch.object(guest_owner.db, "get_owner_principal",
                          return_value=principal):
            return self.app.test_client().get("/probe", headers=headers)

    def test_an_account_is_let_in_exactly_as_before(self):
        response = self._get({"Authorization": "Bearer t"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.seen, {"user_id": USER, "guest": False})

    def test_a_proved_guest_reads_as_its_principal(self):
        response = self._get({"X-Willab-Guest-Owner": TOKEN}, _principal())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.seen, {"user_id": GUEST, "guest": True})

    def test_a_bad_account_token_never_falls_back_to_the_guest(self):
        auth.verify_supabase_token = lambda token: (_ for _ in ()).throw(
            Exception("expired"))
        response = self._get({"Authorization": "Bearer t",
                              "X-Willab-Guest-Owner": TOKEN}, _principal())
        self.assertEqual(response.status_code, 401)
        self.assertEqual(self.seen, {})

    def test_a_claimed_guest_identity_stops_working(self):
        response = self._get({"X-Willab-Guest-Owner": TOKEN},
                             _principal(user_id=USER))
        self.assertEqual(response.status_code, 401)

    def test_a_wrong_secret_is_refused(self):
        response = self._get({"X-Willab-Guest-Owner": TOKEN},
                             _principal(secret="t" * 43))
        self.assertEqual(response.status_code, 401)

    def test_no_identity_at_all_is_refused(self):
        self.assertEqual(self._get({}).status_code, 401)
        self.assertEqual(
            self._get({"X-Willab-Guest-Owner": "not-a-token"}).status_code,
            401)

    def test_a_lookup_failure_is_a_refusal(self):
        with patch.object(guest_owner.db, "get_owner_principal",
                          side_effect=RuntimeError("db down")):
            response = self.app.test_client().get(
                "/probe", headers={"X-Willab-Guest-Owner": TOKEN})
        self.assertEqual(response.status_code, 401)


class TheOwnershipRule(unittest.TestCase):
    """A caller matches only their own Takes, account or guest."""

    def test_the_actor_is_the_account_else_the_guest_owner(self):
        self.assertEqual(session_actor_id(
            {"user_id": USER, "owner_principal_id": "p"}), USER)
        self.assertEqual(session_actor_id(
            {"user_id": None, "owner_principal_id": GUEST}), GUEST)
        self.assertEqual(session_actor_id(None), "")

    def _owned(self, caller, sessions):
        app = Flask(__name__)
        with app.test_request_context("/"):
            request.user_id = caller
            with patch.object(arcs.db.takes, "get_arc_sessions",
                              return_value=sessions):
                return arcs._arc_owned_by_caller(ARC)[0]

    def test_a_guest_owns_its_own_unclaimed_take(self):
        self.assertTrue(self._owned(GUEST, [
            {"user_id": None, "owner_principal_id": GUEST}]))

    def test_a_guest_does_not_own_another_guests_take(self):
        self.assertFalse(self._owned(OTHER_GUEST, [
            {"user_id": None, "owner_principal_id": GUEST}]))

    def test_an_account_still_owns_its_take(self):
        self.assertTrue(self._owned(USER, [
            {"user_id": USER, "owner_principal_id": "account-principal"}]))

    def test_an_empty_caller_owns_nothing(self):
        self.assertFalse(self._owned(None, [
            {"user_id": None, "owner_principal_id": None}]))

    def test_the_guest_reads_its_own_answers_and_nobody_elses(self):
        class Database:
            def v2_get_session_by_id(self, _sid):
                return {"user_id": None, "owner_principal_id": GUEST}

            def list_take_feedback_self_reports(self, _sid, _owner):
                return []

        self.assertEqual(owner_feedback_answers.owner_answers(
            Database(), "take", GUEST), [])
        self.assertIsNone(owner_feedback_answers.owner_answers(
            Database(), "take", OTHER_GUEST))


class TheCoreReadAsAGuest(unittest.TestCase):
    """The cold-open read publishes and reads under the guest's principal --
    the same actor the pipeline published the guest's document under."""

    def test_the_guest_reads_its_document_under_its_principal(self):
        seen = {}

        def fake_read(_db, arc_id, actor_id, *, is_owner):
            seen["actor"] = actor_id
            seen["owned"] = is_owner()
            return None

        with patch.object(guest_owner.db, "get_owner_principal",
                          return_value=_principal()), \
             patch("services.ideal_text_core_snapshot.read_core_or_publish",
                   side_effect=fake_read), \
             patch.object(arcs.db.takes, "get_arc_sessions", return_value=[
                 {"user_id": None, "owner_principal_id": GUEST}]):
            _app().test_client().get(
                f"/v2/explore/arc/{ARC}/ideal-text/core",
                headers={"X-Willab-Guest-Owner": TOKEN})
        self.assertEqual(seen, {"actor": GUEST, "owned": True})

    def test_practise_and_coach_routes_stay_account_only(self):
        # Sign-up is the step in front of practise (founder 2026-10-04).
        source = (ROOT / "routes/v2/user_sessions.py").read_text()
        start = source.index("def v2_post_take_feedback_response(")
        self.assertIn("@require_auth\ndef v2_post_take_feedback_response(",
                      source[start - 200:start + 40])


class NothingIsRecordedForAGuest(unittest.TestCase):
    """A guest reads the page; no learning exposure is frozen for it."""

    def test_the_guest_reader_freezes_no_exposure(self):
        from services.learning_exposures import (
            prepare_ideal_text_presentation,
        )
        self.assertIsNone(prepare_ideal_text_presentation(
            database=object(), owner_principal_id=GUEST, project_id=ARC,
            take_id="take", actor_id=GUEST, text="Words.", version=1,
            take_count=1, title=None, parts=None))


class TheSignUpMigration(unittest.TestCase):
    """0413 lets the account keep what the guest recorded."""

    SQL = (ROOT / "migrations/a_signup_carries_the_whole_take.sql").read_text()

    def test_it_is_manifested(self):
        manifest = (ROOT / "migrations/manifest.txt").read_text()
        self.assertIn("0413\ta_signup_carries_the_whole_take.sql", manifest)

    def test_adopt_gives_the_guests_takes_to_the_account(self):
        adopt = self.SQL[self.SQL.index("IF target.id = claimed.id THEN"):
                         self.SQL.index("PERFORM set_config(")]
        self.assertIn("UPDATE public.v2_sessions\n           SET user_id = "
                      "p_user_id", adopt)
        self.assertIn("UPDATE public.snippets", adopt)
        self.assertIn("move_guest_ideal_text_parts_v1(claimed.id, p_user_id)",
                      adopt)

    def test_merge_still_moves_everything_it_moved(self):
        for table in ("projects", "v2_sessions", "rejected_takes",
                      "moment_suggestions", "transcript_versions", "slides",
                      "paragraphs", "evidence_spans",
                      "acoustic_feature_snapshots", "candidate_sets",
                      "machine_predictions", "generation_runs",
                      "processing_stage_runs", "takes",
                      "processing_transition_events", "recording_attempts",
                      "snippets"):
            self.assertIn(f"UPDATE public.{table}", self.SQL, table)
        self.assertIn("to_regclass('public.recording_1')", self.SQL)
        self.assertIn("SET search_path = extensions, public", self.SQL)

    def test_append_only_evidence_is_not_rewritten(self):
        for table in ("ideal_text_part_revision", "take_feedback_self_report"):
            self.assertNotIn(f"UPDATE public.{table}", self.SQL)

    def test_paragraphs_never_land_on_an_arc_the_account_already_has(self):
        self.assertIn("AND NOT EXISTS (", self.SQL)
        self.assertIn("mine.arc_id = part.arc_id", self.SQL)

    def test_the_mover_and_the_claim_stay_server_only(self):
        self.assertIn(
            "REVOKE ALL ON FUNCTION public.move_guest_ideal_text_parts_v1"
            "(UUID, UUID)\n    FROM PUBLIC, anon, authenticated, service_role",
            self.SQL)
        self.assertIn("GRANT EXECUTE ON FUNCTION public.claim_guest_owner"
                      "(UUID, TEXT, UUID)\n    TO service_role", self.SQL)

    def test_the_repair_only_touches_adopted_principals(self):
        repair = self.SQL[self.SQL.index("-- 0413 REPAIR"):]
        self.assertIn("session.user_id IS NULL", repair)
        self.assertIn("owner.claimed_by_owner_principal_id IS NULL", repair)
        self.assertIn("owner.claimed_at IS NOT NULL", repair)


if __name__ == "__main__":
    unittest.main()
