"""The pairs (founder 2026-09-30, C2 and C5; build plan P2-1).

One rule, one place: a (draft, final) pair is recorded only when a model's
draft was SHOWN to the coach and the coach's final DIFFERS from it. The row
is stamped with its surface, the draft's model version, the pattern and the
moment; the coach is its author; `owner_user_id` names whose passage the
words are about, for the consent door later (L1 of the learning page).

Three surfaces, and they never mix: the praise line, the clearer version,
the exercise script. The walk's exercise answer records two finals, the
saved instruction and the video's transcript, when its request resolves
(services.exercise_coach_requests); a Library save records none: it has no
moment, owner or passage, so no export could ever release it (W6).

NEVER FROM AN OWNER'S ANSWER (L3): only coach routes call `record_pair`,
and `coach_id` is required. A coach answering a moment of their own Take is
the owner answering, so no pair is recorded then either (founder 2026-10-05,
W6: "a pair is recorded only when a model draft was shown and the final
differs; never from the owner"). Nothing here is a score, and no row
reaches a speaker. Each recorded pair is also mirrored, best-effort, into the
annotation ledger the dark export reads, under the same surface name, so a
release authorised later finds them where the exporter looks.

THE MODEL DRAFT IS THE SERVER'S (FL-L3). The draft a pair stands on is the
one the server itself kept: the request row's draft (the walk), the Take
word's draft. A text a client calls a draft (the Library's past finals,
which are a coach's or the founder's own words) is never recorded as one.
"""
from __future__ import annotations

import logging
import re
from typing import Any, Optional

_log = logging.getLogger(__name__)

#: The three answer surfaces, and (Phase 7, C5-a; dark behind
#: COACH_WORD_PAIRS_ENABLED) the coach's own two.
SURFACES = ("praise_line", "clearer_version", "exercise_script",
            "coach_moment_line", "coach_take_word")
#: The three answer surfaces: the drafts of services.coach_request_drafts.
ANSWER_SURFACES = ("praise_line", "clearer_version", "exercise_script")
#: The coach's own words (Phase 7, C5-a): the drafts of
#: services.coach_word_pairs, under their own prompts.
COACH_WORD_SURFACES = ("coach_moment_line", "coach_take_word")
#: The surfaces doors 2, 3 and 4 know: all five. Privacy/Terms 3.5, signed
#: by the founder 2026-10-08 (decisions log N68; legal/phase1-2026.1/22-…
#: SIGNED, E2), covers the coach's own words as training data under the
#: speaker's training yes, and the coach agreement covers the coach's side.
#: Knowing a surface opens nothing: each door still opens for a surface only
#: when its switch is on AND the founder named the surface in its config
#: set (PAIR_RELEASE_SURFACES, TRAINING_SURFACES, PROMOTION_SURFACES), and
#: every one of them needs the speaker's yes (pair_consent).
DOOR_SURFACES = ANSWER_SURFACES + COACH_WORD_SURFACES
FINAL_KINDS = ("final", "transcript")
_WS = re.compile(r"\s+")


def normalised(text: Any) -> str:
    """Whitespace-collapsed, stripped; the comparison the rule uses."""
    return _WS.sub(" ", text).strip() if isinstance(text, str) else ""


def differs(draft: Any, final: Any) -> bool:
    """True when both are words and the final is not the draft."""
    a, b = normalised(draft), normalised(final)
    return bool(a) and bool(b) and a != b


def record_pair(
    database: Any, *, surface: str, draft: Any, final: Any, coach_id: Any,
    model_version: Optional[str] = None, pattern_key: Optional[str] = None,
    owner_user_id: Optional[str] = None, take_session_id: Optional[str] = None,
    snippet_id: Optional[str] = None, request_id: Optional[str] = None,
    exercise_id: Optional[str] = None, exercise_version: Optional[int] = None,
    final_kind: str = "final", take_word_id: Optional[str] = None,
    prompt_snapshot: Optional[dict] = None,
) -> Optional[dict]:
    """The one write. None when the rule says no row, or the write failed:
    a pair that is not recorded never breaks the answer it rode on. A pair
    hangs on a request, an exercise, or (Phase 7, C5-a) a Take word.

    ``prompt_snapshot`` ({passage_text, prompt_context}) is what the draft's
    prompt was given, kept by the drafter itself; the coach's own words pass
    it (services.coach_word_pairs), the answer surfaces read the clip."""
    if surface not in SURFACES or final_kind not in FINAL_KINDS:
        return None
    coach = str(coach_id or "").strip()
    if not coach or not differs(draft, final):
        return None
    if owner_user_id and str(owner_user_id).strip() == coach:
        # The coach is the passage's owner: an owner's answer, never a pair.
        return None
    if not request_id and not exercise_id and not take_word_id:
        return None
    writer = getattr(database, "insert_feedback_pair", None)
    if writer is None:
        return None
    # The pair remembers the yes (0405): its owner's principal and the
    # consent state at this moment; the weekly refresh keeps it true.
    from services.pair_consent import stamp
    consent = stamp(database, surface=surface, owner_user_id=owner_user_id)
    # The pair remembers the passage it was drafted from and what the
    # prompt was told (0406): a training example needs the prompt, and a
    # pair without one is never an example.
    if surface in COACH_WORD_SURFACES:
        # The coach's words were drafted from what the drafter kept; a pair
        # without that snapshot carries no passage and is never released,
        # judged or trained on (fail closed: a clip's transcript is not the
        # prompt these drafts were written from).
        prompt = _given_snapshot(prompt_snapshot)
    else:
        prompt = _prompt_snapshot(database, take_session_id=take_session_id,
                                  snippet_id=snippet_id, surface=surface,
                                  pattern_key=pattern_key)
    try:
        row = writer(
            **consent, **prompt,
            surface=surface, draft_text=str(draft).strip(),
            final_text=str(final).strip(), final_kind=final_kind,
            draft_model_version=model_version or None,
            pattern_key=pattern_key or None, coach_id=coach,
            owner_user_id=owner_user_id or None,
            take_session_id=take_session_id or None,
            snippet_id=snippet_id or None, request_id=request_id or None,
            exercise_id=exercise_id or None,
            exercise_version=int(exercise_version) if exercise_version else None,
            **({"take_word_id": str(take_word_id)} if take_word_id else {}),
        )
    except Exception as e:  # noqa: BLE001 -- the answer stands
        _log.warning("feedback pair not recorded surface=%s: %s", surface, e,
                     exc_info=True)
        return None
    if isinstance(row, dict):
        _mirror(database, row, coach)
        return row
    return None


#: Request kind by surface, as the draft prompt was told it (coach_request_drafts).
KIND_FOR_SURFACE = {"exercise_script": "error", "praise_line": "praise",
                    "clearer_version": "rewrite"}


def _prompt_snapshot(database: Any, *, take_session_id: Any, snippet_id: Any,
                     surface: str, pattern_key: Any) -> dict:
    """{passage_text, prompt_context} for the pair, best effort: the clip's
    transcript as it stands now and the kind the prompt was given. An
    exercise-lane pair (no clip) gets neither and is never trained on."""
    passage = ""
    if take_session_id and snippet_id:
        reader = getattr(database, "get_snippets_by_session", None)
        try:
            for row in (reader(str(take_session_id)) if reader else []) or []:
                if isinstance(row, dict) and str(row.get("id")) == str(snippet_id):
                    passage = " ".join(str(row.get("transcript") or "").split())
                    break
        except Exception as e:  # noqa: BLE001 -- the pair is still recorded
            _log.info("pair prompt snapshot skipped: %s", e)
    if not passage:
        return {"passage_text": None, "prompt_context": None}
    return {"passage_text": passage,
            "prompt_context": {"kind": KIND_FOR_SURFACE.get(surface, "error"),
                               "pattern_key": pattern_key or None}}


def _given_snapshot(snapshot: Any) -> dict:
    """{passage_text, prompt_context} from a drafter's own snapshot, or
    neither when it is missing or carries no passage."""
    if not isinstance(snapshot, dict):
        return {"passage_text": None, "prompt_context": None}
    passage = " ".join(str(snapshot.get("passage_text") or "").split())
    context = snapshot.get("prompt_context")
    if not passage or not isinstance(context, dict):
        return {"passage_text": None, "prompt_context": None}
    return {"passage_text": passage, "prompt_context": dict(context)}


def _mirror(database: Any, row: dict, coach: str) -> None:
    """The dark export's ledger, same surface name, best-effort."""
    mirror = getattr(database, "create_admin_annotation_event", None)
    if mirror is None:
        return
    try:
        mirror(
            user_id=str(row.get("owner_user_id") or coach),
            session_id=row.get("take_session_id"),
            section_type="coach_answer",
            field_name=str(row.get("surface")),
            ai_original_text=row.get("draft_text"),
            coach_final_text=row.get("final_text"),
            reason_chip=None, custom_reason=None, created_by=coach,
        )
    except Exception as e:  # noqa: BLE001 -- the pair row is the record
        _log.info("feedback pair mirror skipped: %s", e)


def counts(database: Any) -> dict:
    """Per surface: how many pairs exist, how many await export and how
    many are releasable (the pace panel's jar). Every surface is named, at
    zero when nothing was written. A count that cannot be read RAISES, so
    the ledger names "pairs" unavailable instead of drawing zeros that read
    as a measurement (ML-2); a database with no pair table at all (a test
    double) reads as zero."""
    reader = getattr(database, "count_feedback_pairs", None)
    raw: Any = reader() if reader is not None else {}
    out = {}
    for surface in SURFACES:
        entry = raw.get(surface) if isinstance(raw, dict) else None
        entry = entry if isinstance(entry, dict) else {}
        out[surface] = {
            "total": int(entry.get("total") or 0),
            "unexported": int(entry.get("unexported") or 0),
            "releasable": int(entry.get("releasable") or 0),
        }
    return out


def exposures(database: Any) -> dict:
    """Per surface: how many times a model's draft was shown to a coach
    (ML-2; the first half of the C5 rule: a pair exists only where a draft
    was shown AND the final differs, so ``pairs / exposures`` is how often
    coaches change a draft). Every surface is named, at zero when nothing
    was shown. Raises when the count cannot be read (named, never zero)."""
    reader = getattr(database, "count_draft_exposures", None)
    raw: Any = reader() if reader is not None else {}
    raw = raw if isinstance(raw, dict) else {}
    return {surface: int(raw.get(surface) or 0) for surface in SURFACES}


def exportable(database: Any) -> dict:
    """Per surface: how many pairs the export contract can actually release
    (C9; W6 2026-10-05): the speaker's training yes AND the passage the draft
    was written from AND the model version that wrote it, ever
    (``exportable``) and still awaiting export (``exportable_unexported``).
    The walk's exercise pairs carried no passage or model version before
    W6, so with a yes they counted as releasable yet could never leave; the
    pace panel's jar and a run's bar of 200 count these instead. Every
    surface is named, at zero when nothing was written. Raises when the
    count cannot be read (named, never zero; ML-2)."""
    reader = getattr(database, "count_exportable_pairs", None)
    raw: Any = reader() if reader is not None else {}
    raw = raw if isinstance(raw, dict) else {}
    out = {}
    for surface in SURFACES:
        entry = raw.get(surface) if isinstance(raw.get(surface), dict) else {}
        out[surface] = {
            "exportable": int(entry.get("exportable") or 0),
            "exportable_unexported": int(entry.get("exportable_unexported") or 0),
        }
    return out
