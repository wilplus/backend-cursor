"""Prompts for the slide claim-ledger (Stickiness #2) — F1 surfaces.

Moved verbatim from services/slide_alignment.py (registry extraction
2026-08-03). Two prompts: decompose slides into atomic claims
(extraction only), then per-snippet textual entailment of those claims
(covered | partial | not). The JSON schemas stay next to the service.
"""
from __future__ import annotations

CLAIMS_SYSTEM = (
    "You decompose presentation slides into atomic, checkable CLAIMS — the "
    "discrete points a speaker would need to make to deliver each slide. "
    "Each claim is one short standalone statement (no slide jargon). This "
    "is extraction, not judgment. 1-5 claims per slide; fewer for sparse "
    "slides. Return strict JSON: {\"slides\":[{\"index\":<int>,\"claims\":"
    "[\"...\"]}]} with one entry per input slide, same indexes."
)

ENTAILMENT_SYSTEM = (
    "For each snippet, decide whether its transcript ENTAILS each of its "
    "slide's claims — does the speaker actually say that point, in any "
    "words? Judge MEANING, never literal term presence: 'top line grew' "
    "entails 'revenue grew'; explaining a concept without naming it counts "
    "as covered. Per claim return one of: covered | partial | not. "
    "'partial' = touched but incomplete/vague. Return strict JSON: "
    "{\"snippets\":[{\"ref\":\"...\",\"verdicts\":[\"covered\"|\"partial\""
    "|\"not\", ...]}]}, verdicts aligned to that snippet's claims order, "
    "one entry per input snippet."
)

REGISTER = {
    "slide_claims.system": CLAIMS_SYSTEM,
    "slide_entailment.system": ENTAILMENT_SYSTEM,
}
