"""Secret resolution + a boot-time audit of what we're actually holding.

WHAT THIS IS, AND WHAT IT ISN'T
-------------------------------
It is NOT a secrets manager. Choosing one — Doppler, Infisical, AWS
Secrets Manager, or staying on Railway's own encrypted variables — is an
ops and billing decision, and the runbook lays out the trade-offs
(docs/OPS-SECRETS-AND-STAGING.md). This module is the seam that makes
that choice a config change instead of a code change, plus the check that
tells us when a secret is missing, fake, or shared across environments.

Three capabilities:

1. ``resolve(name)`` — indirection for a single secret.
   Reads, in order:
     ``<NAME>_FILE``  → path to a file holding the value. This is the
                        idiom every managed secret store speaks (Docker
                        secrets, Kubernetes projected volumes, Vault
                        Agent, AWS Secrets Manager's CSI driver). A file
                        beats an env var because it never lands in
                        ``/proc/<pid>/environ``, a crash dump, or a
                        subprocess that inherits the environment.
     ``<NAME>``       → the plain env var (today's path, unchanged).

2. ``audit()`` — what are we actually running with?
   Flags missing required secrets, obvious placeholders that leaked from
   a copied .env, and values too short to be a real credential.

3. ``enforce_at_boot()`` — refuse to serve production with a fake secret.
   A placeholder JWT secret in production is not a warning-level event;
   it means tokens can be forged. It crashes the process instead.

WHY NOT JUST READ os.getenv EVERYWHERE
--------------------------------------
config.py has ~200 os.getenv calls, and rewriting all of them would be a
large, risky diff for no behavioural gain. Secrets go through here;
everything else (flags, limits, URLs) stays exactly as it is. The seam
lives where the sensitive values are.
"""
from __future__ import annotations

import logging
import os
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

# Secrets whose absence is a real failure in production, with the minimum
# plausible length of a genuine value. Anything shorter is a truncation,
# a placeholder, or a copy-paste accident.
_REQUIRED_IN_PRODUCTION: dict[str, int] = {
    "SUPABASE_URL": 12,
    "SUPABASE_SERVICE_ROLE_KEY": 40,
    "OPENAI_API_KEY": 20,
}

# Optional, but if SET they must look real — a truncated key fails at the
# worst moment (mid-request, mid-charge) rather than at boot.
_OPTIONAL_MIN_LENGTHS: dict[str, int] = {
    "SUPABASE_JWT_SECRET": 20,
    "JWT_SECRET": 20,
    "STRIPE_SECRET_KEY": 20,
    "STRIPE_WEBHOOK_SECRET": 20,
    "RESEND_API_KEY": 20,
    "R2_ACCESS_KEY_ID": 16,
    "R2_SECRET_ACCESS_KEY": 32,
    "SENTRY_DSN": 20,
    "REDIS_URL": 12,
}

# Substrings that mean "this was never filled in". Matched case-insensitively
# against the whole value; these are the strings our own .env.example, CI
# workflow and docs use, so they're the ones that actually leak.
_PLACEHOLDER_MARKERS = (
    "ci-placeholder",
    "placeholder",
    "changeme",
    "change-me",
    "your-key",
    "your_key",
    "yourkey",
    "xxxxx",
    "todo",
    "replace-me",
    "replaceme",
    "dummy",
    "example.com/secret",
    "<your",
)


def resolve(name: str, default: Optional[str] = None) -> Optional[str]:
    """Resolve one secret: ``<NAME>_FILE`` first, then ``<NAME>``.

    Whitespace is stripped (a trailing newline from ``echo >`` or a
    mounted file is the classic silent auth failure), as are wrapping
    quotes — the same defensive handling config.py already applies to
    OPENAI_API_KEY, now available to every secret.
    """
    path = (os.getenv(f"{name}_FILE") or "").strip()
    if path:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return _clean(fh.read())
        except Exception as exc:
            # Do NOT fall through silently to the env var: if an operator
            # pointed us at a file, reading a stale env value instead is
            # how the wrong credential gets used without anyone noticing.
            logger.error(
                "secrets: %s_FILE is set but unreadable (%s) — refusing the "
                "env fallback for %s", name, type(exc).__name__, name,
            )
            return None
    raw = os.getenv(name)
    return _clean(raw) if raw is not None else default


def _clean(value: str) -> str:
    return (value or "").strip().strip('"').strip("'").strip()


def looks_like_placeholder(value: Optional[str]) -> bool:
    """True when the value is obviously not a real credential."""
    if not value:
        return False
    low = value.strip().lower()
    return any(marker in low for marker in _PLACEHOLDER_MARKERS)


def _env_name() -> str:
    return (os.getenv("ENV", "development") or "development").strip().lower()


def audit(*, env: Optional[str] = None) -> dict:
    """Inspect the secrets this process is holding.

    Returns ``{"env", "errors": [...], "warnings": [...], "checked": n}``.
    NEVER includes a secret VALUE — findings name the variable only, so
    the result is safe to log, to return from an admin endpoint, and to
    paste into a ticket.
    """
    env = (env or _env_name()).lower()
    is_prod = env in ("production", "prod")
    errors: list[str] = []
    warnings: list[str] = []
    checked = 0

    def _check(name: str, min_len: int, required: bool) -> None:
        nonlocal checked
        checked += 1
        value = resolve(name)
        if not value:
            if required and is_prod:
                errors.append(f"{name} is not set")
            elif required:
                warnings.append(f"{name} is not set")
            return
        if looks_like_placeholder(value):
            msg = f"{name} looks like a placeholder, not a real credential"
            (errors if is_prod else warnings).append(msg)
            return
        if len(value) < min_len:
            msg = (f"{name} is {len(value)} chars — shorter than a real "
                   f"value ({min_len}+); likely truncated")
            (errors if is_prod else warnings).append(msg)

    for name, min_len in _REQUIRED_IN_PRODUCTION.items():
        _check(name, min_len, required=True)
    for name, min_len in _OPTIONAL_MIN_LENGTHS.items():
        if resolve(name):
            _check(name, min_len, required=False)

    # ── Staging blast-radius checks ──────────────────────────────────────
    # A staging environment exists to be run against carelessly. These are
    # the three ways that turns into a production incident.
    if env == "staging":
        # 1. Pointed at the production database — the classic way a "safe
        #    place to test" deletes real user data.
        supa = (resolve("SUPABASE_URL") or "").lower()
        prod_marker = (os.getenv("PRODUCTION_SUPABASE_URL") or "").strip().lower()
        if prod_marker and supa and supa == prod_marker:
            errors.append(
                "SUPABASE_URL matches PRODUCTION_SUPABASE_URL — staging is "
                "pointed at the production database"
            )
        # 2. A LIVE Stripe key in staging bills real cards from test runs.
        if (resolve("STRIPE_SECRET_KEY") or "").startswith("sk_live_"):
            errors.append(
                "STRIPE_SECRET_KEY is a LIVE key — staging must use sk_test_"
            )
        # 3. Real email with no redirect: staging mirrors prod's user
        #    table, so a digest run reaches real students from a box
        #    nobody is watching. Config.EMAIL_REDIRECT_TO is the fix.
        sends_email = (os.getenv("SEND_EMAILS", "false") or "").strip().lower() \
            == "true"
        if sends_email and not (os.getenv("EMAIL_REDIRECT_TO") or "").strip():
            errors.append(
                "SEND_EMAILS=true with no EMAIL_REDIRECT_TO — staging would "
                "email real users"
            )

    return {"env": env, "errors": errors, "warnings": warnings,
            "checked": checked}


def enforce_at_boot(*, strict: Optional[bool] = None) -> dict:
    """Run the audit at import time; crash production on an error finding.

    ``strict`` defaults to production AND staging. A placeholder
    credential in production is not something to warn about and continue
    past — a fake JWT secret means forgeable tokens, and a fake Supabase
    key means the app runs with whatever access that key happens to
    carry. Failing to boot is the safe outcome; the deploy rolls back to
    the last good release and the live loop keeps serving.

    Staging is strict for the opposite reason: its findings are all
    blast-radius errors (prod database, live Stripe key, un-redirected
    email). A staging box that boots anyway is more dangerous than one
    that doesn't, because people trust it to be harmless.

    Development only logs, so a developer without a full .env can still
    run the app.
    """
    result = audit()
    if strict is None:
        strict = result["env"] in ("production", "prod", "staging")

    for w in result["warnings"]:
        logger.warning("secrets audit: %s", w)
    for e in result["errors"]:
        logger.error("secrets audit: %s", e)

    if result["errors"] and strict:
        raise RuntimeError(
            "Refusing to start: secret configuration is invalid — "
            + "; ".join(result["errors"])
        )
    if not result["errors"] and not result["warnings"]:
        logger.info("secrets audit: %d secret(s) OK (env=%s)",
                    result["checked"], result["env"])
    return result


def redact(value: Optional[str], *, keep: int = 4) -> str:
    """Render a secret for a log line: ``sk-…a91f`` (last 4 only).

    For confirming WHICH key is loaded without printing it. Values too
    short to partially reveal are fully masked.
    """
    if not value:
        return "<unset>"
    v = value.strip()
    if len(v) <= keep * 2:
        return "*" * len(v)
    return f"{v[:2]}…{v[-keep:]}"


def missing(names: Iterable[str]) -> list[str]:
    """Which of ``names`` resolve to nothing. For feature preflights."""
    return [n for n in names if not resolve(n)]
