"""Peer-review validation of the AI's confidence call (founder 2026-08-03).

What the retired acoustic stress lane became. A user or peer is shown the
AI's confidence choice on one snippet and answers one question: did it get
this right? ``ai_correct`` true/false. Nothing else.

STRICT BOOLEAN, and it is worth being explicit about why the string "true" is
a 400 rather than a coercion: this is TRAINING DATA. A coerced value is a
fabricated label — it records a human verdict that no human gave, and it is
indistinguishable from a real one afterwards. The same rule the coach
confidence-label route holds (services/confidence_labels.py). A caller that
sends the wrong type has a bug; a corpus that swallowed it has a lie in it.

PROVENANCE. These labels are NON-BLIND — the reviewer saw the AI's choice
before answering — unlike the coach labels, which stay blind (N1/N2). They
are captured under their own ``SELECTION_SOURCE`` so the two can never be
mixed indistinguishably downstream: validation of a prediction correlates
with the prediction, and an unlabelled blend invites a confirmation loop.

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

# Whether peer_review rows count toward the shadow lane's auto-retrain trigger
# (>=50 total corpus / >=25 new). DECISION, not a default (BE 2026-08-03):
# NO. The trigger governs the BLIND coach-truth corpus. Peer flags are
# non-blind validations of the model's own predictions, so counting them would
# let prediction-correlated labels set the retrain schedule for the very model
# they grade — the confirmation loop this whole split exists to prevent. It is
# also the reversible direction: turning this on later is a one-line change,
# whereas a corpus already retrained on a bad blend cannot be un-trained.
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
