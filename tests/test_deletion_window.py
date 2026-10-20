"""
STORY    As a speaker who deletes my account, I want it to complete by itself
         after seven days unless I cancel, so that my data really goes.
OUTCOME
  O1  The daily run finishes a due deletion: started, purged, then marked
      done; a dry run only reports what it would do and writes nothing.
  O2  A purge that cannot finish is left for a person, with its reasons, and
      is not marked done.
  O3  Once I am leaving, my earlier "yes" to learning is kept on record but
      nothing of mine is released for learning.
  O4  Asking to delete my account opens the cancellable seven-day window;
      ending the service (termination) purges straight away.
  O5  The daily run's route is shut without its secret, refuses a wrong one,
      and deletes for real only when the kill switch is on.
PROVES   O1 -> RunTests::test_a_due_request_is_started_purged_and_finished,
               RunTests::test_a_dry_run_reads_and_writes_nothing
         O2 -> RunTests::test_a_purge_that_stops_is_left_for_a_person_with_its_reasons
         O3 -> LearningTests::test_the_stamp_keeps_the_yes_and_releases_nothing_of_a_leaving_person
         O4 -> SpeakerRouteTests::test_an_account_deletion_takes_the_window_and_a_termination_does_not
         O5 -> CronRouteTests::test_the_route_is_dead_without_its_secret_and_refuses_a_wrong_one,
               CronRouteTests::test_it_deletes_only_with_the_kill_switch_on
WHY      Founder 2026-10-05, decisions log N48.4 Q14 A, Q17 A, Q19 A (migration 0422).
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from services import account_deletion as ad
from services import deletion_completion as dc
from services import processing_authorization as pa

try:
    from flask import Flask

    from routes.v2 import processing_authorization as pa_routes
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    _IMPORT_ERROR = e

NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
PRINCIPAL = "11111111-1111-4111-8111-111111111111"
REQUEST = "22222222-2222-4222-8222-222222222222"
PURGE = "33333333-3333-4333-8333-333333333333"


def _iso(moment: datetime) -> str:
    return moment.isoformat()


class _Query:
    def __init__(self, client, relation):
        self.client, self.relation = client, relation
        self.filters: list = []

    def select(self, _columns):
        return self

    def eq(self, column, value):
        self.filters.append((column, {str(value)}))
        return self

    def in_(self, column, values):
        self.filters.append((column, {str(v) for v in values}))
        return self

    def limit(self, _count):
        return self

    def execute(self):
        self.client.reads.append(self.relation)
        outcome = self.client.tables.get(self.relation, [])
        if isinstance(outcome, Exception):
            raise outcome
        rows = [row for row in outcome
                if all(str(row.get(col)) in allowed for col, allowed in self.filters)]
        return SimpleNamespace(data=rows)


class _Client:
    def __init__(self, tables=None, **answers):
        self.tables = tables or {}
        self.answers = answers
        self.reads: list = []
        self.calls: list = []

    def table(self, relation):
        return _Query(self, relation)

    def rpc(self, name, params):
        client = self

        class _Call:
            def execute(self):
                client.calls.append((name, params))
                outcome = client.answers.get(name)
                if callable(outcome):
                    outcome = outcome(params)
                if isinstance(outcome, Exception):
                    raise outcome
                return SimpleNamespace(data=outcome)
        return _Call()


def _db(tables=None, **answers):
    return SimpleNamespace(client=_Client(tables, **answers))


def _account_row(**over):
    row = {"id": REQUEST, "acquisition_principal_id": PRINCIPAL, "state": "pending",
           "requested_at": _iso(NOW - timedelta(days=1)),
           "completes_after": _iso(NOW + timedelta(days=6)),
           "cancelled_at": None, "started_at": None, "completed_at": None,
           "purge_request_id": None}
    row.update(over)
    return row


# ── What the app reads ────────────────────────────────────────────────────


# ── The completion run ────────────────────────────────────────────────────


def _tables(*, account=(), project=(), purges=(), targets=()):
    return {"account_deletion_requests": list(account),
            "project_deletion_requests": list(project),
            "data_purge_requests": list(purges),
            "data_purge_targets": list(targets)}


def _due(**over):
    return _account_row(**{"completes_after": _iso(NOW - timedelta(hours=1)), **over})


class RunTests(unittest.TestCase):

    def _db(self, tables, **answers):
        answers.setdefault("claim_deletion_completion_lease_v1", True)
        answers.setdefault("release_deletion_completion_lease_v1", True)
        return _db(tables, **answers)

    def test_a_dry_run_reads_and_writes_nothing(self):
        database = self._db(_tables(account=[_due()]))
        report = dc.run_due_deletions(database, execute=False, now=NOW)
        self.assertEqual(report["mode"], "dry_run")
        self.assertEqual([o["result"] for o in report["outcomes"]], ["would_start"])
        self.assertEqual(database.client.calls, [])


    def _run(self, database, final_state):
        orchestrator = mock.Mock()
        orchestrator.run.return_value = {"result": {"state": final_state}}
        with mock.patch("services.data_purge_project_scope.orchestrator_for",
                        return_value=orchestrator) as chooser:
            report = dc.run_due_deletions(database, execute=True, now=NOW)
        return report, orchestrator, chooser

    def test_a_due_request_is_started_purged_and_finished(self):
        database = self._db(
            _tables(account=[_due()]),
            start_due_account_deletion_v1=[_due(state="started", purge_request_id=PURGE)],
            complete_phase1_account_deletion_v1=[_due(state="done")])
        report, orchestrator, _ = self._run(database, "done")
        self.assertEqual(report["outcomes"][0]["result"], "completed")
        orchestrator.run.assert_called_once_with(PURGE)
        names = [c[0] for c in database.client.calls]
        self.assertLess(names.index("start_due_account_deletion_v1"),
                        names.index("complete_phase1_account_deletion_v1"))
        self.assertEqual(names[-1], "release_deletion_completion_lease_v1")

    def test_a_purge_that_stops_is_left_for_a_person_with_its_reasons(self):
        database = self._db(
            _tables(account=[_due()], targets=[
                {"purge_request_id": PURGE, "target_ref": "dependency:ideal_part_revision",
                 "state": "unknown", "metadata": {"reason_code": "EXPLICIT_RESOLVER_REQUIRED"}}]),
            start_due_account_deletion_v1=[_due(state="started", purge_request_id=PURGE)])
        with self.assertLogs("services.deletion_completion", "WARNING"):
            report, _, _ = self._run(database, "review_required")
        outcome = report["outcomes"][0]
        self.assertEqual(outcome["result"], "left_for_a_person")
        self.assertEqual(outcome["reasons"], [{
            "target_ref": "dependency:ideal_part_revision", "state": "unknown",
            "reason": "EXPLICIT_RESOLVER_REQUIRED"}])
        self.assertNotIn("complete_phase1_account_deletion_v1",
                         [c[0] for c in database.client.calls])


# ── Learning stops ────────────────────────────────────────────────────────


class LearningTests(unittest.TestCase):

    def test_the_stamp_keeps_the_yes_and_releases_nothing_of_a_leaving_person(self):
        from services import pair_consent
        database = SimpleNamespace(
            client=_Client(phase1_learning_stopped_v1=True),
            get_owner_principal_for_user=lambda _uid: {"id": PRINCIPAL},
            get_mlc2_training_consent_status=lambda _p: {
                "active": True, "grant_event_id": "g1", "consent_policy_version": "v1"})
        stamp = pair_consent.stamp(database, surface="praise_line", owner_user_id="u1")
        self.assertEqual((stamp["consent_state"], stamp["releasable"]), ("yes", False))
        database.client.answers["phase1_learning_stopped_v1"] = False
        stamp = pair_consent.stamp(database, surface="praise_line", owner_user_id="u1")
        self.assertIs(stamp["releasable"], True)


# ── The routes ────────────────────────────────────────────────────────────


@unittest.skipIf(_IMPORT_ERROR is not None, f"flask app unavailable: {_IMPORT_ERROR}")
class SpeakerRouteTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self._principal = pa_routes._principal_id
        pa_routes._principal_id = lambda: PRINCIPAL

    def tearDown(self):
        pa_routes._principal_id = self._principal

    def _call(self, view, method, body=None, **kwargs):
        import inspect
        raw = inspect.unwrap(view)
        with self.app.test_request_context(method=method, json=body):
            response = raw(**kwargs)
        if isinstance(response, tuple):
            return response[0].get_json(), response[1]
        return response.get_json(), response.status_code

    def test_an_account_deletion_takes_the_window_and_a_termination_does_not(self):
        S = pa.ProcessingAuthorizationService
        with mock.patch.object(S, "request_account_deletion",
                               # The route reads the real clock: a window still open now.
                               return_value=ad.deletion_view(_account_row(
                                   completes_after=_iso(datetime.now(timezone.utc) + timedelta(days=6))))) as window, \
                mock.patch.object(S, "request_purge",
                                  return_value={"purge_request_id": PURGE}) as purge:
            body, status = self._call(pa_routes.v2_processing_terminate, "POST", {
                "trigger_kind": "account_deletion", "idempotency_key": "k1"})
            self.assertEqual((status, body["kind"], body["purge_id"]), (202, "account", REQUEST))
            self.assertTrue(body["cancellable"])
            window.assert_called_once()
            purge.assert_not_called()
            _, status = self._call(pa_routes.v2_processing_terminate, "POST", {
                "trigger_kind": "service_termination", "idempotency_key": "k2"})
            self.assertEqual(status, 202)
            purge.assert_called_once()


class CronRouteTests(unittest.TestCase):

    def setUp(self):
        try:
            from app import app
        except Exception as e:  # pragma: no cover
            self.skipTest(f"app import failed: {e}")
        app.config["TESTING"] = True
        self.client = app.test_client()

    def test_the_route_is_dead_without_its_secret_and_refuses_a_wrong_one(self):
        from config import Config
        with mock.patch.object(Config, "DELETION_COMPLETION_SECRET", ""):
            self.assertEqual(self.client.post("/v2/internal/deletion/complete-due",
                                              json={}).status_code, 503)
        with mock.patch.object(Config, "DELETION_COMPLETION_SECRET", "right"):
            self.assertEqual(self.client.post(
                "/v2/internal/deletion/complete-due", json={},
                headers={"X-Internal-Secret": "wrong"}).status_code, 401)

    def test_it_deletes_only_with_the_kill_switch_on(self):
        from config import Config
        for switch in (False, True):
            with mock.patch.object(Config, "DELETION_COMPLETION_SECRET", "right"), \
                    mock.patch.object(Config, "PHASE1_PURGE_EXECUTION_ENABLED", switch), \
                    mock.patch.object(dc, "run_due_deletions",
                                      return_value={"mode": "x", "outcomes": []}) as run:
                response = self.client.post(
                    "/v2/internal/deletion/complete-due", json={"limit": 3},
                    headers={"X-Internal-Secret": "right"})
            self.assertEqual(response.status_code, 200)
            self.assertIs(run.call_args.kwargs["execute"], switch)
            self.assertEqual(run.call_args.kwargs["limit"], 3)


if __name__ == "__main__":
    unittest.main()
