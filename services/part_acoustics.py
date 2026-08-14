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

# ── THE PRAISE LANE'S THRESHOLD (founder 2026-08-13) ──────────────────────
#
# How far above THE VERSION ALREADY IN THE DOCUMENT this take has to land
# before it is worth offering as a swap. The system has had detectors for
# problems since the beginning and none at all for "this one landed", which is
# why a settled document produced a blank screen: nothing was notable, so
# nothing was generated, so every lane downstream had nothing to route.
#
# A HEAD-TO-HEAD, not a comparison to a rolling average (founder reversal
# 2026-08-13 — see beats_incumbent for why the rolling version was silently
# biased to never fire). Still never against other speakers and never against
# an absolute bar, which is what keeps it inside AC-9: the comparison is
# private, and what reaches the student is a qualitative line about the
# mechanics ("Strong delivery"), never the number or the fact that a
# comparison happened at all.
#
# 0.5 is a starting value and the ONE number to tune here. Too low and every
# take praises something, which devalues the mark; too high and the lane is as
# silent as the thing it was built to fix. It sits below DELIVERY_STAR_Z (1.2,
# the ISSUE threshold) on purpose — flagging a problem should need more
# evidence than noticing a good moment, because a false problem costs the
# student trust and a false positive costs them one ignored mark.
STRONG_Z_MARGIN = 0.5


def beats_incumbent(take_z: Any, doc_z: Any, *,
                    margin: float = STRONG_Z_MARGIN) -> list:
    """Parts this take delivered BETTER THAN THE VERSION IN THE DOCUMENT.

    ``[(part_id, lift)]``, biggest lift first. Pure.

    THE HEAD-TO-HEAD, AND WHY IT REPLACED A ROLLING-BASELINE COMPARISON
    (founder reversal 2026-08-13). The first cut of this compared the take
    against ``arc_part_acoustics.ema_z`` — which sounded right and was
    silently biased to never fire. That EMA is folded from the PERSISTED
    DOCUMENT, i.e. the best-of assembly (see fold_session: "scoring the
    assembly answers how good is this paragraph AT ITS BEST"). Comparing a
    raw take against a rolling average of best-of scores asks a raw take to
    beat the strongest version that has ever survived, which it almost never
    does. The lane would have shipped looking built and fired approximately
    never — the exact failure this product spent a day removing from three
    other places.

    BOTH SIDES COME FROM ``take_z_by_part``. Caller scores this take's pieces
    for ``take_z`` and the persisted document's pieces for ``doc_z``, with
    the same baseline. Same function, same units, same scorer — which is what
    makes the subtraction meaningful rather than a comparison of two things
    that merely look like numbers.

    NO CONSISTENCY FLOOR IS NEEDED, and its absence is not an oversight. On a
    first take the document IS that take, so ``doc_z == take_z``, the lift is
    zero, and no offer exists. The "requires multiple takes" property the
    design asks for falls out of the arithmetic instead of being enforced by
    a rule that could drift from it.

    LOCK-AGNOSTIC, like everything else here: routing a lift to a swap offer
    (locked chunks) or a lock recommendation (open ones) is the caller's
    decision and the two lanes differ.

    Ties break on part id so the choice is stable across calls.
    """
    if not isinstance(take_z, dict) or not isinstance(doc_z, dict):
        return []
    out: list = []
    for pid, now in take_z.items():
        key = str(pid or "")
        if not key or key not in doc_z:
            continue
        try:
            lift = float(now) - float(doc_z[key])
        except (TypeError, ValueError):
            continue
        if lift > margin:
            out.append((key, lift))
    out.sort(key=lambda t: (-t[1], t[0]))
    return out


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
    dropped = 0
    for piece, z in zip(usable, scores):
        part = part_at(spans, piece.get("start"), piece.get("end"))
        if not part:
            dropped += 1
            continue
        pid = str(part.get("id") or "")
        if not pid:
            continue
        buckets.setdefault(pid, []).append(float(z))
    if not buckets:
        # ⚠️ THE LAST UNLOGGED DECLINE (audit finding #5's second half). Every
        # guard upstream says why it skipped; this was the one stage that ate
        # a take silently — usually a coordinate/staleness disagreement
        # between the pieces and the parts, which is exactly the thing worth
        # shouting about.
        logger.warning(
            "part_acoustics: no piece mapped into any part span "
            "(pieces=%d parts=%d dropped=%d) — nothing folded",
            len(usable), len(spans), dropped)
    elif dropped:
        logger.info("part_acoustics: %d/%d piece(s) straddled/missed a part "
                    "span and were dropped", dropped, len(usable))
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


def _with_metrics(pieces: Any, arc_id: Any, database) -> list:
    """The document's pieces with each one's ACOUSTICS joined on. Best-effort.

    OPTION (C), founder 2026-08-13. `take_z_by_part` scores
    `piece["metrics"]`, and the persisted document does not carry any: the
    piece contract from services/transcript_document.py is
    `{snippet_id, take_session_id, take_index, start, end, text, slide_index}`
    — anchors and provenance, no measurements. So even with the document
    column in place the fold would have found `usable == []` and returned {}.
    Two independent breaks, stacked.

    THE MEASUREMENTS ARE JOINED, NOT COPIED INTO THE DOCUMENT. Persisting a
    second copy of per-piece acoustics beside the text would mint a staler
    home for numbers that already have one, and the founder's standing rule on
    detector data is that measurements live in one versioned place and are
    never duplicated into a form that can drift from it. The join key is
    `snippet_id`, which is the piece contract's own identity.

    Pieces whose snippet has no metrics are DROPPED rather than defaulted:
    `take_z_by_part` averages z-scores per part, so admitting a piece with a
    fabricated zero would report "delivered exactly at baseline" for a
    paragraph nobody measured.
    """
    rows = [p for p in (pieces or []) if isinstance(p, dict)]
    if not rows:
        return []
    try:
        from services.best_presentation import spoken_arc_sessions
        sess_ids = [
            s.get("id")
            for s in spoken_arc_sessions(database.get_arc_sessions(arc_id))
            if isinstance(s, dict) and s.get("id")
        ]
        by_session = (database.get_snippets_by_sessions(sess_ids) or {}
                      if sess_ids else {})
        by_id = {
            str(s.get("id")): s.get("metrics")
            for rows_ in by_session.values() if isinstance(rows_, list)
            for s in rows_ if isinstance(s, dict) and s.get("id")
        }
    except Exception as e:
        logger.warning("part_acoustics: metrics join failed arc=%s: %s",
                       arc_id, e)
        return []
    out = []
    metricless = 0
    for p in rows:
        m = by_id.get(str(p.get("snippet_id") or ""))
        # AT LEAST ONE REAL ACOUSTIC KEY, not merely a non-empty dict (audit
        # C2.6): a sub-second piece stores only {piece, recording_kind},
        # scores exactly 0.0 in score_control_direction, and — because
        # ONBOARD_Z is 0.0 — would GRADUATE the focus ratchet for a part
        # nobody measured, excluding it from focus forever. The keys mirror
        # snippet_salience._CONTROL_COMPONENTS.
        if isinstance(m, dict) and any(
                k in m for k in ("f0_sd", "pause_regularity",
                                 "dynamic_db", "voiced_ratio")):
            out.append({**p, "metrics": m})
        elif m is not None:
            metricless += 1
    if metricless:
        logger.info("part_acoustics: %d piece(s) carry no acoustic keys and "
                    "were dropped from the fold", metricless)
    return out


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
            # Cold start — nothing to measure against yet. The ONLY silent
            # skip here, because it is the one that is genuinely expected: a
            # speaker with no baseline has not recorded enough to have one.
            logger.info("part_acoustics: no baseline yet arc=%s", arc_id)
            return {}
        parts = database.get_ideal_text_parts(str(arc_id), str(user_id))
        if not parts:
            logger.info(
                "part_acoustics: fold skipped — no stored parts arc=%s "
                "(document never opened)", arc_id)
            return {}
        row = database.get_coach_arc_ideal_text(str(arc_id)) or {}
        doc = row.get("document") if isinstance(row, dict) else None
        pieces = (doc or {}).get("pieces") if isinstance(doc, dict) else None
        if not pieces:
            # ⚠️ THE LINE THAT WAS MISSING FOR THIS FUNCTION'S ENTIRE LIFE.
            # `document` was read here before the column existed, so every
            # call landed on this branch and returned {} without a word: no
            # part row was ever written, `focus_part_id` returned None for
            # every arc, and a KPI measuring nothing was indistinguishable
            # from a quiet arc. Post-migration this should only fire for arcs
            # assembled before 2026-08-13, and it says so out loud.
            logger.warning(
                "part_acoustics: fold skipped — no piece provenance on the "
                "ideal text arc=%s (pre-2026-08-13 assembly, or "
                "migrations/add_coach_arc_ideal_text_document.sql pending). "
                "No acoustic KPI will be recorded for this take.", arc_id)
            return {}
        scored = _with_metrics(pieces, arc_id, database)
        if not scored:
            logger.warning(
                "part_acoustics: fold skipped — the document's pieces carry "
                "no acoustics arc=%s (snippet metrics missing for every "
                "piece). No acoustic KPI will be recorded for this take.",
                arc_id)
            return {}
        # THE STALENESS GUARD (audit finding #5). part_spans' offsets are only
        # meaningful against a document the parts actually join to — its own
        # docstring says so — and the stored parts refresh only via HTTP
        # routes while the document refreshes every take. Folding against
        # disagreeing pairs produced z-scores for the WRONG paragraphs
        # (reproduced: 3 of 6 pieces silently dropped, one part vanished).
        # Declining loudly beats firing wrong.
        from services.ideal_text_parts import agrees_with_text
        doc_text = (row.get("auto_text") or row.get("text") or "")
        if doc_text and not agrees_with_text(parts, doc_text):
            logger.warning(
                "part_acoustics: fold skipped — stored parts do not join to "
                "the assembled document arc=%s (parts lag the assembly; they "
                "refresh on the next document open). No acoustic KPI for "
                "this take.", arc_id)
            return {}
        return fold_take(
            arc_id, user_id, pieces=scored, parts=parts, baseline=baseline,
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
