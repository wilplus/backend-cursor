"""An admin's AI call about a speaker runs under the SPEAKER's authority.

Founder 2026-10-05, N48.1 step 6 ("every AI call carries its permission
slip ... fix any I find"). Two admin tools send a speaker's own words to the
provider: the directive suggestions (their recent transcripts and the coach's
comments) and the next-session icebreaker (one session's snippets). They live
under /v2/admin/, outside the core gate, so the call went out with no permit,
no snapshot and no provider record even in enforce mode.

The permit is the speaker's, as for the coach drafts
(``routes.v2.processing_authorization.speaker_provider_route``): their words,
their acceptance. ``call_as_speaker`` resolves the speaker's acquisition
principal, requires current authority, and runs the call inside the protected
scope every ``services.llm.chat_complete`` below it reads its permit from. A
speaker without current authority gets no model call; the admin writes by
hand. Inert while the gate is off.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from services.processing_authorization import (
    ProcessingAuthorizationError,
    ProcessingAuthorizationService,
)

logger = logging.getLogger(__name__)

OPERATION = "admin_draft"


@dataclass(frozen=True)
class Speaker:
    """Whose words a call sends. ``take_id`` is set when one Take is named."""
    owner_principal_id: str
    user_id: str | None
    take_id: str | None


def _owner_of_user(database: Any, user_id: str | None) -> str:
    """The user's owner principal, READ only — never created for them."""
    if not user_id:
        return ""
    row = database.get_owner_principal_for_user(str(user_id)) or {}
    return str(row.get("id") or "")


def speaker_of_session(database: Any, session_id: Any) -> Speaker:
    """The speaker of one Take/session. A historical row without an owner
    principal falls back to its user's principal; a training-corpus import
    never does: its user is the importing coach, not the voice on it, and it
    is never processed under a person (N58)."""
    session = database.v2_get_session_by_id(str(session_id or "")) or {}
    user_id = str(session.get("user_id") or "") or None
    owner = str(session.get("owner_principal_id") or "")
    if not owner and session.get("source") != "training_import":
        owner = _owner_of_user(database, user_id)
    return Speaker(owner, user_id, str(session.get("id") or "") or None)


def speaker_of_user(database: Any, user_id: Any) -> Speaker:
    """The speaker a per-user admin tool is about."""
    uid = str(user_id or "") or None
    return Speaker(_owner_of_user(database, uid), uid, None)


def _unresolved() -> ProcessingAuthorizationError:
    return ProcessingAuthorizationError(
        "PROCESSING_PRINCIPAL_UNRESOLVED",
        "The speaker could not be resolved.",
        403,
    )


def _authorize(
    service: ProcessingAuthorizationService,
    resolve: Callable[[], Speaker],
) -> tuple[Speaker, str]:
    """``(speaker, acquisition principal)`` with current authority, or raise
    ProcessingAuthorizationError. A failed read is an unresolved speaker."""
    try:
        speaker = resolve()
    except Exception as error:
        logger.warning("speaker_authority: speaker read failed",
                       exc_info=True)
        raise _unresolved() from error
    if not speaker.owner_principal_id:
        raise _unresolved()
    principal_id = service.resolve_acquisition_principal(
        speaker.owner_principal_id, user_id=speaker.user_id)
    if not principal_id:
        raise _unresolved()
    service.require_current(principal_id, operation=OPERATION)
    return speaker, principal_id


def call_as_speaker(
    database: Any,
    resolve: Callable[[], Speaker],
    call: Callable[[], Any],
    *,
    surface: str,
) -> tuple[Any, ProcessingAuthorizationError | None]:
    """``(call(), None)``, or ``(None, refusal)`` with the model never called.

    ``resolve`` runs only when the gate is enforced, so the gate-off path
    costs no read. A permit refused inside the call (authority withdrawn in
    between) comes back as the refusal too, never as the call's result.
    """
    service = ProcessingAuthorizationService(database)
    if not service.enforced:
        return call(), None
    try:
        speaker, principal_id = _authorize(service, resolve)
    except ProcessingAuthorizationError as error:
        logger.warning(
            "speaker_authority: refused before the model surface=%s code=%s",
            surface, error.code, exc_info=True)
        return None, error
    from services.authorized_provider import (
        AuthorizedProviderAdapter,
        ProviderCoordinates,
        protected_provider_scope,
    )
    adapter = AuthorizedProviderAdapter(
        database,
        ProviderCoordinates(principal_id, speaker.take_id, None),
        authorization=service,
    )
    refused: ProcessingAuthorizationError | None = None
    with protected_provider_scope(
        adapter,
        idempotency_prefix=(
            f"{surface}:{speaker.take_id or principal_id}:{uuid.uuid4()}"),
    ):
        # Caught INSIDE the scope: the error is a frozen dataclass, and
        # contextlib cannot re-raise it through a generator.
        try:
            return call(), None
        except ProcessingAuthorizationError as error:
            logger.warning(
                "speaker_authority: permit refused mid-call surface=%s "
                "code=%s", surface, error.code, exc_info=True)
            refused = error
    return None, refused
