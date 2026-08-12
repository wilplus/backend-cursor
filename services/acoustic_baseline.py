"""The speaker's own acoustic reference, PERSISTED (founder 2026-08-12).

"The True KPI: Acoustic Moving Average — VERDICT: MEASURE AGAINST THE USER'S
BASELINE."

WHAT CHANGED, AND WHAT DID NOT. The baseline itself is not new:
``acoustic_read.build_user_baseline`` has computed ``{feature: (mean, sd)}``
over the speaker's own historical pieces since 2026-07-14, and
``lab_recording`` already calls it on every upload. What it has never done is
KEEP the result — the dict is used to z-score one take's pieces and then
dropped. A moving average cannot exist until the thing it is an average
against outlives one request.

So this module persists what is already computed, at the call site that
already computes it. **No new queries on the upload path.** The existing 1+N
(up to ``_BASELINE_MAX_SESSIONS`` sessions × ``get_snippets_by_session``) is
unchanged, and now that the pipeline timers reach the log it is finally
measurable. Reading the stored row INSTEAD of recomputing is the obvious next
win, but it changes how often the baseline refreshes, which is a behaviour
change and does not belong in the same step as "stop throwing it away".

APPEND-ONLY (founder standing constraint: never silently overwrite historical
calculations). A new snapshot INSERTs and stamps ``superseded_at`` on the
previous row. The KPI's whole claim is a comparison — "this part is now above
where you were" — and a comparison whose reference was quietly recomputed
cannot be reproduced, checked, or explained.

VERSIONING. ``BASELINE_VERSION`` names the regime: the feature set, their
weights, and the evidence floor. Rows from two versions are two different
measurements and must never be read as one series. ``test_acoustic_baseline``
fails if the weights move without the version moving — the same drift guard
``test_local_ci_mirror`` applies to the CI script.

AC-9 / CONSTRUCT. Everything here is machine measurement used to ORDER
interventions and ROUTE focus. No value in this module reaches a payload, a
badge, or a user-facing string.
"""
from __future__ import annotations

import logging
import math
from typing import Any, Optional

from services.snippet_salience import _CONTROL_COMPONENTS

logger = logging.getLogger(__name__)

# The regime. Bump when _CONTROL_COMPONENTS (names OR weights) or the evidence
# floor changes — a baseline computed under different weights is a different
# measurement, and averaging the two would be the silent-overwrite failure in
# a slower form.
BASELINE_VERSION = "acoustic-baseline-v1"

# The feature set this version is defined over, pinned here rather than read
# from the import so the test can compare the two and catch a silent edit.
BASELINE_FEATURES: tuple = ("f0_sd", "pause_regularity", "dynamic_db",
                            "voiced_ratio")


def weights_fingerprint() -> str:
    """A stable string over the live weights — what the version PROMISES.

    Pure. The drift test compares this against the fingerprint recorded for
    BASELINE_VERSION; a weights edit that forgets to bump the version fails
    there instead of silently producing rows that claim a regime they are not
    from.
    """
    return ";".join(f"{name}={weight:.4f}"
                    for name, weight in _CONTROL_COMPONENTS)


def stats_from_metrics(metric_dicts: Any, min_samples: int) -> Optional[dict]:
    """``{feature: {"mean", "sd", "n"}}`` over a pool of piece-metric dicts.

    The same arithmetic as ``acoustic_read._baseline_from_metrics``, keeping
    the sample count it discards. ``n`` matters per feature: a feature backed
    by 8 pieces and one backed by 80 are not the same claim, and the tuple
    shape could not say so.

    Features below ``min_samples``, or with zero spread, are omitted — a
    zero-sd feature carries no signal and z-scoring against it divides by
    zero. None when nothing clears the bar. Pure.
    """
    cols: dict = {name: [] for name, _w in _CONTROL_COMPONENTS}
    for m in (metric_dicts or []):
        if not isinstance(m, dict):
            continue
        for name, _w in _CONTROL_COMPONENTS:
            v = m.get(name)
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                cols[name].append(float(v))
    out: dict = {}
    for name, vals in cols.items():
        if len(vals) < min_samples:
            continue
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        sd = math.sqrt(var)
        if sd > 0:
            out[name] = {"mean": mean, "sd": sd, "n": len(vals)}
    return out or None


def as_baseline(features: Any) -> Optional[dict]:
    """``{feature: {"mean","sd","n"}}`` → ``{feature: (mean, sd)}``.

    The shape every existing consumer (``score_control_direction``,
    ``attach_acoustic_read``) already speaks, so a stored baseline drops into
    the current code with no call-site change. None when nothing is usable.
    Pure.
    """
    if not isinstance(features, dict):
        return None
    out: dict = {}
    for name, stat in features.items():
        if not isinstance(stat, dict):
            continue
        mean, sd = stat.get("mean"), stat.get("sd")
        if isinstance(mean, (int, float)) and isinstance(sd, (int, float)) \
                and not isinstance(mean, bool) and not isinstance(sd, bool) \
                and sd > 0:
            out[str(name)] = (float(mean), float(sd))
    return out or None


def snapshot(user_id: Any, features: Any, *, n_sessions: int = 0,
             database=None) -> Optional[str]:
    """Persist a baseline snapshot; return its id, or None.

    BEST-EFFORT BY CONSTRUCTION. This runs on the upload path, and a baseline
    that cannot be written is a KPI that degrades — never a take that fails
    (LIVE LOOP). Every failure path returns None and the caller carries on
    with the in-memory baseline exactly as it does today.

    Writes the new row FIRST and supersedes the old one after. The order is
    deliberate: interrupted between the two leaves two current rows, and
    readers take the newest — degraded but correct. The reverse order leaves a
    window with NO current baseline, which reads as cold start and would drop
    a user out of single-point focus for no reason.
    """
    if not user_id or not isinstance(features, dict) or not features:
        return None
    try:
        if database is None:
            from services.db import db as database
        return database.insert_user_acoustic_baseline(
            str(user_id), features,
            n_sessions=int(n_sessions or 0),
            n_samples=sum(int(s.get("n") or 0) for s in features.values()
                          if isinstance(s, dict)),
            detector_version=BASELINE_VERSION,
        )
    except Exception as e:
        logger.warning("acoustic_baseline: snapshot failed user=%s: %s",
                       user_id, e)
        return None


def current(user_id: Any, *, database=None) -> tuple:
    """``(baseline_dict | None, baseline_id | None)`` — this user's current
    reference in the shape the z-scorers speak.

    Cold start (guest, first takes, too little history) is a REAL STATE and
    returns ``(None, None)``: callers degrade to within-take z-scores, which
    is exactly today's behaviour. Best-effort; never raises.
    """
    if not user_id:
        return None, None
    try:
        if database is None:
            from services.db import db as database
        row = database.get_current_user_acoustic_baseline(
            str(user_id), detector_version=BASELINE_VERSION)
        if not isinstance(row, dict):
            return None, None
        return as_baseline(row.get("features")), row.get("id")
    except Exception as e:
        logger.warning("acoustic_baseline: read failed user=%s: %s",
                       user_id, e)
        return None, None
