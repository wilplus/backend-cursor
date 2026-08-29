"""Star-suggestion generation (founder 2026-07-18).

After a take's analysis, each notable snippet (resolved by
services.moment_confidence from the stored machine read; replace triggers:
an unconfident read / profanity / very low slide stickiness) gets ONE
generated suggestion the grey star opens:

  * emphasize — a short qualitative "why this landed" line;
  * replace   — an audience-appropriate replacement phrase, in the
                speaker's register, + a short "why swap this" line.

Every string passes say_it_stronger._guard_copy (AC-9: digits/construct
vocabulary kill the string). Persisted per snippet (moment_suggestions);
Approve/Revert live in user_suggestion_feedback. L1 (founder sign-off):
an approved replacement writes the STUDENT's serve-time copy only — the
canonical ideal text is never mutated by anything in this module.

Best-effort throughout: a generation miss stores nothing (no star), and
never breaks the analysis pipeline (LIVE LOOP).
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Prompt text lives in the registry (services/prompts/) — moved verbatim
# 2026-08-03; hash-locked in prompts.lock.json.
from services.prompts.moment_suggestions import SYSTEM as _SYSTEM
from services.prompts.moment_suggestions import STRUCT_SYSTEM as _STRUCT_SYSTEM
from services.prompts.moment_suggestions import (
    EMPHASIS_SYSTEM as _EMPHASIS_SYSTEM,
)

# Cap on the context-document excerpt per prompt. The stored text can reach
# 40k chars and this rides every snippet's call, so the excerpt is bounded.
_MAX_DOC_EXCERPT = 1200

# THE CONFIDENT VOICE CARD (founder mini-brief 2026-08-14, §17
# acoustic-confidence-v1). Purely positive, founder-signed, and
# DETERMINISTIC — the threshold read is the detector and the body is
# fixed copy, so no LLM rides this card and it costs nothing.
CONFIDENT_VOICE_WHY = "You sounded incredibly confident and natural here."


@dataclass(frozen=True)
class _GenerationContext:
    """Read-only evidence shared by every candidate lane for one take."""

    cap: int
    sticky_max: float
    readout: dict[str, Any]
    metrics_by_id: dict[str, dict[str, Any]]
    session: dict[str, Any]
    audience: Optional[str]
    strategic_context: Optional[str]
    confidence_baseline: Any
    context_document: Optional[str]
    decided_keys: set
    intent_keys: set
    take_texts: list


def _load_generation_context(
    session_id: str,
    arc_id: str,
    database: Any,
) -> _GenerationContext:
    """Load take-wide inputs without making any candidate decision."""
    from config import Config
    from services.ideal_decision_ledger import intent_keys, ledger_keys
    from services.lab_recording import build_readout_from_session
    from services.protected_phrases import collect_take_texts

    try:
        cap = max(1, int(Config().MOMENT_SUGGESTIONS_MAX_PER_TAKE))
    except Exception:
        cap = 8
    try:
        sticky_max = max(
            0, int(Config().MOMENT_REPLACE_STICKINESS_MAX_PCT)) / 100.0
    except Exception:
        sticky_max = 0.15

    # Internal coach-view read only. Its serializer deliberately omits the
    # machine-confidence blob, so that evidence is loaded from snippet rows.
    readout = build_readout_from_session(
        session_id, include_slide_scores=True)
    metrics_by_id: dict[str, dict[str, Any]] = {}
    try:
        for row in (database.get_snippets_by_session(session_id) or []):
            row_metrics = row.get("metrics")
            metrics_by_id[str(row.get("id"))] = (
                row_metrics if isinstance(row_metrics, dict) else {})
    except Exception as metrics_error:
        logger.warning(
            "moment_suggestion: metrics read failed sid=%s: %s",
            session_id,
            metrics_error,
        )

    session: dict[str, Any] = {}
    try:
        session = database.v2_get_session_by_id(session_id) or {}
    except Exception:
        pass
    intake = session.get("intake_context")
    context = intake if isinstance(intake, dict) else {}
    audience = context.get("audience") or None
    strategic_context = context.get("strategic_context") or None

    confidence_baseline = None
    try:
        from services.voice_confidence import resolve_confidence_baseline

        confidence_baseline, _ = resolve_confidence_baseline(
            session.get("user_id"),
            [
                metric
                for metric in metrics_by_id.values()
                if isinstance(metric, dict)
            ],
        )
    except Exception as baseline_error:
        logger.warning(
            "moment_suggestion: cue baseline failed sid=%s: %s",
            session_id,
            baseline_error,
        )

    context_document = None
    try:
        document = database.get_arc_context_document(arc_id) or {}
        context_document = (document.get("text") or "").strip() or None
    except Exception as document_error:
        logger.warning(
            "moment_suggestions: context doc read failed arc=%s: %s",
            arc_id,
            document_error,
        )

    try:
        ledger_rows = database.list_ideal_decisions(arc_id)
        decided_keys = ledger_keys(ledger_rows)
        decision_intent_keys = intent_keys(ledger_rows)
    except Exception:
        decided_keys = set()
        decision_intent_keys = set()

    return _GenerationContext(
        cap=cap,
        sticky_max=sticky_max,
        readout=readout,
        metrics_by_id=metrics_by_id,
        session=session,
        audience=audience,
        strategic_context=strategic_context,
        confidence_baseline=confidence_baseline,
        context_document=context_document,
        decided_keys=decided_keys,
        intent_keys=decision_intent_keys,
        take_texts=collect_take_texts(database, arc_id),
    )


def generate_moment_suggestion(
    kind: str, transcript: str, *,
    audience: Optional[str] = None,
    strategic_context: Optional[str] = None,
    context_document: Optional[str] = None,
    trigger: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Optional[dict]:
    """{'why': str, 'replacement': str|None} or None on any miss. Guarded."""
    if kind not in ("emphasize", "replace"):
        return None
    if not isinstance(transcript, str) or not transcript.strip():
        return None
    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_MOMENT_SUGGESTION
        from services.say_it_stronger import _guard_copy

        payload = {
            "kind": kind,
            "moment": transcript.strip()[:600],
            "audience": (audience or "a general professional audience"),
            "reason_flag": trigger or "",
        }
        # ④ step 5 (2026-07-24): the speaker's own setup note, as background
        # only. Omitted when blank so the model isn't handed an empty field.
        if isinstance(strategic_context, str) and strategic_context.strip():
            payload["speaker_intent"] = strategic_context.strip()[:600]
        # X-1 v2 (2026-07-25): an excerpt of the project's context document.
        # Hard-capped: this rides EVERY snippet's prompt, and the stored text
        # can run to 40k chars, so an uncapped paste would multiply token cost
        # by the snippet count.
        if isinstance(context_document, str) and context_document.strip():
            payload["project_background"] = \
                context_document.strip()[:_MAX_DOC_EXCERPT]
        result = chat_complete(
            spec=SPEC_MOMENT_SUGGESTION,
            system=_SYSTEM,
            user=json.dumps(payload, ensure_ascii=False),
            surface="moment_suggestion",
            user_id=user_id,
        )
        parsed = getattr(result, "parsed", None) if result else None
        if not isinstance(parsed, dict):
            return None
        why = _guard_copy((parsed.get("why") or "").strip()) or None
        replacement = None
        if kind == "replace":
            replacement = _guard_copy(
                (parsed.get("replacement") or "").strip()) or None
            if not replacement:
                return None   # a replace star without a replacement is dead
        if not why and not replacement:
            return None
        return {"why": why, "replacement": replacement}
    except Exception as e:
        logger.warning("moment_suggestion: generation failed: %s", e)
        return None


def pick_emphasis_phrase(transcript: str, *,
                         region: Optional[str] = None,
                         cue_keys: Any = None,
                         user_id: Optional[str] = None) -> Optional[str]:
    """The FEW WORDS worth accenting inside one moment, verbatim — or None.

    THE VOCAL HALF (founder 2026-08-15: *"use the verbal and vocal cues of
    what the user said to determine that it was confident or highly engaging,
    not just random"*). `region` and `cue_keys` come from
    services.delivery_cues: which end of the moment the delivery landed on,
    and what the voice measurably did there, both against the speaker's OWN
    baseline. They are EVIDENCE HANDED TO THE MODEL, not a second selector —
    the accent still has to be words that carry meaning, and the prompt is
    told to return nothing when the two halves point at different places
    rather than to accent one on the strength of the other.

    Both are optional and often absent (no baseline yet on a first take, a
    delivery with no standout cue). Absent = judge on the words alone, which
    the prompt is told to do more strictly, not less.

    THE DEFECT THIS CLOSES (founder 2026-08-15): "try not to style the whole
    paragraphs or chunks but key few words or a sentence." An emphasize star
    stored no target at all, so the serve had to guess one from the
    say-it-stronger UPGRADE wordings — a list that is EMPTY by construction
    for a moment delivered well, because say-it-stronger only proposes
    upgrades where the wording is weak. The Confident Voice card fires
    precisely on the moments that have no upgrades, so its narrowing never
    had anything to work with and every one of them bolded the whole piece.
    The target is now chosen here, once, from the moment's own words.

    ANTI-HALLUCINATION PIN, identical to detect_structural_device: the
    returned phrase MUST be a verbatim (case-insensitive) substring of the
    moment, and the MOMENT's own characters are returned, not the model's
    echo. Not a substring → None. It must also be genuinely narrower than
    the moment and of accent width — a model that answers "all of it" has
    not picked anything.

    Skips the call entirely when the moment is ALREADY accent-width: there
    is nothing to narrow, the serve will accent it whole, and this rides
    every emphasize star on every take. Guarded; never raises.
    """
    from services.tracked_changes import is_accent_width

    if not isinstance(transcript, str) or not transcript.strip():
        return None
    moment = transcript.strip()[:600]
    if is_accent_width(moment):
        return None
    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_MOMENT_SUGGESTION
        from services.prompts.moment_suggestions import EMPHASIS_CUE_HINTS

        payload: dict = {"moment": moment}
        # The cue KEYS never ride the prompt: the model is told what the voice
        # DID, in the hint wording that is hash-locked beside the prompt. An
        # unknown key is dropped rather than passed through — a raw key would
        # read to the model as a made-up token.
        #
        # The shape is checked rather than trusted. A malformed cue list is a
        # reason to lose the VOCAL EVIDENCE, never a reason to lose the accent:
        # letting it raise would have dropped the whole pick, and the words
        # alone are still a valid basis (the prompt is told to be stricter
        # when `delivery` is absent).
        _voice = [EMPHASIS_CUE_HINTS[k]
                  for k in (cue_keys if isinstance(cue_keys, (list, tuple))
                            else [])
                  if isinstance(k, str) and k in EMPHASIS_CUE_HINTS]
        _delivery: dict = {}
        if region in ("opening", "closing"):
            _delivery["landed"] = region
        if _voice:
            _delivery["voice"] = _voice
        # Omitted entirely when empty, so "no vocal evidence" reaches the model
        # as an ABSENT field rather than an empty one it might read as a claim.
        if _delivery:
            payload["delivery"] = _delivery
        result = chat_complete(
            spec=SPEC_MOMENT_SUGGESTION,
            system=_EMPHASIS_SYSTEM,
            user=json.dumps(payload, ensure_ascii=False),
            surface="emphasis_phrase",
            user_id=user_id,
        )
        parsed = getattr(result, "parsed", None) if result else None
        if not isinstance(parsed, dict):
            return None
        quote = (parsed.get("quote") or "").strip()
        if not quote or len(quote) >= len(moment):
            return None
        _idx = moment.lower().find(quote.lower())
        if _idx < 0:
            logger.info("emphasis_phrase: quote not verbatim — dropped")
            return None
        quote = moment[_idx:_idx + len(quote)]
        if not is_accent_width(quote):
            logger.info("emphasis_phrase: pick too wide (%d chars) — dropped",
                        len(quote))
            return None
        return quote
    except Exception as e:
        logger.warning("emphasis_phrase: pick failed: %s", e)
        return None


_STRUCT_DEVICES = ("contrast", "list_of_three")


def detect_structural_device(transcript: str, *,
                             user_id: Optional[str] = None) -> Optional[dict]:
    """{'device': 'contrast'|'list_of_three', 'quote': <verbatim>} or None.

    ANTI-HALLUCINATION PIN (founder 2026-07-18): the returned quote MUST be a
    verbatim (case-insensitive) substring of the transcript. Not a substring
    → dropped, no star — the model cannot invent evidence. Guarded, never
    raises."""
    if not isinstance(transcript, str) or not transcript.strip():
        return None
    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_MOMENT_SUGGESTION

        result = chat_complete(
            spec=SPEC_MOMENT_SUGGESTION,
            system=_STRUCT_SYSTEM,
            user=transcript.strip()[:600],
            surface="structural_star",
            user_id=user_id,
        )
        parsed = getattr(result, "parsed", None) if result else None
        if not isinstance(parsed, dict):
            return None
        device = (parsed.get("device") or "").strip().lower()
        quote = (parsed.get("quote") or "").strip()
        if device not in _STRUCT_DEVICES or not quote:
            return None
        # THE pin: the quote must literally occur in the transcript.
        _idx = transcript.lower().find(quote.lower())
        if _idx < 0:
            logger.info("structural_star: quote not verbatim — dropped")
            return None
        # Take the TRANSCRIPT's own characters at the matched span, not the
        # model's echo: the match is case-insensitive, so the model can
        # return "it's not about speed..." for a passage that actually began
        # capitalised. The FE displays this quote as-is, so "verbatim" has
        # to mean character-for-character what the speaker said.
        quote = transcript[_idx:_idx + len(quote)]
        return {"device": device, "quote": quote}
    except Exception as e:
        logger.warning("structural_star: detection failed: %s", e)
        return None


def _structural_stars_enabled() -> bool:
    import os
    return (os.getenv("STRUCTURAL_STARS_ENABLED") or "0").strip().lower() \
        in ("1", "true", "yes")


def _generate_structural(database, arc_id, candidates, *,
                         user_id=None) -> int:
    """Detect + persist structural stars for the no-acoustic-star snippets,
    capped, flag-gated. `why` = the verbatim quote (the user's own words —
    transcript-digit exempt, same precedent as transcript display), no
    replacement, trigger = the device. Returns how many stored."""
    if not _structural_stars_enabled() or not arc_id or not candidates:
        return 0
    try:
        from config import Config
        _cap = max(0, int(Config().STRUCTURAL_STARS_MAX_PER_TAKE))
    except Exception:
        _cap = 2
    if _cap <= 0:
        return 0
    # CONCURRENCY GROUP 2 (founder 2026-08-12, approved after the timing line
    # put `finalizing` at 24.9s on a six-snippet take). Each candidate is an
    # independent LLM call; they were running one after another.
    #
    # IN WAVES OF THE REMAINING CAP, not one big fan-out. The sequential loop
    # BREAKS as soon as `stored` reaches the cap, so firing every candidate at
    # once would spend model calls on results that are thrown away — trading
    # cost for latency without saying so. A wave asks for exactly as many as
    # are still needed: the common case (every candidate yields a device) is
    # one wave and no waste at all, and the worst case is one extra wave's
    # worth, not N.
    #
    # DOCUMENT ORDER SURVIVES. `run_in_parallel` returns results in submission
    # order, so the stars stored are still the FIRST `_cap` candidates that
    # yield a device — identical to the sequential outcome, which is what
    # keeps two runs of the same take producing the same stars.
    #
    # The DETECTION is parallel; the WRITES stay sequential. They are cheap,
    # they must respect the cap in order, and a shared counter across threads
    # is exactly the sort of thing that makes a cap approximate.
    from services.parallel import run_in_parallel

    def _detect(transcript):
        def _run():
            try:
                return detect_structural_device(transcript, user_id=user_id)
            except Exception as e:
                logger.warning("structural_star: detect failed: %s", e)
                return None
        return _run

    stored = 0
    at = 0
    while at < len(candidates) and stored < _cap:
        wave = candidates[at:at + (_cap - stored)]
        at += len(wave)
        found_all = run_in_parallel(*[_detect(t) for _sid, t in wave])
        for (snip_id, _t), found in zip(wave, found_all):
            if stored >= _cap:
                break
            if not found:
                continue
            try:
                if database.upsert_moment_suggestion(
                        snip_id, str(arc_id), "structure",
                        None, found["quote"], found["device"]):
                    stored += 1
            except Exception as e:
                logger.warning("structural_star: snippet failed snip=%s: %s",
                               snip_id, e)
                continue
    if stored:
        logger.info("structural_star: stored %d arc=%s", stored, arc_id)
    return stored


def _delivery_stars_enabled() -> bool:
    import os
    return (os.getenv("DELIVERY_STARS_ENABLED") or "0").strip().lower() \
        in ("1", "true", "yes")


def _generate_delivery(database, arc_id, candidates, baseline, *,
                       cue_baseline=None,
                       metrics_by_id=None) -> list:
    """Measured delivery stars (founder 2026-07-18): deterministic, no LLM.
    ``candidates`` = [(snip_id, features_dict), ...] for the snippets with
    NO acoustic star. Persists up to DELIVERY_STARS_MAX_PER_TAKE rows
    (kind='delivery', trigger=device, no replacement, no why — the FE
    renders the approved copy from `device`). Returns the snip_ids that
    got a delivery star (so structural skips them — never double-star).

    THE PRAISE HALF (founder 2026-08-15): *"if the delivery was impeccable,
    just give them the feedback in the praise lane."* Checked FIRST, and it
    SHORT-CIRCUITS the issue detector, which is the whole point.
    ``detect_delivery_issue`` is one-sided by construction — it looks only
    for flatness, rushing, dragging and over-pausing — so on a moment
    delivered well it either finds nothing or, worse, returns whichever
    complaint was least far from its threshold. Handing that to somebody who
    just nailed it is exactly the note the founder asked to replace.

    The praise is decided by services.delivery_cues.is_impeccable, which
    reads the FULL seven-cue set against the speaker's own confidence
    baseline rather than this module's four one-sided z-tests, and the cues
    that earned it are stored with the row so the line can cite its
    evidence instead of asserting it."""
    if not _delivery_stars_enabled() or not arc_id \
            or not candidates or not baseline:
        return []
    from services.delivery_cues import cue_keys_for_piece, is_impeccable
    from services.delivery_stars import detect_delivery_issue
    try:
        from config import Config
        _cap = max(0, int(Config().DELIVERY_STARS_MAX_PER_TAKE))
        _z = float(Config().DELIVERY_STAR_Z)
    except Exception:
        _cap, _z = 3, 1.2
    if _cap <= 0:
        return []
    starred: list = []
    praised = 0
    for snip_id, feats in candidates:
        if len(starred) >= _cap:
            break
        try:
            # The praise gate reads the RAW metrics when we have them — the
            # same blob the confidence baseline was built from — so cue and
            # baseline are measured off one source. `feats` (the readout
            # spelling) is the fallback; normalize_features folds both.
            _pm = (metrics_by_id or {}).get(str(snip_id)) or feats
            _score = None
            if isinstance(_pm, dict) \
                    and isinstance(_pm.get("voice_confidence"), dict):
                _score = _pm["voice_confidence"].get("score")
            _cues: list = []
            device = None
            if is_impeccable(_pm, cue_baseline, confidence_score=_score):
                device = "impeccable"
                _cues = cue_keys_for_piece(_pm, cue_baseline)
            else:
                device = detect_delivery_issue(feats, baseline,
                                               z_threshold=_z)
            if not device:
                continue
            if database.upsert_moment_suggestion(
                    snip_id, str(arc_id), "delivery", None, None, device,
                    cue_keys=(_cues or None)):
                starred.append(snip_id)
                if device == "impeccable":
                    praised += 1
        except Exception as e:
            logger.warning("delivery_star: snippet failed snip=%s: %s",
                           snip_id, e)
            continue
    if starred:
        logger.info("delivery_star: stored %d arc=%s (praise=%d)",
                    len(starred), arc_id, praised)
    return starred


@dataclass(frozen=True)
class _AcousticCandidatePlan:
    """One snippet's acoustic-lane decision, before any write."""

    outcome: str
    snippet_id: Optional[str] = None
    transcript: str = ""
    features: Any = None
    kind: Optional[str] = None
    trigger: Optional[str] = None

    def unstarred(self) -> Optional[tuple[str, str, Any]]:
        if self.outcome not in {
            "no_conf_read", "decided", "decided_intent", "protected"
        }:
            return None
        if self.snippet_id is None:
            return None
        return self.snippet_id, self.transcript, self.features or {}


def _classify_acoustic_candidate(
    snippet: dict[str, Any],
    context: _GenerationContext,
    stored: int,
    session_id: str,
) -> _AcousticCandidatePlan:
    """Resolve acoustic routing without generating copy or writing rows."""
    from services.ideal_decision_ledger import (
        lane_class,
        normalize_phrase,
    )
    from services.moment_confidence import (
        UNCONFIDENT,
        resolve_moment_confidence,
        resolve_suggestion_kind,
    )
    from services.protected_phrases import phrase_recurs
    from services.text_flags import has_profanity

    snippet_id = snippet.get("id")
    transcript = (snippet.get("transcript") or "").strip()
    features = snippet.get("features") or {}
    if not snippet_id or not transcript:
        return _AcousticCandidatePlan("no_text")
    snippet_id = str(snippet_id)

    metrics = context.metrics_by_id.get(snippet_id)
    confidence = resolve_moment_confidence(metrics)
    stickiness = snippet.get("slide_stickiness")
    if isinstance(stickiness, dict):
        stickiness = stickiness.get("composite")
    kind = resolve_suggestion_kind(
        confidence,
        transcript,
        slide_stickiness=stickiness,
        stickiness_max=context.sticky_max,
    )
    if kind is None:
        return _AcousticCandidatePlan(
            "no_conf_read", snippet_id, transcript, features)
    if stored >= context.cap:
        logger.info(
            "moment_suggestion: acoustic cap %d hit sid=%s",
            context.cap,
            session_id,
        )
        return _AcousticCandidatePlan("capped")
    if (kind, normalize_phrase(transcript)) in context.decided_keys:
        return _AcousticCandidatePlan(
            "decided", snippet_id, transcript, features)

    piece = metrics.get("piece") if isinstance(metrics, dict) else None
    slide_index = piece.get("slide_index") \
        if isinstance(piece, dict) else None
    if (
        isinstance(slide_index, int)
        and not isinstance(slide_index, bool)
        and (slide_index, lane_class(kind)) in context.intent_keys
    ):
        return _AcousticCandidatePlan(
            "decided_intent", snippet_id, transcript, features)

    if (
        kind == "replace"
        and confidence is None
        and not has_profanity(transcript)
        and phrase_recurs(transcript, context.take_texts)
    ):
        return _AcousticCandidatePlan(
            "protected", snippet_id, transcript, features)

    trigger = (
        "unconfident" if confidence == UNCONFIDENT
        else "profanity" if has_profanity(transcript)
        else "stickiness" if kind == "replace"
        else "confident"
    )
    return _AcousticCandidatePlan(
        "candidate", snippet_id, transcript, features, kind, trigger)


def _generate_acoustic_candidate(
    plan: _AcousticCandidatePlan,
    context: _GenerationContext,
) -> Optional[dict[str, Any]]:
    """Generate one candidate without touching shared persistence state."""
    if plan.kind is None or plan.trigger is None or plan.snippet_id is None:
        return None
    if plan.trigger == "confident":
        generated = {"why": CONFIDENT_VOICE_WHY, "replacement": None}
    else:
        generated = generate_moment_suggestion(
            plan.kind,
            plan.transcript,
            audience=context.audience,
            strategic_context=context.strategic_context,
            context_document=context.context_document,
            trigger=plan.trigger,
            user_id=context.session.get("user_id"),
        )
    if not generated:
        return None

    cue_keys: list = []
    emphasis_quote = None
    if plan.kind == "emphasize":
        piece_metrics = context.metrics_by_id.get(plan.snippet_id)
        try:
            from services.delivery_cues import accent_region, cue_keys_for_piece

            cue_keys = cue_keys_for_piece(
                piece_metrics, context.confidence_baseline)
            region = accent_region(
                piece_metrics, context.confidence_baseline)
        except Exception as cue_error:
            logger.warning(
                "moment_suggestion: cues failed snip=%s: %s",
                plan.snippet_id,
                cue_error,
            )
            cue_keys, region = [], None
        emphasis_quote = pick_emphasis_phrase(
            plan.transcript,
            region=region,
            cue_keys=cue_keys,
            user_id=context.session.get("user_id"),
        )

    return {
        "replacement": generated.get("replacement"),
        "why": generated.get("why"),
        "emphasis_quote": emphasis_quote,
        "cue_keys": cue_keys or None,
    }


def _persist_generated_acoustic_candidate(
    plan: _AcousticCandidatePlan,
    generated: dict[str, Any],
    arc_id: str,
    database: Any,
) -> bool:
    """Persist one generated candidate; callers retain document ordering."""
    if plan.kind is None or plan.trigger is None or plan.snippet_id is None:
        return False

    return bool(database.upsert_moment_suggestion(
        plan.snippet_id,
        arc_id,
        plan.kind,
        generated.get("replacement"),
        generated.get("why"),
        plan.trigger,
        emphasis_quote=generated.get("emphasis_quote"),
        cue_keys=generated.get("cue_keys"),
    ))


def _resolve_delivery_baseline_and_capture_arousal(
    context: _GenerationContext,
    database: Any,
) -> Any:
    """Resolve delivery reference and persist its private arousal axis."""
    from services.delivery_stars import arousal_z, resolve_delivery_baseline

    snippets = context.readout.get("snippets") or []
    baseline = resolve_delivery_baseline(
        context.session.get("user_id"),
        [snippet.get("features") or {} for snippet in snippets],
        database=database,
    )
    if not baseline:
        return baseline
    for snippet in snippets:
        try:
            snippet_id = str(snippet.get("id") or "")
            activation = arousal_z(
                snippet.get("features") or {}, baseline)
            if snippet_id and activation is not None:
                database.set_snippet_arousal(snippet_id, activation)
        except Exception:
            continue
    return baseline


def generate_for_session(session_id: str, arc_id: Optional[str], *,
                         database=None) -> int:
    """Analysis-time hook (flag-gated at the caller): resolve + generate +
    persist suggestions for one take's snippets. Live resolution is strictly
    machine-read/profanity/stickiness. Blind peer ratings, whenever collected
    later, stay in the internal corpus and cannot alter this suggestion. A
    later coach-verified star supersedes at serve. Capped per take
    (MOMENT_SUGGESTIONS_MAX_PER_TAKE). Returns the number stored."""
    if not session_id or not arc_id:
        return 0
    try:
        if database is None:
            from services.db import db as database

        context = _load_generation_context(
            session_id, str(arc_id), database)
        readout = context.readout
        _metrics_by_id = context.metrics_by_id
        session = context.session
        _vc_baseline = context.confidence_baseline

        stored = 0
        # ── FUNNEL COUNTERS (2026-08-10) ──────────────────────────────
        # WHY. This generator went silent on 2026-08-03 and nobody could
        # tell WHY for a week: every way it declines to star a snippet is a
        # bare `continue`, and the only signal it emits is "stored N" — which
        # it does not emit at all when N is 0. Zero stars and zero snippets
        # looked identical from outside, as did "the LLM returned nothing"
        # and "the ledger already decided this phrase".
        #
        # Counting the drops costs nothing and turns the silence into a
        # sentence. Named for the reason, not the line number, so the log
        # says which stage ate the candidates.
        _seen = 0            # snippets the readout handed us
        _no_text = 0         # no id or empty transcript
        _capped = 0          # over MOMENT_SUGGESTIONS_MAX_PER_TAKE
        _decided = 0         # decision ledger: already approved/dismissed
        _decided_intent = 0  # §12.3 intent key: same slide+class decided
        _no_gen = 0          # generation returned nothing (LLM or guard)
        _errored = 0         # per-snippet exception, swallowed below
        # ── THE CONFIDENCE-GAP COUNTER (founder 2026-08-13, corrected same
        # evening). One counter, not two: `resolve_suggestion_kind` returns
        # None ONLY when confidence is None (both REPLACE triggers that do
        # not need confidence fire regardless), so the "measured but no
        # star" case is unreachable by construction — the audit caught the
        # second counter as dead code and it was removed.
        #
        # READ no_conf_read HONESTLY: the dead zone (voice_confidence
        # _DEAD_ZONE=0.25) puts roughly 40-50%% of a HEALTHY take's pieces at
        # exactly 0.0, which resolves to None here. no_conf_read ≈ seen is
        # the NORMAL shape of a quiet, well-delivered take — it is a broken
        # stamp only when it holds across MANY takes AND voice_metrics are
        # otherwise present.
        _no_conf_read = 0    # no lean available (unstamped / dead zone)

        # Snippets with NO acoustic star → candidates for a DELIVERY star
        # (measured, deterministic), then a STRUCTURAL star. Priority per
        # founder 2026-07-18: acoustic > delivery > structural; a snippet
        # only ever carries ONE star.
        _unstarred = []   # (snip_id, transcript, features_dict)

        # Acoustic candidates are independent model calls, but the cap and
        # write order are product policy. Generate in waves no larger than the
        # remaining cap, then persist in document order. This is the same
        # bounded/order-preserving contract used by the structural lane: no
        # candidate is added or removed, failed generations still open a slot
        # for the next candidate, and shared database state stays single-
        # threaded.
        from services.parallel import run_in_parallel

        snippets = list(readout.get("snippets") or [])
        cursor = 0
        while cursor < len(snippets):
            wave: list[tuple[dict[str, Any], _AcousticCandidatePlan]] = []
            wave_limit = max(1, context.cap - stored)
            while cursor < len(snippets) and len(wave) < wave_limit:
                snip = snippets[cursor]
                cursor += 1
                _seen += 1
                try:
                    plan = _classify_acoustic_candidate(
                        snip, context, stored, session_id)
                    unstarred = plan.unstarred()
                    if unstarred is not None:
                        _unstarred.append(unstarred)
                    if plan.outcome == "no_text":
                        _no_text += 1
                        continue
                    if plan.outcome == "no_conf_read":
                        _no_conf_read += 1
                        continue
                    if plan.outcome == "capped":
                        _capped += 1
                        continue
                    if plan.outcome == "decided":
                        _decided += 1
                        continue
                    if plan.outcome == "decided_intent":
                        _decided_intent += 1
                        continue
                    if plan.outcome == "protected":
                        continue
                    wave.append((snip, plan))
                except Exception as snippet_error:
                    _errored += 1
                    logger.warning(
                        "moment_suggestion: snippet failed sid=%s snip=%s: %s",
                        session_id, snip.get("id"), snippet_error)

            def _generate(plan: _AcousticCandidatePlan):
                def _run():
                    try:
                        return (
                            _generate_acoustic_candidate(plan, context),
                            None,
                        )
                    except Exception as generation_error:
                        return None, generation_error

                return _run

            generated_wave = run_in_parallel(
                *[_generate(plan) for _snip, plan in wave]
            )
            for (snip, plan), (generated, generation_error) in zip(
                    wave, generated_wave):
                if generation_error is not None:
                    _errored += 1
                    logger.warning(
                        "moment_suggestion: snippet failed sid=%s snip=%s: %s",
                        session_id, snip.get("id"), generation_error)
                    continue
                if generated is None:
                    _no_gen += 1
                    continue
                try:
                    if _persist_generated_acoustic_candidate(
                            plan, generated, str(arc_id), database):
                        stored += 1
                except Exception as persistence_error:
                    _errored += 1
                    logger.warning(
                        "moment_suggestion: snippet failed sid=%s snip=%s: %s",
                        session_id, snip.get("id"), persistence_error)

        # ── Delivery stars, SECOND (founder decisions 2026-07-18):
        # deterministic vs the speaker's own reference — cross-take baseline
        # first, else within-take means at >= 6 pieces (decision BE-1a(b)),
        # else silent. No LLM. Only no-acoustic-star snippets.
        from services.delivery_stars import emphasis_z

        _baseline = _resolve_delivery_baseline_and_capture_arousal(
            context, database)

        # ── Arousal capture (founder 2026-07-24, capture-first / surface-
        # later): a baseline-relative ACTIVATION read per snippet, stored for
        # the coach-labeled learning loop to weight later. NEVER surfaced to a
        # user and NEVER fed into ranking (activation is not quality). Reads
        # the arousal axis only (calm↔activated), never a discrete emotion.
        # Best-effort per snippet — a pending migration or any error is
        # swallowed and never disturbs the suggestion path.
        # ── Congruence delivery star, BEFORE the deterministic ones (founder
        # 2026-07-24 sign-off): the content-aware member of the delivery family
        # — upbeat words over a flat/low-arousal delivery (arousal_z low + a
        # positive-content model gate). Runs first so it claims its moment
        # (one-star-per-piece) rather than being masked by a plain `emphasis`.
        # Flag-gated; surfaces only {kind:'delivery', device:'congruence'}
        # (AC-9); best-effort — never disturbs the rest of the path.
        _congruence_starred: set = set()
        try:
            from services.delivery_alignment import (
                delivery_alignment_enabled, generate_congruence_stars,
            )
            if delivery_alignment_enabled():
                _congruence_starred = set(generate_congruence_stars(
                    database, arc_id, _unstarred, _baseline,
                    user_id=session.get("user_id")))
                stored += len(_congruence_starred)
        except Exception as _cong_err:
            logger.warning("moment_suggestion: congruence failed sid=%s: %s",
                           session_id, _cong_err)

        _deliv = set(_generate_delivery(
            database, arc_id,
            [(sid, feats) for (sid, _t, feats) in _unstarred
             if sid not in _congruence_starred],
            _baseline,
            # The praise half reads the CONFIDENCE baseline, not the delivery
            # one: those are different feature sets with different floors, and
            # "impeccable" is a claim about the confidence cues.
            cue_baseline=_vc_baseline,
            metrics_by_id=_metrics_by_id))
        stored += len(_deliv)
        # congruence IS a delivery star → fold it in so structural skips it too.
        _delivery_starred = _congruence_starred | _deliv

        # ── Structural stars, THIRD (flag-gated; verbatim-quote pinned).
        # Structural INTENSITY (founder #5): scan the flattest-delivered
        # candidates FIRST — a contrast already delivered with lift needs no
        # practice prompt; a flat one does. Unmeasurable flatness sorts last.
        _structural_candidates = [
            (sid, transcript, emphasis_z(feats, _baseline))
            for (sid, transcript, feats) in _unstarred
            if sid not in _delivery_starred
        ]
        _structural_candidates.sort(
            key=lambda t: t[2] if t[2] is not None else float("inf"))
        stored += _generate_structural(
            database, arc_id,
            [(sid, transcript) for (sid, transcript, _z) in
             _structural_candidates],
            user_id=session.get("user_id"))

        # ── THE FUNNEL LINE. Logged ALWAYS, especially at zero. ────────
        #
        # The `if stored:` guard this replaces is the exact reason a week of
        # silence was unreadable: the one moment worth a log line is the one
        # where nothing was produced, and that was the only case it stayed
        # quiet for. A diagnostic that speaks only on success reports that
        # the system is fine right up until you need it.
        #
        # Read it as a funnel, left to right: how many snippets arrived, how
        # many each stage dropped, how many stars came out. `seen=0` is a
        # transcription/snippet problem, not a star problem. `seen>0 stored=0`
        # with everything else zero means every candidate fell through the
        # acoustic/delivery/structural lanes on their own thresholds, which
        # is a legitimate outcome and now a visible one.
        #
        logger.info(
            "moment_suggestion: sid=%s arc=%s seen=%d stored=%d "
            "(no_text=%d capped=%d decided=%d decided_intent=%d no_gen=%d "
            "errored=%d) "
            "unstarred=%d (no_conf_read=%d)",
            session_id, arc_id, _seen, stored,
            _no_text, _capped, _decided, _decided_intent, _no_gen, _errored,
            len(_unstarred),
            _no_conf_read)
        return stored
    except Exception as e:
        logger.warning("moment_suggestion: session pass failed sid=%s: %s",
                       session_id, e)
        return 0
