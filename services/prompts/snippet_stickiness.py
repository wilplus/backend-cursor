"""Prompt for per-snippet stickiness (topic-coherence) — Readout card §5.

Moved verbatim from services/snippet_stickiness.py (registry extraction
2026-08-03). ``system()`` is a builder so ``with_voice_rules`` applies
at call time, exactly as the service did inline.
"""
from __future__ import annotations

CORE = (
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


def system() -> str:
    from services.will_voice import with_voice_rules
    return with_voice_rules(CORE)


REGISTER = {
    "snippet_stickiness.system": system,
}
