"""Fact-check guard for evaluator outputs.

Problem: the LLM evaluator that scores coaching-loop answers can quote
phrases that the user never said. Once those hallucinated quotes seed
the few-shot pool (Phase 1) or learner-profile inferences (Phase 3),
the system starts coaching from wrong ground truth — a compounding
data-quality failure.

Phase 5 of the snippet-CTA roadmap. This module verifies the
rationale's claims against the source evidence BEFORE the outcome is
persisted, without an extra LLM round-trip. Cheap, deterministic,
defensible.

What we check
-------------
1. **Phrase verification.** Every quoted span ("...") in the rationale
   must appear in the user's answer or the source-snippet transcript,
   either as an exact case-insensitive substring or as a fuzzy
   sub-string match (SequenceMatcher ratio ≥ ``fuzzy_threshold``).
   Phrases that fail flag the outcome.

2. **Specificity floor.** When ``specificity`` > 0.7 but the rationale
   doesn't quote anyone at all, the score is downgraded to 0.5. High
   specificity needs verbatim evidence; otherwise the model is
   inflating.

Outputs
-------
``fact_check_outcome`` returns a small dict with:
  - ``passed``: bool — true if no issues found
  - ``issues``: list[str] — human-readable problems for telemetry / logs
  - ``adjusted_specificity``: float | None — set when the floor rule
    fired so the caller can rewrite the component score before persist
  - ``eligible_for_few_shot``: bool — convenience alias for ``passed``
    that the caller writes to the outcome blob; Phase 1 retrieval
    filters on this

Failure semantics
-----------------
We **never** discard an outcome on fact-check failure. The attempt
still lands (preserves evidence for admin review and audits) but it's
marked ineligible for downstream learning (few-shot retrieval, future
profile diffs, mirror generation). The system learns only from
verified exchanges.

Out of scope
------------
Adding an LLM-based factuality verifier on top of this would be a
later commit if drift persists. Today's heuristics catch the common
case (quoted phrase that doesn't exist) at zero LLM cost. Phase 5 in
the roadmap explicitly defers the LLM verifier.
"""
from __future__ import annotations

import difflib
import re
from typing import Any


_QUOTE_PATTERN = re.compile(
    # Match anything between straight or curly double-quotes. The lazy
    # quantifier avoids spanning multiple quoted chunks in one go.
    r'(?:"([^"]+)"|“([^”]+)”)'
)


def fact_check_outcome(
    *,
    rationale: str,
    user_answer_text: str,
    source_transcript: str,
    specificity: float,
    fuzzy_threshold: float = 0.85,
) -> dict[str, Any]:
    """Verify a rationale's claims against the source evidence.

    Args:
        rationale: free-text explanation produced by the evaluator LLM.
            Any double-quoted span here is treated as a citation.
        user_answer_text: the user's actual answer (Whisper output).
        source_transcript: the source-snippet transcript that seeded
            the coaching chat. Citations may legitimately come from
            either — the user might be paraphrasing themselves.
        specificity: the specificity sub-score (0..1) the evaluator
            returned. Used by the floor rule.
        fuzzy_threshold: SequenceMatcher ratio required to consider a
            phrase "found" when it isn't an exact substring. 0.85
            tolerates minor punctuation / whitespace drift while
            rejecting genuinely invented phrases.

    Returns:
        Diagnostic dict — see module docstring for shape.
    """
    issues: list[str] = []

    quoted_spans = _extract_quoted_spans(rationale)
    haystack_lower = (
        (user_answer_text or "").lower()
        + " SEP "  # boundary marker so phrases don't span sources
        + (source_transcript or "").lower()
    ).strip()

    for span in quoted_spans:
        if not _phrase_appears(span, haystack_lower, fuzzy_threshold):
            preview = span[:60] + ("…" if len(span) > 60 else "")
            issues.append(f"Quoted phrase not found in evidence: \"{preview}\"")

    adjusted_specificity: float | None = None
    if specificity > 0.7 and not quoted_spans:
        # Model claims high specificity without quoting the user. Treat
        # as inflation — downgrade to the band where it can't drive
        # few-shot eligibility on its own.
        adjusted_specificity = 0.5
        issues.append(
            "specificity > 0.7 with no verbatim user citation — downgraded to 0.5"
        )

    passed = not issues
    return {
        "passed": passed,
        "issues": issues,
        "adjusted_specificity": adjusted_specificity,
        "eligible_for_few_shot": passed,
    }


# ── Internals ───────────────────────────────────────────────────────────────


def _extract_quoted_spans(text: str) -> list[str]:
    """Pull every quoted-span out of ``text``. Handles both straight and
    curly double-quotes; ignores empty / single-character quotes."""
    if not text:
        return []
    spans: list[str] = []
    for m in _QUOTE_PATTERN.finditer(text):
        raw = (m.group(1) or m.group(2) or "").strip()
        if len(raw) >= 2:
            spans.append(raw)
    return spans


def _phrase_appears(
    span: str,
    haystack_lower: str,
    fuzzy_threshold: float,
) -> bool:
    """Best-effort containment check for ``span`` inside ``haystack_lower``.

    Order matters: cheapest checks first.
      1. Exact case-insensitive substring → bail immediately.
      2. Overall SequenceMatcher ratio against the whole haystack —
         catches cases where the model lightly paraphrased.
      3. Sliding-window match: for each word-length-N window in the
         haystack, compute the ratio against the span and bail as soon
         as one passes ``fuzzy_threshold``. Catches small typos /
         re-orderings inside a longer answer.
    Returns True on the first match found.
    """
    needle = span.strip().lower()
    if not needle:
        return False

    if needle in haystack_lower:
        return True

    # Overall fuzzy ratio — fast O(n+m). Good for medium-length quotes.
    if difflib.SequenceMatcher(None, needle, haystack_lower).ratio() >= fuzzy_threshold:
        return True

    # Window-by-window fuzzy. Only attempted when the global ratio is
    # low — protects against false-rejects when the haystack is much
    # longer than the needle (which deflates the overall ratio).
    needle_words = needle.split()
    haystack_words = haystack_lower.split()
    n = len(needle_words)
    if n == 0 or len(haystack_words) < n:
        return False
    best = 0.0
    for i in range(len(haystack_words) - n + 1):
        window = " ".join(haystack_words[i : i + n])
        r = difflib.SequenceMatcher(None, needle, window).ratio()
        if r >= fuzzy_threshold:
            return True
        if r > best:
            best = r
    return False
