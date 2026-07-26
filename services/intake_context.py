"""Per-session speech-context intake (Task 9).

The user fills out a tiny 3-field form before a full-audit / upload-
recording run so the downstream pacer + tone calibrator + snippet
scorer have actual context about what they're listening to:

    topic                  — what the user is speaking about
    audience               — who they're addressing
    target_length_seconds  — how long the talk is meant to run

All three fields are optional. NULL throughout = "use defaults"
(pre-task-9 behaviour) which keeps in-flight legacy jobs unaffected.

Two entry points:

  validate_intake_context_body(body)
    Manual validator that matches the rest of v2_routes.py's
    style (the codebase has no Pydantic dependency). Returns the
    cleaned dict on success; raises IntakeContextError with a
    user-friendly message on failure.

  snapshot_intake_context(session_id)
    Read the persisted blob from v2_sessions.intake_context AT
    ENQUEUE TIME so a user editing the form between submit and
    job-pickup can't drift the payload mid-pipeline. Wraps
    db.get_session_intake_context with one extra guarantee — the
    returned dict (if any) carries the three canonical keys with
    their None-or-value, so consumers can use a single .get()
    pattern without re-checking shape.

The route handler in routes/v2_routes.py owns the
GET/PUT /v2/user/sessions/<id>/intake-context endpoints; this
module is the validation + snapshot layer they call into.
"""
from __future__ import annotations

import logging
from typing import Any, Optional


logger = logging.getLogger(__name__)


# Bounds match the FE form's UX: short tags, not paragraphs.
_MAX_TEXT_LEN = 200
# Seconds: 30s minimum keeps the form honest (anything shorter is
# the warmup gate), 7200s = 2h is the longest realistic talk.
_MIN_TARGET_SECONDS = 30
_MAX_TARGET_SECONDS = 7200

# domain_vocabulary (willab beta §4): editable list of Whisper-priming
# terms, defaulted from the profile domain's seed (services.domains).
# Short tags, bounded count so the JSONB blob + Whisper prompt stay
# small.
_MAX_VOCAB_TERMS = 50
_MAX_VOCAB_TERM_LEN = 40

# Slide-deck context (UX Wave 4 §S): per-slide {title, body} (body free text,
# newlines = bullets) + the served-PDF ref + the tap-advance timeline. Bounded
# so the JSONB blob stays sane. The slides text feeds Whisper priming + the
# spoken-vs-slide stickiness/compatibility analysis.
_MAX_SLIDES = 60
_MAX_SLIDE_TITLE_LEN = 200
_MAX_SLIDE_BODY_LEN = 2000
_MAX_PRESENTATION_REF_LEN = 2000
_MAX_SLIDE_ADVANCES = 1000

# strategic_context (④ step 5, 2026-07-24): a short free-text note the speaker
# adds at setup — the stakes, the setting, what they want to nail. Longer than
# the tag fields (a sentence or two, not a label) but still bounded. Feeds the
# qualitative feedback as BACKGROUND context only (parallel to `audience`) —
# never the verbatim ideal text (L1).
_MAX_STRATEGIC_LEN = 2000

# Canonical key order — every caller iterates this list when
# building the response so the JSON shape stays stable.
# slide_clock_offset_ms (F1, 2026-07-26): the FE-MEASURED delta between the UI
# clock that timestamps slide taps and the first audio sample the recorder
# produced. Subtracting it puts taps on the audio clock exactly, instead of
# pause-snap guessing the same number from nearby silences. Bounds are generous
# but catch a unit mix-up (seconds sent as milliseconds).
_MAX_CLOCK_OFFSET_MS = 30000
_MIN_CLOCK_OFFSET_MS = -5000

_FIELDS = (
    "topic", "audience", "target_length_seconds", "domain_vocabulary",
    "slides", "presentation_ref", "slide_advances", "strategic_context",
    "slide_clock_offset_ms",
)


class IntakeContextError(ValueError):
    """Validation error with an FE-renderable message.

    Raised by ``validate_intake_context_body``. The route handler
    catches and 400s with the message verbatim — matches the
    INVALID_INPUT pattern the rest of v2_routes.py uses.
    """


def _norm_text(value: Any, field_name: str) -> Optional[str]:
    """Whitespace-trim a string. Empty-after-trim collapses to None
    so "1-char min when present" is a free invariant."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise IntakeContextError(f"{field_name}: must be a string")
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > _MAX_TEXT_LEN:
        raise IntakeContextError(
            f"{field_name}: must be {_MAX_TEXT_LEN} characters or fewer"
        )
    return cleaned


def _norm_seconds(value: Any) -> Optional[int]:
    """Integer in [30, 7200] or None. Bool rejected (Python's
    bool-is-int trick would otherwise let True through as 1)."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise IntakeContextError(
            "target_length_seconds: must be an integer"
        )
    if not isinstance(value, int):
        raise IntakeContextError(
            "target_length_seconds: must be an integer"
        )
    if not (_MIN_TARGET_SECONDS <= value <= _MAX_TARGET_SECONDS):
        raise IntakeContextError(
            "target_length_seconds: must be between "
            f"{_MIN_TARGET_SECONDS} and {_MAX_TARGET_SECONDS} seconds"
        )
    return value


def _norm_vocabulary(value: Any) -> Optional[list[str]]:
    """Normalise the editable domain_vocabulary list.

    Accepts None or a list of short strings. Trims each, drops empties,
    de-dupes preserving order, and collapses an empty result to None
    (None means "unset → fall back to the profile domain's seed", same
    None-means-default convention as the text fields).

    Raises IntakeContextError on a non-list, a non-string item, an
    over-long term, or too many terms.
    """
    if value is None:
        return None
    if not isinstance(value, list):
        raise IntakeContextError("domain_vocabulary: must be a list of strings")
    if len(value) > _MAX_VOCAB_TERMS:
        raise IntakeContextError(
            f"domain_vocabulary: at most {_MAX_VOCAB_TERMS} terms"
        )
    cleaned: list[str] = []
    seen: set[str] = set()
    for term in value:
        if not isinstance(term, str):
            raise IntakeContextError(
                "domain_vocabulary: every term must be a string"
            )
        t = term.strip()
        if not t:
            continue
        if len(t) > _MAX_VOCAB_TERM_LEN:
            raise IntakeContextError(
                f"domain_vocabulary: each term must be "
                f"{_MAX_VOCAB_TERM_LEN} characters or fewer"
            )
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(t)
    return cleaned or None


def _norm_slides(value: Any) -> Optional[list[dict]]:
    """Normalise slides → list of {title:str, body:str} or None.

    body is FREE TEXT (newlines = bullets) — the locked §S shape. Fully-blank
    slides (the FE's empty default rows) are dropped; an all-blank list
    collapses to None. Caps: ≤60 slides, title ≤200, body ≤2000.
    """
    if value is None:
        return None
    if not isinstance(value, list):
        raise IntakeContextError("slides: must be a list")
    if len(value) > _MAX_SLIDES:
        raise IntakeContextError(f"slides: at most {_MAX_SLIDES} slides")
    out: list[dict] = []
    for s in value:
        if not isinstance(s, dict):
            raise IntakeContextError("slides: each slide must be an object")
        title = s.get("title")
        body = s.get("body")
        title = "" if title is None else title
        body = "" if body is None else body
        if not isinstance(title, str) or not isinstance(body, str):
            raise IntakeContextError("slides: title and body must be strings")
        title = title.strip()
        body = body.strip()
        if len(title) > _MAX_SLIDE_TITLE_LEN:
            raise IntakeContextError(
                f"slides: title must be {_MAX_SLIDE_TITLE_LEN} characters or fewer"
            )
        if len(body) > _MAX_SLIDE_BODY_LEN:
            raise IntakeContextError(
                f"slides: body must be {_MAX_SLIDE_BODY_LEN} characters or fewer"
            )
        if not title and not body:
            continue  # drop empty default rows
        out.append({"title": title, "body": body})
    return out or None


def _norm_presentation_ref(value: Any) -> Optional[str]:
    """Served-PDF URL (or None). String, trimmed, bounded."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise IntakeContextError("presentation_ref: must be a string")
    v = value.strip()
    if not v:
        return None
    if len(v) > _MAX_PRESENTATION_REF_LEN:
        raise IntakeContextError("presentation_ref: too long")
    return v


def _norm_slide_advances(value: Any) -> Optional[list[dict]]:
    """Tap-advance timeline → list of {index:int, t_ms:int} or None.

    index = position in slides[]; t_ms = ms from recording start. Bool is
    rejected (Python bool-is-int). The BE maps each snippet to the slide on
    screen at its time from this list (greatest t_ms ≤ snippet.start_offset_ms).
    """
    if value is None:
        return None
    if not isinstance(value, list):
        raise IntakeContextError("slide_advances: must be a list")
    if len(value) > _MAX_SLIDE_ADVANCES:
        raise IntakeContextError(
            f"slide_advances: at most {_MAX_SLIDE_ADVANCES} entries"
        )
    out: list[dict] = []
    for a in value:
        if not isinstance(a, dict):
            raise IntakeContextError("slide_advances: each entry must be an object")
        idx = a.get("index")
        t = a.get("t_ms")
        if (
            isinstance(idx, bool) or isinstance(t, bool)
            or not isinstance(idx, int) or not isinstance(t, int)
        ):
            raise IntakeContextError("slide_advances: index and t_ms must be integers")
        if idx < 0 or t < 0:
            raise IntakeContextError("slide_advances: index and t_ms must be >= 0")
        out.append({"index": idx, "t_ms": t})
    return out or None


def _norm_strategic_context(value: Any) -> Optional[str]:
    """Trim the strategic-context note; empty-after-trim → None (the
    None-means-omitted convention); bounded at 2000 chars. A longer cap than
    the tag fields because it's a free-text sentence or two."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise IntakeContextError("strategic_context: must be a string")
    cleaned = value.strip()
    if not cleaned:
        return None
    if len(cleaned) > _MAX_STRATEGIC_LEN:
        raise IntakeContextError(
            f"strategic_context: must be {_MAX_STRATEGIC_LEN} characters or fewer"
        )
    return cleaned


def _norm_clock_offset(value: Any) -> Optional[int]:
    """Integer ms in [-5000, 30000], or None. Bool rejected (bool-is-int).

    An OUT-OF-RANGE value is rejected loudly rather than clamped: a number that
    far off is a bug in the sender (seconds-for-milliseconds is the classic),
    and silently clamping it would bake a wrong timeline into the transcript
    while looking like it worked.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise IntakeContextError("slide_clock_offset_ms: must be an integer")
    if not isinstance(value, int):
        raise IntakeContextError("slide_clock_offset_ms: must be an integer")
    if not (_MIN_CLOCK_OFFSET_MS <= value <= _MAX_CLOCK_OFFSET_MS):
        raise IntakeContextError(
            "slide_clock_offset_ms: must be between "
            f"{_MIN_CLOCK_OFFSET_MS} and {_MAX_CLOCK_OFFSET_MS} ms"
        )
    return value


def validate_intake_context_body(
    body: Any,
    *,
    require_topic: bool = False,
) -> dict[str, Any]:
    """Parse + validate the PUT body, returning the canonical dict.

    Accepts:
      - dict with any subset of the four keys
      - missing keys are treated as None
      - empty body {} → all-None dict (only when require_topic=False)

    ``require_topic`` (willab beta §3.2 / invariant §5.10): when True,
    a missing/empty ``topic`` is rejected — session_context REQUIRES a
    topic (it feeds stickiness topic-coherence, Whisper priming, prompt
    relevance, coach interpretability). The willab Lab-entry PUT passes
    require_topic=True; the legacy default (False) preserves the Task-9
    all-optional behaviour for any other caller + the validator's unit
    tests.

    Raises IntakeContextError with a user-friendly message on:
      - body not a dict
      - wrong type on any field
      - text field over the 200-char cap
      - target_length_seconds out of [30, 7200]
      - bool sneaking in where int is expected
      - domain_vocabulary not a list / over bounds
      - require_topic=True and topic missing/empty

    The returned dict always carries the four canonical keys with
    None-or-value, so callers can write it straight into the JSONB
    column without further normalization.
    """
    if not isinstance(body, dict):
        raise IntakeContextError("Body must be a JSON object")

    cleaned = {
        "topic": _norm_text(body.get("topic"), "topic"),
        "audience": _norm_text(body.get("audience"), "audience"),
        "target_length_seconds": _norm_seconds(
            body.get("target_length_seconds"),
        ),
        "domain_vocabulary": _norm_vocabulary(
            body.get("domain_vocabulary"),
        ),
        "slides": _norm_slides(body.get("slides")),
        "presentation_ref": _norm_presentation_ref(body.get("presentation_ref")),
        "slide_advances": _norm_slide_advances(body.get("slide_advances")),
        "strategic_context": _norm_strategic_context(
            body.get("strategic_context"),
        ),
        "slide_clock_offset_ms": _norm_clock_offset(
            body.get("slide_clock_offset_ms"),
        ),
    }

    if require_topic and not cleaned["topic"]:
        raise IntakeContextError("topic: required")

    return cleaned


def snapshot_intake_context(session_id: str) -> Optional[dict[str, Any]]:
    """Read the persisted intake_context AT ENQUEUE TIME.

    The pattern matches the spec's anti-drift contract: snapshot
    when the audit / snippet job is queued, NOT when it's picked
    up. A user editing the form between submit and job pickup
    can't change what the job sees, because the job carries the
    snapshot in its payload.

    Returns the canonical 3-key dict (each value is None or
    populated) or None when the column is unset / row missing /
    DB hiccup. ``None`` means "use defaults" — consumers fall
    through to pre-task-9 behaviour on every None path.

    Consumers should write::

        ctx = (job_payload.get("intake_context") or {})
        topic          = ctx.get("topic")
        audience       = ctx.get("audience")
        target_seconds = ctx.get("target_length_seconds")
        # Every None path == legacy default == in-flight jobs unaffected.
    """
    from services.db import db

    raw = db.get_session_intake_context(session_id)
    if not raw:
        return None
    # Return the canonical 3-key shape so consumers don't have to
    # defensively re-check whether the JSONB blob carries extra
    # keys (an admin tool could in theory write any JSON; the read
    # path normalizes back to the contract).
    return {key: raw.get(key) for key in _FIELDS}
