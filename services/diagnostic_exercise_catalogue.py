"""Authoring for the diagnostic exercise catalogue.

Founder 2026-09-16: "I will add the exercises… this would need to be dynamic."

Until now exactly one exercise could exist. The route refused any id but
`hear-every-word-v1` by name, and the CMS hardcoded its problem tags to all
three names in the vocabulary. So a second exercise was unrepresentable, and
had one existed it would have claimed every problem the first one claimed.

WHY THE TAGS ARE THE POINT. Matching ranks by how many of a clip's observed
problems an exercise claims to treat. If every exercise claims everything,
every exercise scores identically and the ranking chooses nothing — it would
run, return an order, and that order would be meaningless. A catalogue of one
hid this; a catalogue of several makes it the whole game.

THE LIBRARY IS THE AUTHORITY. A tag must name an error the speaking error
library calls `detected`. Not merely spelled right — actually findable in
audio. An exercise tagged with an `observed` error would match no clip, raise
nothing, and sit in the catalogue looking healthy. That silent nothing is the
same defect the library was built to prevent, so it is refused here rather
than discovered later.

When the library read comes back EMPTY the check is skipped, not failed: empty
means "no library available" (migration pending, read failed), and reading it
as "nothing is detectable" would refuse every exercise in the catalogue.
"""
from __future__ import annotations

import re
from typing import Any, Optional


# `hear-every-word-v1` is the shape already in use: lower-case, hyphens. The
# underscore is admitted too because the error library speaks that dialect and
# an author should not have to remember which side of the pair they are on.
EXERCISE_ID_SHAPE = re.compile(r"^[a-z][a-z0-9_-]{1,62}$")

# services/confident_voice_practice.py::_PATTERN_ORDINAL. Duplicated because a
# pattern this file admits but that file cannot rank would route nothing.
CONFIDENCE_PATTERNS = (
    "low_confidence_rushing_dominant",
    "near_confident",
    "confident",
)

_URL = re.compile(r"^https?://[^\s]+$", re.IGNORECASE)

_REQUIRED_TEXT = (
    ("title", "a name"),
)

# THE WORDS ARE OPTIONAL (founder 2026-09-24, on the CMS lane's "The words"
# step: "that is not obligatory!").
#
# A video is still required and always was, so what this allows is an exercise
# that demonstrates rather than describes — which is the shape the speaker's
# screen already takes: the coach's recording first, the instruction underneath
# it. An empty instruction now draws no box there rather than an empty one.
#
# They are stored as "" rather than NULL so nothing depends on the columns'
# nullability, and a later save that fills them in is an ordinary update.
_OPTIONAL_TEXT = ("instruction", "introduction_copy")

# ONE FIRED PROBLEM IS THE FIT (contract 35g-1, founder 2026-09-28, D1/D5;
# C4, founder 2026-09-30). An exercise is offered when a detected problem it
# targets fired on that exact clip: its main target for an exact fit, one of
# its secondary targets for a trial. Matching never reads
# `requires_multiple_acoustic_signals` (services.confident_voice_practice
# ranks by exercise_fit alone); the legacy rush lane's two-or-three signal
# gate is a property of the CLIP (exercise_eligibility), not of an exercise.
# The default said `true` from the first single-exercise catalogue, so every
# coach exercise filed from the walk claimed to need several signals while
# the next speaker with its one pattern was served it anyway. It now says
# what routing does (W6, 2026-10-05), and a row that names a main target is
# stored `false` whatever the client mirrored.
DEFAULT_MATCHING_CRITERIA = {
    "requires_multiple_acoustic_signals": False,
    "max_per_take": 1,
}

#: The doors a coach saves through (exercise_versions.SOURCES minus the
#: retired CMS). A NEW exercise from any of them must name its main error
#: (founder 2026-09-30, E5; build plan P2-4).
COACH_SOURCES = ("coach_panel", "coach_request", "coach_review")
MAIN_TARGET_MESSAGE = "Name the one pattern this exercise is written for."
DEFAULT_EXCLUSIONS = {
    "exclude_noise": True,
    "exclude_semantic_or_structural_issue": True,
    "exclude_weak_evidence": True,
}


class CatalogueRefusal(Exception):
    """A refusal an author needs to read, not a bug."""

    def __init__(self, message: str, *, code: str = "INVALID_INPUT",
                 status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.status = status


def detected_error_ids(database: Any) -> frozenset[str]:
    """The error ids the library says code can ACTUALLY find in audio.

    Empty means the library is unavailable, never "nothing is detectable" —
    every caller must skip filtering rather than refuse everything.
    """
    if not hasattr(database, "list_speaking_errors"):
        return frozenset()
    rows = database.list_speaking_errors() or []
    return frozenset(
        str(row.get("error_id"))
        for row in rows
        if isinstance(row, dict)
        and row.get("status") == "detected"
        and row.get("error_id")
    )


def _clean_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise CatalogueRefusal(f"{field}: needs at least one value")
    out = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise CatalogueRefusal(f"{field}: every value must be a name")
        out.append(item.strip())
    return out


def _validate_tags(tags: list[str], database: Any) -> None:
    detected = detected_error_ids(database)
    if not detected:
        return
    unknown = [tag for tag in tags if tag not in detected]
    if unknown:
        raise CatalogueRefusal(
            "these are not errors code can find yet: "
            f"{', '.join(sorted(unknown))}. An exercise tagged with one would "
            "match no recording, raise nothing, and route nothing — name it in "
            "the error library first, and it becomes selectable once a "
            "detector exists.",
            code="TAG_NOT_DETECTED")


def _identity(fields: dict) -> dict:
    """Who this exercise is: its id and the words a speaker reads."""
    exercise_id = str(fields.get("exercise_id") or "").strip()
    if not EXERCISE_ID_SHAPE.match(exercise_id):
        raise CatalogueRefusal(
            "exercise_id: lower-case letters, digits, hyphens and underscores "
            "only, starting with a letter")
    row: dict[str, Any] = {"exercise_id": exercise_id}
    for key, what in _REQUIRED_TEXT:
        value = str(fields.get(key) or "").strip()
        if not value:
            raise CatalogueRefusal(f"{key}: give it {what}")
        row[key] = value
    for key in _OPTIONAL_TEXT:
        row[key] = str(fields.get(key) or "").strip()
    confident = str(fields.get("confident_introduction_copy") or "").strip()
    row["confident_introduction_copy"] = confident if confident else None
    return row


def _targeting(fields: dict, database: Any) -> dict:
    """What it treats, and the assets that let it be offered at all."""
    video = str(fields.get("explanation_video_url") or "").strip()
    if not _URL.match(video):
        raise CatalogueRefusal(
            "explanation_video_url: an exercise needs a video, and the address "
            "must start with http or https")

    tags = _clean_list(fields.get("acoustic_problem_tags"),
                       "acoustic_problem_tags")
    _validate_tags(tags, database)

    patterns = _clean_list(fields.get("supported_confidence_patterns")
                           or list(CONFIDENCE_PATTERNS),
                           "supported_confidence_patterns")
    unknown = [p for p in patterns if p not in CONFIDENCE_PATTERNS]
    if unknown:
        raise CatalogueRefusal(
            f"supported_confidence_patterns: unknown {', '.join(unknown)}")

    row: dict[str, Any] = {
        "explanation_video_url": video,
        "acoustic_problem_tags": tags,
        "supported_confidence_patterns": patterns,
    }
    for key, default in (("matching_criteria", DEFAULT_MATCHING_CRITERIA),
                         ("exclusions", DEFAULT_EXCLUSIONS)):
        supplied = fields.get(key)
        if supplied is None:
            row[key] = dict(default)
        elif isinstance(supplied, dict):
            row[key] = supplied
        else:
            raise CatalogueRefusal(f"{key}: must be an object")

    # THE MAIN TARGET (founder 2026-09-28, D5/D5a). One tag the exercise is
    # written FOR; every other tag becomes a secondary target, which can only
    # ever serve it as a trial. Optional: an exercise that names none keeps
    # every tag as a main target, as before.
    primary = row["matching_criteria"].get("primary_problem_tag")
    if primary is not None and (not isinstance(primary, str)
                                or primary not in tags):
        raise CatalogueRefusal(
            "matching_criteria.primary_problem_tag: must be one of this "
            "exercise's own acoustic_problem_tags — a main target it does not "
            "claim would make it the exact fit for nothing")
    if primary is not None:
        # The main target firing is the whole fit (35g-1): never a claim
        # that several signals are needed (see DEFAULT_MATCHING_CRITERIA).
        row["matching_criteria"] = {**row["matching_criteria"],
                                    "requires_multiple_acoustic_signals": False}

    version = fields.get("version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise CatalogueRefusal("version: must be a whole number above zero")
    row["version"] = version
    return row


def _placement(fields: dict, database: Any) -> dict:
    """Where it lives, and whether it is switched on.

    THE POST IS NOW OPTIONAL (founder 2026-09-23, migration 0353). The coupling
    kept on 2026-09-16 was that an exercise IS a journal post plus a mapping,
    because the post was the explanation a learner read when the exercise
    fired. The founder's decision is that the video and the one-line
    instruction stand on their own, and the write-up is a companion rather than
    a precondition. So an exercise with no post may now go live.

    WHAT DID NOT CHANGE: a post that IS attached still has to be published
    before the exercise switches on. Half-linking an exercise to a draft would
    show a learner a dead address, which is worse than showing them none.
    """
    active = fields.get("active")
    # isinstance, not `in (True, False)`: 1 == True in Python, so the
    # membership test would quietly accept 1 and 0 and switch an exercise live
    # on a number the caller never meant as a decision.
    if not isinstance(active, bool):
        raise CatalogueRefusal("active: must be true or false")

    post_id = str(fields.get("journal_post_id") or "").strip()
    if not post_id:
        return {"journal_post_id": None, "active": active}
    post = database.get_journal_post_by_id(post_id)
    if not post:
        raise CatalogueRefusal("post not found", code="NOT_FOUND", status=404)
    if active and post.get("status") != "published":
        raise CatalogueRefusal(
            "publish the post before switching the exercise on")
    return {"journal_post_id": post_id, "active": active}


def _avatar(fields: dict) -> dict:
    """Whether this recording may seed a future avatar, and from which setup.

    PERISHABLE, WHICH IS THE WHOLE ARGUMENT FOR STORING IT NOW. Only the person
    in the room at record time knows whether the shirt, angle and lighting
    matched the others. It cannot be recovered from the file afterwards, so it
    is captured at the one moment it exists — for a product that does not yet
    exist. Nothing reads these fields today, by the founder's decision:
    remember only, no list, no export, no surface.

    THE LABEL IS NOT OPTIONAL WHEN THE FLAG IS SET, and that is the point of
    the field rather than a formality. A bare yes says this clip was shot
    carefully; it cannot say these clips match EACH OTHER, and matching each
    other is the entire requirement. Two hundred unlabelled "usable" clips is
    the manual sorting job the flag existed to prevent. The database CHECK says
    the same; this exists so an author reads a sentence instead of a constraint
    violation.
    """
    eligible = fields.get("avatar_training_eligible", False)
    if not isinstance(eligible, bool):
        raise CatalogueRefusal(
            "avatar_training_eligible: must be true or false")
    label = str(fields.get("avatar_setup_label") or "").strip()
    if not eligible:
        # A label without the tick is kept rather than dropped: an author who
        # unticks and reticks should not have to type it again.
        return {"avatar_training_eligible": False,
                "avatar_setup_label": label or None}
    if not label:
        raise CatalogueRefusal(
            "avatar_setup_label: name the setup this was shot in — the same "
            "short label for every clip with the same shirt, angle and light. "
            "Without it the tick says a clip was shot carefully but never that "
            "two clips match, which is the only thing a training set needs.")
    if len(label) > 120:
        raise CatalogueRefusal("avatar_setup_label: keep it under 120 letters")
    return {"avatar_training_eligible": True, "avatar_setup_label": label}


def fold_main_target(fields: dict) -> dict:
    """``main_target`` is the short way to name it: folded into
    ``matching_criteria.primary_problem_tag`` (over the defaults when no
    criteria were sent) and into the tags when missing, the request lane's
    rule since 2026-09-30, now the catalogue's for every door."""
    target = fields.pop("main_target", None)
    if not isinstance(target, str) or not target.strip():
        return fields
    target = target.strip()
    supplied = fields.get("matching_criteria")
    criteria = dict(supplied) if isinstance(supplied, dict) \
        else dict(DEFAULT_MATCHING_CRITERIA)
    criteria["primary_problem_tag"] = target
    fields["matching_criteria"] = criteria
    raw = fields.get("acoustic_problem_tags")
    tags = [t for t in (raw if isinstance(raw, list) else []) if isinstance(t, str)]
    if target not in tags:
        fields["acoustic_problem_tags"] = [target, *tags]
    return fields


def _main_target_of(row: Any) -> Optional[str]:
    criteria = row.get("matching_criteria") if isinstance(row, dict) else None
    target = criteria.get("primary_problem_tag") if isinstance(criteria, dict) else None
    return target if isinstance(target, str) and target.strip() else None


def _require_main_target(database: Any, row: dict, source: str) -> None:
    """A NEW COACH EXERCISE NAMES ITS MAIN ERROR (founder 2026-09-30, E5;
    build plan P2-4), on every door a coach saves through: the walk's upload
    seam and the Library (both ``/coach/exercises``, with or without the
    video), the request's own exercise and the practice review's. It was
    held by the frontend alone on the doors the walk uses. An exercise that
    already names one cannot lose it; a library row from before the rule,
    which names none, may still be edited without one."""
    if source not in COACH_SOURCES or _main_target_of(row):
        return
    reader = getattr(database, "get_diagnostic_exercise", None)
    existing = reader(row["exercise_id"]) if reader is not None else None
    if isinstance(existing, dict) and not _main_target_of(existing):
        return
    raise CatalogueRefusal(MAIN_TARGET_MESSAGE, code="MAIN_TARGET_REQUIRED")


def validate_exercise(database: Any, body: Any, *, source: str = "cms") -> dict:
    """The row a save would write, or CatalogueRefusal -- without writing.

    Split out so a door that stores something BEFORE the save (the coach
    panel's video, uploaded and then saved as the new version) can refuse a
    bad definition first and leave nothing behind in storage. ``source`` is
    the door (exercise_versions.SOURCES); a coach's door holds a new
    exercise to its main error (``_require_main_target``).
    """
    fields: dict = fold_main_target(dict(body)) if isinstance(body, dict) else {}
    row = {
        **_identity(fields),
        **_targeting(fields, database),
        **_placement(fields, database),
        **_avatar(fields),
    }
    _require_main_target(database, row, source)
    return row


def save_exercise(
    database: Any, body: Any, *, source: str = "cms", created_by: str = "",
    ai_draft_text: Optional[str] = None,
    ai_draft_model_version: Optional[str] = None,
    video_sha256: Optional[str] = None, video_bytes: Optional[int] = None,
    transcript_status: str = "not_requested",
) -> Optional[dict]:
    """Validate and write one catalogue entry, new or existing.

    Raises CatalogueRefusal for anything an author can fix; returns None only
    when the write itself failed.

    EVERY SAVE KEEPS ITS VERSION (founder 2026-09-29, decision 4; 0399). The
    live row is upserted in place as before; its version is bumped when the
    definition or the video changed, and one immutable version row is written
    beside it with the definition as saved, the AI draft if there was one, the
    video's lineage and the transcript's state. ``source`` names which door
    the save came through (cms, coach_panel, coach_request, coach_review).
    """
    from services.exercise_versions import next_version, record_version
    row = validate_exercise(database, body, source=source)
    reader = getattr(database, "get_diagnostic_exercise", None)
    before = reader(row["exercise_id"]) if reader is not None else None
    row["version"] = next_version(before, row)
    saved = database.upsert_diagnostic_exercise(row)
    if saved:
        record_version(
            database, {**row, **saved}, source=source, created_by=created_by,
            ai_draft_text=ai_draft_text,
            ai_draft_model_version=ai_draft_model_version,
            video_sha256_hex=video_sha256, video_bytes=video_bytes,
            transcript_status=transcript_status,
        )
    return saved


def file_coach_exercise(
    database: Any, *, practice_id: Any, fields: Any,
) -> Optional[dict]:
    """The coach's on-the-spot exercise, filed into the library like any other.

    FOUNDER 2026-09-25, decision 04. This path used to mint a one-off
    ``coach-custom-{practice}`` dictionary carrying a title, an instruction and
    NO ERROR AT ALL. Two things followed, both bad.

    It could never reach anyone. Routing works by matching an exercise's
    errors against the errors a detector actually found on a clip, so an
    exercise naming none matches nothing, forever.

    And it carried a coach's judgement about ONE recording forward onto that
    speaker's later practice -- the provenance wall L3 exists to hold. The
    founder's decision closes that: the coach's video becomes teaching
    material FOR AN ERROR, reusable by any speaker whose recording shows it,
    rather than a private verdict about one person.

    So it goes through exactly the validation every catalogue entry goes
    through -- including the refusal for an error code cannot detect, which is
    the one a coach is most likely to meet and most needs to read.
    """
    payload: dict = fields if isinstance(fields, dict) else {}
    practice = str(practice_id or "").strip()
    if not practice:
        raise CatalogueRefusal("an exercise needs the practice it came from")
    body = dict(payload)
    body["exercise_id"] = f"coach-custom-{practice}"
    body.setdefault("active", True)
    # Every other field is the author's, and is validated by save_exercise --
    # including the video, which the library has always required and this path
    # used to treat as optional.
    return save_exercise(database, body, source="coach_review",
                         created_by=str(body.get("created_by") or ""))
