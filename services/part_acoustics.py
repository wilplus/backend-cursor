"""Per-part acoustic moving average, and the single-point-focus ratchet.

Founder 2026-08-12, item 6: "ISOLATE THE WEAKEST LINK. Identify the single
most consistently underperforming part. Route all feedback and interventions
to that specific part. Suppress feedback everywhere else… The Ratchet: only
when that weakest part surpasses the baseline and 'comes onboard' does the
system unlock feedback for the next underperforming part."

THREE RULES, and each one is a line of code somewhere below:

  1. MEASURE against the speaker's own baseline, per part, across takes.
  2. FOCUS on the single worst part; suppress everywhere else.
  3. RATCHET — coming onboard is permanent; a later bad take does not
     re-capture the focus.

WHY THE MATH IS NOT NEW. ``snippet_salience.score_control_direction`` already
turns a pool of pieces into a per-piece control composite, z-scored against a
supplied ``{feature: (mean, sd)}`` baseline with the ``_CONTROL_COMPONENTS``
weights. This module maps pieces to PARTS and averages, and borrows the
scoring wholesale — a second implementation of "how controlled was this
voice" is exactly the drift the repo keeps writing about.

EMA, NOT A FLAT MEAN. "Most consistently underperforming" has to weight recent
takes above the first one, or a part the student genuinely fixed keeps its
early bad takes forever and stays the focus long after it stopped deserving
to. An exponential average forgets at a fixed rate and needs one number of
state — which is also why ``arc_part_acoustics`` is one row per part rather
than one row per (part, take).

AC-9 / CONSTRUCT. Every number here is machine measurement that ORDERS
interventions and ROUTES focus. Nothing in this module reaches a payload, a
badge, or a user-facing string, and the focus part is surfaced only as "which
paragraph may carry feedback" — never as a rank, a score, or a verdict about
the speaker.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# How fast the average forgets. 0.5 = the newest take carries half the weight,
# so three takes ago contributes ~12%. Chosen to move within ONE rehearsal
# session (the founder's unit of work) rather than over a month: a student who
# fixes a paragraph should see the focus move on their next take or two, not
# after ten.
EMA_ALPHA = 0.5

# "Surpasses the baseline" (the founder's words) in the units this is measured
# in. z = 0 IS the speaker's own baseline by construction, so the threshold is
# not a tunable — it is the definition, and writing it as a named constant is
# only so the ratchet reads as English at the call site.
ONBOARD_Z = 0.0

# "Most CONSISTENTLY underperforming." One observation is not a consistency
# claim, and routing every intervention in the document at a paragraph on the
# strength of a single noisy take is precisely the over-reaction the ratchet
# exists to prevent. Below this the focus rule declines to fire and the
# existing per-paragraph budget governs, unchanged.
MIN_TAKES_FOR_FOCUS = 2


def take_z_by_part(pieces: Any, parts: Any, baseline: Any = None) -> dict:
    """``{part_id: z}`` for ONE take. Pure.

    Each piece is scored by ``score_control_direction`` (higher = more
    controlled), then pieces are grouped onto the part whose span contains
    them and averaged. A part with no pieces this take is ABSENT from the
    result rather than present as 0.0 — the student may simply not have spoken
    those words in this take, and folding a fabricated zero into the moving
    average would read as "they delivered it at exactly their baseline".

    A piece that STRADDLES two parts belongs to neither (``part_at`` returns
    None) and is dropped: the deck's standing rule is drop, never guess.
    """
    from services.ideal_text_parts import part_at, part_spans
    from services.snippet_salience import score_control_direction

    usable = [p for p in (pieces or [])
              if isinstance(p, dict) and isinstance(p.get("metrics"), dict)]
    if not usable:
        return {}
    spans = part_spans(parts)
    if not spans:
        return {}
    scores = score_control_direction(usable, baseline=baseline)

    buckets: dict = {}
    for piece, z in zip(usable, scores):
        part = part_at(spans, piece.get("start"), piece.get("end"))
        if not part:
            continue
        pid = str(part.get("id") or "")
        if not pid:
            continue
        buckets.setdefault(pid, []).append(float(z))
    return {pid: sum(vals) / len(vals) for pid, vals in buckets.items()}


def fold(prev_ema: Any, prev_takes: Any, take_z: float) -> tuple:
    """``(ema, n_takes)`` after folding one take in. Pure.

    The FIRST take seeds the average with its own value rather than pulling a
    0.0 toward it — seeding from an implicit zero would make every part look
    like it started at the baseline and then got worse, which is a story about
    the seed, not the speaker.
    """
    n = int(prev_takes or 0)
    if n <= 0 or not isinstance(prev_ema, (int, float)) \
            or isinstance(prev_ema, bool):
        return float(take_z), 1
    return (EMA_ALPHA * float(take_z)
            + (1.0 - EMA_ALPHA) * float(prev_ema)), n + 1


def is_onboard(row: Any) -> bool:
    """Has this part come onboard? THE RATCHET, read side.

    Latched: a row that has ever crossed carries ``came_onboard_at`` forever,
    so a part that comes onboard and then has one bad take stays onboard. That
    is the difference between a ratchet and a threshold, and re-deriving this
    from ``ema_z`` instead of reading the latch would silently turn it back
    into a threshold.
    """
    return bool(isinstance(row, dict) and row.get("came_onboard_at"))


def focus_part_id(rows: Any) -> Optional[str]:
    """The single part that may carry feedback, or None. Pure.

    None means NO focus could be established, and every caller must read that
    as "behave exactly as before" — never as "suppress everything". Cold start
    (no baseline, a first take, a document nobody has recorded twice) has to
    leave the existing behaviour alone, or the feature would take the feedback
    engine dark for precisely the users who have the least of it.

    Among parts that have not yet come onboard and have enough takes to be
    called consistent, the worst average wins. Ties break on the part id so
    the choice is stable across calls — an unstable focus would move the
    student's feedback around the document between two identical takes.
    """
    open_rows = [
        r for r in (rows or [])
        if isinstance(r, dict)
        and not is_onboard(r)
        and int(r.get("n_takes") or 0) >= MIN_TAKES_FOR_FOCUS
        and isinstance(r.get("ema_z"), (int, float))
        and not isinstance(r.get("ema_z"), bool)
    ]
    if not open_rows:
        return None
    worst = min(open_rows,
                key=lambda r: (float(r["ema_z"]), str(r.get("part_id") or "")))
    # A part already at or above the speaker's own baseline is not
    # underperforming, so there is nothing to focus ON. It has simply not been
    # latched yet (that happens on the next fold); until then, no focus.
    if float(worst["ema_z"]) >= ONBOARD_Z:
        return None
    return str(worst.get("part_id") or "") or None


def fold_take(arc_id: Any, user_id: Any, *, pieces: Any, parts: Any,
              baseline: Any = None, baseline_id: Any = None,
              session_id: Any = None, database=None) -> dict:
    """Fold one take into every part's moving average. Returns ``{part_id: row}``.

    BEST-EFFORT. This runs on the upload path: a KPI that cannot be written is
    a KPI that degrades, never a take that fails (LIVE LOOP). Every failure
    path returns ``{}`` and the callers fall back to today's behaviour.

    Requires a real baseline. Without one, ``score_control_direction``
    z-scores WITHIN the take's own pool — which is scale-free, so a two-piece
    take pegs its parts at ±1 on trivial variation. Folding that into a
    persistent average would poison it with noise that looks like signal, and
    unlike the transient coach needle this number is kept. Cold start writes
    nothing and waits for a baseline to exist.
    """
    if not arc_id or not user_id or not baseline:
        return {}
    try:
        if database is None:
            from services.db import db as database
        from services.acoustic_baseline import BASELINE_VERSION

        by_part = take_z_by_part(pieces, parts, baseline)
        if not by_part:
            return {}
        prev = {
            str(r.get("part_id")): r
            for r in (database.get_arc_part_acoustics(
                str(arc_id), str(user_id)) or [])
            if isinstance(r, dict)
        }
        out: dict = {}
        for pid, take_z in by_part.items():
            was = prev.get(pid) or {}
            ema, n = fold(was.get("ema_z"), was.get("n_takes"), take_z)
            out[pid] = {
                "part_id": pid,
                "arc_id": str(arc_id),
                "user_id": str(user_id),
                "ema_z": ema,
                "n_takes": n,
                "last_take_session_id": str(session_id) if session_id else None,
                # THE LATCH. Already onboard stays onboard — never re-derived
                # from the new average, or a bad take would un-graduate a part
                # the student already fixed.
                "came_onboard": (is_onboard(was)
                                 or (ema >= ONBOARD_Z
                                     and n >= MIN_TAKES_FOR_FOCUS)),
                "baseline_id": str(baseline_id) if baseline_id else None,
                "detector_version": BASELINE_VERSION,
            }
        database.upsert_arc_part_acoustics(list(out.values()))
        logger.info(
            "part_acoustics arc=%s parts=%d onboard=%d focus=%s",
            arc_id, len(out),
            sum(1 for r in out.values() if r["came_onboard"]),
            focus_part_id([{**r, "came_onboard_at": r["came_onboard"] or None}
                           for r in out.values()]))
        return out
    except Exception as e:
        logger.warning("part_acoustics: fold failed arc=%s: %s", arc_id, e)
        return {}


def fold_session(arc_id: Any, user_id: Any, session_id: Any, *,
                 database=None) -> dict:
    """Fold the current assembly into the per-part averages after a take.

    WHAT IS MEASURED, and why it is the assembly rather than the raw take.
    The document is the BEST-OF selection (L1: the best actual take per
    slide, chosen), so a piece in it is the strongest version of that
    paragraph the speaker has produced so far. Scoring the assembly answers
    "how good is this paragraph AT ITS BEST, in this speaker's own terms" —
    which is exactly the founder's weakest link: a part whose best surviving
    version still sits below the speaker's baseline is genuinely the one to
    work on, and one whose best is above it has come onboard no matter how a
    single later take went.

    Scoring only the raw take instead would make the focus jump around on
    take-to-take noise, and would leave any paragraph this take happened not
    to improve without an observation at all.

    Reads the PERSISTED document rather than reassembling: the eager assembly
    has already run by the time this is called, and rebuilding it here would
    pay the whole compose cost twice per take.

    Best-effort; ``{}`` on anything missing (LIVE LOOP).
    """
    if not arc_id or not user_id:
        return {}
    try:
        if database is None:
            from services.db import db as database
        from services.acoustic_baseline import current as current_baseline

        baseline, baseline_id = current_baseline(user_id, database=database)
        if not baseline:
            return {}       # cold start — nothing to measure against yet
        parts = database.get_ideal_text_parts(str(arc_id), str(user_id))
        if not parts:
            return {}       # a document nobody has opened has no parts
        row = database.get_coach_arc_ideal_text(str(arc_id)) or {}
        doc = row.get("document") if isinstance(row, dict) else None
        pieces = (doc or {}).get("pieces") if isinstance(doc, dict) else None
        if not pieces:
            return {}
        return fold_take(
            arc_id, user_id, pieces=pieces, parts=parts, baseline=baseline,
            baseline_id=baseline_id, session_id=session_id,
            database=database)
    except Exception as e:
        logger.warning("part_acoustics: fold_session failed arc=%s: %s",
                       arc_id, e)
        return {}


def current_focus(arc_id: Any, user_id: Any, *, database=None) -> Optional[str]:
    """The part id feedback may land on for this document, or None.

    None = no focus established; callers behave exactly as they did before
    this feature existed. Best-effort; never raises.
    """
    if not arc_id or not user_id:
        return None
    try:
        if database is None:
            from services.db import db as database
        return focus_part_id(
            database.get_arc_part_acoustics(str(arc_id), str(user_id)))
    except Exception as e:
        logger.warning("part_acoustics: focus read failed arc=%s: %s",
                       arc_id, e)
        return None
