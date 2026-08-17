"""Historical confidence-review rows retained for audit only.

The live owner answer moved to ``owner_voice_album_routing``. These old rows
must never train, calibrate, vote in quorum, evaluate, or feed SFT/DPO.

STRICT BOOLEAN remains useful for interpreting the historical audit rows:
a coerced value would claim a human answer that no human gave.

PROVENANCE. These rows are NON-BLIND because the owner saw the AI's choice.
They remain separate solely so historical audits can identify and exclude
them from every learning corpus.

AC-9. Capture only. Nothing in this module is ever serialized back to a user
as a score, verdict or ratio.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The provenance string these rows carry into any corpus breakdown. Distinct
# from the coach lane's 'heuristic' / 'random' selection sources so the mix
# stays visible on /admin/learning (by_selection_source).
SELECTION_SOURCE = "peer_review"

# Permanent fence: historical non-blind rows never count toward retraining.
COUNTS_TOWARD_RETRAIN_TRIGGER = False

_MAX_MODEL_VERSION_LEN = 200


def validate_confidence_review(payload: Any) -> tuple[Optional[dict], Optional[str]]:
    """Validate one peer-review flag → ``(row, None)`` or ``(None, error)``.

    Body: ``{ai_correct: bool, model_version?: str}``.

      ai_correct     REQUIRED, and must be a real boolean. A string "true",
                     1, or "yes" is REJECTED, never coerced (see the module
                     docstring — a coerced label is a fabricated one).
      model_version  OPTIONAL. Which prediction the reviewer was grading.
                     Omitted/null → the caller attributes the currently
                     shadowed version server-side; a blank string is treated
                     as omitted rather than stored as "".

    Pure — no DB, no request context."""
    if not isinstance(payload, dict):
        return None, "body: must be an object"

    ai_correct = payload.get("ai_correct")
    if not isinstance(ai_correct, bool):
        return None, "ai_correct: required, must be true or false"

    model_version = payload.get("model_version")
    if model_version is not None:
        if not isinstance(model_version, str):
            return None, "model_version: must be a string (or omitted)"
        model_version = model_version.strip()[:_MAX_MODEL_VERSION_LEN] or None

    return {
        "ai_correct": ai_correct,
        "model_version": model_version,
    }, None


def review_corpus_summary(rows: Any) -> dict:
    """Class balance for a peer-review corpus pull.

    The same guard ``confidence_labels.corpus_summary`` exists for: a corpus
    that is 95% "the AI was right" teaches nothing except agreement, and this
    is where that shows up BEFORE anything trains on it. Reviewers are counted
    distinctly because one enthusiastic rater flagging 200 snippets is not the
    same evidence as 40 raters flagging 5 each. Pure."""
    items = [r for r in (rows or []) if isinstance(r, dict)]
    yes = sum(1 for r in items if r.get("ai_correct") is True)
    no = sum(1 for r in items if r.get("ai_correct") is False)
    by_version: dict = {}
    for r in items:
        v = r.get("model_version") or "(unattributed)"
        by_version[v] = by_version.get(v, 0) + 1
    return {
        "total": len(items),
        "ai_correct_true": yes,
        "ai_correct_false": no,
        "agreement_rate": (round(yes / len(items), 3) if items else None),
        "by_model_version": by_version,
        "reviewers": len({
            r.get("reviewer_user_id") for r in items if r.get("reviewer_user_id")
        }),
        "selection_source": SELECTION_SOURCE,
        "blind": False,
    }
