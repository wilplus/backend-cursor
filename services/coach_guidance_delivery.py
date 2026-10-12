"""Coach-guidance and practice pilot boundary.

The released D3 foundation remains dark by default.  The product loop has a
separate two-part gate (global switch plus an exact user/principal allowlist),
while dataset, training, evaluation and promotion are intentionally absent
from this module.  In other words, enabling this service can expose an
exercise, but can never make its evidence learning-eligible.
"""
from __future__ import annotations

from hashlib import sha256


def runtime_is_enabled() -> bool:
    """Return the rollout-aware backend gate; disabled is the default.

    Founder-pilot environment values are deliberately ignored here. Exact
    principal access is decided by the database enrollment resolver.
    """
    from config import Config

    return bool(Config.MLC3_SERVICE_ENABLED)


def principal_is_allowlisted(*, principal_id: str | None) -> bool:
    """Compatibility name for the presentation gate only.

    Database enrollment remains authoritative. This helper cannot authorize a
    principal and intentionally ignores the retired environment allowlist.
    """
    return bool(runtime_is_enabled() and principal_id)


def exact_bytes_sha256(body: bytes) -> str:
    """Fingerprint exact media bytes; this is not a speaker identifier."""
    return sha256(body).hexdigest()

