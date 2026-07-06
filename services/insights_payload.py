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
# PR-2 coach fields (optional): `when` = short situational context;
# `examples` = list of example phrases the FE maps over.
_MAX_WHEN_LEN = 1000
_MAX_EXAMPLE_LEN = 500
_MAX_EXAMPLES = 10
# Per-snippet coach breakthrough video — a public URL (no new text field; the
# breakthrough explanation is the note itself). Optional; empty → None.
_MAX_VIDEO_REF_LEN = 2048
# Coach-corrected transcript (founder 2026-07-06) — a real coach-authored
# artifact, distinct from `note` (commentary) and the immutable raw
# transcript. Optional; empty → None.
_MAX_TRANSCRIPT_CORRECTED_LEN = 4000


class InsightsPayloadError(ValueError):
    """Validation error with an FE-renderable message. The publish
    route catches and 422s with the message verbatim."""


def validate_insights_payload(body: Any) -> dict:
    """Validate the publish body's insights_payload, returning the
    cleaned ``{overall_message, snippet_notes}``.

    Enforces the publish contract (§3.10, design-resolved):
      - snippet_notes: a list with ≥1 entry (the library floor)
      - every entry: snippet_id (non-empty str), note (non-empty,
        ≤2000 chars); tag ∈ {strong, to_work_on} is OPTIONAL — a
        missing/blank tag defaults to "strong" (§1.C); an explicit
        wrong value still raises
      - per entry (PR-2, OPTIONAL): when (str ≤1000, empty→None),
        examples (list[str], each ≤500, ≤10 items, empties dropped)
      - overall_message: OPTIONAL str (≤4000), empty/whitespace → None

    Every cleaned note carries a stable shape — {snippet_id, note, tag,
    when, examples} — so the readout round-trip + FE ("hidden when
    absent") see when=None / examples=[] for notes that omit them.

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

        # tag — OPTIONAL since the §1.C publish-floor relaxation (FE handoff
        # 2026-06-19): a missing / null / blank tag defaults to "strong" (the
        # lenient floor — a present note is what gates publish, not the coach
        # remembering to tag). An explicit WRONG value still 422s so a typo
        # surfaces instead of silently flipping to strong.
        tag = n.get("tag")
        if tag is None or (isinstance(tag, str) and not tag.strip()):
            tag = "strong"
        if tag not in VALID_TAGS:
            raise InsightsPayloadError(
                f"snippet_notes[{i}].tag: must be one of "
                f"{', '.join(VALID_TAGS)}"
            )

        # PR-2: `when` — optional situational context (str), empty → None.
        when_raw = n.get("when")
        when_val: Optional[str] = None
        if when_raw is not None:
            if not isinstance(when_raw, str):
                raise InsightsPayloadError(
                    f"snippet_notes[{i}].when: must be a string"
                )
            w = when_raw.strip()
            if w:
                if len(w) > _MAX_WHEN_LEN:
                    raise InsightsPayloadError(
                        f"snippet_notes[{i}].when: must be {_MAX_WHEN_LEN} "
                        "characters or fewer"
                    )
                when_val = w

        # PR-2: `examples` — optional list[str]; trim, drop empties, cap.
        examples_raw = n.get("examples")
        examples_val: list = []
        if examples_raw is not None:
            if not isinstance(examples_raw, list):
                raise InsightsPayloadError(
                    f"snippet_notes[{i}].examples: must be a list of strings"
                )
            if len(examples_raw) > _MAX_EXAMPLES:
                raise InsightsPayloadError(
                    f"snippet_notes[{i}].examples: at most {_MAX_EXAMPLES} "
                    "examples"
                )
            for j, ex in enumerate(examples_raw):
                if not isinstance(ex, str):
                    raise InsightsPayloadError(
                        f"snippet_notes[{i}].examples[{j}]: must be a string"
                    )
                e = ex.strip()
                if not e:
                    continue
                if len(e) > _MAX_EXAMPLE_LEN:
                    raise InsightsPayloadError(
                        f"snippet_notes[{i}].examples[{j}]: must be "
                        f"{_MAX_EXAMPLE_LEN} characters or fewer"
                    )
                examples_val.append(e)

        # Breakthrough video — optional public URL (str), empty → None. The
        # FE renders it next to the breakthrough badge; the explanation text is
        # the `note` above (no separate breakthrough-explanation field).
        bvr_raw = n.get("breakthrough_video_ref")
        breakthrough_video_ref: Optional[str] = None
        if bvr_raw is not None:
            if not isinstance(bvr_raw, str):
                raise InsightsPayloadError(
                    f"snippet_notes[{i}].breakthrough_video_ref: must be a string"
                )
            bvr = bvr_raw.strip()
            if bvr:
                if len(bvr) > _MAX_VIDEO_REF_LEN:
                    raise InsightsPayloadError(
                        f"snippet_notes[{i}].breakthrough_video_ref: must be "
                        f"{_MAX_VIDEO_REF_LEN} characters or fewer"
                    )
                # Must be an http(s) URL — it lands in the learner's <video>
                # src; reject javascript:/data:/garbage even from a coach.
                if not (bvr.startswith("https://") or bvr.startswith("http://")):
                    raise InsightsPayloadError(
                        f"snippet_notes[{i}].breakthrough_video_ref: must be "
                        "an http(s) URL"
                    )
                breakthrough_video_ref = bvr

        # Coach-corrected transcript (founder 2026-07-06) — optional str,
        # empty → None.
        tx_raw = n.get("transcript_corrected")
        transcript_corrected: Optional[str] = None
        if tx_raw is not None:
            if not isinstance(tx_raw, str):
                raise InsightsPayloadError(
                    f"snippet_notes[{i}].transcript_corrected: must be a string"
                )
            tx = tx_raw.strip()
            if tx:
                if len(tx) > _MAX_TRANSCRIPT_CORRECTED_LEN:
                    raise InsightsPayloadError(
                        f"snippet_notes[{i}].transcript_corrected: must be "
                        f"{_MAX_TRANSCRIPT_CORRECTED_LEN} characters or fewer"
                    )
                transcript_corrected = tx

        cleaned_notes.append({
            "snippet_id": sid,
            "note": note,
            "tag": tag,
            "when": when_val,
            "examples": examples_val,
            "breakthrough_video_ref": breakthrough_video_ref,
            "transcript_corrected": transcript_corrected,
        })

    return {
        "overall_message": overall_message,
        "snippet_notes": cleaned_notes,
    }
