"""The speaker's intake profile (POST /v2/user/profile, design §3.1):
domain, goal and the languages they understand. Non-recording.

Moved out of ``routes.v2.user_account`` unchanged (founder 2026-10-12). All
fields are optional so a partial intake is accepted; `domain` (when present)
is one of the five enum keys and `goal` is trimmed, ≤500 chars, empty→null.
Stored on user_settings, distinct from the admin-authored speaker profiles.
Domain is metadata, never a flow fork.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from services.refusal import Refusal

logger = logging.getLogger(__name__)

GOAL_MAX_LEN = 500
_DOMAINS = ("domain: must be one of public_speaking, sales, "
            "executive_presence, customer_service, interview_prep")


def _invalid(error: str) -> Refusal:
    return Refusal("INVALID_INPUT", error, 422)


def _domain(body: dict) -> Optional[str]:
    from services.domains import is_valid_domain
    raw = body.get("domain")
    if raw is None:
        return None
    if not is_valid_domain(raw):
        raise _invalid(_DOMAINS)
    return raw


def _goal(body: dict) -> Optional[str]:
    raw = body.get("goal")
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise _invalid("goal: must be a string")
    cleaned = raw.strip()
    if not cleaned:
        return None
    if len(cleaned) > GOAL_MAX_LEN:
        raise _invalid(f"goal: must be {GOAL_MAX_LEN} characters or fewer")
    return cleaned


def _languages(body: dict) -> Any:
    from services.rater_languages import validate_proficient_languages
    languages, error = validate_proficient_languages(
        body.get("proficient_languages"))
    if error:
        raise _invalid(error)
    return languages


def _not_saved() -> Refusal:
    return Refusal("V2_ERROR", "Failed to persist profile", 500)


def save_profile(database, user_id: Any, body: Any) -> dict:
    """Validate and store what the body carries, read back the rest; the
    response body (the GET's shape). Raises ``Refusal``."""
    from services.domains import default_domain_vocabulary
    if not isinstance(body, dict):
        raise _invalid("Body must be a JSON object")
    domain, goal = _domain(body), _goal(body)
    languages_present = "proficient_languages" in body
    languages = _languages(body) if languages_present else None
    # {domain, goal} is a full set: only write it when the body carries one
    # of them, otherwise an unrelated partial post would null the intake.
    if "domain" in body or "goal" in body:
        if not database.set_user_profile(user_id, domain=domain, goal=goal):
            raise _not_saved()
    else:
        stored = database.get_user_profile(user_id) or {}
        domain, goal = stored.get("domain"), stored.get("goal")
    if languages_present:
        if not database.set_user_proficient_languages(user_id, languages or []):
            raise _not_saved()
    else:
        languages = database.get_user_proficient_languages(user_id)
    logger.info(
        "user/profile.set user=%s domain=%s goal_len=%d rater_languages_set=%s",
        user_id, domain or "-", len(goal or ""), languages_present)
    return {
        "domain": domain,
        "goal": goal,
        "proficient_languages": languages,
        "domain_vocabulary_default": default_domain_vocabulary(domain),
    }
