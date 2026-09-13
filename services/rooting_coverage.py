"""Rooting coverage policy and exact-clause extraction (Chunk 3).

Pure application logic only. No database access, no scores surfaced to users,
no learning surface, no automatic qualification label.

Implements the closed lexicographic routing and 30/80/100 progressive coverage
from Contract Delta D3 §7–§8 and Interface Manifest D6 §4.2 / §5.3.

All gates remain disabled by default; this module never enables them.
"""
from __future__ import annotations

import hashlib
import math
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

# Closed policy version strings (D6 §2)
ROOTING_COVERAGE_POLICY_VERSION = "rooting-coverage-30-80-100-v1"
ROOT_EXACT_CLAUSE_VERSION = "root-exact-clause-v1"
ROOT_LEXICOGRAPHIC_ROUTING_VERSION = "root-lexicographic-routing-v1"

CoverageItemState = Literal[
    "covered_existing_owner_lock",
    "covered_automatic_root",
    "covered_owner_selected",
    "eligible_automatic_proposal",
    "eligible_owner_proposal",
    "pending_rerecord",
    "uncovered_no_aligned_clause",
    "uncovered_owner_declined",
    "excluded_unusable_source",
    "invalidated",
]


@dataclass(frozen=True)
class ExactClause:
    """One contiguous exact transcript span. Words are never rewritten."""

    text: str
    start_token_index: int
    end_token_index: int  # exclusive
    normalized_word_count: int
    span_sha256: str


@dataclass(frozen=True)
class CoverageTarget:
    take_ordinal: int
    slide_count: int
    target_count: int
    policy_version: str = ROOTING_COVERAGE_POLICY_VERSION


def _normalize_words(text: str) -> list[str]:
    """Tokenize on whitespace after stripping; preserve original order."""
    return [t for t in re.split(r"\s+", (text or "").strip()) if t]


def extract_exact_clauses(
    transcript: str,
    *,
    prefer_min_words: int = 5,
    prefer_max_words: int = 20,
) -> list[ExactClause]:
    """Extract maximal contiguous exact clauses ending at canonical punctuation.

    Rules (D3 §8 / D6):
    - Prefer complete clauses of 5–20 normalized words.
    - When none exist, retain the shortest non-empty complete span.
    - Never rewrite words.
    - Ties: fewer tokens, earlier start, earlier end, then lowercase SHA-256.
    """
    if not transcript or not transcript.strip():
        return []

    token_matches = list(re.finditer(r"\S+", transcript))
    if not token_matches:
        return []

    # Rebuild a simple token stream and find punctuation boundaries.
    # We treat the following as clause terminators when they appear as
    # separate tokens or as trailing characters of a token.
    terminators = {".", "?", "!", ";", ":"}

    clauses: list[ExactClause] = []
    start = 0
    i = 0
    while i < len(token_matches):
        tok = token_matches[i].group(0)
        # Check trailing punctuation
        ends = False
        for t in terminators:
            if tok.endswith(t) and len(tok) > 1:
                ends = True
                break
            if tok == t:
                ends = True
                break
        if ends:
            end = i + 1
            text = transcript[
                token_matches[start].start():token_matches[end - 1].end()
            ]
            n_words = len(_normalize_words(re.sub(r"[.?!;:]+$", "", text)))
            if n_words > 0:
                h = hashlib.sha256(text.encode("utf-8")).hexdigest()
                clauses.append(
                    ExactClause(
                        text=text,
                        start_token_index=start,
                        end_token_index=end,
                        normalized_word_count=n_words,
                        span_sha256=h,
                    )
                )
            start = end
        i += 1

    # Trailing incomplete span (no terminator) — treat as one clause if non-empty
    if start < len(token_matches):
        text = transcript[token_matches[start].start():token_matches[-1].end()]
        n_words = len(_normalize_words(text))
        if n_words > 0:
            h = hashlib.sha256(text.encode("utf-8")).hexdigest()
            clauses.append(
                ExactClause(
                    text=text,
                    start_token_index=start,
                    end_token_index=len(token_matches),
                    normalized_word_count=n_words,
                    span_sha256=h,
                )
            )

    if not clauses:
        return []

    # Prefer 5–20 word clauses
    preferred = [
        c for c in clauses
        if prefer_min_words <= c.normalized_word_count <= prefer_max_words
    ]
    if preferred:
        return _sort_clauses(preferred)

    # Fall back to shortest non-empty complete span
    shortest = min(clauses, key=lambda c: (c.normalized_word_count, c.start_token_index, c.end_token_index, c.span_sha256))
    return [shortest]


def _sort_clauses(clauses: Sequence[ExactClause]) -> list[ExactClause]:
    return sorted(
        clauses,
        key=lambda c: (
            c.normalized_word_count,
            c.start_token_index,
            c.end_token_index,
            c.span_sha256,
        ),
    )


def _uuid_bytes(value: str) -> bytes:
    """Canonical UUID byte ordering; invalid product identities fail closed."""
    try:
        return uuid.UUID(value).bytes
    except (ValueError, AttributeError) as error:
        raise ValueError("candidate_id must be a UUID") from error


def coverage_target_for_take(take_ordinal: int, slide_count: int) -> CoverageTarget:
    """Compute the progressive coverage target (D3 §7).

    Take 1: max(1, ceil(0.30 * N)) and always includes Slide 1.
    Take 2: max(previous, ceil(0.80 * N))
    Take 3+: N (100 %)
    """
    if slide_count < 1:
        return CoverageTarget(take_ordinal=take_ordinal, slide_count=0, target_count=0)
    n = slide_count
    if take_ordinal <= 1:
        target = max(1, math.ceil(0.30 * n))
    elif take_ordinal == 2:
        t1 = max(1, math.ceil(0.30 * n))
        target = max(t1, math.ceil(0.80 * n))
    else:
        target = n
    return CoverageTarget(
        take_ordinal=take_ordinal,
        slide_count=n,
        target_count=min(target, n),
    )


@dataclass(frozen=True)
class AnchorCandidate:
    """Minimal frozen fields needed for lexicographic routing (no scores)."""

    slide_index: int
    block_key: int
    candidate_id: str
    membership_item_order: int
    has_aligned_semantics: bool
    owner_response_confident_yes: bool
    has_playable_audio: bool
    has_exact_transcript: bool
    already_has_root: bool
    is_owner_locked: bool


def lexicographic_coverage_order(
    anchors: Sequence[AnchorCandidate],
    *,
    mandatory_slide_1: bool = True,
) -> list[AnchorCandidate]:
    """Closed lexicographic routing (D3 §8 / D6).

    Order:
    1. Mandatory Slide 1 first (when present and eligible).
    2. Slides without a current root before already-covered slides.
    3. Canonical slide index.
    4. Canonical 75-word block index.
    5. V3 membership item order.
    6. Anchor candidate UUID bytes (as string sort for stability).

    Vocal dominance + alignment are used only as eligibility filters;
    no blended score is computed or stored.
    """
    eligible = [
        a for a in anchors
        if a.has_aligned_semantics
        and a.owner_response_confident_yes
        and a.has_playable_audio
        and a.has_exact_transcript
        and not a.is_owner_locked  # locked roots are not auto-replaced
    ]

    def sort_key(a: AnchorCandidate) -> tuple:
        uncovered = 0 if a.already_has_root else 1  # uncovered first
        slide1_priority = 0 if (mandatory_slide_1 and a.slide_index == 0) else 1
        return (
            slide1_priority,
            -uncovered,  # uncovered (1) before covered (0) → negate so 1 first
            a.slide_index,
            a.block_key,
            a.membership_item_order,
            _uuid_bytes(a.candidate_id),
        )

    return sorted(eligible, key=sort_key)


def one_root_per_block_ok(
    existing_roots: Sequence[tuple[int, int]],  # (slide_index, block_key)
    slide_index: int,
    block_key: int,
) -> bool:
    """At most one active root per slide-bounded 75-word block."""
    return (slide_index, block_key) not in set(existing_roots)
