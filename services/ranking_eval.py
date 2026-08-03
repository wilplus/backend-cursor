"""F1 — ranking eval set: is the best-per-slide pick actually the best?

Protocol RATIFIED by the founder 2026-08-03 (docs/RANKING-EVAL.md carries the
full decision record). The load-bearing choices:

  UNIT      one case = one (session, slide) with ≥2 candidate lines — the
            exact decision ``select_best_per_slide`` makes; single takes
            qualify (the ranker never sees take_index). Deckless + imported
            audio are OUT of v1 scope: counted, never silent.
  RUBRIC    the rater answers ONE question: "Which of these would I put in
            their best speech?" — holistic (said + delivered together).
  MODALITY  the rater LISTENS to every candidate, via a self-contained
            local labeling page (render_labeling_page): span playback,
            forced choice, blind.
  ESCAPE    forced choice ALWAYS + a "none of these belong in a best
            speech" checkbox; the report scores all cases and again with
            flagged-garbage cases excluded.
  CEILING   ~10 already-labeled cases are re-served at the end, letters
            reshuffled, disguised as fresh cases. Rater self-agreement on
            those repeats is the ceiling every machine number is judged
            against (R0: ceiling < 0.70 → refine the RUBRIC, judge nothing).
  RULES     R0–R5 agreed BEFORE any number existed — see decide() below.

VARIANTS scored offline from the closed key (drift-proofed: machine picks
come from the REAL select_best_per_slide / power_score, never re-implemented;
the one mirrored piece is the snippet→candidate field mapping from
build_best_presentation:626-694, cited field-by-field):

  shipped_local     the per-slide decision (production selector, case-only)
  shipped_assembly  after the cross-slide dedupe (path-dependence cost)
  no_sentence_gate  completeness demoted from hard sort key to tiebreak
  debiased_coverage slide coverage entering the score ONCE (topic recovered
                    as 2·overall − slide; lab_recording.py:759)
  confidence_on     the STAMPED voice-confidence read served into the blend
                    — simulates VOICE_CONFIDENCE_RANKING_ENABLED=1 without
                    touching the flag (the read is stamped at analysis time
                    even while serving is off; [-1,1], the exact scale
                    rank_term would feed power_score's w_v term)

BLIND (same discipline as confidence_labels): the rater surface carries the
moment and nothing else — no score, no band, no take, no direction, no
machine pick, and repeats are indistinguishable from fresh cases. Bands
select cases and live key-side only.

AC-9: internal, coach-side. Nothing here ever rides a user payload. Pure and
DB-free — the scripts own all I/O.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import string
from typing import Any, Optional

logger = logging.getLogger(__name__)

BANDS = ("gate_decided", "close", "clear")
DEFAULT_PER_BAND = 10
DEFAULT_CLOSE_GAP = 0.10
DEFAULT_MAX_CANDIDATES = 8
DEFAULT_REPEATS = 10

# R0 — the rubric-noise gate: self-agreement below this and no other rule
# may convict anything (noisy ground truth convicts nothing).
CEILING_FLOOR = 0.70
# R1-R3 — "clearly wins": ≥ this share of DECIDED differing cases…
WIN_SHARE = 2.0 / 3.0
# …with at least this many decided differing cases; fewer → "insufficient".
MIN_DECIDED = 6
# R5 — shipped may lag the ceiling by at most this much (garbage excluded).
FLOOR_GAP = 0.20

_LETTERS = string.ascii_uppercase

# The rater-facing sheet is built by ALLOWLIST — a field not named here
# cannot leak, whatever gets added to candidates later.
BLIND_COLUMNS = (
    "case_id", "slide_no", "slide_title", "slide_body", "candidate",
    "transcript", "audio_url", "start_offset_ms", "duration_ms",
)

KEY_COLUMNS = (
    "case_id", "candidate", "session_id", "snippet_id", "slide_index",
    "take_index", "band", "repeat_of", "score", "complete",
    "shipped_local_pick", "shipped_assembly_pick", "activation",
    "slide_stickiness", "topic_stickiness", "tag", "direction",
    "coach_direction", "breakthrough", "voice_confidence",
    "voice_confidence_stamped", "transcript_source", "start_offset_ms",
)

ANSWER_COLUMNS = ("case_id", "picked", "none_fit", "why")


# ─────────────────────────────────────────────────────────────────
# Candidate construction (mirrors build_best_presentation 626-694)
# ─────────────────────────────────────────────────────────────────

def _stamped_confidence(metrics: Any) -> Optional[float]:
    """The voice-confidence composite STAMPED on the piece at analysis time
    (metrics["voice_confidence"]["score"], [-1,1]) — independent of the
    serving flag. This is what rank_term would hand power_score if
    VOICE_CONFIDENCE_RANKING_ENABLED were on, which is exactly what the
    ``confidence_on`` variant simulates. None when unstamped (pre-composite
    pieces) — power_score's documented no-op, preserving neutrality."""
    if not isinstance(metrics, dict):
        return None
    read = metrics.get("voice_confidence")
    if not isinstance(read, dict):
        return None
    score = read.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        return None
    return max(-1.0, min(1.0, float(score)))


def build_session_candidates(
    session: Any, snippets: Any, coach_labels: Any = None,
    corrections: Any = None,
) -> list:
    """One session's snippets → ranking candidates carrying EXACTLY the
    fields build_best_presentation feeds power_score, plus key-side context
    (topic_stickiness, stamped confidence, coach_direction,
    transcript_source). Direction resolution and the breakthrough gate are
    the production functions themselves. Pure; [] on unusable input."""
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
            "voice_confidence_stamped": _stamped_confidence(metrics),
            "tag": None,  # best_presentation.py:690 — labels live in drafts
        })
    return out


# ─────────────────────────────────────────────────────────────────
# Cases + machine picks + bands
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
    is counted, none is silent."""
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
        while case_id in seen_ids:
            case_id += "x"
        seen_ids.add(case_id)
        cases.append({
            "case_id": case_id,
            "session_id": sid,
            "slide_index": si,
            "repeat_of": None,
            "candidates": [_annotate(c) for c in cands],
        })
    return cases, stats


def attach_machine_picks(cases: list, session_candidates: dict) -> None:
    """Mark each candidate with the two shipped answers, in place.
    shipped_local = the REAL select_best_per_slide over the case alone;
    shipped_assembly = over the candidate's whole session (post-dedupe)."""
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
    """gate_decided = the complete-sentence sort key, not the score, chose
    the winner; close = top-two production-order score gap < close_gap;
    clear = the rest."""
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
# Sampling, repeats (the ceiling), letters
# ─────────────────────────────────────────────────────────────────

def draw_sample(
    cases: list, *, per_band: int = DEFAULT_PER_BAND,
    seed: Optional[int] = None, repeats: int = DEFAULT_REPEATS,
) -> list:
    """Stratified draw across BANDS (random within band, round-robin fill so
    a short band redistributes its shortfall), then ``repeats`` of the
    picked cases are cloned to the END of the run — case_id suffixed '-r'
    (key-side only; the page shows sequential numbering, so a repeat is
    indistinguishable from a fresh case), letters INDEPENDENTLY reshuffled.
    Self-agreement across the pairs is the R0 ceiling."""
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

    pool = list(picked)
    rng.shuffle(pool)
    for orig in pool[:max(0, int(repeats))]:
        clone = {
            **{k: v for k, v in orig.items() if k != "candidates"},
            "case_id": orig["case_id"] + "-r",
            "repeat_of": orig["case_id"],
            "candidates": [dict(c) for c in orig["candidates"]],
        }
        _assign_letters(clone, rng)
        picked.append(clone)
    return picked


def _assign_letters(case: dict, rng: random.Random) -> None:
    """Shuffle candidate order and letter them — presentation order must be
    neither speech order (position bias) nor rank order (leak)."""
    cands = list(case["candidates"])
    rng.shuffle(cands)
    for letter, c in zip(_LETTERS, cands):
        c["candidate"] = letter
    case["candidates"] = cands


# ─────────────────────────────────────────────────────────────────
# The two artifacts + the labeling page
# ─────────────────────────────────────────────────────────────────

def blind_rows(cases: list, slides_by_session: Any = None,
               audio_urls: Any = None) -> list:
    """Archive copy of what the rater sees — allowlist construction, one row
    per candidate. The PAGE is the primary labeling surface; this sheet
    exists so the run is inspectable later without opening the page."""
    decks = slides_by_session if isinstance(slides_by_session, dict) else {}
    urls = audio_urls if isinstance(audio_urls, dict) else {}
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
                "audio_url": urls.get(str(c.get("snippet_id")))
                             or c.get("audio_ref") or "",
                "start_offset_ms": c.get("start_offset_ms"),
                "duration_ms": c.get("duration_ms"),
            })
    for r in rows:
        assert set(r) == set(BLIND_COLUMNS), "blind sheet fence violated"
    return rows


def key_rows(cases: list) -> list:
    """The closed key — everything the report needs to score every variant
    without re-touching the DB. KEEP CLOSED until labeling is done."""
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
                "repeat_of": case.get("repeat_of") or "",
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
                "voice_confidence_stamped": c.get("voice_confidence_stamped"),
                "transcript_source": c.get("transcript_source"),
                "start_offset_ms": c.get("start_offset_ms"),
            })
    return rows


def page_payload(cases: list, slides_by_session: Any = None,
                 audio_urls: Any = None) -> list:
    """What the labeling page embeds — the same allowlist as blind_rows,
    shaped per-case. Repeats carry NO marker here (the disguise); the page
    shows 'Case N of M' only, never the case_id."""
    decks = slides_by_session if isinstance(slides_by_session, dict) else {}
    urls = audio_urls if isinstance(audio_urls, dict) else {}
    out = []
    for case in cases:
        deck = decks.get(case["session_id"]) or []
        si = case["slide_index"]
        slide = deck[si] if isinstance(deck, list) and si < len(deck) else {}
        slide = slide if isinstance(slide, dict) else {}
        out.append({
            "id": case["case_id"],
            "slide_no": si + 1,
            "title": (slide.get("title") or "")[:120],
            "body": (slide.get("body") or "")[:200],
            "cands": [
                {
                    "letter": c.get("candidate"),
                    "text": c.get("transcript") or "",
                    "url": urls.get(str(c.get("snippet_id")))
                           or c.get("audio_ref") or "",
                    "start_ms": c.get("start_offset_ms") or 0,
                    "dur_ms": c.get("duration_ms") or 0,
                }
                for c in case["candidates"]
            ],
        })
    return out


def run_id_for(cases: list) -> str:
    """Stable id for one export run — keys the page's localStorage so a
    fresh export never collides with an old run's saved progress."""
    joined = "|".join(c["case_id"] for c in cases)
    return hashlib.sha1(joined.encode("utf-8")).hexdigest()[:12]


def render_labeling_page(payload: list, run_id: str) -> str:
    """The self-contained labeling page (founder-ratified option A): one
    case at a time, span playback per lettered candidate, forced choice +
    the 'none of these belong' checkbox + optional why, resume via
    localStorage, answers exported as CSV matching ANSWER_COLUMNS.

    BLIND: the embedded payload is page_payload's allowlist — no score, no
    band, no take, no machine pick, no repeat marker. Internal coach tool
    (AC-9): never shipped to a user, never served by the app."""
    data = json.dumps(payload, ensure_ascii=False)
    total = len(payload)
    return _PAGE_TEMPLATE.replace("__DATA__", data) \
                         .replace("__RUN_ID__", run_id) \
                         .replace("__TOTAL__", str(total))


_PAGE_TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>willab — best-line labeling</title>
<style>
  :root { --fg:#1a1a1a; --dim:#777; --line:#e3e3e3; --acc:#2456d6;
          --accbg:#eef2fd; --warn:#b00020; }
  * { box-sizing:border-box; }
  body { font:16px/1.5 system-ui,-apple-system,sans-serif; color:var(--fg);
         max-width:760px; margin:0 auto; padding:24px 16px 96px; }
  h1 { font-size:18px; margin:0 0 2px; }
  .sub { color:var(--dim); font-size:13px; margin-bottom:18px; }
  .progress { height:6px; background:var(--line); border-radius:3px;
              margin:12px 0 20px; overflow:hidden; }
  .progress > div { height:100%; background:var(--acc); width:0; }
  .slide { border:1px solid var(--line); border-radius:10px;
           padding:12px 16px; margin-bottom:16px; background:#fafafa; }
  .slide b { display:block; margin-bottom:2px; }
  .slide span { color:var(--dim); font-size:14px; }
  .cand { border:1px solid var(--line); border-radius:10px; padding:12px;
          margin-bottom:10px; display:flex; gap:12px; align-items:flex-start;
          cursor:pointer; }
  .cand.picked { border-color:var(--acc); background:var(--accbg); }
  .cand .letter { flex:0 0 34px; height:34px; border-radius:50%;
          background:var(--fg); color:#fff; display:flex; align-items:center;
          justify-content:center; font-weight:700; }
  .cand.picked .letter { background:var(--acc); }
  .cand .body { flex:1; }
  .cand button.play { border:1px solid var(--line); background:#fff;
          border-radius:6px; padding:4px 12px; cursor:pointer; font-size:13px;
          margin-bottom:6px; }
  .cand button.play.playing { background:var(--acc); color:#fff;
          border-color:var(--acc); }
  .cand .err { color:var(--warn); font-size:12px; display:none; }
  .extras { margin:14px 0; }
  .extras label { display:flex; gap:8px; align-items:center; font-size:14px;
          color:var(--dim); cursor:pointer; }
  textarea { width:100%; border:1px solid var(--line); border-radius:8px;
          padding:8px; font:14px/1.4 inherit; margin-top:8px; resize:vertical;
          min-height:44px; }
  .nav { position:fixed; bottom:0; left:0; right:0; background:#fff;
         border-top:1px solid var(--line); padding:10px 16px; }
  .nav .in { max-width:760px; margin:0 auto; display:flex; gap:10px;
             align-items:center; }
  .nav button { border:1px solid var(--line); background:#fff; padding:8px 18px;
          border-radius:8px; cursor:pointer; font-size:14px; }
  .nav button.primary { background:var(--acc); color:#fff;
          border-color:var(--acc); }
  .nav button:disabled { opacity:.4; cursor:default; }
  .nav .stat { margin-left:auto; color:var(--dim); font-size:13px; }
  .hint { color:var(--warn); font-size:13px; margin-top:8px; display:none; }
</style>
</head>
<body>
<h1>Pick the line you would put in their best speech</h1>
<div class="sub">Listen to every candidate before picking. One winner per
case — the checkbox is for slides where even the winner is not
speech-worthy. Progress saves automatically; close and come back anytime.</div>
<div class="progress"><div id="bar"></div></div>
<div id="stage"></div>
<div class="hint" id="hint">Pick one candidate before moving on.</div>
<div class="nav"><div class="in">
  <button id="prev">&larr; Back</button>
  <button id="next" class="primary">Next &rarr;</button>
  <button id="dl">Download answers</button>
  <span class="stat" id="stat"></span>
</div></div>
<script>
"use strict";
const CASES = __DATA__;
const RUN = "rankeval-__RUN_ID__";
const TOTAL = __TOTAL__;
let idx = 0;
let answers = {};
try { const s = localStorage.getItem(RUN);
      if (s) { const o = JSON.parse(s); answers = o.answers || {};
               idx = Math.min(o.idx || 0, TOTAL - 1); } } catch (e) {}

const audio = new Audio();
let stopAt = null, playingBtn = null;
audio.addEventListener("timeupdate", () => {
  if (stopAt !== null && audio.currentTime >= stopAt) stopPlay();
});
audio.addEventListener("ended", stopPlay);
function stopPlay() {
  audio.pause(); stopAt = null;
  if (playingBtn) { playingBtn.classList.remove("playing");
                    playingBtn.textContent = "▶ Play"; playingBtn = null; }
}
function playSpan(btn, url, startMs, durMs, errEl) {
  if (playingBtn === btn) { stopPlay(); return; }
  stopPlay();
  playingBtn = btn; btn.classList.add("playing"); btn.textContent = "■ Stop";
  errEl.style.display = "none";
  const begin = () => {
    let t0 = (startMs || 0) / 1000;
    // Per-clip files: a start beyond the media length means the ref IS the
    // clip — play it whole.
    if (audio.duration && t0 >= audio.duration - 0.2) t0 = 0;
    audio.currentTime = t0;
    stopAt = durMs ? t0 + durMs / 1000 : null;
    audio.play().catch(() => { errEl.style.display = "block"; stopPlay(); });
  };
  if (audio.src !== url) {
    audio.src = url;
    audio.addEventListener("loadedmetadata", begin, { once: true });
    audio.addEventListener("error", () => {
      errEl.style.display = "block"; stopPlay(); }, { once: true });
    audio.load();
  } else { begin(); }
}

function save() {
  try { localStorage.setItem(RUN, JSON.stringify({ answers, idx })); }
  catch (e) {}
  const done = Object.keys(answers).filter(k => answers[k].picked).length;
  document.getElementById("stat").textContent = done + " / " + TOTAL + " labeled";
  document.getElementById("bar").style.width = (100 * done / TOTAL) + "%";
}

function render() {
  stopPlay();
  const c = CASES[idx];
  const a = answers[c.id] || {};
  const stage = document.getElementById("stage");
  stage.textContent = "";
  const slide = document.createElement("div");
  slide.className = "slide";
  const b = document.createElement("b");
  b.textContent = "Case " + (idx + 1) + " of " + TOTAL +
                  " — slide " + c.slide_no +
                  (c.title ? ": " + c.title : "");
  slide.appendChild(b);
  if (c.body) { const s = document.createElement("span");
                s.textContent = c.body; slide.appendChild(s); }
  stage.appendChild(slide);

  c.cands.forEach(cd => {
    const card = document.createElement("div");
    card.className = "cand" + (a.picked === cd.letter ? " picked" : "");
    const lt = document.createElement("div");
    lt.className = "letter"; lt.textContent = cd.letter;
    const body = document.createElement("div"); body.className = "body";
    const btn = document.createElement("button");
    btn.className = "play"; btn.textContent = "▶ Play";
    const err = document.createElement("div");
    err.className = "err";
    err.textContent = "Audio failed to load — the link may have expired; re-run the export.";
    btn.addEventListener("click", ev => {
      ev.stopPropagation(); playSpan(btn, cd.url, cd.start_ms, cd.dur_ms, err);
    });
    const tx = document.createElement("div"); tx.textContent = cd.text;
    body.appendChild(btn); body.appendChild(tx); body.appendChild(err);
    card.appendChild(lt); card.appendChild(body);
    card.addEventListener("click", () => {
      answers[c.id] = { ...(answers[c.id] || {}), picked: cd.letter };
      save(); render();
    });
    stage.appendChild(card);
  });

  const ex = document.createElement("div"); ex.className = "extras";
  const lab = document.createElement("label");
  const cb = document.createElement("input");
  cb.type = "checkbox"; cb.checked = !!a.none_fit;
  cb.addEventListener("change", () => {
    answers[c.id] = { ...(answers[c.id] || {}), none_fit: cb.checked };
    save();
  });
  lab.appendChild(cb);
  lab.appendChild(document.createTextNode(
    "None of these belong in a best speech"));
  ex.appendChild(lab);
  const ta = document.createElement("textarea");
  ta.placeholder = "Why this one? (optional — feeds the coach corpus)";
  ta.value = a.why || "";
  ta.addEventListener("input", () => {
    answers[c.id] = { ...(answers[c.id] || {}), why: ta.value };
    save();
  });
  ex.appendChild(ta);
  stage.appendChild(ex);

  document.getElementById("prev").disabled = idx === 0;
  document.getElementById("next").textContent =
    idx === TOTAL - 1 ? "Done" : "Next →";
  document.getElementById("hint").style.display = "none";
  save();
}

document.getElementById("prev").addEventListener("click", () => {
  if (idx > 0) { idx--; save(); render(); }
});
document.getElementById("next").addEventListener("click", () => {
  const c = CASES[idx];
  if (!(answers[c.id] || {}).picked) {
    document.getElementById("hint").style.display = "block"; return;
  }
  if (idx < TOTAL - 1) { idx++; save(); render(); }
  else { download(); }
});
function csvEsc(v) {
  const s = String(v == null ? "" : v).replace(/\r?\n/g, " ");
  return '"' + s.replace(/"/g, '""') + '"';
}
function download() {
  const missing = CASES.filter(c => !(answers[c.id] || {}).picked).length;
  if (missing &&
      !confirm(missing + " case(s) unlabeled — download anyway?")) return;
  const lines = ["case_id,picked,none_fit,why"];
  CASES.forEach(c => {
    const a = answers[c.id] || {};
    if (!a.picked) return;
    lines.push([csvEsc(c.id), csvEsc(a.picked), a.none_fit ? "1" : "0",
                csvEsc(a.why || "")].join(","));
  });
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const aEl = document.createElement("a");
  aEl.href = URL.createObjectURL(blob);
  aEl.download = "ranking_answers.csv";
  aEl.click();
}
document.getElementById("dl").addEventListener("click", download);
render();
</script>
</body>
</html>
"""


# ─────────────────────────────────────────────────────────────────
# Scoring (after the answers come back)
# ─────────────────────────────────────────────────────────────────

def parse_answers(rows: Any) -> tuple[dict, set, dict, list]:
    """The page's answers CSV → (labels {case_id: LETTER}, none_fit ids,
    why {case_id: text}, problems). A duplicated case_id or a row without a
    pick is a problem, reported never silent."""
    labels: dict = {}
    none_fit: set = set()
    why: dict = {}
    problems: list = []
    for r in rows or []:
        if not isinstance(r, dict):
            continue
        cid = (r.get("case_id") or "").strip()
        if not cid:
            continue
        pick = (r.get("picked") or "").strip().upper()
        if not pick:
            problems.append(f"{cid}: row without a pick")
            continue
        if cid in labels:
            problems.append(f"{cid}: duplicated in answers")
            continue
        labels[cid] = pick
        if str(r.get("none_fit") or "").strip().lower() in ("1", "true", "x", "yes"):
            none_fit.add(cid)
        w = (r.get("why") or "").strip()
        if w:
            why[cid] = w
    return labels, none_fit, why, problems


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
    """CSV strings back into typed key rows."""
    out = []
    for r in raw_rows or []:
        if not isinstance(r, dict):
            continue
        row = dict(r)
        for k in ("score", "activation", "slide_stickiness",
                  "topic_stickiness", "voice_confidence",
                  "voice_confidence_stamped"):
            row[k] = _parse_opt_float(r.get(k))
        for k in ("complete", "shipped_local_pick", "shipped_assembly_pick",
                  "breakthrough"):
            row[k] = _parse_bool(r.get(k))
        for k in ("tag", "direction", "coach_direction"):
            row[k] = (r.get(k) or "").strip() or None
        row["candidate"] = (r.get("candidate") or "").strip().upper()
        row["repeat_of"] = (r.get("repeat_of") or "").strip() or None
        out.append(row)
    return out


def _debiased_activation(row: dict) -> Optional[float]:
    """activation with the slide-coverage half removed (lab_recording.py:759
    — overall = 0.5·topic + 0.5·slide; slide null → overall = topic). None
    stays None: the non-budget-piece neutrality is preserved."""
    ov = row.get("activation")
    if ov is None:
        return None
    ss = row.get("slide_stickiness")
    if ss is None:
        return ov
    return max(0.0, min(1.0, 2.0 * ov - ss))


VARIANTS = ("shipped_local", "shipped_assembly", "no_sentence_gate",
            "debiased_coverage", "confidence_on")


def _variant_pick(rows: list, variant: str) -> Optional[str]:
    """The winning letter for one case under one variant; None = variant
    can't be computed for this case (counted by the report, never silent).
    Each variant isolates ONE change against the production order."""
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
        scored.sort(key=lambda t: (t[1], t[0]), reverse=True)
        return scored[0][2]["candidate"]
    if variant == "confidence_on":
        scored = []
        for r in rows:
            kw = _score_kwargs(r)
            kw["voice_confidence"] = r.get("voice_confidence_stamped")
            scored.append((power_score(**kw), bool(r.get("complete")), r))
        scored.sort(key=lambda t: (t[1], t[0]), reverse=True)
        return scored[0][2]["candidate"]
    return None


def _rate(pair: list) -> dict:
    a, n = pair
    return {"agree": a, "n": n, "rate": round(a / n, 3) if n else None}


def _agreement_pass(labels: dict, by_case: dict, exclude: set) -> dict:
    """One scoring pass over BASE cases (repeats never enter machine rates)."""
    out: dict = {v: {"overall": [0, 0], "by_band": {b: [0, 0] for b in BANDS},
                     "uncomputable": 0} for v in VARIANTS}
    disagreements: list = []
    for cid, human in sorted(labels.items()):
        rows = by_case.get(cid)
        if not rows or rows[0].get("repeat_of") or cid in exclude:
            continue
        band = rows[0].get("band") or "clear"
        for v in VARIANTS:
            pick = _variant_pick(rows, v)
            if pick is None:
                out[v]["uncomputable"] += 1
                continue
            agree = pick == human
            out[v]["overall"][1] += 1
            out[v]["overall"][0] += 1 if agree else 0
            bb = out[v]["by_band"].setdefault(band, [0, 0])
            bb[1] += 1
            bb[0] += 1 if agree else 0
            if v == "shipped_local" and not agree:
                disagreements.append({"case_id": cid, "band": band,
                                      "human": human, "shipped": pick})
    return {
        "variants": {v: {"overall": _rate(out[v]["overall"]),
                         "by_band": {b: _rate(p)
                                     for b, p in out[v]["by_band"].items()},
                         "uncomputable_cases": out[v]["uncomputable"]}
                     for v in VARIANTS},
        "disagreements": disagreements,
    }


def _ceiling(labels: dict, by_case: dict) -> dict:
    """R0 — rater self-agreement on the disguised repeats, matched by the
    PICKED SNIPPET (letters were reshuffled between the pair on purpose)."""
    pairs = 0
    agree = 0
    for cid, rows in by_case.items():
        orig_id = rows[0].get("repeat_of")
        if not orig_id:
            continue
        if cid not in labels or orig_id not in labels:
            continue
        rep_pick = next((r.get("snippet_id") for r in rows
                         if r.get("candidate") == labels[cid]), None)
        orig_rows = by_case.get(orig_id) or []
        orig_pick = next((r.get("snippet_id") for r in orig_rows
                          if r.get("candidate") == labels[orig_id]), None)
        if rep_pick is None or orig_pick is None:
            continue
        pairs += 1
        agree += 1 if rep_pick == orig_pick else 0
    return {"pairs": pairs, "agree": agree,
            "rate": round(agree / pairs, 3) if pairs else None}


def _duel(labels: dict, by_case: dict, challenger: str, exclude: set) -> dict:
    """R1–R3 verdict machinery: on cases where challenger and shipped_local
    DIFFER, who matched the human? Decided = exactly one of them did.
    clear_win needs ≥MIN_DECIDED decided cases AND challenger share ≥
    WIN_SHARE (the ratified 2-of-3 standard)."""
    differing = 0
    wins = 0
    losses = 0
    for cid, human in labels.items():
        rows = by_case.get(cid)
        if not rows or rows[0].get("repeat_of") or cid in exclude:
            continue
        base = _variant_pick(rows, "shipped_local")
        ch = _variant_pick(rows, challenger)
        if base is None or ch is None or base == ch:
            continue
        differing += 1
        if ch == human and base != human:
            wins += 1
        elif base == human and ch != human:
            losses += 1
    decided = wins + losses
    if decided < MIN_DECIDED:
        verdict = "insufficient_data"
    elif wins / decided >= WIN_SHARE:
        verdict = "clear_win"
    elif losses / decided >= WIN_SHARE:
        verdict = "clear_loss"
    else:
        verdict = "no_clear_winner"
    return {"differing": differing, "decided": decided, "wins": wins,
            "losses": losses, "verdict": verdict}


def agreement_report(labels: dict, key: list,
                     none_fit: Optional[set] = None) -> dict:
    """Human labels × closed key → the full ratified report: ceiling (R0),
    per-variant agreement all-cases and garbage-excluded, R1–R3 duels on
    the clean pass, R4 gap, R5 floor check. Verdict actions trigger off the
    CLEAN numbers (ratified); both passes are reported."""
    nf = none_fit or set()
    by_case: dict = {}
    for r in key or []:
        by_case.setdefault(r.get("case_id"), []).append(r)

    base_ids = {cid for cid, rows in by_case.items()
                if not rows[0].get("repeat_of")}
    labeled_base = {cid: v for cid, v in (labels or {}).items()
                    if cid in base_ids}
    unmatched = sum(1 for cid in (labels or {})
                    if cid not in by_case)

    ceiling = _ceiling(labels or {}, by_case)
    all_pass = _agreement_pass(labeled_base, by_case, set())
    clean_pass = _agreement_pass(labeled_base, by_case, nf)

    duels = {
        "R1_no_sentence_gate": _duel(labeled_base, by_case,
                                     "no_sentence_gate", nf),
        "R2_debiased_coverage": _duel(labeled_base, by_case,
                                      "debiased_coverage", nf),
        "R3_confidence_on": _duel(labeled_base, by_case,
                                  "confidence_on", nf),
    }
    r0_gated = ceiling["rate"] is not None and ceiling["rate"] < CEILING_FLOOR
    if r0_gated:
        for d in duels.values():
            d["verdict"] = f"GATED_BY_R0({d['verdict']})"

    local = clean_pass["variants"]["shipped_local"]["overall"]["rate"]
    asm = clean_pass["variants"]["shipped_assembly"]["overall"]["rate"]
    r4_gap = (round(local - asm, 3)
              if local is not None and asm is not None else None)
    r5_breach = (ceiling["rate"] is not None and local is not None
                 and (ceiling["rate"] - local) > FLOOR_GAP)

    return {
        "cases_labeled": len(labeled_base),
        "cases_unmatched": unmatched,
        "none_fit_flagged": len(nf & base_ids),
        "ceiling": ceiling,
        "r0_gated": r0_gated,
        "all_cases": all_pass,
        "clean": clean_pass,
        "duels": duels,
        "r4_local_minus_assembly": r4_gap,
        "r5_floor_breached": bool(r5_breach),
    }
