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


