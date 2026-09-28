"""The foundation confidence frame: what the dark producer's worker builds.

G-6 (audit 2026-09-22). Every piece of the blind-label chain existed except
this one: a Take promoted under ``founder_canary`` lands on the confidence
outbox, ``DarkConfidenceWorker`` can claim it, ``finalize_mlc2_confidence_frame_v1``
can store a sampling frame, and the D5 coach batch can turn a stored evidence
span into a blind packet. But the worker's ``frame_factory`` was a placeholder
("a future activation supplies a reviewed frame_factory"), and nothing
registered the worker, so no coach or peer judgment on a confident moment
could ever be recorded. This module is that factory, plus the sweep that runs
the worker, plus the one-line boot report.

What a frame is. One candidate per snippet of the Take, each pointing at an
exact span of the Take's own R2 audio object (the one the source manifest
proved). The evidence coordinates are the snippet's ``start_offset_ms`` and
``start_offset_ms + duration_ms`` on that object, which is exactly what
``exercise_evidence_matches_audio_v1`` compares against an exercise audio
lineage, so a stored span is usable by the D5 batch without any adapter.

The classifier is the foundation detector already in production: the
universal delivery-signal composite stamped on every piece
(``voice_confidence``, ``voice-confidence-universal-v3``). Its stamped score in
[-1, 1] becomes a three-class foundation prediction over the instrument's
perceptual answers (yes / in_between / no) at the detector's own band
thresholds (±0.5). ``assignment_origin`` is ``foundation``: nothing here is
trained, calibrated or learned, and the probability distribution is a
deterministic, versioned transform of the score, recorded so a later trained
model can be compared against it. Nothing in the frame carries transcript
text, and nothing here ever reaches a user (the frame is written to the
``ml_*`` tables only; AC-9 is not in play).

Selection follows contract K9: the deterministic pick is the eligible clip
closest to a class boundary (model-boundary active learning), and with the
contract's fixed 20% probability a uniformly random eligible clip is taken
instead (the unbiased window). Every draw, seed and per-candidate inclusion
probability is recorded. Exactly one clip is selected per Take.

Replay-stable by construction. ``finalize_mlc2_confidence_frame_v1`` compares a
replayed frame's pool hash with the stored one and refuses a different frame,
so every id, timestamp and draw here is a pure function of the outbox event
and the Take's snippets: ids are uuid5 of the event's idempotency key, the run
timestamps are the event's ``occurred_at``, the RNG is a sha256 counter seeded
from the idempotency key.

The mode stays ``dark``. ``start_confidence_producer_chain`` starts nothing
unless ``MLC2_CONFIDENCE_CUTOVER_MODE`` is ``founder_canary`` (a code change the
founder makes after the readiness report is green), and the sweep re-checks
the mode on every run, so a chain that outlives a rollback to ``killed``
stops on its next tick.
"""
from __future__ import annotations

import hashlib
import logging
import math
import uuid
from typing import Any, Callable, Mapping, Optional, Sequence

from services.mlc2_confidence import (
    EXPLORATION_PROBABILITY,
    SELECTION_EXECUTION_KIND,
    ConfidenceSamplingFrame,
)
from services.mlc2_confidence_producer import ConfidenceProducerEvent
from services.mlc2_foundation import Mlc2ContractError
from services.voice_confidence import VERSION as DETECTOR_VERSION
from services.voice_confidence import band, stamped_score

logger = logging.getLogger(__name__)

FRAME_VERSION = "confidence-frame-foundation-v1"
CANDIDATE_SET_VERSION = "confidence-frame-v1"
CLASSIFIER_MODEL_ID = "voice-confidence-foundation"
SELECTION_POLICY_VERSION = "confidence-selection-boundary-plus-random-v1"
ELIGIBILITY_POLICY_VERSION = "confidence-eligibility-v1"
THRESHOLD_VERSION = "voice-confidence-thresholds-v3"
TAXONOMY_VERSION = "conf-q-v2"          # SPEC-DECISIONS-LOG §K1
OUTPUT_SCHEMA_VERSION = "confidence-output-foundation-v1"
EVIDENCE_SCHEMA_VERSION = "audio-span-v1"
RNG_ALGORITHM = "sha256-counter-v1"

#: A clip shorter than this cannot be rated blind: the packet plays the exact
#: span and nothing else. Excluded with `audio_too_short`, never silently.
MIN_CLIP_MS = 1000

#: The detector's own band edges (services/voice_confidence.py `band`): at or
#: above +0.5 the cues read as the instrument's `yes`, at or below -0.5 as
#: `no`, between them `in_between`. Recorded on every classification run.
YES_AT_OR_ABOVE = 0.5
NO_AT_OR_BELOW = -0.5

PERCEPTUAL_CLASSES = ("yes", "in_between", "no")

_NAMESPACE = uuid.UUID("7f0f1b8e-3a2d-4c5e-9b6a-1d2e3f4a5b6c")


class NoEligibleConfidenceClip(Mlc2ContractError):
    """The Take has no clip a blind rater could be asked about."""


# ── deterministic identity ──────────────────────────────────────────────────

def _stable_id(*parts: Any) -> str:
    return str(uuid.uuid5(_NAMESPACE, ":".join(str(p) for p in parts)))


def _sha256_text(*parts: Any) -> str:
    return hashlib.sha256(":".join(str(p) for p in parts).encode()).hexdigest()


def _draw(seed: str, index: int) -> float:
    """Uniform in [0, 1) from a sha256 counter; recorded, never re-rolled."""
    digest = hashlib.sha256(f"{seed}:{index}".encode()).hexdigest()
    return int(digest[:13], 16) / float(1 << 52)


# ── the foundation prediction ───────────────────────────────────────────────

def foundation_prediction(score: float) -> dict[str, Any]:
    """Three-class foundation read of one stamped score.

    The predicted class is the band the detector already assigns; the
    distribution is a fixed transform in which the predicted class always
    carries at least half the mass, so argmax and class agree, and the rest
    goes to the neighbouring class(es) in proportion to how near the score
    sits to their boundary. It is a versioned convention, not a calibration.
    """
    s = max(-1.0, min(1.0, float(score)))
    if s >= YES_AT_OR_ABOVE:
        certainty = (s - YES_AT_OR_ABOVE) / (1.0 - YES_AT_OR_ABOVE)
        p = 0.5 + 0.5 * certainty
        distribution = {"yes": p, "in_between": 1.0 - p, "no": 0.0}
        predicted = "yes"
    elif s <= NO_AT_OR_BELOW:
        certainty = (NO_AT_OR_BELOW - s) / (1.0 + NO_AT_OR_BELOW)
        p = 0.5 + 0.5 * certainty
        distribution = {"no": p, "in_between": 1.0 - p, "yes": 0.0}
        predicted = "no"
    else:
        certainty = 1.0 - abs(s) / YES_AT_OR_ABOVE
        p = 0.5 + 0.5 * certainty
        toward_yes = (s - NO_AT_OR_BELOW) / (YES_AT_OR_ABOVE - NO_AT_OR_BELOW)
        distribution = {
            "in_between": p,
            "yes": (1.0 - p) * toward_yes,
            "no": (1.0 - p) * (1.0 - toward_yes),
        }
        predicted = "in_between"
    rounded = {k: round(v, 6) for k, v in distribution.items()}
    return {
        "predicted_value": predicted,
        "confidence_score": round(p, 6),
        "probability_distribution": rounded,
    }


def boundary_distance(score: float) -> float:
    """How far a score sits from the nearest class boundary (lower = more
    informative for a blind rating, contract K9's active-learning slice)."""
    return round(min(abs(score - YES_AT_OR_ABOVE), abs(score - NO_AT_OR_BELOW)), 6)


# ── the frame ───────────────────────────────────────────────────────────────

def _int_or_none(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def build_foundation_frame(
    event: ConfidenceProducerEvent,
    *,
    snippets: Sequence[Mapping[str, Any]],
) -> ConfidenceSamplingFrame:
    """A complete, replay-stable sampling frame for one promoted Take."""
    envelope = event.envelope()
    manifest = dict(event.payload.get("source_manifest") or {})
    audio = dict(manifest.get("audio") or {})
    key = envelope.idempotency_key
    occurred = envelope.occurred_at.isoformat()
    object_id = _stable_id(FRAME_VERSION, "object", audio.get("object_key"))
    object_metadata = {
        "id": object_id,
        "bucket": audio.get("bucket"),
        "object_key": audio.get("object_key"),
        "sha256": audio.get("sha256"),
        "byte_size": audio.get("byte_size"),
        "content_type": audio.get("content_type"),
    }

    pool: list[dict[str, Any]] = []
    without_interval = 0
    for snippet in snippets:
        snippet_id = str(snippet.get("id") or "")
        if not snippet_id:
            continue
        start = _int_or_none(snippet.get("start_offset_ms"))
        duration = _int_or_none(snippet.get("duration_ms"))
        if start is None or duration is None or start < 0 or duration <= 0:
            # No exact span means no evidence at all, and a candidate without
            # evidence cannot exist in the frame. Counted, not silently gone.
            without_interval += 1
            continue
        end = start + duration
        score = stamped_score(snippet.get("metrics"))
        exclusion: Optional[str] = None
        if duration < MIN_CLIP_MS:
            exclusion = "audio_too_short"
        elif score is None:
            exclusion = "no_confidence_read"
        evidence = {
            "id": _stable_id(FRAME_VERSION, key, "evidence", snippet_id),
            "coordinates": {"start_ms": start, "end_ms": end},
            "content_sha256": _sha256_text(
                EVIDENCE_SCHEMA_VERSION, audio.get("sha256"), start, end
            ),
            "evidence_schema_version": EVIDENCE_SCHEMA_VERSION,
            "object": dict(object_metadata),
        }
        candidate: dict[str, Any] = {
            "id": _stable_id(FRAME_VERSION, key, "candidate", snippet_id),
            "clip_id": snippet_id,
            "candidate_key": f"snippet:{snippet_id}",
            "evidence": evidence,
            "eligible": exclusion is None,
            "exclusion_reason_code": exclusion,
            "selected": False,
            "selection_mode": "excluded" if exclusion else "not_selected",
            "selection_reason_code": (
                f"ineligible_{exclusion}" if exclusion else "ranked_not_selected"
            ),
            "sampling_probability": 0,
            "rng_draw_index": None,
            "score": None,
            "rank": None,
        }
        if exclusion is None and score is not None:
            read = foundation_prediction(score)
            stamp = dict((snippet.get("metrics") or {}).get("voice_confidence") or {})
            candidate["prediction"] = {
                "id": _stable_id(FRAME_VERSION, key, "prediction", snippet_id),
                **read,
                "raw_output": {
                    "score": score,
                    "band": band(score),
                    "cues": stamp.get("cues"),
                    "baseline": stamp.get("baseline"),
                    "detector_version": stamp.get("version"),
                },
                "output_schema_version": OUTPUT_SCHEMA_VERSION,
            }
            candidate["score"] = boundary_distance(score)
            candidate["_order"] = (candidate["score"], start, snippet_id)
        pool.append(candidate)

    # The pool's order is part of the hashed frame, so it is the Take's
    # order (start offset, then id), never the order the rows arrived in.
    pool.sort(key=lambda c: (c["evidence"]["coordinates"]["start_ms"], c["clip_id"]))
    eligible = [c for c in pool if c["eligible"]]
    if not eligible:
        raise NoEligibleConfidenceClip(
            "no eligible confidence clip in this Take"
        )
    eligible.sort(key=lambda c: c["_order"])
    for rank, candidate in enumerate(eligible, start=1):
        candidate["rank"] = rank
    for candidate in pool:
        candidate.pop("_order", None)

    n = len(eligible)
    seed = _sha256_text(SELECTION_POLICY_VERSION, key)
    explore_draw = _draw(seed, 0)
    rng_draws: list[dict[str, Any]] = [
        {"index": 0, "value": explore_draw, "purpose": "explore_or_exploit"},
    ]
    if explore_draw < EXPLORATION_PROBABILITY:
        pick_draw = _draw(seed, 1)
        rng_draws.append({"index": 1, "value": pick_draw, "purpose": "uniform_pick"})
        chosen = eligible[min(n - 1, int(math.floor(pick_draw * n)))]
        chosen["selection_mode"] = "exploration"
        chosen["selection_reason_code"] = "random_exploration"
        chosen["rng_draw_index"] = 1
    else:
        chosen = eligible[0]
        chosen["selection_mode"] = "deterministic"
        chosen["selection_reason_code"] = "closest_to_class_boundary"
    chosen["selected"] = True
    share = EXPLORATION_PROBABILITY / n
    for candidate in eligible:
        candidate["sampling_probability"] = round(
            share + (1.0 - EXPLORATION_PROBABILITY if candidate["rank"] == 1 else 0.0), 9
        )

    request_hash = _sha256_text(FRAME_VERSION, key, envelope.take_id, n, len(pool))
    classification_run = {
        "id": _stable_id(FRAME_VERSION, key, "classification_run"),
        "provider": "willab",
        "model_id": CLASSIFIER_MODEL_ID,
        "assignment_origin": "foundation",
        "assignment_version": DETECTOR_VERSION,
        "code_version": FRAME_VERSION,
        "configuration": {
            "min_clip_ms": MIN_CLIP_MS,
            "classes": list(PERCEPTUAL_CLASSES),
            "snippets_without_interval": without_interval,
        },
        "request_sha256": request_hash,
        "started_at": occurred,
        "completed_at": occurred,
        "feature_schema_version": DETECTOR_VERSION,
        "feature_extractor_version": DETECTOR_VERSION,
        "detector_version": DETECTOR_VERSION,
        "threshold_version": THRESHOLD_VERSION,
        "taxonomy_version": TAXONOMY_VERSION,
        "threshold_snapshot": {
            "yes_at_or_above": YES_AT_OR_ABOVE,
            "no_at_or_below": NO_AT_OR_BELOW,
        },
    }
    selection_run = {
        "id": _stable_id(FRAME_VERSION, key, "selection_run"),
        "provider": "deterministic_policy",
        "model_id": SELECTION_POLICY_VERSION,
        "assignment_origin": "deterministic_policy",
        "assignment_version": SELECTION_POLICY_VERSION,
        "code_version": FRAME_VERSION,
        "configuration": {"rank_by": "boundary_distance_then_start_offset"},
        "request_sha256": request_hash,
        "started_at": occurred,
        "completed_at": occurred,
        "execution_kind": SELECTION_EXECUTION_KIND,
        "selection_policy_version": SELECTION_POLICY_VERSION,
        "eligibility_policy_version": ELIGIBILITY_POLICY_VERSION,
        "threshold_version": THRESHOLD_VERSION,
        "rng_algorithm": RNG_ALGORITHM,
        "rng_seed": seed,
        "exploration_probability": EXPLORATION_PROBABILITY,
        "rng_draws": rng_draws,
    }
    return ConfidenceSamplingFrame(
        classification_run=classification_run,
        selection_run=selection_run,
        candidate_set_id=_stable_id(FRAME_VERSION, key, "candidate_set"),
        candidate_set_version=CANDIDATE_SET_VERSION,
        candidates=pool,
    )


def foundation_frame_factory(
    database: Any,
) -> Callable[[ConfidenceProducerEvent], ConfidenceSamplingFrame]:
    """The reviewed ``frame_factory`` for ``DarkConfidenceWorker``: reads the
    Take's snippet rows (offsets and stamped metrics) and builds the frame."""

    def factory(event: ConfidenceProducerEvent) -> ConfidenceSamplingFrame:
        take_id = str(event.envelope().take_id)
        rows = database.get_snippets_by_session(take_id) or []
        return build_foundation_frame(event, snippets=rows)

    return factory


# ── the sweep that runs the worker, and the boot line ───────────────────────

SWEEP_TASK_PATH = "services.mlc2_confidence_frame_factory.sweep_confidence_outbox"
CHAIN_LEASE_KEY = "willab:confidence-producer:chain"
SWEEP_INTERVAL_SECONDS = 30
LEASE_INTERVALS = 4


def _mode() -> Any:
    from services.mlc2_confidence_cutover import configured_confidence_cutover

    return configured_confidence_cutover()


def _own_lease(conn: Any, chain_id: str, *, ttl_seconds: int) -> bool:
    """Take or renew this chain's lease; False when another chain owns it."""
    if conn.set(CHAIN_LEASE_KEY, chain_id, nx=True, ex=ttl_seconds):
        return True
    holder = conn.get(CHAIN_LEASE_KEY)
    if isinstance(holder, bytes):
        holder = holder.decode()
    if holder != chain_id:
        return False
    conn.expire(CHAIN_LEASE_KEY, ttl_seconds)
    return True


def sweep_confidence_outbox(chain_id: str) -> dict[str, Any]:
    """One tick: claim leased confidence events, build and finalize a frame
    for each, then re-arm while this chain still owns the lease.

    Re-checks the cutover mode first, so a rollback to ``killed`` (or a
    container still running an older constant) ends the chain at its next
    tick without a deploy of anything else.
    """
    state = _mode()
    if not state.canonical_writes_enabled:
        return {"skipped": state.mode, "claimed": 0}
    from services import job_queue
    from services.db import db
    from services.mlc2_confidence import Mlc2ConfidenceStore
    from services.mlc2_confidence_producer import (
        DarkConfidenceWorker,
        Mlc2ConfidenceProducerStore,
    )

    worker_id = f"confidence-producer:{chain_id[:12]}"
    producer_store = Mlc2ConfidenceProducerStore(db.client)
    worker = DarkConfidenceWorker(
        producer_store=producer_store,
        frame_store=Mlc2ConfidenceStore(db.client),
        frame_factory=foundation_frame_factory(db),
    )
    claimed = producer_store.claim(worker_id=worker_id)
    finalized = failed = 0
    for row in claimed:
        try:
            worker.process_claimed(row, worker_id=worker_id)
            finalized += 1
        except Exception as error:  # noqa: BLE001 - the worker already failed the event
            failed += 1
            logger.warning("confidence frame failed event=%s: %s",
                           row.get("id"), type(error).__name__)
    conn = job_queue.get_redis()
    rearmed = False
    if conn is not None and _own_lease(
            conn, chain_id, ttl_seconds=SWEEP_INTERVAL_SECONDS * LEASE_INTERVALS):
        rearmed = job_queue.enqueue(
            SWEEP_TASK_PATH, chain_id, delay_seconds=SWEEP_INTERVAL_SECONDS)
    return {"claimed": len(claimed), "finalized": finalized,
            "failed": failed, "rearmed": rearmed}


def start_confidence_producer_chain() -> str:
    """Called once at worker boot. Returns the one line the boot log prints:
    the mode, and whether a chain was started, so the state of the producer
    is visible where the other gate flags are (CONFIG-FIRST)."""
    state = _mode()
    if not state.canonical_writes_enabled:
        return (f"{state.mode}: not started (MLC2_CONFIDENCE_CUTOVER_MODE="
                f"{state.mode}; claims nothing, writes nothing)")
    from services import job_queue

    conn = job_queue.get_redis()
    if conn is None:
        return f"{state.mode}: broker unavailable, chain not started"
    chain_id = uuid.uuid4().hex
    if not _own_lease(conn, chain_id,
                      ttl_seconds=SWEEP_INTERVAL_SECONDS * LEASE_INTERVALS):
        return f"{state.mode}: chain already running elsewhere"
    if not job_queue.enqueue(SWEEP_TASK_PATH, chain_id,
                             delay_seconds=SWEEP_INTERVAL_SECONDS):
        return f"{state.mode}: chain {chain_id} could not be enqueued"
    return f"{state.mode}: chain {chain_id} started (every {SWEEP_INTERVAL_SECONDS}s)"
