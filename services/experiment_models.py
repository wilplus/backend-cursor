"""The experiments model catalog, a chat's chosen model, and taught replies.

Built-in models live here, not in the database. A host's own model is a
row on ``experiment_models``, visible only to them. A chat's choice is
``people_profiles.chat_recipe["experiment"]``: ``model_id`` and
``baseline_prompt_ids``. It travels with the recipe.

The sentence on a built-in model is the catalog line the chat builder
shows. It is not a feeling about a person.
"""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from services.experiments import ExperimentsError, ensure_volunteer
from services.experiments_config import canonical_prompt, load_prompt_set

logger = logging.getLogger(__name__)

MODELS = "experiment_models"
BUILTIN_ID = "wpl_arousal@0.1"
STEPS = ["engagement", "arousal", "valence", "clarity"]
SCHEMA = "analyze-take/v0.1"
#: The catalog line for the built-in model. The chat builder shows it.
MEASURES = (
    "How much you join in, how your voice moves, how it lands and how clear it was"
)
_MAX_NAME = 80
_MAX_MEASURES = 200
_MAX_TEXT = 400


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _rows(result: Any) -> list[dict[str, Any]]:
    data = getattr(result, "data", None)
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list):
        return [row for row in data if isinstance(row, dict)]
    return []


def _prompt_ids(prompt_set: dict[str, Any] | None = None) -> list[str]:
    prompt_set = load_prompt_set() if prompt_set is None else prompt_set
    tags = {prompt["tag"] for prompt in prompt_set["prompts"] if str(prompt["tag"]).startswith("baseline")}
    return [str(prompt["id"]) for prompt in prompt_set["prompts"] if prompt["tag"] in tags]


def builtin() -> dict[str, Any]:
    """The packaged model. Its id is stable."""
    return {
        "id": BUILTIN_ID,
        "name": "Arousal",
        "measures": MEASURES,
        "language": "pl",
        "source": "built_in",
        "research_only": True,
        "needs_baseline": True,
        "steps": list(STEPS),
        "version": "0.1",
        "baseline_prompt_ids": _prompt_ids(),
        "schema": SCHEMA,
    }


def _as_list(value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise ExperimentsError("MODEL", "The baseline prompts are missing.")
    ids: list[str] = []
    known = {prompt["id"] for prompt in load_prompt_set()["prompts"]}
    for item in value:
        if not isinstance(item, str) or item not in known or item in ids:
            raise ExperimentsError("MODEL", "A baseline prompt is not in the library.")
        ids.append(item)
    return ids


def _overrides(body: dict[str, Any]) -> dict[str, Any] | None:
    raw = body.get("interventions")
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ExperimentsError("MODEL", "Interventions must be a list.")
    kept = [_one_rule(item) for item in raw[:20]]
    return {"interventions": kept}


def _one_rule(item: Any) -> dict[str, Any]:
    if not isinstance(item, dict):
        raise ExperimentsError("MODEL", "An intervention must be an object.")
    step = item.get("step")
    if step not in STEPS:
        raise ExperimentsError("MODEL", "An intervention step is not in the model.")
    name = " ".join(str(item.get("name") or "").split())
    text = " ".join(str(item.get("text") or "").split())
    if not name or len(name) > _MAX_NAME or len(text) > _MAX_TEXT:
        raise ExperimentsError("MODEL", "An intervention needs a name and a short tip.")
    threshold = item.get("threshold", 1.0)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ExperimentsError("MODEL", "A threshold must be a number.")
    if not 0 <= float(threshold) <= 2:
        raise ExperimentsError("MODEL", "A threshold must be from 0 to 2.")
    return {
        "id": str(item.get("id") or uuid.uuid4()),
        "name": name,
        "text": text,
        "step": step,
        "threshold": float(threshold),
        "grid": item.get("grid") if isinstance(item.get("grid"), (dict, list)) else [],
    }


def _custom_out(row: dict[str, Any], base: dict[str, Any]) -> dict[str, Any]:
    prompts = row.get("baseline_prompt_ids")
    return {
        "id": str(row.get("id")),
        "name": row.get("name"),
        "measures": row.get("measures"),
        "language": base["language"],
        "source": "user",
        "research_only": True,
        "needs_baseline": True,
        "steps": list(base["steps"]),
        "version": "1",
        "baseline_prompt_ids": list(prompts) if isinstance(prompts, list) else [],
        "schema": base["schema"],
    }


def _saved_rules(row: dict[str, Any]) -> list[dict[str, Any]]:
    raw = row.get("overrides")
    overrides = raw if isinstance(raw, dict) else {}
    rules = overrides.get("interventions")
    return list(rules) if isinstance(rules, list) else []


def _owned_row(database: Any, volunteer_id: str, model_id: str) -> dict[str, Any] | None:
    rows = _rows(database.client.table(MODELS).select("*")
                 .eq("volunteer_id", volunteer_id).eq("id", model_id).limit(1).execute())
    return rows[0] if rows else None


def resolve_model(database: Any, user_id: str, model_id: str | None) -> dict[str, Any]:
    """The caller's model, or 404. The default is the built-in."""
    chosen = (model_id or BUILTIN_ID).strip()
    base = builtin()
    if chosen == base["id"]:
        return {**base, "interventions": []}
    volunteer_id = ensure_volunteer(database, user_id)
    row = _owned_row(database, volunteer_id, chosen)
    if row is None or str(row.get("base_model_id") or "") != base["id"]:
        raise ExperimentsError("NOT_FOUND", "That model is not here.", 404)
    return {**_custom_out(row, base), "interventions": _saved_rules(row)}


def model_for_volunteer(database: Any, volunteer_id: str, model_id: str) -> dict[str, Any]:
    """The model a queued take named. The job has the volunteer id, not the user id."""
    base = builtin()
    if not model_id or model_id == base["id"]:
        return {**base, "interventions": []}
    row = _owned_row(database, volunteer_id, model_id)
    if row is None or str(row.get("base_model_id") or "") != base["id"]:
        raise RuntimeError("model")
    return {**_custom_out(row, base), "interventions": _saved_rules(row)}


def list_models(database: Any, user_id: str) -> dict[str, Any]:
    base = builtin()
    volunteer_id = ensure_volunteer(database, user_id)
    rows = _rows(database.client.table(MODELS).select("*").eq("volunteer_id", volunteer_id).execute())
    rows.sort(key=lambda row: str(row.get("created_at") or ""))
    return {"models": [base, *[_custom_out(row, base) for row in rows]]}


def _clean_model(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ExperimentsError("MODEL", "The model is missing.")
    base = builtin()
    if body.get("base_model_id") != base["id"]:
        raise ExperimentsError("NOT_FOUND", "That model is not here.", 404)
    name = " ".join(str(body.get("name") or "").split())
    measures = " ".join(str(body.get("measures") or "").split())
    if not name or len(name) > _MAX_NAME or not measures or len(measures) > _MAX_MEASURES:
        raise ExperimentsError("MODEL", "The model needs a name and a short line.")
    steps = body.get("steps")
    if steps is not None and list(steps) != list(base["steps"]):
        raise ExperimentsError("MODEL", "The steps stay in the built-in order.")
    return {
        "name": name,
        "base_model_id": base["id"],
        "measures": measures,
        "baseline_prompt_ids": _as_list(body.get("baseline_prompt_ids") or base["baseline_prompt_ids"]),
        "overrides": _overrides(body),
        "updated_at": _now(),
    }


def create_model(database: Any, user_id: str, body: Any) -> dict[str, Any]:
    volunteer_id = ensure_volunteer(database, user_id)
    row = {**_clean_model(body), "id": str(uuid.uuid4()), "volunteer_id": volunteer_id}
    made = _rows(database.client.table(MODELS).insert(row).execute())
    return _custom_out(made[0] if made else row, builtin())


def update_model(database: Any, user_id: str, model_id: str, body: Any) -> dict[str, Any]:
    volunteer_id = ensure_volunteer(database, user_id)
    if _owned_row(database, volunteer_id, model_id) is None:
        raise ExperimentsError("NOT_FOUND", "That model is not here.", 404)
    changed = _clean_model(body)
    made = _rows(database.client.table(MODELS).update(changed)
                 .eq("volunteer_id", volunteer_id).eq("id", model_id).execute())
    return _custom_out(made[0] if made else {**changed, "id": model_id}, builtin())


def delete_model(database: Any, user_id: str, model_id: str) -> dict[str, bool]:
    volunteer_id = ensure_volunteer(database, user_id)
    if _owned_row(database, volunteer_id, model_id) is None:
        raise ExperimentsError("NOT_FOUND", "That model is not here.", 404)
    database.client.table(MODELS).delete().eq("volunteer_id", volunteer_id).eq("id", model_id).execute()
    return {"deleted": True}


def _sign(value: float) -> int:
    if abs(value) < 1e-9:
        return 0
    return 1 if value > 0 else -1


def _expected(pattern: Any) -> list[dict[str, Any]]:
    if isinstance(pattern, list):
        return [item for item in pattern if isinstance(item, dict)]
    if not isinstance(pattern, dict):
        return []
    found = []
    for step, cells in pattern.items():
        if isinstance(cells, dict):
            nums = [float(v) for v in cells.values()
                    if isinstance(v, (int, float)) and not isinstance(v, bool)]
            if nums:
                found.append({"step": step, "cue": "*", "value": sum(nums) / len(nums)})
        elif isinstance(cells, (int, float)) and not isinstance(cells, bool):
            found.append({"step": step, "cue": "*", "value": float(cells)})
    return found


def _actuals(grid: Any, step: str, cue: str) -> list[float]:
    if not isinstance(grid, list):
        return []
    values = []
    for cell in grid:
        if not isinstance(cell, dict) or cell.get("step") != step:
            continue
        if cue not in ("*", None, cell.get("cue")):
            continue
        value = cell.get("value")
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            values.append(float(value))
    return values


def _overlap(pattern: Any, moments: list[dict[str, Any]]) -> float:
    expected = _expected(pattern)
    if not expected:
        return 0.0
    scores: list[float] = []
    for item in expected:
        step, cue = str(item.get("step") or ""), item.get("cue") or "*"
        wanted = item.get("value")
        if isinstance(wanted, bool) or not isinstance(wanted, (int, float)):
            continue
        for moment in moments:
            got = _actuals(moment.get("grid"), step, str(cue))
            if not got:
                scores.append(0.0)
                continue
            actual = sum(got) / len(got)
            match = 1.0 if _sign(float(wanted)) == _sign(actual) else 0.0
            close = (1.0 - min(1.0, abs(float(wanted) - actual) / 2.0)) if match else 0.0
            scores.append(match + close)
    if not scores:
        return 0.0
    return sum(scores) / len(scores)


def volunteer_rules(database: Any, volunteer_id: str) -> list[dict[str, Any]]:
    rows = _rows(database.client.table("experiment_interventions").select("*")
                 .eq("volunteer_id", volunteer_id).execute())
    rules = []
    for row in rows:
        raw_rule = row.get("rule")
        rule: dict[str, Any] = raw_rule if isinstance(raw_rule, dict) else {}
        rules.append({
            "id": str(row.get("id")),
            "name": str(rule.get("name") or "Tip")[:_MAX_NAME],
            "text": str(rule.get("text") or "")[:_MAX_TEXT],
            "step": rule.get("step"),
            "threshold": row.get("threshold", 1.0),
            "grid": row.get("grid"),
        })
    return rules


def pick_interventions(document: dict[str, Any], rules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """At most two tips. The earlier step wins. Each one carries its text."""
    takes = document.get("takes") if isinstance(document.get("takes"), list) else []
    take = takes[0] if takes and isinstance(takes[0], dict) else {}
    order = list(take.get("order") or STEPS)
    gate = take.get("gate") if isinstance(take.get("gate"), dict) else None
    allowed = order
    if gate and gate.get("step") in order:
        allowed = order[:order.index(gate["step"]) + 1]
    moments = [m for m in (take.get("moments") or []) if isinstance(m, dict)]
    fired = []
    for rule in rules:
        step = rule.get("step")
        if step not in allowed:
            continue
        threshold = rule.get("threshold", 1.0)
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            continue
        score = _overlap(rule.get("grid"), moments)
        if score + 1e-9 < float(threshold):
            continue
        fired.append({
            "id": str(rule.get("id") or ""),
            "name": str(rule.get("name") or "Tip"),
            "text": str(rule.get("text") or ""),
            "step": step,
            "score": round(score, 4),
        })
    fired.sort(key=lambda row: (
        allowed.index(str(row["step"])), -float(str(row["score"])), str(row["id"])))
    return fired[:2]


def finish_document(document: dict[str, Any], model: dict[str, Any], rules: list[dict[str, Any]]) -> dict[str, Any]:
    """The stored analysis: model id, an unlocked flag on every step, and tips."""
    document["model_id"] = model["id"]
    for take in document.get("takes") or []:
        if not isinstance(take, dict):
            continue
        summary = take.get("summary")
        if not isinstance(summary, dict):
            summary = {}
            take["summary"] = summary
        for step in STEPS:
            cell = summary.get(step)
            if not isinstance(cell, dict):
                summary[step] = {"score": None, "confidence": 0.0, "vs": "baseline", "unlocked": False}
            else:
                cell["unlocked"] = cell.get("unlocked") is True
    document["intervention"] = pick_interventions(document, rules)
    return document


def rules_for(database: Any, volunteer_id: str, model: dict[str, Any]) -> list[dict[str, Any]]:
    """The model's own tips when it has them, otherwise the volunteer's."""
    own = model.get("interventions")
    if isinstance(own, list) and own:
        return own
    return volunteer_rules(database, volunteer_id)


# ── A chat's choice, kept on the host's recipe ──────────────────────────

def _uuid(value: str) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        return None


def _chat_id_ok(chat_id: str) -> bool:
    text = str(chat_id or "")
    return bool(text) and len(text) <= 80 and text[0].isalnum() and all(
        char.isalnum() or char in "-_" for char in text)


def _host_of_thread(database: Any, thread: dict[str, Any], members: list[dict[str, Any]]) -> str | None:
    owner = thread.get("widget_owner_id") or thread.get("demo_user_id")
    if owner:
        return str(owner)
    link = thread.get("link_id")
    if link:
        rows = _rows(database.client.table("chat_links").select("user_id").eq("id", link).limit(1).execute())
        if rows and rows[0].get("user_id"):
            return str(rows[0]["user_id"])
    people = [m for m in members if m.get("user_id")]
    people.sort(key=lambda row: str(row.get("created_at") or ""))
    return str(people[0]["user_id"]) if people else None


def chat_role(database: Any, user_id: str, chat_id: str) -> tuple[str, bool]:
    """``(host user id, caller is the host)``. 404 when the chat is not theirs."""
    if not _chat_id_ok(chat_id):
        raise ExperimentsError("NOT_FOUND", "Not found.", 404)
    thread_id = _uuid(chat_id)
    thread = None
    if thread_id:
        rows = _rows(database.client.table("chat_threads").select("*").eq("id", thread_id).limit(1).execute())
        thread = rows[0] if rows else None
    if thread is None:
        return str(user_id), True
    members = _rows(database.client.table("chat_members").select("user_id,created_at")
                    .eq("thread_id", thread_id).execute())
    if str(user_id) not in {str(m.get("user_id")) for m in members}:
        raise ExperimentsError("NOT_FOUND", "Not found.", 404)
    host = _host_of_thread(database, thread, members)
    if not host:
        raise ExperimentsError("NOT_FOUND", "Not found.", 404)
    return host, str(user_id) == host


def _recipe(database: Any, host_id: str) -> dict[str, Any]:
    from services.assistants import recipe_of
    recipe = recipe_of(database, host_id)
    return dict(recipe) if isinstance(recipe, dict) else {}


def _write_recipe(database: Any, host_id: str, recipe: dict[str, Any]) -> None:
    stamp = _now()
    stored = {**recipe, "updated_at": stamp}
    table = database.client.table("people_profiles")
    rows = _rows(table.select("user_id").eq("user_id", host_id).limit(1).execute())
    if rows:
        table.update({"chat_recipe": stored, "updated_at": stamp}).eq("user_id", host_id).execute()
    else:
        table.insert({"user_id": host_id, "chat_recipe": stored}).execute()


def _prompts_for(database: Any, host_id: str, prompt_ids: list[str]) -> list[dict[str, Any]]:
    from services.experiments import volunteer_id_for
    volunteer_id = volunteer_id_for(host_id)
    library = _rows(database.client.table("experiment_prompts").select("prompt_id,text,tag")
                    .eq("volunteer_id", volunteer_id).execute())
    by_id = {str(row.get("prompt_id")): row for row in library}
    found = []
    for prompt_id in prompt_ids:
        row = by_id.get(prompt_id)
        if row:
            found.append({"id": prompt_id, "text": row.get("text") or "", "tag": row.get("tag") or ""})
            continue
        prompt = canonical_prompt(load_prompt_set(), prompt_id)
        if prompt:
            found.append({"id": prompt["id"], "text": prompt["text"], "tag": prompt["tag"]})
    return found


def _config_of(recipe: dict[str, Any], model: dict[str, Any]) -> dict[str, Any]:
    raw = recipe.get("experiment")
    saved: dict[str, Any] = raw if isinstance(raw, dict) else {}
    model_id = str(saved.get("model_id") or model["id"])
    prompts = saved.get("baseline_prompt_ids")
    if not isinstance(prompts, list) or not prompts:
        prompts = list(model["baseline_prompt_ids"])
    return {"model_id": model_id, "baseline_prompt_ids": [str(item) for item in prompts]}


def read_config(database: Any, user_id: str, chat_id: str) -> dict[str, Any]:
    host, _is_host = chat_role(database, user_id, chat_id)
    recipe = _recipe(database, host)
    raw = recipe.get("experiment")
    saved: dict[str, Any] = raw if isinstance(raw, dict) else {}
    model = resolve_model(database, host, saved.get("model_id"))
    choice = _config_of(recipe, model)
    return {
        "model_id": choice["model_id"],
        "needs_baseline": bool(model.get("needs_baseline")),
        "baseline_prompt_ids": choice["baseline_prompt_ids"],
        "baseline_prompts": _prompts_for(database, host, choice["baseline_prompt_ids"]),
    }


def write_config(database: Any, user_id: str, chat_id: str, body: Any) -> dict[str, Any]:
    host, is_host = chat_role(database, user_id, chat_id)
    if not is_host:
        raise ExperimentsError("NOT_FOUND", "Not found.", 404)
    if not isinstance(body, dict):
        raise ExperimentsError("MODEL", "The model is missing.")
    model = resolve_model(database, host, body.get("model_id") or BUILTIN_ID)
    prompts = body.get("baseline_prompt_ids")
    ids = _as_list(prompts) if prompts is not None else list(model["baseline_prompt_ids"])
    recipe = _recipe(database, host)
    recipe["experiment"] = {"model_id": model["id"], "baseline_prompt_ids": ids}
    _write_recipe(database, host, recipe)
    return read_config(database, user_id, chat_id)


def reply_examples(database: Any, user_id: str, chat_id: str, *, limit: int, offset: int) -> dict[str, Any]:
    """The host's kept Test answers for this chat. Nobody else."""
    host, is_host = chat_role(database, user_id, chat_id)
    if not is_host:
        raise ExperimentsError("NOT_FOUND", "Not found.", 404)
    rows = _rows(database.client.table("chat_reply_examples").select("id,created_at,ask,answer")
                 .eq("host_id", host).eq("chat_id", str(chat_id)[:80]).execute())
    rows.sort(key=lambda row: str(row.get("created_at") or ""), reverse=True)
    page = rows[offset:offset + limit]
    return {
        "count": len(rows),
        "items": [{
            "id": row.get("id"),
            "created_at": row.get("created_at"),
            "question": row.get("ask") or "",
            "prompt": row.get("ask") or "",
            "answer": row.get("answer") or "",
            "kind": "text",
        } for row in page],
    }
