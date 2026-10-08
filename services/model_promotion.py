"""Door 4: promote by the founder's word (founder 2026-09-30, L8, L9;
build plan ML-12). Built with the door closed; door 4 OPEN since 2026-10-08
for exercise_script, praise_line and clearer_version (founder: "turn it all
ON"), held behind Privacy and Terms 3.5 publication.

A promotion writes one runtime_config key for one surface, through the
only writer there is (``promote_runtime_surface_model_v1``, 0352, widened
in 0406), and leaves a history row (``model_promotions``) because the
runtime row holds only the present. It refuses unless:

  * ``MLC2_PROMOTION_ENABLED`` is True AND the founder named the surface
    (``Config.PROMOTION_SURFACES``, "open door 4 for surface S");
  * an evaluation report for that candidate on that surface passed, and
    its prompt lock is the current one (a prompt edit since the evaluation
    re-points a gated model at text it was never judged under, H-1);
  * the candidate's run was not withdrawn from since the report (a run
    whose owner withdrew keeps its model only if the regurgitation check
    passed AGAINST THAT WITHDRAWAL): the report must still be fresh, its
    checked withdrawn owners the withdrawn owners now, read live
    (services.model_training.withdrawn_basis); a stale report is refused
    and the candidate is evaluated again (audit DOOR-4-WITHDRAWN);
  * the run did not fail: a candidate that once failed the regurgitation
    check is never promoted, whatever a later report says (DOOR-3-RETRAIN).
    A freshness that cannot be read refuses too.

A kill returns the surface to the stock model within one request: the key
is set to the stock model id (which ``_model_the_promotion_gate_allows``
serves as the caller's own default) and the history row is marked killed.
The kill works with the door shut, because closing is never gated.

Only the named surface changes model; the coach's draft comes from the
promoted id through ``compose_draft`` (an answer surface) or
``coach_word_pairs.compose`` (the coach's own words, known to this door
since Privacy/Terms 3.5, N68); nothing a speaker sees changes shape. Both
drafters read SPEC_COACH_ANSWER_DRAFT, so the stock model a kill returns to
is the same.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

from services.feedback_pairs import DOOR_SURFACES as SURFACES

_log = logging.getLogger(__name__)


class PromotionRefusal(Exception):
    def __init__(self, message: str, code: str = "PROMOTION_REFUSED"):
        super().__init__(message)
        self.message, self.code = message, code


def door_open(config: Any) -> bool:
    return bool(getattr(config, "MLC2_PROMOTION_ENABLED", False))


def authorised_surfaces(config: Any) -> frozenset:
    if not door_open(config):
        return frozenset()
    named: Any = getattr(config, "PROMOTION_SURFACES", frozenset()) or frozenset()
    return frozenset(s for s in named if s in SURFACES)


def why_not(config: Any, surface: str) -> Optional[str]:
    if surface not in SURFACES:
        return f"{surface} is not a pair surface any door knows"
    if not door_open(config):
        return "door 4 closed (MLC2_PROMOTION_ENABLED)"
    if surface not in authorised_surfaces(config):
        return "door 4 open, but no founder sentence for this surface yet (PROMOTION_SURFACES)"
    return None


def stock_model() -> str:
    from services.llm_config import SPEC_COACH_ANSWER_DRAFT
    return str(getattr(SPEC_COACH_ANSWER_DRAFT, "model", "") or "")


def _key(surface: str) -> str:
    from services.ml_surface_contracts import runtime_config_key
    return runtime_config_key(surface)


def _prompt_lock(surface: str) -> str:
    from services.ml_surface_contracts import locked_prompt_hash
    return str(locked_prompt_hash(surface))


def promote(database: Any, *, surface: str, candidate_model: str,
            evaluation_report_id: str, by: str, config: Any,
            now: Optional[datetime] = None) -> dict:
    """Serve ``candidate_model`` on ``surface``. Raises PromotionRefusal."""
    reason = why_not(config, surface)
    if reason:
        raise PromotionRefusal(reason, "DOOR_CLOSED")
    candidate = str(candidate_model or "").strip()
    if not candidate:
        raise PromotionRefusal("candidate_model is required", "INVALID_INPUT")
    report = database.get_evaluation_report(str(evaluation_report_id))
    if not isinstance(report, dict):
        raise PromotionRefusal("no such evaluation report", "REPORT_UNKNOWN")
    if str(report.get("surface")) != surface or str(report.get("candidate_model")) != candidate:
        raise PromotionRefusal("the report is for another surface or model", "REPORT_MISMATCH")
    if report.get("passed") is not True:
        raise PromotionRefusal("the candidate did not pass its golden evaluation", "REPORT_FAILED")
    lock = _prompt_lock(surface)
    if str(report.get("prompt_lock_sha256") or "") != lock:
        raise PromotionRefusal("the prompts changed since this evaluation; re-run it",
                               "PROMPT_LOCK_MISMATCH")
    if report.get("run_id"):
        _refuse_unless_current(database, str(report["run_id"]), report)
    previous = database.get_runtime_config(_key(surface))
    now = now or datetime.now(timezone.utc)
    written = database.promote_runtime_surface_model(
        key=_key(surface), value=candidate, updated_by=str(by),
        metadata={"prompt_lock_sha256": lock, "evaluation_report_id": str(evaluation_report_id),
                  "run_id": report.get("run_id"), "promoted_at": now.isoformat()})
    if written is None:
        raise PromotionRefusal("the promote RPC is absent; run migrations/guard_runtime_config_model_keys.sql",
                               "RPC_MISSING")
    row = database.insert_model_promotion(
        surface=surface, candidate_model=candidate, previous_model=previous or None,
        run_id=report.get("run_id"), evaluation_report_id=str(evaluation_report_id),
        promoted_by=str(by), promoted_at=now.isoformat())
    _clear_cache()
    return {"surface": surface, "model": candidate, "previous": previous,
            "promotion_id": (row or {}).get("id")}


def _refuse_unless_current(database: Any, run_id: str, report: dict) -> None:
    """The run behind the report has not failed, and nobody withdrew (or was
    deleted) since the report was written. Read live; unreadable refuses."""
    from services.model_training import report_is_fresh, withdrawn_basis
    try:
        run = database.get_fine_tune_run(run_id)
        basis = withdrawn_basis(database, run_id)
    except Exception as e:  # noqa: BLE001 -- fail closed, named
        _log.warning("promotion freshness unreadable run=%s: %s", run_id, e, exc_info=True)
        raise PromotionRefusal(
            "whose training yes this candidate rests on could not be read now; nothing was promoted",
            "REPORT_FRESHNESS_UNKNOWN") from e
    if not isinstance(run, dict):
        raise PromotionRefusal("the report names a run that cannot be found", "RUN_UNKNOWN")
    if run.get("status") == "failed":
        raise PromotionRefusal(
            "this candidate's run failed (a failed regurgitation check is final); "
            "the next run trains only on pairs no run has trained on", "RUN_FAILED")
    if not report_is_fresh(report, basis):
        raise PromotionRefusal(
            "a speaker withdrew or was deleted after this evaluation, so it checked the wrong "
            "texts; the weekly job evaluates the candidate again, promote from that report",
            "REPORT_STALE")


def kill(database: Any, *, surface: str, by: str, reason: str,
         now: Optional[datetime] = None) -> dict:
    """Back to the stock model, door or no door."""
    if surface not in SURFACES:
        raise PromotionRefusal(f"{surface} is not a pair surface any door knows", "UNKNOWN_SURFACE")
    now = now or datetime.now(timezone.utc)
    stock = stock_model()
    written = database.promote_runtime_surface_model(
        key=_key(surface), value=stock, updated_by=str(by),
        metadata={"prompt_lock_sha256": _prompt_lock(surface), "kill": True,
                  "reason": str(reason)[:200], "killed_at": now.isoformat()})
    if written is None:
        raise PromotionRefusal("the promote RPC is absent", "RPC_MISSING")
    database.kill_model_promotions(surface=surface, killed_by=str(by),
                                   kill_reason=str(reason)[:200], killed_at=now.isoformat())
    _clear_cache()
    return {"surface": surface, "model": stock, "killed": True}


def _clear_cache() -> None:
    try:
        from services.ml_surface_contracts import clear_runtime_model_cache
        clear_runtime_model_cache()
    except Exception as e:  # noqa: BLE001 -- the cache expires in a minute anyway
        _log.info("runtime model cache not cleared: %s", e)
