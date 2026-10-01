"""The golden evaluation for a coach-answer surface (founder 2026-09-30, L6,
L7; counsel 2026-10-01; build plan ML-10, ML-11).

A candidate model is compared with the baseline on the founder's sealed
golden set, through the very adapter that serves the coach
(``compose_draft`` under ``evaluation_model_override``), so a model that
cannot answer in the serving shape fails here and never reaches a row:

  * the set must be sealed and still what was sealed (ML-10); only the
    moments the founder answered "yes" to carry a reference (the coach's
    final the founder confirmed), and at least MIN_REFERENCES of them are
    needed before a score means anything;
  * the score is token F1 between the model's answer and the reference,
    averaged; "ahead" means the candidate's mean beats the baseline's;
  * counsel's regurgitation check: every candidate answer is searched for
    an 8-word window of any passage or final the run learned from whose
    owner has since withdrawn; one hit fails the model, and the run is
    retrained without those pairs (ML-11). The same windows are counted
    against every trained text as a memorisation rate, for the record.

The report is a row (``evaluation_reports``) and nothing else: no
promotion, no runtime_config write. AC-9: a number here is about a model,
never a person, and reaches the research screen only.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from services.golden_set import GoldenRefusal, PAIR_SURFACES, digest, sealed_rows

_log = logging.getLogger(__name__)

REPORT_VERSION = "golden-evaluation-v1"
MIN_REFERENCES = 20
WINDOW_WORDS = 8
_WORD = re.compile(r"[\w']+", re.UNICODE)


class EvaluationRefusal(Exception):
    def __init__(self, message: str, code: str = "EVALUATION_REFUSED"):
        super().__init__(message)
        self.message, self.code = message, code


def tokens(text: Any) -> list[str]:
    return [t.lower() for t in _WORD.findall(str(text or ""))]


def token_f1(candidate: Any, reference: Any) -> float:
    """Bag-of-words F1, the plain overlap score. 0 when either is empty."""
    a, b = tokens(candidate), tokens(reference)
    if not a or not b:
        return 0.0
    counts: dict[str, int] = {}
    for t in b:
        counts[t] = counts.get(t, 0) + 1
    hit = 0
    for t in a:
        if counts.get(t, 0) > 0:
            counts[t] -= 1
            hit += 1
    if hit == 0:
        return 0.0
    precision, recall = hit / len(a), hit / len(b)
    return round(2 * precision * recall / (precision + recall), 4)


def windows(text: Any, size: int = WINDOW_WORDS) -> set[tuple[str, ...]]:
    words = tokens(text)
    return {tuple(words[i:i + size]) for i in range(0, max(0, len(words) - size + 1))}


def reproduces(answer: Any, corpus_windows: set[tuple[str, ...]]) -> bool:
    """True when the answer carries an 8-word window of the corpus."""
    return bool(corpus_windows) and not windows(answer).isdisjoint(corpus_windows)


def references_from(rows: list[dict]) -> list[dict]:
    """The founder's yes-moments: {passage, reference, prompt_context}."""
    out = []
    for row in rows:
        if row.get("value") != "yes":
            continue
        passage = " ".join(str(row.get("passage") or "").split())
        reference = str(row.get("reference") or "").strip()
        if passage and reference:
            out.append({"snippet_id": str(row.get("snippet_id")), "passage": passage,
                        "reference": reference,
                        "prompt_context": row.get("prompt_context") or {}})
    return out


def _answer(surface: str, moment: dict, *, model: Optional[str], compose: Callable) -> str:
    from services.ml_surface_contracts import evaluation_model_override
    context = moment.get("prompt_context") or {}
    kind = str(context.get("kind") or {"exercise_script": "error", "praise_line": "praise",
                                       "clearer_version": "rewrite"}[surface])
    spotted = [str(context.get("pattern_key"))] if context.get("pattern_key") else []
    if model:
        with evaluation_model_override(surface, model):
            out = compose(surface=surface, passage=moment["passage"], spotted=spotted, kind=kind)
    else:
        out = compose(surface=surface, passage=moment["passage"], spotted=spotted, kind=kind)
    return str((out or {}).get("text") or "") if isinstance(out, dict) else ""


def evaluate(database: Any, *, surface: str, candidate_model: str,
             baseline_model: str, run_id: Optional[str] = None,
             withdrawn_texts: Optional[list[str]] = None,
             trained_texts: Optional[list[str]] = None,
             compose: Optional[Callable] = None,
             now: Optional[datetime] = None) -> dict:
    """Run the evaluation and store its report. Returns the stored row's
    fields. Raises EvaluationRefusal (and GoldenRefusal for the set)."""
    if surface not in PAIR_SURFACES:
        raise EvaluationRefusal(f"{surface} has no golden evaluation", "UNKNOWN_SURFACE")
    candidate = str(candidate_model or "").strip()
    if not candidate:
        raise EvaluationRefusal("candidate_model is required", "INVALID_INPUT")
    rows = sealed_rows(database, surface=surface)          # ML-10: refuses unsealed
    refs = references_from(rows)
    if len(refs) < MIN_REFERENCES:
        raise EvaluationRefusal(
            f"only {len(refs)} confirmed references in the sealed set; {MIN_REFERENCES} needed",
            "TOO_FEW_REFERENCES")
    if compose is None:
        from services.coach_request_drafts import compose_draft
        compose = compose_draft
    withdrawn = set()
    for text in withdrawn_texts or []:
        withdrawn |= windows(text)
    trained = set()
    for text in trained_texts or []:
        trained |= windows(text)

    scored = []
    regurgitated = 0
    memorised = 0
    for moment in refs:
        cand = _answer(surface, moment, model=candidate, compose=compose)
        base = _answer(surface, moment, model=None, compose=compose)
        if reproduces(cand, withdrawn):
            regurgitated += 1
        if reproduces(cand, trained):
            memorised += 1
        scored.append({"snippet_id": moment["snippet_id"],
                       "candidate_f1": token_f1(cand, moment["reference"]),
                       "baseline_f1": token_f1(base, moment["reference"]),
                       "candidate_answered": bool(cand), "baseline_answered": bool(base)})
    n = len(scored)
    cand_mean = round(sum(s["candidate_f1"] for s in scored) / n, 4)
    base_mean = round(sum(s["baseline_f1"] for s in scored) / n, 4)
    answered = sum(1 for s in scored if s["candidate_answered"])
    ahead = cand_mean > base_mean
    regurgitation_ok = regurgitated == 0
    passed = ahead and regurgitation_ok and answered == n
    report = {
        "report_version": REPORT_VERSION,
        "surface": surface,
        "candidate_model": candidate,
        "baseline_model": str(baseline_model),
        "golden_count": len(rows),
        "references": n,
        "candidate_mean_f1": cand_mean,
        "baseline_mean_f1": base_mean,
        "ahead": ahead,
        "candidate_answered": answered,
        "regurgitation": {"withdrawn_texts": len(withdrawn_texts or []),
                          "window_words": WINDOW_WORDS,
                          "hits": regurgitated, "ok": regurgitation_ok},
        "memorisation": {"trained_texts": len(trained_texts or []), "hits": memorised,
                         "rate": round(memorised / n, 4)},
        "per_moment": scored,
        "evaluated_at": (now or datetime.now(timezone.utc)).isoformat(),
        "passed": passed,
    }
    stored = database.insert_evaluation_report(
        report_version=REPORT_VERSION, surface=surface, run_id=run_id,
        candidate_model=candidate, baseline_model=str(baseline_model),
        golden_sha256=digest(rows), golden_count=len(rows),
        prompt_lock_sha256=_prompt_lock(surface), report=report, passed=passed)
    return {**(dict(stored) if isinstance(stored, dict) else {}), "report": report, "passed": passed}


def _prompt_lock(surface: str) -> Optional[str]:
    try:
        from services.ml_surface_contracts import locked_prompt_hash
        return locked_prompt_hash(surface)
    except Exception as e:  # noqa: BLE001 -- the lock is a record, not a gate here
        _log.info("prompt lock unavailable for %s: %s", surface, e)
        return None


__all__ = ["evaluate", "token_f1", "reproduces", "windows", "references_from",
           "EvaluationRefusal", "GoldenRefusal", "MIN_REFERENCES"]
