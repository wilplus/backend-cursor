import base64
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

import httpx

from config import Config

logger = logging.getLogger(__name__)
config = Config()

COACH_FEEDBACK_VIDEO_BUCKET = "coach_feedback_videos"


def resolve_script_mode(payload: Dict[str, Any]) -> str:
    mode = str(payload.get("script_mode") or "").strip().lower()
    if mode in ("ai_only", "ai_edited", "full_video_override"):
        return mode
    if (payload.get("full_override_video_url") or payload.get("full_override_video_storage_path")):
        return "full_video_override"
    ai_script = str(payload.get("ai_script_draft") or "").strip()
    current_script = str(payload.get("script_draft") or payload.get("video_script") or "").strip()
    if ai_script and current_script and ai_script != current_script:
        return "ai_edited"
    return "ai_only"


def build_script_manifest(row: Dict[str, Any], payload: Dict[str, Any], script_mode: str) -> Dict[str, Any]:
    ai_script = str(payload.get("ai_script_draft") or row.get("ai_draft_video_script") or "").strip()
    final_script = str(payload.get("script_draft") or payload.get("video_script") or ai_script).strip()
    universal_blocks = payload.get("universal_blocks")
    personalized_blocks = payload.get("personalized_blocks")
    coach_override_blocks = payload.get("coach_override_blocks")
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    return {
        "version": "v1",
        "script_mode": script_mode,
        "resolved_script_text": final_script or None,
        "sections": {
            "ai_original": ai_script or None,
            "final_script": final_script or None,
            "override_video_url": payload.get("full_override_video_url"),
            "override_video_storage_path": payload.get("full_override_video_storage_path"),
        },
        "blocks": {
            "universal_blocks": universal_blocks if isinstance(universal_blocks, list) else [],
            "personalized_blocks": personalized_blocks if isinstance(personalized_blocks, list) else [],
            "coach_override_blocks": coach_override_blocks if isinstance(coach_override_blocks, list) else [],
        },
        "metadata": metadata,
    }


def extract_script_text_from_manifest(script_manifest: Dict[str, Any]) -> str:
    sections = script_manifest.get("sections") if isinstance(script_manifest, dict) else {}
    if not isinstance(sections, dict):
        return ""
    return str(sections.get("final_script") or "").strip()


def parse_reference_tags(payload: Dict[str, Any]) -> List[str]:
    raw = payload.get("reference_tags")
    if isinstance(raw, str):
        return [x.strip() for x in raw.split(",") if x and x.strip()]
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    return []


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def build_feedback_video_storage_path(user_id: str, session_id: Optional[str] = None) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    safe_session = str(session_id or "no-session").strip() or "no-session"
    return f"{user_id}_{safe_session}_{ts}_{uuid4().hex[:8]}.mp4"


def _download_binary_from_url(url: str, *, timeout: int = 120) -> bytes:
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content


def fetch_override_video_bytes(script_manifest: Dict[str, Any]) -> bytes:
    sections = script_manifest.get("sections") if isinstance(script_manifest, dict) else {}
    if not isinstance(sections, dict):
        raise ValueError("script_manifest.sections is required for full_video_override")
    override_url = str(sections.get("override_video_url") or "").strip()
    if not override_url:
        override_storage_path = str(sections.get("override_video_storage_path") or "").strip()
        if not override_storage_path:
            raise ValueError("full_video_override requires sections.override_video_url or sections.override_video_storage_path")
        bucket = config.COACH_FEEDBACK_VIDEO_BUCKET
        path = override_storage_path
        if override_storage_path.startswith("storage://"):
            raw = override_storage_path[len("storage://") :]
            first = raw.split("/", 1)
            if len(first) != 2:
                raise ValueError("Invalid storage URI for override video")
            bucket, path = first[0], first[1]
        from services.db import db
        return db.download_audio(bucket, path)
    return _download_binary_from_url(override_url, timeout=180)


def _extract_binary_or_remote(payload: Dict[str, Any], *, url_key: str, base64_key: str) -> bytes:
    if not isinstance(payload, dict):
        raise ValueError("Invalid provider response payload")
    direct_url = str(payload.get(url_key) or "").strip()
    if direct_url:
        return _download_binary_from_url(direct_url, timeout=180)
    b64 = str(payload.get(base64_key) or "").strip()
    if b64:
        return base64.b64decode(b64)
    raise ValueError(f"Provider response missing {url_key} or {base64_key}")


def generate_audio_bytes_metavoice(script_text: str) -> bytes:
    endpoint = (getattr(config, "METAVOICE_API_URL", None) or "").strip()
    api_key = (getattr(config, "METAVOICE_API_KEY", None) or "").strip()
    voice_id = (getattr(config, "METAVOICE_VOICE_ID", None) or "").strip()
    output_format = (getattr(config, "METAVOICE_OUTPUT_FORMAT", None) or "wav").strip()
    if not endpoint or not api_key or not voice_id:
        raise ValueError("METAVOICE_API_URL, METAVOICE_API_KEY, METAVOICE_VOICE_ID are required")
    if not script_text.strip():
        raise ValueError("Script text is empty")

    req = {"text": script_text, "voice_id": voice_id, "format": output_format, "quality": "high"}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    with httpx.Client(timeout=240) as client:
        resp = client.post(endpoint, json=req, headers=headers)
        resp.raise_for_status()
        ctype = (resp.headers.get("content-type") or "").lower()
        if "audio/" in ctype or "application/octet-stream" in ctype:
            return resp.content
        payload = resp.json()
        return _extract_binary_or_remote(payload, url_key="audio_url", base64_key="audio_base64")


def generate_lipsync_video_bytes(audio_bytes: bytes, avatar_url: Optional[str] = None) -> bytes:
    endpoint = (getattr(config, "BYTEDANCE_API_URL", None) or "").strip()
    api_key = (getattr(config, "BYTEDANCE_API_KEY", None) or "").strip()
    avatar = (avatar_url or getattr(config, "ARTUR_BASE_AVATAR_URL", None) or "").strip()
    if not endpoint or not api_key or not avatar:
        raise ValueError("BYTEDANCE_API_URL, BYTEDANCE_API_KEY, ARTUR_BASE_AVATAR_URL are required")
    if not audio_bytes:
        raise ValueError("Audio bytes are empty")

    files = {"audio": ("audio.wav", audio_bytes, "audio/wav")}
    data = {"avatar_url": avatar}
    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(timeout=600) as client:
        resp = client.post(endpoint, data=data, files=files, headers=headers)
        resp.raise_for_status()
        ctype = (resp.headers.get("content-type") or "").lower()
        if "video/" in ctype or "application/octet-stream" in ctype:
            return resp.content
        payload = resp.json()
        return _extract_binary_or_remote(payload, url_key="video_url", base64_key="video_base64")


def generate_video_from_script(script_manifest: Dict[str, Any]) -> bytes:
    script_text = extract_script_text_from_manifest(script_manifest)
    if not script_text:
        raise ValueError("script_manifest resolved_script_text/final_script is empty")
    audio = generate_audio_bytes_metavoice(script_text)
    return generate_lipsync_video_bytes(audio, avatar_url=None)
