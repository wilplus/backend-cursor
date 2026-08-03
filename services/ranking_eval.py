"""F1 — ranking eval set: is the best-per-slide pick actually the best? (2026-08-03)

``power_score`` decides, for every slide, which of the speaker's lines
represents it — the second load-bearing F1 piece. Its six weights are
hand-set and have never been compared to a human judgment. This module is
the measurement: it draws a BLIND labeling sheet (which line best represents
this slide?), keeps the machine's answer in a closed key, and computes
agreement once the labels come back.

THE UNIT IS A CASE, NOT A TAKE. A case = one (session, slide) with ≥2
candidate lines. That is exactly the decision ``select_best_per_slide``
makes, and it fires on single-take sessions today (the candidate pool is
flat; take_index is metadata the score never sees) — so no multi-take arcs
are required. If arcs return, the same cases and the same harness apply
unchanged.

DRIFT-PROOFING. The machine's picks are computed by calling the REAL
``select_best_per_slide`` and the REAL ``power_score`` — never a re-
implementation (same pattern as the master-doc probe reusing the production
``_CONSTRUCT_RE``). The one thing mirrored rather than imported is the
snippet→candidate field mapping from ``build_best_presentation`` (it is
inline in a DB+LLM orchestration and cannot be called read-only); each field
below cites its production line so a change there is findable here.

WHAT AGREEMENT CAN AND CANNOT SAY. Agreement with one rater on N cases is
evidence, not proof: it can DEMOTE a rule that clearly fights human judgment
(the complete-sentence hard gate), CATCH a structural bias (slide coverage
entering the score twice via ``overall_score``), and give a before/after for
flipping VOICE_CONFIDENCE_RANKING_ENABLED. It cannot certify the ranker
"good" — 30 labeled cases are a regression net and a tiebreak for known
suspects, nothing more. The named variants scored alongside the shipped
blend:

  shipped_local     — select_best_per_slide on the case's own candidates
                      (the pure per-slide decision).
  shipped_assembly  — the pick after the cross-slide dedupe (an earlier
                      slide can steal a later slide's best line); the gap
                      between this and shipped_local is the measured cost
                      of that path dependence.
  no_sentence_gate  — argmax power_score, ignoring the complete-sentence
                      primary sort key. Tests whether the hard gate helps
                      or hurts.
  debiased_coverage — activation with the slide-coverage half removed
                      (overall_score = 0.5·topic + 0.5·slide, so topic is
                      recoverable as 2·overall − slide). Tests the ~2:1
                      slide-vs-topic double-count.

BLIND (same discipline as confidence_labels / export_confidence_validation):
the sheet carries the moment and nothing else — no score, no band, no
take_index, no direction, no machine read of any kind. Bands select cases
and are then kept key-side only. Rows are letter-shuffled per case so
speech order isn't presentation order.

AC-9: internal, coach-side. No output of this module ever rides a user
payload — no score, no verdict, no agreement rate. Pure and DB-free: the
scripts (scripts/export_ranking_eval.py, scripts/score_ranking_eval.py) own
all I/O.
"""
from __future__ import annotations

import logging
import random
import string
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Case-selection strata. gate_decided = the complete-sentence sort key, not
# the score, chose the winner; close = score gap under CLOSE_GAP; clear =
# everything else. Near-ties and gate-decided cases are where the ranker is
# actually deciding anything — a uniform draw would be mostly `clear` and
# flatter the blend.
BANDS = ("gate_decided", "close", "clear")
DEFAULT_PER_BAND = 10
DEFAULT_CLOSE_GAP = 0.10

# A 12-candidate "pick the best" is not a judgment a rater can hold; cases
# past this are excluded AND COUNTED (no silent caps — the count prints).
DEFAULT_MAX_CANDIDATES = 8

_LETTERS = string.ascii_uppercase

# The blind sheet is built by ALLOWLIST — a field not named here cannot
# leak, whatever gets added to candidates later.
BLIND_COLUMNS = (
    "case_id", "slide_no", "slide_title", "slide_body", "candidate",
    "transcript", "audio_ref", "start_offset_ms", "duration_ms",
    "is_best", "why",
)

KEY_COLUMNS = (
    "case_id", "candidate", "session_id", "snippet_id", "slide_index",
    "take_index", "band", "score", "complete", "shipped_local_pick",
    "shipped_assembly_pick", "activation", "slide_stickiness",
    "topic_stickiness", "tag", "direction", "coach_direction",
    "breakthrough", "voice_confidence", "transcript_source",
    "start_offset_ms",
)


# ─────────────────────────────────────────────────────────────────
# Candidate construction (mirrors build_best_presentation 626-694)
# ─────────────────────────────────────────────────────────────────

def build_session_candidates(
    session: Any, snippets: Any, coach_labels: Any = None,
    corrections: Any = None,
) -> list:
    """One session's snippets → ranking candidates carrying EXACTLY the
    fields build_best_presentation feeds power_score, plus key-side context
    (topic_stickiness, coach_direction, transcript_source). Field-by-field
    provenance is services/best_presentation.py:626-694; direction
    resolution and the breakthrough gate are the production functions
    themselves. Pure; [] on unusable input."""
    from services.best_presentation import (
        _resolve_take_directions, _voice_confidence_term,
    )
    from services.challenge_threat import detect_breakthroughs
    from services.slide_alignment import slide_index_for_offset

    s = session if isinstance(session, dict) else {}
    ctx = s.get("intake_context") if isinstance(s.get("intake_context"), dict) else {}
    advances = ctx.get("slide_advances")
    labels = coach_labels if isinstance(coach_labels, dict) else {}
    corr = corrections if isinstance(corrections, dict) else {}

    directed = _resolve_take_directions(
        [x for x in (snippets or []) if isinstance(x, dict)], labels,
    )
    # Breakthrough gate on coach_direction only (best_presentation.py:645-651
    # — the badge never rides a model guess).
    breakthroughs = detect_breakthroughs([
        {"id": x.get("id"), "start_offset_ms": x.get("start_offset_ms"),
         "direction": x.get("coach_direction")}
        for x in directed
    ])

    out = []
    for snip in directed:
        metrics = snip.get("metrics") if isinstance(snip.get("metrics"), dict) else {}
        stick = metrics.get("slide_stickiness")
        if isinstance(stick, dict):
            stick = stick.get("composite")
        topic = metrics.get("stickiness")
        if isinstance(topic, dict):
            topic = topic.get("composite")
        corrected = corr.get(str(snip.get("id")))
        transcript = (
            corrected if isinstance(corrected, str) and corrected.strip()
            else (snip.get("transcript") or snip.get("transcript_excerpt") or "")
        )
        out.append({
            "slide_index": slide_index_for_offset(
                snip.get("start_offset_ms"), advances),
            "snippet_id": snip.get("id"),
            "session_id": s.get("id"),
            "transcript": transcript,
            "transcript_source": (
                "corrected" if isinstance(corrected, str) and corrected.strip()
                else "raw"
            ),
            "audio_ref": snip.get("audio_ref") or snip.get("storage_path"),
            "start_offset_ms": snip.get("start_offset_ms"),
            "duration_ms": snip.get("duration_ms"),
            "take_index": s.get("take_index"),
            "direction": snip.get("direction"),
            "coach_direction": snip.get("coach_direction"),
            "breakthrough": snip.get("id") in breakthroughs,
            "activation": metrics.get("overall_score"),
            "slide_stickiness": stick,
            "topic_stickiness": topic,
            "voice_confidence": _voice_confidence_term(metrics),
            "tag": None,  # best_presentation.py:690 — labels live in drafts
        })
    return out


# ─────────────────────────────────────────────────────────────────
# Cases (the labeling unit) + machine picks + bands
# ─────────────────────────────────────────────────────────────────

def _score_kwargs(c: dict) -> dict:
    """The power_score kwargs for one candidate — the SAME call
    select_best_per_slide makes (best_presentation.py:100-107)."""
    return {
        "activation": c.get("activation"),
        "slide_stickiness": c.get("slide_stickiness"),
        "tag": c.get("tag"),
        "direction": c.get("direction"),
        "breakthrough": bool(c.get("breakthrough")),
        "voice_confidence": c.get("voice_confidence"),
    }


def _annotate(c: dict) -> dict:
    """Attach the production score + complete-sentence flag (key-side)."""
    from services.best_presentation import _is_complete_sentence
    from services.power_phrase_ranking import power_score
    return {
        **c,
        "score": power_score(**_score_kwargs(c)),
        "complete": _is_complete_sentence(c.get("transcript")),
    }


def build_cases(
    candidates: Any, *, max_candidates: int = DEFAULT_MAX_CANDIDATES,
) -> tuple[list, dict]:
    """Group candidates into cases — one per (session, slide_index) with 2+
    non-empty-transcript candidates. Returns (cases, stats); every exclusion
    is counted, none is silent:

      deckless_skipped   — slide_index None (no slide timeline). Deckless
                           ranking (select_best_deckless) is a different
                           label task (choose K of N) and is v1 OUT OF SCOPE.
      singleton_skipped  — 1 candidate: there is no decision to evaluate.
      oversize_skipped   — > max_candidates: not a holdable judgment.
    """
    by_key: dict = {}
    stats = {"deckless_skipped": 0, "singleton_skipped": 0,
             "oversize_skipped": 0, "empty_transcript_skipped": 0}
    for c in candidates if isinstance(candidates, list) else []:
        if not isinstance(c, dict):
            continue
        if not (c.get("transcript") or "").strip():
            stats["empty_transcript_skipped"] += 1
            continue
        si = c.get("slide_index")
        if not isinstance(si, int) or si < 0:
            stats["deckless_skipped"] += 1
            continue
        by_key.setdefault((str(c.get("session_id")), si), []).append(c)

    cases = []
    seen_ids: set = set()
    for (sid, si), cands in sorted(by_key.items()):
        if len(cands) < 2:
            stats["singleton_skipped"] += 1
            continue
        if len(cands) > max_candidates:
            stats["oversize_skipped"] += 1
            continue
        case_id = f"{sid[:8]}-s{si:02d}"
        while case_id in seen_ids:  # 8-char prefix collision — disambiguate
            case_id += "x"
        seen_ids.add(case_id)
        cases.append({
            "case_id": case_id,
            "session_id": sid,
            "slide_index": si,
            "candidates": [_annotate(c) for c in cands],
        })
    return cases, stats


def attach_machine_picks(cases: list, session_candidates: dict) -> None:
    """Mark each candidate with the two shipped answers, in place.

    shipped_local    — the REAL select_best_per_slide over the case's own
                       candidates (the per-slide decision, dedupe-free).
    shipped_assembly — the REAL select_best_per_slide over the candidate's
                       whole session (``session_candidates[session_id]``),
                       i.e. what assembly actually picks after the
                       cross-slide dedupe.
    """
    from services.best_presentation import select_best_per_slide

    assembly_by_sid: dict = {}
    for sid, cands in (session_candidates or {}).items():
        picks = select_best_per_slide(cands)
        assembly_by_sid[str(sid)] = {
            si: p.get("snippet_id") for si, p in picks.items()
        }

    for case in cases:
        local = select_best_per_slide(case["candidates"])
        local_id = (local.get(case["slide_index"]) or {}).get("snippet_id")
        asm_id = assembly_by_sid.get(
            case["session_id"], {}).get(case["slide_index"])
        for c in case["candidates"]:
            c["shipped_local_pick"] = c.get("snippet_id") == local_id
            c["shipped_assembly_pick"] = (
                asm_id is not None and c.get("snippet_id") == asm_id
            )


def band_for_case(case: dict, *, close_gap: float = DEFAULT_CLOSE_GAP) -> str:
    """Which stratum this decision sits in. Production order is
    (complete, score) desc; when the pure score argmax differs from the
    production winner, the sentence GATE decided → ``gate_decided``. Else
    banded by the top-two score gap in production order."""
    ranked = sorted(
        case["candidates"],
        key=lambda c: (bool(c.get("complete")), c.get("score", 0.0)),
        reverse=True,
    )
    by_score = max(case["candidates"], key=lambda c: c.get("score", 0.0))
    if by_score.get("snippet_id") != ranked[0].get("snippet_id"):
        return "gate_decided"
    gap = ranked[0].get("score", 0.0) - ranked[1].get("score", 0.0)
    return "close" if gap < close_gap else "clear"


def attach_bands(cases: list, *, close_gap: float = DEFAULT_CLOSE_GAP) -> None:
    for case in cases:
        case["band"] = band_for_case(case, close_gap=close_gap)


# ─────────────────────────────────────────────────────────────────
# Sampling + the two files
# ─────────────────────────────────────────────────────────────────

def draw_sample(
    cases: list, *, per_band: int = DEFAULT_PER_BAND,
    seed: Optional[int] = None,
) -> list:
    """Stratified draw across BANDS (mirrors export_confidence_validation's
    _stratify): random within band, round-robin across bands so a short band
    redistributes its shortfall instead of being topped up with extremes.
    Bands stay key-side — the sheet never carries them."""
    rng = random.Random(seed)
    by_band: dict = {b: [] for b in BANDS}
    for c in cases:
        by_band.setdefault(c.get("band") or "clear", []).append(c)
    for bucket in by_band.values():
        rng.shuffle(bucket)
    n = per_band * len(BANDS)
    picked: list = []
    while len(picked) < n and any(by_band[b] for b in by_band):
        for b in sorted(by_band):
            if len(picked) >= n:
                break
            if by_band[b]:
                picked.append(by_band[b].pop())
    rng.shuffle(picked)
    for case in picked:
        _assign_letters(case, rng)
    return picked


def _assign_letters(case: dict, rng: random.Random) -> None:
    """Shuffle candidate order and letter them — presentation order must not
    be speech order (position bias) and must not be rank order (leak)."""
    cands = list(case["candidates"])
    rng.shuffle(cands)
    for letter, c in zip(_LETTERS, cands):
        c["candidate"] = letter
    case["candidates"] = cands


def blind_rows(cases: list, slides_by_session: Any = None) -> list:
    """The rater's sheet — allowlist construction, one row per candidate.
    ``slides_by_session[session_id]`` = the deck (list of {title, body}) for
    slide context; absent → blank context, never a crash."""
    decks = slides_by_session if isinstance(slides_by_session, dict) else {}
    rows = []
    for case in cases:
        deck = decks.get(case["session_id"]) or []
        si = case["slide_index"]
        slide = deck[si] if isinstance(deck, list) and si < len(deck) else {}
        slide = slide if isinstance(slide, dict) else {}
        for c in case["candidates"]:
            rows.append({
                "case_id": case["case_id"],
                "slide_no": si + 1,
                "slide_title": (slide.get("title") or "")[:120],
                "slide_body": (slide.get("body") or "")[:200],
                "candidate": c.get("candidate"),
                "transcript": c.get("transcript") or "",
                "audio_ref": c.get("audio_ref") or "",
                "start_offset_ms": c.get("start_offset_ms"),
                "duration_ms": c.get("duration_ms"),
                "is_best": "",
                "why": "",
            })
    # The fence, enforced at build time: exactly the allowlist, nothing else.
    for r in rows:
        assert set(r) == set(BLIND_COLUMNS), "blind sheet fence violated"
    return rows


def key_rows(cases: list) -> list:
    """The closed key — everything the report needs to score every variant
    without re-touching the DB."""
    rows = []
    for case in cases:
        for c in case["candidates"]:
            rows.append({
                "case_id": case["case_id"],
                "candidate": c.get("candidate"),
                "session_id": case["session_id"],
                "snippet_id": c.get("snippet_id"),
                "slide_index": case["slide_index"],
                "take_index": c.get("take_index"),
                "band": case.get("band"),
                "score": c.get("score"),
                "complete": c.get("complete"),
                "shipped_local_pick": c.get("shipped_local_pick"),
                "shipped_assembly_pick": c.get("shipped_assembly_pick"),
                "activation": c.get("activation"),
                "slide_stickiness": c.get("slide_stickiness"),
                "topic_stickiness": c.get("topic_stickiness"),
                "tag": c.get("tag"),
                "direction": c.get("direction"),
                "coach_direction": c.get("coach_direction"),
                "breakthrough": c.get("breakthrough"),
                "voice_confidence": c.get("voice_confidence"),
                "transcript_source": c.get("transcript_source"),
                "start_offset_ms": c.get("start_offset_ms"),
            })
    return rows


# ─────────────────────────────────────────────────────────────────
# Scoring (after the sheet comes back)
# ─────────────────────────────────────────────────────────────────

_TRUTHY = {"1", "x", "yes", "true", "y"}


def parse_labels(sheet_rows: Any) -> tuple[dict, list]:
    """{case_id: winning letter} from the returned sheet + a problem list.
    A case with zero or 2+ marks is invalid — reported, excluded, counted;
    forced choice is the contract (a relative read is still a read)."""
    marks: dict = {}
    for r in sheet_rows or []:
        if not isinstance(r, dict):
            continue
        cid = (r.get("case_id") or "").strip()
        if not cid:
            continue
        marks.setdefault(cid, [])
        if (str(r.get("is_best") or "").strip().lower()) in _TRUTHY:
            marks[cid].append((r.get("candidate") or "").strip().upper())
    labels: dict = {}
    problems: list = []
    for cid, picked in sorted(marks.items()):
        if len(picked) == 1:
            labels[cid] = picked[0]
        else:
            problems.append(
                f"{cid}: {len(picked)} candidates marked (need exactly 1)"
            )
    return labels, problems


def _parse_opt_float(v: Any) -> Optional[float]:
    if v is None or (isinstance(v, str) and not v.strip()):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_bool(v: Any) -> bool:
    return str(v).strip().lower() in ("true", "1")


def parse_key_rows(raw_rows: Any) -> list:
    """CSV strings back into typed key rows (the csv module reads everything
    as str; the report needs numbers/bools/Nones)."""
    out = []
    for r in raw_rows or []:
        if not isinstance(r, dict):
            continue
        row = dict(r)
        for k in ("score", "activation", "slide_stickiness",
                  "topic_stickiness", "voice_confidence"):
            row[k] = _parse_opt_float(r.get(k))
        for k in ("complete", "shipped_local_pick", "shipped_assembly_pick",
                  "breakthrough"):
            row[k] = _parse_bool(r.get(k))
        for k in ("tag", "direction", "coach_direction"):
            row[k] = (r.get(k) or "").strip() or None
        row["candidate"] = (r.get("candidate") or "").strip().upper()
        out.append(row)
    return out


def _debiased_activation(row: dict) -> Optional[float]:
    """activation with the slide-coverage half removed.

    lab_recording.py:759 — overall = 0.5·topic + 0.5·slide (slide null →
    overall = topic). So: topic = 2·overall − slide when slide is present,
    else overall; None stays None (the deliberate non-budget-piece
    neutrality is preserved — a piece the blend treats as neutral stays
    neutral under the variant too)."""
    ov = row.get("activation")
    if ov is None:
        return None
    ss = row.get("slide_stickiness")
    if ss is None:
        return ov
    return max(0.0, min(1.0, 2.0 * ov - ss))


def _variant_pick(rows: list, variant: str) -> Optional[str]:
    """The winning letter for one case under one variant; None = variant
    can't be computed for this case (counted by the report, never silent)."""
    from services.power_phrase_ranking import power_score

    if variant == "shipped_local":
        hits = [r for r in rows if r.get("shipped_local_pick")]
        return hits[0]["candidate"] if hits else None
    if variant == "shipped_assembly":
        hits = [r for r in rows if r.get("shipped_assembly_pick")]
        return hits[0]["candidate"] if hits else None
    if variant == "no_sentence_gate":
        best = max(rows, key=lambda r: (
            r.get("score") if r.get("score") is not None
            else power_score(**_score_kwargs(r)),
            bool(r.get("complete")),
        ))
        return best["candidate"]
    if variant == "debiased_coverage":
        scored = []
        for r in rows:
            kw = _score_kwargs(r)
            kw["activation"] = _debiased_activation(r)
            scored.append((power_score(**kw), bool(r.get("complete")), r))
        # Same shape as production order: complete first, then the score.
        scored.sort(key=lambda t: (t[1], t[0]), reverse=True)
        return scored[0][2]["candidate"]
    return None


VARIANTS = ("shipped_local", "shipped_assembly", "no_sentence_gate",
            "debiased_coverage")


def agreement_report(labels: dict, key: list) -> dict:
    """Human labels × closed key → per-variant agreement, overall and by
    band, plus the disagreement list (the case ids worth listening to again
    — that qualitative pass is the actual product insight; the rates only
    say where to look)."""
    by_case: dict = {}
    for r in key or []:
        by_case.setdefault(r.get("case_id"), []).append(r)

    report: dict = {
        "cases_labeled": 0,
        "cases_unmatched": 0,   # labeled but absent from the key
        "variants": {},
        "disagreements": [],
    }
    tallies = {
        v: {"overall": [0, 0],
            "by_band": {b: [0, 0] for b in BANDS},
            "uncomputable": 0}
        for v in VARIANTS
    }

    for cid, human in sorted((labels or {}).items()):
        rows = by_case.get(cid)
        if not rows:
            report["cases_unmatched"] += 1
            continue
        report["cases_labeled"] += 1
        band = rows[0].get("band") or "clear"
        for v in VARIANTS:
            pick = _variant_pick(rows, v)
            if pick is None:
                tallies[v]["uncomputable"] += 1
                continue
            agree = pick == human
            tallies[v]["overall"][1] += 1
            tallies[v]["overall"][0] += 1 if agree else 0
            bb = tallies[v]["by_band"].setdefault(band, [0, 0])
            bb[1] += 1
            bb[0] += 1 if agree else 0
            if v == "shipped_local" and not agree:
                report["disagreements"].append({
                    "case_id": cid, "band": band,
                    "human": human, "shipped": pick,
                })

    def _rate(pair: list) -> dict:
        a, n = pair
        return {"agree": a, "n": n,
                "rate": round(a / n, 3) if n else None}

    for v in VARIANTS:
        report["variants"][v] = {
            "overall": _rate(tallies[v]["overall"]),
            "by_band": {b: _rate(p)
                        for b, p in tallies[v]["by_band"].items()},
            "uncomputable_cases": tallies[v]["uncomputable"],
        }
    return report
