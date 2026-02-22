# Context fields: where they live and who uses them

| Field | Table / location | Written by | Read by | Purpose |
|-------|------------------|-------------|---------|---------|
| **context_short** | `v2_sessions` | recording_1_job (after first recording transcription) | POST metric-answers (final task generation), report generation | Short summary of first recording; used for focus task and report context |
| **context_long** | `v2_sessions` | POST post-answers (final report text) | Admin (GET session detail), report UI; exposed as **report_text** in API | Final report text for step 5 |
| **coach_notes** | `v2_speaker_profiles` (or speaker profile) | Admin via PUT speaker-profile | `get_user_admin_context` → report generation | Admin-only coach notes; not shown to students in homework flow |

**API surface:** Students see report text as `report_text` in POST post-answers and GET report; that value is stored in `context_long` and optionally mirrored in `v2_reports.report_text`.
