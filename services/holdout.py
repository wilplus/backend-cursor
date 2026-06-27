"""willab — frozen holdout for honest readiness eval (readiness rig #3). Pure.

Reserves a STABLE, deterministic ~20% of labeled snippets from training, so the
machine-vs-coach agreement metric is measured on data the model NEVER trained on.
Today the only split is a random sklearn split computed FRESH on each train run
(learning_train) — so as the corpus grows the same rows drift between train and
test, and "held-out" data leaks into training, inflating the score.

The split here is derived from ``snippet_id`` alone (sha1 → bucket), so it is:
  • reproducible everywhere (export, train, eval) with no DB column needed,
  • stable forever per snippet (a row never changes side as the corpus grows),
  • synthetic-safe by composition (synthetic rows are already excluded upstream
    by the Subsystem-S wall before they ever reach a split).
"""
from __future__ import annotations

import hashlib
from typing import Any

# ~1 in 5 labeled snippets is reserved for honest eval. Stable; change only with
# intent (it re-buckets the whole corpus).
HOLDOUT_FRACTION = 0.2
_BUCKETS = 10000


def is_holdout(snippet_id: Any, fraction: float = HOLDOUT_FRACTION) -> bool:
    """True iff this snippet is in the frozen holdout. Deterministic in
    ``snippet_id``; False for a missing id (never reserve an unkeyed row)."""
    if not snippet_id:
        return False
    try:
        digest = hashlib.sha1(str(snippet_id).encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) % _BUCKETS
    except Exception:
        return False
    frac = max(0.0, min(1.0, float(fraction)))
    return bucket < int(frac * _BUCKETS)
