"""State-generic ternary ratings (SPEC.md v3 §3.2, §6, §17 — slice 1).

WHAT THIS IS. The one instrument every measured cognitive state is rated with:
a single clip, a single question, and three answers — ``yes`` / ``no`` /
``neutral`` — plus a separate ``unrateable`` control that is not an answer.
The question carries the state; the answer space never varies.

WHY THE ANSWER SPACE IS FIXED. A rater who is careful about confidence is
probably careful about anything else you ask them, and that is only learnable
if the response format is shared. Per-state answer labels ("Clear Mastery" vs
"Yes, Confident") would make raters' behaviour incomparable across states — a
wording effect masquerading as a reliability difference — and destroy the one
property that makes rater reliability transfer.

WHY ``unrateable`` IS NOT A FOURTH VALUE. ``neutral`` is a judgment about the
MOMENT: it reads as middling. ``unrateable`` is a judgment about the RATER's
ability to make one, usually because the audio is unclear. Folding the second
into the first books bad audio as a real middling rating and poisons the one
class that defines the decision boundary. Kept separate, the ternary stays
clean and abstention rate survives as a rater-quality signal.

WHY ``neutral`` MATTERS MORE THAN IT LOOKS. It is not a hedge. A recogniser
that has never seen the middle has never seen the boundary it exists to find,
and every later agreement number computed without it is measured on the easy
cases only.

FENCES.
  * BLIND COACH / I1 — nothing in this module renders a model read. The rating
    payload carries the moment and the question, never a score, band or
    comment. ``saw_model_output`` is stored so the invariant is AUDITABLE
    rather than merely asserted.
  * AC-9 — no aggregate here is ever serialized toward a student. ``quality``
    and ``agreement`` are machine-facing.
  * §1.4 — every ``question_id`` resolves to a written operational definition
    (``QUESTIONS`` below, mirroring SPEC.md §17). A question with no entry
    cannot ship.

Pure: no DB, no I/O, unit-tested.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── the instrument ──────────────────────────────────────────────────────────

VALUES = ("yes", "no", "neutral")

# +1 / 0 / -1. Signed so a mean over raters is directly the aggregate position,
# and so the mapping matches power_score's other terms (SPEC §7.2).
_VALUE_TERM = {"yes": 1.0, "neutral": 0.0, "no": -1.0}

# SPEC §6.2. bootstrap is a lane, not a panel: one rater on a model-proposed
# candidate. It is excluded from agreement statistics and from the gold set BY
# QUERY, which is only possible because the lane is stamped on the row.
LANES = ("bootstrap", "coach", "game_peer", "game_owner")

# The lanes whose rows may be aggregated into a panel label. TWO absences are
# deliberate, and each is the whole point of the constant:
#
#   bootstrap  — one rater on a MODEL-PROPOSED candidate (§6.2). Counting it
#                would make a single expert opinion look like consensus.
#   game_owner — §9.1's quorum is model + coach + PEER. The owner is not one of
#                the three, and they are rating their OWN recording: they know
#                what they intended, so their answer is self-assessment, not an
#                independent judgment. In v1.0 the lane carries no question at
#                all (§6.2, "plumbing only"), which makes this exclusion moot
#                today and load-bearing the day it stops being moot.
PANEL_LANES = ("coach", "game_peer")


# ── operational definitions (SPEC §17) ──────────────────────────────────────
#
# Mirrors SPEC.md §17. The wording IS the construct: changing it starts a new
# corpus, so a change means a NEW VERSION KEY here, never an edit in place.
# `_RETIRED` versions stay listed so historical rows remain interpretable.

QUESTIONS: dict[str, dict[str, str]] = {
    "conf-q-v1": {
        "state_id": "confidence",
        "text": "Does the speaker sound confident here?",
        "construct": (
            "How assured the speaker sounds in their DELIVERY of this "
            "moment. A property of the voice, not of the content."
        ),
        "not": (
            "Not authority (assured is not the same as commanding). "
            "Not feeling-of-knowing (certainty about WHAT is said, rather "
            "than assurance in HOW it is said). Not correctness, "
            "likeability or charisma."
        ),
        "anchor": (
            "Jiang & Pell 2017, Speech Communication 88:106-126 — listener "
            "panel >83% agreement; means 4.52 / 3.24 / 2.05 on 1-5."
        ),
    },
}

# The binary instrument this lane used before the ternary (SPEC D3). Listed so
# pre-cutover rows stay interpretable and separable; never offered to a rater.
_RETIRED_QUESTIONS = {
    "conf-q-v0": {
        "state_id": "confidence",
        "text": "(binary instrument — confident yes/no + intensity 1-5)",
    },
}

CURRENT_QUESTION_BY_STATE = {"confidence": "conf-q-v1"}


def question_for_state(state_id: Any) -> Optional[str]:
    """The current question version for a state, or None when the state has
    no written definition — which is the same as saying it cannot be asked."""
    return CURRENT_QUESTION_BY_STATE.get(str(state_id or "").strip())


def describe_question(question_version: Any) -> Optional[dict]:
    """The operational definition behind a stored rating, live or retired.
    Retired versions resolve so an old row can still be read; only live ones
    may be served to a rater."""
    key = str(question_version or "").strip()
    return QUESTIONS.get(key) or _RETIRED_QUESTIONS.get(key)


# ── validation ──────────────────────────────────────────────────────────────

def validate_rating(payload: Any) -> tuple[Optional[dict], Optional[str]]:
    """Validate one ternary rating -> ``(row, None)`` or ``(None, error)``.

    Body::

        { state_id: str,
          value: "yes"|"no"|"neutral",   # XOR unrateable
          unrateable?: bool,
          note?: str,
          latency_ms?: int }

    STRICT TYPES, no coercion — the same rule the coach confidence route and
    the peer-review route already hold. This is TRAINING DATA: a coerced value
    is a fabricated label, it records a human verdict no human gave, and it is
    indistinguishable from a real one afterwards. A caller sending the wrong
    type has a bug; a corpus that swallowed it has a lie in it.

    Legacy bodies (``{confident: bool}``) are NOT accepted here — the route
    translates them, so the translation stays visible in one place rather than
    being buried in a validator that appears to accept two instruments.
    """
    if not isinstance(payload, dict):
        return None, "body: must be an object"

    state_id = str(payload.get("state_id") or "").strip()
    if not state_id:
        return None, "state_id: required"
    question_version = question_for_state(state_id)
    if not question_version:
        # §1.4: no written definition, no question. Refusing here is what
        # stops a new construct entering the corpus by accident.
        return None, f"state_id: '{state_id}' has no operational definition"

    unrateable = payload.get("unrateable", False)
    if not isinstance(unrateable, bool):
        return None, "unrateable: must be true or false"

    value = payload.get("value")
    if unrateable:
        if value is not None:
            return None, "value: must be omitted when unrateable is true"
    else:
        if not isinstance(value, str) or value not in VALUES:
            return None, f"value: required, one of {', '.join(VALUES)}"

    latency_ms = payload.get("latency_ms")
    if latency_ms is not None:
        if isinstance(latency_ms, bool) or not isinstance(latency_ms, int):
            return None, "latency_ms: must be an integer (or omitted)"
        if latency_ms < 0:
            return None, "latency_ms: must not be negative"

    note = payload.get("note")
    if note is not None and not isinstance(note, str):
        return None, "note: must be a string"

    return {
        "state_id": state_id,
        "question_id": state_id,
        "question_version": question_version,
        "value": None if unrateable else value,
        "unrateable": unrateable,
        "note": (note.strip()[:1000] or None) if isinstance(note, str) else None,
        "latency_ms": latency_ms,
        # I1: never true for a rating. Stored so the invariant is auditable.
        "saw_model_output": False,
    }, None


def resolve_lane(session_source: Any, *, is_coach: bool,
                 is_owner: bool = False) -> str:
    """Which lane a rating belongs to (SPEC §6.2).

    An import (``source='training_import'``) rated by the coach is BOOTSTRAP,
    not coach: it is one rater on a model-proposed candidate from a corpus the
    founder assembled, which is not panel-grade however expert the rater. The
    distinction is invisible at write time and impossible to reconstruct
    later, which is exactly why it is stamped now.
    """
    if is_coach:
        return "bootstrap" if str(session_source or "") == "training_import" \
            else "coach"
    return "game_owner" if is_owner else "game_peer"


# ── aggregation ─────────────────────────────────────────────────────────────

_QUALITY_SHRINKAGE = 2.0


def quality(n_raters: Any, agreement: Any) -> float:
    """Confidence in an aggregated label, bounded (0, 1) — SPEC §7.2.

    SAMPLE SIZE DOMINATES AGREEMENT, by decision. A five-rater panel at 60%
    agreement (0.57) outweighs a two-rater unanimous one (0.50). That is the
    right intuition for a perceptual construct: the panel is estimating a
    POPULATION percept, so more independent witnesses beats fewer confident
    ones. Two people agreeing is a small sample, not a strong finding.

    The agreement term never zeroes the product — a genuinely ambiguous moment
    still carries half its size-derived weight, because ambiguity is a finding
    (I10) and not an absence of one.
    """
    try:
        n = max(0, int(n_raters))
        a = min(1.0, max(0.0, float(agreement)))
    except (TypeError, ValueError):
        return 0.0
    if n <= 0:
        return 0.0
    return (n / (n + _QUALITY_SHRINKAGE)) * (0.5 + 0.5 * a)


def aggregate(rows: Any, *, lanes: tuple = PANEL_LANES) -> Optional[dict]:
    """Aggregate raw ratings for ONE snippet into a panel label.

    Returns ``{value, agreement, n_raters, quality, by_value, unrateable_n}``
    or None when no row in an eligible lane carries an answer.

    ``lanes`` defaults to PANEL_LANES — **bootstrap and game_owner are both
    excluded**. bootstrap is one rater on a model-proposed candidate, so
    counting it as a panel member would make a single expert opinion look like
    consensus; game_owner is outside §9.1's model+coach+peer quorum and is the
    speaker judging their own recording. Pass ``lanes=LANES`` deliberately, and
    only for a corpus pull that wants everything.

    ``unrateable`` rows are counted but never aggregated: they carry no answer,
    so including them in ``n_raters`` would inflate quality on the strength of
    people who explicitly declined to judge. They are returned separately
    because the abstention rate is itself a signal — a moment most raters
    refuse is a fact about the moment.

    ``agreement`` is the modal share. At n=1 it is trivially 1.0, which is
    fine and not misleading: ``quality`` discounts a single rater to 0.33
    regardless, so sample size — not a fabricated agreement number — is what
    stops one opinion moving anything.
    """
    if not isinstance(rows, list):
        return None
    allowed = set(lanes or ())
    answered: list[str] = []
    unrateable_n = 0
    for r in rows:
        if not isinstance(r, dict):
            continue
        if r.get("lane") not in allowed:
            continue
        if r.get("unrateable"):
            unrateable_n += 1
            continue
        v = r.get("value")
        if isinstance(v, str) and v in VALUES:
            answered.append(v)

    n = len(answered)
    if n == 0:
        return None

    by_value = {v: answered.count(v) for v in VALUES}
    modal_n = max(by_value.values())
    agreement = modal_n / n
    value = sum(_VALUE_TERM[v] for v in answered) / n

    return {
        "value": round(value, 4),
        "agreement": round(agreement, 4),
        "n_raters": n,
        "quality": round(quality(n, agreement), 4),
        "by_value": by_value,
        "unrateable_n": unrateable_n,
    }


def corpus_summary(rows: Any) -> dict:
    """Class balance for a training pull, so a run can see whether the data is
    usable BEFORE it trains on it.

    A corpus that is 90% one class produces a model that says that class to
    everything, and it will report a flattering accuracy because the test set
    is skewed the same way. This is where that shows up — which is why the
    reader is balanced-metric only (SPEC §12.1) and never raw agreement.
    """
    rows = [r for r in (rows or []) if isinstance(r, dict)]
    by_value = {v: 0 for v in VALUES}
    by_lane: dict = {}
    unrateable_n = 0
    for r in rows:
        lane = r.get("lane") or "unknown"
        by_lane[lane] = by_lane.get(lane, 0) + 1
        if r.get("unrateable"):
            unrateable_n += 1
            continue
        v = r.get("value")
        if isinstance(v, str) and v in by_value:
            by_value[v] += 1
    answered = sum(by_value.values())
    return {
        "total": len(rows),
        "answered": answered,
        "unrateable": unrateable_n,
        "by_value": by_value,
        "by_lane": by_lane,
        "balance": ({k: round(c / answered, 3) for k, c in by_value.items()}
                    if answered else None),
        "raters": len({r.get("rater_id") for r in rows if r.get("rater_id")}),
        # The gate a trainer should read before it trains: 3 classes, so
        # chance is 1/3 and a corpus missing a class cannot teach the boundary.
        "classes_present": sum(1 for c in by_value.values() if c > 0),
    }
