"""Owner edits to a Take's review and receipts from its existing walk."""
from typing import Any


def is_ready(session: dict) -> bool:
    state = session.get("analysis_state")
    if state is not None:
        return state == "ready"
    return bool(session.get("results_published_at")) or session.get("status") == "completed"


def _draft(document: Any) -> dict | None:
    if not isinstance(document, dict) or not document:
        return None
    if set(document) - {"feedback", "ideal_sections"}:
        return None
    feedback = document.get("feedback")
    if "feedback" in document and (not isinstance(feedback, str) or len(feedback) > 12000):
        return None
    ideal = document.get("ideal_sections")
    if "ideal_sections" in document:
        if not isinstance(ideal, list) or not 1 <= len(ideal) <= 180:
            return None
        if any(not isinstance(part, str) or len(part) > 12000 for part in ideal):
            return None
        if sum(map(len, ideal)) > 80000:
            return None
    return document


def read(database, user_id: str, take_id: str) -> dict:
    result = (database.client.table("take_review_edits")
              .select("revision,document").eq("user_id", user_id)
              .eq("take_session_id", take_id).limit(1).execute())
    return result.data[0] if result.data else {"revision": 0, "document": {}}


def save(database, user_id: str, take_id: str, body: Any) -> tuple[dict, int]:
    if not isinstance(body, dict):
        return {"code": "INVALID_INPUT"}, 400
    revision = body.get("revision")
    patch = _draft(body.get("document"))
    if patch is None:
        return {"code": "INVALID_INPUT"}, 400
    return save_patch(database, user_id, take_id, revision, patch)


def save_patch(database, user_id: str, take_id: str, revision: Any, patch: dict) -> tuple[dict, int]:
    """Merge an already validated patch through the shared revision guard."""
    if type(revision) is not int or not 0 <= revision < 2147483647:
        return {"code": "INVALID_INPUT"}, 400
    current = read(database, user_id, take_id)
    document = {**current["document"], **patch}
    if current["document"] == document:
        return current, 200
    if current["revision"] != revision:
        return {"code": "REVIEW_CHANGED", **current}, 409
    record = {"revision": revision + 1, "document": document}
    table = database.client.table("take_review_edits")
    if revision == 0:
        result = table.upsert(
            {"user_id": user_id, "take_session_id": take_id, **record},
            on_conflict="take_session_id", ignore_duplicates=True,
        ).execute()
    else:
        result = (table.update(record).eq("user_id", user_id)
                  .eq("take_session_id", take_id).eq("revision", revision).execute())
    if not result.data:
        latest = read(database, user_id, take_id)
        if latest["document"] == document:
            return latest, 200
        return {"code": "REVIEW_CHANGED", **latest}, 409
    return record, 200


def practice_runs(database, user_id: str, arc_id: str, take_ids: set[str]) -> dict[str, list[dict]]:
    """List the accepted practice receipts, independent of chat pagination."""
    runs: dict[str, list[dict]] = {}
    if not take_ids:
        return runs
    cursor = None
    while True:
        query = (database.client.table("lounge_messages").select(
            "id, client_created_at, take:metadata->>take_session_id, step:metadata->>step",
        ).eq("user_id", user_id).eq("kind", "walk_step").eq("role", "user")
            .eq("chat_erased", False)
            .eq("metadata->>arc_id", arc_id)
            .or_("metadata->>step.like.try:*,metadata->>step.eq.tempo:try"))
        if cursor is not None:
            query = query.gt("id", cursor)
        rows = query.order("id").limit(500).execute().data or []
        for row in rows:
            take = row.get("take")
            if take in take_ids:
                runs.setdefault(take, []).append({
                    "id": row["id"], "at": row["client_created_at"],
                    "kind": "tempo" if row["step"] == "tempo:try" else "voice",
                })
        if len(rows) < 500:
            return runs
        cursor = rows[-1]["id"]


def walk_steps(database, user_id: str, arc_id: str, take_id: str, *,
               exchange: bool = False, shared_at: str | None = None) -> list[dict]:
    """A Take's saved walk, or its complete exchange, oldest first."""
    rows: list[dict] = []
    cursor = None
    while True:
        query = (database.client.table("lounge_messages")
                 .select("id, client_id, role, kind, body, metadata, client_created_at")
                 .eq("user_id", user_id).eq("chat_erased", False)
                 .eq("metadata->>arc_id", arc_id).eq("metadata->>take_session_id", take_id))
        if not exchange:
            query = query.eq("kind", "walk_step")
        if shared_at is not None:
            query = query.lte("created_at", shared_at)
        if cursor is not None:
            query = query.gt("id", cursor)
        batch = query.order("id").limit(500).execute().data or []
        rows.extend(batch)
        if len(batch) < 500:
            return sorted(rows, key=lambda row: row["client_created_at"])
        cursor = batch[-1]["id"]
