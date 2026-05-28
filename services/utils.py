"""Shared utilities for the backend."""
from datetime import datetime, timezone
from typing import Any, Optional


def utc_now_iso() -> str:
    """Return the current UTC time as a Z-suffixed ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


import re as _re


# Threshold for the "real correction vs cosmetic edit" gate on the
# admin RLHF write paths. Anything <= this many changed word tokens
# is treated as cosmetic and either rejected (422) or saved with the
# RLHF signal suppressed via the `is_trivial_edit` override.
# Tuned to the brainstorm's "don't trust the client" anti-lazy-admin
# brief; parameterize per-surface if a longer field (e.g. coaching
# rationale paragraphs) needs a different floor later.
TRIVIAL_EDIT_TOKEN_THRESHOLD = 5


def _word_tokens(s: Optional[str]) -> list[str]:
    """Tokenize a string into comparable words for the trivial-edit gate.

    Strips non-word punctuation, lowercases, splits on whitespace.
    Empty / None input → empty list. The normalisation is intentional:
    a stray comma, capitalisation flip, or trailing space MUST NOT
    count as a real correction (those are exactly the cosmetic edits
    the gate is built to catch).
    """
    if not s:
        return []
    cleaned = _re.sub(r"[^\w\s]", " ", s.lower())
    return cleaned.split()


def changed_word_tokens(a: Optional[str], b: Optional[str]) -> int:
    """Levenshtein distance over whitespace-split word tokens.

    Returns the number of insertions + deletions + substitutions
    needed to transform ``a`` → ``b`` at the WORD level (not char
    level). Case-insensitive and punctuation-insensitive (see
    ``_word_tokens``).

    Why Levenshtein over a simple set-diff: a symmetric set diff
    treats "brave and bold" vs "bold and brave" as 0 changes — but
    that's the kind of reordering an admin would consider a real
    edit. Levenshtein catches it as 2 substitutions (one for each
    swapped position). Matches admin intuition.

    Empty input on either side returns the other's token count, so
    typed-from-scratch admin content always reflects its full word
    count against the threshold (and so a 6-word note still passes
    the gate even with no AI baseline to diff against).

    O(n*m) time / space, but n and m are word counts not char
    counts — comments + rationales are bounded by what fits in a
    chat bubble (low hundreds at most), so this is fine.
    """
    ta = _word_tokens(a)
    tb = _word_tokens(b)
    if not ta:
        return len(tb)
    if not tb:
        return len(ta)
    # Classic two-row DP. dp[j] = edit distance between ta[:i] and
    # tb[:j] after the current i-th row is computed.
    prev = list(range(len(tb) + 1))
    for i, x in enumerate(ta, start=1):
        cur = [i] + [0] * len(tb)
        for j, y in enumerate(tb, start=1):
            cost = 0 if x == y else 1
            cur[j] = min(
                cur[j - 1] + 1,        # insertion (in b)
                prev[j] + 1,            # deletion (from a)
                prev[j - 1] + cost,     # substitution / match
            )
        prev = cur
    return prev[-1]


def render_admin_dont_ask_block(notes: Optional[str]) -> Optional[str]:
    """Render ``user_settings.private_admin_notes`` as a prompt block, or None.

    Used by every chat-LLM prompt builder so the admin's private
    notes about a user influence what the model will and won't
    surface. The wording covers both interview-style endpoints
    (where the LLM ASKS questions) and Q&A endpoints (where the
    LLM ANSWERS) — "asking about or surfacing" plus "never quote,
    repeat, or reference" instructs the model in both directions.

    Whitespace-only is treated as empty so an admin clearing the
    field doesn't leave a sentinel-but-vacuous block in the prompt.

    Returns the addendum string (no trailing newline; callers add
    spacing) or ``None`` when there's nothing to inject.
    """
    if not notes:
        return None
    text = notes.strip()
    if not text:
        return None
    return (
        "[ADMIN-PRIVATE CONTEXT — DO NOT ECHO OR REFERENCE]\n"
        "The user's coach has flagged the following as topics to "
        "AVOID asking about or surfacing in your response. Treat "
        "this as background to navigate around silently — never "
        "quote, repeat, or reference these notes to the user, and "
        "never generate questions or answers that touch on them.\n"
        "---\n"
        f"{text}\n"
        "---"
    )


def score_01_from_recording_row(rec: Any) -> Optional[float]:
    """Read 0..1 score from recordings.performance_metrics_v2.scoring_debug (set by recording_1/2 job)."""
    if not isinstance(rec, dict):
        return None
    pm = rec.get("performance_metrics_v2")
    if not isinstance(pm, dict):
        return None
    dbg = pm.get("scoring_debug")
    if not isinstance(dbg, dict):
        return None
    for key in ("score_01", "final_score_01"):
        v = dbg.get(key)
        if v is None:
            continue
        try:
            return max(0.0, min(1.0, float(v)))
        except (TypeError, ValueError):
            continue
    return None
