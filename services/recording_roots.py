"""Exact, live recording anchors over an immutable Ideal Text snapshot.

The document snapshot owns Paragraph -> Slide lineage.  Locking and choosing
an orange root are product-state writes and can land after that snapshot was
materialised.  This projection joins the two only when their complete ordered
Paragraph identity still matches; it never guesses a Slide from text.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from services.ideal_text_parts import agrees_with_text, serve


class RecordingRootsStale(ValueError):
    """Live Paragraph state no longer matches the immutable document."""


def project_recording_roots(
    snapshot: Mapping[str, Any],
    live_rows: Any,
) -> list[dict[str, Any]]:
    """Return locked helper words with proven Slide lineage."""
    payload = snapshot.get("payload")
    if not isinstance(payload, Mapping):
        raise RecordingRootsStale("RECORDING_ROOTS_SNAPSHOT_REQUIRED")
    text = payload.get("text")
    frozen_parts = payload.get("parts")
    pieces = payload.get("pieces")
    live_parts = serve(live_rows)
    if (
        not isinstance(text, str)
        or not isinstance(frozen_parts, list)
        or not isinstance(pieces, list)
        or live_parts is None
        or len(frozen_parts) != len(pieces)
        or len(frozen_parts) != len(live_parts)
        or not agrees_with_text(frozen_parts, text)
        or not agrees_with_text(live_parts, text)
    ):
        raise RecordingRootsStale("RECORDING_ROOTS_CONTENT_STALE")

    roots: list[dict[str, Any]] = []
    for frozen, live, piece in zip(frozen_parts, live_parts, pieces):
        if not isinstance(frozen, Mapping) or not isinstance(piece, Mapping):
            raise RecordingRootsStale("RECORDING_ROOTS_LINEAGE_STALE")
        if (
            str(frozen.get("id") or "") != str(live.get("id") or "")
            or frozen.get("text") != live.get("text")
            or piece.get("text") != live.get("text")
        ):
            raise RecordingRootsStale("RECORDING_ROOTS_LINEAGE_STALE")

        phrase = live.get("root_phrase")
        if not phrase:
            continue
        if not live.get("locked"):
            # NOT YET ELIGIBLE, NOT A STALE DOCUMENT. Since the emphasis step
            # saves on the step that chose the words (founder 2026-09-24), an
            # unlocked paragraph legitimately carries a phrase. This used to
            # raise RECORDING_ROOTS_UNLOCKED_ROOT, which failed the WHOLE
            # projection with a 409: one unlocked phrase and every root on the
            # project vanished from the read. Skipping keeps the promise this
            # function makes — locked roots only — without letting an ordinary
            # product state present as a corrupted document.
            continue
        # NO SPAN CHECK. The helper words are their own text and persist
        # when a Take rewrites the Paragraph (contract 14, founder
        # 2026-09-25); the recording screen shows the words, not a position,
        # so a Paragraph that no longer contains them still shows them.
        slide = piece.get("slide_index")
        if isinstance(slide, bool) or not isinstance(slide, int) or slide < 0:
            # A committed root without exact Slide lineage remains stored but
            # cannot be displayed during recording.  Never place it by text.
            continue
        roots.append({
            "part_id": str(live["id"]),
            "slide_index": slide,
            "text": phrase,
            "type": "flagship",
        })
    return roots
