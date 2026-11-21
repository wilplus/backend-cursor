"""Run wpl_arousal off the request.

POST /v2/experiments/analyze-take queues this and answers 202. The model
document is stored on the take. The read the volunteer gets has
``score_if_unlocked`` removed; the stored document keeps it.

The package is imported only when a job runs or when WPL_AROUSAL_WARMUP=1.
Tests and the web image do not download the models. The live-loop
requirements file does not install this package: librosa 1.0.1 conflicts
with the pinned 0.10.2 stack. A separate worker does.

Research and internal testing only. nEMO is CC BY-NC-SA. Not for paid use.
"""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

from services.experiments_config import baseline_tags, load_prompt_set

logger = logging.getLogger(__name__)

BASELINES = "experiment_volunteer_baselines"
TAKES = "experiment_takes"
SESSIONS = "experiment_sessions"
_WAV_EXT = {".wav", ".flac", ".ogg"}
_LOCK = threading.Lock()


def warmup_enabled() -> bool:
    return (os.getenv("WPL_AROUSAL_WARMUP") or "").strip().lower() in ("1", "true", "yes")


def maybe_warmup() -> None:
    """Load the models once in this process, only when the flag is on."""
    if not warmup_enabled():
        return
    _model().warmup()


def _model() -> Any:
    import wpl_arousal
    return wpl_arousal


def _data(result: Any) -> list[dict[str, Any]]:
    rows = getattr(result, "data", None)
    if isinstance(rows, dict):
        return [rows]
    if isinstance(rows, list):
        return [row for row in rows if isinstance(row, dict)]
    return []


def _db() -> Any:
    from services.db import db
    return db


def _mark(volunteer_id: str, take_id: str, state: str, *, analysis: Any = None, error: str | None = None) -> None:
    payload: dict[str, Any] = {"analysis_state": state, "analysis_error": error}
    if analysis is not None or state == "ready":
        payload["analysis"] = analysis
    _db().client.table(TAKES).update(payload).eq("volunteer_id", volunteer_id).eq("id", take_id).execute()


def calm_prompt_ids() -> list[str]:
    """The baseline_calm prompt ids in the shipped set (b1, b2, b3)."""
    prompt_set = load_prompt_set()
    tags = baseline_tags(prompt_set)
    return [str(prompt["id"]) for prompt in prompt_set["prompts"] if prompt["tag"] in tags]


def calm_takes(database: Any, volunteer_id: str) -> list[dict[str, Any]]:
    wanted = set(calm_prompt_ids())
    tags = baseline_tags(load_prompt_set())
    rows = _data(database.client.table(TAKES).select("*").eq("volunteer_id", volunteer_id).execute())
    found = [
        row for row in rows
        if row.get("tag") in tags and row.get("prompt_id") in wanted and row.get("audio_path")
    ]
    found.sort(key=lambda row: str(row.get("prompt_id") or ""))
    return found


def _source_ids(rows: list[dict[str, Any]]) -> list[str]:
    return sorted(str(row.get("id") or "") for row in rows)


def _stored_baseline(database: Any, volunteer_id: str) -> dict[str, Any] | None:
    rows = _data(
        database.client.table(BASELINES).select("baseline,source_take_ids")
        .eq("volunteer_id", volunteer_id).limit(1).execute())
    return rows[0] if rows else None


def to_wav(raw: bytes, name: str, dest: Path) -> str:
    """wav/flac/ogg pass through. Browser webm/opus becomes 24 kHz mono wav."""
    suffix = Path(name or "").suffix.lower()
    if suffix not in _WAV_EXT and suffix not in {".webm", ".m4a", ".mp3", ".mp4", ".bin"}:
        suffix = ".bin"
    src = dest.parent / f"{dest.stem}-in{suffix}"
    src.write_bytes(raw)
    if suffix in _WAV_EXT:
        return str(src)
    from services.audio_metrics import _resolve_ffmpeg_executable
    exe = _resolve_ffmpeg_executable()
    if not exe:
        raise RuntimeError("ffmpeg missing")
    subprocess.run(
        [exe, "-nostdin", "-loglevel", "error", "-y", "-i", str(src),
         "-ac", "1", "-ar", "24000", str(dest)],
        check=True, timeout=60,
    )
    return str(dest)


def _audio(storage: Any, row: dict[str, Any], folder: Path) -> str:
    raw = storage.fetch(str(row.get("audio_path") or ""))
    if not raw:
        raise RuntimeError("audio missing")
    name = Path(str(row.get("audio_path") or "talk.webm")).name
    return to_wav(raw, name, folder / f"{row['id']}.wav")


def _save_baseline(database: Any, volunteer_id: str, baseline: dict[str, Any], source_ids: list[str]) -> None:
    row = {"volunteer_id": volunteer_id, "baseline": baseline, "source_take_ids": source_ids}
    existing = _stored_baseline(database, volunteer_id)
    table = database.client.table(BASELINES)
    if existing:
        table.update(row).eq("volunteer_id", volunteer_id).execute()
    else:
        table.insert(row).execute()


def ensure_baseline(database: Any, volunteer_id: str, storage: Any, folder: Path) -> dict[str, Any]:
    """The stored baseline, rebuilt when the calm takes changed."""
    rows = calm_takes(database, volunteer_id)
    if not rows:
        raise RuntimeError("no baseline")
    source_ids = _source_ids(rows)
    stored = _stored_baseline(database, volunteer_id)
    if stored and list(stored.get("source_take_ids") or []) == source_ids and isinstance(stored.get("baseline"), dict):
        return stored["baseline"]
    paths = [_audio(storage, row, folder) for row in rows]
    with _LOCK:
        baseline = _model().build_baseline(paths, volunteer_id=volunteer_id)
    if not isinstance(baseline, dict):
        raise RuntimeError("baseline")
    _save_baseline(database, volunteer_id, baseline, source_ids)
    return baseline


def _session_text(database: Any, volunteer_id: str, session_id: str) -> str:
    rows = _data(
        database.client.table(SESSIONS).select("business_case_text")
        .eq("volunteer_id", volunteer_id).eq("id", session_id).limit(1).execute())
    text = str((rows[0].get("business_case_text") if rows else "") or "").strip()
    return text


def run(take_id: str, volunteer_id: str) -> None:
    """One take. Called by the queue worker, a thread, or the test inline path."""
    database = _db()
    _mark(volunteer_id, take_id, "running")
    try:
        from services.experiments import _storage
        rows = _data(
            database.client.table(TAKES).select("*")
            .eq("volunteer_id", volunteer_id).eq("id", take_id).limit(1).execute())
        if not rows:
            _mark(volunteer_id, take_id, "failed", error="NOT_FOUND")
            return
        take = rows[0]
        storage = _storage()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            baseline = ensure_baseline(database, volunteer_id, storage, root)
            path = _audio(storage, take, root)
            case = _session_text(database, volunteer_id, str(take.get("experiment_session_id") or ""))
            with _LOCK:
                document = _model().analyze_take(
                    path,
                    transcript=str(take.get("transcript") or "") or None,
                    baseline=baseline,
                    business_case=case or None,
                    take_id=str(take["id"]),
                    prompt_tag=str(take.get("tag") or "") or None,
                )
        if not isinstance(document, dict):
            _mark(volunteer_id, take_id, "failed", error="ANALYSIS_FAILED")
            return
        _mark(volunteer_id, take_id, "ready", analysis=document)
    except Exception:
        logger.exception("experiments: analysis failed")
        _mark(volunteer_id, take_id, "failed", error="ANALYSIS_FAILED")


def dispatch(take_id: str, volunteer_id: str) -> str:
    """Queue on the experiments queue. A thread is the fallback. Never the pipeline queue."""
    from services import job_queue
    queue = (os.getenv("WPL_AROUSAL_QUEUE") or "experiments").strip() or "experiments"
    if job_queue.enqueue("services.experiment_analysis.run", take_id, volunteer_id, queue=queue):
        return "queue"
    if (os.getenv("WPL_AROUSAL_INLINE") or "").strip().lower() in ("1", "true", "yes"):
        run(take_id, volunteer_id)
        return "inline"
    threading.Thread(target=run, args=(take_id, volunteer_id), daemon=True).start()
    return "thread"


def for_volunteer(document: dict[str, Any]) -> dict[str, Any]:
    """The UI read. Locked research scores stay in the stored document only."""
    import copy
    shown = copy.deepcopy(document)
    shown.pop("provisional", None)
    for take in shown.get("takes") or []:
        if not isinstance(take, dict):
            continue
        summary = take.get("summary")
        if not isinstance(summary, dict):
            continue
        for step in summary.values():
            if isinstance(step, dict):
                step.pop("score_if_unlocked", None)
                step.pop("note", None)
                step.pop("provisional", None)
    return shown
