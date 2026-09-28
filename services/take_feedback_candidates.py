"""Take-scoped feedback candidates that remain honest over a stable document.

Take 1 creates the canonical Ideal Text.  A later Take can pronounce the same
slide differently without reproducing every canonical sentence byte for byte.
Confident Voice is evidence about that later recording, so its durable source
is the playable snippet; its text span is only the route into the corresponding
slide in the Ideal Text deck.

This module owns that distinction.  It prefers an exact phrase shared by the
recording and the canonical slide.  When no phrase is shared, it uses a small
exact span in the same canonical slide and labels it ``slide_route``.  The UI
never presents that routing span as words the user said; it presents the audio
and asks the user to evaluate it.  No acoustic praise is manufactured here.
"""
from __future__ import annotations

import re
from typing import Any, Optional


_CONFIDENT_TRIGGERS = {"confident", "confidence_review"}
_CONFIDENCE_REVIEW_WHY = "Possible confident moment for review."
_WORD_RE = re.compile(r"[^\W_]+(?:[’'-][^\W_]+)*", re.UNICODE)


def _int(value: Any) -> Optional[int]:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _ci_slice(haystack: str, needle: Any) -> Optional[tuple[int, int]]:
    wanted = needle.strip() if isinstance(needle, str) else ""
    if not wanted:
        return None
    at = haystack.casefold().find(wanted.casefold())
    return (at, at + len(wanted)) if at >= 0 else None


def _shared_phrase(spoken: str, canonical: str) -> Optional[tuple[int, int]]:
    """Longest exact word run shared by both strings, as canonical offsets.

    Two words is the minimum: a single article is not meaningful alignment.
    The returned slice always comes from ``canonical`` so the normal span
    verifier can prove it byte for byte.
    """
    source = [m.group(0).casefold() for m in _WORD_RE.finditer(spoken or "")]
    target_matches = list(_WORD_RE.finditer(canonical or ""))
    target = [m.group(0).casefold() for m in target_matches]
    if len(source) < 2 or len(target) < 2:
        return None
    source_runs: set[tuple[str, ...]] = set()
    ceiling = min(8, len(source), len(target))
    for width in range(ceiling, 1, -1):
        source_runs.clear()
        source_runs.update(
            tuple(source[i:i + width])
            for i in range(0, len(source) - width + 1)
        )
        for i in range(0, len(target) - width + 1):
            if tuple(target[i:i + width]) in source_runs:
                return (
                    target_matches[i].start(),
                    target_matches[i + width - 1].end(),
                )
    return None


def _route_word(canonical: str) -> Optional[tuple[int, int]]:
    """One exact, non-empty deck-routing span when wording did not align."""
    match = _WORD_RE.search(canonical or "")
    return (match.start(), match.end()) if match else None


def _cue_keys(suggestion: dict) -> list[str]:
    try:
        from services.delivery_cues import CUE_KEYS

        return [
            key for key in (suggestion.get("cue_keys") or [])
            if isinstance(key, str) and key in CUE_KEYS
        ]
    except Exception:
        return []


def _detector_candidates(current: list, suggestion_map: dict,
                         excluded: set) -> list:
    """``(positive_rank, ordinal, piece, suggestion)`` for every stored
    Confident Voice emphasis row on a current-Take snippet.

    Prefer the positive detector when it exists; otherwise the neutral
    confidence_review nomination remains a question, never converted into
    praise.  Document order is the deterministic tie-break."""
    candidates = []
    for ordinal, piece in enumerate(current):
        sid = str(piece.get("snippet_id") or "")
        if sid in excluded:
            continue
        suggestion = suggestion_map.get(sid)
        if not sid or not isinstance(suggestion, dict):
            continue
        trigger = str(suggestion.get("trigger") or "")
        if suggestion.get("kind") != "emphasize" \
                or trigger not in _CONFIDENT_TRIGGERS:
            continue
        candidates.append((0 if trigger == "confident" else 1,
                           ordinal, piece, suggestion))
    return candidates


def _review_fallbacks(current: list, excluded: set,
                      already_ranked: set) -> list:
    """A neutral evaluation for every other exact current-Take snippet.

    The three-item Take contract contains one Confident Voice EVALUATION,
    not necessarily one positive detector verdict. Keep generation lanes
    independent: a profanity/clarity suggestion on the only usable snippet
    must not be overwritten merely to create the evaluation. If no stored
    acoustic candidate exists, nominate an exact current-Take audio snippet
    here with neutral copy. The UI asks one qualitative yes/no question; it
    never claims that the detector found a confident delivery."""
    fallbacks = []
    for ordinal, piece in enumerate(current):
        sid = str(piece.get("snippet_id") or "")
        if not sid or sid in excluded or sid in already_ranked:
            continue
        fallbacks.append((
            2,
            ordinal,
            piece,
            {
                "kind": "emphasize",
                "trigger": "confidence_review",
                "why": _CONFIDENCE_REVIEW_WHY,
            },
        ))
    return fallbacks


def _ranked_candidates(current: list, suggestion_map: dict,
                       excluded: set) -> list:
    """Every candidate, detector rows first, then in document order."""
    candidates = _detector_candidates(current, suggestion_map, excluded)
    already_ranked = {
        str(piece.get("snippet_id") or "")
        for _rank, _ordinal, piece, _suggestion in candidates
    }
    candidates.extend(_review_fallbacks(current, excluded, already_ranked))
    # Do not choose here by first fit. Every structurally placeable candidate
    # is evaluated below; positive detector evidence, closed cue evidence and
    # exact phrase anchoring all outrank document position.
    candidates.sort(key=lambda item: item[1])
    return candidates


def _slide_regions(canonical: list, slide: Optional[int],
                   text_length: int) -> list:
    """The well-formed canonical regions on the piece's own slide.

    Same-slide provenance is the hard boundary. A deckless canonical
    document uses None on both sides; that is one honest unlinked talk
    section, not permission to invent a deck page."""
    return [
        p for p in canonical
        if _int(p.get("slide_index")) == slide
        and _int(p.get("start")) is not None
        and _int(p.get("end")) is not None
        and 0 <= int(p["start"]) < int(p["end"]) <= text_length
    ]


def _region_anchor(canonical_text: str, spoken: str,
                   picked: Any) -> Optional[tuple[int, tuple[int, int], str]]:
    """``(score, local span, role)`` inside one region, or None.

    The picked quote scores 3, a phrase shared with what was spoken 2, and
    a routing word 1."""
    local = _ci_slice(canonical_text, picked)
    if local is not None:
        return 3, local, "spoken_phrase"
    local = _shared_phrase(spoken, canonical_text)
    if local is not None:
        return 2, local, "spoken_phrase"
    local = _route_word(canonical_text)
    if local is None:
        return None
    return 1, local, "slide_route"


def _best_anchor(text: str, regions: list, spoken: str,
                 picked: Any) -> Optional[tuple]:
    """``(-score, at, region, (start, end), role)``: the best anchor over
    the slide's regions, the earliest on a tie, or None."""
    ranked: list[tuple[int, int, dict, tuple[int, int], str]] = []
    for region in regions:
        lo, hi = int(region["start"]), int(region["end"])
        anchor = _region_anchor(text[lo:hi], spoken, picked)
        if anchor is None:
            continue
        score, local, role = anchor
        ranked.append((
            -score,
            lo + local[0],
            region,
            (lo + local[0], lo + local[1]),
            role,
        ))
    if not ranked:
        return None
    ranked.sort(key=lambda item: (item[0], item[1]))
    return ranked[0]


def _resolve_candidate(text: str, doc: dict, canonical: list,
                       positive_rank: int, ordinal: int, piece: dict,
                       suggestion: dict) -> Optional[tuple]:
    """``(sort key, change, evidence_piece)`` for one candidate, or None
    when it cannot be placed honestly on its own slide."""
    slide = _int(piece.get("slide_index"))
    regions = _slide_regions(canonical, slide, len(text))
    if not regions:
        return None
    best = _best_anchor(text, regions, str(piece.get("text") or ""),
                        suggestion.get("emphasis_quote"))
    if best is None:
        return None
    _score, _at, region, (start, end), anchor_role = best
    sid = str(piece.get("snippet_id"))
    take_session_id = str(
        piece.get("take_session_id") or doc.get("take_session_id") or "")
    if not take_session_id:
        return None
    manager_evidence: dict[str, Any] = {
        "detector_rank": (2 if positive_rank == 0 else
                          1 if positive_rank == 1 else 0),
        "anchor_score": -int(_score),
        "fallback": positive_rank == 2,
    }
    change: dict[str, Any] = {
        # One snippet may also carry a wording candidate. Feedback item
        # identity must therefore name the family as well as the snippet;
        # the underlying snippet UUID remains separate for playback and
        # owner routing.
        "id": f"confident-voice:{sid}",
        "snippet_id": sid,
        "take_session_id": take_session_id,
        "kind": "bold",
        "source": "confident_voice",
        "span": {"start": start, "end": end},
        "quote": text[start:end],
        "why_key": "confident_voice",
        "why": suggestion.get("why"),
        "anchor_role": anchor_role,
        "_manager_evidence": manager_evidence,
    }
    cues = _cue_keys(suggestion)
    if cues:
        change["cue_keys"] = cues
        manager_evidence["cue_count"] = len(cues)
    evidence_piece = {
        **region,
        "start": start,
        "end": end,
        "text": text[start:end],
        "snippet_id": sid,
        "take_session_id": take_session_id,
        "slide_index": slide,
    }
    return (
        (
            -int(manager_evidence["detector_rank"]),
            -len(cues),
            int(_score),
            ordinal,
            sid,
        ),
        change,
        evidence_piece,
    )


def _inputs(served_text: Any, canonical_pieces: Any, take_document: Any,
            suggestions: Any, excluded_snippet_ids: Any) -> tuple:
    """The caller's arguments, with anything of the wrong shape as empty."""
    text = served_text if isinstance(served_text, str) else ""
    doc = take_document if isinstance(take_document, dict) else {}
    current = [p for p in (doc.get("pieces") or []) if isinstance(p, dict)]
    canonical = [p for p in (canonical_pieces or []) if isinstance(p, dict)]
    suggestion_map = suggestions if isinstance(suggestions, dict) else {}
    excluded = {
        str(value) for value in (excluded_snippet_ids or []) if value
    }
    return text, doc, current, canonical, suggestion_map, excluded


def current_take_confident_voice_candidate(
    served_text: Any,
    *,
    canonical_pieces: Any,
    take_document: Any,
    suggestions: Any,
    excluded_snippet_ids: Any = None,
) -> tuple[Optional[dict], Optional[dict]]:
    """Return one exact current-Take Confident Voice row and evidence piece.

    The result is ``(change, evidence_piece)``.  Both carry the current Take's
    session/snippet identity.  ``evidence_piece`` carries the canonical slide
    span used solely to route the feedback into the right deck chunk.
    ``(None, None)`` means the Project lacks enough structural provenance to
    place the audio honestly; callers fail the required family closed.
    """
    text, doc, current, canonical, suggestion_map, excluded = _inputs(
        served_text, canonical_pieces, take_document, suggestions,
        excluded_snippet_ids)
    if not text or not current or not canonical:
        return None, None

    resolved = []
    for positive_rank, ordinal, piece, suggestion in _ranked_candidates(
            current, suggestion_map, excluded):
        found = _resolve_candidate(text, doc, canonical, positive_rank,
                                   ordinal, piece, suggestion)
        if found is not None:
            resolved.append(found)
    if not resolved:
        return None, None
    resolved.sort(key=lambda item: item[0])
    return resolved[0][1], resolved[0][2]
