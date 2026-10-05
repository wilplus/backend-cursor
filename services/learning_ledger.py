"""The founder's ledger, as data (founder 2026-09-30, C9, E7, L4; build plan
ML-2).

One read that says where every learning jar stands, in counts about the
SYSTEM and never about a person:

  * pairs per surface, for every pair surface (the three answer surfaces
    and the two coach-word ones): total, awaiting export, releasable, and
    the EXPOSURES, the model drafts shown to a coach on that surface (C5:
    a pair needs a draft shown and a final that differs); and beside them
    the pairs the export contract can actually release (``exportable``:
    the yes, the passage and the model version; C9, W6), which alone fill
    a run's bar of 200;
  * the exercise learning jar: counted tries against 300, per exercise
    against 30 (services.exercise_learning_readiness);
  * the shadow cues: coaches' Yes answers in the blind error audit
    against 30 and the audit's catch rate against 80% (N48.5 Q24 A;
    services.verbal_cue_validation);
  * the four doors, as the code constants say them today;
  * what last happened, where a table records it: the newest pair
    release, fine-tune run and promotion (``last``).

A source that cannot be read is NAMED in `unavailable` rather than read as
zero. Nothing here promotes, trains, exports or flips anything. Founder
and research roles only, by the routes that serve it (AC-9 for everyone
else: this is a page of numbers about the machine).
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

_log = logging.getLogger(__name__)

LEDGER_VERSION = "learning-ledger-v1"
#: Pairs a surface needs before one fine-tune run may start (C6).
PAIRS_PER_RUN = 200
#: The window of the coach-load report (Phase 2 addition, 2026-10-01).
COACH_LOAD_DAYS = 28


def _read(name: str, reader: Callable[[], Any], unavailable: list[str]) -> Any:
    try:
        return reader()
    except Exception as e:  # noqa: BLE001 -- named, never read as zero
        _log.warning("ledger source %s unavailable: %s", name, e, exc_info=True)
        unavailable.append(name)
        return None


def doors(config: Any) -> dict:
    """The four doors as the code constants say them. `open` is the literal
    value; nothing here can change one."""
    return {
        "consent": {"open": bool(getattr(config, "MLC2_TRAINING_SWITCH_ENABLED", False)),
                    "constant": "MLC2_TRAINING_SWITCH_ENABLED"},
        "dataset_release": {"open": bool(getattr(config, "MLC2_PAIR_RELEASES_ENABLED", False)),
                            "constant": "MLC2_PAIR_RELEASES_ENABLED",
                            "surfaces": sorted(getattr(config, "PAIR_RELEASE_SURFACES", ()) or ())},
        "training": {"open": bool(getattr(config, "MLC2_TRAINING_ENABLED", False)),
                     "constant": "MLC2_TRAINING_ENABLED"},
        "promotion": {"open": bool(getattr(config, "MLC2_PROMOTION_ENABLED", False)),
                      "constant": "MLC2_PROMOTION_ENABLED"},
    }


def cue_rows(report: Any, *, min_yes: int, min_caught_rate: float) -> dict:
    """Each cue with its bar and whether it is READY to be proposed: the
    coaches' Yes answers in the blind error audit against ``min_yes`` and
    the audit's catch rate against ``min_caught_rate`` (N48.5 Q24 A). The
    moments coaches once named it on ride as history (``named``), never as
    the bar."""
    from services.verbal_cue_validation import meets_bar
    out = {}
    for cue, summary in (report or {}).items():
        if not isinstance(summary, dict):
            continue
        ready, why_not = meets_bar(summary, min_yes=min_yes,
                                   min_caught_rate=min_caught_rate)
        out[str(cue)] = {
            "audit_yes": int(summary.get("audit_yes") or 0),
            "audit_yes_bar": min_yes,
            "caught_rate": summary.get("caught_rate"),
            "caught_bar": min_caught_rate,
            "audited": bool(summary.get("audited", True)),
            "clips_measured": int(summary.get("clips_measured") or 0),
            "false_alarm_rate": summary.get("false_alarm_rate"),
            "named": int(summary.get("coach_named_measured") or 0),
            "ready": bool(ready),
            "why_not": why_not,
        }
    return out


def _newest(database: Any, method: str) -> dict | None:
    """The newest row a ledger table holds, or None when it holds none. A
    database double without the table reads as None; a failed read raises
    (and `_read` names it)."""
    reader = getattr(database, method, None)
    if reader is None:
        return None
    rows = [r for r in (reader(limit=1) or []) if isinstance(r, dict)]
    return rows[0] if rows else None


def _pick(row: Any, keys: tuple[str, ...]) -> dict | None:
    return {k: row.get(k) for k in keys} if isinstance(row, dict) else None


def last_events(database: Any, unavailable: list[str]) -> dict:
    """What last happened, where a table records it (build plan ML-2): the
    newest pair release (door 2), fine-tune run (door 3) and promotion
    (door 4). Surfaces, states, counts and dates about the machine; no
    owner, no coach, no file key. None where nothing has happened yet."""
    release = _read("last_pair_release",
                    lambda: _newest(database, "list_pair_releases"), unavailable)
    run = _read("last_fine_tune",
                lambda: _newest(database, "list_fine_tune_runs"), unavailable)
    promotion = _read("last_promotion",
                      lambda: _newest(database, "list_model_promotions"), unavailable)
    return {
        "pair_release": _pick(release, ("surface", "week_start", "item_count",
                                        "exported_at", "voided_at", "purged_at")),
        "fine_tune": _pick(run, ("surface", "status", "item_count",
                                 "started_at", "finished_at", "withdrawn_at")),
        "promotion": _pick(promotion, ("surface", "candidate_model",
                                       "promoted_at", "killed_at")),
    }


def _peer_lane_counts(database: Any, since: str) -> dict:
    """Counts only; empty and marked dark while the peer lane is off."""
    from services.lend_your_ear import peer_lane_enabled
    if not peer_lane_enabled():
        return {"enabled": False}
    return {"enabled": True, "since": since, **(database.count_lend_your_ear(since) or {})}


def ledger(database: Any, *, config: Any = None) -> dict:
    """Everything the founder's page and the weekly job need, in one dict."""
    from services.feedback_pairs import (
        counts, exportable as exportable_pairs, exposures as draft_exposures,
    )
    from services.exercise_learning_readiness import readiness
    from services.verbal_cue_validation import (
        PROMOTION_MIN_CAUGHT_RATE, PROMOTION_MIN_YES, report,
    )
    from services.verbal_cues import CUES, VERBAL_CUES_VERSION

    if config is None:
        from config import Config
        config = Config()
    unavailable: list[str] = []
    pairs = _read("pairs", lambda: counts(database), unavailable) or {}
    jar = _read("exercise_jar", lambda: readiness(database), unavailable) or {}
    from services.acoustic_cues import ACOUSTIC_CUES_VERSION, CUES as ACOUSTIC_CUES
    cues = _read(
        "shadow_cues",
        lambda: report(database, detector_version=VERBAL_CUES_VERSION, cues=CUES),
        unavailable) or {}
    # The two acoustic shadow cues (ML-14) sit in the same ledger, under
    # their own detector version, against the same bar.
    cues.update(_read(
        "acoustic_cues",
        lambda: report(database, detector_version=ACOUSTIC_CUES_VERSION, cues=ACOUSTIC_CUES),
        unavailable) or {})
    # Drafts shown per surface (ML-2): None on every surface when the count
    # could not be read (named in `unavailable`), never a zero.
    shown = _read("exposures", lambda: draft_exposures(database), unavailable)
    # The pairs the export contract can release (C9; W6): None on every
    # surface when the count could not be read (named), never a zero.
    exportable = _read("exportable_pairs", lambda: exportable_pairs(database),
                       unavailable)
    for surface, entry in pairs.items():
        entry["run_bar"] = PAIRS_PER_RUN
        # Only pairs the export contract can release fill the bar (C9; W6
        # 2026-10-05): the speaker's yes, the passage and the model version.
        # Unknown when that count could not be read: never "ready" on a guess.
        can_leave = exportable.get(surface) if isinstance(exportable, dict) else None
        entry["exportable"] = int(can_leave["exportable"]) if can_leave else None
        entry["exportable_unexported"] = (int(can_leave["exportable_unexported"])
                                          if can_leave else None)
        entry["ready_for_run"] = bool(can_leave) and \
            entry["exportable_unexported"] >= PAIRS_PER_RUN
        entry["exposures"] = (int(shown.get(surface) or 0)
                              if isinstance(shown, dict) else None)
    # Requests per opened moment, before and after the Phase 2 switch
    # (founder 2026-10-01): the last four weeks, split by kind.
    from services.coach_load import coach_load
    since = (datetime.now(timezone.utc) - timedelta(days=COACH_LOAD_DAYS)).isoformat()
    load = _read("coach_load", lambda: coach_load(database, since=since),
                 unavailable) or {}
    # Practices that land, Bold voices heard, steps shown (Phase 3; the
    # founder's weekly line), same window.
    from services.bold_voices import after_practice_counts
    after = _read("after_practice",
                  lambda: after_practice_counts(database, since=since),
                  unavailable) or {}
    # Phase 4 and 5 (the founder's weekly line): peer answers, sets, live
    # shares; the delayed measure's pairs and outcomes. Zero while dark.
    from services.delayed_measure import report as delayed_report
    peer = _read("peer_lane", lambda: _peer_lane_counts(database, since), unavailable) or {}
    delayed = _read("delayed_measure", lambda: delayed_report(database), unavailable) or {}
    # The coach panel's learning additions (0411): the coach's exercise
    # preference (1b), the blind error audit's report card (6a), the fair
    # test of every detector version (6b-6d), the block pick (8) and the
    # share of coach-word drafts sent unchanged (7). Empty while dark.
    panel = _coach_panel_rows(database, unavailable)
    return {
        "ledger_version": LEDGER_VERSION,
        "pairs": pairs,
        "exercise_jar": jar,
        "shadow_cues": cue_rows(cues, min_yes=PROMOTION_MIN_YES,
                                min_caught_rate=PROMOTION_MIN_CAUGHT_RATE),
        "doors": doors(config),
        "last": last_events(database, unavailable),
        "coach_load": load,
        "after_practice": after,
        "peer_lane": peer,
        "delayed_measure": delayed,
        **panel,
        "unavailable": unavailable,
    }


def _coach_panel_rows(database: Any, unavailable: list[str]) -> dict:
    from services.coach_block_pick import ledger as block_pick_ledger
    from services.coach_exercise_preference import ledger as preference_ledger, preference_enabled
    from services.coach_word_pairs import unchanged_share, word_pairs_enabled
    from services.detector_candidates import register_candidates
    from services.detector_rollout import fair_test
    from services.error_presence_audit import audit_enabled, report_card
    register_candidates()
    preference = (_read("coach_preference", lambda: preference_ledger(database), unavailable)
                  if preference_enabled() else {"enabled": False}) or {}
    audit = (_read("error_audit",
                   lambda: report_card(database.list_error_presence_audit_answered_all() or []),
                   unavailable) if audit_enabled() else {"enabled": False}) or {}
    # The fair test grades every version against the audit's answers, so
    # it has nothing to say until the audit is on.
    detectors = (_read("detector_fair_test", lambda: fair_test(database), unavailable)
                 if audit_enabled() else {"enabled": False}) or {}
    picks = _read("block_pick", lambda: block_pick_ledger(database), unavailable) or {}
    words = (_read("coach_word_pairs",
                   lambda: unchanged_share(database.list_coach_word_drafts() or []),
                   unavailable) if word_pairs_enabled() else {"enabled": False}) or {}
    return {"coach_preference": preference, "error_audit": audit,
            "detector_fair_test": detectors, "block_pick": picks,
            "coach_word_pairs": words}
