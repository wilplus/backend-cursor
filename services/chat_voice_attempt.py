"""Prepare a chat recording and measure the clip the speaker decides to send."""
from __future__ import annotations

from hashlib import sha256
import logging
import math
from uuid import uuid4

from itsdangerous import BadData, URLSafeSerializer

from config import Config
from services.speaking_coach_passages import delivery_description
from utils.ids import is_uuid

log = logging.getLogger(__name__)
_MAX_RECEIPT_SIZE = 100_000


def _signer() -> URLSafeSerializer | None:
    secret = Config.SUPABASE_JWT_SECRET or Config.SUPABASE_SERVICE_ROLE_KEY
    if not secret:
        return None
    return URLSafeSerializer(secret, salt="willpowerlab-chat-voice-attempt-v2")


def _words(items: object) -> list[dict]:
    words: list[dict] = []
    if not isinstance(items, list):
        return words
    for item in items[:2000]:
        if not isinstance(item, dict):
            continue
        word, start, end = item.get("word") or item.get("text"), item.get("start"), item.get("end")
        if (isinstance(word, str) and word.strip()
                and isinstance(start, (int, float)) and isinstance(end, (int, float))
                and not isinstance(start, bool) and not isinstance(end, bool)
                and math.isfinite(start) and math.isfinite(end) and 0 <= start < end):
            words.append({"word": word[:100], "start": start, "end": end})
    return words


def hear(adapter, audio: bytes, *, user: str, filename: str, duration: int | None,
         turn: str | None, project: str | None = None, take: str | None = None,
         snippet: str | None = None) -> dict:
    from services.will_question import hear_answer_transcription

    adapter.authorization.require_current(adapter.coordinates.acquisition_principal_id, operation="recording")
    text, duration_ms, transcript = hear_answer_transcription(
        adapter, audio, user_id=user, take=take or str(uuid4()), filename=filename, duration_ms=duration)
    response = {"text": text, "duration_ms": duration_ms}
    signer = _signer() if turn and is_uuid(turn) else None
    if signer is not None:
        response["voice_receipt"] = signer.dumps({
            "user": user, "turn": turn, "project": project, "take": take, "snippet": snippet,
            "audio_hash": sha256(audio).hexdigest(),
            "transcript": text, "duration_ms": duration_ms, "language": transcript.get("language"),
            "words": _words(transcript.get("words")),
        })
    return response


def receipt_payload(raw: object) -> dict | None:
    signer = _signer()
    if signer is None or not isinstance(raw, str) or len(raw) > _MAX_RECEIPT_SIZE:
        return None
    try:
        payload = signer.loads(raw)
    except BadData:
        return None
    return payload if isinstance(payload, dict) else None


def _measure(audio: bytes, transcript: str) -> dict:
    from services.audio_metrics import SAMPLE_RATE, analyze_pcm_window, decode_audio_to_pcm
    from services.plan_flow import MIN_VOICED_SEC

    try:
        pcm = decode_audio_to_pcm(audio)
        if pcm is None:
            return {}
        metrics = analyze_pcm_window(
            pcm, start_offset_ms=0, duration_ms=math.ceil(len(pcm) * 1000 / SAMPLE_RATE),
            transcript=transcript, include_librosa=False,
        ) or {}
        return metrics if metrics.get("voiced_duration_sec", 0) >= MIN_VOICED_SEC else {}
    except (OSError, ValueError, RuntimeError) as error:
        log.warning("chat voice measurement unavailable: %s", type(error).__name__)
        return {}


def analyze(database, user: str, audio: bytes, receipt: dict) -> dict:
    """Keep the Take's measurements private and preserve the original spoken words."""
    from services import verbal_cues, voice_confidence
    from services.content_language import resolve_content_language
    from services.transcript_smoothing import count_fillers

    transcript = receipt["transcript"]
    language = resolve_content_language(recording_language=receipt.get("language"), typed_message=transcript)
    metrics = _measure(audio, transcript)
    if metrics and voice_confidence.enabled():
        baseline, kind = voice_confidence.resolve_confidence_baseline(user, [], database=database)
        voice_confidence.attach_voice_confidence([{"metrics": metrics}], baseline=baseline, baseline_kind=kind)
    # Word timings and hesitations come from this note's transcription. The
    # final chat message can be edited independently before the note is sent.
    return {
        "transcript": transcript, "duration_ms": receipt.get("duration_ms"), "language": language,
        "verbal_cues": {
            "words": receipt["words"], "hesitations": count_fillers(transcript, language),
            "private_measurements": verbal_cues.measure(transcript, language),
        },
        "metrics": metrics,
        "delivery": delivery_description({"metrics": metrics}),
    }
