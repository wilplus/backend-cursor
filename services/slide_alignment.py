"""willab beta — slide↔delivery alignment + claim-ledger (UX Wave 4 Phase 2).

Two layers:

BE-S4 — snippet→slide mapping. The slide for a snippet at time T = the
slide_advances entry with the greatest t_ms ≤ T (slide 0 from t=0; ties → the
later tap, so back-navigation is honored). Text-overlap fallback only when
there's no usable timeline.

Stickiness #2 — claim-ledger (entailment, not keywords, not open grading):
  step 1  decompose each slide → atomic claims (SPEC_SLIDE_CLAIMS, cached by
          slide-text hash).
  step 2  per snippet, entail its MAPPED slide's claims (SPEC_SLIDE_ENTAILMENT)
          → covered | partial | not.
  step 3  two scores:
            (ii) on-slide-ness, per snippet → drives overall/rank. How strongly
                 this moment made ≥1 of its slide's points (max verdict
                 strength). NOT divided by total slide claims.
            (i)  coverage ledger, per slide → coach audit. Roll the verdicts up
                 across all the slide's snippets: "delivered N of M points."

Best-effort everywhere: an LLM failure falls back to a lexical verdict (+
degraded flag) and never raises — process_lab_recording must not hard-fail on
this. Pure helpers (scoring, rollup, abstain, lexical) are unit-tested.
"""
from __future__ import annotations

import hashlib
import logging
import re

logger = logging.getLogger(__name__)

_WORD = re.compile(r"[a-z0-9']+")

# Abstain thresholds (Stickiness #2).
_MIN_WORDS_FLOOR = 4        # under this → null (too little to judge), not 0
_SILENCE_WINDOW_MS = 3000   # no speech for at least this long on a live slide → 0
_ON_SLIDE_THRESHOLD = 0.5   # composite ≥ this → on_slide=True (partial or better)

_VERDICTS = ("covered", "partial", "not")
_STRENGTH = {"covered": 1.0, "partial": 0.5, "not": 0.0}


def slide_index_for_offset(start_offset_ms, slide_advances):
    """The on-screen slide index at start_offset_ms, or None when there's no
    usable timeline. Greatest t_ms ≤ offset wins; ties → the later tap."""
    if not slide_advances:
        return None
    t0 = start_offset_ms if isinstance(start_offset_ms, int) else 0
    chosen = None
    best_t = None
    for a in slide_advances:
        if not isinstance(a, dict):
            continue
        t = a.get("t_ms")
        idx = a.get("index")
        if not isinstance(t, int) or not isinstance(idx, int):
            continue
        if t <= t0 and (best_t is None or t >= best_t):
            best_t = t
            chosen = idx
    return chosen


def _tokens(text):
    return set(_WORD.findall((text or "").lower()))


def _best_match_index(transcript, slides):
    """Fallback: the slide whose title+body overlaps the transcript most."""
    toks = _tokens(transcript)
    if not toks or not slides:
        return None
    best_i, best_score = None, 0
    for i, s in enumerate(slides):
        if not isinstance(s, dict):
            continue
        overlap = len(toks & _tokens(f"{s.get('title', '')} {s.get('body', '')}"))
        if overlap > best_score:
            best_score = overlap
            best_i = i
    return best_i


def slide_for_snippet(snippet, slide_advances, slides):
    """Return {index, title, body} for the slide on screen during this snippet,
    or None. Timeline-first (exact); text-overlap fallback only when there's no
    usable timeline."""
    if not slides:
        return None
    idx = slide_index_for_offset(snippet.get("start_offset_ms"), slide_advances)
    if idx is None:
        idx = _best_match_index(snippet.get("transcript"), slides)
    if not isinstance(idx, int) or idx < 0 or idx >= len(slides):
        return None
    s = slides[idx]
    if not isinstance(s, dict):
        return None
    return {"index": idx, "title": s.get("title") or "", "body": s.get("body") or ""}


# ── Claim-ledger — Stickiness #2 ──────────────────────────────────────────

def _slide_text(slide):
    if not isinstance(slide, dict):
        return ""
    return f"{slide.get('title') or ''}\n{slide.get('body') or ''}".strip()


def _hash_slide(slide):
    return hashlib.sha1(_slide_text(slide).encode("utf-8")).hexdigest()


# Content-hash cache so re-cuts / repeated decks skip re-decomposition.
_claims_cache: dict = {}


def _lexical_verdict(transcript, claim):
    """Deterministic fallback when the LLM entailment is unavailable. Token
    overlap of the claim's content words against the transcript: most words
    present → covered, some → partial, ~none → not. Coarser than entailment
    (misses paraphrase) but never wrong-confidently and never raises."""
    ct = _tokens(transcript)
    cw = _tokens(claim)
    cw = {w for w in cw if len(w) > 2}  # drop tiny stopword-ish tokens
    if not cw:
        return "not"
    hit = len(cw & ct) / len(cw)
    if hit >= 0.6:
        return "covered"
    if hit >= 0.25:
        return "partial"
    return "not"


def on_slide_score(verdicts):
    """(ii) per-snippet on-slide-ness: how strongly this moment made ≥1 of its
    slide's points = the strongest single verdict. NOT averaged over all the
    slide's claims (a single 8s snippet shouldn't be punished for not covering
    the whole slide). Pure."""
    if not verdicts:
        return 0.0
    return max(_STRENGTH.get(v, 0.0) for v in verdicts)


def abstain_reason(transcript, duration_ms, slide, claims):
    """Pure: 'null' (unscorable → abstain), 'zero' (genuine silence on a live
    slide), or None (score it). Order matters."""
    if not isinstance(slide, dict) or not _slide_text(slide):
        return "null"            # no slide / image-only / empty slide
    if not claims:
        return "null"            # couldn't decompose → unscorable
    words = len((transcript or "").split())
    if words == 0:
        # said nothing while a live slide was up long enough → a real 0
        return "zero" if (duration_ms or 0) >= _SILENCE_WINDOW_MS else "null"
    if words < _MIN_WORDS_FLOOR:
        return "null"            # too little speech to judge
    return None


def roll_up_coverage(slide_index, claims, per_snippet_verdicts):
    """(i) per-slide coverage ledger. For each claim, the best verdict ANY of
    the slide's snippets achieved (covered if any covered; else partial if any
    partial; else not), with the snippet_ref that achieved it. Pure.

    per_snippet_verdicts: list of (snippet_ref, [verdict per claim]).
    """
    ledger = []
    covered = partial = 0
    for ci, claim in enumerate(claims):
        best_v, best_ref = "not", None
        for ref, verdicts in per_snippet_verdicts:
            v = verdicts[ci] if ci < len(verdicts) else "not"
            if _STRENGTH.get(v, 0.0) > _STRENGTH.get(best_v, 0.0):
                best_v, best_ref = v, ref
        if best_v == "covered":
            covered += 1
        elif best_v == "partial":
            partial += 1
        ledger.append({"claim": claim, "verdict": best_v, "snippet_ref": best_ref})
    return {
        "slide_index": slide_index, "covered": covered, "partial": partial,
        "total": len(claims), "ledger": ledger,
    }


def decompose_slides_to_claims(slides_by_index):
    """LLM: {slide_index: [claims]} for the given {slide_index: slide} subset.
    Hash-cached per slide text. Best-effort → returns whatever it could get
    (missing index = decomposition unavailable for that slide)."""
    out: dict = {}
    need = {}
    for idx, slide in slides_by_index.items():
        h = _hash_slide(slide)
        if not _slide_text(slide):
            continue
        if h in _claims_cache:
            out[idx] = _claims_cache[h]
        else:
            need[idx] = (h, slide)
    if need:
        fresh = _llm_decompose({i: s for i, (h, s) in need.items()})
        if fresh:
            for i, (h, s) in need.items():
                claims = fresh.get(i)
                if claims is not None:
                    _claims_cache[h] = claims
                    out[i] = claims
    return out


def _llm_decompose(slides_by_index):
    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_SLIDE_CLAIMS
    except Exception as e:
        logger.warning("slide_claims: llm import failed: %s", e)
        return None
    items = [
        {"index": i, "title": s.get("title") or "", "body": s.get("body") or ""}
        for i, s in slides_by_index.items()
    ]
    system = (
        "You decompose presentation slides into atomic, checkable CLAIMS — the "
        "discrete points a speaker would need to make to deliver each slide. "
        "Each claim is one short standalone statement (no slide jargon). This "
        "is extraction, not judgment. 1-5 claims per slide; fewer for sparse "
        "slides. Return strict JSON: {\"slides\":[{\"index\":<int>,\"claims\":"
        "[\"...\"]}]} with one entry per input slide, same indexes."
    )
    import json as _json
    schema = {
        "name": "slide_claims",
        "schema": {
            "type": "object", "additionalProperties": False,
            "required": ["slides"],
            "properties": {"slides": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["index", "claims"],
                "properties": {
                    "index": {"type": "integer"},
                    "claims": {"type": "array", "items": {"type": "string", "maxLength": 200}},
                },
            }}},
        },
        "strict": True,
    }
    try:
        result = chat_complete(
            spec=SPEC_SLIDE_CLAIMS, system=system,
            user=_json.dumps({"slides": items}), surface="slide_claims",
            response_format_override={"type": "json_schema", "json_schema": schema},
        )
        data = result.parsed if result else None
        if not isinstance(data, dict):
            return None
        return {
            int(e["index"]): [str(c) for c in (e.get("claims") or []) if str(c).strip()]
            for e in data.get("slides", []) if isinstance(e, dict) and "index" in e
        }
    except Exception as e:
        logger.warning("slide_claims: decompose failed: %s", e)
        return None


def _entail_batch(work):
    """LLM entailment for work = [{ref, transcript, claims:[...]}]. Returns
    {ref: [verdict per claim]} or None on failure (caller falls back lexically)."""
    if not work:
        return {}
    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_SLIDE_ENTAILMENT
    except Exception as e:
        logger.warning("slide_entail: llm import failed: %s", e)
        return None
    import json as _json
    payload = [
        {"ref": str(w["ref"]), "transcript": (w["transcript"] or "")[:1500],
         "claims": w["claims"]}
        for w in work
    ]
    system = (
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
    schema = {
        "name": "slide_entailment",
        "schema": {
            "type": "object", "additionalProperties": False,
            "required": ["snippets"],
            "properties": {"snippets": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["ref", "verdicts"],
                "properties": {
                    "ref": {"type": "string"},
                    "verdicts": {"type": "array", "items": {
                        "type": "string", "enum": list(_VERDICTS)}},
                },
            }}},
        },
        "strict": True,
    }
    try:
        result = chat_complete(
            spec=SPEC_SLIDE_ENTAILMENT, system=system,
            user=_json.dumps({"snippets": payload}), surface="slide_entailment",
            response_format_override={"type": "json_schema", "json_schema": schema},
        )
        data = result.parsed if result else None
        if not isinstance(data, dict):
            return None
        return {
            str(e["ref"]): [v if v in _VERDICTS else "not" for v in (e.get("verdicts") or [])]
            for e in data.get("snippets", []) if isinstance(e, dict) and "ref" in e
        }
    except Exception as e:
        logger.warning("slide_entail: entailment failed: %s", e)
        return None


def compute_slide_scores(snippets, slides, slide_advances):
    """Orchestrate the claim-ledger. Returns
      {"per_snippet": [{composite|null, on_slide, degraded}],  # aligned to snippets
       "slide_coverage": [{slide_index, covered, partial, total, ledger}]}.
    Best-effort: never raises; degrades to lexical verdicts (+degraded flag) on
    LLM failure, abstains to null where unscorable."""
    n = len(snippets or [])
    blank = [{"composite": None, "on_slide": False, "degraded": False} for _ in range(n)]
    if not slides or not snippets:
        return {"per_snippet": blank, "slide_coverage": []}

    # 1. map each snippet → slide index
    mapped = {}
    for i, snip in enumerate(snippets):
        idx = slide_index_for_offset(snip.get("start_offset_ms"), slide_advances)
        if isinstance(idx, int) and 0 <= idx < len(slides) and _slide_text(slides[idx]):
            mapped[i] = idx

    # 2. decompose the slides that actually have snippets on them
    used_slides = {idx: slides[idx] for idx in set(mapped.values())}
    claims_by_idx = decompose_slides_to_claims(used_slides) if used_slides else {}

    # 3. build entailment work (snippets that pass the word floor + have claims)
    work = []
    for i, idx in mapped.items():
        claims = claims_by_idx.get(idx) or []
        if not claims:
            continue
        if abstain_reason(snippets[i].get("transcript"), snippets[i].get("duration_ms"),
                          slides[idx], claims) is not None:
            continue
        work.append({"ref": i, "transcript": snippets[i].get("transcript") or "",
                     "claims": claims})

    verdicts_by_ref = _entail_batch(work)
    degraded = verdicts_by_ref is None
    if degraded:  # LLM down → lexical fallback per (snippet, claim)
        verdicts_by_ref = {
            str(w["ref"]): [_lexical_verdict(w["transcript"], c) for c in w["claims"]]
            for w in work
        }

    # 4. per-snippet (ii) + accumulate per-slide verdicts for the ledger
    per_snippet = list(blank)
    slide_verdicts: dict = {}  # slide_idx → list of (snippet_ref, [verdicts])
    for i, idx in mapped.items():
        claims = claims_by_idx.get(idx) or []
        reason = abstain_reason(snippets[i].get("transcript"),
                                snippets[i].get("duration_ms"), slides[idx], claims)
        if reason == "zero":
            per_snippet[i] = {"composite": 0.0, "on_slide": False, "degraded": False}
            continue
        if reason == "null":
            continue  # leave as null
        verdicts = (verdicts_by_ref or {}).get(str(i)) or []
        score = on_slide_score(verdicts)
        per_snippet[i] = {
            "composite": round(score, 2),
            "on_slide": score >= _ON_SLIDE_THRESHOLD,
            "degraded": degraded,
        }
        slide_verdicts.setdefault(idx, []).append(
            (snippets[i].get("id") or i, verdicts))

    # 5. per-slide coverage ledger (i)
    coverage = []
    for idx in sorted(used_slides):
        claims = claims_by_idx.get(idx) or []
        if not claims:
            continue
        coverage.append(roll_up_coverage(idx, claims, slide_verdicts.get(idx, [])))

    return {"per_snippet": per_snippet, "slide_coverage": coverage}
