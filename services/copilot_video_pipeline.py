import base64
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

import httpx

from config import Config

logger = logging.getLogger(__name__)
config = Config()

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


def _is_private_ip(hostname: str) -> bool:
    """Reject private/reserved IPs to prevent SSRF."""
    import ipaddress
    import socket
    try:
        infos = socket.getaddrinfo(hostname, None, socket.AF_UNSPEC, socket.SOCK_STREAM)
    except socket.gaierror:
        return True  # unresolvable → block
    for _family, _type, _proto, _canonname, sockaddr in infos:
        ip = ipaddress.ip_address(sockaddr[0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            return True
    return False


def _download_binary_from_url(url: str, *, timeout: int = 120) -> bytes:
    from urllib.parse import urlparse
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        raise ValueError("URL has no hostname")
    blocked_hosts = {"localhost", "metadata.google.internal"}
    if hostname in blocked_hosts or hostname.endswith(".internal"):
        raise ValueError(f"Blocked hostname: {hostname}")
    if _is_private_ip(hostname):
        raise ValueError(f"URL resolves to a private/reserved IP: {hostname}")
    with httpx.Client(timeout=timeout, follow_redirects=True) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.content


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
