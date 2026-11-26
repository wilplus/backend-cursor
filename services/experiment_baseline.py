"""Private recording and self-report for the isolated baseline pilot."""
from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any
from uuid import UUID

from postgrest.exceptions import APIError
from postgrest.types import ReturnMethod

from config import Config
from services import chat_voice, experiments

MODES = ("initial", "on_demand", "refresh")
VALENCES = ("pleasant", "unpleasant", "neutral", "mixed", "unsure")
ENERGIES = ("low", "low_to_medium", "medium", "medium_to_high", "high", "unsure")
MAX_AUDIO_BYTES = 4 * 1024 * 1024
_PAGE_SIZE = 50
_PROGRESS = "experiment_baseline_progress"
_MEDIA_TYPES = ("audio/webm", "audio/wav", "audio/ogg", "audio/mp4", "audio/mpeg")
_MEDIA_ALIASES = {
    "video/webm": "audio/webm", "audio/x-wav": "audio/wav", "audio/wave": "audio/wav",
    "audio/x-m4a": "audio/mp4", "audio/mp3": "audio/mpeg",
}
_CONFLICTS = (
    "PILOT_INITIAL_REQUIRED", "PILOT_REQUEST_CONFLICT", "PILOT_RUN_IN_PROGRESS",
    "PILOT_STEP_CONFLICT", "PILOT_STEP_ORDER", "PILOT_AUDIO_REQUIRED",
)


def error(code: str, status: int) -> experiments.ExperimentsError:
    return experiments.ExperimentsError(code, code, status)


def enabled(user_id: str) -> None:
    if not Config.EXPERIMENT_BASELINE_PILOT_ENABLED or user_id.lower() not in Config.EXPERIMENT_BASELINE_PILOT_USER_IDS:
        raise error("PILOT_UNAVAILABLE", 404)


def _text(value: Any, maximum: int) -> bool:
    return isinstance(value, str) and bool(value.strip()) and len(value) <= maximum


def _prompt(item: Any) -> dict:
    required = {"id", "prompt", "intended_energy"}
    if (not isinstance(item, dict)
            or not required <= item.keys() <= required | {"intended_valence", "partition"}
            or not _text(item["id"], 80) or not _text(item["prompt"], 2000)
            or item.get("intended_valence") not in (None, "pleasant", "unpleasant")
            or item["intended_energy"] not in ENERGIES[:-1]
            or item.get("partition", "calibration") not in ("calibration", "held_out")):
        raise ValueError("invalid pilot prompt")
    normalized = " ".join(unicodedata.normalize("NFKC", item["prompt"]).casefold().split())
    return {"partition": "calibration", **item, "prompt_sha256": hashlib.sha256(normalized.encode()).hexdigest()}


def protocol(language: str) -> dict | None:
    """Validate the operator-supplied, approved disclosure and prompt set."""
    try:
        value = json.loads(Config.EXPERIMENT_BASELINE_PILOT_PROTOCOL)
        if not isinstance(value, dict) or language not in ("en", "pl"):
            return None
        value = value.get(language) if set(value) == {"en", "pl"} else value
        if not isinstance(value, dict) or set(value) != {"version", "disclosure", "prompts"}:
            return None
        disclosure, prompts = value["disclosure"], value["prompts"]
        if (not _text(value["version"], 80)
                or not isinstance(disclosure, dict) or set(disclosure) != {"version", "recording", "purpose", "use"}
                or not _text(disclosure["version"], 80)
                or any(not _text(disclosure[key], 2000) for key in ("recording", "purpose", "use"))
                or not isinstance(prompts, list) or len(prompts) != 2):
            return None
        prompts = [_prompt(item) for item in prompts]
    except (ValueError, TypeError):
        return None
    if ([p["intended_energy"] for p in prompts] != ["low", "high"]
            or prompts[0]["id"] == prompts[1]["id"]
            or prompts[0]["prompt_sha256"] == prompts[1]["prompt_sha256"]):
        return None
    return {**value, "prompts": prompts}


def volunteer(database: Any, user_id: str) -> str | None:
    rows = experiments._data(database.client.table(experiments.KEYS).select("volunteer_id")
                             .eq("user_id", user_id).limit(1).execute())
    return str(rows[0]["volunteer_id"]) if rows else None


def _runs(database: Any, owner: str):
    return database.client.table(_PROGRESS).select("*").eq("volunteer_id", owner)


def _latest(database: Any, owner: str, mode: str) -> dict | None:
    rows = experiments._data(_runs(database, owner).eq("mode", mode)
                             .order("created_at", desc=True).order("id", desc=True).limit(1).execute())
    return rows[0] if rows else None


def _public_run(row: dict) -> dict:
    next_step = None
    if row["next_step_id"]:
        next_step = {"id": row["next_step_id"], "prompt": row["next_prompt"],
                     "state": row["next_step_state"]}
    return {**{key: row[key] for key in ("id", "mode", "protocol_version", "created_at", "completed_at")},
            "next_step": next_step}


def _entry_allowed(database: Any, owner: str) -> bool:
    initial = _latest(database, owner, "initial")
    return bool(initial and initial["completed_at"])


def status(database: Any, user_id: str, language: str) -> dict:
    owner = volunteer(database, user_id)
    rows = {mode: _latest(database, owner, mode) if owner else None for mode in MODES}
    initial = rows["initial"]
    settings = protocol(language)
    return {
        "entry_allowed": bool(initial and initial["completed_at"]),
        "disclosure": settings["disclosure"] if settings else None,
        "runs": {mode: _public_run(row) if row else None for mode, row in rows.items()},
    }


def history(database: Any, user_id: str, mode: str, offset: int = 0) -> dict:
    if mode not in MODES or not 0 <= offset <= 2_147_483_647 - _PAGE_SIZE:
        raise error("PILOT_INPUT", 400)
    owner = volunteer(database, user_id)
    rows = experiments._data(
        _runs(database, owner).eq("mode", mode).order("created_at", desc=True).order("id", desc=True)
        .range(offset, offset + _PAGE_SIZE - 1).execute()
    ) if owner else []
    return {"runs": [_public_run(row) for row in rows],
            "next_offset": offset + _PAGE_SIZE if len(rows) == _PAGE_SIZE else None}


def _run_result(database: Any, owner: str, run_id: str) -> dict:
    rows = experiments._data(_runs(database, owner).eq("id", run_id).limit(1).execute())
    if not rows:
        raise error("PILOT_NOT_FOUND", 404)
    run = _public_run(rows[0])
    permitted = bool(run["completed_at"]) if run["mode"] == "initial" else _entry_allowed(database, owner)
    return {"entry_allowed": permitted, "run": run}


def _uuid(value: Any) -> str:
    if isinstance(value, str):
        try:
            return str(UUID(value))
        except ValueError:
            pass
    raise error("PILOT_INPUT", 400)


def _write(database: Any, rpc: str, parameters: dict) -> str:
    try:
        result = database.client.rpc(rpc, parameters).execute().data
    except APIError as exc:
        if exc.code == "P0001":
            if exc.message == "PILOT_INPUT":
                raise error(exc.message, 422) from None
            if exc.message in _CONFLICTS:
                raise error(exc.message, 409) from None
            if exc.message in ("PILOT_NOT_FOUND", "PILOT_UNAVAILABLE"):
                raise error(exc.message, 404) from None
            if exc.message == "PILOT_PROTOCOL_UNAVAILABLE":
                raise error(exc.message, 503) from None
        raise
    if not isinstance(result, str):
        raise error("PILOT_STORE", 503)
    return result


def start_run(database: Any, user_id: str, body: Any) -> dict:
    if (not isinstance(body, dict) or body.get("mode") not in MODES
            or body.get("language", "en") not in ("en", "pl")):
        raise error("PILOT_INPUT", 400)
    mode, request_id = body["mode"], _uuid(body.get("request_id"))
    owner = volunteer(database, user_id)
    if owner:
        replay = experiments._data(_runs(database, owner).eq("request_id", request_id).limit(1).execute())
        if replay:
            if replay[0]["mode"] != mode:
                raise error("PILOT_REQUEST_CONFLICT", 409)
            return _run_result(database, owner, replay[0]["id"])
    if mode != "initial" and (not owner or not _entry_allowed(database, owner)):
        raise error("PILOT_INITIAL_REQUIRED", 409)
    settings = protocol(body.get("language", "en"))
    if settings is None:
        raise error("PILOT_PROTOCOL_UNAVAILABLE", 503)
    consent = experiments._consent(body.get("consent"))
    if consent["version"] != settings["disclosure"]["version"]:
        raise error("CONSENT_REQUIRED", 422)
    proposed_owner = owner or experiments.volunteer_id_for(user_id)
    run_id = _write(database, "start_experiment_baseline", {
        "p_user_id": user_id, "p_new_volunteer_id": proposed_owner, "p_request_id": request_id, "p_mode": mode,
        "p_protocol_version": settings["version"],
        "p_consent": {**consent, "disclosure": settings["disclosure"]}, "p_prompts": settings["prompts"],
    })
    return _run_result(database, volunteer(database, user_id) or proposed_owner, run_id)


def _owned_run(database: Any, user_id: str, run_id: str) -> str:
    owner = volunteer(database, user_id)
    if owner and _runs(database, owner).eq("id", run_id).limit(1).execute().data:
        return owner
    raise error("PILOT_NOT_FOUND", 404)


def _save(database: Any, owner: str, run_id: str, step_id: str, **fields) -> dict:
    saved_run = _write(database, "save_experiment_baseline_step", {
        "p_volunteer_id": owner, "p_run_id": run_id, "p_step_id": step_id, **fields,
    })
    return _run_result(database, owner, saved_run)


def save_audio(database: Any, user_id: str, run_id: str, step_id: str,
               *, audio: bytes, content_type: str, filename: str) -> dict:
    run_id, step_id = _uuid(run_id), _uuid(step_id)
    owner = _owned_run(database, user_id, run_id)
    if len(audio) > MAX_AUDIO_BYTES:
        raise error("PILOT_AUDIO_TOO_LARGE", 413)
    mime = experiments._audio_mime(content_type)
    mime = _MEDIA_ALIASES.get(mime, mime)
    if not audio or mime not in _MEDIA_TYPES:
        raise error("PILOT_AUDIO_INVALID", 422)
    decoded = chat_voice.decode(audio, filename)
    if decoded is None or chat_voice.too_long(len(decoded[0]) / decoded[1]):
        raise error("PILOT_AUDIO_INVALID", 422)
    from services.min_content_gate import evaluate_min_content

    if not evaluate_min_content(decoded[0])["ok"]:
        raise error("PILOT_AUDIO_INVALID", 422)
    return _save(database, owner, run_id, step_id, p_audio="\\x" + audio.hex(), p_content_type=mime)


def save_report(database: Any, user_id: str, run_id: str, step_id: str, body: Any) -> dict:
    if not isinstance(body, dict) or not (
        body.keys() == {"felt_energy"} and body["felt_energy"] in ENERGIES
        or body.keys() == {"felt_valence"} and body["felt_valence"] in VALENCES
    ):
        raise error("PILOT_REPORT_REQUIRED", 422)
    run_id, step_id = _uuid(run_id), _uuid(step_id)
    owner = _owned_run(database, user_id, run_id)
    return _save(database, owner, run_id, step_id, p_felt_valence=body.get("felt_valence"),
                 p_felt_energy=body.get("felt_energy"))


def read_audio(database: Any, user_id: str, run_id: str, step_id: str) -> tuple[bytes, str]:
    """Keep the saved answer replayable when a private report resumes after reload."""
    from services.chats import _bytes

    run_id, step_id = _uuid(run_id), _uuid(step_id)
    _owned_run(database, user_id, run_id)
    rows = experiments._data(database.client.table("experiment_baseline_steps").select("audio,content_type")
                             .eq("run_id", run_id).eq("id", step_id).limit(1).execute())
    audio = _bytes(rows[0].get("audio")) if rows else b""
    if not audio:
        raise error("PILOT_NOT_FOUND", 404)
    return audio, rows[0]["content_type"]


def erase(database: Any, user_id: str) -> dict:
    owner = volunteer(database, user_id)
    if owner:
        (database.client.table("experiment_baseline_participants").delete(returning=ReturnMethod.minimal)
         .eq("volunteer_id", owner).execute())
    return {"deleted": True}
