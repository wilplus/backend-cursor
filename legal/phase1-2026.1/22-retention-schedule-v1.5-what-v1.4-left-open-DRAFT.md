# Retention schedule v1.5 — what v1.4 left open (for the founder's signature)

    artifact_kind:       retention_schedule
    version:             1.5 — supersedes 1.4 (signed 2026-10-05); never edited in place, see 04 §5
    approving_authority: Artur Willoński (founder and controller)
    approved_at:         2026-10-05 (the day the controller decided the answers; the document records a date, not a time)
    object_key:          phase1-2026.1/legal/retention-schedule-v1.5.pdf
    sha256:              [[computed from the signed PDF at registration time]]
    control_version:     phase1-retention-schedule-v1.5
    author:              Artur Willoński, founder and controller; not reviewed by outside counsel

**STATUS: DRAFT, for the controller's signature, and for counsel to read.**
The controller answered every proposal of v1.4 §5 on 5 October 2026, on the
Wave 3 sign-off page: "P1 A / P2 A / P3 A / P4 A / P5 A / P6 A / P7 A"
(decisions log N50, item 5). v1.5 is **v1.4 unchanged, plus those seven
answers as adopted, plus how the deletion acts on each of them.** Every
period, rule and open point in `06-retention-schedule-v1.0-DRAFT.md` and in
v1.1 to v1.4 (`11-…`, `18-…`, `19-…`, `20-…`) carries over word for word,
except v1.4 §5's seven proposals, which this version answers.

**v1.4 §3 is unchanged and still waits.** Its five tables
(`v1_sessions_review`, `pre_answers_review`, `post_answers_review`,
`student_tasks_review`, `performance_scores_review`) are product records by
v1.4's rule, but no migration in this repository creates them, and the
deletion deletes nothing whose production shape it cannot show. The
founder's read-only look at production has been asked for; its results are
not in yet. Until a later change acts on them, a row there still stops a
deletion for a person.

**v1.5 seeds no rule.** Every answer has a period that a rule already signed
expresses, so each entry points at that rule:

| What was answered | Rule it is decided under | Its period |
|---|---|---|
| P1, P6; P2's free founding pass; P4's video made for the speaker; P5's four tables with one owner | `product-records-v1` (v1.4) | deleted with the account or with the project |
| P2's arc paid for, in credits or through Stripe | `financial-evidence-v1` (v1.3) | five years from the end of the financial year in which it was made |
| P3, the training-choice snapshot | `consent-evidence-v1` (v1.2) | six years after withdrawal or erasure |
| P4's library video | `product-records-v1` (v1.4), for the speaker's link only | the link is deleted with the account; the video stays as the library's |
| P7 | `financial-evidence-v1` (v1.3) | unchanged; the clean-up now deletes each row when its five years end |

P5's corpora are not product records. Their period, as the founder answered
it, is the product records' period (gone with the account), so v1.5 points
them at that rule rather than seed a second rule with the same period; the
deletion files them under that rule's id.

---

## 1. The published schedule

**No new row.** Each answer falls under a row a person can already read:
v1.4 §1's first row ("every other record of how you used the service",
deleted with the project or the account) covers P1, P5, P6, the free
founding pass and a reference video made for the speaker; v1.3's financial
records row covers a paid arc and P7; v1.2's training-choice record covers
P3. A library video is not a record of the speaker's use: only the line that
named the speaker on it is, and that goes. So nothing a person reads
changes, and v1.5 asks for no new words.

## 2. The answers, as adopted

**P1. The nine live records, deleted with the account or the project.**
`learning_surface_presentations`, `learning_surface_exposure_receipts`,
`ideal_text_user_edit_cas_operations`,
`confident_moment_text_update_capabilities`, `feedback_v3_memberships`,
`feedback_v3_membership_items`, `feedback_v3_owner_responses`,
`feedback_v3_service_render_receipts`,
`feedback_v3_service_response_bindings`. The founder's answer named "a
governed database function, applied by hand once", because v1.4 §5.1 said a
deletion needed a function that removes rows, which the migration runner
will not apply by itself. It does not need one. Each of these tables already
has a guard function that refuses every change; migration 0429
(`migrations/the_purge_reaches_what_v1_5_decided.sql`) gives each guard one
governed branch, so the deletion deletes exactly the rows its own sealed
inventory names, and nothing else can. That is the guarantee the answer
chose, and nothing has to be applied by hand but this document's
registration (§5). One of the nine,
`confident_moment_text_update_capabilities`, never holds a row when no one
is editing: the function that writes each row deletes it before it returns.
The deletion counts it and finds nothing; if it ever found a row, it would
stop for a person.

**P2. An arc purchase, told apart by its own columns.**
`arc_purchases_founding_pass`: a free founding pass, redeemed with an invite
code and recording no payment (`kind` founding_pass, `source` invite_code,
no amount, no credits, no checkout) is a product record, deleted with the
account, or with the project whose arc it unlocked. `arc_purchases_paid`: an
arc paid for, in credits or through Stripe (`source` credits or stripe), is a
financial record, kept five years under `financial-evidence-v1`, like the
token ledger; the clean-up that ends the ledger's five years does not reach
it yet (§4). `arc_purchases_review`: a row that is neither (a manual grant,
or a pass that records a payment) still stops a deletion for a person.
Before v1.5 is registered the whole table is that last entry, as today.

**P3. The training-choice snapshot is consent evidence.**
`ml_consent_snapshots`: kept six years under `consent-evidence-v1`, as
`ml_consent_events` already is.

**P4. A reference video goes with the account unless it is library
content.** `reference_videos_library`: a video made library content
(`is_universal`) stays, with the words and tags it was given, and loses only
what tied it to the speaker: their account, their session and their draft.
`reference_videos_own`: a video made for the speaker is deleted with the
account; but its file has no recorded hash or storage provider, so the
deletion cannot prove it deleted the right bytes, and each one stops the
deletion for a person first, as the speaker's own uploads do
(`REFERENCE_VIDEO_PROVIDER_AND_SHA256_UNRESOLVED`). Before v1.5 is
registered the table is `admin_uploaded_reference_review`, as today.

**P5. The retired corpora: a person's own rows go with the account, table by
table.** Four have one column that says whose a row is and hold no stored
file, so the deletion deletes them: `legacy_reflection_clips` and
`legacy_strong_sides` (by the speaker's account), `legacy_recording_reviews`
and `legacy_recording_review_annotations` (by the speaker's Take, which their
foreign key names). The count in §5 previews them: how many rows, and how
many people. The other six still stop a deletion for a person, each until a
reviewed, previewed clean-up of its own: `legacy_snippets_table_review`
(rows from more than one producer, and audio paths), `retired_stress_corpus`
and `legacy_snippet_labels` (no migration shows their shape),
`legacy_acoustic_labels` (a labeller's rows beside the speaker's, and
external clips), `legacy_shadow_predictions` (two text keys, either may be
empty), `legacy_training_labels` (the retired challenge/threat labels: a
coach's label beside the Take it names, by a key the database does not
check). Nine of the ten are
the bundled-era erasure's own list (`migrations/pending/erase_bundled_era_corpus.sql`),
which is that clean-up, still waiting for the founder's authorisation and
counsel's review.

**P6. Learning lineage and the switched-off paths, deleted with the account,
by the same governed branch as P1.** The entries are v1.4 §5.6's, unchanged;
a reviewer's or an author's own rows go with that person's account:

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

**P7. Financial records go when their five years end.** `token_ledger_review`
and `llm_usage_review` are kept through a deletion under
`financial-evidence-v1`, as v1.3 decided. The scheduled clean-up deletes each
row once its five years have ended, for every account, open or deleted, and
counts first; its first real run waits for the founder's word
(`migrations/financial_records_go_after_five_years.sql`, 0426, decisions log
N50 item 6). The deletion itself is unchanged. A paid arc (P2) is kept under
the same rule, but the clean-up names only these two tables, as P7 did (§4).

## 3. How the deletion acts on them

1. **The switch.** Every entry above is marked `schedule="1.5"` in
   `services/data_purge_registry.py`. The deletion acts on one only while
   its rule is active in `data_retention_rules` AND
   `processing_legal_artifacts` holds `(retention_schedule, 1.5)`, which only
   `scripts/phase1_retention_schedule_v1_5.sql` writes. Until both hold, the
   entry does exactly what it did before v1.5: a matching row stops the
   deletion for a person, and nothing is deleted.
2. **The guards.** 0429 adds the governed branch to the nine guard functions
   these tables use, and a guard to the three that had none. The branch lets
   a deletion through only when a deletion request is running with a sealed
   inventory, a pending target of it names this table and this row's own
   key, that target was frozen as a v1.5 delete, its rule is an active
   product-records rule, and v1.5 is registered. Every other change is
   refused, with the message it always had. The service role gains DELETE on
   109 of P1's and P6's 110 tables (all but the editing capability, which
   holds no row at rest), and SELECT only on the columns a deletion selects
   a row by: identifiers, never what anyone said or wrote.
3. **A delete that could not finish stops before anything is deleted.**
   Before the inventory is sealed, each v1.5 delete is checked: may the
   service delete those rows, and does any row the deletion does not delete
   first still point at them? Either one stops the whole deletion for a
   person (`PURGE_CANNOT_DELETE_HERE`, `KEPT_ROWS_STILL_POINT_HERE`) instead
   of failing part-way after the audio is gone. Each delete runs before every
   row it points at.
4. **A project.** A record that names its project, Take or snippet goes with
   the project; the speaker's answers to V3 moments, which name only their
   membership, are reached through the project's memberships, which the
   project's inventory lists since 0429. A person's settings, enrollment,
   training-choice snapshot, paid arcs, reference videos and their own reviews
   of others' work stay with the account. A record no project column reaches
   stops a project deletion for a person whenever the account holds one, as
   before; all of those sit behind switches that are off.

## 4. What these answers do not reach (for the founder)

v1.5 decides each table. What follows are rows the deletion meets that
these answers do not reach, and one period nothing yet ends, each with the
question it puts to the founder.

- **The speaker's answer to a rewrite.** The canonical copy of "Accept and
  practise" / "Keep my words" (`correction_decisions`) is kept as part of
  the empty receipt of the Take (N12), and it points at the V3 item it
  answered, a P1 record, with a key the database refuses to break. For
  anyone who answered a rewrite, the deletion stops at
  `feedback_v3_membership_items`. *Options:* (A) the answer goes with the
  item: it is the speaker's own answer, which v1.4 already decided, in its
  other copy (`take_feedback_self_report`), is a product record; or (B) the
  item stays, as part of the receipt, holding nothing but identifiers.
  *Proposal:* A.
- **A delivery job of the coaching bundle.** Kept 12 months as job evidence
  (v1.4 Table B), it points at the bundle row it delivers, a P6 record.
  *Options:* (A) the job goes with the bundle row; (B) the bundle row waits
  for the job's 12 months. The bundles are switched off; the count in §5
  shows whether any job exists.
- **Learning lineage no inventory reaches.** Fourteen tables of the dark
  learning foundation hang from P6's records and name no person themselves.
  The count shows whether any row exists; if one does, its own reviewed
  deletion is needed first.
- **The end of a paid arc's five years.** From v1.5 a paid arc (P2) is a
  financial record, but the clean-up that deletes financial records when
  their five years end names `token_ledger` and `llm_usage` only, as P7
  did, so nothing yet deletes a paid arc then. Credits could first buy an
  arc in July 2026, and no arc was ever bought through Stripe (N49), so no
  such period ends before 2031. *Options:* (A) the clean-up's financial
  rule takes paid arcs too; (B) it waits until a period is near its end.
  *Proposal:* A, as a reviewed change to the clean-up.
- **A reference video made for the speaker** (P4): its file, as above.
- **The six retired corpora** without a resolver (P5), and **v1.4 §3's five
  tables**, as above.

## 5. How it reaches the database

1. **First, the count.** `scripts/phase1_retention_v1_5_counts.sql`, run in
   the Supabase SQL editor: one SELECT, read only. It prints, table by table,
   the rows of v1.4 §3 and §5 (P1 to P7), the split P2 and P4 make, P5's
   preview, and the rows the deletion keeps that point at v1.5's records.
   Paste the result back: it says which of §4's stops are real.
2. **The deploy.** Merging applies 0429 when the service starts. It touches
   no row.
3. **The registration.** Once this document is signed and the PDF uploaded
   to its `object_key`, put the signed file's sha256 in
   `scripts/phase1_retention_schedule_v1_5.sql` and run it once, by hand. It
   registers this document under `(retention_schedule, 1.5)` and nothing
   else. It refuses while the hash is missing, while any of the three rules
   it points at is not active (run the v1.2, v1.3 and v1.4 scripts first),
   and while 0429 is not in the database. Running it is what switches v1.5
   on.

## 6. What this schedule does and does not do

- **It switches the deletion on for the entries in §2, and only those.**
  Registered, an account or project deletion no longer stops on them, except
  where §4 says it still does.
- **It changes nothing a person reads** (§1), and nothing the deletion keeps
  that v1.0 to v1.4 decided.
- **The bundled-era erasure is not this.** It stays a separately authorised,
  previewed operation of its own.
- **Counsel reads this document** before or after the signature; an answer
  that changes a row is a v1.6, never an edit of this one.

## 7. Signature

By signing, the approving authority adopts v1.4 unchanged together with the
answers in §2, decided under the rules in the table above, and records that
§4's questions are not answered by this signature: each needs the
controller's own answer and, once given, a later version or a reviewed
change.

    Name:      Artur Willoński
    Firm:      None — natural person, no company (działalność nieewidencjonowana)
    Date:      5 October 2026 (the day of the decision; the signature's own timestamp records when it was signed)
    Reference: WILLAB-PHASE1-2026.1-RET-v1.5
