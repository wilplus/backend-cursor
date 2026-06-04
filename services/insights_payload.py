"""willab beta — publish-contract validation for the insights_payload
(design §6b/§14, BE contract §3.9/§3.10).

The coach's user-facing lane: an optional overall message + per-snippet
coach notes, each tagged strong / to-work-on. Published to the user
(Insights view) + ingested into the strong-sides library on read.

The LIBRARY FLOOR (the human-presence guarantee): a session can't be
published unless at least one snippet carries a coach note + tag — so
the bot's "refresh your strong lines" is never empty and every
published session contains at least one phrase from a human.

CONTRACT-VS-DESIGN CONFLICT (resolved here, flagged for sign-off):
  BE contract §3.10 says overall_message is REQUIRED.
  Design §6b/§14 say overall_message is OPTIONAL (soft warning, never a
  block — a mandated overall message just yields filler; the ≥1-tagged-
  note floor already guarantees human presence).
Per the doc-precedence rule (v1.2 design wins over the contract where
they differ), overall_message is treated as OPTIONAL here. The hard
floor is ≥1 snippet note + tag.

This is the USER lane only — the private training-annotation/label lane
(direction-v1, §14) is gated on the §7.1 schema decision and is NOT
handled here (split-sink: the two never cross).
"""
from __future__ import annotations

from typing import Any, Optional


# strong/to-work-on tag (snake_case for storage; FE renders the label).
VALID_TAGS = ("strong", "to_work_on")

_MAX_NOTE_LEN = 2000
_MAX_OVERALL_LEN = 4000


class InsightsPayloadError(ValueError):
    """Validation error with an FE-renderable message. The publish
    route catches and 422s with the message verbatim."""


def validate_insights_payload(body: Any) -> dict:
    """Validate the publish body's insights_payload, returning the
    cleaned ``{overall_message, snippet_notes}``.

    Enforces the publish contract (§3.10, design-resolved):
      - snippet_notes: a list with ≥1 entry (the library floor)
      - every entry: snippet_id (non-empty str), note (non-empty,
        ≤2000 chars), tag ∈ {strong, to_work_on}
      - overall_message: OPTIONAL str (≤4000), empty/whitespace → None

    Raises InsightsPayloadError on any violation.
    """
    if not isinstance(body, dict):
        raise InsightsPayloadError("insights_payload must be a JSON object")

    # overall_message — optional (design §6b/§14).
    raw_overall = body.get("overall_message")
    overall_message: Optional[str] = None
    if raw_overall is not None:
        if not isinstance(raw_overall, str):
            raise InsightsPayloadError("overall_message: must be a string")
        cleaned = raw_overall.strip()
        if cleaned:
            if len(cleaned) > _MAX_OVERALL_LEN:
                raise InsightsPayloadError(
                    f"overall_message: must be {_MAX_OVERALL_LEN} "
                    "characters or fewer"
                )
            overall_message = cleaned

    # snippet_notes — the library floor: ≥1 noted + tagged snippet.
    raw_notes = body.get("snippet_notes")
    if not isinstance(raw_notes, list) or not raw_notes:
        raise InsightsPayloadError(
            "snippet_notes: at least one snippet note + tag is required "
            "(the library floor — a published session must carry at "
            "least one coach phrase)"
        )

    cleaned_notes: list = []
    seen_ids: set = set()
    for i, n in enumerate(raw_notes):
        if not isinstance(n, dict):
            raise InsightsPayloadError(f"snippet_notes[{i}]: must be an object")

        sid = n.get("snippet_id")
        if not isinstance(sid, str) or not sid.strip():
            raise InsightsPayloadError(
                f"snippet_notes[{i}].snippet_id: required"
            )
        sid = sid.strip()
        if sid in seen_ids:
            raise InsightsPayloadError(
                f"snippet_notes[{i}].snippet_id: duplicate ({sid})"
            )
        seen_ids.add(sid)

        note_raw = n.get("note")
        if not isinstance(note_raw, str) or not note_raw.strip():
            raise InsightsPayloadError(
                f"snippet_notes[{i}].note: required (non-empty)"
            )
        note = note_raw.strip()
        if len(note) > _MAX_NOTE_LEN:
            raise InsightsPayloadError(
                f"snippet_notes[{i}].note: must be {_MAX_NOTE_LEN} "
                "characters or fewer"
            )

        tag = n.get("tag")
        if tag not in VALID_TAGS:
            raise InsightsPayloadError(
                f"snippet_notes[{i}].tag: must be one of "
                f"{', '.join(VALID_TAGS)}"
            )

        cleaned_notes.append({
            "snippet_id": sid,
            "note": note,
            "tag": tag,
        })

    return {
        "overall_message": overall_message,
        "snippet_notes": cleaned_notes,
    }
