"""Door 3: a fine-tune at 200 (founder 2026-09-30, L7; counsel 2026-10-01;
build plan ML-11). Built with the door closed; door 3 OPEN since 2026-10-08
for exercise_script, praise_line and clearer_version (founder: "turn it all
ON"), held behind Privacy and Terms 3.5 publication.

Once a week, after the export and the sweep (services.learning_weekly):

  * a surface may train only when ``MLC2_TRAINING_ENABLED`` is True AND
    the founder named it (``Config.TRAINING_SURFACES``, "open door 3 for
    surface S"), the key is set, and its golden set is sealed (ML-10);
    every other surface reports why it waited, in words;
  * the examples are pairs that LEFT through door 2 (``release_id``), are
    still releasable when the run starts (exclusion at run start: a
    withdrawal between the release and the run keeps the pair out), carry
    their passage, and were never trained on (a pair trains once,
    ``mark_feedback_pairs_trained_v1``); a run needs PAIRS_PER_RUN of them;
  * the file is the serving prompt, example for example (system, user,
    assistant = the coach's final), split speaker-disjoint by owner
    principal: train / validation, the test bucket held out entirely;
  * the job is one OpenAI fine-tune; the run row remembers the file, the
    job and whose passages it learned from (``fine_tune_run_owners``);
  * the poll reads the job each week: a finished job gets its files
    deleted at the provider, a succeeded one its candidate id and the
    golden evaluation (services.golden_evaluation), whose report is a row;
  * the withdrawal sweep (counsel): a run with an owner who withdrew has
    its files deleted at the provider at once and a still-running job
    cancelled; a model already trained stays, marked withdrawn-from, and
    the evaluation's regurgitation check decides whether it may ever be
    promoted;
  * a report is fresh only while the withdrawn owners it checked are the
    withdrawn owners NOW (``withdrawn_basis``, read live from the yes in
    force): a withdrawal or a deletion after an evaluation makes the report
    stale, promotion refuses it (services.model_promotion), and the weekly
    pass evaluates the candidate again (``reevaluate_stale``);
  * "retrained without the withdrawn pairs", made consistent with "a pair
    trains once" (audit DOOR-3-RETRAIN): a candidate that fails the
    regurgitation check is marked failed for good (never promoted, never
    evaluated again, its pairs never train again); the retraining is the
    NEXT run, under the same door rules, built only from still-releasable
    pairs no run has trained on, which by construction holds no withdrawn
    pair. Whether a failed run's clean pairs may train a second time is the
    founder's decision, not this module's.

Nothing here promotes. AC-9: counts about the machine, never a person.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from services.feedback_pairs import ANSWER_SURFACES as SURFACES

_log = logging.getLogger(__name__)

RUN_VERSION = "fine-tune-run-v1"
PAIRS_PER_RUN = 200
TERMINAL = ("succeeded", "failed", "cancelled")


def door_open(config: Any) -> bool:
    return bool(getattr(config, "MLC2_TRAINING_ENABLED", False))


def authorised_surfaces(config: Any) -> frozenset:
    if not door_open(config):
        return frozenset()
    named: Any = getattr(config, "TRAINING_SURFACES", frozenset()) or frozenset()
    return frozenset(s for s in named if s in SURFACES)


def why_not(config: Any, surface: str) -> Optional[str]:
    """None when the surface may train; else the reason, in words."""
    if not door_open(config):
        return "door 3 closed (MLC2_TRAINING_ENABLED)"
    if surface not in authorised_surfaces(config):
        return "door 3 open, but no founder sentence for this surface yet (TRAINING_SURFACES)"
    if not (getattr(config, "OPENAI_API_KEY", "") or "").strip():
        return "no OpenAI key (OPENAI_API_KEY)"
    return None


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def example_for(pair: dict) -> Optional[dict]:
    """One chat-format training example, the serving prompt verbatim, or
    None when the pair cannot be prompted (no passage)."""
    from services.coach_request_drafts import _SYSTEM
    from services.prompts.coach_answer_drafts import user as user_prompt
    surface = str(pair.get("surface") or "")
    passage = " ".join(str(pair.get("passage_text") or "").split())
    final = str(pair.get("final_text") or "").strip()
    system = _SYSTEM.get(surface)
    if not passage or not final or system is None:
        return None
    context = pair.get("prompt_context") or {}
    kind = str(context.get("kind") or {"exercise_script": "error", "praise_line": "praise",
                                       "clearer_version": "rewrite"}[surface])
    spotted = [str(context.get("pattern_key"))] if context.get("pattern_key") else []
    return {"messages": [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt(surface=surface, passage=passage,
                                                spotted=spotted, kind=kind)},
        {"role": "assistant", "content": final},
    ]}


def split_examples(pairs: list[dict], splits: Optional[dict] = None,
                   sources: Optional[dict] = None) -> dict:
    """{train: [...], validation: [...], held_out: n, skipped: n},
    speaker-disjoint by the split door 2 released each pair under
    (services/speaker_split.py, F-3). With ``sources`` (each release's
    ``split_source``, which start_run reads), a pair takes exactly its
    release's split and is skipped when that cannot be known; without, the
    owner's speaker assignment or the owner-principal hash. The test bucket
    never trains."""
    from services.speaker_split import released_split, split_for
    out: dict[str, Any] = {"train": [], "validation": [], "held_out": 0, "skipped": 0,
                           "train_pairs": [], "validation_pairs": []}
    for pair in pairs:
        example = example_for(pair)
        owner = str(pair.get("owner_principal_id") or "")
        if example is None or not owner:
            out["skipped"] += 1
            continue
        if sources is not None:
            known = released_split(pair, splits or {}, sources)
            if known is None:
                out["skipped"] += 1
                continue
            split = known
        else:
            split, _ = split_for(owner, splits or {})
        if split == "train":
            out["train"].append(example)
            out["train_pairs"].append(pair)
        elif split == "validation":
            out["validation"].append(example)
            out["validation_pairs"].append(pair)
        else:
            out["held_out"] += 1
    return out


def jsonl(examples: list[dict]) -> bytes:
    return ("\n".join(_json(e) for e in examples) + "\n").encode("utf-8") if examples else b""


def trainable_pairs(database: Any, surface: str) -> list[dict]:
    """Released, still releasable, never trained, with a passage. Read at
    run start, so a withdrawal since the release keeps the pair out."""
    lister = getattr(database, "list_trainable_pairs", None)
    if lister is None:
        return []
    return [p for p in (lister(surface, limit=5000) or [])
            if isinstance(p, dict) and p.get("releasable") is True
            and p.get("release_id") and not p.get("trained_run_id")
            and str(p.get("passage_text") or "").strip()]


def start_run(database: Any, provider: Any, *, surface: str, config: Any,
              now: Optional[datetime] = None) -> dict:
    """One surface, one week: start a run or say why not."""
    now = now or datetime.now(timezone.utc)
    reason = why_not(config, surface)
    if reason:
        waiting = len(trainable_pairs(database, surface)) if hasattr(database, "list_trainable_pairs") else None
        return {"surface": surface, "started": False, "waiting": waiting, "why": reason}
    from services.golden_set import GoldenRefusal, sealed_rows
    try:
        sealed_rows(database, surface=surface)
    except GoldenRefusal as refusal:
        return {"surface": surface, "started": False, "why": refusal.message}
    pairs = trainable_pairs(database, surface)
    if len(pairs) < PAIRS_PER_RUN:
        return {"surface": surface, "started": False, "waiting": len(pairs),
                "why": f"{len(pairs)} of {PAIRS_PER_RUN} trainable pairs"}
    from services.speaker_split import release_split_sources, speaker_splits
    split = split_examples(
        pairs, speaker_splits(database, [p.get("owner_principal_id") for p in pairs]),
        release_split_sources(database, [p.get("release_id") for p in pairs]))
    if len(split["train"]) < PAIRS_PER_RUN // 2:
        return {"surface": surface, "started": False, "waiting": len(pairs),
                "why": f"only {len(split['train'])} examples fall in the training split"}
    train_bytes = jsonl(split["train"])
    val_bytes = jsonl(split["validation"])
    used = split["train_pairs"] + split["validation_pairs"]
    owners = sorted({str(p.get("owner_principal_id")) for p in used})
    base = str(getattr(config, "OPENAI_FINE_TUNE_BASE_MODEL", "") or "").strip()
    file_id = provider.upload(f"willab-{surface}-train.jsonl", train_bytes)
    val_id = provider.upload(f"willab-{surface}-validation.jsonl", val_bytes) if val_bytes else None
    job = provider.create_job(base_model=base, training_file=file_id,
                              validation_file=val_id, suffix=f"willab-{surface}")
    run = database.insert_fine_tune_run(
        run_version=RUN_VERSION, surface=surface, base_model=base, status="running",
        item_count=len(used), train_count=len(split["train"]),
        validation_count=len(split["validation"]),
        file_sha256=hashlib.sha256(train_bytes).hexdigest(),
        owners_sha256=hashlib.sha256("\n".join(owners).encode("utf-8")).hexdigest(),
        prompt_lock_sha256=_prompt_lock(surface),
        openai_file_id=file_id, openai_validation_file_id=val_id,
        openai_job_id=str(job.get("id") or ""), started_at=now.isoformat())
    run_id = str((run or {}).get("id") or "")
    database.insert_fine_tune_run_owners(run_id, owners)
    marked = database.mark_feedback_pairs_trained(run_id, [str(p["id"]) for p in used])
    return {"surface": surface, "started": True, "run_id": run_id,
            "job_id": str(job.get("id") or ""), "trained": int(marked),
            "held_out": split["held_out"], "skipped": split["skipped"]}


def _prompt_lock(surface: str) -> Optional[str]:
    try:
        from services.ml_surface_contracts import locked_prompt_hash
        return locked_prompt_hash(surface)
    except Exception as e:  # noqa: BLE001 -- a record, not a gate
        _log.info("prompt lock unavailable for %s: %s", surface, e)
        return None


def _delete_files(provider: Any, database: Any, run: dict, now: datetime) -> None:
    for key in ("openai_file_id", "openai_validation_file_id"):
        file_id = str(run.get(key) or "")
        if file_id:
            provider.delete_file(file_id)
    database.update_fine_tune_run(str(run["id"]), files_deleted_at=now.isoformat())


def poll_runs(database: Any, provider: Any, *, config: Any,
              now: Optional[datetime] = None) -> list[dict]:
    """Read every running job; finish the finished; evaluate the succeeded."""
    now = now or datetime.now(timezone.utc)
    out = []
    for run in database.list_fine_tune_runs(status="running") or []:
        if not isinstance(run, dict):
            continue
        rid = str(run.get("id") or "")
        try:
            job = provider.get_job(str(run.get("openai_job_id") or ""))
        except Exception as e:  # noqa: BLE001 -- named, retried next week
            _log.warning("fine-tune poll failed run=%s: %s", rid, e, exc_info=True)
            out.append({"run_id": rid, "status": "running", "why": f"poll failed: {str(e)[:120]}"})
            continue
        status = str(job.get("status") or "")
        if status not in TERMINAL:
            out.append({"run_id": rid, "status": "running", "provider_status": status})
            continue
        fields: dict[str, Any] = {"status": status, "finished_at": now.isoformat()}
        if status == "succeeded":
            fields["candidate_model"] = str(job.get("fine_tuned_model") or "")
        else:
            fields["failure"] = str((job.get("error") or {}).get("message") or status)[:500]
        database.update_fine_tune_run(rid, **fields)
        if not run.get("files_deleted_at"):
            _delete_files(provider, database, run, now)
        row: dict[str, Any] = {"run_id": rid, "surface": run.get("surface"), "status": status}
        if status == "succeeded" and fields.get("candidate_model"):
            row["evaluation"] = _evaluate(database, run, fields["candidate_model"], config)
        out.append(row)
    return out


def withdrawn_basis(database: Any, run_id: str) -> dict:
    """Whose texts a regurgitation check of this run must cover NOW
    (counsel 2026-10-01; audit DOOR-4-WITHDRAWN): the run's owners whose
    training yes is not in force at this moment (the active-grants view,
    read live, so a withdrawal counts the moment it is recorded, not at the
    next weekly sweep), or whose pairs the refresh or a deletion request
    made not releasable. Returns the texts the check searches and a digest
    of that owner set, which the report keeps: a report is fresh only while
    the set it checked is the set that holds now. Raises when it cannot be
    read; a caller that gates on it fails closed."""
    pairs = [p for p in (database.list_trained_pairs(str(run_id)) or []) if isinstance(p, dict)]
    owners = sorted({str(p.get("owner_principal_id")) for p in pairs if p.get("owner_principal_id")})
    active = ({str(r.get("acquisition_principal_id"))
               for r in (database.list_active_training_grants(owners) or []) if isinstance(r, dict)}
              if owners else set())
    gone = {o for o in owners if o not in active}
    gone |= {str(p["owner_principal_id"]) for p in pairs
             if p.get("owner_principal_id") and p.get("releasable") is not True}
    trained: list[str] = []
    withdrawn: list[str] = []
    for pair in pairs:
        texts = [str(t) for t in (pair.get("passage_text"), pair.get("final_text")) if t]
        trained.extend(texts)
        if str(pair.get("owner_principal_id") or "") in gone or pair.get("releasable") is not True:
            withdrawn.extend(texts)
    return {"owners_sha256": hashlib.sha256("\n".join(sorted(gone)).encode("utf-8")).hexdigest(),
            "owners": len(gone), "withdrawn_texts": withdrawn, "trained_texts": trained}


def report_is_fresh(report: Any, basis: dict) -> bool:
    """A report speaks for its candidate only while the withdrawn owners it
    checked are the withdrawn owners now. A withdrawal (or a deletion, or a
    renewed yes) after the evaluation makes it STALE: promotion refuses it
    and the weekly pass evaluates again. A report written before the digest
    existed is fresh only while nobody has withdrawn."""
    body = (report or {}).get("report") if isinstance(report, dict) else None
    regurgitation = (body or {}).get("regurgitation") if isinstance(body, dict) else None
    digest = (regurgitation or {}).get("withdrawn_owners_sha256") if isinstance(regurgitation, dict) else None
    if not digest:
        return int(basis.get("owners") or 0) == 0
    return str(digest) == str(basis.get("owners_sha256"))


#: The words a run carries once its candidate failed the regurgitation check
#: (DOOR-3-RETRAIN). Final: the candidate is never promoted, never evaluated
#: again, and its pairs never train again (a pair trains once); "retrained
#: without the withdrawn pairs" is the NEXT run, under the same door rules,
#: built only from still-releasable pairs no run has trained on.
REGURGITATION_FAILURE = (
    "regurgitation check failed: the candidate reproduced a withdrawn speaker's "
    "text, so it is never promoted; the next run trains only on pairs no run "
    "has trained on (a pair trains once)")


def _mark_regurgitated(database: Any, run_id: str) -> None:
    """Failed for good. ``finished_at`` keeps when the provider's job ended."""
    database.update_fine_tune_run(str(run_id), status="failed", failure=REGURGITATION_FAILURE)


def _evaluate(database: Any, run: dict, candidate: str, config: Any) -> dict:
    from services.golden_evaluation import EvaluationRefusal, GoldenRefusal, evaluate
    from services.llm_config import SPEC_COACH_ANSWER_DRAFT
    rid = str(run.get("id") or "")
    try:
        basis = withdrawn_basis(database, rid)
        report = evaluate(
            database, surface=str(run.get("surface")), candidate_model=candidate,
            baseline_model=str(getattr(SPEC_COACH_ANSWER_DRAFT, "model", "") or "stock"),
            run_id=rid, withdrawn_texts=basis["withdrawn_texts"],
            trained_texts=basis["trained_texts"],
            withdrawn_basis={"owners_sha256": basis["owners_sha256"], "owners": basis["owners"]})
    except (EvaluationRefusal, GoldenRefusal) as refusal:
        return {"passed": False, "why": refusal.message}
    except Exception as e:  # noqa: BLE001 -- named; the run row stands
        _log.warning("golden evaluation failed run=%s: %s", rid, e, exc_info=True)
        return {"passed": False, "why": f"evaluation failed: {str(e)[:120]}"}
    out: dict[str, Any] = {"passed": bool(report.get("passed")), "report_id": report.get("id")}
    regurgitation = (report.get("report") or {}).get("regurgitation") or {}
    if regurgitation.get("ok") is False:
        _mark_regurgitated(database, rid)
        out.update(run_failed=True, why=REGURGITATION_FAILURE)
    return out


def reevaluate_stale(database: Any, *, config: Any,
                     skip: frozenset = frozenset()) -> list[dict]:
    """The weekly re-evaluation (DOOR-4-WITHDRAWN): every succeeded run whose
    newest report no longer speaks for it (a withdrawal or a deletion since,
    or no report yet) is evaluated again against the owners withdrawn NOW.
    A failing regurgitation check marks the run failed for good
    (DOOR-3-RETRAIN). Runs whatever the doors say: it can only stop a
    promotion, never start one. A candidate served right now that fails is
    named loudly; killing it is the founder's hand (scripts/promote_pair_surface.py)."""
    out: list[dict] = []
    for run in database.list_fine_tune_runs(status="succeeded", limit=50) or []:
        if not isinstance(run, dict) or not run.get("candidate_model"):
            continue
        rid = str(run.get("id") or "")
        if rid in skip:
            continue
        try:
            basis = withdrawn_basis(database, rid)
            latest = database.get_latest_evaluation_report(rid)
        except Exception as e:  # noqa: BLE001 -- named; promotion refuses meanwhile
            _log.warning("freshness read failed run=%s: %s", rid, e, exc_info=True)
            out.append({"run_id": rid, "surface": run.get("surface"),
                        "why": f"freshness unreadable: {str(e)[:120]}"})
            continue
        if isinstance(latest, dict) and report_is_fresh(latest, basis):
            continue
        candidate = str(run["candidate_model"])
        row: dict[str, Any] = {"run_id": rid, "surface": run.get("surface"),
                               "reevaluated": True,
                               **_evaluate(database, run, candidate, config)}
        if row.get("run_failed") and _served_now(database, str(run.get("surface") or ""), candidate):
            row["served_now"] = True
            row["why"] = (REGURGITATION_FAILURE + ". THIS CANDIDATE IS SERVED NOW: the founder "
                          "kills it with scripts/promote_pair_surface.py kill")
        out.append(row)
    return out


def _served_now(database: Any, surface: str, candidate: str) -> bool:
    try:
        from services.ml_surface_contracts import runtime_config_key
        return str(database.get_runtime_config(runtime_config_key(surface)) or "") == candidate
    except Exception as e:  # noqa: BLE001 -- unknown reads as served: the loud side
        _log.warning("served model read failed surface=%s: %s", surface, e)
        return True


def sweep_withdrawn(database: Any, provider: Any, *,
                    now: Optional[datetime] = None) -> dict:
    """Counsel's reach: a run with a withdrawn owner loses its files at the
    provider now and its job if still running. Runs every week whatever
    the door says."""
    now = now or datetime.now(timezone.utc)
    lister = getattr(database, "list_fine_tune_runs_with_withdrawn_owner", None)
    if lister is None:
        return {"swept": 0, "unavailable": "no run ledger on this database"}
    try:
        due = lister() or []
    except Exception as e:  # noqa: BLE001 -- named, never a silent zero
        _log.warning("withdrawn run read failed: %s", e, exc_info=True)
        return {"swept": 0, "unavailable": str(e)[:200]}
    swept, failed = 0, []
    for run in due:
        if not isinstance(run, dict):
            continue
        rid = str(run.get("run_id") or run.get("id") or "")
        try:
            fields: dict[str, Any] = {}
            if not run.get("withdrawn_at"):
                fields.update(withdrawn_at=now.isoformat(), withdrawn_reason="consent_withdrawn")
            if run.get("status") == "running" and run.get("openai_job_id"):
                provider.cancel_job(str(run["openai_job_id"]))
                fields.update(status="withdrawn", finished_at=now.isoformat())
            if not run.get("files_deleted_at"):
                for key in ("openai_file_id", "openai_validation_file_id"):
                    if run.get(key):
                        provider.delete_file(str(run[key]))
                fields["files_deleted_at"] = now.isoformat()
            if fields:
                database.update_fine_tune_run(rid, **fields)
                swept += 1
        except Exception as e:  # noqa: BLE001 -- the next sweep retries
            _log.warning("withdrawn run %s not swept: %s", rid, e, exc_info=True)
            failed.append(rid)
    return {"swept": swept, "failed": failed}


def run_training_pass(database: Any, *, config: Any, provider: Any = None,
                      now: Optional[datetime] = None) -> dict:
    """The weekly step: sweep withdrawals, poll running jobs, evaluate again
    every candidate whose report went stale, start what may start. Each
    part reports in words."""
    provider = provider or OpenAIFineTuning(config)
    swept = sweep_withdrawn(database, provider, now=now)
    has_runs = hasattr(database, "list_fine_tune_runs")
    polled = poll_runs(database, provider, config=config, now=now) if has_runs else []
    # A run the poll just evaluated holds a fresh report (or a refusal the
    # poll already named): not twice in one pass.
    just = frozenset(str(r.get("run_id")) for r in polled if isinstance(r, dict))
    reevaluated = reevaluate_stale(database, config=config, skip=just) if has_runs else []
    started = [start_run(database, provider, surface=s, config=config, now=now)
               for s in sorted(SURFACES)]
    return {"withdrawn_sweep": swept, "polled": polled, "reevaluated": reevaluated,
            "surfaces": started}


class OpenAIFineTuning:
    """The provider's five verbs, on the official client, built lazily."""

    def __init__(self, config: Any):
        self._config = config
        self._client = None

    def client(self) -> Any:
        if self._client is None:
            from services.llm_client import build_openai_client
            self._client = build_openai_client(
                getattr(self._config, "OPENAI_API_KEY", ""), timeout=120, max_retries=2)
        return self._client

    def upload(self, name: str, body: bytes) -> str:
        created = self.client().files.create(file=(name, body), purpose="fine-tune")
        return str(getattr(created, "id", "") or "")

    def create_job(self, *, base_model: str, training_file: str,
                   validation_file: Optional[str], suffix: str) -> dict:
        kwargs: dict[str, Any] = {"model": base_model, "training_file": training_file,
                                  "suffix": suffix[:18]}
        if validation_file:
            kwargs["validation_file"] = validation_file
        job = self.client().fine_tuning.jobs.create(**kwargs)
        return {"id": getattr(job, "id", None), "status": getattr(job, "status", None)}

    def get_job(self, job_id: str) -> dict:
        job = self.client().fine_tuning.jobs.retrieve(job_id)
        error = getattr(job, "error", None)
        return {"id": getattr(job, "id", None), "status": getattr(job, "status", None),
                "fine_tuned_model": getattr(job, "fine_tuned_model", None),
                "error": {"message": getattr(error, "message", None)} if error else None}

    def cancel_job(self, job_id: str) -> None:
        self.client().fine_tuning.jobs.cancel(job_id)

    def delete_file(self, file_id: str) -> None:
        self.client().files.delete(file_id)
