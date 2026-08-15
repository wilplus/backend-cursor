"""Star-suggestion generation (founder 2026-07-18).

After a take's analysis, each notable snippet (resolved by
services.moment_confidence: panel label → machine read; replace triggers:
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


def _generate_delivery(database, arc_id, candidates, baseline) -> list:
    """Measured delivery stars (founder 2026-07-18): deterministic, no LLM.
    ``candidates`` = [(snip_id, features_dict), ...] for the snippets with
    NO acoustic star. Persists up to DELIVERY_STARS_MAX_PER_TAKE rows
    (kind='delivery', trigger=device, no replacement, no why — the FE
    renders the approved copy from `device`). Returns the snip_ids that
    got a delivery star (so structural skips them — never double-star)."""
    if not _delivery_stars_enabled() or not arc_id \
            or not candidates or not baseline:
        return []
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
    for snip_id, feats in candidates:
        if len(starred) >= _cap:
            break
        try:
            device = detect_delivery_issue(feats, baseline, z_threshold=_z)
            if not device:
                continue
            if database.upsert_moment_suggestion(
                    snip_id, str(arc_id), "delivery", None, None, device):
                starred.append(snip_id)
        except Exception as e:
            logger.warning("delivery_star: snippet failed snip=%s: %s",
                           snip_id, e)
            continue
    if starred:
        logger.info("delivery_star: stored %d arc=%s", len(starred), arc_id)
    return starred


def generate_for_session(session_id: str, arc_id: Optional[str], *,
                         database=None) -> int:
    """Analysis-time hook (flag-gated at the caller): resolve + generate +
    persist suggestions for one take's snippets. NO HUMAN LABEL EXISTS AT
    RECORD TIME — neither a coach tag nor a blind panel rating, both of which
    arrive later — so resolution here is machine-read/profanity/stickiness and
    the panel argument is None by construction, not by oversight. A later
    coach-verified star supersedes at serve. Capped per take
    (MOMENT_SUGGESTIONS_MAX_PER_TAKE). Returns the number stored."""
    if not session_id or not arc_id:
        return 0
    try:
        if database is None:
            from services.db import db as database
        from config import Config
        from services.lab_recording import build_readout_from_session
        from services.moment_confidence import (
            UNCONFIDENT, resolve_moment_confidence, resolve_suggestion_kind,
        )

        try:
            _cap = max(1, int(Config().MOMENT_SUGGESTIONS_MAX_PER_TAKE))
        except Exception:
            _cap = 8
        try:
            _sticky_max = max(
                0, int(Config().MOMENT_REPLACE_STICKINESS_MAX_PCT)) / 100.0
        except Exception:
            _sticky_max = 0.15

        # Coach-view readout = full metrics (acoustic_read + stickiness).
        # Internal read only — nothing here is a user payload.
        readout = build_readout_from_session(
            session_id, include_slide_scores=True)
        # The confidence composite comes from the SNIPPET ROWS, not the
        # readout, and the extra read is the price of a fence rather than an
        # oversight. The readout serializer is an allowlist that deliberately
        # carries no confidence blob on EITHER branch: putting one on the
        # coach packet would show a rater the machine's read of a clip they
        # are supposed to judge blind (test_voice_confidence pins this at
        # source level). Reading the metrics here keeps the routing input on
        # the machine side of that wall.
        _metrics_by_id: dict = {}
        try:
            for _row in (database.get_snippets_by_session(session_id) or []):
                _rm = _row.get("metrics")
                _metrics_by_id[str(_row.get("id"))] = (
                    _rm if isinstance(_rm, dict) else {})
        except Exception as _m_err:
            logger.warning("moment_suggestion: metrics read failed sid=%s: %s",
                           session_id, _m_err)
        session = {}
        try:
            session = database.v2_get_session_by_id(session_id) or {}
        except Exception:
            pass
        ctx = session.get("intake_context") \
            if isinstance(session.get("intake_context"), dict) else {}
        audience = (ctx or {}).get("audience") or None
        strategic_context = (ctx or {}).get("strategic_context") or None

        # ── THE VOCAL EVIDENCE (founder 2026-08-15) ───────────────────────
        # "use the verbal and vocal cues of what the user said to determine
        # that it was confident … not just random."
        #
        # Resolved ONCE per take, exactly as lab_recording resolves it for the
        # composite — same functions, same order (sex after the baseline,
        # because the acoustic fallback reads the speaker's baseline mean f0).
        # Reading it here rather than trusting the stamped blob keeps the cue
        # ORDER available, which is the thing the composite throws away.
        #
        # Best-effort and often absent: a first take has no baseline, and an
        # absent baseline means no cues and no region — which the picker is
        # told to treat as "judge on the words alone, stricter", never as
        # permission to guess a half of the moment.
        _vc_baseline = None
        _vc_sex = None
        try:
            from services.voice_confidence import (
                resolve_confidence_baseline, resolve_take_sex,
            )
            _vc_baseline, _ = resolve_confidence_baseline(
                session.get("user_id"),
                [_m for _m in _metrics_by_id.values() if isinstance(_m, dict)],
            )
            _vc_sex, _ = resolve_take_sex(
                session.get("user_id"), ctx, _vc_baseline,
            )
        except Exception as _vc_err:
            logger.warning(
                "moment_suggestion: cue baseline failed sid=%s: %s",
                session_id, _vc_err)

        # X-1 v2 (2026-07-25): the context DOCUMENT the user attached to this
        # project (a brief / case metrics / Q&A). Arc-scoped, fetched once per
        # take and passed to each snippet's generation exactly like `audience`.
        # BACKGROUND only — it informs the qualitative suggestion so a
        # replacement phrase can use the project's real terminology instead of
        # inventing one. It never becomes the verbatim ideal text (L1), and the
        # excerpt is hard-capped because this rides every snippet's prompt.
        context_document = None
        if arc_id:
            try:
                _doc = database.get_arc_context_document(arc_id) or {}
                context_document = (_doc.get("text") or "").strip() or None
            except Exception as _doc_err:
                logger.warning(
                    "moment_suggestions: context doc read failed arc=%s: %s",
                    arc_id, _doc_err)

        # Decision ledger (founder 2026-07-20): phrases the student already
        # decided on (approved → baked / dismissed → remembered) never
        # regenerate. Best-effort — empty pre-migration.
        from services.ideal_decision_ledger import (
            intent_keys, lane_class as _lane_class,
            ledger_keys, normalize_phrase as _norm_phrase,
        )
        try:
            _ledger_rows = database.list_ideal_decisions(str(arc_id))
            _decided_keys = ledger_keys(_ledger_rows)
            # §12.3 — the INTENT keys beside the phrase keys: a decided
            # (slide, class) pair blocks regeneration however the LLM
            # rephrases the words on the next take (field report #4 — the
            # phrase-drift zombies).
            _intent_keys = intent_keys(_ledger_rows)
        except Exception:
            _decided_keys = set()
            _intent_keys = set()

        # Protected phrases (founder 2026-07-20, rule 4a): wording the
        # speaker repeats across takes is THEIR voice — stickiness
        # replaces never target it. Threat/profanity keep their carve-out
        # (harmful content is still flagged). Best-effort: [] → no
        # protection, today's behavior.
        from services.protected_phrases import (
            collect_take_texts, phrase_recurs,
        )
        _take_texts = collect_take_texts(database, arc_id)

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
        for snip in (readout.get("snippets") or []):
            _seen += 1
            try:
                snip_id = snip.get("id")
                transcript = (snip.get("transcript") or "").strip()
                if not snip_id or not transcript:
                    _no_text += 1
                    continue
                # Panel is None at record time (see the docstring) — the
                # blind raters have not seen this clip yet, so the machine
                # read is the only source there is.
                confidence = resolve_moment_confidence(
                    None, _metrics_by_id.get(str(snip_id)))
                _stick = snip.get("slide_stickiness")
                if isinstance(_stick, dict):
                    _stick = _stick.get("composite")
                kind = resolve_suggestion_kind(
                    confidence, transcript,
                    slide_stickiness=_stick, stickiness_max=_sticky_max)
                if kind is None:
                    _no_conf_read += 1     # the only reachable reason
                    _unstarred.append((str(snip_id), transcript,
                                       snip.get("features") or {}))
                    continue
                if stored >= _cap:
                    _capped += 1
                    logger.info(
                        "moment_suggestion: acoustic cap %d hit sid=%s",
                        _cap, session_id)
                    continue   # keep scanning: later snippets may be
                    #            structural candidates (a different budget)
                # DECISION LEDGER (founder 2026-07-20, rules 2/3): a phrase
                # the student already decided on — approved (baked at
                # assembly) or dismissed — is never re-offered; each
                # version's stars are its delta only. The snippet still
                # counts as unstarred for the delivery/structural lanes
                # (those are behavioural prompts, not text edits).
                if (kind, _norm_phrase(transcript)) in _decided_keys:
                    _decided += 1
                    _unstarred.append((str(snip_id), transcript,
                                       snip.get("features") or {}))
                    continue
                # §12.3 — THE INTENT KEY (founder 2026-08-14). The phrase
                # gate above dies the moment the LLM rewords: take 2's
                # snippet carries fresh words, the normalized phrase no
                # longer matches, and a suggestion the student already
                # declined comes back in new clothes (field report #4).
                # Same slide + same class = same intent, blocked — the
                # student un-blocks by reverting the decision, never the
                # machine by paraphrasing.
                _mtx_i = _metrics_by_id.get(str(snip_id))
                _piece_i = (_mtx_i or {}).get("piece") \
                    if isinstance(_mtx_i, dict) else None
                _slide_i = _piece_i.get("slide_index") \
                    if isinstance(_piece_i, dict) else None
                if isinstance(_slide_i, int) \
                        and not isinstance(_slide_i, bool) \
                        and (_slide_i, _lane_class(kind)) in _intent_keys:
                    _decided_intent += 1
                    _unstarred.append((str(snip_id), transcript,
                                       snip.get("features") or {}))
                    continue
                from services.text_flags import has_profanity
                # Rule 4a: a STICKINESS replace (no confidence lean, no
                # profanity) on wording the speaker uses in >= 2 takes is
                # their voice — never forced. An unconfident read and
                # profanity still replace (the harmful carve-out). The
                # snippet stays eligible for the behavioural lanes.
                if kind == "replace" and confidence is None \
                        and not has_profanity(transcript) \
                        and phrase_recurs(transcript, _take_texts):
                    _unstarred.append((str(snip_id), transcript,
                                       snip.get("features") or {}))
                    continue
                # THE PERSISTED TRIGGER VOCABULARY MOVED WITH THE CONSTRUCT
                # (founder 2026-08-13): 'threat' → 'unconfident', 'charisma'
                # → 'confident'. New rows only — historical rows keep the
                # words they were written with and stay interpretable, per
                # the standing rule that detector definitions are versioned,
                # never overwritten in place. services/intervention_
                # candidates.py reads both vocabularies for that reason.
                trigger = ("unconfident" if confidence == UNCONFIDENT
                           else "profanity" if has_profanity(transcript)
                           else "stickiness" if kind == "replace"
                           else "confident")
                if trigger == "confident":
                    # Confident Voice (§17 acoustic-confidence-v1): the
                    # signed body, no LLM call — deterministic and free.
                    gen = {"why": CONFIDENT_VOICE_WHY, "replacement": None}
                else:
                    gen = generate_moment_suggestion(
                        kind, transcript, audience=audience,
                        strategic_context=strategic_context,
                        context_document=context_document, trigger=trigger,
                        user_id=session.get("user_id"))
                if not gen:
                    _no_gen += 1
                    continue
                # THE ACCENT TARGET (founder 2026-08-15). Picked here, on
                # the moment's own words AND on what the voice did with them,
                # so the serve narrows to a phrase instead of falling back to
                # the whole chunk — and narrows to the phrase the delivery
                # actually landed on rather than to a plausible one. Costs
                # nothing on a moment that is already accent-width, and a None
                # simply leaves the serve's own narrowing to try.
                _cue_keys: list = []
                _emph_quote = None
                if kind == "emphasize":
                    _pm = _metrics_by_id.get(str(snip_id))
                    try:
                        from services.delivery_cues import (
                            accent_region, cue_keys_for_piece,
                        )
                        _cue_keys = cue_keys_for_piece(
                            _pm, _vc_baseline, _vc_sex)
                        _region = accent_region(_pm, _vc_baseline, _vc_sex)
                    except Exception as _cue_err:
                        logger.warning(
                            "moment_suggestion: cues failed snip=%s: %s",
                            snip_id, _cue_err)
                        _cue_keys, _region = [], None
                    _emph_quote = pick_emphasis_phrase(
                        transcript, region=_region, cue_keys=_cue_keys,
                        user_id=session.get("user_id"))
                if database.upsert_moment_suggestion(
                        str(snip_id), str(arc_id), kind,
                        gen.get("replacement"), gen.get("why"), trigger,
                        emphasis_quote=_emph_quote,
                        cue_keys=(_cue_keys or None)):
                    stored += 1
            except Exception as _snip_err:
                _errored += 1
                logger.warning(
                    "moment_suggestion: snippet failed sid=%s snip=%s: %s",
                    session_id, snip.get("id"), _snip_err)
                continue

        # ── Delivery stars, SECOND (founder decisions 2026-07-18):
        # deterministic vs the speaker's own reference — cross-take baseline
        # first, else within-take means at >= 6 pieces (decision BE-1a(b)),
        # else silent. No LLM. Only no-acoustic-star snippets.
        from services.delivery_stars import (
            arousal_z, emphasis_z, resolve_delivery_baseline,
        )
        _baseline = resolve_delivery_baseline(
            session.get("user_id"),
            [s.get("features") or {}
             for s in (readout.get("snippets") or [])],
            database=database)

        # ── Arousal capture (founder 2026-07-24, capture-first / surface-
        # later): a baseline-relative ACTIVATION read per snippet, stored for
        # the coach-labeled learning loop to weight later. NEVER surfaced to a
        # user and NEVER fed into ranking (activation is not quality). Reads
        # the arousal axis only (calm↔activated), never a discrete emotion.
        # Best-effort per snippet — a pending migration or any error is
        # swallowed and never disturbs the suggestion path.
        if _baseline:
            for _snip in (readout.get("snippets") or []):
                try:
                    _sid = str(_snip.get("id") or "")
                    _av = arousal_z(_snip.get("features") or {}, _baseline)
                    if _sid and _av is not None:
                        database.set_snippet_arousal(_sid, _av)
                except Exception:
                    continue

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
            _baseline))
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
