"""willab — Paid Audits, Ideal-Text report (BE chunk A7).

Shapes ``build_best_presentation(arc_id)`` into the report the FE renders at
``/audit/:talkId/ideal-text`` (ideal_text_slides.html). A "talk" IS an arc, so
talkId == arc_id.

L1 fence: ``idealText`` is the verbatim-selected best take of each slide (+ the
light continuity polish already applied in compose) — NEVER re-summarised here.
AC-9: no score/verdict; the report is the text + the deck, nothing ranked.

``thumbnailUrl`` is intentionally null — the FE already renders real slide pages
from ``presentationRef`` (the deck PDF) for the best-presentation surface, so it
maps page=index here too. (No BE PDF rasteriser is added; that would be a heavy,
redundant dependency for a page the FE can already draw.)
"""
from __future__ import annotations

from typing import Optional


def build_ideal_text_report(talk_id: Optional[str], *, database=None) -> dict:
    """The Ideal-Text report for a talk (arc). Best-effort — an arc with <3
    takes still returns its slides with ready=False (the FE shows the
    not-ready state, the route's paywall gate runs first)."""
    from services.best_presentation import build_best_presentation

    bp = build_best_presentation(talk_id, database=database)
    slides = bp.get("slides") or []
    out_slides = []
    for s in slides:
        if not isinstance(s, dict):
            continue
        title = s.get("title")
        body = s.get("body")
        take_index = s.get("take_index")
        out_slides.append({
            "index": s.get("index"),
            # label = the slide's heading (title), with body as the subline.
            "label": title or body or None,
            "title": title,
            "body": body,
            "thumbnailUrl": None,  # FE renders page=index from presentationRef
            "idealText": s.get("text"),  # L1 verbatim-selected, never re-summarised
            "takeRoute": (f"/audit/{talk_id}/take/{take_index}"
                          if take_index is not None else None),
            "breakthrough": bool(s.get("breakthrough")),
            # Glanceable per-slide phrases for the presenter's mid-talk look
            # (backlog 1.7) — derived from the winning pick's Say-It-Stronger
            # upgrades in compose; display hints only, never the text (L1).
            "keyPhrases": s.get("key_phrases") or [],
            # The winning moment's snippet id — the exported PDF deep-links
            # this slide's "Key moment" to /game?snippet=<id> (P8).
            "snippetId": s.get("snippet_id"),
        })
    return {
        "talkId": talk_id,
        "talkTitle": bp.get("name"),
        "ready": bp.get("ready"),
        "coachReviewed": bp.get("coach_reviewed"),
        # HARD gate (founder 2026-07-06): False → idealText is "" on every
        # slide (never the raw auto draft) — the FE shows "still being
        # prepared by your coach", distinct from the payment paywall.
        "coachFinalized": bp.get("coach_finalized"),
        "presentationRef": bp.get("presentation_ref"),
        "slides": out_slides,
    }
