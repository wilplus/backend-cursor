"""
STORY    As a speaker, I want Delete on a project to be a request I can cancel
         within 7 days, with no new Takes added meanwhile, so that I can
         change my mind and nothing new lands in a project about to go.
OUTCOME
  O1  Asking to delete my project creates a pending request; someone
      else's project answers "not found".
  O2  A project waiting to be deleted refuses a new Take, but if the lock
      cannot be read, recording still goes ahead.
  O3  Cancelling after the operator confirmed is refused.
  O4  The operator's confirm returns the id of the erasure it starts.
  O5  What the speaker is shown about the request never names the owner.
PROVES   O1 -> RouteTests::test_request_is_created,
               RouteTests::test_not_the_owners_project_is_404
         O2 -> CreateTakeLockTests::test_pending_project_refuses_a_new_take,
               CreateTakeLockTests::test_an_unreadable_lock_never_stops_recording
         O3 -> RouteTests::test_cancel_after_confirmation_is_409
         O4 -> ConfirmRouteTests::test_confirm_returns_the_purge_request
         O5 -> ServiceTests::test_public_view_never_carries_the_owner
WHY      Founder 2026-09-25, decisions log N8.
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


    def test_public_view_never_carries_the_owner(self):
        view = public_view(ROW)
        self.assertNotIn("acquisition_principal_id", view)
        self.assertEqual(view["state"], "pending")
        self.assertIsNone(public_view(None))


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


    def test_not_the_owners_project_is_404(self):
        self.service.request.side_effect = ProjectDeletionError(
            "PROJECT_NOT_FOUND", "PROJECT_NOT_FOUND", 404)
        body, status = self._post()
        self.assertEqual((status, body["code"]), (404, "PROJECT_NOT_FOUND"))


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
