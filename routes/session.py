from flask import Blueprint, request, jsonify
from auth import require_auth
from services.db import db
from services.question_service import (
    calculate_cursor,
    determine_mode,
    THEMES,
    INTENT_TO_THEME,
    filter_commands_for_theme_cursor_mode,
    get_commands_for_theme_ignore_cursor,
    get_commands_for_mode_any_theme,
    get_command_prompt_for_intent,
)
import random
import sentry_sdk
import logging

logger = logging.getLogger(__name__)
session_bp = Blueprint("session", __name__)


def _effective_mode(session):
    """Rollout: COALESCE(mode, structure) or 'guided'."""
    return (session.get("mode") or session.get("structure")) or "guided"


def _build_plan_response(session_id: str, session: dict, pre_questions_list: list, command_options_list: list):
    """Build v1 response JSON (theme_*, pre_questions length 1, command_options length 3, recommended_command_option_id, cursor, mode, structure)."""
    # Recommended command: use for recording without showing A/B/C picker (system chooses)
    recommended = "A"
    if command_options_list:
        primary = next((o for o in command_options_list if o.get("is_primary")), command_options_list[0])
        recommended = primary.get("option_id", "A")
    return {
        "session_id": session_id,
        "theme_recommended_code": session.get("theme_recommended_code"),
        "theme_recommended_reason": session.get("theme_recommended_reason"),
        "theme_chosen_code": session.get("theme_chosen_code"),
        "theme_chosen_source": session.get("theme_chosen_source"),
        "pre_questions": pre_questions_list,
        "command_options": command_options_list,
        "recommended_command_option_id": recommended,
        "cursor": session.get("cursor"),
        "mode": session.get("mode"),
        "structure": session.get("structure"),
    }


@session_bp.route("/start", methods=["POST"])
@require_auth
def start_session():
    """v1: Start or resume session; idempotent plan (theme → 1 preQ → 3 command options)."""
    try:
        user_id = request.user_id
        data = request.get_json() or {}
        resume_session_id = data.get("session_id")
        questionnaire = data.get("questionnaire")

        # --- Resume: load session by id ---
        if resume_session_id:
            session = db.get_session(resume_session_id, user_id)
            if not session:
                return jsonify({"code": "SESSION_NOT_FOUND", "error": "Session not found"}), 404
            session_id = session["id"]
            # Idempotent: if already planned, return existing plan
            if session.get("planned_pre_question_id"):
                opts = db.get_session_command_options(session_id)
                if len(opts) >= 3:
                    pre_questions = [{
                        "id": session["planned_pre_question_id"],
                        "code": session.get("planned_pre_question_code_snapshot"),
                        "question_text": session.get("planned_pre_question_text_snapshot") or "",
                        "question_type": session.get("planned_pre_question_type_snapshot") or "text_short",
                        "order_index": 0,
                    }]
                    command_options = [
                        {
                            "option_id": o["option_id"],
                            "intent": o["intent"],
                            "tier": o["tier"],
                            "mode": o["mode"],
                            "prompt_text_snapshot": o["prompt_text_snapshot"],
                            "is_primary": o.get("is_primary", False),
                        }
                        for o in opts[:3]
                    ]
                    return jsonify(_build_plan_response(session_id, session, pre_questions, command_options)), 200
        else:
            session_id = None
            session = None

        # --- New session or continue planning ---
        if not session:
            active_session = db.get_active_session(user_id)
            if active_session:
                session = active_session
                session_id = session["id"]
                # Idempotent: if already planned, return existing plan
                if session.get("planned_pre_question_id"):
                    opts = db.get_session_command_options(session_id)
                    if len(opts) >= 3:
                        pre_questions = [{
                            "id": session["planned_pre_question_id"],
                            "code": session.get("planned_pre_question_code_snapshot"),
                            "question_text": session.get("planned_pre_question_text_snapshot") or "",
                            "question_type": session.get("planned_pre_question_type_snapshot") or "text_short",
                            "order_index": 0,
                        }]
                        command_options = [
                            {"option_id": o["option_id"], "intent": o["intent"], "tier": o["tier"], "mode": o["mode"],
                             "prompt_text_snapshot": o["prompt_text_snapshot"], "is_primary": o.get("is_primary", False)}
                            for o in opts[:3]
                        ]
                        return jsonify(_build_plan_response(session_id, session, pre_questions, command_options)), 200

            if not session_id:
                # Create new session
                mood = "positive"
                readiness = 5
                inspiration_needed = False
                cursor = None
                mode = None
                pre_questions_completed = False
                session_status = "pre_questions_pending"
                if questionnaire:
                    mood = questionnaire.get("mood", "positive")
                    if mood not in ["positive", "negative"]:
                        mood = "positive"
                    readiness = questionnaire.get("readiness", 5)
                    if not isinstance(readiness, int) or readiness < 1 or readiness > 10:
                        readiness = 5
                    inspiration_needed = bool(questionnaire.get("inspiration_needed", False))
                    cursor = questionnaire.get("cursor")
                    if cursor is None:
                        cursor = calculate_cursor(mood, readiness)
                    mode = questionnaire.get("mode")
                    if mode is None:
                        mode = determine_mode(inspiration_needed)
                    pre_questions_completed = True
                    session_status = "recording_ready"
                if mode is None:
                    mode = "guided"
                if cursor is None:
                    cursor = 0.5
                session = db.create_session(
                    user_id=user_id,
                    cursor=cursor,
                    mode=mode,
                    mood=mood,
                    readiness=readiness,
                    inspiration_needed=inspiration_needed,
                    pre_questions_completed=pre_questions_completed,
                    status=session_status,
                )
                if not session:
                    return jsonify({"code": "SESSION_CREATE_FAILED", "error": "Failed to create session"}), 500
                session_id = session["id"]
                # Rollout: mirror mode into structure
                db.client.table("recording_sessions").update({"structure": mode}).eq("id", session_id).execute()
                session["structure"] = mode

        # Reload session for latest fields
        session = db.get_session(session_id, user_id)
        cursor = session.get("cursor")
        if cursor is None:
            cursor = 0.5
        mode = session.get("mode") or session.get("structure") or "guided"

        # --- Admin override (consume once) ---
        override = db.get_active_override(user_id)
        if override and session.get("admin_override_consumed_at") is None:
            theme_forced = override.get("force_theme_code")
            mode_forced = override.get("force_mode")
            if theme_forced:
                db.update_session_theme(session_id, chosen_code=theme_forced, chosen_source="admin")
            if mode_forced:
                db.client.table("recording_sessions").update({"mode": mode_forced, "structure": mode_forced}).eq("id", session_id).execute()
                session["mode"] = mode_forced
                session["structure"] = mode_forced
                mode = mode_forced
            db.update_session_admin_override_consumed(session_id, override["id"])
            db.consume_admin_override(override["id"])
            session = db.get_session(session_id, user_id)

        # --- Theme ---
        theme_chosen = session.get("theme_chosen_code")
        theme_source = session.get("theme_chosen_source")
        if not theme_chosen:
            admin_theme = override.get("force_theme_code") if override else None
            user_theme = questionnaire.get("theme_code") if questionnaire else None
            recent_themes = []
            if admin_theme:
                theme_chosen = admin_theme
                theme_source = "admin"
            elif user_theme and user_theme in THEMES:
                theme_chosen = user_theme
                theme_source = "user"
            else:
                recent_themes = db.get_recent_theme_exposures_by_session(user_id, limit_sessions=2)
                candidates = [t for t in THEMES if t not in recent_themes]
                theme_chosen = random.choice(candidates) if candidates else random.choice(THEMES)
                theme_source = "system"
            db.update_session_theme(
                session_id,
                recommended_code=theme_chosen if theme_source == "system" else None,
                recommended_reason="anti-repeat" if (theme_source == "system" and recent_themes) else None,
                chosen_code=theme_chosen,
                chosen_source=theme_source,
            )
            db.log_exposure(user_id, "theme", theme_chosen, session_id=session_id)
        session = db.get_session(session_id, user_id)
        theme_chosen = session.get("theme_chosen_code") or theme_chosen

        # --- Plan 1 pre-question (exclude "How are you feeling today?" – that step is removed from flow) ---
        if not session.get("planned_pre_question_id"):
            recent_pre = db.get_recent_exposures(user_id, "pre_q_template", 5)
            exclude_codes = [r.get("content_code") for r in recent_pre if r.get("content_code")]
            templates = db.get_pre_question_templates_for_theme(theme_chosen, exclude_codes=exclude_codes or None, limit=3)
            if not templates:
                templates = db.get_pre_question_templates_for_theme(None, limit=3)
            # Do not plan "How are you feeling today?" (step 1.5 removed)
            skip_text = "how are you feeling today"
            templates = [t for t in templates if (t.get("question_text") or "").strip().lower() != skip_text]
            if templates:
                t = templates[0]
                db.update_session_planned_pre_question(
                    session_id,
                    planned_id=t["id"],
                    text_snapshot=t.get("question_text", ""),
                    type_snapshot=t.get("question_type", "text_short"),
                    code_snapshot=t.get("code", ""),
                )
                db.log_exposure(user_id, "pre_q_template", t.get("code", ""), session_id=session_id, content_id=t["id"])
            session = db.get_session(session_id, user_id)

        # --- Plan 3 command options (always ≥3: strict filter → theme-any-cursor → any-theme) ---
        opts = db.get_session_command_options(session_id)
        if len(opts) < 3:
            effective_mode = _effective_mode(session)
            completed_count = db.get_completed_sessions_count(user_id)
            avg_fillers = db.get_avg_fillers_per_min(user_id, 5)
            no_fillers_eligible = (
                cursor >= 0.60 and completed_count >= 3 and avg_fillers < 15
            )
            recent_intent = db.get_recent_exposures(user_id, "intent", 3)
            recent_codes = [r.get("content_code") for r in recent_intent if r.get("content_code")]

            # 1) Strict: theme + cursor + mode
            candidates = filter_commands_for_theme_cursor_mode(
                theme_chosen, cursor, effective_mode, no_fillers_eligible
            )
            candidates = [c for c in candidates if c["intent"] not in recent_codes]
            seen_intents = {c["intent"] for c in candidates}

            # 2) Fallback: same theme, any cursor (so e.g. confidence_comfort always has options)
            if len(candidates) < 3:
                extra = get_commands_for_theme_ignore_cursor(
                    theme_chosen, effective_mode, no_fillers_eligible
                )
                for c in extra:
                    if c["intent"] not in recent_codes and c["intent"] not in seen_intents:
                        candidates.append(c)
                        seen_intents.add(c["intent"])
                        if len(candidates) >= 5:
                            break

            # 3) Last resort: any theme, same mode (never leave user with 0 options)
            if len(candidates) < 3:
                any_theme = get_commands_for_mode_any_theme(effective_mode, no_fillers_eligible)
                random.shuffle(any_theme)
                for c in any_theme:
                    if c["intent"] not in recent_codes and c["intent"] not in seen_intents:
                        candidates.append(c)
                        seen_intents.add(c["intent"])
                        if len(candidates) >= 5:
                            break

            # 4) Guarantee ≥3: if anti-repeat left us short, allow repeats so we never show blank
            if len(candidates) < 3:
                any_theme = get_commands_for_mode_any_theme(effective_mode, no_fillers_eligible)
                random.shuffle(any_theme)
                for c in any_theme:
                    if c["intent"] not in seen_intents:
                        candidates.append(c)
                        seen_intents.add(c["intent"])
                        if len(candidates) >= 5:
                            break

            candidates = candidates[:5]
            random.shuffle(candidates)
            selected = candidates[:3]
            option_ids = ["A", "B", "C"]
            options_payload = []
            for i, cmd in enumerate(selected[:3]):
                opt_id = option_ids[i]
                prompt_text = get_command_prompt_for_intent(cmd["intent"], i % 3)
                options_payload.append({
                    "option_id": opt_id,
                    "intent": cmd["intent"],
                    "tier": cmd["tier"],
                    "mode": effective_mode,
                    "prompt_text_snapshot": prompt_text,
                    "is_primary": i == 0,
                    "cursor_min": cmd["cursor_range"][0],
                    "cursor_max": cmd["cursor_range"][1],
                })
                db.log_exposure(
                    user_id, "intent", cmd["intent"],
                    session_id=session_id, tier=cmd["tier"], was_selected=False
                )
            db.insert_session_command_options(session_id, options_payload)
            opts = db.get_session_command_options(session_id)

        # --- Response ---
        session = db.get_session(session_id, user_id)
        pre_questions = []
        if session.get("planned_pre_question_id"):
            pre_questions = [{
                "id": session["planned_pre_question_id"],
                "code": session.get("planned_pre_question_code_snapshot"),
                "question_text": session.get("planned_pre_question_text_snapshot") or "",
                "question_type": session.get("planned_pre_question_type_snapshot") or "text_short",
                "order_index": 0,
            }]
        elif session.get("planned_pre_question_text_snapshot"):
            pre_questions = [{
                "id": session.get("planned_pre_question_id"),
                "code": session.get("planned_pre_question_code_snapshot"),
                "question_text": session.get("planned_pre_question_text_snapshot"),
                "question_type": session.get("planned_pre_question_type_snapshot") or "text_short",
                "order_index": 0,
            }]
        command_options = [
            {
                "option_id": o["option_id"],
                "intent": o["intent"],
                "tier": o["tier"],
                "mode": o["mode"],
                "prompt_text_snapshot": o["prompt_text_snapshot"],
                "is_primary": o.get("is_primary", False),
            }
            for o in (opts or [])[:3]
        ]
        if not pre_questions and command_options:
            pre_questions = [{"id": "fallback-0", "code": "fallback", "question_text": "What would you like to say?", "question_type": "text_short", "order_index": 0}]
        return jsonify(_build_plan_response(session_id, session, pre_questions, command_options)), 200

    except Exception as e:
        logger.error(f"Session start error: {str(e)}")
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "SESSION_ERROR", "error": str(e)}), 500


@session_bp.route("/abandon", methods=["POST"])
@require_auth
def abandon_session():
    """Abandon the current active session"""
    try:
        user_id = request.user_id
        active_session = db.get_active_session(user_id)
        if not active_session:
            return jsonify({"code": "NO_ACTIVE_SESSION", "error": "No active session found"}), 404
        session_id = active_session["id"]
        db.abandon_session(session_id, user_id)
        return jsonify({"message": "Session abandoned"}), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "ABANDON_ERROR", "error": str(e)}), 500


@session_bp.route("/status", methods=["GET"])
@require_auth
def get_session_status():
    """Get current session status"""
    try:
        user_id = request.user_id
        active_session = db.get_active_session(user_id)
        if not active_session:
            return jsonify({"active": False}), 200
        return jsonify({
            "active": True,
            "session_id": active_session["id"],
            "pre_completed": active_session.get("pre_questions_completed", False),
            "recording_completed": active_session.get("recording_completed", False),
            "post_completed": active_session.get("post_questions_completed", False),
            "recording_id": active_session.get("recording_id"),
        }), 200
    except Exception as e:
        sentry_sdk.capture_exception(e)
        return jsonify({"code": "STATUS_ERROR", "error": str(e)}), 500
