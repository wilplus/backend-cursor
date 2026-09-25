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

import inspect
import pathlib
import unittest

from services import processing_authorization as pa

try:
    from flask import Flask, request
    from routes import phase2_guard
    from routes.v2 import coach as v2_coach
    from routes.v2 import processing_authorization as pa_routes
    from services.db import db
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

    def test_a_yes_is_allowed_in_every_mode(self):
        for mode in ("off", "enforce"):
            service = _service(mode, get_phase1_consent_choices_v1=_choices())
            self.assertTrue(service.choice_permitted(
                PRINCIPAL, pa.PERSONALISED_PRACTICE), mode)

    def test_nothing_to_read_follows_the_gate(self):
        for answer in (_choices(has_receipt=False), None,
                       RuntimeError("function missing")):
            self.assertFalse(_service(
                "enforce", get_phase1_consent_choices_v1=answer
            ).choice_permitted(PRINCIPAL, pa.PERSONALISED_PRACTICE), answer)
            self.assertTrue(_service(
                "off", get_phase1_consent_choices_v1=answer
            ).choice_permitted(PRINCIPAL, pa.PERSONALISED_PRACTICE), answer)

    def test_the_two_choices_are_read_separately(self):
        service = _service("enforce", get_phase1_consent_choices_v1=_choices(
            practice=True, sensitive=False))
        self.assertTrue(service.choice_permitted(
            PRINCIPAL, pa.PERSONALISED_PRACTICE))
        self.assertFalse(service.choice_permitted(
            PRINCIPAL, pa.SENSITIVE_INFORMATION))


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

    def test_reading_is_untouched_by_the_withdrawal(self):
        # The core gate uses operation="core_service" for every read.
        service = _service("off", get_phase1_consent_choices_v1=_choices(
            sensitive=False))
        authority = service.require_current(PRINCIPAL, operation="core_service")
        self.assertEqual(authority.code, "PROCESSING_GATE_INACTIVE")
        self.assertEqual(service.client.calls, [])

    def test_recording_goes_ahead_with_the_consent_standing(self):
        service = _service("off", get_phase1_consent_choices_v1=_choices())
        authority = service.require_current(PRINCIPAL, operation="recording")
        self.assertEqual(authority.code, "PROCESSING_GATE_INACTIVE")


class SetChoiceTests(unittest.TestCase):
    def test_a_change_goes_to_the_one_function(self):
        state = _choices(practice=False)
        service = _service("enforce", set_phase1_consent_choice_v1=state)
        out = service.set_consent_choice(
            PRINCIPAL, choice=pa.PERSONALISED_PRACTICE, enabled=False,
            idempotency_key="key-12345678", client_version="web")
        self.assertEqual(out, state)
        name, params = service.client.calls[0]
        self.assertEqual(name, "set_phase1_consent_choice_v1")
        self.assertEqual(params["p_choice"], "personalised_practice")
        self.assertIs(params["p_enabled"], False)

    def test_bad_input_never_reaches_the_database(self):
        service = _service("enforce")
        for kwargs in (
            {"choice": "marketing", "enabled": False, "idempotency_key": "k" * 9},
            {"choice": pa.PERSONALISED_PRACTICE, "enabled": "no",
             "idempotency_key": "k" * 9},
            {"choice": pa.PERSONALISED_PRACTICE, "enabled": False,
             "idempotency_key": "short"},
        ):
            with self.assertRaises(pa.ProcessingAuthorizationError):
                service.set_consent_choice(PRINCIPAL, client_version=None,
                                           **kwargs)
        self.assertEqual(service.client.calls, [])

    def test_database_refusals_keep_their_meaning(self):
        for raised, code, status in (
            ("PROCESSING_AUTHORIZATION_REQUIRED",
             "PROCESSING_AUTHORIZATION_REQUIRED", 403),
            ("CONSENT_CHOICE_INVALID", "CONSENT_CHOICE_INVALID", 400),
            ("connection reset", "CONSENT_CHOICE_FAILED", 503),
        ):
            service = _service("enforce", set_phase1_consent_choice_v1=(
                RuntimeError(raised)))
            with self.assertRaises(pa.ProcessingAuthorizationError) as ctx:
                service.set_consent_choice(
                    PRINCIPAL, choice=pa.SENSITIVE_INFORMATION, enabled=False,
                    idempotency_key="key-12345678", client_version=None)
            self.assertEqual((ctx.exception.code, ctx.exception.status),
                             (code, status))


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

    def test_a_yes_lets_the_request_through(self):
        self.assertEqual(self._call(allowed=True), ("ran", 200))
        self.assertEqual(self.asked, [(PRINCIPAL, "personalised_practice")])

    def test_a_no_is_refused_before_the_handler(self):
        response, status = self._call(allowed=False)
        self.assertEqual(status, 403)
        self.assertEqual(response.get_json()["code"], "CONSENT_CHOICE_OFF")

    def test_an_unresolvable_caller_follows_the_gate(self):
        _response, status = self._call(allowed=True, principal=None,
                                       enforced=True)
        self.assertEqual(status, 403)
        self.assertEqual(self._call(allowed=True, principal=None,
                                    enforced=False), ("ran", 200))

    def test_every_practice_route_asks_and_the_recording_one_asks_twice(self):
        source = (ROOT / "routes/v2/user_sessions.py").read_text()
        for name in ("v2_start_confident_voice_practice",
                     "v2_get_confident_voice_practice",
                     "v2_add_confident_voice_practice_attempt",
                     "v2_complete_confident_voice_practice"):
            head = source[:source.index(f"def {name}(")]
            decorators = head[head.rindex("@v2_bp.route"):]
            self.assertIn('@consent_choice_required("personalised_practice")',
                          decorators, name)
            self.assertIn(
                '@operational_purpose_disabled('
                '"personalized_exercise_recommendation")', decorators, name)
        head = source[:source.index(
            "def v2_add_confident_voice_practice_attempt(")]
        self.assertIn('@consent_choice_required("sensitive_information")',
                      head[head.rindex("@v2_bp.route"):])


class OfferTests(unittest.TestCase):
    """The Feedback Manager's exercise offer asks about the Take's owner."""

    def _run(self, permitted):
        from services import ideal_text_changes as itc
        import services.confident_voice_practice as cvp

        attached: list = []
        original_attach = cvp.attach_exercise_offer
        cvp.attach_exercise_offer = (
            lambda changes, **kw: attached.append(kw) or ["with-offer"])
        try:
            run = itc._ChangesRun.__new__(itc._ChangesRun)
            run.changes = ["card"]
            run.arm_sid = "take-1"
            run.db = object()
            run._practice_permitted = lambda: permitted
            run._practice_offer()
            return run.changes, attached
        finally:
            cvp.attach_exercise_offer = original_attach

    def test_no_offer_without_the_person_s_yes(self):
        changes, attached = self._run(False)
        self.assertEqual(changes, ["card"])
        self.assertEqual(attached, [])

    def test_the_offer_is_attached_with_it(self):
        changes, attached = self._run(True)
        self.assertEqual(changes, ["with-offer"])
        self.assertEqual(attached[0]["take_session_id"], "take-1")

    def test_a_person_s_no_is_not_reported_as_a_degradation(self):
        from services import ideal_text_changes as itc
        source = inspect.getsource(itc)
        block = source[source.index("def _practice_offer"):
                       source.index("def _practice_permitted")]
        self.assertNotIn("log.note", block)


@unittest.skipIf(_IMPORT_ERROR is not None, f"flask app unavailable: {_IMPORT_ERROR}")
class CoachTests(unittest.TestCase):
    """E3: the coach's review asks about the SPEAKER."""

    def test_the_check_is_about_the_take_not_the_coach(self):
        source = inspect.getsource(v2_coach._speaker_practice_permitted)
        self.assertIn("take_acquisition_principal", source)
        self.assertNotIn("request.user_id", source)

    def test_it_runs_after_the_blind_gate_and_before_the_practice(self):
        source = (ROOT / "routes/v2/coach.py").read_text()
        start = source.index("def v2_coach_confident_voice_practice")
        route = source[start:source.index("@v2_bp.route", start)]
        self.assertLess(route.index("BLIND_RATING_REQUIRED"),
                        route.index("_speaker_practice_permitted(owner_sid)"))
        self.assertLess(route.index("_speaker_practice_permitted(owner_sid)"),
                        route.index("get_confident_voice_practice_by_take"))
        self.assertIn('"SPEAKER_PRACTICE_OFF"', route)


@unittest.skipIf(_IMPORT_ERROR is not None, f"flask app unavailable: {_IMPORT_ERROR}")
class ChoicesRouteTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self._orig_principal = pa_routes._principal_id
        self._orig_client = db.client
        pa_routes._principal_id = lambda: PRINCIPAL

    def tearDown(self):
        pa_routes._principal_id = self._orig_principal
        db.client = self._orig_client

    def _call(self, method, body=None, **answers):
        db.client = _Client(**answers)
        raw = inspect.unwrap(pa_routes.v2_processing_choices)
        with self.app.test_request_context(method=method, json=body):
            response, status = raw()
        return response.get_json(), status, db.client.calls

    def test_get_returns_the_choices_in_force(self):
        body, status, _ = self._call(
            "GET", get_phase1_consent_choices_v1=_choices(practice=False))
        self.assertEqual(status, 200)
        self.assertIs(body["personalised_practice"], False)

    def test_an_unreadable_state_is_a_503_not_a_guess(self):
        _body, status, _ = self._call(
            "GET", get_phase1_consent_choices_v1=RuntimeError("down"))
        self.assertEqual(status, 503)

    def test_post_changes_one_choice(self):
        body, status, calls = self._call(
            "POST", {"choice": "personalised_practice", "enabled": False,
                     "idempotency_key": "key-12345678"},
            set_phase1_consent_choice_v1=_choices(practice=False))
        self.assertEqual(status, 200)
        self.assertIs(body["personalised_practice"], False)
        self.assertEqual(calls[0][1]["p_acquisition_principal_id"], PRINCIPAL)

    def test_post_refuses_a_malformed_body(self):
        for payload in (["x"], {"choice": "personalised_practice",
                                "enabled": "false",
                                "idempotency_key": "key-12345678"}):
            _body, status, calls = self._call("POST", payload)
            self.assertEqual(status, 400, payload)
            self.assertEqual(calls, [])

    def test_the_route_sits_where_the_core_gate_never_locks_it(self):
        source = (ROOT / "routes/v2/processing_authorization.py").read_text()
        self.assertIn('"/processing-authorization/choices"', source)
        gate = source[source.index("def enforce_phase1_processing_gate"):]
        self.assertIn('path.startswith(\n        "/v2/processing-authorization"',
                      gate)


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

    def test_a_recording_that_would_not_go_keeps_its_row_and_practice(self):
        database = _PracticeDb({"p1": [{"id": "a1"}, {"id": "a2"}]},
                               failing_audio={"a2"})
        result = self._erase(database)
        self.assertFalse(result["complete"])
        self.assertNotIn(("attempt", "a2"), database.calls)
        self.assertNotIn(("practice", "p1"), database.calls)
        self.assertEqual([a["id"] for a in database.practices["p1"]], ["a2"])

    def test_a_failed_read_is_never_taken_for_nothing_to_delete(self):
        database = _PracticeDb({"p1": [{"id": "a1"}]}, graph_error=True)
        result = self._erase(database)
        self.assertFalse(result["complete"])
        self.assertEqual(database.calls, [])

    def test_the_backstop_retries_everyone_listed(self):
        from services.practice_retention import sweep_withdrawn_practice

        class _Db(_PracticeDb):
            def list_recent_practice_withdrawals(self, since, limit):
                self.asked = (since, limit)
                return [PRINCIPAL]

        database = _Db({"p1": [{"id": "a1"}]})
        totals = sweep_withdrawn_practice(database=database, limit=5)
        self.assertEqual(totals["people"], 1)
        self.assertEqual(totals["attempts"], 1)
        self.assertEqual(database.asked[1], 5)

    def test_the_worker_runs_the_backstop(self):
        source = (ROOT / "services/pipeline_jobs.py").read_text()
        self.assertIn("sweep_withdrawn_practice(", source)


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

    def test_nothing_else_erases(self):
        for choice, enabled, state in (
            (pa.PERSONALISED_PRACTICE, True, _choices(practice=True)),
            (pa.SENSITIVE_INFORMATION, False, _choices(sensitive=False)),
            # Practice already off, then the OTHER consent is withdrawn: only
            # the practice switch itself erases.
            (pa.SENSITIVE_INFORMATION, False,
             _choices(practice=False, sensitive=False)),
            (pa.SENSITIVE_INFORMATION, True, _choices()),
        ):
            out, erased = self._change(choice, enabled, state)
            self.assertEqual(erased, [], (choice, enabled))
            self.assertNotIn("practice_erasure", out)

    def test_the_route_calls_the_change_that_erases(self):
        source = (ROOT / "routes/v2/processing_authorization.py").read_text()
        route = source[source.index("def v2_processing_choices"):]
        route = route[:route.index("@v2_bp.route")]
        self.assertIn("service.change_consent_choice(", route)
        self.assertNotIn("service.set_consent_choice(", route)


if __name__ == "__main__":
    unittest.main()
