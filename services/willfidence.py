"""willfidence-v1-machine: the machine's private read of each moment
(V4 Phase 1, B1.3; build plan D-ML-8; SPEC §17 ``willfidence-v1``; founder
S-B1 A, S-B1b A, Q-B1 A, QG8 A, V4 A, V5 B, V6 A, W1, W2, H3; migration 0449).

WHAT IS READ, per moment (one block of the Take's dark frame, about 75
words). Every value is 0 to 1 and never reaches a screen (AC-9).

  S          the machine's sound read: the mean of the moment's clips'
             universal-v3 reads (-1..+1), stretched evenly to 0..1 (V4 A).
  Filler     how free the moment is of filler words (S-B1 A): the share of
             its words that are unambiguous fillers (``FILLER_TERMS``), on
             the stricter scale (V5 B): none gives 1, ``CEILING_PER_100`` or
             more per 100 words gives 0, a straight line between. "So",
             "like" and "right" never count.
  Hedging    how directly the speaker commits (S-B1 A): the share of its
             words that are unambiguous hedges (``HEDGE_TERMS``), the same
             scale. Modal words like "might" or "could" never count.
  Slide fit  whether the moment says what its slide is about (S-B1 A): 1 if
             it fully makes at least one of the slide's points, 0.5 if it
             partly does, 0 if none, by the point-by-point check the app
             already runs (``slide_stickiness`` on each clip; the moment
             takes its best clip). None when no clip was checked.
  Holding together  whether its sentences follow on as one line of thought
             (S-B1 A): 1 yes, 0.5 partly, 0 no, from the one batched call
             per Take that also tags the role (``services.v4_take_tags``).
  W          the mean of the word signals present (H3: the partial W, until
             naturalness and the full WORDS exist).
  Boxes      willfident S*W, hollow S(1-W), hidden (1-S)W, lost (1-S)(1-W).
  Spread     empty (V6 A): with one judge there is nothing to compare.

The database computes S, W, the boxes and the Take's line from what the app
sends (``record_v4_willfidence_reads_v1``); the pure functions here are the
same rules, so a reader of either can check the other (the tests pin them
equal). The Take's willfidence is the mean of S*W over its rated random
moments (W1, 0447's draw); W2 gives its status.

WHEN. A queued job after the Take's random moments are drawn, never on the
request path (LIVE LOOP). It reads, tags and writes once per Take.
"""
from __future__ import annotations

import logging
from fractions import Fraction
from typing import Any, Iterable, Optional

from services import verbal_markers

logger = logging.getLogger(__name__)

READ_VERSION = "willfidence-v1-machine"
SOUND_VERSION = "voice-confidence-universal-v3"
TASK_PATH = "services.willfidence.run_read"

#: V5 B: this many per 100 words or more gives 0. "A starting value you can
#: change later" — a change is a new read version.
CEILING_PER_100 = 10

#: The unambiguous entries of the lexicons (verbal_markers, SPEC D21): the
#: ones with no common non-marker use. Every ambiguous term ("so", "like",
#: "right", the modals) is left out by construction (S-B1 A).
FILLER_TERMS = tuple(sorted(
    term for term, ambiguous in verbal_markers.lexicon(verbal_markers.TIC).items()
    if not ambiguous))
HEDGE_TERMS = tuple(sorted(
    term for term, ambiguous in verbal_markers.lexicon(verbal_markers.HEDGE).items()
    if not ambiguous))

#: W2: a Take or a speaker with more than this share of random moments
#: unrateable reads "audio problem"; fewer than MIN_RATED rated moments read
#: "not enough data".
MAX_DROPPED = Fraction(3, 10)
MIN_RATED = 10


# ── the signals ─────────────────────────────────────────────────────────────

def stretch(score: Any) -> Optional[float]:
    """V4 A: -1 becomes 0, 0 becomes 0.5, +1 becomes 1."""
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    if not -1.0 <= float(score) <= 1.0:
        return None
    return (float(score) + 1.0) / 2.0


def scale(marks: int, words: int) -> Optional[float]:
    """V5 B: 1 at no marks, 0 at CEILING_PER_100 or more per 100 words."""
    if words <= 0:
        return None
    per_100 = 100.0 * marks / words
    return max(0.0, 1.0 - per_100 / CEILING_PER_100)


def filler(text: Any) -> Optional[float]:
    counted = verbal_markers.count(text)
    return scale(counted[verbal_markers.TIC]["strict"], counted["n_words"])


def hedging(text: Any) -> Optional[float]:
    counted = verbal_markers.count(text)
    return scale(counted[verbal_markers.HEDGE]["strict"], counted["n_words"])


def slide_fit(clip_metrics: Iterable[Any]) -> Optional[float]:
    """The moment's best clip by the app's point-by-point check."""
    found: list[float] = []
    for metrics in clip_metrics:
        sticky = (metrics or {}).get("slide_stickiness") if isinstance(metrics, dict) else None
        value = sticky.get("composite") if isinstance(sticky, dict) else None
        if isinstance(value, (int, float)) and not isinstance(value, bool) \
                and float(value) in (0.0, 0.5, 1.0):
            found.append(float(value))
    return max(found) if found else None


def sound(clip_metrics: Iterable[Any]) -> Optional[float]:
    """S: the clips' universal-v3 reads, averaged, then stretched (V4 A)."""
    scores: list[float] = []
    for metrics in clip_metrics:
        read = (metrics or {}).get("voice_confidence") if isinstance(metrics, dict) else None
        if not isinstance(read, dict) or read.get("version") != SOUND_VERSION:
            continue
        score = read.get("score")
        if isinstance(score, (int, float)) and stretch(score) is not None:
            scores.append(float(score))
    return stretch(sum(scores) / len(scores)) if scores else None


def partial_w(*signals: Optional[float]) -> Optional[float]:
    present = [float(s) for s in signals if s is not None]
    return sum(present) / len(present) if present else None


def boxes(s: Optional[float], w: Optional[float]) -> Optional[dict]:
    if s is None or w is None:
        return None
    return {"willfident": s * w, "hollow": s * (1 - w),
            "hidden": (1 - s) * w, "lost": (1 - s) * (1 - w)}


def status(random_moments: int, rated: int) -> str:
    """W2, in this order: too many dropped is an audio problem first."""
    dropped = random_moments - rated
    if random_moments <= 0:
        return "not_enough_data"
    if Fraction(dropped, random_moments) > MAX_DROPPED:
        return "audio_problem"
    if rated < MIN_RATED:
        return "not_enough_data"
    return "measured"


def summary(reads: Iterable[dict]) -> dict:
    """The Take's (or speaker's) line over the random moments (W1, W2)."""
    random_rows = [r for r in reads if r.get("is_random")]
    rated = [r["s"] * r["w"] for r in random_rows
             if r.get("s") is not None and r.get("w") is not None]
    return {
        "random_moments": len(random_rows),
        "rated_random_moments": len(rated),
        "willfidence": sum(rated) / len(rated) if rated else None,
        "status": status(len(random_rows), len(rated)),
    }


# ── one Take ────────────────────────────────────────────────────────────────

def word_signals(text: str, clip_metrics: list[Any]) -> dict:
    return {"filler": filler(text), "hedging": hedging(text),
            "slide_fit": slide_fit(clip_metrics)}


def take_reads(frame: dict, snippets: Iterable[Any],
               tags: Optional[dict]) -> list[dict]:
    """What the app sends the database: per frame block, its three local
    word signals, holding together and role from the call. Pure."""
    by_id = {str(row.get("id")): row for row in snippets or []
             if isinstance(row, dict) and row.get("id")}
    out: list[dict] = []
    for block in frame.get("blocks") or []:
        block_id = str(block.get("block_id") or "")
        clips: list[dict] = [
            by_id[str(sid)] for sid in block.get("snippet_ids") or []
            if str(sid) in by_id]
        text = " ".join(str(clip.get("transcript") or "") for clip in clips).strip()
        tag = (tags or {}).get(block_id) or {}
        out.append({
            "block_id": block_id,
            **word_signals(text, [clip.get("metrics") for clip in clips]),
            "holding_together": tag.get("holding_together"),
            "role": tag.get("role"),
        })
    return out


def moments_text(frame: dict, snippets: Iterable[Any]) -> list[dict]:
    by_id = {str(row.get("id")): row for row in snippets or []
             if isinstance(row, dict) and row.get("id")}
    return [
        {"ref": str(block.get("block_id") or ""),
         "text": " ".join(str((by_id.get(str(sid)) or {}).get("transcript") or "")
                          for sid in block.get("snippet_ids") or []).strip()}
        for block in frame.get("blocks") or []
    ]


def enqueue_read(take_session_id: Any) -> bool:
    """Ask for this Take's read, off the request path. Never raises."""
    take = str(take_session_id or "").strip()
    if not take:
        return False
    try:
        from services import job_queue
        if not job_queue.queue_configured():
            return False
        return job_queue.enqueue(
            TASK_PATH, take, queue=job_queue.bake_queue_name(),
            rq_job_id=f"v4-willfidence:{take}")
    except Exception as error:  # noqa: BLE001 -- the Take stands
        logger.warning("v4 willfidence not enqueued take=%s: %s", take, error)
        return False


def _tags_under_authority(database: Any, frame: dict, snippets: list,
                          take: str) -> Optional[dict]:
    """The one call per Take, through the processing-authorization path
    (PLF1): inside a protected provider scope for this Take when the mode
    enforces, so the call takes its own permit. A refusal is no tags."""
    from services.v4_take_tags import tag_take
    moments = moments_text(frame, snippets)
    from services.processing_authorization import ProcessingAuthorizationService
    authorization = ProcessingAuthorizationService(database)
    if not authorization.enforced:
        return tag_take(moments, session_id=take)
    import uuid
    from services.authorized_provider import (
        AuthorizedProviderAdapter, ProviderCoordinates, protected_provider_scope)
    session = database.v2_get_session_by_id(take) or {}
    principal = authorization.resolve_acquisition_principal(
        str(session.get("owner_principal_id") or ""),
        user_id=str(session.get("user_id") or "") or None)
    if not principal:
        return None
    adapter = AuthorizedProviderAdapter(
        database,
        ProviderCoordinates(principal, take, str(frame.get("recording_id") or "") or None),
        authorization=authorization)
    with protected_provider_scope(
            adapter, idempotency_prefix=f"v4-willfidence:{take}:{uuid.uuid4()}"):
        return tag_take(moments, session_id=take)


def run_read(take_session_id: str) -> Optional[dict]:
    """RQ entry point: read one Take once. Never raises."""
    take = str(take_session_id or "").strip()
    try:
        from services.db import db
        frame = db.get_v4_dark_frame(take)
        if not isinstance(frame, dict):
            return None
        snippets = db.get_snippets_by_session(take) or []
        try:
            tags = _tags_under_authority(db, frame, snippets, take)
        except Exception as error:  # noqa: BLE001 -- refused or failed: no tags
            logger.warning("v4 willfidence tags refused take=%s: %s", take, error)
            tags = None
        return db.record_v4_willfidence_reads(take, take_reads(frame, snippets, tags))
    except Exception as error:  # noqa: BLE001 -- dark measure; logged
        logger.warning("v4 willfidence read failed take=%s: %s", take, error)
        return None
