from types import SimpleNamespace

import pytest

from services.create_take import (
    CreateTakeError,
    attach_recording_to_project,
    ensure_project_presentation_unchanged,
    reserve_take,
    resolve_take_project,
)
from services.project_ownership import issue_guest_owner


class FakeDatabase:
    def __init__(self):
        self.owner = None
        self.project = None
        self.duplicate = None
        self.bound = None
        self.variant_bound = None
        self.sessions = []

    def get_owner_principal(self, principal_id):
        return self.owner if self.owner and self.owner["id"] == principal_id else None

    def get_owner_principal_for_user(self, user_id):
        return self.owner if self.owner and self.owner.get("user_id") == user_id else None

    def create_user_owner_principal(self, user_id):
        self.owner = {"id": "owner-user", "user_id": user_id}
        return self.owner

    def get_project_for_owner(self, project_id, owner_principal_id):
        if self.project and self.project["id"] == project_id \
                and self.project["owner_principal_id"] == owner_principal_id:
            return self.project
        return None

    def get_project_take_by_upload_key(self, project_id, upload_key):
        return self.duplicate

    def bind_take_to_project(self, take_id, project_id, owner_principal_id):
        self.bound = (take_id, project_id, owner_principal_id)
        return 3

    def bind_recording_variant_to_project(
        self, variant_id, project_id, owner_principal_id, paired_take_id,
    ):
        self.variant_bound = (
            variant_id, project_id, owner_principal_id, paired_take_id,
        )
        return 2

    def get_arc_sessions(self, project_id):
        return self.sessions


def test_authenticated_take_requires_owned_project_and_project_scoped_key():
    database = FakeDatabase()
    database.owner = {"id": "owner-user", "user_id": "user-1"}
    database.project = {"id": "project-1", "owner_principal_id": "owner-user"}
    database.duplicate = {"id": "take-existing"}

    result = resolve_take_project(
        {"project_id": "project-1", "upload_idempotency_key": "upload-1"},
        user_id="user-1",
        guest_token=None,
        database=database,
    )

    assert result.project_id == "project-1"
    assert result.duplicate_take == {"id": "take-existing"}


def test_guest_take_uses_verifiable_owner_credential():
    issued = issue_guest_owner()
    database = FakeDatabase()
    database.owner = {
        "id": issued.principal_id,
        "user_id": None,
        "guest_secret_hash": issued.secret_hash,
    }
    database.project = {
        "id": "project-1",
        "owner_principal_id": issued.principal_id,
    }

    result = resolve_take_project(
        {"project_id": "project-1", "upload_idempotency_key": "upload-1"},
        user_id=None,
        guest_token=issued.token,
        database=database,
    )

    assert result.principal.id == issued.principal_id
    assert result.principal.is_guest is True


@pytest.mark.parametrize(
    "form,code",
    [
        ({"upload_idempotency_key": "upload-1"}, "PROJECT_REQUIRED"),
        ({"project_id": "project-1"}, "IDEMPOTENCY_KEY_REQUIRED"),
    ],
)
def test_take_contract_rejects_missing_identity(form, code):
    with pytest.raises(CreateTakeError) as caught:
        resolve_take_project(
            form,
            user_id="user-1",
            guest_token=None,
            database=FakeDatabase(),
        )
    assert caught.value.code == code


def test_reserve_take_uses_atomic_repository_result():
    database = FakeDatabase()
    context = SimpleNamespace(
        project_id="project-1",
        principal=SimpleNamespace(id="owner-user"),
    )
    assert reserve_take(context, take_id="take-3", database=database) == 3
    assert database.bound == ("take-3", "project-1", "owner-user")


def test_read_variant_is_bound_to_pair_without_reserving_a_take():
    database = FakeDatabase()
    context = SimpleNamespace(
        project_id="project-1",
        principal=SimpleNamespace(id="owner-user"),
    )
    result = attach_recording_to_project(
        context,
        recording_id="read-1",
        recording_kind="read",
        paired_take_id="take-2",
        database=database,
    )
    assert result.take_index == 2
    assert database.bound is None
    assert database.variant_bound == (
        "read-1", "project-1", "owner-user", "take-2",
    )


def test_existing_project_rejects_a_changed_presentation():
    database = FakeDatabase()
    database.sessions = [{
        "intake_context": {
            "slides": [{"title": "Original", "body": "Deck"}],
            "presentation_ref": "original.pdf",
        },
    }]
    context = SimpleNamespace(project_id="project-1")
    with pytest.raises(CreateTakeError) as caught:
        ensure_project_presentation_unchanged(
            context,
            {"slides": [{"title": "Different", "body": "Deck"}],
             "presentation_ref": "different.pdf"},
            database=database,
        )
    assert caught.value.code == "PRESENTATION_LOCKED"


def test_read_variant_never_becomes_the_project_deck_reference():
    database = FakeDatabase()
    database.sessions = [
        {
            "recording_kind": "read",
            "paired_session_id": "take-1",
            "intake_context": {
                "slides": [{"title": "Stale read", "body": "Variant"}],
                "presentation_ref": "stale-read.pdf",
            },
        },
        {
            "recording_kind": "spoken",
            "take_index": 1,
            "intake_context": {
                "slides": [{"title": "Canonical", "body": "Deck"}],
                "presentation_ref": "canonical.pdf",
            },
        },
    ]
    context = SimpleNamespace(project_id="project-1")

    ensure_project_presentation_unchanged(
        context,
        {
            "slides": [{"title": "Canonical", "body": "Deck"}],
            "presentation_ref": "canonical.pdf",
        },
        database=database,
    )


def test_create_take_contract_contains_no_legacy_identity_inputs():
    import inspect
    from routes.v2.lab_recording import v2_lab_create_recording

    source = inspect.getsource(v2_lab_create_recording)
    for retired in (
        "project_intent", "continue_arc_id", "guest_session_id",
        "continue_deck_arc", "continue_topic_arc",
    ):
        assert retired not in source
    assert "resolve_take_project" in source
    assert "GUEST_OWNER_HEADER" in source
