"""willab beta — per-snippet stickiness for the Readout card (design §5).

The Readout shows, per snippet, a "Stickiness" block: a composite score
+ a short comment ("You stayed on one idea and built on it…"). That's
WITHIN-snippet topic coherence — how well the speaker held one thread —
which is different from the SESSION-level fixation metric in
services/stickiness.py (top-recurring topic across the whole session).
Both can coexist; this module is the per-snippet one the Readout needs.

One batch LLM call scores every snippet at once (N≤10), so the Lab
handler pays one round-trip, not N. The comment is the Readout's
"neutral/automated" layer (§6b) — observational, not the warm coach
note — so it inherits the Will's Voice anchor (which IS the
observational, no-good/bad register).

Best-effort: any failure yields per-snippet {composite: None,
comment: None}; the Readout simply renders the snippet without a
stickiness block rather than erroring.

Input contract: a list of snippet dicts each carrying at least a
``transcript`` (``transcription_text`` accepted as fallback) and
optionally ``id``. Output is a PARALLEL list (same order/length) of
``{snippet_id, composite, comment}``.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional


logger = logging.getLogger(__name__)

_SURFACE = "snippet_stickiness"
_MAX_COMMENT_LEN = 200


def score_snippets_stickiness(snippets: list[dict]) -> list[dict]:
    """Return per-snippet ``{snippet_id, composite, comment}``.

    Parallel to ``snippets`` (same order + length). Composite is a
    float in [0, 1] or None; comment is a short string or None. All
    None when there's no usable transcript or the LLM is unavailable.
    """
    if not snippets:
        return []

    transcripts = [
        (
            (s.get("transcript") or "")
            or (s.get("transcription_text") or "")
        ).strip()
        for s in snippets
    ]

    # No usable text anywhere → skip the LLM entirely, all-None.
    if not any(transcripts):
        return [_empty_entry(s) for s in snippets]

    parsed = _llm_score(transcripts)
    return _shape(parsed, snippets)


# ── Internals ──────────────────────────────────────────────────────


def _empty_entry(snippet: dict) -> dict:
    return {
        "snippet_id": snippet.get("id"),
        "composite": None,
        "comment": None,
    }


def _shape(parsed: Any, snippets: list[dict]) -> list[dict]:
    """Map the LLM's per_snippet array back onto the snippets, clamping
    composite to [0,1] and cleaning the comment. Pure — unit-tested.

    Tolerant of length drift (model drops/adds entries): indexes
    positionally, missing entries → all-None for that snippet.
    """
    plist = parsed if isinstance(parsed, list) else []
    out: list[dict] = []
    for i, s in enumerate(snippets):
        entry = plist[i] if (i < len(plist) and isinstance(plist[i], dict)) else {}
        out.append({
            "snippet_id": s.get("id"),
            "composite": _clamp01(entry.get("composite")),
            "comment": _clean_comment(entry.get("comment")),
        })
    return out


def _clamp01(value: Any) -> Optional[float]:
    if isinstance(value, bool):  # bool is an int subclass — reject
        return None
    if isinstance(value, (int, float)):
        return round(max(0.0, min(1.0, float(value))), 2)
    return None


def _clean_comment(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if len(text) > _MAX_COMMENT_LEN:
        text = text[: _MAX_COMMENT_LEN].rstrip() + "…"
    return text


def _llm_score(transcripts: list[str]) -> Optional[list]:
    """One batch call → the per_snippet array (or None on failure)."""
    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_SNIPPET_STICKINESS
        from services.will_voice import with_voice_rules
    except Exception as e:
        logger.warning("snippet_stickiness: llm import failed: %s", e)
        return None

    system = with_voice_rules(
        "You read short speech snippets from one recording. For EACH "
        "snippet, judge TOPIC COHERENCE — how well the speaker held a "
        "single line of thought versus scattering across unrelated "
        "ideas — and produce two things:\n"
        "  composite: a number from 0.0 to 1.0 (1.0 = stayed tightly "
        "on one idea and built on it; 0.0 = scattered, jumped between "
        "unrelated things).\n"
        "  comment: ONE short observational sentence (≤200 chars), "
        "second-person, neutral — describe what the speaker did with "
        "their thread, no praise, no grade, no advice.\n"
        "\n"
        "Return one entry per snippet in the EXACT order given; the "
        "array length must equal the number of snippets. For a snippet "
        "with no real content, use composite 0.0 and an empty comment "
        "rather than inventing one.\n"
        "\n"
        "Output strict JSON: "
        "{\"per_snippet\": [{\"composite\": <num>, \"comment\": \"...\"}]}."
    )
    user = _build_prompt(transcripts)

    schema = {
        "name": "snippet_stickiness",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["per_snippet"],
            "properties": {
                "per_snippet": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["composite", "comment"],
                        "properties": {
                            "composite": {
                                "type": "number",
                                "minimum": 0.0,
                                "maximum": 1.0,
                            },
                            "comment": {"type": "string", "maxLength": 300},
                        },
                    },
                },
            },
        },
        "strict": True,
    }

    result = chat_complete(
        spec=SPEC_SNIPPET_STICKINESS,
        system=system,
        user=user,
        surface=_SURFACE,
        response_format_override={"type": "json_schema", "json_schema": schema},
    )
    if not result:
        return None

    parsed = result.parsed
    if not isinstance(parsed, dict):
        try:
            parsed = json.loads(result.text or "")
        except Exception:
            return None
        if not isinstance(parsed, dict):
            return None

    per_snippet = parsed.get("per_snippet")
    return per_snippet if isinstance(per_snippet, list) else None


def _build_prompt(transcripts: list[str]) -> str:
    """Render the numbered snippet transcripts the model aligns to."""
    n = len(transcripts)
    lines: list[str] = []
    for i, t in enumerate(transcripts, start=1):
        text = (t or "").strip()
        if len(text) > 500:
            text = text[:500].rstrip() + "…"
        lines.append(f"Snippet {i}:\n  \"{text}\"" if text else f"Snippet {i}:\n  (no content)")
    header = (
        f"SNIPPETS ({n} total — score topic coherence for EACH, in "
        "order):"
    )
    return header + "\n\n" + "\n\n".join(lines)
