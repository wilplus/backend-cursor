# MLC-2 Confidence Classification Dependency Audit

Status: `SLICE 4 DARK PRODUCER INTEGRATED — FLAG OFF — CUTOVER BLOCKED`

Owner: Señor Engineer

Contract: `MLC-2 / ED-2.4`

Surface: `confidence_classification`
Feedback family: `confident_voice`

This is the checked-in producer/reader/route/job/UI map required before any
legacy Confidence Classification path can change.  It authorizes no live
producer, legacy cutover, dataset, training, model promotion, merge or
deployment.  Unknown dependencies fail closed.

## Live behavior map

| Layer | Current entry point | Current storage/reader | Product behavior | MLC-2 target | Slice 3 action |
|---|---|---|---|---|---|
| Analysis job | `services.analysis_worker.run_full_analysis` calls `services.moment_suggestions.generate_for_session` | `services.db.upsert_moment_suggestion` → `moment_suggestions` | Produces acoustic delivery moments after a Take | one canonical outbox event followed by `ml_model_runs`, `ml_classification_runs`, `ml_machine_predictions`, `ml_selection_runs`, `ml_candidate_sets`, `ml_candidates` | audited only; unchanged |
| Acoustic classifier | `services.moment_suggestions._classify_acoustic_candidate` and `_persist_acoustic_candidate` | `moment_suggestions` plus snippet/acoustic fields | Creates the candidate and evidence used by the feedback Manager | typed confidence frame with exact R2 audio evidence and classifier versions | dark validator only |
| Take candidate adapter | `services.take_feedback_candidates.current_take_confident_voice_candidate` | reads current-Take snippets and `moment_suggestions` | Converts current-Take evidence into a Confident Voice feedback candidate | `ml_candidates` reading one immutable classifier prediction | unchanged |
| Exact-three Manager | `services.take_feedback_manager.rank_family_pool`, `exposure_snapshot`, `ensure_required_families` | `ideal_text_feedback_sets`, `take_feedback_exposure` | Deterministically selects the Confident Voice lane alongside correction and praise | confidence deterministic-policy selection run; still one of seven surfaces | unchanged |
| Feedback assembly | `routes.v2.explore_ideal_text` and `services.feedback_data_contract.build_feedback_exposure_bundle` | old ED-1 `candidate_sets`, `feedback_candidates`, `feedback_exposures`, `machine_predictions`, `evidence_spans` | Displays exact-three feedback and preserves current product flow | later render-confirmed `ml_presentations` / `ml_rendered_exposures`; no server-selection timestamp as “shown” | unchanged |
| User confidence response | `routes.v2.user_sessions.v2_post_take_feedback_response` | `take_feedback_self_report`; old ED-1 `confidence_self_reports` shadow | Stores the five-state self-report for the exact Take item | later immutable non-blind `ml_judgments` linked to rendered exposure and evidence | audited only; unchanged |
| User Voice Album routing | `v2_user_snippet_confidence_review`, `v2_put_confidence_agree`; `services.voice_album_routing` | `owner_voice_album_routing` | Product-only Yes/In-between/No routing; can block/permit album state | later `ml_product_actions`; never a label inferred from styling/admission | unchanged product state |
| Blind coach queue | `routes.v2.coach.v2_coach_confidence_queue`; `_confidence_queue_selection` | `confidence_labels`, old ED-1 evidence/assignment RPCs | Gives a coach an independently blind exact clip | later `ml_review_assignments` with blind packet hash and hidden selection metadata | audited only; unchanged |
| Blind coach judgment | `routes.v2.coach.v2_coach_put_confidence_label` | `services.db.upsert_confidence_label`; old ED-1 `confidence_coach_labels` shadow | Stores five-state blind coach judgment then permits reveal | later immutable `ml_judgments`; reveal only after submitted event | audited only; unchanged |
| Blind comparison | `routes.v2.coach.v2_coach_confidence_comparison` | current labels, owner response and comparison RPC | Reveals provenance-separated answers after blind submission | query canonical machine/user/coach/peer rows without merging them | unchanged |
| Non-blind star review | `v2_coach_put_star_verdict`; `services.star_verdicts` | `star_verdicts` | Professional review of an already revealed star | evaluation-only; never confidence training supervision | unchanged |
| Practice | `v2_start_confident_voice_practice`, `v2_add_confident_voice_practice_attempt`, `v2_complete_confident_voice_practice`; `services.confident_voice_practice` | `confident_voice_practice`, `confident_voice_practice_attempt`, `voice_album_practice` | Records and evaluates practice attempts | user self-report may later be eligible; revealed coach control remains evaluation-only until blind replacement | unchanged |
| Voice Album quorum | `services.voice_album.reconcile_voice_album_clip`, `refresh_voice_album` | `voice_album`, `voice_album_admissions`, `owner_voice_album_routing`, coach labels | Product admission requires its explicit quorum | later product-action link only; does not collapse machine/user/coach provenance | unchanged |
| Rereview | confidence-rereview functions in `services.db` and coach/session readers | `confidence_rereview_queue` | Keeps unresolved product review work visible | later review-assignment state, not a label | unchanged |
| Corpus/export | `services.db.get_confidence_label_corpus`, coach corpus routes, legacy scripts | `confidence_labels`, `training_labels`, annotation/export tables | Legacy evaluation/training views | prohibited as an MLC-2 dataset source | guarded; no canonical consumer |

## Frontend and BFF consumers

The UI does not create classifier predictions.  These consumers prove why the
legacy product state cannot simply be deleted during a learning cutover:

| User/coach surface | API/BFF | UI reader |
|---|---|---|
| Take feedback and self-report | `src/services/api/takeFeedback.ts`; `/api/v2/user/snippets/[snippetId]/confidence-review`; `/confidence-agree` | `src/components/willab/DeckChunkModal.tsx` |
| Blind coach rating | `/api/v2/coach/sessions/[sessionId]/confidence-queue`; `/api/v2/coach/snippets/[snippetId]/confidence-label`; `/confidence-comparison` | `src/components/willab/CoachSnippetReviewCard.tsx` |
| Coach corpus/evaluation | `src/services/api/trainingCorpus.ts`, `starVerdicts.ts`, `founderConfidenceComparison.ts` | `src/app/coach/corpus/page.client.tsx` |
| Voice Album | `src/services/api/voiceAlbum.ts`; `/api/v2/explore/arc/[arcId]/voice-album`; `/api/v2/voice-album` | `src/app/voice-album/page.client.tsx` |

Paths above are in the `hunter-frontend` repository.  No frontend file imports
or knows about the Slice 3 database contracts.

## Legacy storage classification and migration owners

| Object(s) | Classification | Why it must not be treated as canonical training data | Target / owner | Cutover status |
|---|---|---|---|---|
| `moment_suggestions` | mixed-purpose | powers current feedback and also contains historical classifier-like output with incomplete MLC-2 provenance | confidence runtime frame / Señor Engineer | blocked |
| `ideal_text_feedback_sets`, `take_feedback_exposure`, `take_feedback_self_report` | mixed-purpose | necessary product delivery/response state; server selection is not rendered exposure | presentations, rendered exposures, judgments / Señor Engineer | blocked |
| old ED-1 `candidate_sets`, `feedback_candidates`, `feedback_exposures`, `machine_predictions`, `acoustic_feature_snapshots`, `evidence_spans` | mixed-purpose | supports current parity/blind-review paths but lacks the MLC-2 event, consent and speaker boundary | Slice 3 frame plus foundation evidence / Señor Engineer | blocked |
| old ED-1 `confidence_self_reports`, `confidence_coach_labels`, `confidence_peer_labels` | mixed-purpose | actor provenance exists in separate tables but does not satisfy the MLC-2 canonical envelope and exposure rules | immutable `ml_judgments` / Señor Engineer | blocked |
| `confidence_labels` | mixed-purpose | current blind coach product state is also read by legacy corpus/export paths | review assignment + judgment / Señor Engineer | blocked |
| `owner_voice_album_routing`, `voice_album`, `voice_album_admissions`, `voice_album_practice` | product-state | explicit routing/admission is a mutation, never a training label | product actions only / Señor Engineer | preserve |
| `star_verdicts`, `snippet_confidence_reviews` | mixed-purpose evaluation | non-blind/revealed controls are evaluation-only for confidence | evaluation lineage later / Señor Engineer | preserve; blocked for training |
| `confident_voice_practice`, `confident_voice_practice_attempt`, `diagnostic_exercise` | product-state/mixed evaluation | user practice and revealed professional controls have different blindness and eligibility rules | typed later events / Señor Engineer | preserve |
| `confidence_rereview_queue` | product-state | workflow state is not a judgment | review workflow / Señor Engineer | preserve |
| `training_labels`, annotation tables, export corpora | learning-only legacy | no historical import or relabeling is authorized | no MLC-2 target history / Señor Engineer | permanently prohibited as MLC-2 input |

## Dark contract delivered by migration 0303

The additive schema separates what the classifier did from what the Manager
selected:

1. `ml_model_runs` records provider-neutral classifier execution and a distinct
   deterministic-policy execution.
2. `ml_classification_runs` records feature, extractor, detector, threshold and
   taxonomy versions.
3. `ml_machine_predictions` stores each exact machine output separately from
   every human judgment.
4. `ml_selection_runs` is allowed for this surface only as
   `execution_kind=deterministic_policy`, references its classification run,
   and freezes the 20% exploration probability and RNG provenance.
5. `ml_candidate_sets` and `ml_candidates` persist the complete eligible and
   excluded pool, ranks, probabilities, reason codes, selected rows and the
   immutable pool hash.
6. `finalize_mlc2_confidence_frame_v1` writes the canonical event, R2 metadata,
   exact evidence, both runs, every prediction and the complete frame in one
   PostgreSQL transaction.  Conflicting replays fail closed.

All new tables are append-only, RLS-enabled, unreadable by `anon` and
`authenticated`, SELECT-only for `service_role`, and writable only through the
reviewed RPC.  Blind payload construction remains a later slice and must never
include scores, ranks, thresholds, selection reasons, probabilities, RNG or
model/version hints.

## Cutover gates (all currently closed)

- `Config.MLC2_CONFIDENCE_CUTOVER_MODE` is hard-coded `dark`; it is not an
  environment-controlled flag. Slice 6 adds the reviewed
  `dark` / `founder_canary` / `killed` state machine so rollback cannot
  resurrect a retired learning writer.
- No route, product service, worker or UI imports `services.mlc2_confidence`.
- No learning provenance is dual-written to an old and new learning store.
- The old product-state writers remain unchanged.
- No historical row is imported or relabeled.
- Canonical dataset/release/training code is prohibited from reading every
  object named in this audit.
- ML/data review is required before producer activation.
- A later atomic cutover must enable the canonical producer as the legacy
  learning writer deactivates.  Rollback may disable the canonical producer but
  may not reactivate legacy training writes; queued outbox events remain
  retryable.

## Slice 4 dark integration

Migration `0304` and the application bridge make the future boundary
executable without changing current production behavior:

- Successful Take promotion and the `confidence_take_ready` outbox event use
  one PostgreSQL transaction. Invalid identity, consent or immutable R2 source
  metadata rolls back both. Worker failure after commit leaves the Take intact
  and the event visible and retryable.
- `claim_mlc2_confidence_outbox_v1` can lease only Confidence Classification
  producer events; it cannot consume another surface's work.
- `services.mlc2_confidence_producer` validates the event envelope and exposes
  a dependency-injected worker seam. It is not registered with RQ, the analysis
  worker or a sweeper.
- `ml_confidence_blind_packets` freezes an exact selected clip and the
  five-state rating instrument. The server constructs the allowlisted packet;
  transcript, prediction, score, rank, model, threshold, policy, probability,
  RNG and every prior human answer are absent.
- A blind judgment requires an authenticated client-rendered exposure. Reveal
  requires the immutable judgment itself, not merely a UI event.
- The same hard-coded mode chooses the atomic producer promotion and the prior
  ED-1 all-family learning shadow: `dark` permits only the pre-cutover shadow,
  `founder_canary` permits only the canonical founder producer, and `killed`
  permits neither. Legacy `moment_suggestions` remains a product read/write
  model; it is not a canonical or dataset source.

The mode remains literal `dark`. No environment value can activate it. The SQL
rehearsal invokes the dark RPCs directly inside a disposable transaction; that
proves the cutover contract without activating a producer in any app process.

## Tests required before Slice 3 acceptance

- SQL contract tests for exact surface/stage/family semantics, provider-neutral
  classifier runs and deterministic selection-only execution.
- Complete-frame validation including eligible and excluded candidates,
  rankings, probabilities, selected rows, 20% exploration and RNG lineage.
- PostgreSQL apply/reapply and atomic rollback/replay rehearsal.
- RLS, direct-write denial and append-only tests for every new table.
- Static isolation test proving no product route imports the dark module and no
  MLC-2 module references a legacy learning object.
- Checked-in audit completeness test covering every object in the table above.

Only after those tests pass may Slice 3 be submitted for ML/data and Engineering
implementation acceptance.  Acceptance still does not authorize cutover.
