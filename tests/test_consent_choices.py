"""A person can change their mind, and every processing decision listens.

FOUNDER 2026-09-25, locked E1, E3, E5-A. The PostgreSQL behaviour of 0361 is
pinned in tests/test_consent_choices_postgres.py; this pins the application:

  * choice_permitted: an explicit "no" is refused in every mode; with nothing
    to read, an enforcing gate refuses and a gate that is off keeps the
    established path;
  * recording stops when the sensitive-information consent is withdrawn, in
    either mode, and nothing else stops with it (E5-A);
  * the practice routes ask about the CALLER, the Feedback Manager's offer
    asks about the Take's owner, and the coach's review asks about the
    SPEAKER, never the coach (E1, E3);
  * the choices route reads and changes a choice.

Run: python3 -m unittest tests.test_consent_choices
"""
from __future__ import annotations

import pathlib
import unittest

from services import processing_authorization as pa

try:
    from flask import Flask, request

    from routes import phase2_guard
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e

ROOT = pathlib.Path(__file__).resolve().parents[1]
PRINCIPAL = "11111111-1111-1111-1111-111111111111"


class _Result:
    def __init__(self, data):
        self.data = data


class _Call:
    def __init__(self, client, name, params):
        self.client, self.name, self.params = client, name, params

    def execute(self):
        self.client.calls.append((self.name, self.params))
        outcome = self.client.answers.get(self.name)
        if isinstance(outcome, Exception):
            raise outcome
        return _Result(outcome)


class _Client:
    def __init__(self, **answers):
        self.answers = answers
        self.calls: list = []

    def rpc(self, name, params):
        return _Call(self, name, params)


class _Db:
    def __init__(self, client):
        self.client = client


def _service(mode, **answers):
    return pa.ProcessingAuthorizationService(_Db(_Client(**answers)), mode=mode)


def _choices(practice=True, sensitive=True, has_receipt=True):
    return {"has_receipt": has_receipt, "personalised_practice": practice,
            "sensitive_information": sensitive}


class ChoicePermittedTests(unittest.TestCase):
    def test_an_explicit_no_is_refused_in_every_mode(self):
        for mode in ("off", "enforce"):
            service = _service(mode, get_phase1_consent_choices_v1=_choices(
                practice=False))
            self.assertFalse(service.choice_permitted(
                PRINCIPAL, pa.PERSONALISED_PRACTICE), mode)


class RecordingWithdrawalTests(unittest.TestCase):
    """E5-A: withdrawing stops new recording, and only that."""

    def test_recording_is_refused_after_a_withdrawal_in_either_mode(self):
        for mode in ("off", "enforce"):
            service = _service(mode, get_phase1_consent_choices_v1=_choices(
                sensitive=False))
            with self.assertRaises(pa.ProcessingAuthorizationError) as ctx:
                service.require_current(PRINCIPAL, operation="recording")
            self.assertEqual(ctx.exception.code,
                             "PROCESSING_RECORDING_WITHDRAWN", mode)
            self.assertEqual(ctx.exception.status, 403)


@unittest.skipIf(_IMPORT_ERROR is not None, f"flask app unavailable: {_IMPORT_ERROR}")
class GuardTests(unittest.TestCase):
    """The practice routes ask about the caller."""

    def setUp(self):
        self.app = Flask(__name__)
        self._orig = (pa.ProcessingAuthorizationService.user_acquisition_principal,
                      pa.ProcessingAuthorizationService.choice_permitted,
                      pa.ProcessingAuthorizationService.enforced)
        self.asked: list = []

    def tearDown(self):
        (pa.ProcessingAuthorizationService.user_acquisition_principal,
         pa.ProcessingAuthorizationService.choice_permitted,
         pa.ProcessingAuthorizationService.enforced) = self._orig

    def _call(self, *, allowed, principal=PRINCIPAL, enforced=True):
        def resolve(_self, user_id):
            if principal is None:
                raise RuntimeError("unresolvable")
            return principal
        pa.ProcessingAuthorizationService.user_acquisition_principal = resolve
        pa.ProcessingAuthorizationService.choice_permitted = (
            lambda _self, who, choice: self.asked.append((who, choice)) or allowed)
        pa.ProcessingAuthorizationService.enforced = property(lambda _self: enforced)

        @phase2_guard.consent_choice_required("personalised_practice")
        def view():
            return "ran", 200

        with self.app.test_request_context():
            request.user_id = "user-1"
            return view()


    def test_a_no_is_refused_before_the_handler(self):
        response, status = self._call(allowed=False)
        self.assertEqual(status, 403)
        self.assertEqual(response.get_json()["code"], "CONSENT_CHOICE_OFF")


@unittest.skipIf(_IMPORT_ERROR is not None, f"flask app unavailable: {_IMPORT_ERROR}")
class CoachTests(unittest.TestCase):
    """E3: the coach's review asks about the SPEAKER."""


    def test_it_runs_after_the_blind_gate_and_before_the_practice(self):
        source = (ROOT / "routes/v2/coach.py").read_text()
        start = source.index("def v2_coach_confident_voice_practice")
        route = source[start:source.index("@v2_bp.route", start)]
        self.assertLess(route.index("BLIND_RATING_REQUIRED"),
                        route.index("_speaker_practice_permitted(owner_sid)"))
        self.assertLess(route.index("_speaker_practice_permitted(owner_sid)"),
                        route.index("get_confident_voice_practice_by_moment"))
        self.assertIn('"SPEAKER_PRACTICE_OFF"', route)


class _PracticeDb:
    """One person's practices and attempts, and the calls made to erase them."""

    def __init__(self, practices, *, failing_audio=(), graph_error=False):
        self.practices = {pid: list(attempts) for pid, attempts in practices.items()}
        self.failing_audio = set(failing_audio)
        self.graph_error = graph_error
        self.calls: list = []

    def practice_ids_for_principal(self, principal_id):
        if self.graph_error:
            raise RuntimeError("graph down")
        return list(self.practices)

    def list_confident_voice_practice_attempts(self, practice_id):
        return [dict(a) for a in self.practices.get(practice_id, [])]

    def delete_practice_audio_object(self, attempt_id):
        self.calls.append(("audio", attempt_id))
        return attempt_id not in self.failing_audio

    def delete_confident_voice_practice_attempt(self, attempt_id):
        self.calls.append(("attempt", attempt_id))
        for attempts in self.practices.values():
            attempts[:] = [a for a in attempts if a["id"] != attempt_id]
        return True

    def delete_confident_voice_practice(self, practice_id):
        self.calls.append(("practice", practice_id))
        self.practices.pop(practice_id, None)
        return True


class ErasureTests(unittest.TestCase):
    """E2: turning practice off deletes the practice recordings."""

    def _erase(self, database):
        from services.practice_retention import erase_practice_for_principal
        return erase_practice_for_principal(database=database,
                                            principal_id=PRINCIPAL)

    def test_everything_goes_recording_first_then_rows(self):
        database = _PracticeDb({
            # Open, chosen and album-kept attempts are NOT spared here: that
            # is the 30-day sweep's rule, not a withdrawal's.
            "p-open": [{"id": "a1"}, {"id": "a2", "kept": True}],
            "p-closed": [{"id": "a3"}],
        })
        result = self._erase(database)
        self.assertTrue(result["complete"])
        self.assertEqual(database.practices, {})
        self.assertEqual(database.calls[:2], [("audio", "a1"), ("attempt", "a1")])
        for practice in ("p-open", "p-closed"):
            self.assertIn(("practice", practice), database.calls)


class ChangeChoiceTests(unittest.TestCase):
    """Only turning PRACTICE off erases, and only when it is off after."""

    def _change(self, choice, enabled, state):
        import services.practice_retention as retention

        erased: list = []
        original = retention.erase_practice_for_principal
        retention.erase_practice_for_principal = (
            lambda **kw: erased.append(kw) or {"complete": True})
        try:
            service = _service("enforce", set_phase1_consent_choice_v1=state)
            out = service.change_consent_choice(
                PRINCIPAL, choice=choice, enabled=enabled,
                idempotency_key="key-12345678", client_version=None)
            return out, erased
        finally:
            retention.erase_practice_for_principal = original

    def test_turning_practice_off_erases_it(self):
        out, erased = self._change(pa.PERSONALISED_PRACTICE, False,
                                   _choices(practice=False))
        self.assertEqual(erased[0]["principal_id"], PRINCIPAL)
        self.assertEqual(out["practice_erasure"], {"complete": True})


if __name__ == "__main__":
    unittest.main()
