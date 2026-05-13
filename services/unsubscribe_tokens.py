"""Signed unsubscribe tokens (HS256 JWT).

Phase 14 of the email rollout. Each publish-results email carries a
unsubscribe footer link that points at /unsubscribe?token=<...>; the
token is a short-lived signed JWT whose only job is to prove the
user actually owns the inbox we sent to. The unsubscribe endpoint
decodes the token, flips ``user_settings.email_pref_publish_results``
to FALSE, and the publish path skips future sends.

Why a dedicated secret (not the auth JWT secret)
-----------------------------------------------
Different blast radius. The auth JWT secret signs session cookies —
if it leaks, every user is compromised. The unsubscribe secret only
lets an attacker unsubscribe other users (annoying, not catastrophic)
and can be rotated independently. The token claims include an
``aud`` field pinned to the flow (e.g. ``unsubscribe-publish-
results``) so a token minted for one flow can't be reused for
another.

Token shape
-----------
    {
      "sub": "<user_id_uuid>",
      "aud": "unsubscribe-publish-results",
      "iat": <unix seconds>,
      "exp": <unix seconds, default iat + 30 days>
    }

Functions
---------
  generate_unsubscribe_token(user_id, audience=..., ttl_days=30) → token str
  verify_unsubscribe_token(token, audience=...) → user_id str

verify raises specific exceptions the route layer maps to HTTP
statuses:
  UnsubscribeTokenError       — base class
  UnsubscribeTokenInvalid     — signature / shape / audience wrong (401)
  UnsubscribeTokenExpired     — past exp (401)
  UnsubscribeTokenNotConfigured — UNSUBSCRIBE_TOKEN_SECRET unset (503)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import jwt


logger = logging.getLogger(__name__)


# Default audience for the publish-results unsubscribe flow. Other
# email categories can use their own audience claim so a token from
# this flow can never unsubscribe the user from a different list.
DEFAULT_AUDIENCE = "unsubscribe-publish-results"

# 30 days matches the link's reasonable click-window. Long enough
# that a user who opens the email a few weeks later can still
# unsubscribe; short enough that a leaked token from old archives
# doesn't stay weaponised forever.
DEFAULT_TTL_DAYS = 30

_ALG = "HS256"


class UnsubscribeTokenError(Exception):
    """Base class for unsubscribe-token verification failures."""


class UnsubscribeTokenInvalid(UnsubscribeTokenError):
    """Bad signature, malformed token, or audience mismatch."""


class UnsubscribeTokenExpired(UnsubscribeTokenError):
    """Token's exp claim is in the past."""


class UnsubscribeTokenNotConfigured(UnsubscribeTokenError):
    """UNSUBSCRIBE_TOKEN_SECRET is empty — generation / verification can't run."""


def _secret() -> str:
    """Read the secret from config at call time so env changes during
    a process lifetime (rare) still apply without a restart-of-imports
    dance. Raises UnsubscribeTokenNotConfigured when unset so the
    caller can return 503 with a clear code instead of a 500."""
    from config import Config
    secret = (Config.UNSUBSCRIBE_TOKEN_SECRET or "").strip()
    if not secret:
        raise UnsubscribeTokenNotConfigured(
            "UNSUBSCRIBE_TOKEN_SECRET env var is not set"
        )
    return secret


def generate_unsubscribe_token(
    user_id: str,
    *,
    audience: str = DEFAULT_AUDIENCE,
    ttl_days: int = DEFAULT_TTL_DAYS,
) -> str:
    """Mint a fresh unsubscribe token for ``user_id``.

    Raises UnsubscribeTokenNotConfigured when the secret is empty —
    callers higher up the email path should skip the unsubscribe
    link and log loudly rather than send an email with a broken
    link.
    """
    if not user_id:
        raise UnsubscribeTokenError("user_id required")
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "aud": audience,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(days=ttl_days)).timestamp()),
    }
    return jwt.encode(payload, _secret(), algorithm=_ALG)


def verify_unsubscribe_token(
    token: str,
    *,
    audience: str = DEFAULT_AUDIENCE,
) -> str:
    """Validate ``token`` and return the user_id from its sub claim.

    Order of validation:
      1. Secret configured (else UnsubscribeTokenNotConfigured)
      2. Signature, exp, and audience (PyJWT enforces all three)
      3. sub claim present and non-empty

    Distinct exception types are raised per failure mode so the
    route layer can map directly to the documented HTTP codes
    (401 for INVALID_TOKEN regardless of which sub-reason; 503 for
    SERVICE_UNAVAILABLE when the secret is unset).
    """
    if not token or not isinstance(token, str):
        raise UnsubscribeTokenInvalid("token is empty")
    secret = _secret()
    try:
        decoded = jwt.decode(
            token,
            secret,
            algorithms=[_ALG],
            audience=audience,
        )
    except jwt.ExpiredSignatureError as e:
        raise UnsubscribeTokenExpired(str(e)) from e
    except jwt.InvalidAudienceError as e:
        raise UnsubscribeTokenInvalid(f"audience mismatch: {e}") from e
    except jwt.InvalidTokenError as e:
        raise UnsubscribeTokenInvalid(str(e)) from e

    user_id = (decoded.get("sub") or "").strip()
    if not user_id:
        raise UnsubscribeTokenInvalid("token missing sub claim")
    return user_id
