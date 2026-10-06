"""The verified account identity a speaker is bound by (MLC-2 F-3).

A speaker (``ml_speakers``) is the stable person the 80/10/10 split is
assigned to; an acquisition principal is the account or guest the data came
through. They are bound only by an authenticated act of the person (the
foundation's rule), never inferred. Since 2026-10-05 that act is the
training yes (founder, decisions log N48.5 Q27 A): the training switch binds
the speaker in the same transaction as the yes (0430,
``accept_mlc2_training_consent_v1``).

The coordinates are computed on the server from the verified token, never
sent by a browser: the identity is the token's issuer and subject, the proof
adds the verified email. It is the same construction the retired bundled
route used, so a person bound there and here is one speaker.
"""
from __future__ import annotations

import hashlib
from typing import Any, Mapping

IDENTITY_VERSION = "supabase-auth-sub-v1"
BOUND_BY = "authenticated-training-consent-v1"


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def identity_coordinates(token_payload: Mapping[str, Any] | None,
                         user_id: str) -> tuple[str, str]:
    """``(identity_hash, binding_proof_hash)`` for the verified subject."""
    payload = token_payload or {}
    issuer = str(payload.get("iss") or "supabase").strip()
    subject = str(payload.get("sub") or user_id).strip()
    identity = _sha256(f"{IDENTITY_VERSION}:{issuer}:{subject}")
    proof = _sha256(
        "verified-account-link-v1:"
        f"{issuer}:{subject}:{str(payload.get('email') or '').strip().lower()}"
    )
    return identity, proof
