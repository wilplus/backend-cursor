"""Strict project ownership and idempotency boundary for CreateTake."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.canonical_product import OwnerPrincipal
from services.project_ownership import parse_guest_owner_token, verify_guest_owner
from services.project_repository import ProjectOwnershipError, ProjectRepository


class CreateTakeError(ValueError):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class TakeProjectContext:
    project_id: str
    principal: OwnerPrincipal
    project: dict
    idempotency_key: str
    duplicate_take: dict | None


@dataclass(frozen=True)
class TakeCoordinates:
    project_id: str
    take_index: int
    take_count: int


def resolve_owner_principal(
    repository: ProjectRepository,
    *,
    user_id: str | None,
    guest_token: str | None,
) -> OwnerPrincipal:
    if user_id:
        return repository.owner_for_user(str(user_id))
    parsed = parse_guest_owner_token(guest_token)
    if not parsed:
        raise CreateTakeError(
            "INVALID_GUEST_OWNER", "A verified guest owner is required", 401,
        )
    principal_id, _ = parsed
    stored = repository.get_principal(principal_id)
    if not verify_guest_owner(guest_token, stored):
        raise CreateTakeError(
            "INVALID_GUEST_OWNER", "Guest owner token was rejected", 403,
        )
    return OwnerPrincipal(principal_id, None, True)


def session_owned_by_principal(
    session: dict | None,
    *,
    repository: ProjectRepository,
    user_id: str | None,
    guest_token: str | None,
) -> bool:
    """Return whether this request proves the Take's canonical owner.

    A pre-signup user has the same ownership boundary as an account user: the
    Take must carry an ``owner_principal_id`` and the request must present the
    matching signed Guest ID.  A bare session UUID is never authorization.
    """
    if not session:
        return False
    if not session.get("owner_principal_id"):
        # Read/write compatibility for historical account-owned Takes created
        # before owner_principals existed. This never opens a guest capability:
        # anonymous requests still fail closed.
        stored_user = str(session.get("user_id") or "")
        return bool(user_id and stored_user and stored_user == str(user_id))
    try:
        principal = resolve_owner_principal(
            repository,
            user_id=user_id,
            guest_token=guest_token,
        )
    except (CreateTakeError, ProjectOwnershipError):
        return False
    return str(session.get("owner_principal_id")) == principal.id


def resolve_take_project(
    form: Any,
    *,
    user_id: str | None,
    guest_token: str | None,
    database: Any,
) -> TakeProjectContext:
    project_id = str(form.get("project_id") or "").strip()
    if not project_id:
        raise CreateTakeError(
            "PROJECT_REQUIRED", "Create or select a project before recording", 422,
        )
    idempotency_key = str(form.get("upload_idempotency_key") or "").strip()
    if not idempotency_key:
        raise CreateTakeError(
            "IDEMPOTENCY_KEY_REQUIRED", "The captured take needs an upload key", 422,
        )
    repository = ProjectRepository(database)
    try:
        principal = resolve_owner_principal(
            repository, user_id=user_id, guest_token=guest_token,
        )
        project = repository.require_owned_project(project_id, principal.id)
    except ProjectOwnershipError as error:
        raise CreateTakeError("PROJECT_NOT_FOUND", "Project not found", 404) from error
    duplicate = repository.project_take_by_idempotency_key(
        project_id, idempotency_key,
    )
    return TakeProjectContext(
        project_id=project_id,
        principal=principal,
        project=project,
        idempotency_key=idempotency_key,
        duplicate_take=duplicate,
    )


def reserve_take(
    context: TakeProjectContext,
    *,
    take_id: str,
    database: Any,
) -> int:
    repository = ProjectRepository(database)
    take_index = repository.bind_take(
        take_id,
        context.project_id,
        context.principal.id,
    )
    if take_index is None:
        raise CreateTakeError(
            "TAKE_CREATE_FAILED", "Could not attach the take to its project", 500,
        )
    return int(take_index)


def ensure_project_presentation_unchanged(
    context: TakeProjectContext,
    session_context: dict,
    *,
    database: Any,
) -> None:
    """Protect the slide structure after the first completed project take."""
    sessions = ProjectRepository(database).project_takes(context.project_id)
    spoken_sessions = [
        session
        for session in sessions
        if isinstance(session, dict)
        and session.get("recording_kind") != "read"
        and not session.get("paired_session_id")
    ]
    if not spoken_sessions:
        return
    from services.presentation_change_intent import deck_matches_recorded_project

    if deck_matches_recorded_project(spoken_sessions, session_context):
        return
    raise CreateTakeError(
        "PRESENTATION_LOCKED",
        "Your current roadmap is connected to these slides. "
        "Create a new project for the updated deck.",
        409,
    )


def attach_recording_to_project(
    context: TakeProjectContext,
    *,
    recording_id: str,
    recording_kind: str,
    paired_take_id: str | None,
    database: Any,
) -> TakeCoordinates:
    """Atomically bind a spoken Take or its non-counting read variant."""
    if recording_kind == "read":
        if not paired_take_id:
            raise CreateTakeError(
                "PAIRED_TAKE_REQUIRED",
                "A read recording must belong to an existing take",
                422,
            )
        take_index = ProjectRepository(database).bind_variant(
            recording_id,
            context.project_id,
            context.principal.id,
            paired_take_id,
        )
    else:
        take_index = reserve_take(
            context, take_id=recording_id, database=database,
        )
    if take_index is None:
        raise CreateTakeError(
            "TAKE_CREATE_FAILED", "Could not attach the take to its project", 500,
        )
    index = int(take_index)
    return TakeCoordinates(context.project_id, index, index)
