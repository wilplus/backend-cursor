"""
STORY    As a person who already has an account and fills in the sign-up form
         again, I want to be told my email is registered and sent to sign in.
OUTCOME
  O1  A sign-up with a registered email is answered 409 EMAIL_IN_USE.
  O2  That answer is not reported to Sentry as a server error.
PROVES   O1, O2 -> test_a_registered_email_is_told_to_sign_in
WHY      Sentry 2026-10-29: "AuthApiError v2.v2_auth_signup — A user with this
         email address has already been registered" raised as an error on
         every repeat sign-up.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class EmailInUse(unittest.TestCase):
    def test_a_registered_email_is_told_to_sign_in(self):
        from flask import Flask

        import routes.auth as auth_routes

        client = MagicMock()
        client.auth.admin.create_user.side_effect = Exception(
            "A user with this email address has already been registered")
        app = Flask(__name__)
        app.add_url_rule("/v2/auth/signup", view_func=auth_routes.signup, methods=["POST"])

        with patch.object(auth_routes, "new_client", return_value=client), \
                patch.object(auth_routes, "_signup_terms_version", return_value="1.2"), \
                patch.object(auth_routes.sentry_sdk, "capture_exception") as capture:
            response = app.test_client().post("/v2/auth/signup", json={
                "email": "a@example.com", "password": "secret1", "terms_accepted": True})

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["code"], "EMAIL_IN_USE")
        capture.assert_not_called()


if __name__ == "__main__":
    unittest.main()
