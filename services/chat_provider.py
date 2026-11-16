"""Provider selection for stateless text chat completions.

OpenAI remains the default.  A Mistral target is selected only when all of
the following are true:

* the surface is explicitly named in ``MISTRAL_TEXT_SURFACES``;
* the surface is still using the stock cheap model; and
* callers use the shared ``services.llm.chat_complete`` boundary.

Strong-model work, promoted/fine-tuned models, and audio transcription are
therefore unaffected.  Missing Mistral configuration does not silently send
the request to OpenAI: the client is unavailable and the caller's existing
safe fallback runs instead.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from config import Config
from services.llm_config import CHEAP_MODEL


@dataclass(frozen=True)
class ChatTarget:
    provider: str
    model: str
    base_url: Optional[str] = None


def resolve_chat_target(
    surface: str,
    resolved_model: str,
    *,
    config: Any = Config,
) -> ChatTarget:
    """Return the provider/model target for one already-gated model call."""
    allowed = frozenset(getattr(config, "MISTRAL_TEXT_SURFACES", ()) or ())
    if str(surface) in allowed and str(resolved_model) == CHEAP_MODEL:
        return ChatTarget(
            provider="mistral",
            model=str(getattr(config, "MISTRAL_MODEL", None) or "").strip(),
            base_url=(
                str(getattr(config, "MISTRAL_BASE_URL", None) or "").strip()
                or "https://api.mistral.ai/v1"
            ),
        )
    return ChatTarget(provider="openai", model=str(resolved_model))


def build_chat_client(target: ChatTarget, *, config: Any = Config) -> Optional[Any]:
    """Build the OpenAI-compatible client for ``target``, or ``None``.

    The OpenAI SDK is only the transport for Mistral's compatible Chat
    Completions endpoint.  Provider identity remains ``mistral`` in permits,
    logs, and usage records.
    """
    if target.provider == "mistral":
        key = str(getattr(config, "MISTRAL_API_KEY", None) or "").strip()
        if not key or not target.model or not target.base_url:
            return None
        base_url = target.base_url
    else:
        key = str(getattr(config, "OPENAI_API_KEY", None) or "").strip()
        if not key:
            return None
        base_url = None

    from services.llm_client import build_openai_client

    return build_openai_client(
        key,
        timeout=float(getattr(config, "OPENAI_TIMEOUT_SECONDS", 120.0)),
        max_retries=int(getattr(config, "OPENAI_MAX_RETRIES", 2)),
        base_url=base_url,
    )
