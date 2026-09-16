"""The Confident Voice practice attempt's one door to the provider.

WHY THIS MODULE EXISTS (founder authorization 2026-09-16, to lift the Phase-2
purpose gate on the practice routes).

Until now the practice attempt route called ``transcribe_snippet_bytes``
directly, which reaches ``openai_service.client`` and therefore OpenAI, with no
permit, no recorded provider event, and no regard for
``PLF1_PROCESSING_AUTHORIZATION_MODE``. The ``operational_purpose_disabled``
gate was the only thing standing between a speaker's practice recording and
that call. Removing the gate without this module would have left a direct
provider client on a live route — precisely what the standing constraint
forbids, and invisible while it worked.

A practice attempt is NEW audio of the speaker's voice, captured for a
different reason than the Take it came from. It gets the same treatment a Take
gets: resolve who owns it, take a permit, record the outcome.

COORDINATES. ``take_id`` is the Take the practice hangs off — true, and what
the permit needs to scope the subject. ``recording_id`` is deliberately None: a
practice attempt has no row in ``recordings``, and naming the ORIGINAL
recording here would assert that the original audio was sent to the provider,
which is false. An untrue permit is worse than an unscoped one.

MODE OFF. Every call below no-ops when authorization is not enforced
(``issue_provider_permit`` returns None; ``record_provider_event`` returns
early), so this is one code path rather than an enforced branch and an
unenforced one. The unenforced branch is the one that would rot.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


def transcribe_practice_attempt(
    database: Any, practice: Any, audio_bytes: bytes, *,
    hint_filename: str = "practice.webm",
    language_hint: Optional[str] = None,
) -> Optional[dict]:
    """Transcribe one practice attempt through the authorization boundary.

    Returns the snippet transcription contract unchanged —
    ``{transcript, language, words, transcribed_duration_ms}`` or None — so the
    caller sees exactly what the unpermitted call used to return, including
    each word's recognition ``confidence``.
    """
    from services.authorized_provider import (
        AuthorizedProviderAdapter, ProviderCoordinates,
    )
    from services.processing_authorization import ProcessingAuthorizationService

    row: dict = practice if isinstance(practice, dict) else {}
    take_id = str(row.get("take_session_id") or "") or None

    authorization = ProcessingAuthorizationService(database)
    principal_id = ""
    if authorization.enforced:
        session = (database.v2_get_session_by_id(take_id) or {}) if take_id else {}
        principal_id = authorization.resolve_acquisition_principal(
            str(session.get("owner_principal_id") or ""),
            user_id=str(row.get("owner_user_id") or "") or None,
        )

    adapter = AuthorizedProviderAdapter(
        database,
        ProviderCoordinates(principal_id, take_id, None),
        authorization=authorization,
    )
    return adapter.transcribe_snippet(
        audio_bytes, hint_filename, language_hint=language_hint,
    )
