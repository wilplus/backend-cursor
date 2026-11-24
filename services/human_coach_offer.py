"""The handoff contract for an explicit human-coach request (N688)."""
import re
from typing import Any

from services import human_coach_booking as calendar, human_coach_reviews as reviews
from services.booking import BookingError
from services.content_language import resolve_content_language
from services.processing_authorization import ProcessingAuthorizationError
from services.take_review_history import is_ready

_EXPLICIT = re.compile(
    r"\b(?:"
    r"(?:book|schedule|set up)\s+(?:me\s+)?(?:(?:a|the|an)\s+)?(?:call|meeting|session)\b"
    r"|(?:talk|speak|chat|meet|connect)\b.{0,36}\b(?:artur|(?:a\s+)?(?:real\s+)?human|real person)\b"
    r"|(?:human|real)\s+(?:speaking\s+)?coach\b"
    r"|(?:send|share)\b.{0,50}\b(?:artur|human coach)\b"
    r"|(?:porozmawia[ćc]|pogada[ćc]|spotka[ćc]|rozmow[ęeay])\b.{0,32}\b(?:artur(?:em|a)?|cz[łl]owiekiem|trenerem)\b"
    r"|um[oó]w(?:i[ćc]|isz)?\b.{0,32}\b(?:rozmow[ęeay]|spotkanie|arturem)\b"
    r"|(?:wy[śs]lij|wys[łl]a[ćc]|prze[śs]lij)\b.{0,45}\bartur(?:owi|a)\b"
    r")", re.IGNORECASE,
)
_NEGATED = re.compile(r"\b(?:don't|do not|never|no need to|nie chc[ęe]|nie wysy[łl]aj)\b", re.IGNORECASE)


def explicit_request(question: str) -> bool:
    return bool(_EXPLICIT.search(question)) and not _NEGATED.search(question)


def _recent_source(database: Any, user: str, project: str | None) -> tuple[str | None, str | None]:
    if project:
        rows = database.takes.get_arc_sessions(project) or []
    else:
        rows = (database.client.table("v2_sessions")
                .select("id,project_id,user_id,recording_kind,paired_session_id,analysis_state,status")
                .eq("user_id", user).eq("analysis_state", "ready").not_.is_("project_id", "null")
                .order("created_at", desc=True).limit(12).execute().data or [])
    for row in sorted(rows, key=lambda item: str(item.get("created_at") or ""), reverse=True):
        if (str(row.get("user_id")) == user and is_ready(row) and row.get("recording_kind") != "read"
                and not row.get("paired_session_id")):
            return project or reviews.uid(row.get("project_id")), str(row["id"])
    return project, None


def offer(database: Any, user: str, question: str, *, project: str | None = None,
          take: str | None = None) -> dict | None:
    """Resolve a reply's optional actions. The chat never acts on the offer."""
    if not reviews.email_available():
        return None
    if project:
        try:
            reviews.require_project(database, user, project)
        except reviews.HandoffError:
            return None
    if not take:
        project, take = _recent_source(database, user, project)
    can_send = False
    recipient = reviews.reviewer(database) if project and take else None
    if project and take and recipient and recipient != user:
        try:
            reviews.preview(database, user, project, take)
            can_send = True
        except (reviews.HandoffError, ProcessingAuthorizationError):
            pass
    try:
        calendar.settings()
        can_book = True
    except BookingError:
        can_book = False
    if not (can_book or can_send):
        return None
    polish = resolve_content_language(typed_message=question) == "pl"
    answer = ("Mogę pomóc Ci przyjrzeć się Twojemu głosowi i wystąpieniu. Jeśli chcesz omówić je z człowiekiem, mogę połączyć Cię z Arturem."
              if polish else "I can help you review your voice and presentation. If you’d like to talk it through with a person, I can connect you with Artur.")
    return {
        "answer": answer,
        "row_metadata": {
            "human_coach_handoff": {
                "project_id": project,
                "take_session_id": take if can_send else None,
                "book": can_book,
                "send": can_send,
            },
        },
    }
