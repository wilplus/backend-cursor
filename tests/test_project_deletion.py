"""Project deletion requests (P1-A, founder 2026-09-25, decisions log N8).

The picker's Delete is a REQUEST: an operator confirms it within 7 days, the
project is locked until then, and its owner may cancel. These tests pin the
application side; tests/test_project_deletion_postgres.py runs the SQL.

Flask-route classes skip locally without app deps and run in CI.
"""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from services.project_deletion import (
    ProjectDeletionError,
    ProjectDeletionService,
    public_view,
)

try:
    from flask import Flask, request
    from routes.v2 import projects as v2_projects
    from services.canonical_product import OwnerPrincipal
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    request = None
    _IMPORT_ERROR = e

PROJECT = "22222222-2222-4222-8222-222222222222"
ROW = {
    "id": "r1", "acquisition_principal_id": "p1", "project_id": PROJECT,
    "state": "pending", "requested_at": "2026-09-25T12:00:00Z",
    "due_at": "2026-10-02T12:00:00Z", "cancelled_at": None,
}


class _ApiError(Exception):
    def __init__(self, message, code=""):
        super().__init__(message)
        self.code = code


def _client(*, rpc=None, rpc_error=None, rows=None, select_error=None):
    client = MagicMock()
    if rpc_error is not None:
        client.rpc.return_value.execute.side_effect = rpc_error
    else:
        client.rpc.return_value.execute.return_value = SimpleNamespace(data=rpc)
    chain = client.table.return_value.select.return_value
    for method in ("in_", "order", "limit"):
        getattr(chain, method).return_value = chain
    if select_error is not None:
        chain.execute.side_effect = select_error
    else:
        chain.execute.return_value = SimpleNamespace(data=rows or [])
    return client


class ServiceTests(unittest.TestCase):

    def _service(self, **kw):
        return ProjectDeletionService(SimpleNamespace(client=_client(**kw)))

    def test_request_returns_the_row(self):
        row = self._service(rpc=[ROW]).request("p1", PROJECT, "k")
        self.assertEqual(row["id"], "r1")

    def test_rpc_names_map_to_public_codes(self):
        for raised, code, status in (
            ("PROJECT_NOT_FOUND", "PROJECT_NOT_FOUND", 404),
            ("PROJECT_DELETION_NOT_PENDING", "PROJECT_DELETION_NOT_PENDING", 409),
            ("PROJECT_DELETION_ALREADY_CONFIRMED",
             "PROJECT_DELETION_ALREADY_CONFIRMED", 409),
            ("IDEMPOTENCY_CONFLICT", "IDEMPOTENCY_CONFLICT", 409),
        ):
            service = self._service(rpc_error=_ApiError(f"P0001: {raised}"))
            with self.assertRaises(ProjectDeletionError) as ctx:
                service.cancel("p1", PROJECT)
            self.assertEqual((ctx.exception.code, ctx.exception.status),
                             (code, status))

    def test_unmigrated_function_is_unavailable_not_a_crash(self):
        service = self._service(rpc_error=_ApiError("no function", "PGRST202"))
        with self.assertRaises(ProjectDeletionError) as ctx:
            service.request("p1", PROJECT, "k")
        self.assertEqual(ctx.exception.status, 503)

    def test_other_rpc_failures_raise(self):
        service = self._service(rpc_error=_ApiError("boom", "XX000"))
        with self.assertRaises(_ApiError):
            service.request("p1", PROJECT, "k")

    def test_open_for_projects_is_keyed_by_project(self):
        service = self._service(rows=[ROW])
        self.assertEqual(service.open_for_projects([PROJECT]), {PROJECT: ROW})
        self.assertEqual(service.open_for_projects([]), {})

    def test_unmigrated_table_reads_as_no_request(self):
        service = self._service(select_error=_ApiError("missing", "42P01"))
        self.assertEqual(service.open_for_projects([PROJECT]), {})
        self.assertEqual(service.queue(), [])

    def test_a_failed_read_is_not_read_as_no_request(self):
        service = self._service(select_error=_ApiError("timeout", "57014"))
        with self.assertRaises(_ApiError):
            service.open_for_project(PROJECT)

    def test_public_view_never_carries_the_owner(self):
        view = public_view(ROW)
        self.assertNotIn("acquisition_principal_id", view)
        self.assertEqual(view["state"], "pending")
        self.assertIsNone(public_view(None))


class FeedTests(unittest.TestCase):
    """The picker feed carries each project's open request, or None."""

    def test_open_request_is_stamped_and_others_are_none(self):
        from services.project_deletion import with_deletion_state

        other = "33333333-3333-4333-8333-333333333333"
        database = SimpleNamespace(client=_client(rows=[ROW]))
        out = with_deletion_state(database, [{"arc_id": PROJECT},
                                             {"arc_id": other}])
        self.assertEqual(out[0]["deletion"]["state"], "pending")
        self.assertIsNone(out[1]["deletion"])

    def test_a_failed_read_leaves_the_feed_usable(self):
        from services.project_deletion import with_deletion_state

        database = SimpleNamespace(client=_client(
            select_error=_ApiError("timeout", "57014")))
        out = with_deletion_state(database, [{"arc_id": PROJECT}])
        self.assertIsNone(out[0]["deletion"])

    def test_an_erased_project_leaves_the_feed(self):
        """P1-B: once erased, a project's row and takes are empty receipts;
        the picker must not list them (tombstoned, or a finished request)."""
        from services.project_deletion import with_deletion_state

        tombstoned = "33333333-3333-4333-8333-333333333333"
        finished = "44444444-4444-4444-8444-444444444444"
        client = MagicMock()

        def table(name):
            chain = MagicMock()
            chain.select.return_value = chain
            chain.in_.return_value = chain
            rows = {
                "projects": [
                    {"id": PROJECT, "tombstoned_at": None},
                    {"id": tombstoned, "tombstoned_at": "2026-09-26T10:00:00Z"},
                ],
                "project_deletion_requests": [
                    {"project_id": finished, "state": "done"},
                ],
            }[name]
            chain.execute.return_value = SimpleNamespace(data=rows)
            return chain

        client.table.side_effect = table
        out = with_deletion_state(SimpleNamespace(client=client), [
            {"arc_id": PROJECT}, {"arc_id": tombstoned}, {"arc_id": finished},
        ])
        self.assertEqual([t["arc_id"] for t in out], [PROJECT])

    def test_a_legacy_arc_id_is_never_sent_as_a_project_id(self):
        client = _client(rows=[])
        ProjectDeletionService(SimpleNamespace(client=client)).erased_projects(
            ["arc-not-a-uuid"])
        client.table.assert_not_called()

    def test_a_database_without_a_client_sees_no_request(self):
        self.assertEqual(
            ProjectDeletionService(SimpleNamespace()).open_for_projects([PROJECT]),
            {})


class CreateTakeLockTests(unittest.TestCase):
    """No new take goes into a project waiting to be deleted."""

    def _resolve(self, *, open_request, duplicate):
        from services import create_take

        repo = MagicMock()
        repo.owner_for_user.return_value = SimpleNamespace(id="p1")
        repo.require_owned_project.return_value = {"id": PROJECT}
        repo.project_take_by_idempotency_key.return_value = duplicate
        with patch.object(create_take, "ProjectRepository", return_value=repo), \
             patch.object(create_take, "ProjectDeletionService") as svc:
            svc.return_value.open_for_project.return_value = open_request
            return create_take.resolve_take_project(
                {"project_id": PROJECT, "upload_idempotency_key": "u1"},
                user_id="user-1", guest_token=None, database=MagicMock(),
            )

    def test_pending_project_refuses_a_new_take(self):
        from services.create_take import CreateTakeError

        with self.assertRaises(CreateTakeError) as ctx:
            self._resolve(open_request=ROW, duplicate=None)
        self.assertEqual(ctx.exception.status, 409)
        self.assertEqual(ctx.exception.code, "PROJECT_DELETION_PENDING")

    def test_a_retried_upload_of_an_existing_take_still_resolves(self):
        context = self._resolve(open_request=ROW, duplicate={"id": "t1"})
        self.assertEqual(context.duplicate_take, {"id": "t1"})

    def test_an_unreadable_lock_never_stops_recording(self):
        from services import create_take

        repo = MagicMock()
        repo.owner_for_user.return_value = SimpleNamespace(id="p1")
        repo.require_owned_project.return_value = {"id": PROJECT}
        repo.project_take_by_idempotency_key.return_value = None
        with patch.object(create_take, "ProjectRepository", return_value=repo), \
             patch.object(create_take, "ProjectDeletionService") as svc:
            svc.return_value.open_for_project.side_effect = RuntimeError("down")
            context = create_take.resolve_take_project(
                {"project_id": PROJECT, "upload_idempotency_key": "u1"},
                user_id="user-1", guest_token=None, database=MagicMock(),
            )
        self.assertEqual(context.project_id, PROJECT)

    def test_no_request_records_as_before(self):
        context = self._resolve(open_request=None, duplicate=None)
        self.assertEqual(context.project_id, PROJECT)


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class RouteTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)
        self.repo = MagicMock()
        self.repo.owner_for_user.return_value = OwnerPrincipal("p1", "u1", False)
        self.service = MagicMock()
        self._p = [
            patch.object(v2_projects, "ProjectRepository", return_value=self.repo),
            patch.object(v2_projects, "ProjectDeletionService",
                         return_value=self.service),
        ]
        for p_ in self._p:
            p_.start()

    def tearDown(self):
        for p_ in self._p:
            p_.stop()

    def _post(self, project=PROJECT, body=None):
        with self.app.test_request_context(json=body if body is not None
                                           else {"idempotency_key": "k1"}):
            request.user_id = "u1"
            resp, status = v2_projects.v2_request_project_deletion.__wrapped__(project)
            return resp.get_json(), status

    def _delete(self, project=PROJECT):
        with self.app.test_request_context():
            request.user_id = "u1"
            resp, status = v2_projects.v2_cancel_project_deletion.__wrapped__(project)
            return resp.get_json(), status

    def test_request_is_created(self):
        self.service.request.return_value = ROW
        body, status = self._post()
        self.assertEqual(status, 201)
        self.assertEqual(body["deletion"]["state"], "pending")
        self.service.request.assert_called_once_with("p1", PROJECT, "k1")

    def test_bad_uuid_and_missing_key_are_400(self):
        self.assertEqual(self._post(project="nope")[1], 400)
        self.assertEqual(self._post(body={})[1], 400)
        self.service.request.assert_not_called()

    def test_not_the_owners_project_is_404(self):
        self.service.request.side_effect = ProjectDeletionError(
            "PROJECT_NOT_FOUND", "PROJECT_NOT_FOUND", 404)
        body, status = self._post()
        self.assertEqual((status, body["code"]), (404, "PROJECT_NOT_FOUND"))

    def test_cancel(self):
        self.service.cancel.return_value = {**ROW, "state": "cancelled",
                                            "cancelled_at": "2026-09-26"}
        body, status = self._delete()
        self.assertEqual((status, body["deletion"]["state"]), (200, "cancelled"))

    def test_cancel_after_confirmation_is_409(self):
        self.service.cancel.side_effect = ProjectDeletionError(
            "PROJECT_DELETION_ALREADY_CONFIRMED",
            "PROJECT_DELETION_ALREADY_CONFIRMED", 409)
        self.assertEqual(self._delete()[1], 409)


if __name__ == "__main__":
    unittest.main()


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class ConfirmRouteTests(unittest.TestCase):
    """The operator's confirm (P1-B, N8)."""

    OPERATOR = "55555555-5555-4555-8555-555555555555"
    REQUEST = "66666666-6666-4666-8666-666666666666"

    def setUp(self):
        self.app = Flask(__name__)
        self.service = MagicMock()
        self._p = patch.object(v2_projects, "ProjectDeletionService",
                               return_value=self.service)
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def _confirm(self, request_id=None):
        with self.app.test_request_context(method="POST"):
            request.user_id = self.OPERATOR
            resp, status = v2_projects.v2_admin_confirm_project_deletion.__wrapped__(
                request_id or self.REQUEST)
            return resp.get_json(), status

    def test_confirm_returns_the_purge_request(self):
        self.service.confirm.return_value = {
            **ROW, "state": "confirmed", "purge_request_id": "purge-1"}
        body, status = self._confirm()
        self.assertEqual(status, 200)
        self.assertEqual(body["deletion"]["state"], "confirmed")
        self.assertEqual(body["purge_request_id"], "purge-1")
        self.service.confirm.assert_called_once_with(self.REQUEST, self.OPERATOR)

    def test_a_cancelled_request_cannot_be_confirmed(self):
        self.service.confirm.side_effect = ProjectDeletionError(
            "PROJECT_DELETION_NOT_PENDING", "PROJECT_DELETION_NOT_PENDING", 409)
        _body, status = self._confirm()
        self.assertEqual(status, 409)

    def test_a_bad_id_is_400(self):
        _body, status = self._confirm("not-a-uuid")
        self.assertEqual(status, 400)
        self.service.confirm.assert_not_called()


class ConfirmServiceTests(unittest.TestCase):

    def test_confirm_maps_its_errors(self):
        for raised, status in (("PROJECT_DELETION_NOT_FOUND", 404),
                               ("PROJECT_DELETION_NOT_PENDING", 409),
                               ("PURGE_PROJECT_NOT_OWNED", 409)):
            service = ProjectDeletionService(SimpleNamespace(
                client=_client(rpc_error=_ApiError(raised, "P0001"))))
            with self.assertRaises(ProjectDeletionError) as ctx:
                service.confirm("r1", "o1")
            self.assertEqual(ctx.exception.status, status)
