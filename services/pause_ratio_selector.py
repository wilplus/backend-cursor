from typing import Callable


def select_pause_ratio(
    audio_bytes: bytes,
    pause_ratio_from_client,
    audio_extractor: Callable[[bytes], float | None],
) -> tuple[float, str]:
    """
    Select pause ratio in explicit priority order:
    1) audio-derived
    2) request value
    3) neutral fallback 0.5
    Returns (value, source) where source in {"audio", "request", "neutral"}.
    """
    pause_ratio_from_audio = audio_extractor(audio_bytes)
    if pause_ratio_from_audio is not None:
        return float(pause_ratio_from_audio), "audio"
    if pause_ratio_from_client is not None:
        try:
            return float(pause_ratio_from_client), "request"
        except (TypeError, ValueError):
            pass
    return 0.5, "neutral"
