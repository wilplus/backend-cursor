"""N688: a speaker's private, per-Take request to Artur."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from html import escape
from typing import Any
from uuid import UUID

from config import Config
from services import take_review_history
from services.processing_authorization import ProcessingAuthorizationService
from services.project_repository import ProjectOwnershipError, ProjectRepository

TABLE = "human_coach_reviews"
STATUS_FIELDS = "id,take_session_id,requested_at,email_sent_at,feedback,feedback_at"
config = Config()


class HandoffError(Exception):
    def __init__(self, code: str, message: str, status: int):
        super().__init__(message)
        self.code = code
        self.status = status


def uid(value: Any) -> str | None:
    try:
        return str(UUID(value)) if isinstance(value, str) else None
    except ValueError:
        return None


def missing() -> HandoffError:
    return HandoffError("NOT_FOUND", "Not found.", 404)


def email_available() -> bool:
    return bool(config.SEND_EMAILS and config.RESEND_API_KEY and config.RESEND_FROM_EMAIL
                and config.ADMIN_EMAIL and (config.is_production or not config.EMAIL_REDIRECT_TO))


def reviewer(database) -> str | None:
    """One account owns the address that receives the private email."""
    from services.take_sends import _founder

    if not email_available() or not (recipient := _founder(database)):
        return None
    account = database.client.auth.admin.get_user_by_id(recipient).user
    email = str(getattr(account, "email", "") or "").strip().casefold()
    if email == Config.ADMIN_EMAIL.strip().casefold() and getattr(account, "email_confirmed_at", None):
        return recipient
    return None


def require_project(database, user: str, project: str) -> tuple[str, dict]:
    if not uid(project):
        raise missing()
    owner = database.get_owner_principal_for_user(user)
    if not owner:
        raise missing()
    principal = str(owner["id"])
    try:
        row = ProjectRepository(database).require_owned_project(project, principal)
    except ProjectOwnershipError as error:
        raise missing() from error
    return principal, row


def _source(database, user: str, project: str, take: str) -> tuple[dict, dict, dict]:
    principal, project_row = require_project(database, user, project)
    if not uid(take):
        raise missing()
    try:
        source = ProjectRepository(database).require_owned_take(project, take, principal)
    except ProjectOwnershipError as error:
        raise missing() from error
    if (str(source.get("user_id")) != user or source.get("recording_kind") == "read"
            or source.get("paired_session_id") or not take_review_history.is_ready(source)):
        raise missing()
    ProcessingAuthorizationService(database).require_current(principal, operation="recording")
    recording = database.get_recording(str(source.get("recording_id") or ""), user_id=user) \
        if source.get("recording_id") else None
    if not recording or str(recording.get("session_v2_id") or "") != take:
        rows = (database.client.table("recordings")
                .select("id,storage_path,audio_url,recording_origin,duration")
                .eq("session_v2_id", take).eq("user_id", user).limit(1).execute().data or [])
        recording = rows[0] if rows else None
    if not recording or not (recording.get("storage_path") or recording.get("audio_url")):
        raise missing()
    return project_row, source, recording


def _sent_for_take(database, user: str, project: str, take: str) -> dict | None:
    rows = (database.client.table(TABLE).select(STATUS_FIELDS + ",recipient_user_id,note")
            .eq("owner_user_id", user).eq("project_id", project)
            .eq("take_session_id", take).limit(1).execute().data or [])
    return rows[0] if rows else None


def _status(row: dict) -> dict:
    return {key: row.get(key) for key in STATUS_FIELDS.split(",")}


def _revision(database, user: str, project: str, take: dict) -> dict:
    from services.ideal_text_read import resolve_ideal_text_source, resolve_live_text
    from services.paragraph_history import document_history

    core = database.get_ideal_text_document_core_v2(project, user) or {}
    snapshot = (core.get("snapshot") or {}).get("payload") or {}
    if str(snapshot.get("latest_take_session_id") or "") == str(take["id"]):
        revision = {
            "text": snapshot.get("text"),
            "slides": [piece.get("slide_index") for piece in snapshot.get("pieces") or []],
            "presentation_ref": snapshot.get("presentation_ref"),
            "slide_titles": snapshot.get("slide_titles"),
        }
        overlay = core.get("dynamic_overlay") or {}
        edit = overlay.get("owner_edit") or {}
        if edit.get("version") == snapshot.get("version") and edit.get("text"):
            revision["text"] = edit["text"]
        return revision
    index = take.get("take_index")
    if index is None:
        return {}
    versions = database.list_ideal_text_versions(project)
    revisions = document_history(versions, [take])
    for revision in revisions:
        if revision["take_index"] == index:
            return revision
    head = resolve_ideal_text_source(database.ideal_text.get_coach_arc_ideal_text(project))
    return {"text": resolve_live_text(project, user, head, database=database).text} if head.version == index else {}


def _document(database, user: str, project: str, take: dict) -> dict:
    """Pin the matching Ideal Text and its recorded slide mapping at send."""
    from services.ideal_text_block import strip_moment_markers

    revision = _revision(database, user, project, take)
    review = take_review_history.read(database, user, str(take["id"]))["document"]
    paragraphs = review.get("ideal_sections") or str(revision.get("text") or "").split("\n\n")
    if not any(paragraph.strip() for paragraph in paragraphs):
        raise HandoffError("IDEAL_TEXT_PENDING", "Your Ideal Text is still getting ready.", 409)
    slides = revision.get("slides") or []
    if len(slides) != len(paragraphs):
        slides = [None] * len(paragraphs)
    return {
        "sections": [{"text": strip_moment_markers(text), "slide_index": slide}
                     for text, slide in zip(paragraphs, slides) if text.strip()],
        "slide_titles": revision.get("slide_titles") or [],
        "presentation_ref": revision.get("presentation_ref") or None,
    }


def preview(database, user: str, project: str, take: str) -> dict:
    project_row, source, recording = _source(database, user, project, take)
    existing = _sent_for_take(database, user, project, take)
    return {
        "project_title": project_row.get("display_name") or "",
        "take_index": source.get("take_index"),
        "duration_seconds": recording.get("duration"),
        "sent": bool(existing and existing.get("email_sent_at")),
    }


def list_reviews(database, user: str, project: str) -> dict:
    require_project(database, user, project)
    rows = (database.client.table(TABLE).select(STATUS_FIELDS)
            .eq("owner_user_id", user).eq("project_id", project)
            .not_.is_("email_sent_at", "null")
            .order("requested_at", desc=True).limit(100).execute().data or [])
    return {"reviews": rows}


def _delivery_error() -> HandoffError:
    return HandoffError("DELIVERY_UNAVAILABLE", "We couldn’t send this Take. Try again.", 503)


def _email(database, user: str, source: dict, row: dict) -> str:
    from services.email_service import send_email_resend
    from services.lab_send import _authorize_coach_delivery

    take = str(source["id"])
    adapter, permit_id = _authorize_coach_delivery(
        database, source, take, user, provider="resend", correlation=str(row["id"]),
        manifest={"content": ["private_review_link", "speaker_note"], "purpose": "coach_review"},
    )
    url = (Config.FRONTEND_URL or "https://willpowerlab.com").rstrip("/") + f"/coach/private-review/{row['id']}"
    note = row.get("note") or ""
    text = "A speaker sent you a Take for private review."
    html = f"<p>{text}</p>"
    if note:
        text += "\n\n" + note
        html += f'<p style="white-space:pre-wrap">{escape(note)}</p>'
    try:
        result = send_email_resend(
            to=Config.ADMIN_EMAIL, subject="A Take for your private review",
            text=f"{text}\n\nOpen Take: {url}",
            html=html + f'<p><a href="{escape(url, quote=True)}">Open Take</a></p>',
            idempotency_key=f"private-take-review:{row['id']}",
        )
        provider_id = (result.get("resend_response") or {}).get("id")
        if not result.get("sent") or not isinstance(provider_id, str):
            raise _delivery_error()
    except Exception:
        adapter.authorization.record_provider_event(permit_id, "failed", error_code="EMAIL_NOT_SENT")
        raise
    adapter.authorization.record_provider_event(
        permit_id, "completed", provider_operation_ref=provider_id,
        metadata={"result_kind": "private_human_review_email"})
    return provider_id


def send(database, user: str, project: str, take: str, note: Any) -> dict:
    if not isinstance(note, str) or len(note) > 300:
        raise HandoffError("INVALID_NOTE", "Keep your message to 300 characters.", 400)
    _, source, _ = _source(database, user, project, take)
    if not (recipient := reviewer(database)) or recipient == user:
        raise _delivery_error()
    now = datetime.now(timezone.utc)
    row = _sent_for_take(database, user, project, take)
    if row is None:
        packet = _document(database, user, project, source)
        created = (database.client.table(TABLE).upsert({
            "owner_user_id": user, "recipient_user_id": recipient,
            "project_id": project, "take_session_id": take, "note": note.strip(),
            "document": packet, "requested_at": now.isoformat(),
        }, on_conflict="take_session_id", ignore_duplicates=True).execute().data or [])
        row = created[0] if created else _sent_for_take(database, user, project, take)
    if not row or str(row["recipient_user_id"]) != recipient:
        raise _delivery_error()
    if row.get("email_sent_at"):
        return _status(row)

    lease = now.isoformat()
    stale = (now - timedelta(minutes=5)).isoformat()
    claimed = (database.client.table(TABLE).update({"email_claimed_at": lease})
               .eq("id", row["id"]).is_("email_sent_at", "null")
               .or_(f"email_claimed_at.is.null,email_claimed_at.lt.{stale}").execute().data or [])
    if not claimed:
        raise HandoffError("DELIVERY_IN_PROGRESS", "This Take is being sent. Try again shortly.", 409)
    try:
        provider_id = _email(database, user, source, row)
    except Exception:
        (database.client.table(TABLE).update({"email_claimed_at": None})
         .eq("id", row["id"]).eq("email_claimed_at", lease).execute())
        raise
    sent_at = datetime.now(timezone.utc).isoformat()
    result = (database.client.table(TABLE).update({
        "email_sent_at": sent_at, "email_claimed_at": None, "provider_email_id": provider_id,
    })
              .eq("id", row["id"]).eq("email_claimed_at", lease).execute().data or [])
    if not result:
        raise _delivery_error()
    return _status(result[0])


def _assigned(database, reader: str, review: str) -> dict:
    if not uid(review):
        raise missing()
    rows = (database.client.table(TABLE).select("*").eq("id", review)
            .eq("recipient_user_id", reader).limit(1).execute().data or [])
    if not rows or not (rows[0].get("email_sent_at") or rows[0].get("email_claimed_at")):
        raise missing()
    return rows[0]


def _walk_rows(database, user: str, project: str, take: str, at: str) -> list[dict]:
    from routes.v2.common import _resolve_snippet_audio_url
    from services.audio_ref_resolver import resolve_playable_ref
    from services.lounge_clips import refresh_practice_clips, refresh_walk_clips
    from services.lounge_messages import host_rooms

    rooms = host_rooms(database, user)
    rows = take_review_history.walk_steps(database, user, project, take, exchange=True, shared_at=at)
    playback: list[dict] = []
    shared = []
    practices: dict[str, bool] = {}
    for row in rows:
        meta = row.get("metadata") or {}
        if (rooms.chat_of(row) is not None or meta.get("take_exchange") is False
                or row["role"] not in ("user", "bot") or row["kind"] not in ("text", "walk_step")
                or (row["kind"] == "walk_step" and meta.get("step") == "end")):
            continue
        clip = _clip_reference(meta, take)
        if clip and (pid := clip.get("practice_id")):
            if pid not in practices:
                practice = database.get_confident_voice_practice(pid, user) or {}
                practices[pid] = str(practice.get("take_session_id")) == take
            if not practices[pid]:
                clip = None
        if clip:
            playback.append({"kind": "walk_step", "metadata": {"clip": clip, "take_session_id": take}})
        body = _walk_text(row, meta)
        if body or clip:
            shared.append({"id": row["id"], "role": row["role"], "body": body, "clip": clip})
    refresh_walk_clips(playback, user, database, _resolve_snippet_audio_url)
    refresh_practice_clips(playback, user, database, resolve_playable_ref)
    return shared


def _walk_text(row: dict, meta: dict) -> str:
    body = str(row.get("body") or "").strip()
    if row["role"] != "bot":
        return body
    artifact = meta.get("chat_artifact")
    artifact = artifact if isinstance(artifact, dict) and artifact.get("version") == 1 else {}
    parts = [body]
    for value in (artifact.get("moment"), artifact.get("intervention"), artifact.get("output"),
                  meta.get("after_ideal_text")):
        if isinstance(value, str) and (words := value.strip()) and words not in parts:
            parts.append(words)
    return "\n\n".join(filter(None, parts))


def _clip_reference(meta: dict, take: str) -> dict | None:
    clip = meta.get("clip")
    if isinstance(clip, dict):
        snippet = uid(clip.get("snippet_id"))
        practice, attempt = uid(clip.get("practice_id")), uid(clip.get("attempt_id"))
        if snippet:
            return {"snippet_id": snippet}
        if practice and attempt:
            return {"practice_id": practice, "attempt_id": attempt}
    moment = meta.get("coach_moment")
    if isinstance(moment, dict) and moment.get("take_session_id") == take and uid(moment.get("snippet_id")):
        return {"snippet_id": moment["snippet_id"]}
    return None


def _mark_nonblind(database, coach: str, user: str, take: str, walk: list[dict]) -> None:
    from services.snippet_tables import SNIPPETS_TABLE

    # Opening the full recording exposes its snippets as well as all of
    # the saved attempts that can play in this packet.
    snippet_rows: list[dict] = []
    cursor = None
    while True:
        query = database.client.table(SNIPPETS_TABLE).select("id").eq("user_id", user).eq("session_id", take)
        if cursor is not None:
            query = query.gt("id", cursor)
        batch = query.order("id").limit(500).execute().data or []
        snippet_rows.extend(batch)
        if len(batch) < 500:
            break
        cursor = batch[-1]["id"]
    clips = {str(row["id"]): "snippet" for row in snippet_rows}
    for row in walk:
        clip = row.get("clip") or {}
        if clip.get("src") and clip.get("attempt_id"):
            clips[clip["attempt_id"]] = "practice_attempt"
    if clips:
        (database.client.table("coach_clip_exposures").upsert([
            {"coach_id": coach, "clip_id": clip, "clip_kind": kind, "via": "request"}
            for clip, kind in clips.items()
        ], on_conflict="coach_id,clip_id", ignore_duplicates=True).execute())


def inbox(database, reader: str, review: str) -> dict:
    from services.coach_video_storage import refreshed_media_url
    from services.snippet_audio_url import recording_playback_url

    row = _assigned(database, reader, review)
    user, project, take = (str(row[key]) for key in ("owner_user_id", "project_id", "take_session_id"))
    project_row, source, recording = _source(database, user, project, take)
    document = row["document"]
    walk = _walk_rows(database, user, project, take, row["requested_at"])
    _mark_nonblind(database, reader, user, take, walk)
    return {
        "project_title": project_row.get("display_name") or "",
        "take_index": source.get("take_index"),
        "note": row["note"],
        "audio_url": recording_playback_url(recording, database, Config),
        "ideal_text": {**document, "presentation_ref": refreshed_media_url(document.get("presentation_ref"))},
        "walk": walk,
        "feedback": row.get("feedback"),
    }


def publish(database, reader: str, review: str, feedback: Any) -> dict:
    if not isinstance(feedback, str) or not (text := feedback.strip()) or len(text) > 6000:
        raise HandoffError("INVALID_FEEDBACK", "Enter feedback up to 6000 characters.", 400)
    row = _assigned(database, reader, review)
    _source(database, str(row["owner_user_id"]), str(row["project_id"]), str(row["take_session_id"]))
    if row.get("feedback"):
        if row["feedback"] == text:
            return _status(row)
        raise HandoffError("ALREADY_REPLIED", "Feedback was already sent.", 409)
    at = datetime.now(timezone.utc).isoformat()
    saved = (database.client.table(TABLE).update({"feedback": text, "feedback_at": at})
             .eq("id", review).eq("recipient_user_id", reader)
             .is_("feedback_at", "null").execute().data or [])
    if not saved:
        current = _assigned(database, reader, review)
        if current.get("feedback") != text:
            raise HandoffError("ALREADY_REPLIED", "Feedback was already sent.", 409)
        return _status(current)
    return _status(saved[0])
