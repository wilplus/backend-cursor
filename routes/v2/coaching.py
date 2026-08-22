"""The conversational surface: /chat/*, /coaching/* and /onboarding/*.

The chat query + session state, the coaching turn and the 9-step state
machine, the intro bubble and the onboarding opener.

Distinct from ``routes/v2/user_chat.py``, which holds the interview
QUESTION-GENERATION machinery and the self-rating -- the two share no
symbols. Several prompts here are drift-tracked in place by
services/prompts/pending.py; moving them means updating that path map, so
the manifest keeps resolving (it raises loudly when a symbol goes missing).

Moved verbatim out of ``routes/v2_routes.py`` (god-file split, phase 5);
bodies are byte-identical. Routes register on the SAME ``v2_bp`` object, so
endpoint names and the URL map are unchanged.

Re-exported from ``routes.v2_routes`` for import compatibility.
"""
import logging

import sentry_sdk
from flask import jsonify, request

import json
import uuid
from typing import Any

from auth import optional_auth, require_auth
from routes.v2.common import _is_valid_uuid, _resolve_snippet_audio_url
from services.rate_limits import llm_limit
from services.skills import get_skill as _get_skill, resolve_for_snippet as _skill_for_snippet
from config import Config
from routes.v2.blueprint import v2_bp
from services.db import db
from services.snippet_values import display_hz, resolve_all

logger = logging.getLogger(__name__)
config = Config()


def _generate_snippet_follow_up_question(
    snippet_type: str,
    transcript: str,
    admin_comment: str,
) -> str | None:
    """Generate a single follow-up question for the Infinite Retention Loop.

    Called when an admin labels/comments on a snippet. The question is stored
    on the snippet row so it can be served instantly when the user later clicks
    the snippet — no latency at click time.

    snippet_type: "charisma" | "stress" | "unlabeled"
    transcript:   Whisper transcript of the snippet audio.
    admin_comment: Coach's text note on the snippet.

    Returns the generated question string, or None on failure.
    """
    try:
        from services.openai_service import OpenAIService
        service = OpenAIService()
        if not service.client:
            return None

        if snippet_type == "charisma":
            system_prompt = (
                "You are a charisma coaching assistant. "
                "An admin coach has flagged this audio snippet as a HIGH-CHARISMA moment "
                "and left a comment about it. Your task is to write a response that:\n"
                "1. Opens with ONE brief warm acknowledgment of this specific moment (1 sentence)\n"
                "2. Follows with ONE powerful question that helps the user deconstruct WHY they "
                "felt so confident and how they can deliberately replicate that energy "
                "(e.g. in cold calls, presentations, or negotiations)\n"
                "The question must be:\n"
                "- Specific to the transcript content (reference what they actually said)\n"
                "- High-energy and motivating in tone\n"
                "- Focused on replicability (how to trigger this state on demand)\n"
                "- No longer than 2 sentences\n"
                "FORMATTING RULE: Separate your acknowledgment from your question using the exact "
                "delimiter `|||`. "
                "Example: `That energy you described is magnetic! ||| What specific conditions were "
                "present that day that let you access that state so easily?`\n"
                "Return ONLY these two parts separated by `|||`, nothing else."
            )
        elif snippet_type == "stress":
            system_prompt = (
                "You are a performance coaching assistant. "
                "An admin coach has flagged this audio snippet as a HIGH-STRESS or VOCAL-STRAIN moment "
                "and left a comment. Your task is to write a response that:\n"
                "1. Opens with ONE brief empathetic acknowledgment of this specific moment (1 sentence)\n"
                "2. Follows with ONE targeted question that addresses the cognitive load or emotional "
                "trigger that caused the vocal stress spike\n"
                "The question must be:\n"
                "- Specific to what the speaker was saying in the transcript\n"
                "- Empathetic but direct (not dismissive)\n"
                "- Focused on uncovering the root cause of that specific stress moment\n"
                "- No longer than 2 sentences\n"
                "FORMATTING RULE: Separate your acknowledgment from your question using the exact "
                "delimiter `|||`. "
                "Example: `That moment sounds genuinely tough. ||| What was running through your mind "
                "right before your voice shifted?`\n"
                "Return ONLY these two parts separated by `|||`, nothing else."
            )
        else:
            # unlabeled or unknown — generic deepening question
            system_prompt = (
                "You are a voice coaching assistant. "
                "Based on this audio transcript and the coach's comment, write a response that:\n"
                "1. Opens with ONE brief acknowledgment of the moment (1 sentence)\n"
                "2. Follows with ONE insightful question to help the speaker reflect on it\n"
                "FORMATTING RULE: Separate your acknowledgment from your question using the exact "
                "delimiter `|||`. "
                "Return ONLY these two parts separated by `|||`, nothing else."
            )

        user_content = (
            f"Transcript: \"{transcript}\"\n"
            f"Coach comment: \"{admin_comment}\""
        )

        response = service.client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            max_tokens=120,
            temperature=0.7,
        )
        question = response.choices[0].message.content.strip()
        if question.startswith('"') and question.endswith('"'):
            question = question[1:-1]
        return question if question else None

    except Exception as e:
        logger.warning("_generate_snippet_follow_up_question failed: %s", e)
        return None


def _build_user_raw_snippet_list(
    session_id: str,
    *,
    include_admin_fields: bool,
) -> list[dict]:
    """Build the per-snippet raw-block array consumed by both the
    signed-in /sessions/<id>/summary and the anonymous
    /public/interview/<gsid>/raw-results endpoints.

    Always included (raw, no interpretation):
      snippet_id, audio_url (presigned), duration_ms, transcript,
      question_tone, acoustic stats block, classifier_stress_probability,
      created_at

    Gated on ``include_admin_fields`` (i.e., session is published):
      admin_comment, coach_label, follow_up_question

    Ordering depends on phase (mirrors the include_admin_fields gate):

      PRE-PUBLISH / ANONYMOUS (include_admin_fields=False):
        Chronological — snippets in the order they were collected
        during the session. The raw view is the user's honest
        replay of "what just happened"; resorting it before any
        human interpretation would imply judgment we haven't made
        yet.

      POST-PUBLISH (include_admin_fields=True):
        Bucket by question_tone and sort by intensity:
          - charisma bucket first, ASC by classifier_stress_probability
            (lower stress = more characteristically charismatic)
          - stress bucket next, DESC by classifier_stress_probability
            (higher stress = more stressful)
          - other/untagged trails chronological
        Snippets missing the classifier output tail each bucket.
        The intensity sort IS the curated narrative — and it's
        only earned once a human has reviewed.

    The raw block payload shape is identical for both phases; only
    the ordering changes. FE renders one card component either way.
    """
    snippets = db.get_snippets_by_session(session_id) or []

    rendered: list[dict] = []
    for s in snippets:
        # Skip un-extracted candidates; we only show real snippets.
        # storage_path is the proxy: an extracted snippet has its
        # audio bytes anchored; a placeholder row may not.
        if not (s.get("storage_path") or s.get("audio_url")):
            continue

        metrics = s.get("metrics") or {}
        if not isinstance(metrics, dict):
            metrics = {}

        row: dict[str, Any] = {
            "snippet_id":    s.get("id"),
            "audio_url":     _resolve_snippet_audio_url(s),
            "duration_ms":   s.get("duration_ms"),
            "transcript":    (
                s.get("transcript")
                or s.get("transcription_text")
                or ""
            ),
            "question_tone": (s.get("question_tone") or "").lower() or None,
            # PM-9. Two defects here, not one. (a) `or` is wrong for a
            # numeric: a genuine 0 -- zero fillers, a silent stretch -- is
            # falsy and fell through to the dead column, reading as absent.
            # (b) the blob's keys are pitch_center_st / energy_ratio, and
            # `fillers` is in neither the blob nor a live column, so it was
            # always None. resolve_all knows all three facts.
            #
            # pitch_center_hz keeps its Hz contract by reading f0_mean. The
            # `pitch_center` dimension is SEMITONES despite the registry
            # labelling it Hz; wiring that here would have put semitones
            # under an Hz key.
            "acoustic": {
                **{k: v for k, v in resolve_all(s).items()
                   if k != "pitch_center"},
                "pitch_center_hz": display_hz(s),
            },
            "classifier_stress_probability": (
                s.get("classifier_stress_probability")
            ),
            "created_at":    s.get("created_at"),
        }

        if include_admin_fields:
            row["admin_comment"]      = s.get("admin_comment")
            row["coach_label"]        = (s.get("coach_label") or "").lower() or None
            row["follow_up_question"] = s.get("follow_up_question")

        rendered.append(row)

    # Phase-aware ordering: chronological pre-publish (DB order
    # already is start_offset_ms ASC), intensity-sorted post-publish.
    # See docstring above for the rationale.
    if include_admin_fields:
        return _sort_raw_snippets_by_intensity(rendered)
    return rendered


def _sort_raw_snippets_by_intensity(rendered: list[dict]) -> list[dict]:
    """Bucket by ``question_tone`` and sort each bucket by intensity.

    Ordering rules (single source of truth — used by both signed-in
    and anonymous endpoints):

      1. CHARISMA bucket first, sorted by classifier_stress_probability
         ASCENDING (lower stress signal = more charismatic delivery).
      2. STRESS bucket next, sorted by classifier_stress_probability
         DESCENDING (higher stress signal = more stressful delivery).
      3. Untagged / other-tone snippets last, in original (chronological)
         order — defensive against legacy rows or future tones.

    Snippets missing the classifier output (NULL probability) sort
    to the tail of their bucket so visible "best" snippets are always
    the ones with actual measured intensity, not the ones we couldn't
    score.
    """
    # Sentinel for snippets missing the classifier output. Used as
    # the secondary sort key so untyped probs fall to the END of
    # each bucket regardless of which direction we're sorting.
    _UNSCORED = float("inf")

    def _intensity(row: dict) -> float:
        p = row.get("classifier_stress_probability")
        return float(p) if isinstance(p, (int, float)) else _UNSCORED

    charisma_bucket = [r for r in rendered if r.get("question_tone") == "charisma"]
    stress_bucket   = [r for r in rendered if r.get("question_tone") == "stress"]
    other_bucket    = [
        r for r in rendered
        if r.get("question_tone") not in ("charisma", "stress")
    ]

    # CHARISMA: ascending by stress prob (lower = better) — but
    # unscored rows still trail. The compound key (is_unscored, value)
    # forces unscored to the end regardless of asc/desc direction.
    charisma_bucket.sort(
        key=lambda r: (_intensity(r) is _UNSCORED, _intensity(r)),
    )
    # STRESS: descending by stress prob (higher = more stressful).
    # Negate the value so unscored (inf) flips to -inf and the
    # primary key sorts naturally; unscored still tail via the
    # is_unscored boolean.
    stress_bucket.sort(
        key=lambda r: (_intensity(r) is _UNSCORED, -_intensity(r)),
    )

    return charisma_bucket + stress_bucket + other_bucket


def _format_duration(duration_ms: int | None) -> str:
    """Format a duration in ms as M:SS for the timeline UI (e.g. 12000 -> '0:12')."""
    if not duration_ms or duration_ms < 0:
        return "0:00"
    total_seconds = int(duration_ms // 1000)
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes}:{seconds:02d}"


def _snippet_to_journey_card(snippet: dict) -> dict:
    """Map a charisma_snippets row into the `Snippet` shape the
    /results Voice-Journey page expects (lib/results/types.ts).

    The page's existing typed interface is the contract; we transform once
    here on the backend so the frontend can drop its mock without inventing
    a translation layer.
    """
    coach_label = (snippet.get("coach_label") or "").lower()
    snippet_type = "charisma" if coach_label == "charisma" else "stress"

    badge_label = (
        "Charisma Moment" if snippet_type == "charisma" else "Stress Pattern"
    )
    cta_label = (
        "Understand your charisma"
        if snippet_type == "charisma"
        else "Work on this stress"
    )

    # Build the metrics list — we omit any metric whose value is null so
    # the UI accordion doesn't render empty rows.
    # PM-9: this read the blob with the COLUMN names, so "pitch_center",
    # "energy" and "fillers" were never in it and those three rows never
    # rendered. Pitch reads f0_mean because this formatter says "Hz" and the
    # pitch_center dimension is semitones -- rendering one as the other is the
    # exact mistake display_hz exists to prevent.
    resolved = resolve_all(snippet)
    raw_metrics = [
        ("WPM", resolved.get("wpm"), lambda v: f"{int(v)}"),
        ("Pitch", display_hz(snippet), lambda v: f"{int(v)} Hz"),
        ("Pause", resolved.get("pause_ms"), lambda v: f"{(v / 1000):.1f}s"),
        ("Energy", resolved.get("energy"), lambda v: f"{int(v * 100)}%"),
        ("Fillers", resolved.get("fillers"), lambda v: f"{int(v)}"),
        ("Dynamic dB", resolved.get("dynamic_db"), lambda v: f"{int(v)}"),
    ]
    metrics: list[dict] = []
    for label, value, fmt in raw_metrics:
        if value is None:
            continue
        try:
            metrics.append({"label": label, "value": fmt(value)})
        except Exception:
            # Defensive — never let a formatting error blank out a snippet.
            continue

    return {
        "id": str(snippet.get("id")),
        "type": snippet_type,
        "duration": _format_duration(snippet.get("duration_ms")),
        "badgeLabel": badge_label,
        "insight": snippet.get("admin_comment") or "",
        "ctaLabel": cta_label,
        "metrics": metrics,
        "audioUrl": snippet.get("audio_url"),
    }


def _system_prompt_for_intent(intent: str) -> str:
    """Pick the awareness-stage system prompt for a given coaching intent.

    Phase 7 — the prompts themselves moved to services/skills/. This
    function is a thin shim over the registry kept around so existing
    call sites don't have to change; new code should call
    ``services.skills.get_skill(intent).awareness_system_prompt``
    directly. The fallback path (unknown intent) lands on the stress
    skill, matching pre-refactor behaviour.
    """
    skill = _get_skill(intent) or _get_skill("stress")
    return skill.awareness_system_prompt if skill else ""


def _augment_coaching_system_prompt(base_prompt: str, user_id: str) -> str:
    """Append the long-term user profile to a coaching system prompt.

    Three sources of personalisation, stacked top-to-bottom in the
    system prompt:
      - user_settings.custom_llm_instructions — free-text instructions
        the admin set in Admin Tab 3 ("Global LLM Instructions"). Goes
        verbatim into the prompt so the admin's wording is preserved.
      - student profile.behavioral_profile — the user's classified
        learner type (e.g. Stressor, Racer, Freezer) from the
        behavioural-profile classifier.
      - Phase 3: user_settings.inferred_learner_profile — AI-inferred
        traits derived from coaching_attempts aggregates (weakest
        component, score trend, self-rating gap, etc.). Flag-gated by
        LEARNER_PROFILE_INJECTION_ENABLED and additionally gated by
        sample-size threshold in services/learner_profile.py.

    Any of these can be absent. When all three are silent we return
    the base prompt unchanged — no [USER LONG-TERM PROFILE] block.

    Failure modes are swallowed: a DB read miss returns the base
    prompt rather than blocking the coaching turn. Personalisation is
    additive — the awareness loop must keep running even when the
    profile is unreadable.
    """
    admin_instructions: str = ""

    settings: dict = {}
    try:
        settings = db.get_user_settings(user_id) or {}
        admin_instructions = (settings.get("custom_llm_instructions") or "").strip()
    except Exception as e:
        logger.warning("coaching/turn: settings load failed user=%s: %s", user_id, e)

    # Old-subsystem personalisation removed in the excision: the sniper
    # learner-type and the learner_profile inferred-insights block no
    # longer inject here. Admin custom instructions remain.

    if not admin_instructions:
        return base_prompt

    lines: list[str] = ["[USER LONG-TERM PROFILE]"]
    if admin_instructions:
        lines.append(f"Custom Coaching Instructions: {admin_instructions}")
    lines.append("")
    lines.append(
        "CRITICAL: You must adhere to these custom instructions and "
        "tailor your feedback to this learner type."
    )

    return f"{base_prompt}\n\n" + "\n".join(lines)


def _coach_intent_for_snippet(snippet: dict) -> str:
    """Map a snippet's coach_label to a coaching intent.

    Phase 7 — thin shim over services.skills.resolve_for_snippet.
    Kept under the old name so existing call sites in this module
    keep working; new code should import resolve_for_snippet
    directly from the skills package.
    """
    return _skill_for_snippet(snippet)


@v2_bp.route("/coaching/start", methods=["POST"])
@llm_limit
@require_auth
def v2_coaching_start():
    """Open a micro-coaching session on one snippet.

    Body: { "snippet_id": "<uuid>" }

    Validates the user owns the snippet and that the admin has left a
    comment (no comment ⇒ nothing to coach about). Creates a
    coaching_sessions row in the awareness stage.

    Response (200):
        {
            "coaching_id": str,
            "intent": "stress" | "charisma",
            "awareness_message": str,   # admin_comment, served verbatim
            "source_snippet": {
                "id": str, "transcript": str | None, "audio_url": str | None,
                "duration_ms": int | None
            }
        }
    """
    try:
        body = request.get_json(silent=True) or {}
        snippet_id = (body.get("snippet_id") or "").strip()
        if not _is_valid_uuid(snippet_id):
            return jsonify({"code": "INVALID_INPUT", "error": "snippet_id must be a UUID"}), 400

        user_id = request.user_id
        snippet = db.get_snippet_by_id(snippet_id, user_id=user_id)
        if not snippet:
            return jsonify({
                "code": "SNIPPET_NOT_FOUND",
                "error": "Snippet not found or not yours.",
            }), 404

        admin_comment = (snippet.get("admin_comment") or "").strip()
        if not admin_comment:
            return jsonify({
                "code": "SNIPPET_NOT_COACHABLE",
                "error": "This snippet has no coach comment yet — nothing to coach on.",
            }), 422

        intent = _coach_intent_for_snippet(snippet)
        # Both 'stress' and 'charisma' intents are now live; the prompt
        # router in v2_coaching_turn picks the right system prompt.
        coaching = db.create_coaching_session(user_id, snippet_id, intent)
        if not coaching:
            return jsonify({"code": "V2_ERROR", "error": "Failed to start coaching"}), 500

        return jsonify({
            "coaching_id": str(coaching.get("id")),
            "intent": intent,
            "awareness_message": admin_comment,
            "source_snippet": {
                "id": str(snippet.get("id")),
                "transcript": snippet.get("transcript"),
                "audio_url": snippet.get("audio_url"),
                "duration_ms": snippet.get("duration_ms"),
            },
        }), 200

    except Exception as e:
        logger.error("coaching/start failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to start coaching"}), 500


@v2_bp.route("/coaching/<coaching_id>", methods=["GET"])
@require_auth
def v2_coaching_get(coaching_id):
    """Re-hydrate a coaching session — survive reloads of /coach/[id].

    Returns the same shape as /coaching/start except with current_stage
    and trial_session_id reflecting any progress already made.

    404 GET semantics: NOT_FOUND covers both "doesn't exist" and "owned
    by someone else" so we don't leak coaching id existence.
    """
    try:
        if not _is_valid_uuid(coaching_id):
            return jsonify({"code": "INVALID_INPUT", "error": "coaching_id must be a UUID"}), 400
        user_id = request.user_id
        coaching = db.get_coaching_session(coaching_id, user_id)
        if not coaching:
            return jsonify({
                "code": "COACHING_NOT_FOUND",
                "error": "Coaching session not found.",
            }), 404
        snippet = db.get_snippet_by_id(coaching.get("source_snippet_id"), user_id=user_id)
        if not snippet:
            return jsonify({
                "code": "SNIPPET_NOT_FOUND",
                "error": "Source snippet missing.",
            }), 404
        return jsonify({
            "coaching_id": str(coaching.get("id")),
            "intent": coaching.get("intent"),
            "current_stage": coaching.get("current_stage"),
            "awareness_message": (snippet.get("admin_comment") or "").strip(),
            "source_snippet": {
                "id": str(snippet.get("id")),
                "transcript": snippet.get("transcript"),
                "audio_url": snippet.get("audio_url"),
                "duration_ms": snippet.get("duration_ms"),
            },
            "trial_session_id": coaching.get("trial_session_id"),
        }), 200
    except Exception as e:
        logger.error("coaching/<id> failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Failed to load coaching"}), 500


@v2_bp.route("/coaching/turn", methods=["POST"])
@llm_limit
@require_auth
def v2_coaching_turn():
    """Run one LLM turn of the awareness stage.

    LIVE — drives the /coach/<id> coach-invite deep-link (FE seam-7a):
    src/app/coach/[coachingId]/page.tsx → /api/coaching/turn → here. Do
    NOT excise in a dead-route sweep; it has no inbound link from the main
    nav but is reached by direct URL, so a reference search comes up empty.


    Body: { "coaching_id": "<uuid>", "user_message": "..." }

    Loads the coaching session + source snippet, builds the awareness
    prompt with admin_comment / transcript / user_message context, calls
    GPT, parses the `|||` + `[ADVANCE]` shape, and advances to the trial
    stage when [ADVANCE] is present.

    Response (200):
        {
            "bubbles": [str, str],   # second may be empty if model
                                     # forgot the delimiter
            "advance": bool,
            "next_stage": "awareness" | "trial" | "complete"
        }
    """
    try:
        body = request.get_json(silent=True) or {}
        coaching_id = (body.get("coaching_id") or "").strip()
        user_message = (body.get("user_message") or "").strip()

        if not _is_valid_uuid(coaching_id):
            return jsonify({"code": "INVALID_INPUT", "error": "coaching_id must be a UUID"}), 400
        if not user_message:
            return jsonify({"code": "INVALID_INPUT", "error": "user_message is required"}), 400

        user_id = request.user_id
        coaching = db.get_coaching_session(coaching_id, user_id)
        if not coaching:
            return jsonify({"code": "COACHING_NOT_FOUND", "error": "Coaching session not found"}), 404
        if coaching.get("current_stage") == "complete":
            return jsonify({
                "code": "COACHING_COMPLETE",
                "error": "This coaching loop is already complete.",
            }), 409

        snippet = db.get_snippet_by_id(coaching.get("source_snippet_id"), user_id=user_id)
        if not snippet:
            return jsonify({"code": "SNIPPET_NOT_FOUND", "error": "Source snippet missing"}), 404

        intent = coaching.get("intent") or "stress"
        base_system_prompt = _system_prompt_for_intent(intent)

        # ── Long-term profile injection ─────────────────────────────
        # Pulls the admin-set custom_llm_instructions (Admin Tab 3) +
        # the user's behavioral_profile classification (e.g. Stressor,
        # Racer, Freezer). When either is present, we append a
        # [USER LONG-TERM PROFILE] block to the system prompt so the
        # coaching turn adapts to who this specific user is rather
        # than coaching every learner identically.
        system_prompt = _augment_coaching_system_prompt(base_system_prompt, user_id)

        from services.openai_service import OpenAIService
        service = OpenAIService()
        if not service.client:
            return jsonify({"code": "LLM_UNAVAILABLE", "error": "Coaching LLM is not configured"}), 503

        admin_comment = (snippet.get("admin_comment") or "").strip()
        user_transcript = (snippet.get("transcript") or "").strip()

        user_content = (
            f'admin_comment: "{admin_comment}"\n'
            f'user_transcript: "{user_transcript}"\n'
            f'user_first_reply: "{user_message}"'
        )

        # Persist the user side of the exchange before calling the LLM.
        # If the LLM call fails downstream we still want admins to see
        # what the user actually said. Best-effort — append never blocks
        # the response if the JSONB column hasn't been migrated yet.
        try:
            db.append_coaching_message(coaching_id, "user", user_message)
        except Exception as msg_err:
            logger.warning("coaching/turn user-msg append failed: %s", msg_err)

        # Phase 0 — structured output. The model returns a strict
        # JSON object {validation_bubble, challenge_bubble, advance}
        # so the prior |||  + [ADVANCE] string-parsing dance is gone.
        # System prompt still tells the model what each field means;
        # the schema enforces shape, the prompt enforces semantics.
        from services.llm_schemas import (
            AWARENESS_TURN_SCHEMA,
            response_format as _response_format,
        )
        structured_prompt = (
            f"{system_prompt}\n\n"
            "RESPONSE SHAPE — return JSON only with exactly these keys:\n"
            "  validation_bubble — 1-2 sentence acknowledgment of the user's reply.\n"
            "  challenge_bubble  — the mic-on instruction telling them what to do next.\n"
            "  advance           — true when the user is ready to record the trial.\n"
        )

        try:
            response = service.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": structured_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=0.6,
                max_tokens=240,
                response_format=_response_format(AWARENESS_TURN_SCHEMA),
            )
            raw = response.choices[0].message.content or ""
        except Exception as llm_err:
            logger.error("coaching/turn LLM call failed: %s", llm_err, exc_info=True)
            return jsonify({
                "code": "LLM_ERROR",
                "error": "Coach is unavailable. Please try again in a moment.",
            }), 502

        # Schema enforces the shape — only failure left is a transport
        # blip that returns malformed text. We log + fall back below.
        bubble_1 = ""
        bubble_2 = ""
        advance = False
        try:
            parsed = json.loads(raw) if raw else {}
            bubble_1 = (parsed.get("validation_bubble") or "").strip()
            bubble_2 = (parsed.get("challenge_bubble") or "").strip()
            advance = bool(parsed.get("advance"))
        except (json.JSONDecodeError, ValueError, AttributeError) as parse_err:
            logger.warning(
                "coaching/turn: structured output not parseable: %r err=%s",
                raw[:300], parse_err,
            )

        if not bubble_1 and not bubble_2:
            # Total LLM failure — return a graceful fallback instead of
            # an empty payload so the user always sees something. The
            # bubbles come from the skill registry so a degraded
            # response stays tonally consistent with the active skill.
            fallback_skill = _get_skill(intent) or _get_skill("stress")
            if fallback_skill is not None:
                bubble_1 = fallback_skill.fallback_validation_bubble
                bubble_2 = fallback_skill.fallback_challenge_bubble
            advance = True

        # Persist the AI side of the exchange. Both bubbles together so
        # the admin transcript reads as one assistant message rather
        # than two synthetic ones — the `||| / [ADVANCE]` is an LLM
        # output detail, not a semantic separation.
        try:
            ai_content_parts = [b for b in (bubble_1, bubble_2) if b]
            db.append_coaching_message(
                coaching_id,
                "assistant",
                " ||| ".join(ai_content_parts),
                extra={
                    "bubbles": [bubble_1, bubble_2],
                    "advance": advance,
                    "raw_llm_output": raw,
                },
            )
        except Exception as msg_err:
            logger.warning("coaching/turn assistant-msg append failed: %s", msg_err)

        next_stage = "trial" if advance else coaching.get("current_stage", "awareness")
        if advance and coaching.get("current_stage") != "trial":
            db.update_coaching_stage(coaching_id, "trial")

        return jsonify({
            "bubbles": [bubble_1, bubble_2],
            "advance": advance,
            "next_stage": next_stage,
        }), 200

    except Exception as e:
        logger.error("coaching/turn failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "V2_ERROR", "error": "Coaching turn failed"}), 500


@v2_bp.route("/coaching/state-machine/turn", methods=["POST"])
@llm_limit
@require_auth
def v2_coaching_state_machine_turn():
    """One turn of the 5-step coaching state machine.

    Parallel to ``/v2/coaching/turn`` (which runs the older
    awareness→trial loop). Doesn't touch the existing flow — the
    frontend opts in by hitting this endpoint instead.

    Body::

        {
          "coaching_id": "<uuid>",   // existing coaching_sessions row
          "user_message": "..."       // optional on the very first
                                      // call (STEP 1 has no user
                                      // message yet — the AI opens)
        }

    Response (200) — mirrors the structured-output schema verbatim
    plus an ``ai_message_id`` placeholder the frontend can ignore::

        {
          "narration":    str,
          "step":         1..5,
          "triggers":     [str, ...],
          "end":          bool,
          "current_question_position": 1..5 | null,  // Director's
                                                      // Script position
          "snippet_player":   { snippet_id } | omitted,
          "label_buttons":    { snippet_id, yes_label, no_label } | omitted
        }

    Persists each turn to ``coaching_sessions.messages`` so the
    admin transcript view replays the full chat. The state itself
    is implicit in the conversation history — we hand the LLM the
    full prior turns and it follows the protocol from the system
    prompt.
    """
    try:
        body = request.get_json(silent=True) or {}
        coaching_id = (body.get("coaching_id") or "").strip()
        user_message = (body.get("user_message") or "").strip()
        # Optional language hint for STEP 1 (which has no prior
        # user message to infer language from). Accept either key
        # so the frontend BFF doesn't have to be picky. Plain
        # display name ("Polish", "English") or ISO code — the
        # prompt builder hands it to the LLM verbatim.
        user_language_hint = (
            body.get("user_language")
            or body.get("user_language_hint")
            or body.get("language")
            or ""
        ).strip() or None

        if not _is_valid_uuid(coaching_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "coaching_id must be a UUID",
            }), 400

        user_id = request.user_id
        coaching = db.get_coaching_session(coaching_id, user_id)
        if not coaching:
            return jsonify({
                "code": "COACHING_NOT_FOUND",
                "error": "Coaching session not found",
            }), 404
        if coaching.get("current_stage") == "complete":
            return jsonify({
                "code": "COACHING_COMPLETE",
                "error": "This coaching loop is already complete.",
            }), 409

        snippet = db.get_snippet_by_id(
            coaching.get("source_snippet_id"), user_id=user_id,
        )
        if not snippet:
            return jsonify({
                "code": "SNIPPET_NOT_FOUND",
                "error": "Source snippet missing",
            }), 404

        # Acoustic targets are computed against the snippet's parent
        # session — its global metrics are the user's baseline for
        # this conversation. Falls through to None targets when the
        # session row hasn't been finalized yet (the prompt builder
        # drops missing lines).
        parent_session: dict = {}
        if snippet.get("session_id"):
            try:
                parent_session = db.v2_get_session_by_id(
                    snippet.get("session_id"),
                ) or {}
            except Exception as e:
                logger.warning(
                    "coaching/state-machine: parent session load failed sid=%s err=%s",
                    snippet.get("session_id"), e,
                )

        from services.coaching_state_machine import (
            build_state_machine_system_prompt,
            STATE_MACHINE_RESPONSE_SCHEMA,
            parse_state_machine_response,
            CONFIDENCE_REVIEW_TRIGGER as _CONFIDENCE_REVIEW_TRIGGER,
            STEP2_YES_LABEL as _STEP2_YES_LABEL,
            STEP2_NO_LABEL as _STEP2_NO_LABEL,
        )
        # ACOUSTIC TARGETS DELETED 2026-08-06 (founder: "we don't want that,
        # it is a wrong call"). This block used to compute prescriptive numeric
        # goals -- "keep your tempo at around 145 WPM (you were at 132 this
        # time)" -- behind a sign-off flag. The flag is gone with the feature:
        # a prescriptive number IS a direction, and pairing a shortfall with a
        # goal is a verdict wearing a suggestion's clothes (AC-9 split-sink).
        # STEP 8 now frames the next take qualitatively, which is what it has
        # actually emitted since 2026-06-01 anyway.
        # Director's Script — admin-edited array wins; fall through
        # to AI-pre-generated draft; empty list if neither exists
        # (the prompt handles the empty case by skipping straight
        # from STEP 2 to STEP 8).
        director_script_questions = (
            parent_session.get("final_human_next_questions")
            or parent_session.get("ai_predicted_next_questions")
            or []
        )
        if not isinstance(director_script_questions, list):
            director_script_questions = []

        # First-name + org-context are nice-to-haves; missing both
        # is fine, the prompt builder degrades gracefully.
        first_name: str | None = None
        try:
            details = db.v2_get_student_details(user_id) or {}
            full_name = (details.get("name") or "").strip()
            if full_name:
                first_name = full_name.split()[0]
        except Exception:
            pass

        # Admin's private notes about this user become a don't-ask
        # block at the end of the system prompt. Best-effort read —
        # a DB hiccup just means the block is missing, not a 500.
        admin_dont_ask_notes: str | None = None
        try:
            _settings = db.get_user_settings(user_id) or {}
            admin_dont_ask_notes = (
                _settings.get("private_admin_notes") or None
            )
        except Exception as e:
            logger.warning(
                "coaching/state-machine: private_admin_notes load "
                "failed user=%s: %s", user_id, e,
            )

        system_prompt = build_state_machine_system_prompt(
            snippet=snippet,
            director_script_questions=director_script_questions,
            user_first_name=first_name,
            user_org_context=None,
            user_language_hint=user_language_hint,
            coaching_id=coaching_id,
            admin_dont_ask_notes=admin_dont_ask_notes,
        )

        # Build the LLM's view of the conversation. The system
        # prompt encodes the protocol; the message history tells
        # the model which step we're on.
        messages: list[dict] = [
            {"role": "system", "content": system_prompt},
        ]
        prior = coaching.get("messages") or []
        if isinstance(prior, list):
            for m in prior:
                role = (m.get("role") or "").strip()
                content = (m.get("content") or "").strip()
                # 'trial_audio' rows aren't part of the state-machine
                # exchange — they're recordings dropped into the
                # legacy awareness flow. Filter them out so the LLM
                # doesn't see binary placeholders.
                if role in ("user", "assistant") and content:
                    messages.append({"role": role, "content": content})

        # On the very first call (no user_message and no prior
        # messages) we still ask the LLM for STEP 1 — the system
        # prompt instructs it to open without waiting for input.
        if user_message:
            messages.append({"role": "user", "content": user_message})

        from services.openai_service import OpenAIService
        service = OpenAIService()
        if not service.client:
            return jsonify({
                "code": "LLM_UNAVAILABLE",
                "error": "Coach LLM not configured",
            }), 503

        try:
            response = service.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=messages,
                temperature=0.7,
                max_tokens=600,
                response_format={
                    "type": "json_schema",
                    "json_schema": STATE_MACHINE_RESPONSE_SCHEMA,
                },
            )
            raw = response.choices[0].message.content or ""
        except Exception as llm_err:
            logger.error(
                "coaching/state-machine: LLM call failed: %s",
                llm_err, exc_info=True,
            )
            return jsonify({
                "code": "LLM_ERROR",
                "error": "Coach is unavailable. Please try again.",
            }), 502

        parsed = parse_state_machine_response(raw)
        if parsed is None:
            return jsonify({
                "code": "LLM_PARSE_ERROR",
                "error": (
                    "Coach response was malformed. Please send again."
                ),
            }), 502

        # STEP 2 button copy is FOUNDER-SIGNED (LIVE LOOP), so it is stamped
        # here rather than trusted from the model. The prompt asks for these
        # exact labels, but "asked nicely" is not a guarantee — a model that
        # helpfully softens "Not quite" would ship unsigned copy into a live
        # chat, and nothing downstream would catch it. Overwrite, don't
        # default: a present-but-reworded label is the case worth fixing.
        # snippet_id stays the model's (it varies per turn); only the two
        # signed strings are pinned.
        if _CONFIDENCE_REVIEW_TRIGGER in (parsed.get("triggers") or []):
            buttons = parsed.get("label_buttons")
            if not isinstance(buttons, dict):
                buttons = {}
            buttons["yes_label"] = _STEP2_YES_LABEL
            buttons["no_label"] = _STEP2_NO_LABEL
            parsed["label_buttons"] = buttons

        # Persist user side first so the admin transcript reads
        # chronologically even if assistant persist fails downstream.
        if user_message:
            try:
                db.append_coaching_message(
                    coaching_id, "user", user_message,
                )
            except Exception as msg_err:
                logger.warning(
                    "coaching/state-machine: user msg append failed: %s",
                    msg_err,
                )

        try:
            db.append_coaching_message(
                coaching_id,
                "assistant",
                parsed.get("narration") or "",
                extra={
                    "step": parsed.get("step"),
                    "current_question_position": parsed.get(
                        "current_question_position"
                    ),
                    "triggers": parsed.get("triggers") or [],
                    "end": bool(parsed.get("end")),
                    "snippet_player": parsed.get("snippet_player"),
                    "label_buttons": parsed.get("label_buttons"),
                    "raw_llm_output": raw,
                },
            )
        except Exception as msg_err:
            logger.warning(
                "coaching/state-machine: assistant msg append failed: %s",
                msg_err,
            )

        # When the LLM flags end=true on STEP 8, advance the
        # coaching_session to 'complete' so subsequent POSTs return
        # COACHING_COMPLETE. Best-effort; the chat already showed
        # the closing card by this point.
        if parsed.get("end") and coaching.get("current_stage") != "complete":
            try:
                db.update_coaching_stage(coaching_id, "complete")
            except Exception as stage_err:
                logger.warning(
                    "coaching/state-machine: stage advance failed: %s",
                    stage_err,
                )

        return jsonify(parsed), 200

    except Exception as e:
        logger.error(
            "coaching/state-machine/turn failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "State machine turn failed",
        }), 500


@v2_bp.route("/chat/session-state", methods=["GET"])
@require_auth
def v2_chat_session_state():
    """Drive the /chat route's UI state for a returning user.

    The frontend killed the /results page; /chat is now the
    single destination after onboarding. This endpoint tells it
    what mode to render in.

    State machine::

        NO_SESSION     — user has no v2_sessions row at all (fresh
                          signup, never recorded). Frontend should
                          route them into the onboarding interview.

        PENDING_COACH  — latest session exists but
                          results_published_at IS NULL (admin
                          hasn't reviewed + published yet).
                          Frontend renders the waiting / FAQ chat;
                          POST /v2/chat/query is fully usable
                          against the Master Document in this
                          state.

        REVIEW_LOOP    — latest session has been published. Payload
                          includes the snippets + admin_comments
                          so the frontend can drop straight into
                          the snippet-review chat without a second
                          round-trip to /v2/user/results/<id>.

    Response (200)::

        {
          "state": "NO_SESSION" | "PENDING_COACH" | "REVIEW_LOOP",
          "session_id": "<uuid>" | null,
          "created_at": "<iso8601>" | null,
          "results_published_at": "<iso8601>" | null,

          // present iff state == "REVIEW_LOOP"
          "snippets":         [ ... full snippet objects, see below ],
          // kpi_score + charisma_profile removed (AC-9 — classifier/
          // appraisal data is never serialized to the user).
          "ai_summary":       string | null
        }

    Each REVIEW_LOOP snippet matches the shape /user/results/<id>
    returns so the frontend can reuse its existing renderer
    without a second translation layer.

    Why a separate endpoint when /user/sessions/current exists:
    /sessions/current emits the legacy 5-status vocabulary
    (no_session / processing / pending_review / completed /
    error). The frontend's /chat router wants the new
    3-state vocabulary explicitly + the snippet payload inline.
    We could overload /sessions/current, but doing that risks
    breaking the homework + admin routing surfaces that read
    its current shape. A dedicated endpoint is cheaper.
    """
    try:
        user_id = request.user_id
        session = db.v2_get_latest_session_for_user(user_id)

        if not session:
            return jsonify({
                "state": "NO_SESSION",
                "session_id": None,
                "created_at": None,
                "results_published_at": None,
            }), 200

        session_id = str(session.get("id"))
        published_at = session.get("results_published_at")
        base = {
            "session_id": session_id,
            "created_at": session.get("created_at"),
            "results_published_at": published_at,
        }

        if not published_at:
            # Admin hasn't clicked Publish yet. The /v2/chat/query
            # endpoint is the right surface for the user to ask
            # questions while they wait — same Master-Document
            # grounding, no special-casing needed here.
            return jsonify({"state": "PENDING_COACH", **base}), 200

        # REVIEW_LOOP — load published snippets in the same shape
        # /user/results/<id> uses, so the frontend renderer is
        # reusable. We resolve audio URLs the same way too: the
        # admin Files tab, the /results page, and this endpoint all
        # serve the same playable URL.
        try:
            raw_snippets = db.v2_get_results_snippets_for_session(
                session_id, user_id,
            ) or []
        except Exception as snip_err:
            logger.warning(
                "chat/session-state: snippet load failed sid=%s err=%s",
                session_id, snip_err,
            )
            raw_snippets = []

        snippets = [
            {
                "id": s.get("id"),
                "snippet_type": s.get("snippet_type"),
                "admin_comment": s.get("admin_comment"),
                "audio_url": _resolve_snippet_audio_url(s),
                "transcript": s.get("transcript"),
                "turn_number": s.get("turn_number"),
                "question_text": s.get("question_text"),
                "question_tone": s.get("question_tone"),
                "start_offset_ms": s.get("start_offset_ms") or 0,
                "duration_ms": s.get("duration_ms"),
                # PM-9: the six denormalized columns are dead on the live
                # path (services/snippet_values) — this block returned six
                # NULLs for every auto-extracted snippet, which is every
                # snippet the lab pipeline makes. Resolve against the blob.
                "metrics": resolve_all(s),
            }
            for s in raw_snippets
        ]

        # Phase 18.x split-sinks Option A — ai_summary surfaces the
        # immutable AI draft so admin edits don't leak to the user.
        return jsonify({
            "state": "REVIEW_LOOP",
            **base,
            "snippets": snippets,
            "ai_summary": (
                session.get("session_kpi_narrative_ai_draft")
                or session.get("ai_task_alignment_comment")
            ),
        }), 200

    except Exception as e:
        logger.error(
            "chat/session-state failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to evaluate session state",
        }), 500


def _persist_chat_turn(
    user_id, question, answer, *, suggested_action=None,
    suggested_actions=None, bubbles=None, intent=None, user_client_id=None,
    user_created_at=None,
):
    """BE-owned persistence of one Lounge chat turn (founder #2 — bubbles must
    never disappear). Writes the user message + the bot reply to lounge_messages
    so the thread survives reload + relogin on ANY device, rather than relying on
    a best-effort FE append that can silently fail or race the auth token.

    Idempotent: client_ids are deterministic (uuid5), so re-posting the same turn
    is a no-op (UNIQUE(user_id, client_id)). The user-turn id prefers the FE's
    own client_id (so it de-dupes with the FE's optimistic local copy + preserves
    merge ordering); the bot-turn id derives from it → exactly one bot row per
    user turn. The bot row carries suggested_action/suggested_actions + bubbles
    in metadata so the FE reconstructs contextual choices on rehydrate. Mirrors
    the existing
    server-insert pattern (publish 'insights ready' card, session cadence).

    Returns the bot row's client_id (so the FE can de-dupe its optimistic
    bubble) or None on failure. Best-effort — never raises to the route.
    """
    from datetime import datetime as _dt, timezone as _tz

    q = (question or "").strip()
    a = (answer or "").strip()
    if not user_id or not a:
        return None

    def _is_uuid(v):
        try:
            uuid.UUID(str(v))
            return True
        except (ValueError, AttributeError, TypeError):
            return False

    # User-turn id: prefer the FE's own (dedupe + merge order); else derive
    # deterministically from the text so an identical re-post stays a no-op.
    if user_client_id and _is_uuid(user_client_id):
        u_id = str(user_client_id)
    else:
        u_id = str(uuid.uuid5(
            uuid.NAMESPACE_URL, f"willab-chat-user:{user_id}:{q}"))
    # Bot-turn id derives from the user-turn id → one bot row per user turn.
    b_id = str(uuid.uuid5(uuid.NAMESPACE_URL, f"willab-chat-bot:{u_id}"))

    now_iso = _dt.now(_tz.utc).isoformat()
    u_ts = (user_created_at if isinstance(user_created_at, str)
            and user_created_at.strip() else now_iso)

    rows = []
    if q:
        rows.append({
            "client_id": u_id, "role": "user", "kind": "text",
            "body": q, "metadata": None, "client_created_at": u_ts,
        })
    meta = {"intent": intent}
    if suggested_action:
        meta["suggested_action"] = suggested_action
    if suggested_actions:
        meta["suggested_actions"] = suggested_actions
    if bubbles:
        meta["bubbles"] = bubbles
    rows.append({
        "client_id": b_id, "role": "bot", "kind": "text",
        "body": a, "metadata": meta, "client_created_at": now_iso,
    })

    try:
        db.insert_lounge_messages(str(user_id), rows)
        return b_id
    except Exception as e:
        logger.warning(
            "chat/query: persist turn failed user=%s: %s", user_id, e)
        return None


def _parse_chat_request(req) -> dict:
    """Normalize JSON and multipart chat requests into one transport shape.

    Invalid optional metadata degrades to its neutral value exactly as before;
    validation of the required question remains the route's responsibility.
    """
    is_multipart = "multipart/form-data" in (req.content_type or "").lower()
    parsed: dict[str, Any] = {
        "question": None,
        "history": None,
        "audio_bytes": None,
        "transcript_source": "web_speech",
        "audio_duration_sec": 0.0,
        "presentation_context": {},
        "persist_thread": False,
        "user_client_id": None,
        "user_created_at": None,
    }
    if not is_multipart:
        body = req.get_json(silent=True) or {}
        parsed["question"] = body.get("question")
        history = body.get("history")
        parsed["history"] = history if isinstance(history, list) else None
        parsed["persist_thread"] = bool(body.get("persist"))
        client_id = body.get("client_id")
        parsed["user_client_id"] = client_id \
            if isinstance(client_id, str) else None
        created_at = body.get("client_created_at")
        parsed["user_created_at"] = created_at \
            if isinstance(created_at, str) else None
        context = body.get("presentation_context")
        parsed["presentation_context"] = context \
            if isinstance(context, dict) else {}
        return parsed

    parsed["question"] = (req.form.get("question") or "").strip()
    history_raw = req.form.get("history")
    if history_raw:
        try:
            history = json.loads(history_raw)
            parsed["history"] = history if isinstance(history, list) else None
        except Exception:
            pass

    presentation_raw = req.form.get("presentation_context")
    if presentation_raw:
        try:
            context = json.loads(presentation_raw)
            parsed["presentation_context"] = context \
                if isinstance(context, dict) else {}
        except Exception:
            pass

    parsed["persist_thread"] = (
        (req.form.get("persist") or "").strip().lower()
        in ("1", "true", "yes", "on")
    )
    parsed["user_client_id"] = req.form.get("client_id") or None
    parsed["user_created_at"] = req.form.get("client_created_at") or None

    audio_file = req.files.get("audio_file")
    if audio_file is None:
        return parsed
    try:
        parsed["audio_bytes"] = audio_file.read()
    except Exception as read_err:
        logger.warning(
            "chat/query: audio read failed user=%s err=%s — continuing text-only",
            getattr(req, "user_id", None), read_err,
        )
    source = (req.form.get("transcript_source") or "").strip().lower()
    if source in ("web_speech", "server_whisper"):
        parsed["transcript_source"] = source
    try:
        parsed["audio_duration_sec"] = float(
            req.form.get("audio_duration_sec") or "0")
    except (TypeError, ValueError):
        pass
    return parsed


def _finalize_chat_response(
    resp, *, user_id, question, persist_thread, user_client_id,
    user_created_at, intent=None,
):
    """Persist/charge one completed Chat turn and create its HTTP response."""
    if persist_thread and user_id:
        bot_cid = _persist_chat_turn(
            user_id, question, resp.get("answer"),
            suggested_action=resp.get("suggested_action"),
            suggested_actions=resp.get("suggested_actions"),
            bubbles=resp.get("bubbles"), intent=intent,
            user_client_id=user_client_id,
            user_created_at=user_created_at,
        )
        resp["persisted"] = bool(bot_cid)
        if bot_cid:
            resp["persisted_client_id"] = bot_cid
    # Charge after answering, never before. Chat is repeatable, so it has no
    # idempotency ref; billing failure must never replace the answer.
    if user_id:
        try:
            from services.token_account import charge as _charge
            _charge(str(user_id), "chat")
        except Exception:
            pass
    return jsonify(resp), 200


@v2_bp.route("/chat/query", methods=["POST"])
@llm_limit
@optional_auth
def v2_chat_query():
    """Unified chat orchestrator for the /chat page.

    Powers the post-signup single-thread chat surface. The LLM
    runs under services.master_doc_rag with the verbatim Master
    Document as its only source of truth, plus capability-boundary
    + upload-intent rules. Returns structured output the frontend
    uses to drive UI state (showing/hiding the upload dropzone).

    Body::

        {
          "question": "what is this?",
          "history":  [                          // optional
            { "role": "user",      "content": "..." },
            { "role": "assistant", "content": "..." }
          ],
          // #2 — BE-owned thread persistence (signed-in only). Opt-in: when
          // persist=true, the user + bot turns are written to lounge_messages
          // server-side so they survive reload + relogin (no race-prone FE
          // append). client_id = the user message's FE id (idempotency +
          // dedupe with the FE's optimistic copy); client_created_at = its
          // FE timestamp (ordering). All optional; ignored when signed out.
          "persist":           bool,             // optional, default false
          "client_id":         "uuid",           // optional (user msg id)
          "client_created_at": "iso8601"         // optional (user msg ts)
        }

    Responses::

        200 {
              "answer":         str,    # the chat bubble text
              "bubbles":        [str],  # pre-split chat bubbles (FE #157)
              "show_record_ui": bool,   # per-turn record affordance
                                         # toggle (RULE I) — in-app mic
              "suggested_action": str | None,  # the one contextual button
              "suggested_actions": [str],      # deliberate pair, when needed
              "debug":          {...},  # model + history_used / error
              # present only when persist=true + signed in:
              "persisted":         bool,   # bot turn written server-side
              "persisted_client_id": str   # the bot row's client_id (FE dedupe)
            }
        400 INVALID_INPUT — question missing or not a string
        500 V2_ERROR

    show_record_ui semantics:
      • show_record_ui — TRUE on the turn where the user expressed
        intent to RECORD in-app via the chat's mic ("can I record
        here?", "let me just record it", etc.). RULE I.
      • Per-turn signal — frontend must NOT cache it across turns;
        each answer carries the current state.
      • (show_upload_ui was removed — uploads are off and FE seam-7b
        cleared the field; upload intent still redirects to record
        per RULE G, just without a flag.)

    Why @optional_auth: the willab Lounge is an unsigned-home
    (design §3) — the Lounge bot / librarian must answer without a
    session. Signed-in requests carry request.user_id (so the
    strong-sides library + admin notes layer in); anonymous requests
    get request.user_id=None and the general bot (no per-user reads/
    writes, no DSP attribution). NEVER 401s — signed-out chat works.

    ─────────────────────────────────────────────────────────────────
    Phase Stress-Contrast (BE-3) — dual-mode body parsing
    ─────────────────────────────────────────────────────────────────
    This endpoint additively supports a ``multipart/form-data`` body
    when the frontend captures audio alongside the typed/dictated
    question. Path A (text → LLM) is unchanged. Path B (audio → DSP)
    fires asynchronously via ``casual_voice_analytics`` and never
    blocks the HTTP response.

    Multipart fields (all when Path B applies):
      - question:              str (required; same semantics as JSON)
      - history:               JSON-stringified list (optional)
      - audio_file:            webm/opus blob (required for Path B)
      - transcript_source:     "web_speech" | "server_whisper"
                                (default "web_speech")
      - audio_duration_sec:    float hint (optional)

    JSON callers (the existing path) keep the exact same request
    and response shape — no regression.
    """
    try:
        transport = _parse_chat_request(request)
        question = transport["question"]
        history = transport["history"]
        audio_bytes = transport["audio_bytes"]
        transcript_source = transport["transcript_source"]
        audio_duration_sec = transport["audio_duration_sec"]
        presentation_context = transport["presentation_context"]
        persist_thread = transport["persist_thread"]
        user_client_id = transport["user_client_id"]
        user_created_at = transport["user_created_at"]

        if not isinstance(question, str) or not question.strip():
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "question must be a non-empty string",
            }), 400

        def _finalize(resp, *, intent=None):
            """Persist this turn server-side (founder #2) when the FE opted in
            and the caller is signed in, then return the 200. The bot row carries
            suggested_action + bubbles in its metadata so the contextual chip
            (trainings / strong_sides / best-presentation) reconstructs on
            rehydrate — exactly what was vanishing on relogin. Best-effort: a
            persist failure never fails the chat response."""
            return _finalize_chat_response(
                resp, user_id=request.user_id, question=question,
                persist_thread=persist_thread,
                user_client_id=user_client_id,
                user_created_at=user_created_at, intent=intent,
            )

        # ── Life Panel hashtag router (founder 2026-07-26) — the FIRST
        # intercept, and the feature's ONLY contact point with this file.
        #
        # It fires on a leading `#tag` from a signed-in user who has consented
        # to the Life Panel, and on nothing else. Three guards, cheapest
        # first, so a normal chat turn pays ~nothing:
        #   1. LIFE_PANEL_ENABLED (default 0) — off, and this block is a
        #      boolean check that falls straight through.
        #   2. signed in — anonymous Lounge chat never reaches it.
        #   3. handle_note returns None for an untagged message BEFORE any DB
        #      read, and None for a non-consented user. None ⇒ we do not
        #      touch this turn at all.
        #
        # N3 is the contract: for a non-participating user every response on
        # this endpoint is byte-identical to main. That is why the fall-
        # through is `return None → keep going` rather than any modified
        # answer, and why the whole block is inside its own try/except — a
        # broken Life Panel must cost the panel, never the chat.
        if request.user_id and getattr(config, "LIFE_PANEL_ENABLED", False):
            try:
                from services.life_chat import handle_note
                from services.master_doc_rag import split_answer_into_bubbles
                _ln = handle_note(request.user_id, question.strip())
                if _ln:
                    _ans = _ln.get("answer") or ""
                    # The founder's own words, returned at the moment they
                    # apply — appended only when the wall actually had
                    # something above the relevance floor.
                    _ph = _ln.get("phrase") or {}
                    if _ph.get("body"):
                        _ans = f"{_ans}\n\n“{_ph['body']}”"
                    return _finalize({
                        "answer": _ans,
                        "bubbles": split_answer_into_bubbles(_ans),
                        "show_record_ui": False,
                        "suggested_action": None,
                        "debug": {"intent": "life_panel",
                                  "route": _ln.get("route"),
                                  "link": _ln.get("link")},
                    }, intent="life_panel")
            except Exception as _le:
                logger.warning(
                    "chat/query: life-panel intercept failed user=%s: %s",
                    request.user_id, _le,
                )

        # ── Goal-update intercept (Prompt A §6 C4) — BEFORE the librarian.
        # §0: never add rules to master_doc_rag (attention ceiling). A
        # signed-in user saying "change my goal to X" (any language) updates
        # user_settings.profile_goal and gets an in-language confirmation;
        # the librarian is short-circuited for that turn. Cheap pre-gate
        # inside, so normal chat turns spend no extra LLM call. Best-effort:
        # any failure falls through to the normal answer.
        if request.user_id:
            try:
                from services.goal_update import handle_goal_update
                from services.master_doc_rag import split_answer_into_bubbles
                _gu = handle_goal_update(request.user_id, question.strip())
                if _gu and _gu.get("answer"):
                    return _finalize({
                        "answer": _gu["answer"],
                        "bubbles": split_answer_into_bubbles(_gu["answer"]),
                        "show_record_ui": False,
                        "suggested_action": None,
                        "debug": {
                            "intent": "goal_update",
                            "new_goal": _gu.get("new_goal"),
                        },
                    }, intent="goal_update")
            except Exception as _ge:
                logger.warning(
                    "chat/query: goal-update intercept failed user=%s: %s",
                    request.user_id, _ge,
                )

        # ── Audit intercept (Prompt C §5) — BEFORE the librarian (§0: no
        # master_doc_rag rule edits). A signed-in user asking for their audit
        # gets a short bubble + the audit button (suggested_action="audit")
        # opening the audits page. Deterministic keyword pre-gate inside, so
        # normal chat pays nothing. Best-effort: any failure falls through.
        # Prompt D: RETIRED by default (the Best-Presentation replaces the
        # audit). AUDIT_SURFACE_ENABLED=1 restores it (endpoints stay dormant).
        if request.user_id and getattr(config, "AUDIT_SURFACE_ENABLED", False):
            try:
                from services.audit_intent import handle_audit_intent
                from services.master_doc_rag import split_answer_into_bubbles
                _ai = handle_audit_intent(request.user_id, question.strip())
                if _ai and _ai.get("suggested_action") == "audit":
                    _ans = _ai.get("answer") or ""
                    return _finalize({
                        "answer": _ans,
                        "bubbles": split_answer_into_bubbles(_ans),
                        "show_record_ui": False,
                        "suggested_action": "audit",
                        "debug": {"intent": "audit"},
                    }, intent="audit")
            except Exception as _ae:
                logger.warning(
                    "chat/query: audit intercept failed user=%s: %s",
                    request.user_id, _ae,
                )

        # Presentation/deck changes are project-boundary decisions, not open-
        # ended coaching prose.  Resolve them deterministically from the
        # current project's explicit state before the general librarian can
        # improvise a mutation or collapse two talks together.
        try:
            from services.presentation_change_intent import (
                handle_presentation_change,
            )
            from services.master_doc_rag import split_answer_into_bubbles
            _pi = handle_presentation_change(
                question.strip(), presentation_context,
            )
            if _pi:
                _ans = _pi["answer"]
                return _finalize({
                    "answer": _ans,
                    "bubbles": split_answer_into_bubbles(_ans),
                    "show_record_ui": False,
                    "suggested_action": None,
                    "suggested_actions": _pi["suggested_actions"],
                    "debug": {"intent": _pi["intent"]},
                }, intent=_pi["intent"])
        except Exception as _pie:
            logger.warning(
                "chat/query: presentation-change intercept failed: %s", _pie,
            )

        # ── Lounge-bot deterministic intercepts (chat-audit 2026-06-21) —
        # BEFORE the librarian (§0: keep these OUT of master_doc_rag's mega-
        # prompt; the attention ceiling is full and the probe grades the LLM
        # path). Crisis (safety) → record CTA (the acquisition lever, #4:
        # show_record_ui + suggested_action="record_again", reversing #119 for
        # CLEAR intent) → off-mission generative deflect. Runs for anonymous +
        # signed-in; the goal/audit intercepts above are signed-in-only + more
        # specific, so they win for those phrasings. Best-effort.
        try:
            from services.chat_intents import detect_chat_intent
            from services.master_doc_rag import split_answer_into_bubbles
            _ci = detect_chat_intent(question.strip())
            if _ci:
                _ans = _ci["answer"]
                return _finalize({
                    "answer": _ans,
                    "bubbles": split_answer_into_bubbles(_ans),
                    "show_record_ui": _ci["show_record_ui"],
                    "suggested_action": _ci["suggested_action"],
                    "debug": {"intent": _ci["intent"]},
                }, intent=_ci["intent"])
        except Exception as _cie:
            logger.warning("chat/query: chat-intent intercept failed: %s", _cie)

        # ── Path A — LLM answer (the only thing the HTTP response
        # carries back). Unchanged from the pre-BE-3 behavior.
        # Pull admin's private notes for this user → don't-ask block
        # in the FAQ chat system prompt. @require_auth guarantees a
        # user_id; best-effort on the DB read.
        # Per-user layers (admin don't-ask notes + the strong-sides
        # library) apply only when signed in. Anonymous (unsigned-home,
        # §3) gets the general bot — no per-user reads. Both best-effort.
        admin_dont_ask_notes: str | None = None
        library_entries: list | None = None
        if request.user_id:
            try:
                _settings = db.get_user_settings(request.user_id) or {}
                admin_dont_ask_notes = (
                    _settings.get("private_admin_notes") or None
                )
            except Exception as e:
                logger.warning(
                    "chat/query: private_admin_notes load failed "
                    "user=%s: %s", request.user_id, e,
                )

            # willab §3.12 — the user's strong-sides library (coach
            # notes) for the Lounge bot to retrieve/replay. The librarian
            # guardrail (no trajectory/scores) lives in answer_question.
            #
            # B3 — distinguish a GENUINE empty library ([]) from a transient
            # LOAD FAILURE (None). Both used to collapse to None via
            # `or None`, so a failed load read as "no notes" for a user who
            # actually has them — inconsistent turn-to-turn. Retry once, and
            # log every outcome so the real failure rate is measurable.
            #   library_entries == []   → genuinely no notes (bot may say so)
            #   library_entries is None → load FAILED after retry (NOT empty)
            for _attempt in (1, 2):
                try:
                    library_entries = db.get_strong_sides_library(
                        request.user_id
                    ) or []
                    logger.info(
                        "chat/query: library loaded user=%s entries=%d "
                        "(attempt %d)", request.user_id,
                        len(library_entries), _attempt,
                    )
                    break
                except Exception as e:
                    logger.warning(
                        "chat/query: library load failed user=%s "
                        "(attempt %d): %s", request.user_id, _attempt, e,
                    )
                    library_entries = None

        # BE-9 — the Life Panel's per-user block, for participating users only.
        # Retrieved at request time from the requesting user's OWN rows, capped
        # to the top few by relevance; the renderer in master_doc_rag trims and
        # caps again. Everyone else — flag off, not signed in, not consented —
        # passes None, so their prompt is byte-for-byte what it is today.
        # Best-effort: a failed load costs the grounding, never the answer.
        life_context = None
        if request.user_id and getattr(config, "LIFE_PANEL_ENABLED", False):
            try:
                from services.life_chat import has_consented
                if has_consented(request.user_id):
                    from services.life_engine import life_chat_context
                    life_context = life_chat_context(
                        request.user_id, question.strip())
            except Exception as _lce:
                logger.warning(
                    "chat/query: life context load failed user=%s: %s",
                    request.user_id, _lce,
                )

        from services.master_doc_rag import (
            answer_question, split_answer_into_bubbles,
        )
        payload, debug = answer_question(
            question.strip(),
            history=history,
            admin_dont_ask_notes=admin_dont_ask_notes,
            library_entries=library_entries,
            # B3 — None (after retry) means the load FAILED, not empty.
            library_load_failed=bool(request.user_id and library_entries is None),
            life_context=life_context,
        )

        # ── Path B — fire-and-forget DSP extraction. Spawned BEFORE
        # the jsonify so the daemon's stack frame exists by the time
        # the request worker recycles, but AFTER Path A so we never
        # delay the LLM. The dispatch itself is a thread.start() —
        # microseconds; safe to do before returning. Failure to
        # dispatch is logged and swallowed; the LLM answer still
        # ships.
        # Anonymous (unsigned-home) chat skips DSP capture — there's no
        # user to attribute the casual-voice benchmark to.
        if audio_bytes and request.user_id:
            try:
                from services.casual_voice_analytics import (
                    analyze_casual_audio_async,
                )
                analyze_casual_audio_async(
                    user_id=str(request.user_id),
                    # session_id is None for pure Lounge chat — the
                    # endpoint isn't session-bound. The column on
                    # casual_voice_benchmarks is nullable for this
                    # exact reason; see migration comment.
                    session_id=None,
                    audio_bytes=audio_bytes,
                    transcript=question.strip(),
                    duration_sec=audio_duration_sec,
                    transcript_source=transcript_source,
                )
            except Exception as cv_err:
                # The dispatcher should never raise (it's just a
                # thread.start), but defense-in-depth: a broken
                # casual-voice path MUST NOT take down the chat
                # response. Log and move on.
                logger.warning(
                    "chat/query: casual_voice dispatch failed "
                    "user=%s err=%s (non-fatal — LLM answer still "
                    "returned)",
                    request.user_id, cv_err,
                )

        # S1 — per-turn intent → the one contextual button the FE renders.
        # ("audit" is set by the audit intercept above, not the librarian, but
        # is a valid enum value so the FE contract stays consistent.)
        _sa = payload.get("suggested_action")
        if _sa not in ("strong_sides", "trainings", "audit"):
            _sa = None
        _answer = payload.get("answer", "")
        return _finalize({
            "answer": _answer,
            # FE #157 — pre-split chat bubbles (renders 1:1; falls back to
            # splitting `answer` on blank lines when absent). `answer` stays
            # the fallback.
            "bubbles": split_answer_into_bubbles(_answer),
            "show_record_ui": bool(payload.get("show_record_ui", False)),
            "suggested_action": _sa,
            "debug": debug,
        }, intent=(debug or {}).get("intent") or "faq")

    except Exception as e:
        logger.error("chat/query failed: %s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Chat query failed",
        }), 500


@v2_bp.route("/chat/snippet-followup", methods=["POST"])
@llm_limit
@require_auth
def v2_chat_snippet_followup():
    """One-shot follow-up question generator after a user labels a snippet.

    Body (JSON):
      - snippet_id (UUID, required)
      - user_label (bool, required) — AGREEMENT semantic; see module-level
        comment above and ``docs/PANEL-STATE-MATRIX.md`` preamble.

    Response 200 (JSON):
      {
        "followup_text": "<≤2-sentence question>",
        "debug": {
          "model": "gpt-4o-mini",
          "user_label_interpretation": "agreement"
        }
      }

    Errors:
      400 INVALID_INPUT                — missing/malformed fields
      404 NOT_FOUND                    — snippet missing OR not owner-scoped
      422 SNIPPET_CONTEXT_UNAVAILABLE  — snippet lacks admin_comment
      500 V2_ERROR                     — LLM/parse/other failure
    """
    try:
        user_id = request.user_id
        body = request.get_json(silent=True) or {}

        # ── Input validation ──
        snippet_id = (body.get("snippet_id") or "").strip()
        if not snippet_id or not _is_valid_uuid(snippet_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "snippet_id must be a valid UUID",
            }), 400

        user_label_raw = body.get("user_label")
        if not isinstance(user_label_raw, bool):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "user_label must be a boolean (agreement semantic)",
            }), 400
        user_label: bool = user_label_raw

        # ── Owner-scoped fetch ──
        # 404 (not 403) on foreign-owner so we don't leak existence.
        snippet = db.get_snippet_by_id(snippet_id, user_id=user_id)
        if not snippet:
            return jsonify({
                "code": "NOT_FOUND",
                "error": "Snippet not found",
            }), 404

        admin_comment = (snippet.get("admin_comment") or "").strip()
        if not admin_comment:
            # Without the coach's insight the follow-up question would
            # be ungrounded ("how did that make you feel?" style filler).
            # Refuse rather than emit something vapid.
            return jsonify({
                "code": "SNIPPET_CONTEXT_UNAVAILABLE",
                "error": "Snippet has no admin_comment yet",
            }), 422

        transcript = (
            (snippet.get("transcript") or "")
            or (snippet.get("transcription_text") or "")
            or (snippet.get("transcript_text") or "")
            or (snippet.get("transcript_excerpt") or "")
        ).strip()
        coach_label = (snippet.get("coach_label") or "").strip().lower() or None
        snippet_type = (snippet.get("snippet_type") or "").strip().lower() or None
        # Display label = whatever the AI/coach asserted about this
        # snippet, in user-facing words. Fall back through coach_label →
        # snippet_type → "this moment" so the prompt never reads
        # "you {None} this".
        display_label = coach_label or snippet_type or "this moment"

        # ── LLM call ──
        from services.llm import chat_complete
        from services.llm_config import SPEC_SNIPPET_FOLLOWUP

        agreement_phrase = (
            "The user AGREES with the coach's label."
            if user_label
            else "The user DISAGREES with the coach's label."
        )
        system = (
            "You are a warm, curious communication coach. After a "
            "user has agreed or disagreed with a coach's label on a "
            "moment from their own speech, you ask ONE short "
            "follow-up question (≤2 sentences) that invites them to "
            "reflect on why. Anchor your question to the specific "
            "coach insight provided; never ask generic 'how did that "
            "feel' filler. Output strict JSON: "
            '{"followup_text": "<question>"}.'
        )
        user_prompt = (
            f"Coach's label on this snippet: {display_label}\n"
            f"Coach's written insight (admin_comment):\n{admin_comment}\n"
            f"User's spoken transcript on this moment:\n"
            f"{transcript or '(no transcript captured)'}\n\n"
            f"User's response: {agreement_phrase}\n\n"
            "Return strict JSON with a single key followup_text."
        )

        result = chat_complete(
            spec=SPEC_SNIPPET_FOLLOWUP,
            system=system,
            user=user_prompt,
            surface="snippet_followup",
            user_id=str(user_id),
        )
        if result is None:
            # chat_complete already logged the failure reason.
            return jsonify({
                "code": "V2_ERROR",
                "error": "Failed to generate follow-up",
            }), 500

        parsed = result.parsed
        if not isinstance(parsed, dict):
            logger.error(
                "snippet_followup.malformed_json user=%s snippet=%s raw=%r",
                user_id, snippet_id, result.text[:200],
            )
            return jsonify({
                "code": "V2_ERROR",
                "error": "Coach response was malformed",
            }), 500
        followup_text = (parsed.get("followup_text") or "").strip()

        if not followup_text:
            logger.warning(
                "snippet_followup.empty_text user=%s snippet=%s",
                user_id, snippet_id,
            )
            return jsonify({
                "code": "V2_ERROR",
                "error": "Coach returned an empty follow-up",
            }), 500

        return jsonify({
            "followup_text": followup_text,
            "debug": {
                "model": result.model,
                # PIN: never change to "type" without coordinated FE
                # update + matrix-doc preamble update. See module-level
                # comment for the full contract.
                "user_label_interpretation": "agreement",
            },
        }), 200

    except Exception as e:
        logger.error("snippet_followup.error err=%s", e, exc_info=True)
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to generate follow-up",
        }), 500


_INTERVIEW_FINALIZE_VALID_REASONS = {"threshold", "max_turns", "user_done"}

# Signup-CTA default copy. Task 7 — confirmed wording from the FE
# handoff reply (matches the brainstorm's "Sign up for full
# analysis" phrasing). Surfaced as `next.signup_cta.copy` in the
# finalize response — a BE flag (not FE hardcoded) so the copy is
# A/B-able without a FE deploy and per-user variants can fan out
# later (e.g. warm-lead vs cold).
_FINALIZE_SIGNUP_CTA_COPY = (
    "Sign up for your full analysis."
)


_COACHING_INTRO_STATIC_FALLBACK = (
    "Now let's record a fresh take and see what shifts. "
    "Tap the mic below when you're ready."
)


@v2_bp.route("/coaching/intro-bubble", methods=["POST"])
@llm_limit
@require_auth
def v2_coaching_intro_bubble():
    """Generate a personalized intro line for the new official
    recording session that follows snippet labeling.

    Body (JSON):
      - snippet_id (UUID, required) — the snippet the user just
        labeled. Used to ground the intro in real context.

    Response 200 (always — see fallback contract below):
      {
        "intro_text": "<1–2 sentence intro string>",
        "debug": {
          "model": "gpt-4o-mini",
          "prompt_version": "coaching_intro_v1",
          "source": "llm" | "static_fallback"
        }
      }

    Errors:
      400 INVALID_INPUT  — missing / malformed snippet_id
      404 NOT_FOUND      — snippet missing or not owner-scoped

    Fallback contract: when the LLM call fails OR the snippet is
    missing admin_comment, we still return 200 with the static
    fallback string. The FE NEVER has to handle "intro generation
    failed" — it always gets a usable string.
    """
    try:
        user_id = request.user_id
        body = request.get_json(silent=True) or {}

        snippet_id = (body.get("snippet_id") or "").strip()
        if not snippet_id or not _is_valid_uuid(snippet_id):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "snippet_id must be a valid UUID",
            }), 400

        # Owner-scoped fetch. Foreign / nonexistent → 404 (no
        # existence leak).
        snippet = db.get_snippet_by_id(snippet_id, user_id=user_id)
        if not snippet:
            return jsonify({
                "code": "NOT_FOUND",
                "error": "Snippet not found",
            }), 404

        # ── Directives queue takes priority (Item 7 / Phase 2) ──
        # If the admin has authored a directive arc for this user,
        # pop the next un-exhausted entry and use its question as
        # the intro line — this "smoothly introduces" the admin's
        # next question for the fresh recording session. The
        # admin-authored copy wins over the LLM personalization.
        try:
            directive = db.pop_next_directive(str(user_id))
        except Exception as pop_err:
            logger.warning(
                "coaching_intro_bubble.pop_directive_failed "
                "user=%s err=%s — falling through to LLM path",
                user_id, pop_err,
            )
            directive = None

        if directive and (directive.get("question") or "").strip():
            logger.info(
                "coaching_intro_bubble.directives_queue_hit "
                "user=%s pos=%s intent=%s",
                user_id, directive.get("position"),
                directive.get("intent_tag"),
            )
            return jsonify({
                "intro_text": directive["question"].strip(),
                "debug": {
                    "model": "gpt-4o-mini",
                    "prompt_version": "coaching_intro_v1",
                    "source": "directives_queue",
                    "directive": {
                        "position": directive.get("position"),
                        "intent_tag": directive.get("intent_tag"),
                    },
                },
            }), 200

        # Try the LLM path. ``generate_intro_line`` returns None on
        # any failure mode — we then drop to the static fallback.
        from services.coaching_intro import (
            generate_intro_line,
            PROMPT_VERSION,
        )
        intro = None
        try:
            intro = generate_intro_line(
                user_id=str(user_id),
                snippet=snippet,
            )
        except Exception as gen_err:
            # Defensive: generate_intro_line is supposed to swallow
            # its own errors, but if anything escapes we still want
            # to return 200 with the fallback.
            logger.warning(
                "coaching_intro_bubble.generator_raised user=%s "
                "snippet=%s err=%s — using fallback",
                user_id, snippet_id, gen_err,
            )
            intro = None

        if intro:
            return jsonify({
                "intro_text": intro,
                "debug": {
                    "model": "gpt-4o-mini",
                    "prompt_version": PROMPT_VERSION,
                    "source": "llm",
                },
            }), 200

        # Fallback path — still 200. The FE renders this string
        # exactly like the LLM path; ``debug.source`` lets devs
        # spot fallback rates without consulting backend logs.
        return jsonify({
            "intro_text": _COACHING_INTRO_STATIC_FALLBACK,
            "debug": {
                "model": "gpt-4o-mini",
                "prompt_version": PROMPT_VERSION,
                "source": "static_fallback",
            },
        }), 200

    except Exception as e:
        logger.error(
            "coaching_intro_bubble.error err=%s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        # Last-resort: still return 200 with the static fallback so
        # the FE flow never breaks on a backend bug. Matches the
        # "always usable string" contract above.
        return jsonify({
            "intro_text": _COACHING_INTRO_STATIC_FALLBACK,
            "debug": {
                "model": "gpt-4o-mini",
                "prompt_version": "coaching_intro_v1",
                "source": "static_fallback",
            },
        }), 200


@v2_bp.route("/onboarding/opener/start", methods=["POST"])
@llm_limit
@optional_auth
def v2_onboarding_opener_start():
    """Begin the dad-joke onboarding opener.

    No body required. Picks a random active joke and returns the
    setup bubble shape::

        {
          "stage": "setup",
          "joke_id": "<uuid>",
          "frame":  "Attention, before we begin, let me crack a dad-joke!",
          "setup":  "How do cows stay up to date?"
        }

    Returns 204 (no opener) when the dad_jokes table is empty / not
    yet migrated — FE skips the opener and goes straight to the
    real first onboarding question. Silent fallback by design: the
    joke is decorative, never blocking.
    """
    try:
        from services.onboarding_opener import (
            pick_random_joke, build_setup_message,
        )
        joke = pick_random_joke()
        if not joke:
            logger.info(
                "opener.start.no_joke user=%s — skipping opener",
                request.user_id,
            )
            return ("", 204)
        payload = build_setup_message(joke)
        return jsonify(payload), 200
    except Exception as e:
        logger.error(
            "onboarding/opener/start failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        # Soft-fail: opener is decorative; return 204 so FE skips
        # without showing an error banner on the user's first
        # onboarding screen.
        return ("", 204)


@v2_bp.route("/onboarding/opener/next", methods=["POST"])
@llm_limit
@optional_auth
def v2_onboarding_opener_next():
    """Advance the opener to the next bubble.

    Body::

        {
          "joke_id":          "<uuid>",        # required
          "user_reply":       "<string>",      # optional, used for ack
          "after_punchline":  false            # default false
        }

    Stage transitions:
      after_punchline=false → returns the PUNCHLINE bubble:
        {
          "stage":     "punchline",
          "joke_id":   "<uuid>",
          "ack":       "<≤80-char LLM bridge>",   # may be ""
          "punchline": "They read the moos-paper. 🐄"
        }

      after_punchline=true → returns the PIVOT bubble:
        {
          "stage":      "pivot",
          "joke_id":    null,
          "pivot_line": "Okok, nevermind. Let's focus on public speaking — how can I help you?",
          "done":       true
        }

    The pivot line is HARDCODED in services.onboarding_opener.
    PIVOT_LINE and never produced by the LLM. The ack on the
    punchline bubble is the only LLM-touched content in this flow.

    Responses:
      200 — normal flow
      400 INVALID_INPUT — missing/invalid joke_id
      404 JOKE_NOT_FOUND — joke_id resolves to nothing (admin
                            deactivated the joke between /start
                            and /next, or migration mismatch)
      500 V2_ERROR — unexpected; FE should bail to real onboarding
    """
    try:
        from services.onboarding_opener import (
            build_punchline_message,
            build_pivot_message,
            generate_punchline_ack,
        )

        body = request.get_json(silent=True) or {}
        joke_id_raw = body.get("joke_id")
        after_punchline = bool(body.get("after_punchline", False))
        user_reply = body.get("user_reply") or ""
        if not isinstance(user_reply, str):
            user_reply = ""

        # Pivot path — no joke lookup needed, pure constant return.
        # We accept (but don't require) joke_id here so the FE can
        # round-trip the same payload shape on every /next call.
        if after_punchline:
            return jsonify(build_pivot_message()), 200

        # Punchline path — joke_id is required and must resolve.
        if not joke_id_raw or not isinstance(joke_id_raw, str):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "joke_id is required for the punchline stage",
            }), 400
        if not _is_valid_uuid(joke_id_raw):
            return jsonify({
                "code": "INVALID_INPUT",
                "error": "joke_id must be a valid UUID",
            }), 400

        joke = db.get_dad_joke_by_id(joke_id_raw)
        if not joke:
            return jsonify({
                "code": "JOKE_NOT_FOUND",
                "error": "Joke not found",
            }), 404

        # LLM bridge ack — best-effort, empty string on any failure.
        ack = generate_punchline_ack(user_reply)
        payload = build_punchline_message(joke, ack=ack)
        return jsonify(payload), 200

    except Exception as e:
        logger.error(
            "onboarding/opener/next failed: %s", e, exc_info=True,
        )
        sentry_sdk.capture_exception(e)
        return jsonify({
            "code": "V2_ERROR",
            "error": "Failed to advance opener",
        }), 500
