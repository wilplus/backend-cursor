"""The research screen's one read (founder 2026-09-30, L4 to L9; build plan
ML-7). What the data scientist sees: datasets per surface, the label
quorum, the exclusions, the exports, the evaluations, the promotions, the
drift and the monitors, and the golden set. Every panel whose door is
closed says so in words rather than showing a zero that looks like a
measurement. Pseudonyms only; no row here names a person.

Read-only, for the research role and the founder; the routes gate it.
"""
from __future__ import annotations

import logging
from typing import Any, Callable

_log = logging.getLogger(__name__)

VIEW_VERSION = "research-view-v1"


def _read(name: str, reader: Callable[[], Any], unavailable: list[str]) -> Any:
    try:
        return reader()
    except Exception as e:  # noqa: BLE001 -- named, never read as zero
        _log.warning("research source %s unavailable: %s", name, e, exc_info=True)
        unavailable.append(name)
        return None


def _datasets(ledger: dict, releases: Any, doors: dict) -> dict:
    """Per pair surface: how many pairs exist, and what a release would
    need. The consent-authorised share waits on door 1 (the training yes);
    splits exist only once a release exists."""
    consent_open = bool((doors.get("consent") or {}).get("open"))
    release_open = bool((doors.get("dataset_release") or {}).get("open"))
    out = {}
    for surface, entry in (ledger.get("pairs") or {}).items():
        out[surface] = {
            "pairs": int((entry or {}).get("total") or 0),
            "unexported": int((entry or {}).get("unexported") or 0),
            "consent_authorised_share": None,
            "consent_note": (None if consent_open
                             else "door 1 closed: no training yes exists yet, so no pair is releasable"),
            "releases": [r for r in (releases or []) if isinstance(r, dict)
                         and r.get("learning_surface") == surface],
            "splits": None,
            "splits_note": (None if release_open
                            else "door 2 closed: splits are assigned at release (80/10/10, speaker-disjoint)"),
        }
    return out


def _promotions(database: Any) -> list[dict]:
    """Which model each contract surface serves today (the runtime row is
    the present); the history is ``model_promotions`` (door 4, ML-12)."""
    from services.ml_surface_contracts import SURFACES
    out = []
    for surface_id, contract in SURFACES.items():
        value = database.get_runtime_config(contract.runtime_config_key)
        out.append({"surface": surface_id, "key": contract.runtime_config_key,
                    "model": value, "note": None if value else "stock model (never promoted)"})
    return out


def _evaluations(database: Any, doors: dict) -> dict:
    reports = [r for r in (database.list_evaluation_reports(limit=20) or []) if isinstance(r, dict)]
    rows = [{"surface": r.get("surface"), "candidate_model": r.get("candidate_model"),
             "baseline_model": r.get("baseline_model"), "passed": r.get("passed"),
             "golden_count": r.get("golden_count"), "created_at": r.get("created_at"),
             "candidate_mean_f1": (r.get("report") or {}).get("candidate_mean_f1"),
             "baseline_mean_f1": (r.get("report") or {}).get("baseline_mean_f1"),
             "regurgitation_ok": ((r.get("report") or {}).get("regurgitation") or {}).get("ok"),
             "id": r.get("id")} for r in reports]
    training_open = bool((doors.get("training") or {}).get("open"))
    return {"reports": rows,
            "note": (None if rows else
                     "no candidate has been evaluated yet" if training_open else
                     "door 3 closed: no candidate has been evaluated; a report appears when a run finishes")}


def _training(database: Any) -> dict:
    runs = [r for r in (database.list_fine_tune_runs(limit=20) or []) if isinstance(r, dict)]
    return {"runs": [{"surface": r.get("surface"), "status": r.get("status"),
                      "item_count": r.get("item_count"), "candidate_model": r.get("candidate_model"),
                      "started_at": r.get("started_at"), "finished_at": r.get("finished_at"),
                      "files_deleted_at": r.get("files_deleted_at"),
                      "withdrawn_at": r.get("withdrawn_at"), "id": r.get("id")} for r in runs],
            "note": None if runs else "no fine-tune has run"}


def _promotion_history(database: Any) -> list[dict]:
    rows = [r for r in (database.list_model_promotions(limit=20) or []) if isinstance(r, dict)]
    return [{"surface": r.get("surface"), "candidate_model": r.get("candidate_model"),
             "previous_model": r.get("previous_model"), "promoted_by": r.get("promoted_by"),
             "promoted_at": r.get("promoted_at"), "killed_at": r.get("killed_at"),
             "kill_reason": r.get("kill_reason")} for r in rows]


def _sources(database: Any, config: Any, unavailable: list[str]) -> dict:
    """Every read the view makes, each named when it cannot be made."""
    from services.learning_ledger import ledger as read_ledger
    from services.golden_set import SURFACES as GOLDEN_SURFACES, counts as golden_counts
    ledger = _read("ledger", lambda: read_ledger(database, config=config), unavailable) or {}
    doors = ledger.get("doors") or {}
    golden = {}
    for surface in GOLDEN_SURFACES:
        def _count(s: str = surface) -> dict:
            return golden_counts(database, surface=s)
        golden[surface] = _read(f"golden.{surface}", _count, unavailable)
    return {
        "ledger": ledger, "doors": doors, "golden": golden,
        "releases": _read("releases", lambda: database.list_dataset_releases(), unavailable) or [],
        "labels": _read("labels", lambda: database.get_confidence_label_corpus(limit=5000), unavailable) or [],
        "exclusions": _read("exclusions", lambda: database.list_dataset_exclusions(), unavailable) or [],
        "exports": _read("exports", lambda: database.list_annotation_export_runs(limit=20), unavailable) or [],
        "promotions": _read("promotions", lambda: _promotions(database), unavailable) or [],
        "snapshots": _read("snapshots", lambda: database.list_ledger_snapshots(limit=8), unavailable) or [],
        "pair_releases": _read("pair_releases", lambda: database.list_pair_releases(limit=20), unavailable) or [],
        "evaluations": (_read("evaluations", lambda: _evaluations(database, doors), unavailable)
                        or {"reports": [], "note": "evaluation reports unreadable"}),
        "training": (_read("training", lambda: _training(database), unavailable)
                     or {"runs": [], "note": "fine-tune runs unreadable"}),
        "history": _read("promotion_history", lambda: _promotion_history(database), unavailable) or [],
    }


def _exports_panel(exports: list, pair_releases: list) -> dict:
    return {
        "annotation_runs": [
            {"started_at": r.get("started_at"), "status": r.get("status"),
             "exported_count": r.get("exported_count"), "export_uri": r.get("export_uri")}
            for r in exports if isinstance(r, dict)],
        "pair_exports": [
            {"surface": r.get("surface"), "week_start": r.get("week_start"),
             "item_count": r.get("item_count"), "manifest_sha256": r.get("manifest_sha256"),
             "file_sha256": r.get("file_sha256"), "storage_key": r.get("storage_key"),
             "exported_at": r.get("exported_at"), "voided_at": r.get("voided_at"),
             "voided_reason": r.get("voided_reason"), "purged_at": r.get("purged_at")}
            for r in pair_releases if isinstance(r, dict)],
        "note": (None if pair_releases else
                 "door 2 closed: no pair release has run; a release needs the door open in code "
                 "and the founder's sentence per surface. The annotation runs above are the retired daily export"),
    }


def overview(database: Any, *, config: Any = None) -> dict:
    from services.research_quorum import quorum
    if config is None:
        from config import Config
        config = Config()
    unavailable: list[str] = []
    src = _sources(database, config, unavailable)
    by_reason: dict[str, int] = {}
    for row in src["exclusions"]:
        if isinstance(row, dict):
            key = str(row.get("reason_code") or "unspecified")
            by_reason[key] = by_reason.get(key, 0) + 1
    return {
        "view_version": VIEW_VERSION,
        "datasets": _datasets(src["ledger"], src["releases"], src["doors"]),
        "labels": quorum(src["labels"]),
        "exclusions": {"by_reason": by_reason,
                       "note": None if src["exclusions"] else "no release yet, so no exclusion was decided"},
        "exports": _exports_panel(src["exports"], src["pair_releases"]),
        "evaluations": src["evaluations"],
        "training": src["training"],
        "promotions": src["promotions"],
        "promotion_history": src["history"],
        "drift": {"last": None, "note": "the weekly drift run stores no rows yet; its verdicts reach Sentry only"},
        "monitors": {"last": None, "note": "the readiness monitors write to Sentry, not to a table"},
        "golden": src["golden"],
        "weekly": [{"week_start": s.get("week_start"), "ready_cues": s.get("ready_cues"),
                    "updated_at": s.get("updated_at")} for s in src["snapshots"] if isinstance(s, dict)],
        "doors": src["doors"],
        "unavailable": unavailable,
    }
