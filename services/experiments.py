"""A volunteer's private experiments: sessions, takes, prompts, interventions.

The caller's auth id is kept only on ``experiment_volunteer_keys``, so a
deletion can find the row. Every other table stores the opaque
``volunteer_id`` and every read filters on it. The API never returns the
auth id. The service-role key is the client's, and this module never reads
or logs it.

The analysis the volunteer reads is analyze-take/v0.1, without the locked
research scores. Nothing here names a feeling.
``coaching_context`` builds a block the coaching chat could read later; it
does not call that chat.

The gate order, each cell's ``reference``, and the self-rating choices come
from the prompt set (``services/experiments_config.py``).
"""
from __future__ import annotations

import csv
import hashlib
import hmac
import io
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from services.chat_voice import safe_name, too_big, too_long, transcribe_words
from services.experiments_config import (
    CHANNELS,
    canonical_prompt,
    check_self_rating,
    load_prompt_set,
    prompt_tags,
    rank_interventions,
    step_of,
)
from services.experiments_config import PromptSetError

logger = logging.getLogger(__name__)

KEYS = "experiment_volunteer_keys"
SESSIONS = "experiment_sessions"
TAKES = "experiment_takes"
PROMPTS = "experiment_prompts"
INTERVENTIONS = "experiment_interventions"
BUCKET = "experiment-recordings"
CASE_MAX = 10 * 1024 * 1024
TEXT_MAX = 20000
_BUILT_IN_PEPPER = "experiments-v1"
_SLIDE_EXT = {".ppt", ".pptx", ".odp", ".key"}
_PDF_TYPES = {"application/pdf"}
_SLIDE_TYPES = {
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.oasis.opendocument.presentation",
    "application/x-iwork-keynote-sffkey",
}


class ExperimentsError(Exception):
    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def _pepper() -> str:
    raw = (os.environ.get("EXPERIMENTS_VOLUNTEER_PEPPER") or "").strip()
    service = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    if raw and service and raw == service:
        raise ExperimentsError(
            "CONFIG", "The volunteer pepper is not a usable secret.", 500)
    return raw or _BUILT_IN_PEPPER


def volunteer_id_for(user_id: str) -> str:
    """An opaque id. It is not the auth id, and it is not logged as one."""
    digest = hmac.new(
        _pepper().encode("utf-8"), str(user_id).encode("utf-8"), hashlib.sha256)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _data(result: Any) -> list[dict[str, Any]]:
    rows = getattr(result, "data", None)
    if isinstance(rows, dict):
        return [rows]
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return []


def _table(database: Any, name: str) -> Any:
    return database.client.table(name)


def _own(database: Any, name: str, volunteer_id: str) -> list[dict[str, Any]]:
    return _data(
        _table(database, name).select("*").eq("volunteer_id", volunteer_id).execute())


def _own_one(
    database: Any, name: str, volunteer_id: str, column: str, value: str,
) -> dict[str, Any] | None:
    rows = _data(
        _table(database, name).select("*")
        .eq("volunteer_id", volunteer_id).eq(column, value).limit(1).execute())
    return rows[0] if rows else None


def ensure_volunteer(database: Any, user_id: str) -> str:
    """The caller's opaque id, creating the key row the first time."""
    rows = _data(
        _table(database, KEYS).select("volunteer_id")
        .eq("user_id", user_id).limit(1).execute())
    if rows and rows[0].get("volunteer_id"):
        return str(rows[0]["volunteer_id"])
    volunteer_id = volunteer_id_for(user_id)
    try:
        _table(database, KEYS).insert({
            "user_id": user_id,
            "volunteer_id": volunteer_id,
            "researcher_consent": False,
        }).execute()
    except Exception:
        logger.exception("experiments: volunteer key insert failed")
        again = _data(
            _table(database, KEYS).select("volunteer_id")
            .eq("user_id", user_id).limit(1).execute())
        if again and again[0].get("volunteer_id"):
            return str(again[0]["volunteer_id"])
        raise ExperimentsError("STORE", "The volunteer record could not be saved.", 502) from None
    return volunteer_id


def _researcher(database: Any, user_id: str) -> bool:
    rows = _data(
        _table(database, KEYS).select("researcher_consent")
        .eq("user_id", user_id).limit(1).execute())
    return bool(rows and rows[0].get("researcher_consent") is True)


def _mark_researcher(database: Any, user_id: str) -> None:
    _table(database, KEYS).update(
        {"researcher_consent": True}).eq("user_id", user_id).execute()


def _consent(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ExperimentsError("CONSENT_REQUIRED", "Consent is required.")
    if body.get("participant") is not True:
        raise ExperimentsError("CONSENT_REQUIRED", "Consent is required.")
    researcher = body.get("researcher")
    if researcher is not True and researcher is not False:
        raise ExperimentsError("CONSENT_REQUIRED", "Consent is required.")
    version = body.get("version")
    if not isinstance(version, str) or not version.strip() or len(version) > 80:
        raise ExperimentsError("CONSENT_REQUIRED", "Consent is required.")
    return {
        "participant": True,
        "researcher": researcher is True,
        "version": version.strip(),
    }


def _rating(body: Any) -> dict[str, str]:
    try:
        return check_self_rating(body, load_prompt_set())
    except PromptSetError as exc:
        raise ExperimentsError("RATING", "The self rating does not match the prompt set.") from exc


def _ext(name: str) -> str:
    suffix = ""
    if "." in (name or ""):
        suffix = "." + name.rsplit(".", 1)[-1].lower()
    return suffix if len(suffix) <= 8 else ""


def _kind(name: str, content_type: str) -> str:
    suffix = _ext(name)
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if suffix == ".pdf" or mime in _PDF_TYPES:
        return "pdf"
    if suffix in _SLIDE_EXT or mime in _SLIDE_TYPES:
        return "slides"
    raise ExperimentsError("UNREADABLE", "Upload one PDF page, or slides.")


def pdf_pages(raw: bytes) -> int:
    from io import BytesIO

    from pypdf import PdfReader
    try:
        return len(PdfReader(BytesIO(raw)).pages)
    except Exception:
        logger.exception("experiments: the pdf could not be read")
        raise ExperimentsError("UNREADABLE", "The PDF could not be read.") from None


def pdf_text(raw: bytes) -> str:
    from io import BytesIO

    from pypdf import PdfReader
    try:
        reader = PdfReader(BytesIO(raw))
        parts = [(page.extract_text() or "") for page in reader.pages]
    except Exception:
        logger.exception("experiments: the pdf text could not be read")
        return ""
    return "\n".join(parts)[:TEXT_MAX]


def _case_file(name: str, content_type: str, raw: bytes) -> dict[str, Any]:
    if not raw:
        raise ExperimentsError("UNREADABLE", "The file is empty.")
    if len(raw) > CASE_MAX:
        raise ExperimentsError("TOO_BIG", "The file is too big.", 413)
    kind = _kind(name or "case", content_type or "")
    text = ""
    if kind == "pdf":
        if pdf_pages(raw) != 1:
            raise ExperimentsError("ONE_PAGE", "The PDF must be one page.")
        text = pdf_text(raw)
    return {
        "name": (name or "case")[:200],
        "content_type": (content_type or "application/octet-stream")[:120],
        "text": text,
        "raw": raw,
        "ext": ".pdf" if kind == "pdf" else (_ext(name) or ".bin"),
    }


class Storage:
    """Private-bucket reads and writes. Paths stay under one volunteer id."""

    def put(self, path: str, data: bytes, content_type: str) -> None:
        raise NotImplementedError

    def remove(self, paths: list[str]) -> None:
        raise NotImplementedError

    def fetch(self, path: str) -> bytes | None:
        raise NotImplementedError


class SupabaseStorage(Storage):
    def __init__(self, client: Any, bucket: str = BUCKET) -> None:
        self.client = client
        self.bucket = bucket

    def put(self, path: str, data: bytes, content_type: str) -> None:
        self.client.storage.from_(self.bucket).upload(
            path=path, file=data, file_options={"content-type": content_type})

    def remove(self, paths: list[str]) -> None:
        if paths:
            self.client.storage.from_(self.bucket).remove(paths)

    def fetch(self, path: str) -> bytes | None:
        try:
            result = self.client.storage.from_(self.bucket).download(path)
        except Exception:
            logger.exception("experiments: storage fetch failed")
            return None
        if isinstance(result, bytes):
            return result
        return None


def _storage() -> Storage:
    from services.db import db
    return SupabaseStorage(db.client)


def _put(storage: Storage, path: str, data: bytes, content_type: str) -> None:
    try:
        storage.put(path, data, content_type)
    except ExperimentsError:
        raise
    except Exception:
        logger.exception("experiments: storage put failed")
        raise ExperimentsError("STORAGE", "The file could not be stored.", 502) from None


def _drop(storage: Storage, paths: list[str]) -> None:
    try:
        storage.remove([path for path in paths if path])
    except Exception:
        logger.exception("experiments: storage remove failed")
        raise ExperimentsError("STORAGE", "The file could not be removed.", 502) from None


def vocal_measures(raw: bytes, name: str) -> dict[str, float] | None:
    """Loudness of a recording we can decode. None when we cannot.

    librosa's RMS feeds the vocal cells that the prompt set marks baseline.
    A file that does not decode leaves those cells on the placeholder.
    """
    from services.chat_voice import decode
    loaded = decode(raw, name)
    if not loaded:
        return None
    audio, rate = loaded
    try:
        import numpy as np
        import librosa
        frames = librosa.feature.rms(y=np.asarray(audio, dtype=np.float32))
        rms = float(np.mean(frames)) if getattr(frames, "size", 0) else 0.0
    except Exception:
        logger.exception("experiments: vocal measure failed")
        return None
    seconds = float(len(audio) / rate) if rate else 0.0
    return {"rms": rms, "seconds": seconds}


def _session_out(row: dict[str, Any]) -> dict[str, Any]:
    case = None
    if row.get("business_case_name"):
        case = {
            "name": row.get("business_case_name"),
            "content_type": row.get("business_case_type"),
        }
    return {
        "id": row.get("id"),
        "volunteer_id": row.get("volunteer_id"),
        "consent": row.get("consent"),
        "business_case": case,
        "created_at": row.get("created_at"),
    }


def _take_out(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row.get("id"),
        "session_id": row.get("experiment_session_id"),
        "prompt_id": row.get("prompt_id"),
        "tag": row.get("tag"),
        "self_rating": row.get("self_rating"),
        "transcript": row.get("transcript") or "",
        "words": row.get("words") or [],
        "seconds": row.get("seconds") or 0,
        "created_at": row.get("created_at"),
    }


def _prompt_out(row: dict[str, Any]) -> dict[str, Any]:
    out = {
        "id": row.get("prompt_id"),
        "tag": row.get("tag"),
        "text": row.get("text"),
    }
    if row.get("reference"):
        out["reference"] = row.get("reference")
    return out


def create_session(
    database: Any, user_id: str, consent: Any, case: dict[str, Any] | None = None,
    storage: Storage | None = None,
) -> dict[str, Any]:
    kept = _consent(consent)
    volunteer_id = ensure_volunteer(database, user_id)
    session_id = str(uuid.uuid4())
    path = None
    store = storage or _storage()
    if case:
        path = f"{volunteer_id}/{session_id}/business-case{case['ext']}"
        _put(store, path, case["raw"], case["content_type"])
    row = {
        "id": session_id,
        "volunteer_id": volunteer_id,
        "consent": kept,
        "business_case_path": path,
        "business_case_name": case["name"] if case else None,
        "business_case_type": case["content_type"] if case else None,
        "business_case_text": (case["text"] if case else "") or "",
    }
    try:
        made = _data(_table(database, SESSIONS).insert(row).execute())
    except Exception:
        logger.exception("experiments: session insert failed")
        if path:
            try:
                store.remove([path])
            except Exception:
                logger.exception("experiments: session file cleanup failed")
        raise ExperimentsError("STORE", "The session could not be saved.", 502) from None
    if kept["researcher"]:
        _mark_researcher(database, user_id)
    saved = made[0] if made else row
    return _session_out(saved)


def _known_prompt(database: Any, volunteer_id: str, prompt_id: str) -> dict[str, Any]:
    prompt_set = load_prompt_set()
    row = _own_one(database, PROMPTS, volunteer_id, "prompt_id", prompt_id)
    if row:
        return {"id": row["prompt_id"], "tag": row["tag"], "text": row.get("text") or ""}
    found = canonical_prompt(prompt_set, prompt_id)
    if found is None:
        raise ExperimentsError("PROMPT", "That prompt is not in the library.")
    return found


def _words_of(raw: bytes, name: str, user_id: str) -> list[dict[str, Any]]:
    found = transcribe_words(raw, name, user_id) or []
    words: list[dict[str, Any]] = []
    for item in found[:5000]:
        if not isinstance(item, dict):
            continue
        word = str(item.get("word") or "")
        start = item.get("start")
        if not word or isinstance(start, bool) or not isinstance(start, (int, float)):
            continue
        end = item.get("end")
        words.append({
            "word": word,
            "start": float(start),
            "end": float(end) if isinstance(end, (int, float)) and not isinstance(end, bool) else float(start),
        })
    return words


def _audio_mime(content_type: str) -> str:
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    allowed = mime.startswith("audio/") or mime in ("", "application/octet-stream", "video/webm")
    if not allowed:
        raise ExperimentsError("UNREADABLE", "The recording is not audio.")
    return mime or "application/octet-stream"


def _owned_prompt(
    database: Any, user_id: str, session_id: str, prompt_id: str, tag: str,
) -> tuple[str, dict[str, Any]]:
    if tag not in prompt_tags(load_prompt_set()):
        raise ExperimentsError("TAG", "That tag is not in the prompt set.")
    volunteer_id = ensure_volunteer(database, user_id)
    if _own_one(database, SESSIONS, volunteer_id, "id", session_id) is None:
        raise ExperimentsError("NOT_FOUND", "That session is not here.", 404)
    prompt = _known_prompt(database, volunteer_id, str(prompt_id or ""))
    if prompt["tag"] != tag:
        raise ExperimentsError("TAG", "The tag does not match the prompt.")
    return volunteer_id, prompt


def _heard(
    audio: bytes, filename: str, user_id: str,
) -> tuple[list[dict[str, Any]], str, float, dict[str, float] | None]:
    measured = vocal_measures(audio, filename)
    if measured and too_long(float(measured.get("seconds") or 0)):
        raise ExperimentsError("TOO_LONG", "The recording is too long.")
    words = _words_of(audio, filename, user_id)
    transcript = " ".join(str(word["word"]) for word in words).strip()[:TEXT_MAX]
    if measured:
        seconds = float(measured["seconds"])
    elif words:
        seconds = float(words[-1]["end"])
    else:
        seconds = 0.0
    features = {"rms": float(measured["rms"])} if measured and "rms" in measured else None
    return words, transcript, seconds, features


def _insert_take(database: Any, store: Storage, path: str, row: dict[str, Any]) -> dict[str, Any]:
    try:
        made = _data(_table(database, TAKES).insert(row).execute())
    except Exception:
        logger.exception("experiments: take insert failed")
        _drop(store, [path])
        raise ExperimentsError("STORE", "The take could not be saved.", 502) from None
    return _take_out(made[0] if made else row)


def add_take(
    database: Any, user_id: str, session_id: str, *,
    audio: bytes, filename: str, content_type: str,
    prompt_id: str, tag: str, self_rating: Any,
    storage: Storage | None = None,
) -> dict[str, Any]:
    if not audio:
        raise ExperimentsError("UNREADABLE", "The recording is empty.")
    if too_big(audio):
        raise ExperimentsError("TOO_BIG", "The recording is too big.", 413)
    mime = _audio_mime(content_type)
    rating = _rating(self_rating)
    name = filename or "talk.webm"
    volunteer_id, prompt = _owned_prompt(database, user_id, session_id, prompt_id, tag)
    words, transcript, seconds, features = _heard(audio, name, user_id)
    take_id = str(uuid.uuid4())
    path = f"{volunteer_id}/{session_id}/{take_id}-{safe_name(name)}"
    store = storage or _storage()
    _put(store, path, audio, mime)
    return _insert_take(database, store, path, {
        "id": take_id,
        "experiment_session_id": session_id,
        "volunteer_id": volunteer_id,
        "prompt_id": prompt["id"],
        "tag": tag,
        "self_rating": rating,
        "transcript": transcript,
        "words": words,
        "audio_path": path,
        "audio_type": mime,
        "seconds": seconds,
        "features": features,
    })


def request_analysis(
    database: Any, user_id: str, take_id: str, model_id: str | None = None,
) -> dict[str, Any]:
    """Queue analyze-take/v0.1 for one catalog model. The HTTP handler answers 202."""
    from services.experiment_analysis import calm_takes, dispatch
    from services.experiment_models import resolve_model
    model = resolve_model(database, user_id, model_id)
    volunteer_id = ensure_volunteer(database, user_id)
    take = _own_one(database, TAKES, volunteer_id, "id", str(take_id or ""))
    if take is None:
        raise ExperimentsError("NOT_FOUND", "That take is not here.", 404)
    if model.get("needs_baseline") and not calm_takes(
            database, volunteer_id, list(model.get("baseline_prompt_ids") or [])):
        raise ExperimentsError("NO_BASELINE", "Record the calm baseline prompts first.", 409)
    _table(database, TAKES).update({
        "analysis_state": "queued", "analysis_error": None, "model_id": model["id"],
    }).eq("volunteer_id", volunteer_id).eq("id", take["id"]).execute()
    dispatch(str(take["id"]), volunteer_id)
    return {"take_id": take["id"], "status": "queued", "model_id": model["id"]}


def get_analysis(database: Any, user_id: str, take_id: str) -> tuple[str, dict[str, Any]]:
    """``pending`` while the job runs, else the volunteer read of the document."""
    from services.experiment_analysis import for_volunteer
    volunteer_id = ensure_volunteer(database, user_id)
    take = _own_one(database, TAKES, volunteer_id, "id", str(take_id or ""))
    if take is None:
        raise ExperimentsError("NOT_FOUND", "That take is not here.", 404)
    state = take.get("analysis_state")
    if state in ("queued", "running"):
        return "pending", {"take_id": take["id"], "status": state}
    if state == "failed":
        raise ExperimentsError("ANALYSIS_FAILED", "The analysis did not finish.", 502)
    document = take.get("analysis")
    if not isinstance(document, dict) or "takes" not in document:
        raise ExperimentsError("NOT_FOUND", "That analysis is not here.", 404)
    return "ready", for_volunteer(document)


def _clean_prompt(body: Any, *, existing_id: str | None = None) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ExperimentsError("PROMPT", "The prompt does not match the schema.")
    prompt_set = load_prompt_set()
    prompt_id = existing_id if existing_id is not None else body.get("id")
    text = body.get("text")
    tag = body.get("tag")
    if not isinstance(prompt_id, str) or not prompt_id.strip() or len(prompt_id) > 80:
        raise ExperimentsError("PROMPT", "The prompt does not match the schema.")
    if not isinstance(text, str) or not text.strip() or len(text) > 4000:
        raise ExperimentsError("PROMPT", "The prompt does not match the schema.")
    if not isinstance(tag, str) or tag not in prompt_tags(prompt_set):
        raise ExperimentsError("TAG", "That tag is not in the prompt set.")
    row: dict[str, Any] = {"prompt_id": prompt_id.strip(), "tag": tag, "text": text.strip()}
    if "reference" in body and body.get("reference") is not None:
        if body.get("reference") != "business_case":
            raise ExperimentsError("PROMPT", "The prompt does not match the schema.")
        row["reference"] = "business_case"
    else:
        row["reference"] = None
    return row


def list_prompts(database: Any, user_id: str) -> dict[str, Any]:
    volunteer_id = ensure_volunteer(database, user_id)
    rows = _own(database, PROMPTS, volunteer_id)
    rows.sort(key=lambda row: str(row.get("prompt_id") or ""))
    return {"prompts": [_prompt_out(row) for row in rows]}


def create_prompt(database: Any, user_id: str, body: Any) -> dict[str, Any]:
    volunteer_id = ensure_volunteer(database, user_id)
    row = _clean_prompt(body)
    if _own_one(database, PROMPTS, volunteer_id, "prompt_id", row["prompt_id"]):
        raise ExperimentsError("PROMPT", "That prompt id is already in the library.", 409)
    row.update({"volunteer_id": volunteer_id, "updated_at": _now()})
    made = _data(_table(database, PROMPTS).insert(row).execute())
    return _prompt_out(made[0] if made else row)


def update_prompt(database: Any, user_id: str, prompt_id: str, body: Any) -> dict[str, Any]:
    volunteer_id = ensure_volunteer(database, user_id)
    if _own_one(database, PROMPTS, volunteer_id, "prompt_id", prompt_id) is None:
        raise ExperimentsError("NOT_FOUND", "That prompt is not here.", 404)
    row = _clean_prompt(body, existing_id=prompt_id)
    row["updated_at"] = _now()
    made = _data(
        _table(database, PROMPTS).update(row)
        .eq("volunteer_id", volunteer_id).eq("prompt_id", prompt_id).execute())
    return _prompt_out(made[0] if made else {**row, "prompt_id": prompt_id})


def delete_prompt(database: Any, user_id: str, prompt_id: str) -> dict[str, bool]:
    volunteer_id = ensure_volunteer(database, user_id)
    if _own_one(database, PROMPTS, volunteer_id, "prompt_id", prompt_id) is None:
        raise ExperimentsError("NOT_FOUND", "That prompt is not here.", 404)
    _table(database, PROMPTS).delete().eq("volunteer_id", volunteer_id).eq(
        "prompt_id", prompt_id).execute()
    return {"deleted": True}


def import_prompts(database: Any, user_id: str) -> dict[str, Any]:
    """Copy the shipped prompt set into this volunteer's library."""
    volunteer_id = ensure_volunteer(database, user_id)
    saved = []
    for prompt in load_prompt_set()["prompts"]:
        saved.append(create_prompt(database, user_id, prompt) if not _own_one(
            database, PROMPTS, volunteer_id, "prompt_id", prompt["id"])
            else update_prompt(database, user_id, prompt["id"], prompt))
    return {"imported": len(saved), "prompts": saved}


def _unit(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExperimentsError("GRID", "The grid does not match the prompt set.")
    number = float(value)
    if number < -1 or number > 1:
        raise ExperimentsError("GRID", "The grid does not match the prompt set.")
    return number


def _pattern(body: Any) -> dict[str, dict[str, float]]:
    prompt_set = load_prompt_set()
    order = set(prompt_set["order"])
    if not isinstance(body, dict) or not body:
        raise ExperimentsError("GRID", "The grid does not match the prompt set.")
    pattern: dict[str, dict[str, float]] = {}
    for dimension, cells in body.items():
        if dimension not in order or not isinstance(cells, dict) or not cells:
            raise ExperimentsError("GRID", "The grid does not match the prompt set.")
        cleaned: dict[str, float] = {}
        for channel, value in cells.items():
            if channel not in CHANNELS:
                raise ExperimentsError("GRID", "The grid does not match the prompt set.")
            cleaned[channel] = _unit(value)
        pattern[dimension] = cleaned
    return pattern


def _rule(body: Any, pattern: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ExperimentsError("RULE", "The rule must be an object.")
    order = list(load_prompt_set()["order"])
    step = body.get("step")
    if step is not None and (not isinstance(step, str) or step not in order):
        raise ExperimentsError("RULE", "The rule's step is not in the prompt set order.")
    if step is None and step_missing(body, pattern, order):
        raise ExperimentsError("RULE", "The rule's step is not in the prompt set order.")
    return body


def step_missing(rule: dict[str, Any], pattern: dict[str, Any], order: list[str]) -> bool:
    return step_of(rule, pattern, order) is None


def _intervention_out(row: dict[str, Any]) -> dict[str, Any]:
    order = list(load_prompt_set()["order"])
    raw_grid = row.get("grid")
    pattern: dict[str, Any] = raw_grid if isinstance(raw_grid, dict) else {}
    return {
        "id": row.get("id"),
        "grid": pattern,
        "threshold": row.get("threshold"),
        "rule": row.get("rule"),
        "step": step_of(row.get("rule"), pattern, order),
        "updated_at": row.get("updated_at"),
    }


def _threshold(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ExperimentsError("RULE", "The threshold must be between 0 and 2.")
    number = float(value)
    if number < 0 or number > 2:
        raise ExperimentsError("RULE", "The threshold must be between 0 and 2.")
    return number


def list_interventions(database: Any, user_id: str) -> dict[str, Any]:
    volunteer_id = ensure_volunteer(database, user_id)
    rows = _own(database, INTERVENTIONS, volunteer_id)
    rows.sort(key=lambda row: str(row.get("created_at") or ""))
    return {"interventions": [_intervention_out(row) for row in rows]}


def create_intervention(database: Any, user_id: str, body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ExperimentsError("RULE", "The rule must be an object.")
    pattern = _pattern(body.get("grid"))
    rule = _rule(body.get("rule"), pattern)
    volunteer_id = ensure_volunteer(database, user_id)
    row = {
        "id": str(uuid.uuid4()),
        "volunteer_id": volunteer_id,
        "grid": pattern,
        "threshold": _threshold(body.get("threshold")),
        "rule": rule,
        "updated_at": _now(),
    }
    made = _data(_table(database, INTERVENTIONS).insert(row).execute())
    return _intervention_out(made[0] if made else row)


def update_intervention(
    database: Any, user_id: str, intervention_id: str, body: Any,
) -> dict[str, Any]:
    volunteer_id = ensure_volunteer(database, user_id)
    current = _own_one(database, INTERVENTIONS, volunteer_id, "id", intervention_id)
    if current is None:
        raise ExperimentsError("NOT_FOUND", "That intervention is not here.", 404)
    if not isinstance(body, dict):
        raise ExperimentsError("RULE", "The rule must be an object.")
    pattern = _pattern(body.get("grid", current.get("grid")))
    rule = _rule(body.get("rule", current.get("rule")), pattern)
    changed = {
        "grid": pattern,
        "threshold": _threshold(body.get("threshold", current.get("threshold"))),
        "rule": rule,
        "updated_at": _now(),
    }
    made = _data(
        _table(database, INTERVENTIONS).update(changed)
        .eq("volunteer_id", volunteer_id).eq("id", intervention_id).execute())
    return _intervention_out(made[0] if made else {**current, **changed})


def delete_intervention(database: Any, user_id: str, intervention_id: str) -> dict[str, bool]:
    volunteer_id = ensure_volunteer(database, user_id)
    if _own_one(database, INTERVENTIONS, volunteer_id, "id", intervention_id) is None:
        raise ExperimentsError("NOT_FOUND", "That intervention is not here.", 404)
    _table(database, INTERVENTIONS).delete().eq("volunteer_id", volunteer_id).eq(
        "id", intervention_id).execute()
    return {"deleted": True}


def coaching_context(database: Any, user_id: str, moment: dict[str, Any]) -> dict[str, Any]:
    """A block the coaching chat can take as context. It does not call the chat.

    ``moment`` is one analyze moment: start, end, and grid. At most two
    interventions come back, the earlier step in the prompt set's order first.
    """
    prompt_set = load_prompt_set()
    order = list(prompt_set["order"])
    volunteer_id = ensure_volunteer(database, user_id)
    grid = moment.get("grid") if isinstance(moment, dict) else None
    if not isinstance(grid, dict):
        raise ExperimentsError("GRID", "The grid does not match the prompt set.")
    rows = _own(database, INTERVENTIONS, volunteer_id)
    return {
        "source": "experiments",
        "order": order,
        "moment": {
            "start": moment.get("start"),
            "end": moment.get("end"),
            "grid": grid,
        },
        "fired": rank_interventions(rows, grid, order),
    }


def _paths(database: Any, volunteer_id: str) -> list[str]:
    paths = []
    for row in _own(database, SESSIONS, volunteer_id):
        if row.get("business_case_path"):
            paths.append(str(row["business_case_path"]))
    for row in _own(database, TAKES, volunteer_id):
        if row.get("audio_path"):
            paths.append(str(row["audio_path"]))
    return paths


def erase(database: Any, user_id: str, storage: Storage | None = None) -> dict[str, bool]:
    """Delete this caller's experiment rows and the files those rows name."""
    rows = _data(
        _table(database, KEYS).select("volunteer_id")
        .eq("user_id", user_id).limit(1).execute())
    volunteer_id = str(rows[0]["volunteer_id"]) if rows else volunteer_id_for(user_id)
    store = storage or _storage()
    _drop(store, _paths(database, volunteer_id))
    for name in (TAKES, PROMPTS, INTERVENTIONS, SESSIONS,
                 "experiment_volunteer_baselines", "experiment_models"):
        _table(database, name).delete().eq("volunteer_id", volunteer_id).execute()
    _table(database, KEYS).delete().eq("user_id", user_id).execute()
    return {"deleted": True}


def _csv_cell(value: Any) -> str:
    text = "" if value is None else str(value)
    if text[:1] in ("=", "+", "-", "@"):
        return "'" + text
    return text


def _export_rows(database: Any, volunteer_id: str) -> dict[str, Any]:
    sessions = [_session_out(row) | {
        "business_case_text": row.get("business_case_text") or "",
    } for row in _own(database, SESSIONS, volunteer_id)]
    takes = []
    for row in _own(database, TAKES, volunteer_id):
        item = _take_out(row)
        item["has_audio"] = bool(row.get("audio_path"))
        item["analysis"] = row.get("analysis")
        item["analysis_state"] = row.get("analysis_state")
        takes.append(item)
    return {
        "volunteer_id": volunteer_id,
        "sessions": sessions,
        "takes": takes,
        "prompts": [_prompt_out(row) for row in _own(database, PROMPTS, volunteer_id)],
        "interventions": [
            _intervention_out(row) for row in _own(database, INTERVENTIONS, volunteer_id)],
    }


def export_data(
    database: Any, user_id: str, fmt: str, audience: str,
) -> tuple[str, dict[str, Any] | str]:
    """The caller's own rows. ``researcher`` still returns only those rows."""
    if fmt not in ("json", "csv"):
        raise ExperimentsError("FORMAT", "format must be csv or json.")
    if audience not in ("self", "researcher"):
        raise ExperimentsError("FORMAT", "audience must be self or researcher.")
    volunteer_id = ensure_volunteer(database, user_id)
    if audience == "researcher" and not _researcher(database, user_id):
        raise ExperimentsError(
            "RESEARCHER_CONSENT_REQUIRED",
            "Researcher export needs the researcher's consent.", 403)
    bundle = _export_rows(database, volunteer_id)
    bundle["audience"] = audience
    if audience == "self":
        from services.experiment_analysis import for_volunteer
        for row in bundle.get("takes") or []:
            if isinstance(row.get("analysis"), dict) and "takes" in row["analysis"]:
                row["analysis"] = for_volunteer(row["analysis"])
    if fmt == "json":
        return "json", bundle
    return "csv", _csv(bundle)


def _csv(bundle: dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "record", "id", "session_id", "tag", "prompt_id", "transcript",
        "rating", "audience", "volunteer_id",
    ])
    volunteer_id = bundle.get("volunteer_id")
    audience = bundle.get("audience")
    for row in bundle.get("sessions") or []:
        writer.writerow([
            _csv_cell("session"), _csv_cell(row.get("id")), "", "", "",
            _csv_cell(row.get("business_case_text")), "", _csv_cell(audience),
            _csv_cell(volunteer_id),
        ])
    for row in bundle.get("takes") or []:
        writer.writerow([
            _csv_cell("take"), _csv_cell(row.get("id")), _csv_cell(row.get("session_id")),
            _csv_cell(row.get("tag")), _csv_cell(row.get("prompt_id")),
            _csv_cell(row.get("transcript")), _csv_cell(row.get("self_rating")),
            _csv_cell(audience), _csv_cell(volunteer_id),
        ])
    for row in bundle.get("prompts") or []:
        writer.writerow([
            _csv_cell("prompt"), _csv_cell(row.get("id")), "", _csv_cell(row.get("tag")),
            _csv_cell(row.get("id")), _csv_cell(row.get("text")), "",
            _csv_cell(audience), _csv_cell(volunteer_id),
        ])
    return buffer.getvalue()
