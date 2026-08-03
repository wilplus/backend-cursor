"""willab — self-declared speaker sex: the signup field, the profile route,
and the store method behind them.

The composite's side of this lives in test_voice_confidence.py (the cue-weight
reversal). This file covers how the value gets IN, and the two ways that could
go wrong quietly:

  * A sex-only POST — which is exactly what the signup screen sends — must not
    null a profile_domain / profile_goal the user filled in elsewhere.
    set_user_profile writes those two as a FULL SET, so the presence guard in
    the route is the only thing standing between a signup answer and a wiped
    intake.
  * A bad `sex` at signup must be rejected BEFORE the Supabase account is
    created, or a typo leaves an orphaned user behind and the caller sees an
    error for an account that now exists.

Also pinned: the store write is PARTIAL (carries neither domain nor goal), the
enum is validated at every entry point, and an unanswered field reads as null
rather than as a default — "never asked" and "declined" are different states
and the composite treats them differently.

Run: python3 -m unittest test_speaker_sex
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

# Placeholder credentials BEFORE the app graph is imported — config.py and
# services/db.py read the environment at import time and the Supabase client
# validates the key's SHAPE at construction. Never leave the process; every
# store call here is mocked. Same pattern as test_life_panel.py.
os.environ.setdefault("SUPABASE_URL", "https://speaker-sex-test.invalid")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "aaaa.bbbb.cccc")

try:
    from flask import Flask
    import auth
    from routes import auth as auth_routes
    from routes import v2_routes
    _IMPORT_ERROR = None
except Exception as e:                          # pragma: no cover
    Flask = None
    auth = auth_routes = v2_routes = None
    _IMPORT_ERROR = e

USER = "11111111-1111-4111-8111-111111111111"


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ProfileRouteTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(v2_routes.v2_bp)
        self.client = self.app.test_client()
        self._orig_verify = auth.verify_supabase_token
        auth.verify_supabase_token = lambda token: {"sub": USER}

        self.db = MagicMock()
        self.db.get_user_profile.return_value = {
            "domain": "sales", "goal": "close the Q3 deal",
            "previous_goal": None, "goal_changed_at": None,
        }
        self.db.get_user_speaker_sex.return_value = None
        self.db.set_user_profile.return_value = True
        self.db.set_user_speaker_sex.return_value = True
        # /v2/user/profile lives in routes.v2.user_account (god-file split) —
        # the whole-object db/is_coach rebinds must target THAT module's
        # namespace, not the routes.v2_routes re-exports.
        from routes.v2 import user_account as ua
        self._db_patch = patch.object(ua, "db", self.db)
        self._db_patch.start()
        self._coach_patch = patch.object(ua, "is_coach",
                                         return_value=False)
        self._coach_patch.start()

    def tearDown(self):
        self._coach_patch.stop()
        self._db_patch.stop()
        auth.verify_supabase_token = self._orig_verify

    def _post(self, body):
        return self.client.post("/v2/user/profile", json=body,
                                headers={"Authorization": "Bearer t"})

    def _get(self):
        return self.client.get("/v2/user/profile",
                               headers={"Authorization": "Bearer t"})

    # ── The one that matters ───────────────────────────────────────

    def test_a_sex_only_post_does_not_touch_the_intake(self):
        """THE signup case. set_user_profile writes {domain, goal} as a full
        set, so calling it here with two Nones would silently wipe an intake
        the user completed in the Lab."""
        resp = self._post({"sex": "female"})
        self.assertEqual(resp.status_code, 200)
        self.db.set_user_profile.assert_not_called()
        self.db.set_user_speaker_sex.assert_called_once_with(USER, "female")
        # ...and the response still reports the stored intake, not nulls.
        body = resp.get_json()
        self.assertEqual(body["domain"], "sales")
        self.assertEqual(body["goal"], "close the Q3 deal")
        self.assertEqual(body["sex"], "female")

    def test_an_intake_post_does_not_touch_a_declared_sex(self):
        """The mirror case: the Lab posts domain+goal and must not clear an
        answer given at signup."""
        self.db.get_user_speaker_sex.return_value = "male"
        resp = self._post({"domain": "sales", "goal": "new goal"})
        self.assertEqual(resp.status_code, 200)
        self.db.set_user_speaker_sex.assert_not_called()
        self.assertEqual(resp.get_json()["sex"], "male")

    def test_intake_and_sex_together_write_both(self):
        resp = self._post({"domain": "sales", "goal": "g", "sex": "male"})
        self.assertEqual(resp.status_code, 200)
        self.db.set_user_profile.assert_called_once()
        self.db.set_user_speaker_sex.assert_called_once_with(USER, "male")

    # ── Validation + shape ─────────────────────────────────────────

    def test_bad_sex_is_422_and_writes_nothing(self):
        for bad in ("m", "other", "Female!", 1, True, [], {}):
            self.db.reset_mock()
            resp = self._post({"sex": bad})
            self.assertEqual(resp.status_code, 422, bad)
            self.assertEqual(resp.get_json()["code"], "INVALID_INPUT")
            self.db.set_user_speaker_sex.assert_not_called()
            self.db.set_user_profile.assert_not_called()

    def test_the_three_accepted_values(self):
        for value in ("female", "male", "prefer_not_to_say"):
            self.db.reset_mock()
            self.db.set_user_speaker_sex.return_value = True
            resp = self._post({"sex": value})
            self.assertEqual(resp.status_code, 200, value)
            self.db.set_user_speaker_sex.assert_called_once_with(USER, value)

    def test_explicit_null_clears_the_answer(self):
        """Distinct from omitting the key, which leaves it alone."""
        resp = self._post({"sex": None})
        self.assertEqual(resp.status_code, 200)
        self.db.set_user_speaker_sex.assert_called_once_with(USER, None)

    def test_get_reports_null_when_never_asked(self):
        """null is how the FE knows to show the question at all — it must not
        be papered over with a default."""
        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        self.assertIn("sex", resp.get_json())
        self.assertIsNone(resp.get_json()["sex"])

    def test_get_reports_a_decline_distinctly(self):
        self.db.get_user_speaker_sex.return_value = "prefer_not_to_say"
        self.assertEqual(self._get().get_json()["sex"], "prefer_not_to_say")

    def test_a_failed_sex_write_is_a_500(self):
        self.db.set_user_speaker_sex.return_value = False
        resp = self._post({"sex": "male"})
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.get_json()["code"], "V2_ERROR")

    def test_legacy_intake_only_bodies_behave_exactly_as_before(self):
        """Back-compat: every existing FE caller sends domain and/or goal, and
        for them set_user_profile must still be called with both — including
        the long-standing full-set semantics where posting one clears the
        other."""
        self._post({"domain": "sales"})
        self.db.set_user_profile.assert_called_once_with(
            USER, domain="sales", goal=None)

    def test_the_sex_value_is_not_logged(self):
        # Capture the whole routes.* hierarchy: the profile route logs as
        # routes.v2.user_account since the god-file split, and pinning one
        # module name would silently blind this privacy fence on the next move.
        with self.assertLogs("routes", level="INFO") as captured:
            self._post({"sex": "female"})
        joined = " ".join(captured.output)
        self.assertIn("sex_set=True", joined)
        self.assertNotIn("female", joined)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class SignupTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(auth_routes.auth_bp)
        self.client = self.app.test_client()

        self.supabase = MagicMock()
        created = MagicMock()
        created.user.id = USER
        self.supabase.auth.admin.create_user.return_value = created
        session = MagicMock()
        session.session.access_token = "at"
        session.session.refresh_token = "rt"
        session.session.expires_in = 3600
        session.user.id = USER
        session.user.email = "a@b.c"
        self.supabase.auth.sign_in_with_password.return_value = session

        self._client_patch = patch.object(auth_routes, "create_client",
                                          return_value=self.supabase)
        self.create_client = self._client_patch.start()
        self.db = MagicMock()
        self.db.record_user_consent.return_value = {"id": "c1"}
        self._db_patch = patch.object(auth_routes.db_module, "db", self.db)
        self._db_patch.start()

    def tearDown(self):
        self._db_patch.stop()
        self._client_patch.stop()

    def _signup(self, **extra):
        body = {"email": "a@b.c", "password": "secret123",
                "terms_accepted": True}
        body.update(extra)
        return self.client.post("/signup", json=body)

    def test_sex_is_persisted_when_given(self):
        resp = self._signup(sex="female")
        self.assertEqual(resp.status_code, 201)
        self.db.set_user_speaker_sex.assert_called_once_with(USER, "female")

    def test_sex_is_optional(self):
        """Not mandatory at the BE. An account created without it is complete;
        the composite simply uses sex-blind weights until it is answered."""
        resp = self._signup()
        self.assertEqual(resp.status_code, 201)
        self.db.set_user_speaker_sex.assert_not_called()

    def test_a_bad_value_is_rejected_before_the_account_exists(self):
        """Order matters. Validating after create_user would leave an orphaned
        Supabase account behind every typo."""
        resp = self._signup(sex="m")
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.get_json()["code"], "INVALID_INPUT")
        self.create_client.assert_not_called()
        self.supabase.auth.admin.create_user.assert_not_called()

    def test_a_failed_sex_write_does_not_fail_the_signup(self):
        """The account already exists by then. Losing a weight-routing hint is
        not worth failing a registration over — the user can set it later."""
        self.db.set_user_speaker_sex.side_effect = RuntimeError("boom")
        resp = self._signup(sex="male")
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.get_json()["user"]["id"], USER)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class StoreTests(unittest.TestCase):
    """The write is deliberately PARTIAL — called unbound against a fake self
    so no Supabase client is constructed."""

    def _fake_db(self):
        from services.db import DatabaseService
        fake = MagicMock()
        return DatabaseService, fake

    def test_the_write_carries_neither_domain_nor_goal(self):
        DatabaseService, fake = self._fake_db()
        ok = DatabaseService.set_user_speaker_sex(fake, USER, "male")
        self.assertTrue(ok)
        payload = fake.client.table.return_value.upsert.call_args[0][0]
        self.assertEqual(payload["user_id"], USER)
        self.assertEqual(payload["profile_sex"], "male")
        self.assertNotIn("profile_domain", payload)
        self.assertNotIn("profile_goal", payload)

    def test_a_missing_column_degrades_instead_of_raising(self):
        """Pre-migration environments read as 'never asked' and write False —
        the composite then uses sex-blind weights, which is its shipped
        behaviour. Un-improved, never broken."""
        DatabaseService, fake = self._fake_db()
        fake.client.table.side_effect = Exception(
            "PGRST204 column user_settings.profile_sex does not exist")
        self.assertIsNone(DatabaseService.get_user_speaker_sex(fake, USER))
        self.assertFalse(DatabaseService.set_user_speaker_sex(fake, USER, "male"))

    def test_no_user_id_is_a_no_op(self):
        DatabaseService, fake = self._fake_db()
        self.assertIsNone(DatabaseService.get_user_speaker_sex(fake, ""))
        self.assertFalse(DatabaseService.set_user_speaker_sex(fake, "", "male"))
        fake.client.table.assert_not_called()


class MigrationTests(unittest.TestCase):
    """Pure file reads — no app deps, so these run everywhere."""

    def _sql(self) -> str:
        with open("migrations/add_speaker_sex.sql", encoding="utf-8") as fh:
            return fh.read()

    def test_migration_is_idempotent(self):
        sql = self._sql()
        self.assertIn("ADD COLUMN IF NOT EXISTS", sql)
        self.assertIn("FROM pg_constraint", sql)   # constraint added via probe

    def test_the_check_matches_the_code_enum(self):
        """Three places have to agree on the same three strings: the DB CHECK,
        the validator, and the composite's routing table. Drift between them
        is a 500 at write time or a silently unrouted speaker."""
        from services.voice_confidence import _SEX_VALUES
        sql = self._sql()
        for value in _SEX_VALUES:
            self.assertIn(f"'{value}'", sql)
        self.assertIn("profile_sex IS NULL OR", sql)   # NULL stays legal


if __name__ == "__main__":
    unittest.main()
