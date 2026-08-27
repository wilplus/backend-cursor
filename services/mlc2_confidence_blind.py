"""Strict answer-free payload validation for Slice-4 blind confidence work."""
from __future__ import annotations

from typing import Any, Mapping
from uuid import UUID

from services.mlc2_foundation import Mlc2ContractError


PACKET_VERSION = "confidence-blind-packet-v1"
RATING_CHOICES = (
    "rating_yes",
    "rating_in_between",
    "rating_no",
    "rating_not_sure",
    "rating_audio_unclear",
)

_TOP_LEVEL = frozenset({"packet_version", "clip", "taxonomy"})
_CLIP_FIELDS = frozenset({
    "clip_id", "audio_object_id", "audio_sha256", "start_ms", "end_ms",
})
_TAXONOMY_FIELDS = frozenset({"version", "choices"})
_FORBIDDEN_ANYWHERE = frozenset({
    "transcript", "text", "exact_text", "score", "rank", "threshold",
    "model", "prediction", "selection_reason", "sampling_probability",
    "rng", "user_label", "coach_label", "peer_label", "judgment",
})


def _walk_keys(value: Any) -> set[str]:
    if isinstance(value, Mapping):
        keys = {str(key).lower() for key in value}
        for nested in value.values():
            keys.update(_walk_keys(nested))
        return keys
    if isinstance(value, list):
        nested_keys: set[str] = set()
        for nested in value:
            nested_keys.update(_walk_keys(nested))
        return nested_keys
    return set()


def validate_blind_packet(value: Any) -> dict[str, Any]:
    """Return a detached exact-allowlist packet or fail closed."""
    if not isinstance(value, Mapping) or set(value) != _TOP_LEVEL:
        raise Mlc2ContractError("blind packet top-level allowlist mismatch")
    packet = dict(value)
    if packet.get("packet_version") != PACKET_VERSION:
        raise Mlc2ContractError("unknown blind packet version")
    clip = packet.get("clip")
    taxonomy = packet.get("taxonomy")
    if not isinstance(clip, Mapping) or set(clip) != _CLIP_FIELDS:
        raise Mlc2ContractError("blind packet clip allowlist mismatch")
    if not isinstance(taxonomy, Mapping) or set(taxonomy) != _TAXONOMY_FIELDS:
        raise Mlc2ContractError("blind packet taxonomy allowlist mismatch")
    if tuple(taxonomy.get("choices") or ()) != RATING_CHOICES:
        raise Mlc2ContractError("blind packet requires the five-state taxonomy")
    if not str(taxonomy.get("version") or "").strip():
        raise Mlc2ContractError("blind packet taxonomy version is required")
    try:
        UUID(str(clip.get("clip_id")))
        UUID(str(clip.get("audio_object_id")))
    except (TypeError, ValueError, AttributeError) as error:
        raise Mlc2ContractError("blind packet clip identity is invalid") from error
    audio_sha256 = str(clip.get("audio_sha256") or "").lower()
    if len(audio_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in audio_sha256):
        raise Mlc2ContractError("blind packet audio checksum is invalid")
    start, end = clip.get("start_ms"), clip.get("end_ms")
    if isinstance(start, bool) or not isinstance(start, int) or start < 0 \
            or isinstance(end, bool) or not isinstance(end, int) or end <= start:
        raise Mlc2ContractError("blind packet audio coordinates are invalid")
    keys = _walk_keys(packet)
    if keys.intersection(_FORBIDDEN_ANYWHERE):
        raise Mlc2ContractError("blind packet contains answer or selection hints")
    # Detach the nested values without importing JSON model semantics.
    return {
        "packet_version": PACKET_VERSION,
        "clip": dict(clip),
        "taxonomy": {
            "version": str(taxonomy.get("version") or ""),
            "choices": list(RATING_CHOICES),
        },
    }
