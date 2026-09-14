from unittest.mock import patch

from flask import Flask, request

from routes.v2.blueprint import v2_bp


class FakeRepository:
    def __init__(self, database):
        self.principal = {"id": "11111111-1111-4111-8111-111111111111",
                          "user_id": None}

    def get_principal(self, principal_id):
        return self.principal

    def create_guest_owner(self, principal_id, secret_hash):
        from services.canonical_product import OwnerPrincipal
        self.principal = {"id": principal_id, "user_id": None,
                          "guest_secret_hash": secret_hash}
        return OwnerPrincipal(principal_id, None, True)

    def owner_for_user(self, user_id):
        from services.canonical_product import OwnerPrincipal
        return OwnerPrincipal("22222222-2222-4222-8222-222222222222",
                              user_id, False)

    def create_project(self, **kwargs):
        from services.canonical_product import Project
        return Project(kwargs["project_id"], kwargs["owner_principal_id"],
                       kwargs["display_name"], kwargs["setup"])

    def require_owned_project(self, project_id, principal_id):
        if project_id != "33333333-3333-4333-8333-333333333333":
            from services.project_repository import ProjectOwnershipError
            raise ProjectOwnershipError("project not found")
        return {"id": project_id, "owner_principal_id": principal_id}

    def require_owned_take(self, project_id, take_id, principal_id):
        if take_id != "44444444-4444-4444-8444-444444444444":
            from services.project_repository import ProjectOwnershipError
            raise ProjectOwnershipError("take not found")
        return {"id": take_id, "arc_id": project_id,
                "owner_principal_id": principal_id}


def _app():
    app = Flask(__name__)
    app.config["TESTING"] = True
    app.register_blueprint(v2_bp, url_prefix="/v2")
    return app


def test_guest_project_is_created_before_take_and_returns_credential():
    with patch("routes.v2.projects.ProjectRepository", FakeRepository):
        response = _app().test_client().post("/v2/projects", json={
            "display_name": "Quarterly update",
            "setup": {"audience": "Board"},
        })
    assert response.status_code == 201
    body = response.get_json()
    assert body["project_id"]
    assert body["owner_principal_id"]
    assert body["guest_owner_token"].startswith(body["owner_principal_id"])


def test_duplicate_display_names_are_not_rejected():
    with patch("routes.v2.projects.ProjectRepository", FakeRepository):
        client = _app().test_client()
        first = client.post("/v2/projects", json={"display_name": "Same"})
        second = client.post("/v2/projects", json={"display_name": "Same"})
    assert first.status_code == second.status_code == 201
    assert first.get_json()["project_id"] != second.get_json()["project_id"]


def test_shaky_voice_and_ownerless_merge_routes_are_not_registered():
    rules = {rule.rule for rule in _app().url_map.iter_rules()}
    assert "/v2/public/shaky-voice/upload" not in rules
    assert "/v2/public/shaky-voice/claim" not in rules
    assert "/v2/public/funnel/afterwards-video" not in rules
    assert "/v2/auth/merge-session" not in rules
    assert (
        "/v2/projects/<project_id>/takes/<take_id>/send-to-coach" in rules
    )


def test_send_to_coach_uses_exact_owned_project_take_coordinates():
    from routes.v2.projects import v2_send_project_take_to_coach

    project_id = "33333333-3333-4333-8333-333333333333"
    take_id = "44444444-4444-4444-8444-444444444444"
    app = _app()
    with app.test_request_context(method="POST"):
        request.user_id = "user-1"
        with patch("routes.v2.projects.ProjectRepository", FakeRepository), \
             patch("routes.v2.projects.send_lab_recording_to_coach",
                   return_value={"ok": True, "already_sent": False}), \
             patch("services.arc_notifications.backfill_ideal_bubbles"):
            response, status = v2_send_project_take_to_coach.__wrapped__(
                project_id, take_id)
    assert status == 200
    assert response.get_json()["review_pending"] is True
    assert response.get_json()["project_id"] == project_id
    assert response.get_json()["take_id"] == take_id


def test_send_to_coach_hides_an_unowned_take():
    from routes.v2.projects import v2_send_project_take_to_coach

    app = _app()
    with app.test_request_context(method="POST"):
        request.user_id = "user-1"
        with patch("routes.v2.projects.ProjectRepository", FakeRepository):
            response, status = v2_send_project_take_to_coach.__wrapped__(
                "33333333-3333-4333-8333-333333333333",
                "55555555-5555-4555-8555-555555555555",
            )
    assert status == 404
    assert response.get_json()["code"] == "TAKE_NOT_FOUND"
