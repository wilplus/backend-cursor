"""Confidence labelling (founder 2026-07-28) — the corpus for the app's core
function: recognising the confident snippet.

TWO PIECES, both pure:

  * ``validate_confidence_label`` — the coach's call on one snippet:
    ``confident`` yes/no, plus ``intensity`` 1-5 for how strongly. Binary
    first because the model's job is a binary recognition and a rater who
    must commit gives a cleaner boundary; the 1-5 is the same scale Jiang &
    Pell (2017) put in front of their listeners, which makes these numbers
    directly comparable to the published anchor AND the human side of the
    voice-confidence validation gate.

  * ``mixed_label_queue`` — WHICH pieces to put in front of the coach. It
    combines model-boundary examples, balanced predicted regions, and a
    uniform exploration sample. A model-only queue observes behavior it
    caused; the exploration slice is the unbiased evaluation window. Every
    selection carries server-side reason/probability provenance, which is
    persisted but never returned to the blind rater.

BLIND COACH. The queue carries the moment and nothing else: no band, no
score, no machine read of any kind. The composite decides who gets asked;
the coach decides the answer.

AC-9. ``intensity`` is a number and is coach->machine only. Nothing in this
module is ever serialized toward a student.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

SOURCES = ("coach", "game", "peer")

# Band edges on the voice-confidence spectrum ([-1, 1], 0 = the neutral dead
# zone). Deliberately coarse — these only decide who gets ASKED, so precision
# buys nothing and false precision would invite reading them as truth.
_CONFIDENT_MIN = 0.35
_DOUBTFUL_MAX = -0.35

# Small on purpose: review attention is the scarce resource, and a mixed 15
# beats a lopsided 60. Quotas are policy, not model output.
DEFAULT_QUEUE_SIZE = 15
EXPLORATION_SHARE = 0.20
BOUNDARY_SHARE = 0.40
SELECTION_POLICY_VERSION = "confidence-mixed-v1"


def validate_confidence_label(payload: Any) -> tuple[Optional[dict], Optional[str]]:
    """Validate one confidence label → ``(row, None)`` or ``(None, error)``.

    Body: ``{confident: bool, intensity?: 1..5, note?: str}``. ``confident``
    is required and must be a real boolean — a string "true" is rejected
    rather than coerced, because a rating corpus that quietly accepted
    truthy junk would be worse than one that refused it. ``intensity`` is
    optional (a coach may call it without grading it) but must be 1-5 when
    present. Pure."""
    if not isinstance(payload, dict):
        return None, "body: must be an object"

    confident = payload.get("confident")
    if not isinstance(confident, bool):
        return None, "confident: required, must be true or false"

    intensity = payload.get("intensity")
    if intensity is not None:
        if isinstance(intensity, bool) or not isinstance(intensity, int):
            return None, "intensity: must be an integer 1-5 (or omitted)"
        if not (1 <= intensity <= 5):
            return None, "intensity: must be between 1 and 5"

    note = payload.get("note")
    if note is not None and not isinstance(note, str):
        return None, "note: must be a string"

    source = (payload.get("source") or "coach")
    if source not in SOURCES:
        return None, f"source: must be one of {', '.join(SOURCES)}"

    return {
        "confident": confident,
        "intensity": intensity,
        "note": (note.strip()[:1000] or None) if isinstance(note, str) else None,
        "source": source,
    }, None


def _confidence_of(snippet: Any) -> Optional[float]:
    """The stored voice-confidence score for a piece, or None when unstamped
    (older takes, or too few measurable cues). Pure."""
    if not isinstance(snippet, dict):
        return None
    metrics = snippet.get("metrics")
    if not isinstance(metrics, dict):
        return None
    read = metrics.get("voice_confidence")
    if not isinstance(read, dict):
        return None
    v = read.get("score")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return None


def band_of(score: Any) -> str:
    """'confident' | 'neutral' | 'doubtful' | 'unscored'. Internal to
    selection — never returned to a labeller. Pure."""
    if not isinstance(score, (int, float)) or isinstance(score, bool):
        return "unscored"
    v = float(score)
    if v >= _CONFIDENT_MIN:
        return "confident"
    if v <= _DOUBTFUL_MAX:
        return "doubtful"
    return "neutral"


def mixed_label_queue(snippets: Any, *,
                      target_size: int = DEFAULT_QUEUE_SIZE,
                      seed: str = "") -> list:
    """Build one auditable mixed queue without exposing routing signals.

    The returned snippet copies carry a private ``_selection`` record:

    ``model_boundary``
        Scored clips nearest the decision boundary (active learning).
    ``band_balance``
        Round-robin coverage of confident/middle/doubtful/unscored regions.
    ``random_exploration``
        Uniform hash sample from everything left. This is the only slice that
        should be used as an unbiased evaluation estimate.

    Selection and final order are deterministic from ``seed`` so retries and
    reloads cannot silently change the cohort. With a random session UUID as
    seed, hash ranking is a reproducible uniform draw. Selection metadata is
    server-side only; :func:`queue_payload` is an allowlist and drops it.
    """
    rows_by_id: dict[str, dict] = {}
    for snippet in (snippets or []):
        if isinstance(snippet, dict) and snippet.get("id"):
            rows_by_id.setdefault(str(snippet["id"]), snippet)
    rows = list(rows_by_id.values())
    if not rows:
        return []

    try:
        requested = int(target_size)
    except (TypeError, ValueError):
        requested = DEFAULT_QUEUE_SIZE
    target = min(len(rows), max(0, requested))
    if target == 0:
        return []

    def _key(s: dict, purpose: str = "pick") -> str:
        return hashlib.sha1(
            f"{seed}:{purpose}:{s.get('id')}".encode("utf-8")
        ).hexdigest()

    exploration_n = max(1, round(target * EXPLORATION_SHARE))
    boundary_n = min(target - exploration_n,
                     max(1, round(target * BOUNDARY_SHARE)))
    balance_n = max(0, target - exploration_n - boundary_n)

    chosen: list[tuple[dict, str, float]] = []
    chosen_ids: set[str] = set()

    # 1. Model-boundary candidates. Unscored clips are not faked as zero;
    # they remain available to balanced/random selection.
    scored = [
        (row, score)
        for row in rows
        if (score := _confidence_of(row)) is not None
    ]
    scored.sort(key=lambda item: (
        abs(item[1]), _key(item[0], "boundary-tie")))
    for row, _score in scored[:boundary_n]:
        chosen.append((row, "model_boundary", 1.0))
        chosen_ids.add(str(row["id"]))

    # 2. Round-robin model-region coverage from what remains.
    buckets: dict[str, list] = {}
    for row in rows:
        if str(row["id"]) in chosen_ids:
            continue
        buckets.setdefault(band_of(_confidence_of(row)), []).append(row)
    for bucket in buckets.values():
        bucket.sort(key=lambda row: _key(row, "balance"))
    band_order = ("confident", "neutral", "doubtful", "unscored")
    while balance_n > 0 and any(buckets.get(band) for band in band_order):
        for band in band_order:
            if balance_n <= 0:
                break
            bucket = buckets.get(band) or []
            if not bucket:
                continue
            row = bucket.pop(0)
            chosen.append((row, "band_balance", 1.0))
            chosen_ids.add(str(row["id"]))
            balance_n -= 1

    # 3. Uniform exploration fills its own quota and any deterministic quota
    # that lacked enough candidates. Its inclusion probability is exact for
    # this remaining pool and is persisted for audit/evaluation weighting.
    remaining = [row for row in rows if str(row["id"]) not in chosen_ids]
    remaining.sort(key=lambda row: _key(row, "exploration"))
    random_n = min(target - len(chosen), len(remaining))
    random_probability = (random_n / len(remaining)) if remaining else 0.0
    for row in remaining[:random_n]:
        chosen.append((row, "random_exploration", random_probability))

    # Final ordering must not reveal the selection stratum to the rater.
    chosen.sort(key=lambda item: _key(item[0], "blind-order"))
    return [
        {
            **row,
            "_selection": {
                "policy_version": SELECTION_POLICY_VERSION,
                "reason": reason,
                "sampling_probability": round(float(probability), 6),
            },
        }
        for row, reason, probability in chosen
    ]


def selection_records(selected: Any) -> list[dict]:
    """Persistable queue provenance, separate from the blind payload."""
    out: list[dict] = []
    for row in (selected or []):
        if not isinstance(row, dict) or not row.get("id"):
            continue
        meta = row.get("_selection")
        if not isinstance(meta, dict):
            continue
        out.append({
            "snippet_id": str(row["id"]),
            "policy_version": meta.get("policy_version"),
            "reason": meta.get("reason"),
            "sampling_probability": meta.get("sampling_probability"),
        })
    return out


def stored_selection_records(context: Any) -> list[dict]:
    """Read the canonical persisted cohort with one legacy boundary adapter.

    New sessions store ``label_queue_selection`` records. Historical sessions
    stored only ``label_queue`` IDs; those remain reviewable but are marked
    ``legacy_unspecified`` and carry no fabricated sampling probability.
    """
    ctx = context if isinstance(context, dict) else {}
    canonical = ctx.get("label_queue_selection")
    if isinstance(canonical, list):
        out: list[dict] = []
        for item in canonical:
            if not isinstance(item, dict) or not item.get("snippet_id"):
                continue
            out.append({
                "snippet_id": str(item["snippet_id"]),
                "policy_version": item.get("policy_version"),
                "reason": item.get("reason"),
                "sampling_probability": item.get("sampling_probability"),
            })
        return out
    legacy = ctx.get("label_queue")
    if not isinstance(legacy, list):
        return []
    return [
        {
            "snippet_id": str(snippet_id),
            "policy_version": None,
            "reason": "legacy_unspecified",
            "sampling_probability": None,
        }
        for snippet_id in legacy if snippet_id
    ]


def queue_payload(snippets: Any) -> list:
    """The labelling queue as the coach sees it: the moment, and nothing that
    could hint at an answer.

    Explicitly an allowlist — the snippet row carries metrics with
    voice_confidence, acoustic_read and the tone word, any of which would
    anchor the label if it leaked into this payload (BLIND COACH). Pure."""
    out: list = []
    for s in (snippets or []):
        if not isinstance(s, dict) or not s.get("id"):
            continue
        out.append({
            "snippet_id": s.get("id"),
            "transcript": (s.get("transcript")
                           or s.get("transcript_excerpt") or ""),
            "audio_ref": (s.get("audio_segment_path") or s.get("audio_ref")
                          or s.get("storage_path")),
            "start_offset_ms": s.get("start_offset_ms"),
            "duration_ms": s.get("duration_ms"),
            "session_id": s.get("session_id"),
        })
    return out


def corpus_summary(label_rows: Any) -> dict:
    """Class balance for a confidence-corpus pull — so a training run can see
    whether the data is usable before it trains on it. A corpus that is 90%
    'confident: true' will produce a model that says yes to everything, and
    this is where that shows up."""
    rows = [r for r in (label_rows or []) if isinstance(r, dict)]
    # V2 FIRST: three perceptual positions plus two explicit utility states.
    # Legacy `neutral` (v1's IDK) and `unrateable` remain readable without
    # being reinterpreted as the new perceptual middle.
    # written before the migration. Counting only the binary here was the
    # BE sibling of the FE's pickLabel bug: a stored neutral vanished
    # from every count and the balance read as cleaner than the corpus.
    def _answer(r):
        v = r.get("value")
        if v in ("yes", "in_between", "no", "not_sure",
                 "audio_unclear", "neutral"):
            return v
        if r.get("confident") is True:
            return "yes"
        if r.get("confident") is False:
            return "no"
        return None

    yes = sum(1 for r in rows if _answer(r) == "yes")
    no = sum(1 for r in rows if _answer(r) == "no")
    in_between = sum(1 for r in rows if _answer(r) == "in_between")
    not_sure = sum(1 for r in rows
                   if _answer(r) in ("not_sure", "neutral"))
    audio_unclear = sum(1 for r in rows
                        if (_answer(r) == "audio_unclear"
                            or r.get("unrateable") is True))
    answered = yes + no + in_between
    by_intensity: dict = {}
    for r in rows:
        v = r.get("intensity")
        if isinstance(v, int) and not isinstance(v, bool):
            by_intensity[v] = by_intensity.get(v, 0) + 1
    rated = sum(by_intensity.values())
    return {
        "total": len(rows),
        "confident_yes": yes,
        "confident_no": no,
        "in_between": in_between,
        "not_sure": not_sure,
        # Two abstentions are not two labels — unrateable rows carry no
        # answer and stay out of `balance` (same rule as aggregate()).
        "audio_unclear": audio_unclear,
        "unrateable": audio_unclear,
        "balance": (round(yes / answered, 3) if answered else None),
        "by_intensity": by_intensity,
        "mean_intensity": (
            round(sum(k * n for k, n in by_intensity.items()) / rated, 2)
            if rated else None
        ),
        "raters": len({r.get("rater_id") for r in rows if r.get("rater_id")}),
    }
