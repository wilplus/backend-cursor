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
    """Which model each contract surface serves today. The runtime row is
    overwritten on promotion, so this is the present, not a history; a
    history table comes with door 4 (ML-12)."""
    from services.ml_surface_contracts import SURFACES
    out = []
    for surface_id, contract in SURFACES.items():
        value = database.get_runtime_config(contract.runtime_config_key)
        out.append({"surface": surface_id, "key": contract.runtime_config_key,
                    "model": value, "note": None if value else "stock model (never promoted)"})
    return out


def overview(database: Any, *, config: Any = None) -> dict:
    from services.learning_ledger import ledger as read_ledger
    from services.golden_set import SURFACES as GOLDEN_SURFACES, counts as golden_counts
    from services.research_quorum import quorum
    if config is None:
        from config import Config
        config = Config()
    unavailable: list[str] = []
    ledger = _read("ledger", lambda: read_ledger(database, config=config), unavailable) or {}
    doors = ledger.get("doors") or {}
    releases = _read("releases", lambda: database.list_dataset_releases(), unavailable) or []
    labels = _read("labels", lambda: database.get_confidence_label_corpus(limit=5000), unavailable) or []
    exclusions = _read("exclusions", lambda: database.list_dataset_exclusions(), unavailable) or []
    exports = _read("exports", lambda: database.list_annotation_export_runs(limit=20), unavailable) or []
    promotions = _read("promotions", lambda: _promotions(database), unavailable) or []
    snapshots = _read("snapshots", lambda: database.list_ledger_snapshots(limit=8), unavailable) or []
    golden = {}
    for surface in GOLDEN_SURFACES:
        def _count(s: str = surface) -> dict:
            return golden_counts(database, surface=s)
        golden[surface] = _read(f"golden.{surface}", _count, unavailable)
    by_reason: dict[str, int] = {}
    for row in exclusions:
        if isinstance(row, dict):
            key = str(row.get("reason_code") or "unspecified")
            by_reason[key] = by_reason.get(key, 0) + 1
    return {
        "view_version": VIEW_VERSION,
        "datasets": _datasets(ledger, releases, doors),
        "labels": quorum(labels),
        "exclusions": {"by_reason": by_reason,
                       "note": None if exclusions else "no release yet, so no exclusion was decided"},
        "exports": {
            "annotation_runs": [
                {"started_at": r.get("started_at"), "status": r.get("status"),
                 "exported_count": r.get("exported_count"), "export_uri": r.get("export_uri")}
                for r in exports if isinstance(r, dict)],
            "pair_exports": [],
            "note": "door 2 closed: no pair export has run; the annotation runs above are the retired daily export",
        },
        "evaluations": {"reports": [],
                        "note": "door 3 closed: no candidate has been evaluated; reports appear with ML-11"},
        "promotions": promotions,
        "drift": {"last": None, "note": "the weekly drift run stores no rows yet; its verdicts reach Sentry only"},
        "monitors": {"last": None, "note": "the readiness monitors write to Sentry, not to a table"},
        "golden": golden,
        "weekly": [{"week_start": s.get("week_start"), "ready_cues": s.get("ready_cues"),
                    "updated_at": s.get("updated_at")} for s in snapshots if isinstance(s, dict)],
        "doors": doors,
        "unavailable": unavailable,
    }
