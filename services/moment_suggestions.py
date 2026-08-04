"""Star-suggestion generation (founder 2026-07-18).

After a take's analysis, each notable snippet (resolved by
services.moment_direction: coach label → potentiometer; replace triggers:
threat / profanity / very low slide stickiness) gets ONE generated
suggestion the grey star opens:

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
from typing import Optional

logger = logging.getLogger(__name__)

# Prompt text lives in the registry (services/prompts/) — moved verbatim
# 2026-08-03; hash-locked in prompts.lock.json.
from services.prompts.moment_suggestions import SYSTEM as _SYSTEM
from services.prompts.moment_suggestions import STRUCT_SYSTEM as _STRUCT_SYSTEM

# Cap on the context-document excerpt per prompt. The stored text can reach
# 40k chars and this rides every snippet's call, so the excerpt is bounded.
_MAX_DOC_EXCERPT = 1200


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
    stored = 0
    for snip_id, transcript in candidates:
        if stored >= _cap:
            break
        try:
            found = detect_structural_device(transcript, user_id=user_id)
            if not found:
                continue
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
    persist suggestions for one take's snippets. Coach labels don't exist at
    record time, so resolution here is potentiometer/profanity/stickiness;
    a later coach-verified star supersedes at serve. Capped per take
    (MOMENT_SUGGESTIONS_MAX_PER_TAKE). Returns the number stored."""
    if not session_id or not arc_id:
        return 0
    try:
        if database is None:
            from services.db import db as database
        from config import Config
        from services.lab_recording import build_readout_from_session
        from services.moment_direction import (
            resolve_moment_direction, resolve_suggestion_kind,
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
        session = {}
        try:
            session = database.v2_get_session_by_id(session_id) or {}
        except Exception:
            pass
        ctx = session.get("intake_context") \
            if isinstance(session.get("intake_context"), dict) else {}
        audience = (ctx or {}).get("audience") or None
        strategic_context = (ctx or {}).get("strategic_context") or None

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
            ledger_keys, normalize_phrase as _norm_phrase,
        )
        try:
            _decided_keys = ledger_keys(
                database.list_ideal_decisions(str(arc_id)))
        except Exception:
            _decided_keys = set()

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
        # Snippets with NO acoustic star → candidates for a DELIVERY star
        # (measured, deterministic), then a STRUCTURAL star. Priority per
        # founder 2026-07-18: acoustic > delivery > structural; a snippet
        # only ever carries ONE star.
        _unstarred = []   # (snip_id, transcript, features_dict)
        for snip in (readout.get("snippets") or []):
            try:
                snip_id = snip.get("id")
                transcript = (snip.get("transcript") or "").strip()
                if not snip_id or not transcript:
                    continue
                direction = resolve_moment_direction(
                    None, snip.get("acoustic_read"))
                _stick = snip.get("slide_stickiness")
                if isinstance(_stick, dict):
                    _stick = _stick.get("composite")
                kind = resolve_suggestion_kind(
                    direction, transcript,
                    slide_stickiness=_stick, stickiness_max=_sticky_max)
                if kind is None:
                    _unstarred.append((str(snip_id), transcript,
                                       snip.get("features") or {}))
                    continue
                if stored >= _cap:
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
                    _unstarred.append((str(snip_id), transcript,
                                       snip.get("features") or {}))
                    continue
                from services.text_flags import has_profanity
                # Rule 4a: a STICKINESS replace (no direction, no
                # profanity) on wording the speaker uses in >= 2 takes is
                # their voice — never forced. Threat and profanity still
                # replace (the harmful carve-out). The snippet stays
                # eligible for the behavioural lanes.
                if kind == "replace" and direction is None \
                        and not has_profanity(transcript) \
                        and phrase_recurs(transcript, _take_texts):
                    _unstarred.append((str(snip_id), transcript,
                                       snip.get("features") or {}))
                    continue
                trigger = ("threat" if direction == "threat"
                           else "profanity" if has_profanity(transcript)
                           else "stickiness" if kind == "replace"
                           else "charisma")
                gen = generate_moment_suggestion(
                    kind, transcript, audience=audience,
                    strategic_context=strategic_context,
                    context_document=context_document, trigger=trigger,
                    user_id=session.get("user_id"))
                if not gen:
                    continue
                if database.upsert_moment_suggestion(
                        str(snip_id), str(arc_id), kind,
                        gen.get("replacement"), gen.get("why"), trigger):
                    stored += 1
            except Exception as _snip_err:
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

        if stored:
            logger.info("moment_suggestion: stored %d sid=%s arc=%s",
                        stored, session_id, arc_id)
        return stored
    except Exception as e:
        logger.warning("moment_suggestion: session pass failed sid=%s: %s",
                       session_id, e)
        return 0
