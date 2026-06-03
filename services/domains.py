"""willab beta — domain enum + vocabulary seed (design §2, contract §1).

Single source of truth for the five intake domains and their Whisper-
priming vocabulary seeds. Imported by both the profile store (the
domain enum on `user_settings`) and the per-recording `session_context`
(whose `domain_vocabulary` defaults from the profile domain's seed,
then is editable per recording).

Domain is METADATA, never a flow fork (design §0/§2): no branch in
prompts, content, or KPI keys off it. Keep the enum keys STABLE — the
coach packet + session_context reference them.
"""
from __future__ import annotations

from typing import Any


# The five intake domains. Enum KEY is the stored contract; the FE
# renders the human label. Bounded to exactly five (design §2 — do
# not add/substitute without a design change).
VALID_DOMAINS: tuple[str, ...] = (
    "public_speaking",
    "sales",
    "executive_presence",
    "customer_service",
    "interview_prep",
)


# Vocabulary seed per domain (design §2 table). Lands as the default
# `session_context.domain_vocabulary` and primes Whisper; the user can
# edit it per recording. Short, domain-characteristic terms — the
# words a transcriber is most likely to fumble without priming.
DOMAIN_VOCABULARY_SEED: dict[str, tuple[str, ...]] = {
    "public_speaking": (
        "keynote", "slide", "audience", "podium", "Q&A", "pacing",
    ),
    "sales": (
        "pipeline", "objection", "close", "discovery call", "pitch", "quota",
    ),
    "executive_presence": (
        "board", "stakeholder", "all-hands", "gravitas", "brief", "alignment",
    ),
    "customer_service": (
        "ticket", "escalation", "resolution", "caller", "SLA", "de-escalate",
    ),
    "interview_prep": (
        "recruiter", "behavioral question", "STAR", "panel", "role", "offer",
    ),
}


def is_valid_domain(value: Any) -> bool:
    """True iff ``value`` is one of the five canonical domain keys."""
    return isinstance(value, str) and value in VALID_DOMAINS


def default_domain_vocabulary(domain: Any) -> list[str]:
    """Return the editable default vocabulary list for a domain.

    Empty list for an unknown/None domain — the caller (session_context
    creation) then leaves `domain_vocabulary` unset and the pipeline
    falls back to un-primed Whisper, which is the correct degradation
    for a user who never picked a domain.
    """
    if not is_valid_domain(domain):
        return []
    return list(DOMAIN_VOCABULARY_SEED[domain])
