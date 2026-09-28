"""Spoken-word cues, measured silently first (founder 2026-09-28, D2 + D3).

Three habits read from a clip's transcript — ``filler_cluster``, ``hedging``,
``restart_repair`` — each with the written definition the speaking error
library holds for it (migration 0386). They run in the SHADOW stage: once per
Take, after processing, their verdicts are logged and nothing else happens.
They route no exercise (routing reads ``status = 'detected'`` only), reach no
user, and feed no dataset. Promotion is a separate migration, made once the
verdicts have been checked against coaches' own judgments.

WHY ENGLISH ONLY. English audio is transcribed with a prompt that keeps "um"
and "uh" in the text (services/openai_service.py); other languages are not,
so their transcripts mostly lack fillers that were said. Counting them would
log "no fillers" where the truth is "not written down" — a false verdict, not
a missing one. Other languages log nothing until their transcripts can carry
the evidence.

REUSED, NOT RE-INVENTED. Hesitation tokens and the immediate-repeat pattern
come from services/transcript_smoothing.py; hedges from
services/verbal_markers.py, strict terms only (the module's own rule: use
`strict` for anything that feeds a threshold).
"""
from __future__ import annotations

import logging
from typing import Any, Optional

_log = logging.getLogger(__name__)

#: The version every verdict is logged under. It names the thresholds below,
#: the lexicons they read, and the language rule. Bump it with any change;
#: ``test_the_verbal_cue_rules_are_versioned`` fails until you do, because a
#: verdict logged under the wrong version compares unlike with unlike.
VERBAL_CUES_VERSION = "verbal-cues-v1"

SUPPORTED_LANGUAGES = ("en",)

FILLER_MIN_COUNT = 2
FILLER_MIN_PER_100_WORDS = 5.0
HEDGE_MIN_COUNT = 2
RESTART_MIN_COUNT = 2

CUES = ("filler_cluster", "hedging", "restart_repair")


def _language(value: Any) -> Optional[str]:
    code = str(value or "").strip().lower()[:2]
    return code or None


def _repeats(text: str) -> list[str]:
    from services.transcript_smoothing import _REPEAT_RE
    return [m.group(1).lower() for m in _REPEAT_RE.finditer(text)]


def _hesitations(text: str, language: str) -> list[str]:
    from services.transcript_smoothing import _filler_re, hesitations_for
    return [m.group(0).lower()
            for m in _filler_re(hesitations_for(language)).finditer(text)]


def measure(transcript: Any, language: Any) -> Optional[dict]:
    """Every cue's verdict and the counts behind it, for one clip.

    None when the clip cannot be measured honestly: an unsupported or unknown
    language, or no words. Never a verdict of "absent" in those cases.
    """
    from services.verbal_markers import HEDGE, count, word_count
    lang = _language(language)
    if lang not in SUPPORTED_LANGUAGES or not isinstance(transcript, str):
        return None
    n_words = word_count(transcript)
    if n_words == 0:
        return None
    fillers = _hesitations(transcript, lang)
    per_100 = round(100.0 * len(fillers) / n_words, 2)
    hedges = count(transcript, language=lang)[HEDGE]
    strict_terms = {term: n for term, n in hedges["terms"].items()
                    if _is_strict_hedge(term, lang)}
    repeats = _repeats(transcript)
    return {
        "filler_cluster": {
            "fired": (len(fillers) >= FILLER_MIN_COUNT
                      and per_100 >= FILLER_MIN_PER_100_WORDS),
            "measurements": {"n_words": n_words, "count": len(fillers),
                             "per_100_words": per_100,
                             "tokens": sorted(set(fillers))},
        },
        "hedging": {
            "fired": hedges["strict"] >= HEDGE_MIN_COUNT,
            "measurements": {"n_words": n_words, "count": hedges["strict"],
                             "ambiguous_not_counted": hedges["ambiguous"],
                             "terms": strict_terms},
        },
        "restart_repair": {
            "fired": len(repeats) >= RESTART_MIN_COUNT,
            "measurements": {"n_words": n_words, "count": len(repeats),
                             "repeated": sorted(set(repeats))},
        },
    }


def _is_strict_hedge(term: str, language: str) -> bool:
    from services.verbal_markers import HEDGE, lexicon
    return lexicon(HEDGE, language).get(term) is False


def take_observations(snippets: list[dict], *, take_session_id: str,
                      language_of: Any) -> list[dict]:
    """The rows one Take logs. ``language_of(recording_id)`` returns the
    recording's transcription language (or None)."""
    rows: list[dict] = []
    languages: dict[str, Optional[str]] = {}
    for snippet in snippets or []:
        if not isinstance(snippet, dict) or not snippet.get("id"):
            continue
        recording_id = str(snippet.get("recording_id") or "")
        if recording_id not in languages:
            languages[recording_id] = (language_of(recording_id)
                                       if recording_id else None)
        language = _language(languages[recording_id])
        verdicts = measure(snippet.get("transcript"), language)
        if verdicts is None:
            continue
        for cue in CUES:
            rows.append({
                "take_session_id": str(take_session_id),
                "snippet_id": str(snippet["id"]),
                "recording_id": recording_id or None,
                "error_id": cue,
                "detector_version": VERBAL_CUES_VERSION,
                "language": language,
                "fired": bool(verdicts[cue]["fired"]),
                "measurements": verdicts[cue]["measurements"],
            })
    return rows


def _practice_permitted(database: Any, take_session_id: str) -> bool:
    """Only with the speaker's "Personalised practice" yes (E1): these cues
    exist to route exercises, and choosing exercises from a recording is that
    tick. The same boundary every exercise path asks."""
    from services.processing_authorization import (
        PERSONALISED_PRACTICE,
        ProcessingAuthorizationService,
    )
    service = ProcessingAuthorizationService(database)
    try:
        principal = service.take_acquisition_principal(str(take_session_id))
    except Exception:
        return not service.enforced
    return service.choice_permitted(principal, PERSONALISED_PRACTICE)


def record_take(database: Any, take_session_id: str) -> int:
    """Measure one Take's clips and log the verdicts. Returns rows added.

    Best-effort by contract: the caller runs it under DegradationLog, and a
    Take is never slower to reach its Ideal Text or worse for its speaker
    because of anything here.
    """
    if not take_session_id or not _practice_permitted(database,
                                                      take_session_id):
        return 0

    def language_of(recording_id: str) -> Optional[str]:
        row = database.get_recording(recording_id)
        return row.get("transcription_language") if isinstance(row, dict) else None

    rows = take_observations(
        database.get_snippets_by_session(str(take_session_id)) or [],
        take_session_id=str(take_session_id), language_of=language_of)
    if not rows:
        return 0
    return int(database.record_verbal_cue_shadow(rows) or 0)
