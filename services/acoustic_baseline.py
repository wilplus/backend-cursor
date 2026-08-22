"""The speaker's own acoustic reference, PERSISTED (founder 2026-08-12).

"The True KPI: Acoustic Moving Average — VERDICT: MEASURE AGAINST THE USER'S
BASELINE."

The baseline is a neutral, speaker-relative reference over acoustic features.
It does not classify a psychological state and never reaches user-facing copy.

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

# How many recent sessions feed a rebuild, and the minimum evidence per feature.
_BASELINE_MAX_SESSIONS = 5
_BASELINE_MIN_SAMPLES = 8
_BASELINE_MIN_SAMPLES_PARENT = 6

# How many takes a stored baseline serves before it is rebuilt. Not "never":
# a reference that stops tracking the speaker does not merely age, it INVERTS
# the measurement — the KPI's whole job is to notice improvement, and a frozen
# baseline reports improvement as drift away from itself. Not "every take"
# either: that pays six sequential round-trips for a mean that moves by a
# fraction of one sample. Three is one rehearsal round.
REFRESH_EVERY_TAKES = 3


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

    ``n`` matters per feature: a feature backed
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

    The shape the neutral acoustic comparison consumers speak, so a stored
    baseline drops into the current code with no call-site change. None when
    nothing is usable.
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


def _newer_than(iso: Any, sessions: Any) -> int:
    """How many of `sessions` were created after `iso`. Pure.

    Unparseable timestamps count as NEWER. The bias is deliberate: over-
    counting causes a recompute (correct, merely not free), while under-
    counting would pin a stale baseline in place forever — and a KPI measured
    against a reference that stopped tracking the speaker is worse than a
    slow one.
    """
    from datetime import datetime, timezone

    def _dt(v: Any):
        """Parse to an AWARE datetime, or None.

        NAIVE VALUES ARE STAMPED UTC (bug, found in production 2026-08-12).
        Postgres hands these two columns back differently — `computed_at`
        arrives with an offset and `created_at` without — and comparing the
        two raises "can't compare offset-naive and offset-aware datetimes".
        That TypeError fires at the COMPARISON, not at the parse, so it fell
        past this function's guard into the caller's except, which logged
        "cached read failed" and rebuilt the baseline. Every take. The cache
        never once served a hit, and the whole 1+N saving was silently
        forfeited while the code looked correct.
        UTC is the right stamp rather than a guess: this stack stores and
        returns UTC everywhere, and the two values are minutes apart in
        practice, so a wrong assumption here would be visible immediately.
        """
        try:
            at = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        return at if at.tzinfo else at.replace(tzinfo=timezone.utc)

    at = _dt(iso)
    if at is None:
        return len(sessions or [])
    n = 0
    for s in (sessions or []):
        made = _dt((s or {}).get("created_at")) if isinstance(s, dict) else None
        try:
            newer = made is None or made > at
        except TypeError:      # pragma: no cover - _dt now normalises both
            # Belt to the braces above. A comparison that raises must count as
            # NEWER (rebuild), never escape and disable the cache wholesale —
            # which is exactly how this failed the first time.
            newer = True
        if newer:
            n += 1
    return n


def _session_piece_metrics(session_id: Any, *, database=None) -> list:
    """Stored piece metrics for one session. Best-effort and read-only."""
    if not session_id:
        return []
    try:
        if database is None:
            from services.db import db as database
        return [
            row.get("metrics")
            for row in (database.get_snippets_by_session(str(session_id)) or [])
            if isinstance(row.get("metrics"), dict)
        ]
    except Exception as error:
        logger.warning(
            "acoustic_baseline: session metrics failed sid=%s: %s",
            session_id,
            error,
        )
        return []


def _build_user_stats(user_id: Any, *, database=None) -> tuple:
    """Return ``(stats, session_count)`` for the speaker's recent takes."""
    if not user_id:
        return None, 0
    try:
        if database is None:
            from services.db import db as database
        sessions = database.v2_list_user_lab_sessions(
            str(user_id), limit=_BASELINE_MAX_SESSIONS,
        ) or []
        pool: list = []
        for session in sessions:
            pool.extend(
                _session_piece_metrics(session.get("id"), database=database)
            )
        return stats_from_metrics(pool, _BASELINE_MIN_SAMPLES), len(sessions)
    except Exception as error:
        logger.warning(
            "acoustic_baseline: rebuild failed user=%s: %s",
            user_id,
            error,
        )
        return None, 0


def _resolve_stats(user_id: Any, *, recording_kind: str,
                   paired_session_id: Any, database=None) -> tuple:
    """Resolve neutral baseline stats without inferring a delivery state."""
    stats, count = _build_user_stats(user_id, database=database)
    if stats:
        return stats, "user", count
    if recording_kind == "read" and paired_session_id:
        parent = stats_from_metrics(
            _session_piece_metrics(paired_session_id, database=database),
            _BASELINE_MIN_SAMPLES_PARENT,
        )
        if parent:
            return parent, "parent_take", 1
    return None, None, 0


def resolve_for_take(user_id: Any, *, recording_kind: str = "spoken",
                     paired_session_id: Any = None, database=None) -> tuple:
    """``(baseline | None, kind | None)`` — the reference for THIS take, read
    from the store when it is still fresh.

    THE QUERY CUT (founder 2026-08-12, "can we still do smth with the wait
    time?"). Rebuilding the baseline reads up to ``_BASELINE_MAX_SESSIONS``
    sessions AND one ``get_snippets_by_session`` per session — six sequential
    round-trips, on the upload path, every take. Now that the result is
    persisted, most takes can read one row instead.

    THE REFRESH RULE, and why it is not "never" or "always". A baseline that
    is never refreshed stops describing the speaker the moment they improve,
    which is precisely the improvement the KPI exists to detect — so a stale
    reference does not just age, it inverts the measurement. Recomputing every
    take pays the full 1+N for a mean that moves by a fraction of a sample.

    So: recompute once every ``REFRESH_EVERY_TAKES`` takes, counted from the
    stored snapshot's own timestamp against the session list — which is ONE
    cheap query, not the N expensive ones. Steady state is 2 queries where it
    was 6, with a full rebuild on every third take.

    Cold start, a guest, and a re-read with no user baseline all fall through
    to the existing resolver unchanged: the fast path requires a stored row,
    and there is nothing to store yet.
    """
    if database is None:
        from services.db import db as database
    try:
        row = database.get_current_user_acoustic_baseline(
            str(user_id or ""), detector_version=BASELINE_VERSION) \
            if user_id else None
        if isinstance(row, dict):
            fresh = as_baseline(row.get("features"))
            if fresh:
                sessions = database.v2_list_user_lab_sessions(
                    str(user_id), limit=_max_sessions()) or []
                if _newer_than(row.get("computed_at"),
                               sessions) < REFRESH_EVERY_TAKES:
                    logger.info("acoustic baseline reused id=%s features=%d",
                                row.get("id"), len(fresh))
                    return fresh, "user"
    except Exception as e:
        # A read hiccup must cost a recompute, never a take (LIVE LOOP).
        logger.warning("acoustic_baseline: cached read failed user=%s: %s",
                       user_id, e)

    stats, kind, n_sessions = _resolve_stats(
        user_id, recording_kind=recording_kind,
        paired_session_id=paired_session_id, database=database)
    if kind == "user":
        # Only the SPEAKER'S OWN baseline is stored. A parent-take reference is
        # a within-session comparison, not a claim about where this speaker
        # normally sits; storing it as one would corrupt the series it feeds.
        logger.info("acoustic baseline rebuilt stored=%s features=%d "
                    "sessions=%d",
                    snapshot(user_id, stats,
                             n_sessions=n_sessions) is not None,
                    len(stats or {}), n_sessions)
    return as_baseline(stats), kind


def _max_sessions() -> int:
    """The session window the baseline is built over — read from the module
    that owns it, so the freshness check and the rebuild can never disagree
    about how far back "recent" goes."""
    return _BASELINE_MAX_SESSIONS


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
