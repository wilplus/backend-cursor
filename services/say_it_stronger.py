"""'Say It Stronger' — per-snippet rewrite suggestions (founder 2026-07-07).

Replaces the raw acoustic numbers on the USER readout with actionable,
metric-grounded language coaching: up to 3 word-level upgrades + two
full-sentence rewrites ("your voice" / "polished") + one short qualitative
"why", per snippet. The numbers themselves stay in `metrics`, in the L2
ranking blend, and on the coach view — this is presentation-layer only.

FENCES
------
* L1 — suggestion overlay ONLY for the composed WORDS: no upgrade/rewrite
  string may ever become part of the assembled best-presentation/ideal
  text. HONESTY NOTE (docstring-truth fix 2026-07-18 — the old absolute
  "never read by best_presentation.py" claim was false): best_presentation
  DOES read this module's upgrades, but only as DISPLAY HINTS — the
  per-slide ``key_phrases`` used to bold spans that ALREADY occur verbatim
  in the text (``if kp in text``; a rewrite that isn't a substring bolds
  nothing). The composed words themselves stay verbatim-select +
  coach-corrected; under POLISH_AS_SUGGESTIONS the key-phrase bolding is
  off entirely and edits reach the text only via user-approved stars.
* AC-9 / CONSTRUCT — the user-facing ``why`` / ``reason`` copy is guarded in
  code: no digits, none of the retired construct vocabulary. Acoustic
  evidence is expressed qualitatively and ONLY relative to the speaker's
  own averages across this take (self-referential, never population claims).
* LIVE LOOP — generation is fire-and-forget off the synchronous process
  path (mirrors coach_comment_drafter); every failure logs and skips.
  Write-once per snippet (only when NULL) so duplicate runs are idempotent.

The model never sees raw numbers either — metrics are converted to
plain-language self-comparisons in code before the call.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_MAX_UPGRADES = 3
_MAX_WHY_LEN = 500
_MAX_REWRITE_LEN = 600
_SUGGESTION_VERSION = 2  # v2: upgrades carry scope word|phrase (2026-07-14)

# AC-9 output guard — user-facing coaching copy must stay qualitative:
# any digit, or any of the retired construct family, kills the field.
_DIGIT_RE = re.compile(r"\d")
_GUARD_CONSTRUCT_RE = re.compile(
    r"\bthreat[\s:\-]*challenge\b"
    r"|\bt\s*:\s*c\b"
    r"|\bcharisma\s+(?:score|profile|classifier|ratio)\b"
    r"|\bstress\s+(?:score|classifier)\b"
    r"|\bkpi\b",
    re.IGNORECASE,
)


def _guard_copy(text: Any) -> Optional[str]:
    """Return the text iff it passes the AC-9 qualitative guard, else None."""
    if not isinstance(text, str):
        return None
    t = text.strip()
    if not t:
        return None
    if _DIGIT_RE.search(t) or _GUARD_CONSTRUCT_RE.search(t):
        return None
    return t[:_MAX_WHY_LEN]


# ── metrics → plain-language SELF-comparisons (the only form the LLM sees) ──

# metric key aliases, same normalization the drafter uses.
_AGG_KEYS = {
    "pace": ("wpm", "speech_rate"),
    "pitch_variety": ("f0_sd",),
    "pausing": ("pause_ratio",),
    "energy": ("dynamic_db", "loudness_range"),
}

# relative tolerance before we call a delta real (avoid noise-level claims).
_REL_TOL = 0.12


def aggregate_session_means(snippets: Any) -> dict:
    """Mean of each normalized metric across the take's snippets. Pure."""
    sums: dict = {}
    counts: dict = {}
    for snip in (snippets or []):
        m = snip.get("metrics") if isinstance(snip.get("metrics"), dict) else {}
        for key, aliases in _AGG_KEYS.items():
            v = next(
                (m.get(a) for a in aliases
                 if isinstance(m.get(a), (int, float))
                 and not isinstance(m.get(a), bool)),
                None,
            )
            if v is not None:
                sums[key] = sums.get(key, 0.0) + float(v)
                counts[key] = counts.get(key, 0) + 1
    return {k: sums[k] / counts[k] for k in sums if counts.get(k)}


def qualitative_self_comparison(metrics: Any, session_means: Any) -> dict:
    """This moment vs the speaker's OWN average across the take, in plain
    words only ("your pauses here are shorter than your average"). Never a
    number, never a population claim. Pure; {} when nothing comparable."""
    m = metrics if isinstance(metrics, dict) else {}
    means = session_means if isinstance(session_means, dict) else {}
    labels = {
        "pace": ("faster than your average", "slower than your average"),
        "pitch_variety": ("more expressive than your average",
                          "flatter than your average"),
        "pausing": ("longer pauses than your average",
                    "shorter pauses than your average"),
        "energy": ("more energetic than your average",
                   "steadier than your average"),
    }
    out: dict = {}
    for key, aliases in _AGG_KEYS.items():
        v = next(
            (m.get(a) for a in aliases
             if isinstance(m.get(a), (int, float))
             and not isinstance(m.get(a), bool)),
            None,
        )
        mean = means.get(key)
        if v is None or not isinstance(mean, (int, float)) or not mean:
            continue
        rel = (float(v) - float(mean)) / abs(float(mean))
        if abs(rel) < _REL_TOL:
            out[key] = "about your average"
        else:
            hi, lo = labels[key]
            out[key] = hi if rel > 0 else lo
    return out


# ── the LLM call ────────────────────────────────────────────────────────────

_RESPONSE_SCHEMA = {
    "name": "say_it_stronger",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["already_strong", "upgrades", "rewrite_your_voice",
                     "rewrite_polished", "why"],
        "properties": {
            "already_strong": {"type": "boolean"},
            "upgrades": {"type": "array", "maxItems": _MAX_UPGRADES, "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["original", "upgrade", "reason", "kind", "scope"],
                "properties": {
                    "original": {"type": "string", "maxLength": 200},
                    "upgrade": {"type": "string", "maxLength": 200},
                    "reason": {"type": "string", "maxLength": 300},
                    "kind": {"type": "string",
                             "enum": ["upgrade", "filler", "overuse"]},
                    # word → the FE's "old word → new word" row;
                    # phrase → the "old phrase → new phrase" row
                    # (founder design 2026-07-14).
                    "scope": {"type": "string", "enum": ["word", "phrase"]},
                },
            }},
            "rewrite_your_voice": {"type": "string", "maxLength": _MAX_REWRITE_LEN},
            "rewrite_polished": {"type": "string", "maxLength": _MAX_REWRITE_LEN},
            "why": {"type": "string", "maxLength": _MAX_WHY_LEN},
        },
    },
    "strict": True,
}

# Founder's system prompt (2026-07-07), verbatim core + the two fence rules.
_SYSTEM_PROMPT = (
    "You are a communication coach helping software engineers improve how "
    "they sound in professional presentations. You never invent facts. You "
    "never add information that wasn't in the original sentence. You only "
    "restructure, strengthen, and remove verbal noise.\n\n"
    "Your job for each sentence you receive:\n\n"
    "1. Suggest up to 3 upgrades (only where the original is genuinely "
    "weak — do not force upgrades for their own sake). Each upgrade is "
    "either scope='word' (one word swapped for a stronger one) or "
    "scope='phrase' (a whole weak phrase replaced by a stronger "
    "alternative) — set the scope honestly by what you are replacing.\n\n"
    "2. Generate TWO full-sentence rewrites:\n"
    "- rewrite_your_voice (\"your voice\"): Preserve the speaker's natural "
    "tone. Only remove hedging, filler chains, and weak closers. Keep "
    "casual phrasing if it was casual. This should feel like the speaker "
    "on their best day, not a different person.\n"
    "- rewrite_polished (\"polished\"): Slightly more formal and "
    "structured. Suitable for a manager, customer, or leadership meeting. "
    "Never corporate jargon-heavy — avoid \"leverage\", \"synergy\", "
    "\"utilize\", \"endeavor\", \"in order to\", \"in the process of\".\n\n"
    "3. Write ONE short \"why this matters\" paragraph (2-3 sentences "
    "maximum). Focus on what the weak version communicates unintentionally "
    "(e.g., doubt, uncertainty, lack of authority). Never lecture. Never "
    "generic. When the speaker's voice data (given as plain observations) "
    "genuinely supports the advice, weave it in — e.g. a speaker whose "
    "pauses run shorter than their own average can be told they have room "
    "to just use silence and it won't feel awkward to the audience.\n\n"
    "FILLER & OVERUSE (you do this analysis yourself — judge from the full "
    "take transcript provided as context):\n"
    "- Spot FILLER words/phrases in the sentence (e.g. 'sort of', 'like', "
    "'you know', 'basically') — chains of them are noise; mark such an "
    "upgrade with kind='filler'.\n"
    "- Spot words the speaker OVERUSES across the whole take (used "
    "noticeably more than everything else) — when this sentence uses one, "
    "propose a synonym suited to the audience and mark kind='overuse'.\n"
    "- Every other word-level improvement is kind='upgrade'.\n"
    "- Fit suggestions to the CONTEXT you are given: who the audience is, "
    "and how long the talk is meant to be vs how long it ran (a talk over "
    "its target rewards tighter phrasing).\n\n"
    "Hard rules:\n"
    "- Never add facts, numbers, or claims not in the original sentence.\n"
    "- Never change the speaker's technical content or intent.\n"
    "- Never suggest jargon that would make an engineer roll their eyes.\n"
    "- If the original sentence is already strong, set already_strong=true, "
    "return an EMPTY upgrades array, and return the original sentence "
    "unchanged as BOTH rewrites — do not force changes.\n"
    "- Never include numeric values in the \"why\" or any \"reason\" text — "
    "express voice evidence qualitatively, and only relative to this "
    "speaker's own averages (you are given those comparisons; never invent "
    "others, never compare to other people).\n"
    "- Never use the words: charisma score, stress score, threat, ratio, "
    "classifier.\n"
    "- Write ALL output text in the SAME language the speaker used in the "
    "sentence. A Polish sentence gets Polish upgrades/rewrites/why.\n"
    "- Output must be valid JSON matching the provided schema."
)


_MAX_CONTEXT_TRANSCRIPT_CHARS = 6000


def _user_prompt(transcript: str, observations: dict,
                 context: Optional[dict] = None) -> str:
    obs = "; ".join(f"{k.replace('_', ' ')}: {v}"
                    for k, v in (observations or {}).items())
    ctx = context if isinstance(context, dict) else {}
    lines = [
        "Rewrite the following sentence a speaker said during a practice "
        "presentation.",
    ]
    if (ctx.get("topic") or "").strip():
        lines.append(f"The talk is about: \"{ctx['topic'].strip()}\".")
    if (ctx.get("audience") or "").strip():
        lines.append(f"The audience: {ctx['audience'].strip()}.")
    tgt = ctx.get("target_length_seconds")
    dur = ctx.get("duration_sec")
    if isinstance(tgt, (int, float)) and tgt and isinstance(dur, (int, float)) and dur:
        lines.append(
            f"Planned length: about {round(tgt / 60)} min; this take ran "
            f"about {max(1, round(dur / 60))} min."
        )
    elif isinstance(dur, (int, float)) and dur:
        lines.append(f"This take ran about {max(1, round(dur / 60))} min.")
    full = (ctx.get("full_transcript") or "").strip()
    if full:
        if len(full) > _MAX_CONTEXT_TRANSCRIPT_CHARS:
            full = full[:_MAX_CONTEXT_TRANSCRIPT_CHARS].rstrip() + "…"
        lines.append(
            "Full take transcript (context for judging filler chains and "
            f"overused words): \"{full}\""
        )
    lines.append(
        f"Their voice in this moment vs. their own average across the take: "
        f"{obs or '(no voice read available)'}."
    )
    lines.append(f"Sentence: \"{transcript}\"")
    lines.append("Return JSON per the schema.")
    return "\n".join(lines)


def _clean_payload(parsed: Any, transcript: str) -> Optional[dict]:
    """Validate + AC-9-guard the LLM output into the persisted shape.
    Returns None when the output is unusable. Pure."""
    if not isinstance(parsed, dict):
        return None
    rewrite_a = (parsed.get("rewrite_your_voice") or "").strip()
    rewrite_b = (parsed.get("rewrite_polished") or "").strip()
    if not rewrite_a or not rewrite_b:
        return None
    already = bool(parsed.get("already_strong"))
    upgrades_out: list = []
    if not already:
        for u in (parsed.get("upgrades") or [])[:_MAX_UPGRADES]:
            if not isinstance(u, dict):
                continue
            orig = (u.get("original") or "").strip()
            upg = (u.get("upgrade") or "").strip()
            if not orig or not upg:
                continue
            kind = u.get("kind")
            if kind not in ("upgrade", "filler", "overuse"):
                kind = "upgrade"
            # scope: word vs phrase row on the FE (founder 2026-07-14).
            # Deterministic fallback from the original text when the model
            # misses/mangles it — a space means it replaced a phrase.
            scope = u.get("scope")
            if scope not in ("word", "phrase"):
                scope = "phrase" if " " in orig else "word"
            upgrades_out.append({
                "original": orig[:200],
                "upgrade": upg[:200],
                # A reason that trips the guard is dropped, the pair kept.
                "reason": _guard_copy(u.get("reason")),
                "kind": kind,
                "scope": scope,
            })
    return {
        "already_strong": already,
        "upgrades": upgrades_out,
        "rewrite_your_voice": (transcript if already else rewrite_a)[:_MAX_REWRITE_LEN],
        "rewrite_polished": (transcript if already else rewrite_b)[:_MAX_REWRITE_LEN],
        "why": _guard_copy(parsed.get("why")),
        "version": _SUGGESTION_VERSION,
    }


def generate_say_it_stronger(
    transcript: str,
    metrics: Optional[dict],
    session_means: Optional[dict],
    context: Optional[dict] = None,
) -> Optional[dict]:
    """One LLM call → the persisted suggestion payload, or None on empty
    transcript / no LLM / failure. Metrics become plain-language
    self-comparisons HERE — the model never sees numbers."""
    transcript = (transcript or "").strip()
    if not transcript:
        return None
    observations = qualitative_self_comparison(metrics, session_means)
    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_SAY_IT_STRONGER
    except Exception as e:
        logger.warning("say_it_stronger: llm import failed: %s", e)
        return None
    try:
        result = chat_complete(
            spec=SPEC_SAY_IT_STRONGER,
            system=_SYSTEM_PROMPT,
            user=_user_prompt(transcript, observations, context),
            surface="say_it_stronger",
            response_format_override={
                "type": "json_schema", "json_schema": _RESPONSE_SCHEMA,
            },
        )
    except Exception as e:
        logger.warning("say_it_stronger: llm call failed: %s", e)
        return None
    parsed = result.parsed if result else None
    if parsed is None and result is not None:
        try:
            parsed = json.loads(result.text or "")
        except (ValueError, TypeError):
            parsed = None
    cleaned = _clean_payload(parsed, transcript)
    if cleaned is None:
        return None
    from services.llm_config import SPEC_SAY_IT_STRONGER as _spec
    cleaned["model"] = _spec.model
    cleaned["generated_at"] = datetime.now(timezone.utc).isoformat()
    return cleaned


# ── fire-and-forget dispatch (mirrors coach_comment_drafter) ───────────────

def dispatch_say_it_stronger(session_id: str, snippets: list,
                             context: Optional[dict] = None,
                             means: Optional[dict] = None) -> None:
    """Fire-and-forget: generate + persist a suggestion for each snippet.
    Never raises into the caller (process_lab_recording). No-op without
    snippets.

    ``means`` (pieces-canonical 2026-07-14): the "your average" reference. In
    pieces mode only the LLM-BUDGET subset is passed as ``snippets`` (cost
    cap), but the self-comparisons must be against the WHOLE take's average —
    so the caller passes the full-take means here. None → computed from
    ``snippets`` (legacy: snippets already IS the whole take)."""
    if not snippets:
        return
    try:
        threading.Thread(
            target=_generate_all,
            args=(session_id, snippets, context, means),
            daemon=True,
        ).start()
    except Exception as e:
        logger.warning(
            "say_it_stronger: dispatch failed sid=%s: %s", session_id, e)


def _generate_all(session_id, snippets, context=None, means=None) -> None:
    from services.db import db
    if not isinstance(means, dict):
        means = aggregate_session_means(snippets)
    written = 0
    for snip in (snippets or []):
        try:
            sid = snip.get("id")
            transcript = (snip.get("transcript") or "").strip()
            if not sid or not transcript:
                continue
            payload = generate_say_it_stronger(
                transcript,
                snip.get("metrics") if isinstance(snip.get("metrics"), dict) else None,
                means,
                context,
            )
            if payload and db.set_charisma_snippet_say_it_stronger(sid, payload):
                written += 1
        except Exception as e:
            logger.warning(
                "say_it_stronger: generate failed sid=%s snip=%s: %s",
                session_id, snip.get("id"), e,
            )
    logger.info(
        "say_it_stronger: wrote %d/%d for session %s",
        written, len(snippets or []), session_id,
    )
