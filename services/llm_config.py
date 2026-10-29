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
  ``SPEC_DELIVERY_ALIGNMENT``) so the temperature / max_tokens /
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
    timeout_seconds: Optional[float] = None
    """Forwarded verbatim to OpenAI's API. ``None`` = default (plain
    text). For JSON output use ``{"type": "json_object"}``; for a
    pinned schema use ``{"type": "json_schema", "json_schema": ...}``
    and supply the schema dict next to the service code."""


# ── Named specs for each existing user-facing LLM surface ───────
#
# When you add a new LLM surface, add its spec here. Co-locating the
# decoding parameters with the model choice is what makes this file
# useful — without it, the constants would just be model strings.


SPEC_TAKE_SUMMARY = LLMSpec(
    model=STRONG_MODEL,
    temperature=0.6,
    max_tokens=180,
    timeout_seconds=20.0,
)
"""The closing summary after a Take's review (founder lock 2026-10-12,
moment and feedback chat, section 3; cheeky and curious since 2026-10-14):
2-4 short sentences, a colleague talking. ``services.take_summary``."""


SPEC_MASTER_DOC_RAG = LLMSpec(
    model=CHEAP_MODEL,
    temperature=0.4,
    # ~50-word answer (≤400 chars ≈ 100 tokens) plus the JSON wrapper
    # (~30 tokens). A reply cut off mid-JSON fails json.loads and falls
    # back (lane → mega-prompt → _fallback_payload), never crashes.
    max_tokens=220,
    # Master Doc RAG uses a strict json_schema; the schema dict lives
    # in services/master_doc_rag.py as ``_RESPONSE_SCHEMA`` and is
    # passed through at call time. Spec leaves response_format=None
    # so the caller wires it explicitly.
    response_format=None,
)
"""Chat reply for the post-signup FAQ surface (master_doc_rag)."""

SPEC_MASTER_DOC_ROUTER = LLMSpec(
    model=CHEAP_MODEL, temperature=0.0, max_tokens=40,
)

SPEC_COACH_COMMENT_DRAFT = LLMSpec(
    model=CHEAP_MODEL, temperature=0.6, max_tokens=320,
)
SPEC_EXERCISE_SCRIPT_DRAFT = LLMSpec(
    model=CHEAP_MODEL, temperature=0.6, max_tokens=500,
)
"""A first script for a coach's exercise video, shown to the coach only
(founder 2026-09-29, decision 4). Never reaches a speaker as drafted."""

SPEC_COACH_ANSWER_DRAFT = LLMSpec(
    model=CHEAP_MODEL, temperature=0.5, max_tokens=400,
)
"""One draft per coach request, by its kind (founder 2026-09-30, C2): an
exercise script, a praise line or a clearer version. Shown to the coach
only; the coach's edited final is what anyone else sees, and the (draft,
final) pair is the learning record (services.feedback_pairs)."""


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


SPEC_DELIVERY_ALIGNMENT = LLMSpec(
    model=CHEAP_MODEL,
    # A single classification — deterministic-leaning, no prose.
    temperature=0.2,
    # Just the tiny {"words_positive": bool} envelope.
    max_tokens=20,
    response_format={"type": "json_object"},
)
"""Congruence delivery star: judges 'are the words clearly positive?' over a
flat/low-arousal moment (founder 2026-07-24 sign-off). Returns only
{"words_positive": bool} — the star copy lives FE-side, keyed by device."""


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
    # Schema lives in services/slide_selection.py, passed at call time.
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


SPEC_SPEAKER_MEMORY = LLMSpec(
    model=CHEAP_MODEL,
    # Low temperature: the note must stay close to what the events show.
    temperature=0.2,
    max_tokens=220,
    response_format=None,
)
"""Speaker memory (WIL-74, founder 2026-10-20) — rewrites one speaker's
private note (at most five lines) from the old note and the new events.
Never shown to anyone but the founder; read by Will (services.speaker_memory)."""


SPEC_WILL_QUESTION_HEARD = LLMSpec(
    model=CHEAP_MODEL,
    # Zero: it copies words out of the Take, it never writes any.
    temperature=0.0,
    max_tokens=60,
    response_format={"type": "json_object"},
    timeout_seconds=8.0,
)
"""Will's question after a Take (founder 2026-10-20, N82) — reads who the
talk is for and what it asks, word for word from the Take or nothing; code
keeps only words the Take says (services.will_question.read_heard)."""


SPEC_WILL_QUESTION_VARY = LLMSpec(
    model=CHEAP_MODEL,
    # Warm enough to reword, never to invent: the words are checked against
    # the signed question before Will says them.
    temperature=0.7,
    max_tokens=80,
    timeout_seconds=8.0,
)
"""Will's question after a Take, said with a light touch (founder 2026-10-20,
N86) — the signed question in slightly different words; code keeps it only
when it still means the signed one and keeps the speaker's own words in it
(services.will_question.read_varied), else Will says the signed words."""

SPEC_WILL_LEAD_IN = LLMSpec(
    model=CHEAP_MODEL,
    # Warm enough to tie the ask to the Take, never to invent: the words
    # are checked (no number, the ask still said) before Will says them.
    temperature=0.7,
    max_tokens=120,
    timeout_seconds=8.0,
)
"""Will's lead-in to an ask after a Take (founder 2026-10-20, N89): one or
two sentences tied to the Take, then the ask's signed words with a light
touch; code keeps it only when services.will_question.read_lead_in does,
else the ask is said as written."""


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


SPEC_V4_TAKE_TAGS = LLMSpec(
    model=CHEAP_MODEL,
    # Constrained labels (six roles, three holding-together answers): low
    # temperature for stability across replays.
    temperature=0.0,
    # One batched call per Take (founder H6): a role and an answer per moment.
    max_tokens=2000,
    response_format=None,  # schema via response_format_override
)
"""V4 B1.3/B1.6: one call per Take tags each moment's role (S-B1b A) and
reads whether its sentences hold together (S-B1 A). Internal only (AC-9)."""


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


"""Master-document skeleton chunking (founder 2026-07-22): ONE pass per
project splitting the take-1 transcript into logical blocks. Returns
piece INDEX boundaries + short labels ONLY — never transcript text
(L1: block text is always the verbatim recorded pieces)."""

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


"""FIX.1 — Contextual follow-up question for the interview funnel.
Replaces the legacy alternation prompt that produced bicycle →
boardroom non-sequiturs (tester feedback)."""


SPEC_COMMUNITY_CONTENT = LLMSpec(
    model=STRONG_MODEL,
    # Founder-specified gpt-4o, not mini: this is public-facing marketing
    # copy the founder pastes under his own name, and the cheap model
    # flattens the voice into LinkedIn boilerplate.
    # 0.7 — warmth over determinism. The three formats are meant to read
    # like a person, and there is a human reviewing every one before it
    # goes anywhere.
    temperature=0.7,
    # Three posts in one response; the longest (Fear) runs to ~1300 chars.
    max_tokens=2400,
    response_format=None,  # strict json_schema via override, next to the service
)
"""Community Content Studio — derives the Myth-bust / Fear / Win community
posts from a Journal post (the week's Technique anchor), per the content
model in services/prompts/community_content_strategy.md. Founder-only
marketing surface: it never feeds any F1 assembly path (L1) and its output
is never publishable to the public Journal."""


SPEC_JOURNAL_IMAGE_BRIEF = LLMSpec(
    model=CHEAP_MODEL,
    # The expensive call on this surface is the IMAGE (cents, not fractions of
    # one), so the brief runs on mini — and distilling one essay into one
    # scene is well inside its range.
    # 0.8 — the highest temperature in this file, and deliberate: the whole
    # point of "Regenerate" with no note is a DIFFERENT scene for the same
    # essay. A low temperature would redraw the same cover and the button
    # would look broken.
    temperature=0.8,
    # One image prompt (≤3800 chars) plus a one-sentence alt text.
    max_tokens=1200,
    response_format=None,  # strict json_schema via override, next to the service
)
"""Journal cover-image BRIEF (founder 2026-07-28) — turns a journal post (plus
the founder's steer and the previous brief) into one image-model prompt and
its public alt text. Marketing surface: never feeds an F1 assembly path (L1).
The alt text is public copy, so services/journal_image.py construct-guards it
before it can be promoted onto a post."""


SPEC_CEO_INTELLIGENCE = LLMSpec(
    model=STRONG_MODEL,
    # Architecture synthesis should be stable and evidence-led, not creative.
    temperature=0.1,
    # One bounded Architecture table or ML graph plus risks, next steps, and
    # citations. The source input carries detail; output stays compact.
    max_tokens=3600,
    response_format=None,  # strict schema lives beside ceo_intelligence
)
"""Admin-only CEO proposal generator. Output is always a preview revision;
the model has no route to code, runtime data, deployment, or official status."""


SPEC_SUNDAY_NOTE = LLMSpec(
    model=STRONG_MODEL,
    # Close to what the week shows; a little room for the reflection.
    temperature=0.3,
    max_tokens=900,
    response_format={"type": "json_object"},
)
"""The Sunday note (Will learning plan step 2, founder 2026-10-20): one case
in the founder's form from the week's notes, Takes and chat. Founder only;
read in the Lounge (services.sunday_note)."""


SPEC_LIFE_GOAL_DRAFT = LLMSpec(
    model=STRONG_MODEL,
    # Their own words in one sentence; no room to invent.
    temperature=0.2,
    max_tokens=300,
    response_format={"type": "json_object"},
)
"""Life goals (Will learning plan step 3, N172): one goal drafted from the
founder's own answers in the lens, with the words it came from. Founder only
(services.life_goals)."""


SPEC_IN_CONTROL = LLMSpec(
    model=STRONG_MODEL,
    # Will's answer to a worry: two or three short lines from its guide.
    temperature=0.3,
    max_tokens=300,
    response_format={"type": "json_object"},
)
"""What is in your control (N241 O1, N258): is a # note a worry about
something out of the person's hands, and Will's answer from its signed
guide, once per worry (services.in_control)."""


SPEC_SALES_NOTE = LLMSpec(
    model=CHEAP_MODEL,
    # Detection only: a sale that stalled or was lost, or not.
    temperature=0.0,
    max_tokens=40,
    response_format={"type": "json_object"},
)
"""The sales framing (N241 P2): is a # note about a sale of theirs that
stalled or was lost? (services.sales_framing)."""


SPEC_SALES_CHANGE = LLMSpec(
    model=STRONG_MODEL,
    # One or two short lines from Will's guide: one change to one step.
    temperature=0.3,
    max_tokens=200,
    response_format={"type": "json_object"},
)
"""The sales framing (N241 P2, N258): one change to the step the sale
stalled at, from Will's signed guide (services.sales_framing)."""


SPEC_YOUR_WHY_DRAFT = LLMSpec(
    model=STRONG_MODEL,
    # Their own words in three short lines; no room to invent.
    temperature=0.2,
    max_tokens=400,
    response_format={"type": "json_object"},
)
"""Your why (N255 Q2): the why, the vision and how they treat people, each
drafted only from their own answers, with the words it came from
(services.your_why)."""


SPEC_YOUR_WHY_ASK = LLMSpec(
    model=CHEAP_MODEL,
    # Detection only: an ask for their why, or not.
    temperature=0.0,
    max_tokens=40,
    response_format={"type": "json_object"},
)
"""Your why (N255 Q3): does a chat message ask to set, see or change their
why? Runs only after a keyword pre-gate (services.your_why)."""


SPEC_STRENGTHS_READ = LLMSpec(
    model=STRONG_MODEL,
    # One read of a note: a kept strength at work, a trait on two days, a
    # talk's date. Their words only; no room to invent.
    temperature=0.1,
    max_tokens=300,
    response_format={"type": "json_object"},
)
"""Strengths (N241 N2 to N4, signed N258): under a # note, a kept strength
at work in it, a strength shown on two different days, and a talk date the
note names (services.strengths)."""



SPEC_WALK_QUOTE = LLMSpec(
    model=STRONG_MODEL,
    # A pick only: which of the speaker's own kept words answers the
    # sentence, or none. No words written, so no room to invent.
    temperature=0.0,
    max_tokens=60,
    response_format={"type": "json_object"},
)
"""The walk quotes your notebook (N268): after a good try on a Clearer
version, a kept strength, the vision or a # note that answers the sentence,
or none (services.walk_quote)."""

SPEC_LIFE_GOAL_ASK = LLMSpec(
    model=CHEAP_MODEL,
    # Detection only: a life goal asked for, or not.
    temperature=0.0,
    max_tokens=120,
    response_format={"type": "json_object"},
)
"""Life goals (N172 M2): does a chat message ask to add or see a life goal
(never the talk's goal)? Runs only after a keyword pre-gate, founder only
(services.life_goals)."""


SPEC_TEMPO_TOPIC = LLMSpec(
    model=CHEAP_MODEL,
    # A name for what the speaker talked about, never a new idea.
    temperature=0.2,
    max_tokens=24,
    timeout_seconds=8.0,
)
"""The tempo step's topic (founder 2026-10-26, N162, N166): a few words naming
what the stretch was about, said back in "Tell me more about {topic}". Code
keeps it only when it is short and plain (services.tempo_stretch.read_topic);
else the step says "that part"."""


SPEC_PLAN_TURN = LLMSpec(
    model=STRONG_MODEL,
    # The speaker's own words in a signed template; no room to invent.
    temperature=0.2,
    max_tokens=600,
    response_format={"type": "json_object"},
    timeout_seconds=25.0,
)
"""The plan's questions (N138, N139, N145, N150): Will's reply naming the
speaker's event in their words, and the next follow-up as a signed template
fitted to them. Code keeps a question only when it matches its template
(services.plan.fitted_question); else Will says the plain template."""
