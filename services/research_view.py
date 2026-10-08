"""The research screen's one read (founder 2026-09-30, L4 to L9; build plan
ML-7). What the data scientist sees: datasets per surface, the label
quorum, the exclusions, the exports, the evaluations, the promotions, the
drift and the monitors, and the golden set. Every panel whose door is
closed says so in words rather than showing a zero that looks like a
measurement. Pseudonyms only; no row here names a person.

  * datasets: per pair surface, the pairs, the drafts shown (exposures),
    the CONSENT-AUTHORISED SHARE (pairs whose speaker's training yes is in
    force, over all pairs) and the SPLITS the releases assigned (train,
    validation, test, speaker-disjoint 80/10/10, summed from the signed
    manifests of the releases still standing);
  * drift: the weekly PSI 2x2 (PM-3) as the weekly learning job stored it
    with its newest week, most urgent dimension first;
  * monitors: the confidence readiness monitor's checks, read NOW from the
    database the way the five-minute cron reads them (aggregate counts and
    codes only). Whether that cron has its own switch and Sentry is read on
    the cron service and is not judged here.

Read-only, for the research role and the founder; the routes gate it.
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)

VIEW_VERSION = "research-view-v1"


def _read(name: str, reader: Callable[[], Any], unavailable: list[str]) -> Any:
    try:
        return reader()
    except Exception as e:  # noqa: BLE001 -- named, never read as zero
        _log.warning("research source %s unavailable: %s", name, e, exc_info=True)
        unavailable.append(name)
        return None


def _splits(releases: list) -> Optional[dict]:
    """Train, validation and test counts summed over the releases still
    standing (voided ones left out), from their signed manifests. None
    when no release stands."""
    standing = [r for r in releases if isinstance(r, dict) and not r.get("voided_at")]
    if not standing:
        return None
    out = {"train": 0, "validation": 0, "test": 0}
    for release in standing:
        counts = ((release.get("manifest") or {}).get("split_counts") or {}) \
            if isinstance(release.get("manifest"), dict) else {}
        for split in out:
            value = counts.get(split)
            out[split] += int(value) if isinstance(value, int) and not isinstance(value, bool) else 0
    return out


def _datasets(ledger: dict, releases: Any, doors: dict) -> dict:
    """Per pair surface: the pairs, the drafts shown, the consent-authorised
    share and the splits its releases assigned, each with the words for
    why it is missing when it is."""
    consent_open = bool((doors.get("consent") or {}).get("open"))
    release_door = doors.get("dataset_release") or {}
    release_open = bool(release_door.get("open"))
    named = set(release_door.get("surfaces") or ())
    out = {}
    for surface, raw in (ledger.get("pairs") or {}).items():
        entry = raw if isinstance(raw, dict) else {}
        total = int(entry.get("total") or 0)
        releasable = int(entry.get("releasable") or 0)
        mine = [r for r in (releases or []) if isinstance(r, dict) and r.get("surface") == surface]
        splits = _splits(mine)
        if not consent_open:
            consent_note: Optional[str] = "door 1 closed: no training yes exists yet, so no pair is releasable"
        elif total == 0:
            consent_note = "no pair on this surface yet"
        else:
            consent_note = None
        if not release_open:
            splits_note: Optional[str] = "door 2 closed: splits are assigned at release (80/10/10, speaker-disjoint)"
        elif surface not in named:
            splits_note = "door 2 is not open for this surface: splits are assigned at release"
        elif splits is None:
            splits_note = "no release yet: splits are assigned at release (80/10/10, speaker-disjoint)"
        else:
            splits_note = None
        out[surface] = {
            "pairs": total,
            "unexported": int(entry.get("unexported") or 0),
            "releasable": releasable,
            "exposures": entry.get("exposures"),
            "consent_authorised_share": (round(releasable / total, 4)
                                         if consent_open and total else None),
            "consent_note": consent_note,
            "releases": [{"week_start": r.get("week_start"), "item_count": r.get("item_count"),
                          "voided_at": r.get("voided_at")} for r in mine],
            "splits": splits,
            "splits_note": splits_note,
        }
    return out


_TRIAGE_ORDER = ("PIPELINE_CHANGED", "UPSTREAM_CHANGE", "POPULATION_MOVED", "UNKNOWN", "HEALTHY")


def _drift(snapshots: list) -> dict:
    """The newest stored week that carries a drift reading: its worst
    verdict and every dimension's 2x2, most urgent first. In words when no
    week carries one yet."""
    for row in snapshots:
        if not isinstance(row, dict):
            continue
        drift = (row.get("snapshot") or {}).get("drift") if isinstance(row.get("snapshot"), dict) else None
        if not isinstance(drift, dict):
            continue
        raw_dims = drift.get("dimensions")
        dims: dict = raw_dims if isinstance(raw_dims, dict) else {}
        rows = [{"dimension": str(dim), "triage": v.get("triage"), "psi": v.get("psi"),
                 "psi_band": v.get("psi_band"), "chart_signal": v.get("chart_signal"),
                 "n_sessions": v.get("n_sessions")}
                for dim, v in dims.items() if isinstance(v, dict)]
        rank = {verdict: i for i, verdict in enumerate(_TRIAGE_ORDER)}
        rows.sort(key=lambda r: (rank.get(str(r["triage"]), len(_TRIAGE_ORDER)), r["dimension"]))
        return {"week_start": row.get("week_start"), "worst": drift.get("worst"),
                "dimensions": rows, "minted": drift.get("minted"),
                "sessions_by_dimension": drift.get("sessions_by_dimension") or {},
                "note": drift.get("note") or drift.get("unavailable")}
    return {"week_start": None, "worst": None, "dimensions": [], "minted": None,
            "sessions_by_dimension": {},
            "note": ("no stored week carries a drift reading yet: the weekly learning job "
                     "stores one with each week (Mondays 06:00 UTC once its cron service "
                     "exists, or “Run the weekly job now” on the pace panel)")}


#: The two checks that are about the cron service's own variables; the web
#: service cannot see them, so the research view does not judge them.
CRON_ONLY_CHECKS = ("production_monitor_not_enabled", "production_alert_sink_not_configured")


def _monitors(database: Any, config: Any) -> dict:
    """The confidence readiness monitor, read now: the same two aggregate
    reads and the same pure assessment the five-minute cron runs
    (scripts/check_mlc2_confidence_canary_readiness.py). Codes and counts,
    never a row. Raises when a read fails (the view names it)."""
    from datetime import datetime, timezone
    from services.coach_video_storage import coach_videos_use_r2
    from services.mlc2_confidence_readiness import assess_confidence_canary_readiness
    report = assess_confidence_canary_readiness(
        database.get_mlc2_confidence_canary_readiness(),
        cutover_mode=getattr(config, "MLC2_CONFIDENCE_CUTOVER_MODE", None),
        ring_health=database.get_ring_confidence_readiness(),
        monitoring_enabled=bool(getattr(config, "MLC2_CONFIDENCE_MONITORING_ENABLED", False)),
        alert_sink_configured=bool(getattr(config, "SENTRY_DSN", None)),
        dataset_creation_enabled=bool(getattr(config, "MLC2_DATASET_RELEASES_ENABLED", False)),
        training_enabled=bool(getattr(config, "MLC2_TRAINING_ENABLED", False)),
        promotion_enabled=bool(getattr(config, "MLC2_PROMOTION_ENABLED", False)),
        source_audio_store_is_r2=coach_videos_use_r2(),
    ).as_dict()
    blockers = [c for c in report.get("blocker_codes") or [] if c not in CRON_ONLY_CHECKS]
    return {
        "confidence_canary": {
            "ready": not blockers,
            "blocker_codes": blockers,
            "warning_codes": list(report.get("warning_codes") or []),
            "cutover_mode": (report.get("evidence") or {}).get("cutover_mode"),
            "read_at": datetime.now(timezone.utc).isoformat(),
        },
        "note": ("read now from the database: the checks the five-minute readiness cron runs. "
                 "Whether that cron has its own switch and Sentry is read on the cron service, "
                 "not here"),
    }


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
        "labels": _read("labels", lambda: database.get_confidence_label_corpus(limit=5000), unavailable) or [],
        "exclusions": _read("exclusions", lambda: database.list_dataset_exclusions(), unavailable) or [],
        "exports": _read("exports", lambda: database.list_annotation_export_runs(limit=20), unavailable) or [],
        "promotions": _read("promotions", lambda: _promotions(database), unavailable) or [],
        "snapshots": _read("snapshots", lambda: database.list_ledger_snapshots(limit=8), unavailable) or [],
        "pair_releases": _read("pair_releases", lambda: database.list_pair_releases(limit=500), unavailable) or [],
        "evaluations": (_read("evaluations", lambda: _evaluations(database, doors), unavailable)
                        or {"reports": [], "note": "evaluation reports unreadable"}),
        "training": (_read("training", lambda: _training(database), unavailable)
                     or {"runs": [], "note": "fine-tune runs unreadable"}),
        "history": _read("promotion_history", lambda: _promotion_history(database), unavailable) or [],
        "monitors": _read("monitors", lambda: _monitors(database, config), unavailable),
    }


def _exports_panel(exports: list, pair_releases: list, doors: dict) -> dict:
    release_open = bool((doors.get("dataset_release") or {}).get("open"))
    if pair_releases:
        note = None
    elif release_open:
        note = ("door 2 is open, but no pair release has run yet: the weekly job exports each "
                "named surface once the release bucket and the signing key are set and the job "
                "runs. The annotation runs above are the retired daily export")
    else:
        note = ("door 2 closed: no pair release has run; a release needs the door open in code "
                "and the founder's sentence per surface. The annotation runs above are the "
                "retired daily export")
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
        "note": note,
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
        "datasets": _datasets(src["ledger"], src["pair_releases"], src["doors"]),
        "labels": quorum(src["labels"]),
        "exclusions": {"by_reason": by_reason,
                       "note": None if src["exclusions"] else "no release yet, so no exclusion was decided"},
        "exports": _exports_panel(src["exports"], src["pair_releases"][:20], src["doors"]),
        "evaluations": src["evaluations"],
        "training": src["training"],
        "promotions": src["promotions"],
        "promotion_history": src["history"],
        "drift": _drift(src["snapshots"]),
        "monitors": src["monitors"] or {"confidence_canary": None,
                                        "note": "the readiness monitor could not be read now"},
        "golden": src["golden"],
        "weekly": [{"week_start": s.get("week_start"), "ready_cues": s.get("ready_cues"),
                    "updated_at": s.get("updated_at")} for s in src["snapshots"] if isinstance(s, dict)],
        "doors": src["doors"],
        "unavailable": unavailable,
    }
