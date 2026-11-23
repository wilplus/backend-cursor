"""Named conversations under a person's built chat, and group lifecycle."""
from typing import Any
from uuid import UUID, uuid4

DEFAULT = {"coach": "active", "builder": "active", "subchats": [], "published_chat": None, "main_chat_id": "main"}


def read(database, user_id: str) -> tuple[int, dict]:
    result = (database.client.table("owner_chat_structures").select("revision,document")
              .eq("user_id", user_id).limit(1).execute())
    if not result.data:
        return 0, {**DEFAULT, "subchats": []}
    row = result.data[0]
    return row["revision"], {**DEFAULT, **row["document"]}


def _words(value: Any, limit: int) -> str:
    return value.strip() if isinstance(value, str) and 0 < len(value.strip()) <= limit else ""


def _published_chat(value: Any) -> dict | None:
    if not isinstance(value, dict):
        return None
    name = _words(value.get("name"), 100)
    spec = _words(value.get("spec"), 500)
    send = value.get("send")
    who = value.get("who")
    if not name or not spec or not isinstance(send, list) or not 1 <= len(send) <= 4:
        return None
    if any(kind not in ("rec", "text", "photo", "file") for kind in send) or who not in ("shadow", "you", "assistant"):
        return None
    return {
        "name": name, "spec": spec, "send": list(dict.fromkeys(send)), "who": who,
        "hello": _words(value.get("hello"), 2000), "line": _words(value.get("line"), 500),
        "taps": _short_lines(value.get("taps")),
        "questions": [{"q": q} for q in _short_lines(value.get("questions"))],
    }


def _short_lines(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [line for item in value[:3] if (line := _words(item, 500))]


def change(layout: dict, body: dict) -> tuple[dict, list[str]] | None:
    action = body.get("action")
    section = body.get("section")
    rows = [dict(item) for item in layout["subchats"]]
    layout = {**layout, "subchats": rows}
    removed: list[str] = []
    if action == "publish":
        published = _published_chat(body.get("chat"))
        if not published or layout["builder"] != "active":
            return None
        layout["published_chat"] = published
    elif action == "add":
        title = _words(body.get("title"), 100)
        question = _words(body.get("question"), 500)
        if not title or not question or len(rows) >= 30 or layout["builder"] != "active":
            return None
        if any(item["title"] == title and item["question"] == question for item in rows):
            return layout, removed
        rows.append({"id": str(uuid4()), "title": title, "question": question, "archived": False})
    elif section in ("coach", "builder"):
        return _change_parent(layout, section, action)
    else:
        return _change_child(layout, section, action)
    return layout, removed


def _change_parent(layout: dict, section: str, action: str) -> tuple[dict, list[str]] | None:
    state = {"archive": "archived", "restore": "active", "delete": "deleted"}.get(action)
    if not state or (section == "coach" and action == "delete"):
        return None
    if layout[section] == "deleted" and action != "restore":
        return None
    layout[section] = state
    if section == "builder" and action == "delete":
        removed = [layout["main_chat_id"], *(row["id"] for row in layout["subchats"])]
        layout.update(subchats=[], published_chat=None, main_chat_id=str(uuid4()))
        return layout, removed
    return layout, []


def _change_child(layout: dict, section: str, action: str) -> tuple[dict, list[str]] | None:
    rows = layout["subchats"]
    child = next((item for item in rows if item["id"] == section), None)
    if not child or layout["builder"] != "active":
        return None
    if action in ("archive", "restore"):
        child["archived"] = action == "archive"
        return layout, []
    if action == "delete":
        rows.remove(child)
        return layout, [child["id"]]
    return None


def update(database, user_id: str, body: Any) -> tuple[dict, int]:
    if not isinstance(body, dict) or not isinstance(body.get("action"), str):
        return {"code": "INVALID_INPUT"}, 400
    if body["action"] == "delete" and body.get("section") == "coach":
        return delete_coach(database, user_id, body.get("projects"))
    for _ in range(3):
        revision, before = read(database, user_id)
        proposed = change(before, body)
        if proposed is None:
            return {"code": "INVALID_INPUT"}, 400
        layout, removed = proposed
        result = database.client.rpc("write_owner_chat_structure_v1", {
            "p_user": user_id, "p_expected": revision, "p_document": layout, "p_removed": removed,
        }).execute()
        if result.data is True:
            return layout, 200
    return {"code": "CHAT_STRUCTURE_CHANGED"}, 409


def _principal(database, user_id: str) -> str:
    from services.project_repository import ProjectRepository

    return str(ProjectRepository(database).owner_for_user(user_id).id)


def coach_projects(database, user_id: str) -> list[dict]:
    owner = _principal(database, user_id)
    return (database.client.table("projects").select("id,display_name")
            .eq("owner_principal_id", owner).is_("tombstoned_at", "null").order("id").execute().data or [])


def delete_coach(database, user_id: str, projects: Any) -> tuple[dict, int]:
    if not isinstance(projects, list):
        return {"code": "INVALID_INPUT"}, 400
    try:
        expected = sorted({str(UUID(item)) for item in projects if isinstance(item, str)})
    except ValueError:
        return {"code": "INVALID_INPUT"}, 400
    if len(expected) != len(projects):
        return {"code": "INVALID_INPUT"}, 400
    revision, _ = read(database, user_id)
    result = database.client.rpc("delete_owner_speaking_chat_v1", {
        "p_user": user_id, "p_principal": _principal(database, user_id),
        "p_expected": revision, "p_projects": expected,
    }).execute()
    if result.data is True:
        return read(database, user_id)[1], 200
    return {"code": "CHAT_STRUCTURE_CHANGED"}, 409


def section(layout: dict, section_id: str) -> dict | None:
    if layout["builder"] != "active":
        return None
    if section_id == layout["main_chat_id"]:
        return {"id": section_id}
    return next((item for item in layout["subchats"]
                 if item["id"] == section_id and not item["archived"]), None)


def turns(database, user_id: str, section_id: str) -> tuple[dict, int]:
    if section(read(database, user_id)[1], section_id) is None:
        return {"code": "NOT_FOUND"}, 404
    return {"turns": read_turns(database, user_id, section_id)}, 200


def read_turns(database, user_id: str, section_id: str, *, limit: int = 100) -> list[dict]:
    result = (database.client.table("owner_chat_section_turns")
              .select("client_id,question,answer").eq("user_id", user_id)
              .eq("section_id", section_id).order("created_at", desc=True)
              .order("client_id", desc=True).limit(limit).execute())
    return list(reversed(result.data or []))


def keep_turn(database, user_id: str, section_id: str, body: Any) -> tuple[dict, int]:
    if not isinstance(body, dict):
        return {"code": "INVALID_INPUT"}, 400
    try:
        client_id = str(UUID(str(body.get("client_id"))))
    except ValueError:
        return {"code": "INVALID_INPUT"}, 400
    question = _words(body.get("question"), 4000)
    answer = _words(body.get("answer"), 16000)
    if not question or not answer:
        return {"code": "INVALID_INPUT"}, 400
    result = database.client.rpc("append_owner_chat_section_v1", {
        "p_user": user_id, "p_section": section_id, "p_client": client_id,
        "p_question": question, "p_answer": answer,
    }).execute()
    return ({"saved": True}, 200) if result.data is True else ({"code": "NOT_FOUND"}, 404)
