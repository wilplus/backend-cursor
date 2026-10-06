"""A deletion completes by itself after seven days: the application side
(founder 2026-10-05, decisions log N48.4 Q14 A, Q17 A, Q19 A; migration
0422). tests/test_a_deletion_completes_after_seven_days_postgres.py runs the
SQL; this pins:

  * what the speaker's app reads: the deletion view, whether it can still be
    cancelled, the status read's ``pending_deletion``;
  * the authority service maps every refusal to its code and status;
  * the completion run: what is due, a dry run that writes nothing, one run
    at a time, a purge that stops for a person, a fault that never stops
    the others, the lease always released;
  * the routes: the terminate split, the cancel, the cron route's two gates;
  * learning stops: the pair stamp and the corpus copy job.

Flask-route classes skip locally without app deps and run in CI.
"""
from __future__ import annotations

import pathlib
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

from services import account_deletion as ad
from services import deletion_completion as dc
from services import processing_authorization as pa
from services.project_deletion import ProjectDeletionService, public_view

try:
    from flask import Flask
    from routes.v2 import processing_authorization as pa_routes
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    _IMPORT_ERROR = e

ROOT = pathlib.Path(__file__).resolve().parents[1]
NOW = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
PRINCIPAL = "11111111-1111-4111-8111-111111111111"
REQUEST = "22222222-2222-4222-8222-222222222222"
PURGE = "33333333-3333-4333-8333-333333333333"


def _iso(moment: datetime) -> str:
    return moment.isoformat()


class _ApiError(Exception):
    def __init__(self, message, code=""):
        super().__init__(message)
        self.code = code


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


class ViewTests(unittest.TestCase):

    def test_the_view_carries_ids_state_dates_and_whether_to_offer_cancel(self):
        view = ad.deletion_view(_account_row(), NOW)
        self.assertEqual(set(view), {
            "purge_id", "request_id", "id", "kind", "trigger_kind", "project_id",
            "state", "requested_at", "completes_after", "cancellable",
            "cancelled_at", "completed_at"})
        self.assertEqual((view["purge_id"], view["request_id"], view["kind"]),
                         (REQUEST, REQUEST, "account"))
        self.assertIs(view["cancellable"], True)
        self.assertNotIn("acquisition_principal_id", view)
        self.assertIsNone(ad.deletion_view(None))

    def test_only_a_pending_request_inside_its_window_is_cancellable(self):
        self.assertTrue(ad.cancellable(_account_row(), NOW))
        self.assertFalse(ad.cancellable(
            _account_row(completes_after=_iso(NOW - timedelta(seconds=1))), NOW))
        for state in ("cancelled", "started", "done"):
            self.assertFalse(ad.cancellable(_account_row(state=state), NOW), state)
        self.assertFalse(ad.cancellable(_account_row(completes_after="soon"), NOW))

    def test_a_reason_is_a_machine_code_or_the_default(self):
        self.assertEqual(ad.reason_code("ACCOUNT_DELETION"), "ACCOUNT_DELETION")
        self.assertEqual(ad.reason_code("service_termination"), "SERVICE_TERMINATION")
        for raw in (None, "", "I want to leave because…", "x" * 65):
            self.assertEqual(ad.reason_code(raw), "ACCOUNT_DELETION", raw)

    def test_a_project_view_has_the_same_window_words(self):
        row = {"id": "r1", "project_id": "p1", "state": "pending",
               "requested_at": _iso(NOW), "due_at": _iso(NOW + timedelta(days=7)),
               "cancelled_at": None, "acquisition_principal_id": PRINCIPAL}
        view = public_view(row, NOW)
        self.assertEqual((view["kind"], view["completes_after"], view["cancellable"]),
                         ("project", row["due_at"], True))
        self.assertFalse(public_view({**row, "due_at": _iso(NOW)}, NOW)["cancellable"])
        self.assertFalse(public_view({**row, "state": "confirmed"}, NOW)["cancellable"])
        self.assertNotIn("acquisition_principal_id", view)


class LearningStoppedTests(unittest.TestCase):

    def test_the_answer_is_the_function_s(self):
        for data, expected in ((True, True), (False, False), ([True], True),
                               ([{"phase1_learning_stopped_v1": True}], True),
                               (None, False)):
            database = _db(phase1_learning_stopped_v1=data)
            self.assertIs(ad.learning_stopped(database, PRINCIPAL), expected, data)

    def test_no_client_no_principal_or_no_migration_is_no(self):
        self.assertFalse(ad.learning_stopped(SimpleNamespace(), PRINCIPAL))
        self.assertFalse(ad.learning_stopped(_db(), None))
        missing = _db(phase1_learning_stopped_v1=_ApiError("no function", "PGRST202"))
        self.assertFalse(ad.learning_stopped(missing, PRINCIPAL))

    def test_any_other_failure_stops_learning(self):
        broken = _db(phase1_learning_stopped_v1=_ApiError("timeout", "57014"))
        with self.assertLogs("services.account_deletion", "WARNING"):
            self.assertTrue(ad.learning_stopped(broken, PRINCIPAL))


class AccountServiceTests(unittest.TestCase):

    def test_refusals_keep_their_code_and_status(self):
        for raised, code, status in (
            ("ACCOUNT_DELETION_NOT_FOUND", "ACCOUNT_DELETION_NOT_FOUND", 404),
            ("ACCOUNT_DELETION_WINDOW_CLOSED", "ACCOUNT_DELETION_WINDOW_CLOSED", 409),
            ("ACCOUNT_DELETION_ALREADY_STARTED", "ACCOUNT_DELETION_ALREADY_STARTED", 409),
        ):
            database = _db(cancel_phase1_account_deletion_v1=_ApiError(f"P0001: {raised}"))
            with self.assertRaises(ad.AccountDeletionRefused) as ctx:
                ad.AccountDeletionService(database).cancel(PRINCIPAL, REQUEST)
            self.assertEqual((ctx.exception.code, ctx.exception.status), (code, status))

    def test_an_unmigrated_function_is_unavailable_and_other_faults_raise(self):
        missing = _db(request_phase1_account_deletion_v1=_ApiError("x", "PGRST202"))
        with self.assertRaises(ad.AccountDeletionRefused) as ctx:
            ad.AccountDeletionService(missing).request(PRINCIPAL, idempotency_key="k")
        self.assertEqual(ctx.exception.status, 503)
        broken = _db(request_phase1_account_deletion_v1=_ApiError("boom", "XX000"))
        with self.assertRaises(_ApiError):
            ad.AccountDeletionService(broken).request(PRINCIPAL, idempotency_key="k")

    def test_the_request_sends_a_clean_reason(self):
        database = _db(request_phase1_account_deletion_v1=[_account_row()])
        ad.AccountDeletionService(database).request(
            PRINCIPAL, idempotency_key="k", reason="please delete me")
        name, params = database.client.calls[0]
        self.assertEqual(params["p_reason_code"], "ACCOUNT_DELETION")

    def test_a_cancel_by_a_malformed_id_never_reaches_the_database(self):
        database = _db()
        with self.assertRaises(ad.AccountDeletionRefused) as ctx:
            ad.AccountDeletionService(database).cancel(PRINCIPAL, "../etc")
        self.assertEqual(ctx.exception.status, 404)
        self.assertEqual(database.client.calls, [])

    def test_the_live_request_is_the_newest(self):
        rows = [_account_row(id="a", state="started", requested_at="2026-09-01T00:00:00+00:00"),
                _account_row(id="b", state="done", requested_at="2026-10-01T00:00:00+00:00"),
                _account_row(id="c", state="cancelled", requested_at="2026-10-04T00:00:00+00:00")]
        database = _db({"account_deletion_requests": rows})
        self.assertEqual(ad.AccountDeletionService(database).live_for_principal(PRINCIPAL)["id"], "b")
        empty = _db({"account_deletion_requests": _ApiError("missing", "42P01")})
        self.assertIsNone(ad.AccountDeletionService(empty).live_for_principal(PRINCIPAL))


class AuthorityTests(unittest.TestCase):
    """The routes call the one boundary; it speaks ProcessingAuthorizationError."""

    def _service(self, **kw):
        return pa.ProcessingAuthorizationService(_db(**kw), mode="off")

    def test_a_request_answers_the_view(self):
        view = self._service(request_phase1_account_deletion_v1=[_account_row()]
                             ).request_account_deletion(PRINCIPAL, idempotency_key="k")
        self.assertEqual((view["purge_id"], view["kind"], view["state"]),
                         (REQUEST, "account", "pending"))

    def test_refusals_and_faults_map_to_codes(self):
        service = self._service(cancel_phase1_account_deletion_v1=_ApiError(
            "P0001: ACCOUNT_DELETION_WINDOW_CLOSED"))
        with self.assertRaises(pa.ProcessingAuthorizationError) as ctx:
            service.cancel_account_deletion(PRINCIPAL, REQUEST)
        self.assertEqual((ctx.exception.code, ctx.exception.status),
                         ("ACCOUNT_DELETION_WINDOW_CLOSED", 409))
        broken = self._service(request_phase1_account_deletion_v1=_ApiError("boom", "XX000"))
        with self.assertRaises(pa.ProcessingAuthorizationError) as ctx:
            broken.request_account_deletion(PRINCIPAL, idempotency_key="k")
        self.assertEqual((ctx.exception.code, ctx.exception.status),
                         ("PURGE_REQUEST_FAILED", 503))

    def test_without_0422_a_request_is_still_recorded_the_old_way(self):
        service = self._service(
            request_phase1_account_deletion_v1=_ApiError("no function", "PGRST202"),
            request_phase1_purge_v1={"purge_request_id": PURGE, "state": "requested"})
        with self.assertLogs("services.processing_authorization", "WARNING"):
            row = service.request_account_deletion(PRINCIPAL, idempotency_key="k")
        self.assertEqual(row, {"purge_request_id": PURGE, "state": "requested"})
        name, params = service.client.calls[-1]
        self.assertEqual((name, params["p_trigger_kind"]),
                         ("request_phase1_purge_v1", "account_deletion"))

    def test_an_unreadable_pending_deletion_is_none_and_logged(self):
        service = pa.ProcessingAuthorizationService(
            _db({"account_deletion_requests": _ApiError("timeout", "57014")}), mode="off")
        with self.assertLogs("services.processing_authorization", "WARNING"):
            self.assertIsNone(service.pending_deletion(PRINCIPAL))

    def test_the_status_read_by_id_falls_back_to_the_purge_request(self):
        purge = {"id": PURGE, "trigger_kind": "service_termination", "state": "requested",
                 "requested_at": _iso(NOW), "completed_at": None,
                 "acquisition_principal_id": PRINCIPAL}
        service = pa.ProcessingAuthorizationService(_db({
            "account_deletion_requests": [_account_row()],
            "data_purge_requests": [purge]}), mode="off")
        self.assertEqual(service.deletion_status(PRINCIPAL, REQUEST)["kind"], "account")
        self.assertEqual(service.deletion_status(PRINCIPAL, PURGE)["id"], PURGE)


# ── The completion run ────────────────────────────────────────────────────


def _tables(*, account=(), project=(), purges=(), targets=()):
    return {"account_deletion_requests": list(account),
            "project_deletion_requests": list(project),
            "data_purge_requests": list(purges),
            "data_purge_targets": list(targets)}


def _due(**over):
    return _account_row(**{"completes_after": _iso(NOW - timedelta(hours=1)), **over})


class CollectTests(unittest.TestCase):

    def test_what_is_due_and_what_waits(self):
        later = _iso(NOW + timedelta(days=2))
        tables = _tables(
            account=[_due(id="due"), _account_row(id="window"),
                     _due(id="resume", state="started", purge_request_id="p-run"),
                     _account_row(id="early", state="started", purge_request_id="p-early",
                                  completes_after=later),
                     _due(id="finish", state="started", purge_request_id="p-done"),
                     _due(id="person", state="started", purge_request_id="p-review")],
            project=[{"id": "proj", "project_id": "x", "state": "pending",
                      "due_at": _iso(NOW - timedelta(days=1)), "purge_request_id": None},
                     {"id": "proj-early", "project_id": "y", "state": "confirmed",
                      "due_at": later, "purge_request_id": "p-op"}],
            purges=[{"id": "p-run", "state": "requested"},
                    {"id": "p-early", "state": "in_progress"},
                    {"id": "p-done", "state": "done"},
                    {"id": "p-review", "state": "review_required"},
                    {"id": "p-op", "state": "requested"}])
        work = {item.request_id: item.action for item in dc.collect(_db(tables), NOW)}
        self.assertEqual(work, {"due": "start", "resume": "resume", "finish": "complete",
                                "person": "review", "proj": "start"})


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

    def test_a_held_lease_turns_the_run_away(self):
        database = self._db(_tables(account=[_due()]),
                            claim_deletion_completion_lease_v1=False)
        report = dc.run_due_deletions(database, execute=True, now=NOW)
        self.assertEqual((report["skipped"], report["outcomes"]), ("LEASE_HELD", []))
        self.assertEqual([c[0] for c in database.client.calls],
                         ["claim_deletion_completion_lease_v1"])

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

    def test_a_fault_is_reported_the_others_go_on_and_the_lease_is_released(self):
        database = self._db(
            _tables(account=[_due(id="a"), _due(id="b")]),
            start_due_account_deletion_v1=lambda p: (
                _ApiError("boom", "XX000") if p["p_request_id"] == "a"
                else [_due(id="b", state="started", purge_request_id=PURGE)]),
            complete_phase1_account_deletion_v1=[_due(id="b", state="done")])
        with self.assertLogs("services.deletion_completion", "ERROR"):
            report, _, _ = self._run(database, "done")
        results = {o["request_id"]: o["result"] for o in report["outcomes"]}
        self.assertEqual(results, {"a": "error", "b": "completed"})
        self.assertEqual(database.client.calls[-1][0], "release_deletion_completion_lease_v1")

    def test_a_run_that_loses_its_lease_stops(self):
        answers = iter([True, False])
        database = self._db(_tables(account=[_due(id="a"), _due(id="b")]),
                            claim_deletion_completion_lease_v1=lambda _p: next(answers))
        report, orchestrator, _ = self._run(database, "done")
        self.assertEqual((report["stopped"], report["outcomes"]), ("LEASE_LOST", []))
        orchestrator.run.assert_not_called()
        self.assertNotIn("release_sweep", report)

    def test_an_executing_run_ends_by_sweeping_the_voided_releases(self):
        database = self._db(_tables())
        key = "pair-releases/praise_line/2026-10-05/pairs.jsonl"
        marked: list = []
        database.list_voided_unpurged_pair_releases = lambda: [
            {"id": "r1", "storage_bucket": "releases", "storage_key": key}]
        database.mark_pair_release_purged = marked.append
        storage = mock.Mock()

        report = dc.run_due_deletions(database, execute=True, now=NOW,
                                      release_storage=storage)

        self.assertEqual(report["release_sweep"], {"purged": 1, "failed": []})
        self.assertEqual(storage.delete.call_args_list, [
            mock.call("releases", key),
            mock.call("releases", key.replace("pairs.jsonl", "manifest.json"))])
        self.assertEqual(marked, ["r1"])
        self.assertEqual(database.client.calls[-1][0], "release_deletion_completion_lease_v1")
        dry = dc.run_due_deletions(database, execute=False, now=NOW,
                                   release_storage=storage)
        self.assertNotIn("release_sweep", dry)
        self.assertEqual(storage.delete.call_count, 2)

    def test_a_sweep_that_cannot_run_is_reported_and_never_fails_the_run(self):
        database = self._db(_tables())
        database.list_voided_unpurged_pair_releases = mock.Mock(
            side_effect=RuntimeError("ledger down"))
        with self.assertLogs("services.pair_release", "WARNING"):
            report = dc.run_due_deletions(database, execute=True, now=NOW,
                                          release_storage=mock.Mock())
        self.assertEqual(report["release_sweep"],
                         {"purged": 0, "unavailable": "ledger down"})
        with mock.patch("services.pair_release.sweep_voided",
                        side_effect=RuntimeError("boom")), \
                self.assertLogs("services.deletion_completion", "WARNING"):
            report = dc.run_due_deletions(database, execute=True, now=NOW,
                                          release_storage=mock.Mock())
        self.assertEqual(report["release_sweep"], {"purged": 0, "unavailable": "boom"})

    def test_fresh_starts_come_before_resumptions(self):
        tables = _tables(
            account=[_due(id="old", state="started", purge_request_id="p1",
                          completes_after=_iso(NOW - timedelta(days=30))),
                     _due(id="new")],
            purges=[{"id": "p1", "state": "in_progress"}])
        self.assertEqual([w.request_id for w in dc.collect(_db(tables), NOW)],
                         ["new", "old"])

    def test_the_limit_is_kept_and_bounded(self):
        database = self._db(_tables(account=[_due(id=f"r{i}") for i in range(30)]))
        report = dc.run_due_deletions(database, execute=False, limit=500, now=NOW)
        self.assertEqual((len(report["outcomes"]), report["deferred"]),
                         (dc.MAX_LIMIT, 30 - dc.MAX_LIMIT))


class ProjectServiceTests(unittest.TestCase):

    def test_the_window_refusals_are_conflicts(self):
        from services.project_deletion import ProjectDeletionError
        for raised in ("PROJECT_DELETION_WINDOW_CLOSED", "PROJECT_DELETION_WINDOW_OPEN"):
            service = ProjectDeletionService(_db(
                cancel_project_deletion_v1=_ApiError(f"P0001: {raised}"),
                start_due_project_deletion_v1=_ApiError(f"P0001: {raised}")))
            for call in (lambda: service.cancel(PRINCIPAL, "p"),
                         lambda: service.start_due("r")):
                with self.assertRaises(ProjectDeletionError) as ctx:
                    call()
                self.assertEqual((ctx.exception.code, ctx.exception.status), (raised, 409))

    def test_an_owner_s_open_requests_newest_first(self):
        rows = [{"id": "old", "acquisition_principal_id": PRINCIPAL, "state": "pending",
                 "requested_at": "2026-09-01T00:00:00+00:00"},
                {"id": "new", "acquisition_principal_id": PRINCIPAL, "state": "confirmed",
                 "requested_at": "2026-10-01T00:00:00+00:00"}]
        service = ProjectDeletionService(_db({"project_deletion_requests": rows}))
        self.assertEqual([r["id"] for r in service.open_for_principal(PRINCIPAL)],
                         ["new", "old"])
        missing = ProjectDeletionService(_db({"project_deletion_requests": _ApiError("x", "42P01")}))
        self.assertEqual(missing.open_for_principal(PRINCIPAL), [])


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

    def test_the_copy_job_stops_for_a_leaving_person(self):
        from services import training_corpus
        database = SimpleNamespace(
            client=_Client(phase1_learning_stopped_v1=True),
            v2_get_session_by_id=lambda _sid: {"owner_principal_id": PRINCIPAL},
            get_mlc2_training_consent_status=lambda _p: {"active": True,
                                                         "grant_event_id": "g1"})
        with mock.patch.object(training_corpus, "copy_enabled", return_value=True):
            out = training_corpus.run_corpus_copy("take-1", "arc-1", database=database)
        self.assertEqual(out, {"status": "learning_stopped"})


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
                               return_value=ad.deletion_view(_account_row())) as window, \
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

    def test_the_cancel_answers_the_view_or_the_refusal(self):
        S = pa.ProcessingAuthorizationService
        with mock.patch.object(S, "cancel_account_deletion", return_value=ad.deletion_view(
                _account_row(state="cancelled", cancelled_at=_iso(NOW)))):
            body, status = self._call(pa_routes.v2_processing_deletion_cancel, "POST",
                                      purge_id=REQUEST)
        self.assertEqual((status, body["state"], body["cancellable"]), (200, "cancelled", False))
        with mock.patch.object(S, "cancel_account_deletion", side_effect=pa.ProcessingAuthorizationError(
                "ACCOUNT_DELETION_WINDOW_CLOSED", "closed", 409)):
            body, status = self._call(pa_routes.v2_processing_deletion_cancel, "POST",
                                      purge_id=REQUEST)
        self.assertEqual((status, body["code"]), (409, "ACCOUNT_DELETION_WINDOW_CLOSED"))

    def test_the_status_read_carries_the_pending_deletion(self):
        S = pa.ProcessingAuthorizationService
        with mock.patch.object(S, "status", return_value={
                "authorized": False, "code": "PROCESSING_SERVICE_BLOCKED"}), \
                mock.patch.object(S, "pending_deletion",
                                  return_value=ad.deletion_view(_account_row())), \
                mock.patch.object(S, "pending_project_deletions", return_value=[]):
            body, status = self._call(pa_routes.v2_processing_authorization, "GET")
        self.assertEqual(status, 200)
        self.assertEqual(body["code"], "PROCESSING_SERVICE_BLOCKED")
        self.assertEqual(body["pending_deletion"]["purge_id"], REQUEST)
        self.assertEqual(body["pending_project_deletions"], [])


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

    def test_the_admin_read_needs_an_admin(self):
        self.assertIn(self.client.get("/v2/admin/deletions").status_code, (401, 403))
        source = (ROOT / "routes/v2/projects.py").read_text()
        start = source.index("def v2_admin_deletions")
        head = source[source.rindex("@v2_bp.route", 0, start):start]
        self.assertIn("@require_admin", head)


class OperatorScriptTests(unittest.TestCase):
    """scripts/run_due_deletions.py: a preview unless doubly told."""

    def setUp(self):
        try:
            from scripts import run_due_deletions as script
        except Exception as e:  # pragma: no cover
            self.skipTest(f"script import failed: {e}")
        self.script = script

    def test_a_preview_writes_nothing_and_execute_needs_the_switch(self):
        with mock.patch.object(self.script, "run_due_deletions",
                               return_value={"mode": "dry_run"}) as run, \
                mock.patch("builtins.print"):
            self.assertEqual(self.script.main([]), 0)
            self.assertIs(run.call_args.kwargs["execute"], False)
            with mock.patch.dict("os.environ", {"PHASE1_PURGE_EXECUTION_ENABLED": ""}):
                with self.assertRaises(SystemExit) as ctx:
                    self.script.main(["--execute"])
            self.assertEqual(str(ctx.exception), "PHASE1_PURGE_EXECUTION_DISABLED")
            with mock.patch.dict("os.environ", {"PHASE1_PURGE_EXECUTION_ENABLED": "true"}):
                self.assertEqual(self.script.main(["--execute", "--limit", "2"]), 0)
            self.assertEqual((run.call_args.kwargs["execute"], run.call_args.kwargs["limit"]),
                             (True, 2))


class ConfigTests(unittest.TestCase):

    def test_only_true_executes(self):
        """The operator script's reading of the kill switch, in a process of
        its own so no other test sees a reloaded Config."""
        import json
        import subprocess
        import sys
        probe = (
            "import importlib, json, os\n"
            "import config\n"
            "out = {}\n"
            "for raw in ('true', ' TRUE ', '1', 'yes', ''):\n"
            "    os.environ['PHASE1_PURGE_EXECUTION_ENABLED'] = raw\n"
            "    importlib.reload(config)\n"
            "    out[raw] = config.Config.PHASE1_PURGE_EXECUTION_ENABLED\n"
            "print(json.dumps(out))\n")
        done = subprocess.run([sys.executable, "-c", probe], cwd=ROOT,
                              capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(done.stdout.strip().splitlines()[-1]), {
            "true": True, " TRUE ": True, "1": False, "yes": False, "": False})


if __name__ == "__main__":
    unittest.main()
