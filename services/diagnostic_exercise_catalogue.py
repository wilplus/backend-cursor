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
    ("instruction", "what the speaker should do"),
    ("introduction_copy", "the line the speaker sees first"),
)

DEFAULT_MATCHING_CRITERIA = {
    "requires_multiple_acoustic_signals": True,
    "max_per_take": 1,
}
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

    version = fields.get("version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise CatalogueRefusal("version: must be a whole number above zero")
    row["version"] = version
    return row


def _placement(fields: dict, database: Any) -> dict:
    """Where it lives, and whether it is switched on.

    The coupling the founder chose to keep (2026-09-16): an exercise is a
    journal post plus a mapping, and it only goes live when that post is
    published. The database CHECK says the same thing; this exists so an
    author reads a sentence instead of a constraint violation.
    """
    active = fields.get("active")
    # isinstance, not `in (True, False)`: 1 == True in Python, so the
    # membership test would quietly accept 1 and 0 and switch an exercise live
    # on a number the caller never meant as a decision.
    if not isinstance(active, bool):
        raise CatalogueRefusal("active: must be true or false")

    post_id = str(fields.get("journal_post_id") or "").strip()
    if not post_id:
        raise CatalogueRefusal("an exercise needs a post to live on")
    post = database.get_journal_post_by_id(post_id)
    if not post:
        raise CatalogueRefusal("post not found", code="NOT_FOUND", status=404)
    if active and post.get("status") != "published":
        raise CatalogueRefusal(
            "publish the post before switching the exercise on")
    return {"journal_post_id": post_id, "active": active}


def save_exercise(database: Any, body: Any) -> Optional[dict]:
    """Validate and write one catalogue entry, new or existing.

    Raises CatalogueRefusal for anything an author can fix; returns None only
    when the write itself failed.
    """
    fields: dict = body if isinstance(body, dict) else {}
    row = {
        **_identity(fields),
        **_targeting(fields, database),
        **_placement(fields, database),
    }
    return database.upsert_diagnostic_exercise(row)
