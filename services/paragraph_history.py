"""The history behind a Paragraph's bookmark (contract 16, founder 2026-09-25).

Clicking a bookmark never opens an empty screen: it shows how this Slide's
words changed Take by Take, which helper words were locked when, and which
practised passages were adopted into it (contract 29a). Every
Take rewrites the Slides it spoke (contract 8), so the history is read per
Slide from the version snapshots, each of which keeps its Slide map.

Words only — no score, rank or verdict (AC-9). A version whose snapshot has
no Slide map (written before 2026-09-25) is left out rather than guessed.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional

_PARA = "\n\n"


def _slide_paragraphs(version: Mapping, slide_index: int) -> Optional[list]:
    """This Slide's Paragraph texts in one version, or None if unprovable."""
    doc = version.get("document")
    text = version.get("text")
    if not isinstance(doc, Mapping) or not isinstance(text, str):
        return None
    paragraphs = doc.get("paragraphs")
    blocks = text.split(_PARA)
    if not isinstance(paragraphs, list) or len(paragraphs) != len(blocks):
        return None
    return [block for block, para in zip(blocks, paragraphs)
            if isinstance(para, Mapping)
            and para.get("slide_index") == slide_index]


def _take_index(version: Mapping) -> Optional[int]:
    """The Take whose words this version holds, when its snapshot says so —
    the answered bookmark labels each version "Take N" (Q21 A)."""
    doc = version.get("document")
    value = doc.get("take_index") if isinstance(doc, Mapping) else None
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return value
    return None


def slide_history(versions: Any, helper_log: Any, slide_index: int,
                  adoptions: Any = None) -> dict:
    """Versions where this Slide's words changed, and its helper-word sets.

    Consecutive versions with identical words collapse into the first: a Take
    that did not speak this Slide adds nothing to its history."""
    out_versions: list = []
    last: Optional[list] = None
    for row in versions or []:
        if not isinstance(row, Mapping):
            continue
        words = _slide_paragraphs(row, slide_index)
        if not words or words == last:
            continue
        out_versions.append({
            "version": row.get("version"),
            "take_index": _take_index(row),
            "paragraphs": words,
            "at": row.get("created_at"),
        })
        last = words
    helper_words = [
        {"phrases": list(r.get("phrases") or []), "at": r.get("created_at")}
        for r in helper_log or [] if isinstance(r, Mapping)
    ]
    practice = [
        {"before": r.get("before_text"), "after": r.get("after_text"),
         "at": r.get("created_at")}
        for r in adoptions or [] if isinstance(r, Mapping)
    ]
    return {"slide_index": slide_index, "versions": out_versions,
            "helper_words": helper_words, "practice": practice}


def history_for_part(database: Any, arc_id: str, user_id: str,
                     part_id: str) -> Optional[dict]:
    """The bookmark's history: resolve the Paragraph's Slide, then read.

    None when the Slide cannot be proven from the published document."""
    from services.slide_helper_words import slide_of_part

    slide = slide_of_part(
        database.get_ideal_text_document_core(arc_id, user_id), part_id)
    if slide is None:
        return None
    return slide_history(
        database.list_ideal_text_versions(arc_id),
        database.list_slide_helper_words_log(arc_id, user_id, slide),
        slide,
        database.list_practice_adoptions(arc_id, user_id, slide))
