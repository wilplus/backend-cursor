"""The speaker's one AI voice: made once from a Take, reused, deletable
(founder lock 2026-10-12, A4 and D8; N71).

  after_take   called when a spoken Take finishes processing. When the
               speaker may use the AI voice and has none yet, one clone job
               is queued. It never slows the Take: the job runs on its own.
  run_clone    the job. Claims the clone row (so two workers never make two),
               reads the Take's audio through the permit, keeps up to 150 s
               of it, refuses a Take too short or too noisy (the next Take
               tries again), and makes one Instant Voice Clone.
  delete       the Data & consent card's Delete: the clone at ElevenLabs
               first, then here; safe to repeat; a provider failure is
               reported, never hidden.
  turn_on      the card's Turn on: the next Take makes the voice again.

The provider's voice id stays in ``ai_voice_clones`` and is never returned
to a client, written to a log, or put in a permit manifest.
"""
from __future__ import annotations

import logging
import subprocess
import time
from typing import Any, Optional

from config import Config
from services import ai_voice_store as store

_log = logging.getLogger(__name__)

SAMPLE_MAX_S = 150
SAMPLE_MIN_VOICED_S = 30
#: The loud end of the Take must stand this far above its quiet end, or the
#: room is too loud to make a clean voice from (D8).
SAMPLE_MIN_RANGE_DB = 15.0


def available_to(user_id: Any) -> bool:
    """On for every speaker whenever the ElevenLabs key is set (founder
    2026-10-12: always on, for everyone). A non-empty AI_VOICE_ALLOWLIST
    narrows it; AI_VOICE_ENABLED=0 is only an emergency off."""
    if not Config.AI_VOICE_ENABLED or not Config.ELEVENLABS_API_KEY or not user_id:
        return False
    allow = Config.AI_VOICE_ALLOWLIST
    return not allow or str(user_id) in allow


def voice_for(database: Any, owner_user_id: str) -> Optional[str]:
    """The ready, enabled voice id for a speaker, or None."""
    row = store.get_clone(database, owner_user_id)
    if row and row.get("enabled", True) and row.get("status") == "ready":
        return str(row.get("provider_voice_id") or "") or None
    return None


def after_take(database: Any, *, user_id: Any, principal_id: str, take_id: str,
               recording_id: str, storage: dict) -> bool:
    """Queue one clone job if this speaker needs one. Never raises."""
    try:
        if not available_to(user_id):
            return False
        row = store.get_clone(database, str(user_id))
        if row and (not row.get("enabled", True)
                    or row.get("status") in ("creating", "ready", "deleting")):
            return False
        args = (str(user_id), principal_id, take_id, recording_id,
                str(storage.get("storage_provider") or ""),
                str(storage.get("bucket") or ""), str(storage.get("storage_key") or ""))
        from services.job_queue import enqueue
        if enqueue("services.ai_voice_clone.run_clone", *args,
                   rq_job_id=f"ai-voice-clone-{user_id}-{take_id}"):
            return True
        import threading
        threading.Thread(target=run_clone, args=args, daemon=True,
                         name="ai-voice-clone").start()
        return True
    except Exception as error:  # noqa: BLE001 — the Take's loop never waits on this
        _log.warning("ai voice: clone not queued take=%s: %s",
                     take_id, type(error).__name__, exc_info=True)
        return False


def after_take_job(database: Any, payload: dict, principal_id: str) -> bool:
    """The Take pipeline's one call: a spoken Take may make the voice."""
    if payload.get("recording_kind") != "spoken":
        return False
    return after_take(database, user_id=payload.get("user_id"), principal_id=principal_id,
                      take_id=str(payload.get("session_id") or ""),
                      recording_id=str(payload.get("recording_id") or ""),
                      storage=payload)


def _ffmpeg() -> Optional[str]:
    from services.audio_metrics import _resolve_ffmpeg_executable
    return _resolve_ffmpeg_executable()


def prepare_sample(audio: bytes, *, decode=None, transcode=None) -> tuple[Optional[bytes], str]:
    """(mp3 bytes, "") or (None, reason): ``too_short`` · ``too_noisy`` ·
    ``undecodable``. Keeps the first SAMPLE_MAX_S seconds."""
    import numpy as np
    if decode is None:
        from services.audio_metrics import decode_audio_to_pcm as decode
    pcm = decode(audio)
    if pcm is None or len(pcm) == 0:
        return None, "undecodable"
    pcm = pcm[: 16000 * SAMPLE_MAX_S]
    frame = 320
    usable = len(pcm) - len(pcm) % frame
    if usable <= 0:
        return None, "too_short"
    frames = pcm[:usable].reshape(-1, frame)
    dbs = 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)
    voiced_s = float((dbs > -45).sum()) * 0.02
    if voiced_s < SAMPLE_MIN_VOICED_S:
        return None, "too_short"
    if float(np.percentile(dbs, 90) - np.percentile(dbs, 10)) < SAMPLE_MIN_RANGE_DB:
        return None, "too_noisy"
    sample = (transcode or _transcode)(audio)
    return (sample, "") if sample else (None, "undecodable")


def _transcode(audio: bytes) -> Optional[bytes]:
    exe = _ffmpeg()
    if not exe:
        return None
    proc = subprocess.run(
        [exe, "-i", "pipe:0", "-t", str(SAMPLE_MAX_S), "-ac", "1", "-ar", "44100",
         "-b:a", "192k", "-f", "mp3", "pipe:1"],
        input=audio, capture_output=True, timeout=60)
    return proc.stdout if proc.returncode == 0 and proc.stdout else None


def _voice_provider(database: Any, principal_id: str, take_id: str,
                    recording_id: Optional[str]):
    from services.authorized_provider import ProviderCoordinates
    from services.authorized_voice_provider import AuthorizedVoiceProvider
    return AuthorizedVoiceProvider(database, ProviderCoordinates(
        acquisition_principal_id=principal_id, take_id=take_id or None,
        recording_id=recording_id or None))


def run_clone(user_id: str, principal_id: str, take_id: str, recording_id: str,
              storage_provider: str, bucket: str, storage_key: str,
              *, database: Any = None, provider: Any = None,
              read_audio=None, prepare=prepare_sample) -> str:
    """The clone job; returns its end state (for logs and tests)."""
    if database is None:
        from services.db import db as database
    if not available_to(user_id):
        return "not_available"
    from services.ai_voice_limits import clone_refusal
    refused = clone_refusal(database)
    if refused:
        return refused
    if not store.claim_clone_creation(database, user_id):
        return "already_claimed"
    started = time.monotonic()
    try:
        if read_audio is None:
            from services.authorized_provider import (
                AuthorizedProviderAdapter, ProviderCoordinates)
            adapter = AuthorizedProviderAdapter(database, ProviderCoordinates(
                principal_id, take_id or None, recording_id or None))
            audio = adapter.download_audio(
                storage_provider=storage_provider, bucket=bucket,
                object_key=storage_key,
                idempotency_key=f"ai-voice-sample:{take_id}:{int(time.time())}")
        else:
            audio = read_audio()
        sample, reason = prepare(audio)
        if sample is None:
            store.save_clone(database, user_id, {
                "status": "none", "failure_kind": reason, "source_take_id": take_id})
            return reason
        voices = provider or _voice_provider(database, principal_id, take_id, recording_id)
        voice_id = voices.create_voice(owner_key=str(user_id), sample=sample,
                                       filename="take-sample.mp3",
                                       content_type="audio/mpeg")
        store.save_clone(database, user_id, {
            "status": "ready", "provider_voice_id": voice_id,
            "source_take_id": take_id, "failure_kind": None,
            "ready_at": store._now()})
        _log.info("ai voice: clone ready take=%s in %d ms", take_id,
                  int((time.monotonic() - started) * 1000))
        return "ready"
    except Exception as error:  # noqa: BLE001 — recorded, retried on the next Take
        kind = str(getattr(error, "kind", "") or type(error).__name__)
        store.save_clone(database, user_id, {"status": "failed", "failure_kind": kind[:60]})
        _log.warning("ai voice: clone failed take=%s: %s", take_id, kind, exc_info=True)
        return "failed"


def delete(database: Any, user_id: str, *, principal_id: str = "",
           provider: Any = None, delete_clip_objects=None) -> dict:
    """Delete the AI voice and every clip made from it; turn it off.

    Safe to repeat. Returns ``{"state": "off"}`` when everything is gone,
    or ``{"state": "deleting", "error": kind}`` when the provider could not
    confirm, so the card can say it isn't finished yet."""
    row = store.get_clone(database, user_id) or {}
    voice_id = str(row.get("provider_voice_id") or "")
    store.save_clone(database, user_id, {"enabled": False, "status": "deleting"})
    from services.ai_voice_clip import erase_clips
    if erase_clips(database, user_id, delete_object=delete_clip_objects):
        return {"state": "deleting", "error": "storage"}
    if voice_id:
        try:
            voices = provider or _voice_provider(database, principal_id, "", None)
            voices.delete_voice(owner_key=str(user_id), voice_id=voice_id)
        except Exception as error:  # noqa: BLE001 — visible, and retried by the next Delete
            kind = str(getattr(error, "kind", "") or type(error).__name__)
            _log.warning("ai voice: provider delete not confirmed: %s", kind, exc_info=True)
            return {"state": "deleting", "error": kind}
    store.save_clone(database, user_id, {
        "status": "deleted", "provider_voice_id": None, "enabled": False,
        "deleted_at": store._now()})
    return {"state": "off"}


def turn_on(database: Any, user_id: str) -> dict:
    row = store.get_clone(database, user_id) or {}
    if row.get("status") == "deleting":
        return {"state": "deleting"}
    store.save_clone(database, user_id, {
        "enabled": True,
        "status": "ready" if row.get("status") == "ready" else "none"})
    return {"state": "on"}


def card_state(database: Any, user_id: str) -> dict:
    """What the Data & consent card shows: on or off (and nothing else)."""
    row = store.get_clone(database, user_id)
    if row and row.get("status") == "deleting":
        return {"available": True, "state": "deleting"}
    on = not row or bool(row.get("enabled", True))
    return {"available": True, "state": "on" if on else "off"}


def erase_on_termination(database: Any, user_id: Any, principal_id: str) -> None:
    """Account deletion or service termination: the AI voice and its clips
    go at once (they are made from the speaker's voice). Never raises; an
    unfinished delete stays 'deleting' and is retried by the card's Delete
    and by the next termination request."""
    if not user_id:
        return
    try:
        if store.get_clone(database, str(user_id)) or store.owner_cycles(
                database, str(user_id), limit=1):
            result = delete(database, str(user_id), principal_id=principal_id)
            if result.get("state") != "off":
                _log.warning("ai voice: termination delete not finished: %s",
                             result.get("error"))
    except Exception as error:  # noqa: BLE001 — never blocks the deletion request
        _log.warning("ai voice: termination delete failed: %s", type(error).__name__,
                     exc_info=True)
