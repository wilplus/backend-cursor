"""Centralized LLM model + decoding-spec constants.

One place to find every model name, temperature, and token cap used
by the backend. Replaces string-literal ``model="gpt-4o-mini"`` calls
scattered across service modules — the future cost of an OpenAI
model deprecation is now ONE diff instead of N.

Convention
----------
- Model identifiers are bare strings (``CHEAP_MODEL``, ``STRONG_MODEL``,
  optionally future ``LOCAL_MODEL`` etc.). Bump them in one place when
  OpenAI deprecates.
- Each user-facing LLM surface gets its own named ``LLMSpec`` (e.g.
  ``SPEC_SNIPPET_FOLLOWUP``) so the temperature / max_tokens /
  response_format choice is captured next to the model decision and
  visible at a glance.
- New LLM surfaces should add their spec here, NOT inline at the
  call site.
- ``response_format`` is forwarded verbatim to OpenAI; pass the
  full dict the API expects (``{"type": "json_object"}`` or
  ``{"type": "json_schema", "json_schema": {...}}``). Services with
  service-specific JSON schemas keep those schemas next to the
  service code and pass them through at call time.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ── Canonical model identifiers ──────────────────────────────────
#
# Bump these when OpenAI deprecates a model. Every caller imports
# the SYMBOL, not the string, so there's no scattered grep-and-replace.

CHEAP_MODEL = "gpt-4o-mini"
"""Default for chat replies, digests, intent classification, single-turn
generation. Low cost, fast latency."""

STRONG_MODEL = "gpt-4o"
"""For graders, judges, critical reasoning, and anything where the
quality bar justifies the higher per-token cost. Use sparingly."""


# ── LLMSpec dataclass ────────────────────────────────────────────


@dataclass(frozen=True)
class LLMSpec:
    """Minimum config for one ``chat.completions.create`` call.

    Frozen so it's hashable + can't be mutated by callers. Specs are
    constants — define new ones in this module, don't mutate.
    """
    model: str
    temperature: float
    max_tokens: int
    response_format: Optional[dict] = None
    """Forwarded verbatim to OpenAI's API. ``None`` = default (plain
    text). For JSON output use ``{"type": "json_object"}``; for a
    pinned schema use ``{"type": "json_schema", "json_schema": ...}``
    and supply the schema dict next to the service code."""


# ── Named specs for each existing user-facing LLM surface ───────
#
# When you add a new LLM surface, add its spec here. Co-locating the
# decoding parameters with the model choice is what makes this file
# useful — without it, the constants would just be model strings.


SPEC_MASTER_DOC_RAG = LLMSpec(
    model=CHEAP_MODEL,
    temperature=0.4,
    max_tokens=600,
    # Master Doc RAG uses a strict json_schema; the schema dict lives
    # in services/master_doc_rag.py as ``_RESPONSE_SCHEMA`` and is
    # passed through at call time. Spec leaves response_format=None
    # so the caller wires it explicitly.
    response_format=None,
)
"""Chat reply for the post-signup FAQ surface (master_doc_rag)."""


SPEC_CONVERSATION_SUMMARY = LLMSpec(
    model=CHEAP_MODEL,
    # Low temp — same input should produce the same digest.
    # The summary IS the running memory; we don't want it drifting
    # between identical replays.
    temperature=0.3,
    # 200 leaves headroom for the ~150-token target digest.
    max_tokens=250,
    response_format=None,  # plain text digest, not JSON
)
"""Rolling per-session conversation digest (Phase A2.1)."""


SPEC_DIRECTIVE_SUGGESTIONS = LLMSpec(
    model=CHEAP_MODEL,
    # Some warmth — coaching questions shouldn't feel mechanical —
    # but not so high we lose grounding in the context payload.
    temperature=0.5,
    # Tightened from 800 → 400 after the arc length dropped from
    # 5 → 2 (items 2 / 7 in the Single-Slot-Chat spec).
    max_tokens=400,
    response_format={"type": "json_object"},
)
"""Admin's 5-step (now 2-step) directive arc suggestion generator."""


SPEC_COACHING_INTRO = LLMSpec(
    model=CHEAP_MODEL,
    # Warmth without drift. Mirrors snippet-followup.
    temperature=0.5,
    max_tokens=120,
    response_format={"type": "json_object"},
)
"""Personalized intro line for the post-labeling recording session."""


SPEC_SNIPPET_FOLLOWUP = LLMSpec(
    model=CHEAP_MODEL,
    # Some warmth; not creative writing.
    temperature=0.4,
    max_tokens=200,
    response_format={"type": "json_object"},
)
"""One-shot follow-up question after a user labels a snippet (BE-0)."""


SPEC_EVAL_GRADER = LLMSpec(
    model=STRONG_MODEL,
    # Deterministic grading — we want repeatability between runs of
    # the same eval.
    temperature=0.0,
    max_tokens=200,
    response_format={"type": "json_object"},
)
"""Semantic grader for tests/evals/master_doc_probe.py."""


SPEC_NEXT_SESSION_ICEBREAKER = LLMSpec(
    model=CHEAP_MODEL,
    # Some warmth — the question should feel like a coach who
    # remembered, not a stock prompt — but kept moderate so the
    # output stays anchored in the specific snippets we passed in.
    temperature=0.7,
    # 200 is plenty for ONE ≤280-char question (≈ 60 tokens) with
    # safety margin for verbose schemas.
    max_tokens=200,
    # Schema lives in services/next_session_icebreaker.py and is
    # passed through at call time via response_format_override.
    response_format=None,
)
"""AI-prefilled icebreaker for session N+1 (Task 10)."""


SPEC_SESSION_CADENCE = LLMSpec(
    model=CHEAP_MODEL,
    # Some warmth so the cadence reads like Will inviting the next take,
    # not a form letter — but kept moderate because the beat is PINNED
    # doctrine (fixed facts + safety caveat survive verbatim, §2). The
    # renderer translates/voices the spec; it must not invent.
    temperature=0.5,
    # One short multi-line bubble (intent + facts + optional caveat +
    # woven goal). 320 leaves headroom for non-Latin scripts (which
    # tokenize heavier) without ever running long.
    max_tokens=320,
    # Schema lives in services/session_cadence.py and is passed at call
    # time via response_format_override.
    response_format=None,
)
"""Explore-Session cadence bubble — renders a language-neutral beat
spec into the user's language (Prompt A §2/§4). The protocol (modes,
fixed facts, exercise/safety caveat) is doctrine and is NEVER invented
by the LLM — see services/session_cadence.py ``BEATS``."""


SPEC_BEST_PRESENTATION = LLMSpec(
    model=CHEAP_MODEL,
    # Very low temp — the composition MOSTLY reuses the user's own best lines
    # verbatim and may change only a FEW words per slide for continuity +
    # slide-accuracy. It is NOT creative writing; high temp would invent.
    temperature=0.2,
    # A handful of short slide lines; small cap keeps it from running long.
    max_tokens=600,
    # Schema lives in services/best_presentation.py, passed at call time.
    response_format=None,
)
"""Best-Presentation composition (Prompt D §4) — lightly stitches the user's
per-slide best CHALLENGE lines into continuous 'ideal presentation' text.
Grounded in the recorded transcript + slide{title,body}; no new claims."""


SPEC_GOAL_UPDATE = LLMSpec(
    model=CHEAP_MODEL,
    # Low temp — goal-update DETECTION must be conservative + stable (a
    # casual "my goal is to relax" must NOT trigger a profile write). The
    # in-language confirmation it also returns needs no creativity.
    temperature=0.2,
    max_tokens=240,
    # Schema lives in services/goal_update.py, passed at call time.
    response_format=None,
)
"""Explore-Session goal-update intercept (Prompt A §6 C4) — detects an
explicit "change my goal to X", extracts the new goal, and renders an
in-language confirmation. Runs BEFORE master_doc_rag (never a rule edit)."""


SPEC_AUDIT_POINTER = LLMSpec(
    model=CHEAP_MODEL,
    # Low temp — one short, in-language line pointing the user to their audit
    # button. No creativity, no explanation; the line just frames the button.
    temperature=0.3,
    max_tokens=120,
    # Schema lives in services/audit_intent.py, passed at call time.
    response_format=None,
)
"""Explore/Audit — the short in-language bubble line that accompanies the
'audit' suggested_action button (Prompt C §5). Never explains what an audit
is; the audit CONTENT is the coach's PDF."""


SPEC_ONBOARDING_OPENER = LLMSpec(
    model=CHEAP_MODEL,
    # Low warmth — the ack is a deadpan bridge into a canonical
    # punchline. Too much creativity here adds line-noise before
    # the joke lands.
    temperature=0.3,
    # 80-char target output; 60 tokens is overkill but cheap.
    max_tokens=60,
    response_format={"type": "json_object"},
)
"""Pre-punchline acknowledgement line in the onboarding dad-joke
opener (Ticket 2). The canonical punchline and pivot line are
NEVER produced by the LLM — see services/onboarding_opener.py."""


SPEC_SNIPPET_STICKINESS = LLMSpec(
    model=CHEAP_MODEL,
    # Low temp — a coherence score should be stable across replays of
    # the same snippet, not creative.
    temperature=0.3,
    # One batch call scoring N (≤10) snippets, each a small float + a
    # ≤200-char comment. 600 covers the worst case with headroom.
    max_tokens=600,
    # Schema (per_snippet array) passed via response_format_override in
    # services/snippet_stickiness.py.
    response_format=None,
)
"""Per-snippet stickiness (topic-coherence composite + comment) for the
willab Readout card (design §5). Distinct from the session-level
stickiness metric (services/stickiness.py)."""


SPEC_SLIDE_CLAIMS = LLMSpec(
    model=CHEAP_MODEL,
    # Extraction, not judgment — keep it deterministic-ish.
    temperature=0.2,
    # One batched call decomposing the whole deck (≤60 slides) into a few
    # short claims each; bounded output.
    max_tokens=1500,
    response_format=None,  # schema via response_format_override
)
"""Decompose each slide (title + body) into atomic, checkable claims for the
slide-delivery claim-ledger (Stickiness #2). Extraction only."""


SPEC_SLIDE_ENTAILMENT = LLMSpec(
    model=CHEAP_MODEL,
    # Constrained verdicts (covered/partial/not) — low temp for stability.
    temperature=0.2,
    # One batched call: per snippet, a verdict per claim of its mapped slide.
    max_tokens=1500,
    response_format=None,  # schema via response_format_override
)
"""Per-snippet textual entailment of its mapped slide's claims (covered |
partial | not) — the claim-ledger verdicts behind Stickiness #2."""


SPEC_SAY_IT_STRONGER = LLMSpec(
    model=CHEAP_MODEL,
    # Founder spec 2026-07-07: deterministic enough to be consistent,
    # creative enough to give real alternatives.
    temperature=0.5,
    # Up to 3 word-level upgrades + two full-sentence rewrites + a
    # short qualitative "why".
    max_tokens=1200,
    response_format=None,  # strict json_schema via override (next to the service)
)
"""'Say It Stronger' — per-snippet rewrite suggestions on the user
readout (replaces the raw acoustic NUMBERS there; the metrics stay in
the data/ranking/coach view). Suggestion overlay for the composed WORDS
(L1): upgrades never become assembled text — best_presentation reads them
only as key-phrase DISPLAY HINTS (bolding spans already verbatim-present;
off entirely under POLISH_AS_SUGGESTIONS)."""


SPEC_MOMENT_SUGGESTION = LLMSpec(
    model=CHEAP_MODEL,
    # Same balance as Say-It-Stronger: consistent, but real alternatives.
    temperature=0.5,
    # One short why-line (+ one replacement phrase for replace-kind).
    max_tokens=300,
    response_format={"type": "json_object"},
)
"""Star suggestions (founder 2026-07-18): per key-moment snippet, the short
qualitative 'why' (+ an audience-appropriate replacement phrase for the
replace kind). Suggestion overlay ONLY — approved replacements write the
student's own copy at serve time, never the canonical ideal text (L1)."""


SPEC_CONTEXTUAL_FOLLOWUP = LLMSpec(
    model=CHEAP_MODEL,
    # Moderate warmth — the question should feel like a coach who
    # actually listened, not a stock prompt. Lower than the
    # icebreaker (0.7) because the LLM has TWO constraints to
    # juggle (bridge naturally AND elicit a specific intent) and
    # higher temp loses one of them under load.
    temperature=0.55,
    # Two-sentence question + a 5-12 word bridge_to debug tag.
    # 150 leaves room for verbose model wrapping without truncating.
    max_tokens=150,
    response_format={"type": "json_object"},
)
"""FIX.1 — Contextual follow-up question for the interview funnel.
Replaces the legacy alternation prompt that produced bicycle →
boardroom non-sequiturs (tester feedback)."""
