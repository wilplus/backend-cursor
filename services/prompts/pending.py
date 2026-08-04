"""Pending-extraction tier — every inline prompt NOT yet physically
moved into this package, drift-tracked in place by source-segment hash.

The 2026-08-03 inventory found ~118 prompt strings across 30 files.
Physically extracting all of them in one change would be a mega-refactor
of the live loop; instead, each entry here pins the prompt's CURRENT
source (constant assignment or enclosing function) into
prompts.lock.json via ``SourceRef``. Editing any of these prompts —
or the interpolation glue around them — flips its hash and fails the
drift gate exactly like an extracted prompt.

Granularity honesty: a ``SourceRef`` to a function hashes the WHOLE
function, so a non-prompt edit inside it also flags as prompt drift.
That is deliberate and conservative for a pending entry — the fix is
to physically extract that surface into its own module here (see
say_it_stronger.py for the pattern), which shrinks the hash back down
to the prompt text itself. Extract opportunistically, one surface per
PR, verbatim, with the pre/post capture proof.

When you extract a surface: delete its entries HERE, add its module
with ``REGISTER`` there, and regenerate the lockfile — the eval map in
tests/evals keys on the same surface prefix either way.
"""
from __future__ import annotations

from services.prompts.registry import SourceRef

_MDR = "services/master_doc_rag.py"
_OAI = "services/openai_service.py"
_V2 = "routes/v2_routes.py"
_LIFE = "services/life_engine.py"

REGISTER = {
    # ── master_doc_rag — the Lounge chat mega-prompt (probe-guarded) ──
    "master_doc_rag.master_document": SourceRef(_MDR, "MASTER_DOCUMENT"),
    "master_doc_rag.system": SourceRef(_MDR, "_SYSTEM_PROMPT"),
    "master_doc_rag.librarian_guardrail": SourceRef(_MDR, "_LIBRARIAN_GUARDRAIL"),
    "master_doc_rag.life_guardrail": SourceRef(_MDR, "_LIFE_GUARDRAIL"),
    "master_doc_rag.library_block": SourceRef(_MDR, "_render_library_block"),
    "master_doc_rag.life_block": SourceRef(_MDR, "_render_life_block"),
    "master_doc_rag.anchor_metrics": SourceRef(_MDR, "_fmt_anchor_metrics"),
    "master_doc_rag.two_anchors": SourceRef(_MDR, "_render_two_anchors"),
    "master_doc_rag_router.classifier": SourceRef(_MDR, "_CLASSIFIER_SYSTEM"),
    "master_doc_rag_lane.base": SourceRef(_MDR, "_LANE_BASE"),
    "master_doc_rag_lane.bodies": SourceRef(_MDR, "_LANE_BODIES"),
    "master_doc_rag_lane.builder": SourceRef(_MDR, "_build_lane_prompt"),

    # ── legacy OpenAIService hub (pre-llm.py; 14 prompt-bearing methods) ──
    "legacy_openai.whisper_priming": SourceRef(_OAI, "OpenAIService.transcribe_audio"),
    "legacy_openai.classify_speech": SourceRef(_OAI, "OpenAIService.classify_speech"),
    "legacy_openai.final_report": SourceRef(_OAI, "OpenAIService.generate_final_report"),
    "legacy_openai.context_short": SourceRef(_OAI, "OpenAIService.generate_context_short"),
    "legacy_openai.coach_insight": SourceRef(_OAI, "OpenAIService.generate_coach_insight"),
    "legacy_openai.final_task": SourceRef(_OAI, "OpenAIService.generate_final_task"),
    "legacy_openai.custom_questions": SourceRef(_OAI, "OpenAIService.analyze_custom_questions"),
    "legacy_openai.suggested_questions": SourceRef(_OAI, "OpenAIService.generate_suggested_questions"),
    "legacy_openai.ai_task_score": SourceRef(_OAI, "OpenAIService.generate_ai_task_score"),
    "legacy_openai.coach_suggestions": SourceRef(_OAI, "OpenAIService.generate_coach_suggestions"),
    "legacy_openai.admin_grade_comment": SourceRef(_OAI, "OpenAIService.generate_admin_grade_comment_draft"),
    "legacy_openai.student_email": SourceRef(_OAI, "OpenAIService.generate_student_email_draft"),
    "legacy_openai.next_task": SourceRef(_OAI, "OpenAIService.generate_next_task_suggestion"),
    "legacy_openai.video_script": SourceRef(_OAI, "OpenAIService.generate_video_script_draft"),

    # ── interview / coaching chat (routes/v2_routes.py) ──
    "interview.system": SourceRef(_V2, "_INTERVIEW_SYSTEM_PROMPT"),
    "interview.snippet_followup": SourceRef(_V2, "_generate_snippet_follow_up_question"),
    "interview.llm_question": SourceRef(_V2, "_generate_llm_question"),
    "interview.few_shot_block": SourceRef(_V2, "_build_few_shot_block"),
    "interview.longitudinal_block": SourceRef(_V2, "_build_longitudinal_context_block"),
    "interview.master_score_block": SourceRef(_V2, "_build_master_score_block"),
    "interview.profile_augment": SourceRef(_V2, "_augment_interview_prompt_with_profile"),
    "coaching.intent_system": SourceRef(_V2, "_system_prompt_for_intent"),
    "coaching.profile_augment": SourceRef(_V2, "_augment_coaching_system_prompt"),
    "coaching.turn": SourceRef(_V2, "v2_coaching_turn"),
    "chat.snippet_followup": SourceRef(_V2, "v2_chat_snippet_followup"),

    # ── 9-step structured coaching chat ──
    "coaching_state_machine.system": SourceRef(
        "services/coaching_state_machine.py", "build_state_machine_system_prompt"),
    "coaching_state_machine.acoustic_targets": SourceRef(
        "services/coaching_state_machine.py", "_format_acoustic_targets_for_prompt"),

    # ── skills (F2 awareness turns) ──
    "skill_charisma.awareness": SourceRef("services/skills/charisma.py", "_AWARENESS_PROMPT"),
    "skill_stress.awareness": SourceRef("services/skills/stress.py", "_AWARENESS_PROMPT"),

    # ── Life Panel engine ──
    "life_case.system": SourceRef(_LIFE, "_CASE_SYSTEM"),
    "life_wins.system": SourceRef(_LIFE, "_WINS_SYSTEM"),
    "life_diff.system": SourceRef(_LIFE, "_DIFF_SYSTEM"),
    "life_docs.system": SourceRef(_LIFE, "_DOCS_SYSTEM"),
    "life_doc_draft.system": SourceRef(_LIFE, "_DOC_DRAFT_SYSTEM"),
    "life_doc_draft_kind.system": SourceRef(_LIFE, "_DOC_DRAFT_LINES_SYSTEM"),
    "life_board.system": SourceRef(_LIFE, "_BOARD_SYSTEM"),
    "life_board.advisors": SourceRef("services/life_panel.py", "ADVISORS"),
    "life_goal_rank.system": SourceRef(_LIFE, "_GOAL_RANK_SYSTEM"),
    "life_day_draft.system": SourceRef(_LIFE, "_DAY_DRAFT_SYSTEM"),

    # ── Will voice rules (spliced into 13+ system prompts) ──
    "will_voice.off_brand": SourceRef("services/will_voice.py", "OFF_BRAND_EXAMPLES"),
    "will_voice.on_brand": SourceRef("services/will_voice.py", "ON_BRAND_EXAMPLES"),
    "will_voice.rules": SourceRef("services/will_voice.py", "WILL_VOICE_RULES"),
    "will_voice.wrapper": SourceRef("services/will_voice.py", "with_voice_rules"),

    # ── single-surface services still inline ──
    "session_cadence.render_beat": SourceRef("services/session_cadence.py", "_render_beat"),
    "session_cadence.beats": SourceRef("services/session_cadence.py", "BEATS"),
    "stickiness_topics.builder": SourceRef("services/stickiness.py", "_extract_topics_via_llm"),
    "stickiness_topics.user": SourceRef("services/stickiness.py", "_build_user_prompt"),
    "conversation_summary.builder": SourceRef("services/conversation_summary.py", "_llm_fold"),
    "conversation_summary.context_block": SourceRef(
        "services/conversation_summary.py", "format_summary_for_prompt"),
    "goal_update.builder": SourceRef("services/goal_update.py", "_classify_goal_update"),
    "audit_pointer.builder": SourceRef("services/audit_intent.py", "_render_pointer"),
    "next_session_icebreaker.builder": SourceRef(
        "services/next_session_icebreaker.py", "_llm_generate_question"),
    "next_session_icebreaker.user": SourceRef(
        "services/next_session_icebreaker.py", "_build_user_prompt"),
    "coaching_intro.builder": SourceRef("services/coaching_intro.py", "generate_intro_line"),
    "onboarding_opener.builder": SourceRef(
        "services/onboarding_opener.py", "generate_punchline_ack"),
    "baseline_summary.system": SourceRef("services/baseline_summary.py", "_build_system_prompt"),
    "baseline_summary.user": SourceRef("services/baseline_summary.py", "_build_user_prompt"),
    "baseline_summary.context_block": SourceRef(
        "services/baseline_summary.py", "format_baseline_for_prompt"),
    "directive_suggestions.builder": SourceRef(
        "services/directive_suggestions.py", "suggest_directive_arc"),
    "directive_suggestions.recent_snippets": SourceRef(
        "services/directive_suggestions.py", "_recent_snippets_section"),
    "directive_suggestions.profile_section": SourceRef(
        "services/directive_suggestions.py", "_profile_section"),
    "directive_suggestions.charisma_profile": SourceRef(
        "services/directive_suggestions.py", "_recent_charisma_profile"),
    "community_content.preamble": SourceRef("services/community_content.py", "_PREAMBLE"),
    "community_content.system": SourceRef("services/community_content.py", "build_system_prompt"),
    "community_content.user": SourceRef("services/community_content.py", "build_user_prompt"),
    "community_content.strategy_md": SourceRef(
        "services/prompts/community_content_strategy.md"),
    "journal_image_brief.system": SourceRef("services/journal_image.py", "_BRIEF_SYSTEM"),
    "journal_image_brief.style": SourceRef("services/journal_image.py", "_DEFAULT_STYLE"),
    "journal_image_brief.user": SourceRef("services/journal_image.py", "build_brief_user"),
    "journal_image_brief.fallback": SourceRef("services/journal_image.py", "fallback_brief"),
    "snippet_drafts.charisma_system": SourceRef(
        "services/snippet_drafts.py", "_charisma_system_prompt"),
    "snippet_drafts.stress_system": SourceRef(
        "services/snippet_drafts.py", "_stress_system_prompt"),
    "snippet_drafts.charisma_user": SourceRef(
        "services/snippet_drafts.py", "_charisma_user_prompt"),
    "snippet_drafts.stress_user": SourceRef(
        "services/snippet_drafts.py", "_stress_user_prompt"),
    "dev_tasks.reference": SourceRef("services/dev_tasks.py", "_REFERENCE"),
    "dev_tasks.system": SourceRef("services/dev_tasks.py", "_SYSTEM"),
    "dev_tasks.reeval": SourceRef("services/dev_tasks.py", "_REEVAL_SYSTEM"),
    "whisper_snippet.priming": SourceRef(
        "services/snippet_transcription.py", "_DISFLUENT_PROMPT"),
    "shared_blocks.admin_dont_ask": SourceRef(
        "services/utils.py", "render_admin_dont_ask_block"),

    # ── prompt-shaped text that never hits a live API but drives models
    #    downstream (fine-tuning export, backlog email for coding agents,
    #    schema descriptions that reach the model via response_format) ──
    "ml_finetuning.default_system": SourceRef(
        "services/ml_finetuning_export.py", "_DEFAULT_SYSTEM"),
    "ml_finetuning.field_prompts": SourceRef(
        "services/ml_finetuning_export.py", "_FIELD_SYSTEM_PROMPTS"),
    "dev_bugs.context": SourceRef("services/dev_bugs.py", "_CTX"),
    "llm_schemas.all": SourceRef("services/llm_schemas.py"),
}
