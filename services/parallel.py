"""Bounded, order-preserving concurrency for the analysis pipeline.

Founder 2026-08-12, after the first production timing line
(``total=42639ms {'analysis': 21548, …}``): the model calls inside one phase
are independent and were running one after another. This runs them at the
same time. **It removes no AI** — every call that ran before still runs.

THIS IS THE FIRST CONCURRENCY IN THE SERVICES LAYER, so the rules live here
rather than at the call site, where the second user of this would have to
re-derive them.

RESULTS COME BACK IN SUBMISSION ORDER, NEVER COMPLETION ORDER. This is the
one property that matters and the reason this helper exists at all. The values
produced here feed ``overall_score`` and therefore the L2 ranking blend, so a
result list that reordered itself by whichever model answered first would make
two identical takes rank differently — a non-deterministic ranking that would
be almost impossible to reproduce, because it would depend on network jitter.

EXCEPTIONS SURFACE AT COLLECTION, IN SUBMISSION ORDER, so a caller sees the
same exception it would have seen sequentially. What CANNOT be preserved is
the "later work never ran" side effect: if the first callable raises, the
second has already executed and its model call has already been paid for. Its
result is discarded exactly as it would have been. That is the honest cost of
overlapping them, and it is bounded at one wasted call.

BOUNDED BY CONSTRUCTION. `max_workers` defaults to the number of thunks and is
hard-capped: a 270-piece talk must never be able to fan out into a thread per
piece and a rate-limit storm. Callers pass small, fixed groups.

THREAD SAFETY IS THE CALLER'S. Each thunk must read shared state and write only
its own return value — no appending into a list the sibling also touches. The
pipeline's calls satisfy this because each builds a fresh list from `prelim`
and returns it.
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)

# A ceiling, not a target. The groups this serves are 2-3 calls; anything
# larger is a fan-out that should be batched into one request instead.
MAX_WORKERS = 4


def run_in_parallel(*thunks: Callable[[], Any],
                    max_workers: Optional[int] = None) -> list:
    """Run zero-argument callables concurrently; results in SUBMISSION ORDER.

    Degrades to sequential for 0 or 1 thunk — a thread pool for one call is
    pure overhead, and the single-call path stays byte-identical to what it
    was before this module existed.
    """
    calls = [t for t in thunks if callable(t)]
    if not calls:
        return []
    if len(calls) == 1:
        return [calls[0]()]

    workers = min(max_workers or len(calls), MAX_WORKERS, len(calls))
    with ThreadPoolExecutor(max_workers=workers,
                            thread_name_prefix="willab-par") as pool:
        futures = [pool.submit(t) for t in calls]
        # Collected by INDEX, not by as_completed(): submission order is the
        # contract, and as_completed() is precisely the function that would
        # silently break it.
        return [f.result() for f in futures]
