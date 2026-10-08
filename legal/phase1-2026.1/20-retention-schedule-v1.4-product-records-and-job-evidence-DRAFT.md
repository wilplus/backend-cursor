# Retention schedule v1.4 — product records and job evidence (for the founder's signature)

    artifact_kind:       retention_schedule
    version:             1.4 — supersedes 1.3 (signed 2026-10-05); never edited in place, see 04 §5
    approving_authority: Artur Willoński (founder and controller)
    approved_at:         2026-10-05 (the day the controller decided the rule; the document records a date, not a time)
    object_key:          phase1-2026.1/legal/retention-schedule-v1.4.pdf
    sha256:              [[computed from the signed PDF at registration time]]
    control_version:     phase1-retention-schedule-v1.4
    author:              Artur Willoński, founder and controller; not reviewed by outside counsel

**STATUS: DRAFT, for the controller's signature, and for counsel to read.**
The controller decided the rule on 5 October 2026 (decisions log N48.4, Q15
A): **product records** (what the service showed, the speaker's own answers,
every version of a paragraph, and any other record of the speaker's own use
of the service) are deleted with the account or with the project; **job
evidence** (processing job events and similar operational evidence) is kept
12 months and then deleted. v1.4 is **v1.3 unchanged, plus the two rows
below, plus a decision for every table the deletion process still left for a
person to resolve.** Every period, rule and open point in
`06-retention-schedule-v1.0-DRAFT.md`, in v1.1's two rows (`11-…`), in v1.2's
three rows (`18-…`) and in v1.3's row (`19-…`) carries over word for word.

**Why now.** The deletion process (the purge) inventories everything a person
owns before it deletes anything, and it stops for a person whenever it finds
a row in a table nobody has decided: the registry marks such a table
`external_review` (`services/data_purge_registry.py`). On 5 October 2026, 196
of the registry's entries were marked so. Four of them are written by every
Take that gets feedback (`take_feedback_exposure`, `take_feedback_self_report`,
`ideal_text_part_revision`, `phase1_processing_job_events`; decisions log N14),
so no real account or project deletion could finish by itself. The 5 October
audit named three more that stop an account deletion: an arc purchase, a coach
AI conversation and Life Panel consent.

**What this document decides.** §2 seeds the two rules and lists, by registry
code, the 50 entries they govern: the deletion acts on them by itself once
the rules are seeded. §3 lists 5 more product records that the rule decides
but the deletion reaches only after one read-only check. §5 sets out, as
proposals for the founder, the 142 entries that fit neither rule or need a
mechanism the founder has not chosen; this signature does not adopt them.

---

## 1. Additions to the published schedule (v1.0 §1, after v1.3 §1)

| Category | Period | Trigger |
|---|---|---|
| What the service showed you, your answers to it, every version of your paragraphs, and every other record of how you used the service | until you delete the project it belongs to, or your account; then deleted | deletion of the project or of the account |
| Records of how each of your recordings was processed: when processing ran, and whether it succeeded | 12 months from the day each was recorded, including after you delete your account; then deleted | the day it was recorded |

The first row restates for these records what v1.0 §1 already says of
transcripts, the Ideal Text and feedback ("until account deletion"), and adds
the project: deleting a project deletes its records. Records kept as evidence
(v1.0 §2, v1.1, v1.2) and financial records (v1.3) keep their own periods.
So do v1.0 §1's shorter ones: a record one of them also covers (audio and
voice measurements, 12 months after last use; security and technical logs,
90 days) goes when that period ends, or with the project or the account if
that comes first.

The second row is new. These records outlive a deletion for up to 12 months.
They hold identifiers, times, states and technical error codes; never your
words and never your voice.

## 2. Additions to the rules to seed (v1.0 §2, after v1.3 §2)

| `rule_code` | `evidence_category` | `retention_until_rule` | What it covers |
|---|---|---|---|
| `product-records-v1` | `product_records` | `deleted_with_account_or_project` | Table A: disposition `delete`, `ruled_by` this rule in `services/data_purge_registry.py` |
| `job-evidence-v1` | `job_evidence` | `recorded_plus_12_months` | Table B: disposition `retain`, `ruled_by` this rule |

**How the two rows act.** Each entry in tables A and B names its rule in the
registry. Until a row with that `rule_code`, in that category, is active in
`data_retention_rules`, the entry does exactly what it did before v1.4: a
matching row stops the deletion for a person, and nothing is deleted. Once the
rule is active, the deletion acts on the entry by itself: a product record is
deleted, and job evidence is kept under its rule. A row of another code, even
in the same category, opens nothing. The rules are seeded active by the
script in §4, after this document is signed.

**The append-only records.** Three tables in table A refuse every change by
design (`take_feedback_exposure`, `take_feedback_self_report`,
`ideal_text_part_revision`). Their guard lets exactly one deletion through:
one made by a running deletion whose sealed inventory names those rows, under
an active `product-records-v1`. Nothing else can delete them, before or after
this signature.

### Table A — product records, deleted with the account or the project (`product-records-v1`)

| What it is | Registry entries | Deleted with | Why it is a product record |
|---|---|---|---|
| What a Take showed and the speaker's answers to it | `feedback_exposure` (`take_feedback_exposure`), `feedback_self_report` (`take_feedback_self_report`) | the Take: the project or the account | what was shown; the speaker's own answers (the rule's own words) |
| Every version of a paragraph | `ideal_part_revision` (`ideal_text_part_revision`) | the project or the account | paragraph revisions (the rule's own words) |
| The speaker's own conversations and requests | `coach_ai_review` (`coach_ai_conversations`), `coaching_directives_review` (`coaching_directives_queue`) | the account | the speaker's own use of the coach AI |
| The Life Panel | `life_consent_review`, `life_setup_review`, `life_notes_review`, `life_cases_review`, `life_items_review`, `life_strategy_review`, `life_proposals_review`, `life_applications_review`, `life_days_review`, `life_weeks_review`, `life_period_reviews_review`, `life_setup_documents_review`, `life_push_subscriptions_review`, `life_reminder_settings_review`, `life_reminder_log_review`, `life_user_copy_review` | the account, in the Life Panel's own order (consent last) | the person's own use of the Life Panel, which its own delete already erases whole |
| What earlier versions of the product showed or asked | `content_exposure_review` (`content_exposures`), `session_commands_review` (`session_command_options`), `v2_reports_review` (`v2_reports`), `arc_deliveries_review` (`arc_batch_deliveries`), `intervention_arm_review` (`intervention_arms`), `student_post_questions_review` (`v2_student_post_recording_questions`) | the account; a Take's or a project's rows also with it | what was shown, delivered or asked |
| The speaker's own choices and state in earlier versions | `intervention_decisions_review` (`intervention_decisions`), `moment_unlocks_review` (`moment_unlocks`), `student_profile_review` (`student_profile`), `student_memory_review` (`v2_student_coaching_memory`), `student_overrides_review` (`v2_student_overrides`) | the account; a project's rows also with it | the speaker's own answers and the state of their own use. The tokens an unlock costs are in the token ledger, kept under v1.3; an unlock paid in credits before 12 August 2026 records the credits on its own row, and that number goes with the row |
| A coach's or an operator's work on the speaker's sessions | `admin_session_override_review` (`admin_session_overrides`), `admin_archive_review` (`admin_copilot_queue_archives`), `admin_student_draft_review` (`admin_student_send_drafts`), `admin_annotation_review` (`admin_annotation_events`), `admin_annotation_log_review` (`admin_annotations_log`), `confidence_rereview` (`confidence_rereview_queue`) | the account | made about the speaker's own sessions, as the coach's drafts and revisions already are (registry `coach_drafts`, `coach_revisions`) |
| Judgements and measurements of the speaker's own recordings | `confidence_labels_review` (`confidence_labels`), `label_revision_review` (`label_revision`), `dimension_evaluation_review` (`dimension_evaluations`) | the recording: the project or the account | a judgement about a recording goes with it, as v1.2 decided for the coach's blind check; a measurement never outlives its source (v1.0 §1) |

### Table B — job evidence, kept 12 months (`job-evidence-v1`)

| What it is | Registry entries | Why it is job evidence |
|---|---|---|
| Each processing run of a recording, and the job it belongs to | `phase1_job_events` (`phase1_processing_job_events`), `phase1_jobs` (`phase1_processing_jobs`) | the rule's own words. The job row is kept with its events, for the same period, because each event points at its job and the database refuses to delete a job an event still names. Before v1.4 the registry listed the job row for deletion with the account; after it, it is kept with its events |
| An upload job's progress | `copilot_upload_jobs_review` (`copilot_reference_upload_jobs`) | operational evidence of a processing step |
| Which examples served one of the speaker's requests | `few_shot_review` (`few_shot_retrievals`) | operational evidence of how a piece of feedback was made |
| The delivery jobs of the coaching bundles, their events and claims | `feedback_language_delivery_materialization_jobs`, `feedback_language_delivery_job_events`, `feedback_language_delivery_job_claim_attempts`, `feedback_language_delivery_job_claim_heads`, `feedback_language_delivery_job_due_heads` | processing job evidence; the bundle records they deliver are in §5 |

Kept job evidence is only counted by the deletion, never touched.

## 3. Product records the deletion reaches after one check

| Registry entries | Why the deletion waits |
|---|---|
| `v1_sessions_review` (`recording_sessions`), `pre_answers_review` (`pre_recording_answers`), `post_answers_review` (`post_recording_answers`), `student_tasks_review` (`tasks`), `performance_scores_review` (`performance_scores`) | Product records by the rule (the speaker's own sessions, answers, tasks and scores of their own recordings). No migration in this repository creates these five tables, so their production shape (columns, links, guards) cannot be read here, and the deletion deletes nothing whose shape it cannot show. One read-only query of production settles it, then one reviewed change switches them to `product-records-v1`. Until then a row there still stops the deletion for a person. |

## 4. How the rows reach the database

`scripts/phase1_retention_rules_v1_4.sql`, run by hand once: it registers this
document under `(retention_schedule, 1.4)` by the signed PDF's `object_key`
and `sha256` (both read from `SIGNED-ARTIFACTS.md` after the upload), then
inserts the two rows, active, with `ON CONFLICT (rule_code) DO NOTHING`. It
refuses to run while the hash placeholder is still in the file. Nothing in it
is a migration. The change to the deletion process that reads these rules can
be deployed before or after the script runs: neither acts without the other.

## 5. For the founder — proposals NOT adopted by this signature

Each entry below fits neither rule as written, or needs a mechanism only the
founder can choose. Each carries a proposal and a one-line reason. Until the
founder answers and a later version (v1.5) carries the answer, a row in any of
them still stops a deletion for a person, exactly as today.

**5.1 Live records the database lets only its own functions change
(for the founder).** `learning_surface_presentations`,
`learning_surface_exposure_receipts`, `ideal_text_user_edit_cas_operations`,
`confident_moment_text_update_capabilities`, `feedback_v3_memberships`,
`feedback_v3_membership_items`, `feedback_v3_owner_responses`,
`feedback_v3_service_render_receipts`, `feedback_v3_service_response_bindings`.
*Proposal:* product records, deleted with the account or the project. *Reason
it is for the founder:* they are what the service showed, the speaker's own
answers and their own edits, so the rule decides them; but they are
append-only and only database functions may write them (0389, and the
migrations that made each table), so a deletion needs a database function
that removes rows, and the migration runner refuses to apply such a file
unless a person applies it by hand (`scripts/migrate.py --allow-destructive`).
The alternative is an empty receipt (the words erased, the bare row kept), as
decided for the Take's own record on 26 September (N12). **These rows are
written on the live path (the Ideal Text page, the V3 feedback and the
speaker's own edits), so until one of the two lands, the deletion of a
signed-in speaker who has opened the Ideal Text or answered a V3 moment still
stops here for a person.**

**5.2 An arc purchase (for the founder).** `arc_purchases_review`
(`arc_purchases`). Since 5 October 2026 nothing sells an arc (decisions log
N49: no arc was ever bought through Stripe); the one path that still writes
this table is the founding pass, redeemed with a free invite code, which
records no payment. *Proposal:* a founding pass is a product record, deleted
with the account; a row that records a payment (an arc unlocked with credits,
offered in July 2026) is a financial record, kept five years under v1.3's
`financial-evidence-v1`, like the token ledger. *Reason:* what was paid for is
v1.3's category, a free pass is a record of the speaker's own use, and the
deletion needs one small change to tell the two apart.

**5.3 A training-choice snapshot (for the founder).** `ml_consent_snapshots`.
*Proposal:* consent evidence, kept six years under v1.2's
`consent-evidence-v1`, as `ml_consent_events` already is. *Reason:* v1.2 §2
already names this table; only the registry was never moved.

**5.4 A reference video made for the speaker (for the founder).**
`admin_uploaded_reference_review` (`admin_uploaded_reference_videos`).
*Proposal:* deleted with the account, unless it has been made library content
(`is_universal`), in which case the speaker's link is cleared and the video
stays. *Reason:* library content is not the speaker's record, and the video
file has no storage target in the deletion yet.

**5.5 The retired corpora (for the founder).** `legacy_snippets_table_review`
(`charisma_snippets`), `retired_stress_corpus` (`stress_snippets`),
`legacy_acoustic_labels`, `legacy_recording_review_annotations`,
`legacy_recording_reviews`, `legacy_reflection_clips`,
`legacy_shadow_predictions`, `legacy_snippet_labels`, `legacy_strong_sides`,
`legacy_training_labels`. *Proposal:* the person's own rows deleted with the
account. *Reason:* these are frozen corpora of retired constructs; the
standing rule is that their clean-up is a separately authorized, previewed
operation, and some hold rows from more than one producer, so each needs its
own reviewed resolver.

**5.6 Training and model lineage, and the switched-off coaching paths (for
the founder).** *Proposal:* deleted with the account: they describe the
speaker's own recordings and use, and no model has been trained on them
(doors 3 and 4 are shut); a reviewer's or an author's own rows go with that
person's account, as v1.2 decided for the coach's blind check. *Reason:* they
are append-only and written only by database functions, the mechanism
question of 5.1; and the product-legal flow asks that a deletion invalidate
such lineage and quarantine any model trained on it
(`docs/PRODUCT-LEGAL-FLOW-PLF-1.1.md`, termination), which nothing does yet. Most sit behind
switches that are off; one read-only count per table shows which hold rows.

- MLC-2 learning lineage: `ml_speaker_binding`, `ml_purge`,
  `ml_canonical_events`, `ml_object_artifacts`, `ml_evidence_spans`,
  `ml_product_actions`, `ml_candidate_sets`, `ml_confidence_producer_receipts`.
- Dataset lineage: `canonical_split_assignments`, `canonical_release_items`,
  `canonical_dataset_exclusions`.
- V3 evaluation frames (written for the founder's own Takes only, in dark
  mode): `v3_shadow`, `v3_detector_reconciliation`.
- MLC-3 exercise and practice lineage: `exercise_authorization_checks`,
  `exercise_learning_profiles`, `exercise_audio_lineages`,
  `exercise_blind_packets`, `exercise_blind_packet_events`,
  `exercise_profile_observations`, `exercise_feature_snapshots`,
  `exercise_candidate_sets`, `exercise_candidates`, `exercise_assignments`,
  `exercise_randomization`, `exercise_requests`,
  `exercise_n1_source_patterns`, `exercise_n1_pattern_snapshots`,
  `exercise_n1_pattern_candidates`, `exercise_practice_sessions`,
  `exercise_practice_upload_recoveries`, `exercise_practice_attempts`,
  `exercise_practice_measurements`, `exercise_practice_validity`,
  `exercise_practice_selections`, `exercise_practice_events`,
  `exercise_service_offers`, `exercise_service_offer_candidates`,
  `exercise_service_offer_events`, `exercise_pair_revisions`,
  `exercise_pair_assignments`, `exercise_pair_assignment_reviewers`,
  `exercise_pair_judgments`, `exercise_pair_judgment_reviewers`,
  `exercise_reviewer_context`, `exercise_service_requests`,
  `exercise_authoring_drafts`, `exercise_authoring_draft_authors`,
  `exercise_service_acquisition_receipts`,
  `exercise_practice_transcription_runs`,
  `exercise_service_confidence_assignments`,
  `exercise_service_confidence_assignment_reviewers`,
  `exercise_service_confidence_render_receipts`,
  `exercise_service_confidence_render_reviewers`,
  `exercise_service_confidence_judgments`,
  `exercise_service_confidence_judgment_reviewers`,
  `exercise_service_blind_review_sets`,
  `exercise_service_blind_review_set_reviewers`,
  `exercise_service_blind_reveal_grants`,
  `exercise_service_blind_reveal_grant_reviewers`,
  `exercise_service_blind_reveal_accesses`,
  `exercise_service_blind_reveal_access_reviewers`.
- MLC-3 service enrollment and speaker binding (the service loop retired on
  30 September): `mlc3_service_principal_allowlist_subjects`,
  `mlc3_service_principal_allowlist_approvers`, `mlc3_service_cohort_members`,
  `mlc3_service_enrollment_revisions`, `mlc3_service_access_events`,
  `mlc3_speaker_acquisition_revisions`, `mlc3_self_speaker_assertions`,
  `mlc3_target_speaker_bindings`,
  `mlc3_comparison_speaker_eligibility_revisions`.
- Confident Moment coaching bundles (switched off): 
  `confident_moment_bundle_attachments`,
  `confident_moment_owner_decision_bindings`, `root_phrase_coverage_frames`,
  `root_phrase_coverage_items`, `feedback_language_revision_deliveries`,
  `feedback_language_delivery_recipients`,
  `feedback_language_delivery_reviewers`, `feedback_revision_subjects`,
  `feedback_revision_reviewers`, `confident_moment_bundle_projections`,
  `confident_moment_bundle_projection_items`,
  `confident_moment_bundle_text_update_bindings`,
  `confident_moment_coach_authorability_inventories`,
  `confident_moment_coach_authorability_items`,
  `confident_moment_blind_assignment_bindings`,
  `confident_moment_coach_wording_subjects`,
  `confident_moment_coach_wording_reviewers`.
- Rooting-phrase qualification (non-serving): `root_phrase_content_versions`,
  `root_phrase_semantic_input_snapshots`, `root_phrase_semantic_results`,
  `root_phrase_owner_alignment_actions`,
  `root_phrase_qualification_revisions`, `root_phrase_product_actions`,
  `root_phrase_block_heads`.
- Coach guidance delivery (D3): `coach_guidance_review_frames`,
  `coach_guidance_review_frame_items`, `coach_guidance_review_batches`,
  `coach_guidance_reveal_grants`, `coach_guidance_reveal_grant_judgments`,
  `coach_guidance_reveal_accesses`, `coach_guidance_media_bindings`,
  `coach_guidance_upload_permits`, `coach_guidance_upload_recoveries`,
  `coach_guidance_upload_events`, `coach_guidance_media_validity_events`,
  `coach_guidance_independent_media_reviews`,
  `coach_guidance_independent_media_reviewers`,
  `coach_guidance_media_source_dependencies`,
  `coach_guidance_attachments`, `coach_guidance_attachment_versions`,
  `coach_guidance_lifecycle_events`, `coach_guidance_publications`,
  `coach_guidance_publication_invalidations`.
- Coach inline authoring (D5): `coach_inline_source_roles`,
  `coach_inline_source_role_reviewers`, `coach_inline_exercise_drafts`,
  `coach_inline_exercise_draft_authors`, `coach_inline_context_assessments`,
  `coach_inline_context_assessment_reviewers`,
  `coach_inline_exercise_eligibility_reviews`.

**5.7 The end of the financial records' period (a proposal, for the
founder).** v1.3 keeps purchase and token-use records five years from the end
of the financial year in which each was made, and says that nothing yet
deletes them when the five years end. *Proposal:* the scheduled clean-up
(decisions log N48.4, Q16) deletes each `token_ledger` and `llm_usage` row
once its five years have ended, for every account, open or deleted, and its
dry-run report counts them first; its first real run waits for the founder's
word, as N45 says. *Reason:* a period nobody enforces is a promise kept by
accident. The ledger is an audit trail (the balance lives on the account, not
in the ledger), so an open account loses nothing it needs. `financial-evidence-v1`
and its `retention_until_rule` are unchanged; only the deletion at the end is
new.

## 6. What this schedule does and does not do

- **It switches the deletion on for the entries in §2, and only those.**
  Signed and seeded, an account or project deletion no longer stops on them;
  it still stops on any entry in §3 or §5 that holds a row.
- **Nothing yet deletes job evidence when its 12 months end.** The scheduled
  clean-up (Q16) is where that belongs, but it is built to delete guests,
  audio, voice measurements and logs, and no evidence table. Job evidence
  joins it only by a reviewed change of its own, with a governed path for the
  append-only job events; its first real run waits for the founder's word.
- **The Privacy Policy lists three things that survive a deletion** (Privacy
  3.3 §9: the records that prove processing was agreed to, the training-choice
  record, and anything kept by law), and says a deletion removes "queued
  processing jobs" with everything else. Job evidence kept 12 months after a
  deletion is a fourth survivor, and the job row itself is kept with it. Until
  a Privacy version says so (the founder's sign-off on the words, and a
  re-acceptance), counsel is asked whether the first of the three covers it
  (counsel brief `21-…`, question 3).
- **Counsel reads this document** (Q15 A) before or after the signature; an
  answer that changes a row is a v1.5, never an edit of this one.

## 7. Signature

By signing, the approving authority adopts v1.3 unchanged together with the
additions in §1 and §2 and the decisions in tables A, B and §3, and records
that the proposals in §5 are not adopted by this signature: each needs the
controller's own answer and, once given, a later version.

    Name:      Artur Willoński
    Firm:      None — natural person, no company (działalność nieewidencjonowana)
    Date:      5 October 2026 (the day of the decision; the signature's own timestamp records when it was signed)
    Reference: WILLAB-PHASE1-2026.1-RET-v1.4
