"""The founder's ledger, as data (founder 2026-09-30, C9, E7, L4; build plan
ML-2).

One read that says where every learning jar stands, in counts about the
SYSTEM and never about a person:

  * pairs per surface, total and awaiting export (feedback_pairs);
  * the exercise learning jar: counted tries against 300, per exercise
    against 30 (services.exercise_learning_readiness);
  * the shadow cues: coach-named moments against 30 and the caught rate
    against 80% (services.verbal_cue_validation);
  * the four doors, as the code constants say them today;
  * what last happened, where a table records it.

A source that cannot be read is NAMED in `unavailable` rather than read as
zero. Nothing here promotes, trains, exports or flips anything. Founder
and research roles only, by the routes that serve it (AC-9 for everyone
else: this is a page of numbers about the machine).
"""
from __future__ import annotations

import logging
from typing import Any, Callable

_log = logging.getLogger(__name__)

LEDGER_VERSION = "learning-ledger-v1"
#: Pairs a surface needs before one fine-tune run may start (C6).
PAIRS_PER_RUN = 200


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


def cue_rows(report: Any, *, min_named: int, min_caught_rate: float) -> dict:
    """Each cue with its bar and whether it is READY to be proposed."""
    out = {}
    for cue, summary in (report or {}).items():
        if not isinstance(summary, dict):
            continue
        named = int(summary.get("coach_named_measured") or 0)
        rate = summary.get("caught_rate")
        ready = named >= min_named and rate is not None and rate >= min_caught_rate
        out[str(cue)] = {
            "named": named,
            "named_bar": min_named,
            "caught_rate": rate,
            "caught_bar": min_caught_rate,
            "clips_measured": int(summary.get("clips_measured") or 0),
            "false_alarm_rate": summary.get("false_alarm_rate"),
            "ready": bool(ready),
        }
    return out


def ledger(database: Any, *, config: Any = None) -> dict:
    """Everything the founder's page and the weekly job need, in one dict."""
    from services.feedback_pairs import counts
    from services.exercise_learning_readiness import readiness
    from services.verbal_cue_validation import (
        PROMOTION_MIN_CAUGHT_RATE, PROMOTION_MIN_NAMED, report,
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
    for surface, entry in pairs.items():
        entry["run_bar"] = PAIRS_PER_RUN
        entry["ready_for_run"] = entry.get("unexported", 0) >= PAIRS_PER_RUN
    return {
        "ledger_version": LEDGER_VERSION,
        "pairs": pairs,
        "exercise_jar": jar,
        "shadow_cues": cue_rows(cues, min_named=PROMOTION_MIN_NAMED,
                                min_caught_rate=PROMOTION_MIN_CAUGHT_RATE),
        "doors": doors(config),
        "unavailable": unavailable,
    }
