"""The /v2 route layer's registration + compatibility façade.

Every /v2 route now lives in a domain module under ``routes/v2/``. This
module holds NO route code: importing it imports each domain module, which
is what REGISTERS that domain's routes on the shared ``v2_bp``, and it
re-exports every moved name so ``routes.v2_routes.<name>`` keeps resolving.

  blueprint            the shared v2_bp object
  common / arcs        cross-domain leaves + the arc domain
  lab_recording        the Lab upload path (record -> take)
  coach                the coach review surface
  user_sessions        takes + readouts        user_chat      interview Qs
  user_account         profile + consent       lounge         the Lounge thread
  explore_ideal_text   the ideal-text surface
  admin                the admin console       coaching       chat/coaching
  publish              the internal publish    funnel         guest -> account
  reflection           the Reflection Game

Import order is load-bearing: app.py imports this module, and every domain
module must be imported BEFORE the blueprint is registered on the app --
Flask rejects route additions to an already-registered blueprint.

`is_admin` / `is_coach` are re-exported from routes.admin because the test
suite patches those names on THIS module.
"""
# Compatibility surface. The suite reaches the shared singletons THROUGH this
# module (`v2.db.<method>` is patched at ~360 sites, and `patch.object(v2,
# "is_admin"/"is_coach")` rebinds these names here), so the façade must keep
# exporting them even though no route code lives here any more.
from flask import jsonify, request  # noqa: F401 — re-exported for import compat
from config import Config
from routes.admin import (  # noqa: F401 — re-exported: tests patch these here
    is_admin,
    is_coach,
    require_admin,
    require_admin_or_coach,
)
from services.db import db  # noqa: F401 — re-exported: tests patch v2.db.<method>

config = Config()

# `v2_bp` lives in routes/v2/blueprint.py so the domain modules below can
# register on it without importing THIS module (which would be a cycle).
# Same object, same blueprint name "v2" → endpoint names and the URL map are
# byte-identical to before the split.
from routes.v2.blueprint import v2_bp  # noqa: F401 — app.py + tests import it from here
from routes.v2.common import (  # noqa: F401 — re-exported for import compat
    _COACH_PSEUDONYM_SALT,
    _LAB_MAX_AUDIO_MB,
    _PRESENTATION_MAX_MB,
    _VIDEO_UPLOAD_EXTS,
    _async_analysis_enabled,
    _client_ip_from_request,
    _is_valid_uuid,
    _pipeline_queue_enabled,
    _resolve_snippet_audio_url,
)
from routes.v2.arcs import (  # noqa: F401 — re-exported for import compat
    _arc_audit_paid,
    _arc_owned_by_caller,
    _charge_arc_deliverable,
    _continue_deck_arc,
    _continue_topic_arc,
    _fold_applied_moments,
    _moment_applied_map,
    _moment_explanations_map,
    _moment_playback_map,
    _moment_reference,
    _moment_reference_map,
    _moment_suggestions_enabled,
    _moments_entitled,
    _presentation_id_from_slides,
    _reassemble_after_decision,
    _spoken_takes_and_reads,
    _take_full_text,
    _take_key_moments,
    v2_arc_checkout,
    v2_arc_game,
    v2_arc_game_answer,
    v2_arc_game_save,
    v2_arc_redeem,
    v2_arc_snippet_library,
    v2_arc_unlock,
    v2_explore_arc_best_presentation,
    v2_explore_arc_voice_album,
    v2_explore_arc_breakthroughs,
    v2_explore_arc_edit_slide,
    v2_explore_arc_feedback,
    v2_explore_arc_moments,
    v2_explore_arc_progress,
    v2_explore_arc_setup,
    v2_explore_arc_take_comparison,
    v2_explore_get_context_document,
    v2_explore_start,
    v2_explore_upload_context_document,
    v2_get_moment_explanation,
    v2_unlock_moments,
)
from routes.v2.explore_ideal_text import (  # noqa: F401 — re-exported for import compat
    _block_variants_gate,
    _ideal_parts_block,
    _ideal_piece_provenance,
    _ideal_save_state,
    _ideal_text_pieces,
    _instant_ideal_enabled,
    _locked_parts,
    _previous_spoken_session,
    _tracked_changes_block,
    v2_explore_block_variants,
    v2_explore_decide_block,
    v2_explore_decide_prior_take,
    v2_explore_get_ideal_text,
    v2_explore_ideal_revisions,
    v2_explore_put_ideal_notes,
    v2_explore_put_ideal_user_edit,
    v2_explore_restore_ideal_revision,
    v2_explore_save_ideal_text,
    v2_explore_select_block_variant,
    v2_explore_set_part_lock,
)
from routes.v2.user_chat import (  # noqa: F401 — re-exported for import compat
    _CONTEXTUAL_INTENTS,
    _INTERVIEW_QUESTIONS_FALLBACK,
    _INTERVIEW_SYSTEM_PROMPT,
    _SELF_RATING_RE,
    _SELF_RATING_TEXT_MAX,
    _SELF_RATING_WORD_MAP,
    _augment_interview_prompt_with_profile,
    _best_self_rating,
    _build_few_shot_block,
    _build_longitudinal_context_block,
    _build_master_score_block,
    _first_self_rating,
    _generate_llm_question,
    _parse_self_rating_from_text,
    v2_user_chat_first_question,
    v2_user_coaching_self_rating,
)
from routes.v2.user_account import (  # noqa: F401 — re-exported for import compat
    _CONSENT_FIELDS_FE,
    _PROFILE_GOAL_MAX_LEN,
    _shape_consent_response,
    v2_user_consent,
    v2_user_game_sessions,
    v2_user_get_audits,
    v2_user_get_credits,
    v2_user_get_profile,
    v2_user_get_sharing_consent,
    v2_user_kpi_timeline,
    v2_user_last_setup,
    v2_user_put_sharing_consent,
    v2_user_recording_progress,
    v2_user_set_profile,
)
from routes.v2.lounge import (  # noqa: F401 — re-exported for import compat
    v2_user_lounge_messages_delete,
    v2_user_lounge_messages_get,
    v2_user_lounge_messages_post,
)
from routes.v2.coach import (  # noqa: F401 — re-exported for import compat
    _COACH_PSEUDONYM_ADJ,
    _COACH_PSEUDONYM_ANIMAL,
    _coach_pseudonym,
    _coach_session_state,
    _coach_state_for,
    _coach_state_map,
    _int_or,
    _resolve_audio_refs,
    _save_coach_snippet_lanes,
    _snippet_owner_map,
    v2_coach_annotation_upload,
    v2_coach_approve_ideal_text,
    v2_coach_arc_best_presentation,
    v2_coach_arc_review_state,
    v2_coach_arc_stars,
    v2_coach_archive_training_import,
    v2_coach_audit_data,
    v2_coach_confidence_queue,
    v2_coach_create_audit,
    v2_coach_get_ideal_text,
    v2_coach_get_session,
    v2_coach_list_training_imports,
    v2_coach_publish_analysis,
    v2_coach_put_confidence_label,
    v2_coach_put_ideal_text,
    v2_coach_put_moment_reference,
    v2_coach_put_say_it_stronger,
    v2_coach_put_star_text,
    v2_coach_put_star_verdict,
    v2_coach_queue,
    v2_coach_restore_training_import,
    v2_coach_save_feedback,
    v2_coach_save_snippet,
    v2_coach_session_recut,
    v2_coach_session_video,
    v2_coach_slide_alignment,
    v2_coach_snippet_breakthrough_video,
    v2_coach_student_audit,
    v2_coach_student_audit_send,
    v2_coach_student_detail,
    v2_coach_students,
    v2_coach_training_import,
    v2_coach_training_import_status,
    v2_coach_verify_ideal_text,
)
from routes.v2.admin import (  # noqa: F401 — re-exported for import compat
    _ANNOTATION_ACTIONS,
    _BULK_APPROVE_THRESHOLD,
    _DIRECTIVES_ARC_LENGTH,
    _DIRECTIVES_VALID_POSITIONS,
    _QUESTION_POOL_MAX_TEXT_LEN,
    _QUESTION_POOL_VALID_INTENTS,
    _QUESTION_POOL_VALID_POSITIONS,
    _build_icebreaker_response,
    _obscure_email,
    _pseudonymous_user_id,
    _resolve_turn_audio_url,
    _snippet_end_time,
    _snippet_start_time,
    _validate_directives_rows,
    _validate_question_pool_body,
    v2_admin_coaching_attempt_annotation_create,
    v2_admin_coaching_attempt_annotation_list,
    v2_admin_dad_jokes_health,
    v2_admin_delete_directives_queue,
    v2_admin_delete_user_file,
    v2_admin_funnel_afterwards_video_upload,
    v2_admin_get_directives_queue,
    v2_admin_get_next_session_icebreaker,
    v2_admin_get_session,
    v2_admin_get_session_readout,
    v2_admin_health,
    v2_admin_learning_models,
    v2_admin_learning_status,
    v2_admin_learning_trace,
    v2_admin_learning_train,
    v2_admin_post_directives_queue,
    v2_admin_question_pool_create,
    v2_admin_question_pool_delete,
    v2_admin_question_pool_list,
    v2_admin_question_pool_update,
    v2_admin_regenerate_next_session_icebreaker,
    v2_admin_review_queue,
    v2_admin_suggest_directives_queue,
    v2_admin_update_next_session_icebreaker,
    v2_admin_update_snippet_coaching_rationale,
    v2_public_unsubscribe,
)
from routes.v2.coaching import (  # noqa: F401 — re-exported for import compat
    _COACHING_INTRO_STATIC_FALLBACK,
    _FINALIZE_SIGNUP_CTA_COPY,
    _INTERVIEW_FINALIZE_VALID_REASONS,
    _augment_coaching_system_prompt,
    _build_user_raw_snippet_list,
    _coach_intent_for_snippet,
    _format_duration,
    _generate_snippet_follow_up_question,
    _persist_chat_turn,
    _snippet_to_journey_card,
    _sort_raw_snippets_by_intensity,
    _system_prompt_for_intent,
    v2_chat_query,
    v2_chat_session_state,
    v2_chat_snippet_followup,
    v2_coaching_get,
    v2_coaching_intro_bubble,
    v2_coaching_start,
    v2_coaching_state_machine_turn,
    v2_coaching_turn,
    v2_onboarding_opener_next,
    v2_onboarding_opener_start,
)
from routes.v2.publish import (  # noqa: F401 — re-exported for import compat
    _apply_willab_publish_contract,
    _assemble_insights_from_drafts,
    _assemble_labels_from_store,
    v2_internal_publish_session_results,
    v2_internal_whisper_health,
)
from routes.v2.funnel import (  # noqa: F401 — re-exported for import compat
    _IMPORT_ALLOWED_EXTENSIONS,
    _POST_SIGNUP_CONFIRMATION,
    _admin_import_validate_audio_file,
    _merge_anonymous_session_into_user,
    v2_auth_merge_session,
    v2_auth_signup,
    v2_public_funnel_afterwards_video,
    v2_public_shaky_voice_claim,
    v2_public_shaky_voice_upload,
)
from routes.v2.reflection import (  # noqa: F401 — re-exported for import compat
    _reflection_audio_map,
    v2_coach_reflection_queue,
    v2_coach_reflection_verdict,
    v2_library_confident_voices,
    v2_reflection_get_clips,
    v2_reflection_vote,
)
from routes.v2.lab_recording import (  # noqa: F401 — re-exported for import compat
    _parse_lab_vocabulary,
    _recording_flow_tags,
    v2_config_recording,
    v2_guest_get_recording_readout,
    v2_lab_create_recording,
    v2_lab_presentation_extract,
)
from routes.v2.user_sessions import (  # noqa: F401 — re-exported for import compat
    _SUGGESTION_ACTIONS,
    _SUGGESTION_TARGETS,
    _TRANSCRIPT_EDIT_MAX_LEN,
    _build_user_session_status,
    _derive_session_status,
    _document_phrase_for,
    _hard_delete_session_for_user,
    _metrics_ready,
    _user_presentation_groups,
    _user_presentation_sessions_all,
    v2_session_status,
    v2_user_delete_presentation,
    v2_user_delete_session,
    v2_user_delete_take,
    v2_user_get_library,
    v2_user_get_results,
    v2_user_get_session_intake_context,
    v2_user_get_session_readout,
    v2_user_get_strengths,
    v2_user_list_readouts,
    v2_user_list_trainings,
    v2_user_put_session_intake_context,
    v2_user_put_transcript_edit,
    v2_user_sessions_current,
    v2_user_snippet_confidence_review,
    v2_user_suggestion_feedback,
)


# The guest funnel's two hourly caps (per-IP + global) now live in
# services/rate_limits.py::guest_funnel_limit, decorated onto the upload
# route below. Same caps, same config vars, same 429 copy — but counted in
# the shared Redis instead of an in-process dict, so the real cap is the
# stated cap rather than `stated x gunicorn workers`, and it survives a
# restart.


############################################################################
# Multi-Turn Interview endpoints
############################################################################




# ---------------------------------------------------------------------------
# Cold-start onboarding (turns 1-4) — REMOVED IN PHASE 18.
#
# Per docs/ARCHITECTURE_SINGLE_SOURCE_OF_TRUTH.md, the frontend now
# owns turns 1-4 entirely as hardcoded ONBOARDING_MESSAGES strings.
# The backend's scripted EBCP path (the long _EBCP_BASELINE_SYSTEM_
# PROMPT, the _EBCP_FALLBACKS dict, and _generate_ebcp_question) was
# deleted to eliminate duplicate ownership. /v2/public/interview/
# next-question now refuses turn_number <= 4 with 400 TURN_OWNED_BY_
# FRONTEND so a confused client surfaces the violation immediately
# instead of silently regressing into "backend owns turn 1 again".
# ---------------------------------------------------------------------------


# ─────────────────────────────────────────────────────────────────────
# Coaching loop — micro-coaching session on a single snippet
#
# v1: stress intent only, two technical stages (awareness → trial) with
# the reframe baked into the awareness prompt. The flow:
#
#   /v2/coaching/start
#     POST { snippet_id }
#     → reads charisma_snippets row, validates ownership + admin_comment,
#       creates coaching_sessions row, returns the admin_comment as the
#       awareness "first bubble" so the frontend can render it instantly.
#
#   /v2/coaching/turn
#     POST { coaching_id, user_message }
#     → looks up the active skill via services.skills.get_skill(intent),
#       calls the LLM with that skill's awareness_system_prompt, parses
#       the structured JSON (validation_bubble / challenge_bubble /
#       advance) and advances stage to 'trial' when advance is true.
#
#   /v2/coaching/trial-recording
#     POST multipart audio_file + coaching_id
#     → uploads audio, creates v2_session + recording rows, runs the
#       existing extract_recording_snippets pipeline, marks the
#       coaching_session 'complete' and binds trial_session_id.
# ─────────────────────────────────────────────────────────────────────


# ── Phase 9: admin RLHF + profile override ──────────────────────────────


# ── Directed-freestyle baseline (turns 1-4 for new users) ──────────
# Pivot from Phase 18's "frontend owns turns 1-4 as hardcoded strings"
# back to backend-generated dynamic questions, but with per-turn
# psychological OBJECTIVES so the LLM doesn't drift across the
# onboarding arc. Each turn has a single goal; the LLM builds the
# scenario but must satisfy that goal.
#
# Tone arc for the 4 baseline turns: turns 1-2 are warm (charisma —
# icebreaker + empathy), turns 3-4 are pressure (stress — challenge
# + reflex). After baseline (turn 5+), tone alternates per SSoT §4.


############################################################################
# Admin: AI evaluator rationale review (Phase 14.x — frontend BFF target)
############################################################################


############################################################################
# Admin: Snippet boundary adjustment (the +/- 2s feature)
############################################################################


# ── Task 10 — Next-session icebreaker (admin endpoints) ─────────────
#
# Lives on session N's row; previewed/edited from admin Tab 1
# (Sessions & Analysis). After session N+1's first chat message
# delivers it (via /v2/user/chat/first-question), the row's status
# flips to 'delivered' and the card becomes read-only.
#
# Three endpoints below: GET (poll-safe; FE polls every ~3s while
# queue_status='not_yet_generated' post-finalize), PUT (Save —
# empty save = 'skipped'), POST /regenerate (blows away admin
# edits and re-runs the LLM; rate-limited).
#
# See: services/next_session_icebreaker.py for the generator +
# validator, services/db.py get_next_session_icebreaker_row /
# update_next_session_icebreaker_editable, and
# migrations/add_next_session_icebreaker_columns.sql for the
# column shape.


# The regenerate endpoint's 60s-per-session double-click guard now lives
# in services/rate_limits.py::regenerate_limit (decorated below) — same
# window, same force bypass, but counted in the shared Redis instead of a
# per-worker dict, so a second click landing on a second worker no longer
# buys a second LLM call.


# ── Coaching Directives Queue (Phase Directives-Queue / BE) ───────
#
# User-level 5-step coaching arc. Admin authors a sequence of 5
# questions for one user; the chat / interview surface pops them
# one at a time as the AI question for the next turn, marking
# each exhausted as it fires. When the queue is empty, those
# surfaces fall back to _generate_llm_question.
#
# Replaces the per-user single-question
# user_settings.queued_override_question (removed in Week-1
# cleanup) and the conceptually-misplaced snippet-level
# next_question_1..5 columns (which never shipped to this branch).
#
# Audit: every write logs an INFO line with structured fields
# (user, admin, op, row count). We do NOT route to
# admin_annotations_log — that table's schema captures the RLHF
# (predicted, final) training pair, not admin config changes. The
# application log is the audit trail of record for this surface.


# ── Public interview funnel: end-of-session signal ────────────────
#
# The frontend BFF at /api/session/finalize forwards here when the
# guest interview funnel ends. Three legitimate reasons today:
#   • threshold  — cold-start 30s aggregate audio threshold reached
#   • max_turns  — legacy fallback when the turn cap fires
#   • user_done  — user clicked "Finish & see results"
#
# Historical note: this endpoint did not exist in this repo. The FE
# BFF was built against it on the assumption that the backend
# wanted an explicit end-of-funnel signal. Without it the FE was
# logging a 404 on every session close. We're shipping the stub now
# so the FE stays clean; the actual end-of-funnel bookkeeping
# happens elsewhere (via upload-answer + the results-publish flow),
# so this handler is intentionally minimal:
#
#   - validates inputs
#   - emits a structured log line so funnel-completion analytics
#     can grep on `funnel.end sid=... reason=...`
#   - returns 200 — the FE treats failure as non-fatal anyway, so
#     200 just keeps the console quiet
#
# When analytics actually wants this data persisted (per-row in
# Postgres, or piped to a warehouse), extend this handler to write
# to v2_sessions or a dedicated `funnel_events` table. For now,
# log-line analytics is enough.


# ── Coaching intro bubble (Phase Single-Slot-Chat) ────────────────
#
# Frontend contract: after the user labels a snippet (Yes/No) and
# reads the follow-up question, the chat transitions into a new
# official recording session. The intro bubble for that new
# session should feel continuous with what the user just labeled
# — referencing the coach's insight, inviting them to record
# now.
#
# 1–2 sentences, ≤180 chars target, generated by gpt-4o-mini
# grounded in the just-labeled snippet. Falls back to a static
# line when the LLM is unavailable or the snippet lacks
# admin_comment.
#
# Endpoint is owner-scoped: foreign snippet → 404, not 403
# (avoids existence leak — same pattern as snippet-followup).


# ── tester-soft-v1 — KPI timeline + question pool admin CRUD ─────────
#
# M1.1 (raw mode): GET /v2/user/kpi/timeline — per-session KPI
#                  scores in chronological order with a summary card.
#                  No smoothing yet; FE can render a chart now, the
#                  `smoothed_kpi` field will be additive when it lands.
#
# M1.3 schema-only: GET / POST / PATCH / DELETE for chat_question_pool
#                   admin curation. Empty pool = legacy question logic
#                   so this changes nothing until content seeds.


# ── willab beta — Lab readout re-read + history (parked-restore + scroll-back) ─


# ── willab beta — coach review flow (design §14, contract §3.8) ──────
#
# Two admin/coach endpoints. The split-sink wall (§2) is the rule: the
# USER re-read (/v2/user/sessions/<id>/readout) OMITS the private
# direction label; the COACH readout below INCLUDES it (the coach
# authors/corrects it). Identity is pseudonymized, never the real
# user_id (§14 red-line 6) — list = low-identifiability; detail =
# pseudonymized-not-anonymized (full transcript + goal, opaque identity).


# ── willab Phase 4 / Prompt 1 — Learning subsystem (SHADOW) admin surface ──
# The model trains on training_labels ⋈ the 11 features and predicts in SHADOW
# only — it influences NOTHING (no selection, no direction pre-fill). These
# endpoints are the human's window + manual "train now"; auto-retrain (B3) runs
# off the label/publish hook. All @require_admin_or_coach.


# ── FIX.3 — Dad jokes health probe (deploy verification) ────────────


# ── Ticket 2 — Dad-joke onboarding opener ────────────────────────────
#
# Three-bubble flow on a new user's first onboarding contact:
#   1. /onboarding/opener/start  → returns {stage: 'setup', frame, setup, joke_id}
#   2. /onboarding/opener/next   → body {joke_id, user_reply}
#                                  returns {stage: 'punchline', ack, punchline}
#   3. /onboarding/opener/next   → body {joke_id, user_reply, after_punchline: true}
#                                  returns {stage: 'pivot', pivot_line, done: true}
#
# Auth: @optional_auth — GUEST-ALLOWED (founder 2026-07-14 regression fix).
# The round-4 flow moved onboarding SIGNED-OUT-FIRST (record before signup),
# so a guest hitting the old @require_auth opener got 401 → no joke → "it
# can't." The opener reads NO user data (it just picks a random joke and
# echoes the reply), so anonymous is safe: request.user_id is simply None.
#
# Canonical PIVOT_LINE lives in services/onboarding_opener.py and
# is never LLM-generated. The LLM only produces the optional ack
# line that bridges user reply → punchline.


# ═══════════════════════ Reflection Game (F2 handoff §1, 2026-08-03) ══
# The shadow detector's "possibly confident" moments, asked back to the
# user as a QUESTION, coach-verified BLIND, landing (verified only) in
# the cross-project Confident Voices library. Founder-locked fences:
#   * NO DECOY LEAK — the user payload is an explicit allowlist; decoy
#     identity (machine_flagged) and any model confidence never ride.
#   * BLIND COACH — the coach payload is audio + transcript only: no
#     machine flag, no user vote, pre-verdict.
#   * AC-9 — no counts/streaks/scores on any surface. A list is a list.
#   * Cadence ≤2 fresh clips per user per UTC day, server-enforced.
# Approved copy (question / two options / interstitial) is FE-side and
# verbatim-locked; nothing textual is served from here (LIVE LOOP).
