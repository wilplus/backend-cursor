"""Door 3: a fine-tune at 200 (founder 2026-09-30, L7; counsel 2026-10-01;
build plan ML-11). Built with the door closed.

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
    promoted — a failing one is retrained without those pairs.

Nothing here promotes. AC-9: counts about the machine, never a person.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from services.feedback_pairs import SURFACES

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


def split_examples(pairs: list[dict]) -> dict:
    """{train: [...], validation: [...], held_out: n, skipped: n} by owner
    principal, speaker-disjoint; the test bucket never trains."""
    from services.dataset_releases import speaker_split
    out: dict[str, Any] = {"train": [], "validation": [], "held_out": 0, "skipped": 0,
                           "train_pairs": [], "validation_pairs": []}
    for pair in pairs:
        example = example_for(pair)
        owner = str(pair.get("owner_principal_id") or "")
        if example is None or not owner:
            out["skipped"] += 1
            continue
        split, _ = speaker_split(owner)
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
    split = split_examples(pairs)
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


def _evaluate(database: Any, run: dict, candidate: str, config: Any) -> dict:
    from services.golden_evaluation import EvaluationRefusal, GoldenRefusal, evaluate
    from services.llm_config import SPEC_COACH_ANSWER_DRAFT
    rid = str(run.get("id") or "")
    try:
        texts = database.list_trained_texts(rid) or {}
        report = evaluate(
            database, surface=str(run.get("surface")), candidate_model=candidate,
            baseline_model=str(getattr(SPEC_COACH_ANSWER_DRAFT, "model", "") or "stock"),
            run_id=rid, withdrawn_texts=list(texts.get("withdrawn") or []),
            trained_texts=list(texts.get("trained") or []))
        return {"passed": bool(report.get("passed")), "report_id": report.get("id")}
    except (EvaluationRefusal, GoldenRefusal) as refusal:
        return {"passed": False, "why": refusal.message}
    except Exception as e:  # noqa: BLE001 -- named; the run row stands
        _log.warning("golden evaluation failed run=%s: %s", rid, e, exc_info=True)
        return {"passed": False, "why": f"evaluation failed: {str(e)[:120]}"}


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
    """The weekly step: sweep withdrawals, poll running jobs, start what
    may start. Each part reports in words."""
    provider = provider or OpenAIFineTuning(config)
    swept = sweep_withdrawn(database, provider, now=now)
    polled = poll_runs(database, provider, config=config, now=now) \
        if hasattr(database, "list_fine_tune_runs") else []
    started = [start_run(database, provider, surface=s, config=config, now=now)
               for s in sorted(SURFACES)]
    return {"withdrawn_sweep": swept, "polled": polled, "surfaces": started}


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
