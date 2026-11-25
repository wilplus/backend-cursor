"""Source-bound human observations and intervention matches for the founder."""
from services.refusal import Refusal
from services.speaking_calibration import _BOUNDS, _cues

TABLE = "speaking_pattern_examples"
FIELDS = "id,session_id,snippet_id,source,kind,pattern,start_ms,end_ms,note,intervention"
PAGE_SIZE = 30
KINDS = ("error", "praise", "control", "unsure")
ERROR_TOOLS = ("sniper", "ai_audio", "rewrite", "coach_video", "other")
PRAISE_TOOLS = ("name_strength", "play_strength", "other")


def examples_for(database, curator):
    return database.client.table(TABLE).select(FIELDS).eq("curator_id", curator)


def clip_examples(database, curator, source, session, snippet):
    rows = (examples_for(database, curator).eq("source", source)
            .eq("session_id", session).eq("snippet_id", snippet["id"])
            .order("created_at").order("id").execute().data or [])
    return {
        "examples": rows,
        "cues": _cues(snippet.get("metrics") or {}) if rows else {},
    }


def page(database, curator, offset, *, kind, source, search):
    query = examples_for(database, curator)
    if kind in KINDS:
        query = query.eq("kind", kind)
    if source in ("take", "corpus"):
        query = query.eq("source", source)
    if search:
        escaped = search.replace("\\", "\\\\").replace("%", r"\%").replace("_", r"\_")
        query = query.ilike("pattern", "%" + escaped + "%")
    return (query.order("created_at", desc=True)
            .order("id", desc=True).range(offset, offset + PAGE_SIZE - 1)
            .execute().data or [])


def _text(value, limit, *, required=False):
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise Refusal("INVALID_PATTERN", "Check the pattern name and notes.", 400)
    return value.strip()


def observation(body, duration):
    if set(body) - {"kind", "pattern", "start_ms", "end_ms", "note"}:
        raise Refusal("INVALID_PATTERN", "This form saves a listening observation.", 400)
    kind, start, end = body.get("kind"), body.get("start_ms"), body.get("end_ms")
    if (kind not in KINDS or type(start) is not int or type(end) is not int
            or not 0 <= start < end <= duration):
        raise Refusal("INVALID_PATTERN", "Choose a label and a span inside the clip.", 400)
    return {
        "kind": kind, "pattern": _text(body.get("pattern"), 100, required=True),
        "start_ms": start, "end_ms": end, "note": _text(body.get("note", ""), 1000),
    }


def intervention(body, kind):
    if set(body) - {"example_id", "intervention"}:
        raise Refusal("INVALID_MATCH", "This form saves an intervention match.", 400)
    value = body.get("intervention")
    if value is None:
        return None
    tools = ERROR_TOOLS if kind == "error" else PRAISE_TOOLS if kind == "praise" else ()
    if (not isinstance(value, dict) or set(value) - {"tool", "name", "delivery", "status", "values"}
            or value.get("tool") not in tools or value.get("status") not in ("draft", "approved")):
        raise Refusal("INVALID_MATCH", "Choose an intervention for this pattern.", 400)
    return {
        "tool": value["tool"], "status": value["status"],
        "name": _text(value.get("name"), 100, required=True),
        "delivery": _text(value.get("delivery", ""), 1000),
        "values": _delivery_values(value.get("values", {}), kind),
    }


def _delivery_values(values, kind):
    if (not isinstance(values, dict) or set(values) - set(_BOUNDS)
            or (values and kind != "error")):
        raise Refusal("INVALID_MATCH", "Check the delivery values.", 400)
    for key, value in values.items():
        low, high = _BOUNDS[key]
        if type(value) not in (int, float) or not low <= value <= high:
            raise Refusal("INVALID_MATCH", "Check the delivery values.", 400)
    return values


def save_observation(database, curator, source, session, snippet, body):
    fields = observation(body, snippet["duration_ms"])
    database.client.table(TABLE).insert({
        **fields, "curator_id": curator, "source": source,
        "session_id": session, "snippet_id": snippet["id"],
    }).execute()


def example_query(query, curator, source, session, snippet, example):
    return (query.eq("curator_id", curator).eq("source", source).eq("session_id", session)
            .eq("snippet_id", snippet).eq("id", example))
