# MLC-3 exercise dependency audit

Status: **M3-1 COMPLETE — DOCUMENTATION ONLY — CUTOVER BLOCKED**

Implementation addendum (M3-3): the original legacy audit remains unchanged.
New dark-only dependencies, authoritative RPCs, observation inputs, tables,
deletion classifications and remaining gates are mapped in
[`MLC3-M3-3-IMPLEMENTATION-REVIEW.md`](MLC3-M3-3-IMPLEMENTATION-REVIEW.md).
No legacy producer/reader/route/job/UI was cut over. New personal tables are
explicitly inventoried as `external_review`; they cannot be skipped by purge.

Owner: Señor Engineer

Product owner: Artur Willoński

Design: `MLC-3-D2`
Audit date: 2026-08-30

This is the checked-in producer, reader, route, job, UI, table, and legacy
classification required before any exercise schema or runtime implementation.
It authorizes no schema, runtime, migration, activation, dataset, training,
evaluation, promotion, deployment, or deletion change. Unknown dependencies
fail closed.

## 1. Decision-filter result

The work is split because it has two priorities:

```yaml
VERDICT:  ADVANCE-F1
CATEGORY: F1-CORE
WHY:      The versioned Feedback Policy V3 contract directly governs Manager
          evidence coverage and non-invention.
REDIRECT: Keep V3 inactive until its typed dark implementation passes ML/data,
          Engineering, and founder serving gates.
```

```yaml
VERDICT:  ADVANCE-F2
CATEGORY: F2
WHY:      The dependency audit is the named prerequisite for provenance-safe
          exact-clip exercise matching and practice under MLC-3-D2.
REDIRECT: Use this audit to design M3-2; do not reuse mixed legacy rows as
          canonical training or evaluation records.
```

`FILTER: ADVANCE-F1 / ADVANCE-F2 — cat F1-core + F2 — fences clear — locks clear — redirect: implement the typed dark M3-2 foundation only after separate authorization.`

## 2. Audit method and completeness boundary

The audit searched the backend and frontend `origin/main` trees for:

- `confident_voice_practice`;
- `confident_voice_practice_attempt`;
- `voice_album_practice`;
- `diagnostic_exercise`;
- `practice_exercise`;
- `confidence-practice`;
- `attach_exercise_offer`;
- `exercise_eligibility`;
- user/coach exercise API types and UI components.

Generated files, archived documentation, and unrelated uses of the ordinary
word “exercise” were excluded. The inventory covers every matching live source
path, migration, test, API proxy, and user/coach/admin surface found at the
audited revisions:

- backend `9492fdd` plus this documentation branch;
- frontend `origin/main` at `4dc0b032`.

If a later source scan finds another producer, reader, table, route, job, or UI
consumer, the cutover is blocked until this document is amended and reviewed.

## 3. Current production-shaped flow

```text
current exact-three Manager
  -> explore_ideal_text attaches at most one hard-coded exercise offer
  -> owner answers Confident Voice with legacy yes/no-compatible state
  -> owner explicitly opens/resumes one practice for the whole Take
  -> request synchronously transcribes, analyzes, and stores up to 3 attempts
  -> owner keeps/dismisses an attempt and supplies yes/no
  -> coach first submits a legacy blind yes/no confidence rating
  -> revealed coach screen chooses library/custom exercise and may share it
  -> selected attempt enters Voice Album only on machine/user/coach yes
```

This flow is not MLC-3. In particular it has one hard-coded matcher, one
practice per Take, two-state owner/coach controls in critical places, mutable
mixed-purpose rows, no complete exercise candidate frame, no exact audio-object
SHA-256 lineage, no MLC-3 as-of feature snapshot, no canonical exposure, and no
exercise-adequacy learning record.

All user and coach exercise routes are presently guarded by
`operational_purpose_disabled("personalized_exercise_recommendation")`. That is
a fail-closed product-purpose gate, not an MLC-3 implementation. The Manager
offer annotator is outside that route decorator, so an active legacy exercise
could still be serialized before the start route refuses it. M3-2/M3-5 must
eliminate that split activation boundary before any serving can be authorized.

## 4. Backend producers and readers

| Role | Source | Reads | Writes/returns | Current semantics | Classification | MLC-3 disposition / owner |
| --- | --- | --- | --- | --- | --- | --- |
| Offer matcher | `services/confident_voice_practice.py::exercise_eligibility` | one `snippet`, its metrics/words/audio ref, session median WPM | in-memory eligibility, pattern, priority, acoustic snapshot | hard-coded “Hear every word” acoustic rules | mixed-purpose | replace only after typed need/gate contracts; Señor Engineer |
| Offer attachment | `services/confident_voice_practice.py::attach_exercise_offer` | Manager-selected Confident Voice rows, snippets, `diagnostic_exercise`, existing practice | adds `practice_exercise` to at most one already-selected feedback row | one exercise per whole Take; suppresses collision with rewrite | mixed-purpose | V3 assignment service; no legacy matching import; Señor Engineer |
| Feedback assembly caller | `routes/v2/explore_ideal_text.py` | exact-three Manager output | invokes offer attachment and serializes it with Ideal Text feedback | synchronous best-effort annotation after old Manager | mixed-purpose | retire producer at atomic exercise cutover; Señor Engineer |
| Practice start | `routes/v2/user_sessions.py::v2_start_confident_voice_practice` | snippet, session, owner route, active exercise, Take snippets | `confident_voice_practice` | requires legacy owner yes/no, recomputes matcher, enforces one per Take | product + evaluation | preserve readable history; new MLC-3 assignment/session writer; Señor Engineer |
| Practice read | `routes/v2/user_sessions.py::v2_get_confident_voice_practice` | practice, exercise snapshot, attempts | owner-safe payload | hides raw metrics, exposes qualitative comparison | product-state | preserve read-only history; new canonical read adapter; Señor Engineer |
| Attempt processing | `routes/v2/user_sessions.py::v2_add_confident_voice_practice_attempt` | practice, prior attempts, exact passage, Take baseline | audio object, transcript, metrics, comparison, machine yes/no attempt | synchronous provider/storage work inside request; up to three attempts | mixed-purpose | replace with authorized exact-byte attempt boundary; Señor Engineer |
| Practice completion | `routes/v2/user_sessions.py::v2_complete_confident_voice_practice` | practice and attempts | selected attempt, kept flag, owner yes/no, closed state | product action and self-report stored together | mixed-purpose | preserve product result; split canonical action/judgment later; Señor Engineer |
| Comparison | `services/confident_voice_practice.py::comparison_for_attempt` | original/current/prior/best acoustic snapshots | internal deltas, strength, qualitative copy key | no approved MLC-3 primary endpoint/horizon | evaluation-only legacy | never import as adequacy label; ML/data owner for future label contract |
| Attempt Album reconciliation | `services/confident_voice_practice.py::reconcile_practice_voice_album` | selected attempt and practice | `voice_album_practice` insert/delete | exact-attempt machine/user/coach yes quorum | product-state | preserve admission; later link canonical judgments without merging; Señor Engineer |
| Coach read/write | `routes/v2/coach.py::v2_coach_confident_voice_practice` | legacy blind state, practice, exercise list, attempts | professional decision, selected-attempt coach yes/no, custom/library exercise, explicit share | revealed post-rating workflow; coach can author/share | mixed-purpose | preserve readable review; replace with versioned blind/reveal + authoring records; Señor Engineer |
| Exercise catalogue admin | `routes/journal.py` diagnostic list/save routes | `journal_post`, `diagnostic_exercise` | mutable mapping/activation | only `hear-every-word-v1`; published video required | product content | reviewed copy into immutable catalog only; Product/content reviewer + Señor Engineer |
| Database adapter | `services/db.py` practice/diagnostic/Album methods | four legacy tables | direct CRUD and updates | service-role table access; mutable rows | mixed-purpose | no canonical direct writes; new RPC-only boundary; Señor Engineer |
| Voice Album reader | `routes/v2/arcs.py::_serialize_arc_voice_album` | `voice_album`, practice attempt | user Album payload | practice attempt displayed as an Album item | product-state | preserve legacy entries and playback; Señor Engineer |
| Voice Album reconciler | `services/voice_album.py::reconcile_voice_album_clip` | practice/attempt or original clip evidence | Album admission/removal | distinguishes practice attempts from original clips | product-state | preserve; no adequacy supervision inference; Señor Engineer |
| Coach-share notification | `services/arc_notifications.py::fire_confidence_practice_shared` | practice/project/user IDs | `lounge_messages` action | explicit coach share creates one Chat action | product-state | preserve; future assignment/version ID in new action; Señor Engineer |
| Purge inventory | `services/data_purge_registry.py` | reviewed relation allowlist | deletion/review targets | attempts to include practice tables in Phase-1 purge graph | compliance support / unknown selectors | blocked pending exact selector repair and rehearsal; Señor Engineer |
| CEO source index | `services/ceo_intelligence.py` | named backend/frontend files | source snapshot only | internal code-review discoverability | product tooling | update path inventory when M3 files exist; Señor Engineer |

### Migration, documentation, and verification readers

| Source | Role | Classification | Disposition |
| --- | --- | --- | --- |
| `migrations/add_confident_voice_practice.sql` | defines and grants the four legacy relations | historical schema/product support | immutable migration; never edit or treat as MLC-3 schema |
| `migrations/manifest.txt` | orders the legacy migration | deployment history | unchanged in M3-1 |
| `test_confident_voice_practice.py` | protects one-per-Take, three attempts, explicit share, current matcher and Album behavior | legacy product verification | preserve; it does not prove MLC-3 eligibility |
| `tests/test_mlc2_legacy_isolation.py` | classifies legacy practice state outside canonical MLC-2 training | provenance verification | preserve and extend with MLC-3 isolation in its owning slice |
| `docs/MLC2-CONFIDENCE-DEPENDENCY-AUDIT.md` | prior Confidence audit that names practice as mixed product/evaluation state | authoritative historical audit | remains compatible with this classification |
| `docs/MLC3-EXERCISE-ADEQUACY-DESIGN.md` | accepted D2 target contract | MLC-3 design | governs future slices; is not executable behavior |

### Database adapter methods in scope

The direct adapter surface is complete as of this audit:

- `get_confident_voice_practice_candidates`;
- `get_active_diagnostic_exercise`;
- `list_diagnostic_exercises`;
- `upsert_diagnostic_exercise`;
- `get_confident_voice_practice_by_take`;
- `get_confident_voice_practice`;
- `create_confident_voice_practice`;
- `list_confident_voice_practice_attempts`;
- `get_confident_voice_practice_attempt`;
- `insert_confident_voice_practice_attempt`;
- `set_confident_voice_practice_strongest`;
- `update_confident_voice_practice`;
- `keep_confident_voice_practice_attempt`;
- `set_confident_voice_practice_attempt_coach_decision`;
- `insert_voice_album_practice_entry`;
- `delete_voice_album_practice_entry`.

No one of these methods is an approved MLC-3 canonical writer or dataset
reader.

## 5. HTTP and BFF route map

| Actor | Backend route | Frontend BFF | Mutation/read | Cutover rule |
| --- | --- | --- | --- | --- |
| Owner | `POST /v2/user/snippets/:snippetId/confidence-practice` | `POST /api/v2/user/snippets/:snippetId/confidence-practice` | creates/resumes legacy practice | remain disabled; replace only after canonical assignment exists |
| Owner | `GET /v2/user/confidence-practice/:practiceId` | matching GET BFF | reads legacy practice/history | preserve for old product state |
| Owner | `POST /v2/user/confidence-practice/:practiceId/attempts` | matching attempts BFF | synchronous upload/transcribe/analyze/write | remain disabled; new provider-permit/object-hash path required |
| Owner | `PUT /v2/user/confidence-practice/:practiceId/complete` | matching complete BFF | dismisses or keeps attempt and writes yes/no | preserve old decision; new typed action/judgment split required |
| Coach | `GET/PUT /v2/coach/sessions/:sessionId/snippets/:snippetId/confidence-practice` | matching coach BFF | revealed review, author/select/share, attempt yes/no | preserve history; replace with MLC-3 blind/reveal contract |
| Admin | `POST /v2/internal/journal/diagnostic-exercises/list` | matching internal BFF | lists mutable legacy mapping | retain for legacy inspection only |
| Admin | `POST /v2/internal/journal/diagnostic-exercises/save` | matching internal BFF | updates/activates `hear-every-word-v1` | cannot populate canonical catalog directly |

Every user/coach route is authenticated under its existing actor policy. None
has the MLC-3 acquisition-principal, canonical-speaker, immutable exercise
version, complete candidate frame, rendered exposure, or exact-byte lineage
contract.

The exact frontend BFF files are:

- `src/app/api/v2/user/snippets/[snippetId]/confidence-practice/route.ts`;
- `src/app/api/v2/user/confidence-practice/[practiceId]/route.ts`;
- `src/app/api/v2/user/confidence-practice/[practiceId]/attempts/route.ts`;
- `src/app/api/v2/user/confidence-practice/[practiceId]/complete/route.ts`;
- `src/app/api/v2/coach/sessions/[sessionId]/snippets/[snippetId]/confidence-practice/route.ts`;
- `src/app/api/v2/internal/journal/diagnostic-exercises/list/route.ts`;
- `src/app/api/v2/internal/journal/diagnostic-exercises/save/route.ts`.

## 6. Jobs, providers, notifications, and objects

There is no dedicated exercise queue, RQ job, cron, or analysis-worker stage.
That absence is part of the audit, not proof that no processing occurs:

| Operation | Current execution | Risk/constraint | MLC-3 owner action |
| --- | --- | --- | --- |
| Offer matching | synchronous during Ideal Text feedback assembly | coupled to old Manager response; failure is swallowed as no offer | move behind typed assignment boundary |
| Attempt transcription | synchronous in owner HTTP request via `transcribe_snippet_bytes` | provider call is not represented as MLC-3 lineage | require current authority/permit and immutable run lineage |
| Attempt acoustic analysis | synchronous in same request via `analyze_audio` and confidence read | mixed comparison and confidence evidence | freeze approved feature/run versions separately |
| Attempt object upload | synchronous via `put_lab_audio_bytes` | stores path/URL but not a verified object SHA-256 in practice row | add canonical object record and recomputed SHA-256 |
| Coach share | synchronous database update plus Chat notification | notification is product delivery, not exposure or label | retain explicit share; add authenticated render event later |
| Purge | Phase-1 inventory/resolver workflow | legacy practice selector coverage is not presently proven | fail closed until synthetic traversal passes |

M3-2 must not invent a background worker merely for architectural symmetry.
It must, however, use the existing authorization/provider/object/outbox
boundaries wherever asynchronous or external processing occurs.

## 7. Frontend/UI consumers

The frontend does not create exercise-adequacy labels. It does contain product
state that makes destructive legacy removal unsafe.

| Surface | Files | Current behavior | Classification | MLC-3 impact |
| --- | --- | --- | --- | --- |
| Feedback mapper | `src/services/api/idealText.ts` | maps optional `practice_exercise` nested in a feedback item | product-state adapter | future mapper must accept explicit assignment/version, never infer exposure |
| Ideal Text feedback | `src/components/willab/DeckChunkModal.tsx` | renders practice only after legacy owner `yes` or `no`; in-between/not-sure paths receive no exercise | product UI + legacy routing | replace with five-state exact-clip assignment flow |
| Owner practice | `src/components/willab/ConfidentVoicePractice.tsx` | offer, video, exact passage, recording, up to three attempts, final yes/no | product UI | preserve UX concepts; rebind to canonical session/attempt IDs |
| Owner API mapper | `src/services/api/confidentVoicePractice.ts` | maps practice/attempt payload; strips metrics | product adapter | retain score-free contract; add typed state without legacy inference |
| Coach practice | `src/components/willab/CoachConfidencePracticeReview.tsx` | loads only after definite blind yes/no, then reveals user answer and attempts; lets coach select/create/share | mixed product/evaluation UI | replace blind/reveal event sequence and five-state instrument |
| Coach API mapper | `src/services/api/coachConfidencePractice.ts` | maps two-state selected-attempt judgment and `yes/no/refine` professional decision | mixed adapter | professional decision stays evaluation-only; blind judgment separate |
| Coach parent card | `src/components/willab/CoachSnippetReviewCard.tsx` | enables practice only for coach `yes` or `no` | mixed review UI | five-state blind packet and post-submit reveal required |
| Coach-shared overlay | `src/components/willab/ConfidencePracticeOverlay.tsx` | read-only exact exercise/audio context | product UI | preserve explicit shared destination; attach exact version lineage |
| Chat/Lounge | `src/components/willab/Lounge.tsx` | opens overlay from `confidence_practice_shared` message | product delivery | opening is not rendered exposure; new client confirmation required |
| CMS | `src/app/cms/DiagnosticExerciseSection.tsx`, `src/services/api/journalAdmin.ts` | edits the one journal-backed exercise mapping | product content admin | cannot write immutable MLC-3 catalog without reviewed promotion flow |
| BFF proxies | `src/app/api/v2/**/confidence-practice/**`, diagnostic list/save routes | forwards backend contracts | transport only | no semantic inference; retire/repoint atomically with backend routes |
| Contract tests | `src/components/willab/confidentVoicePractice.test.ts`, `src/services/api/confidentVoicePractice.test.ts`, `idealText.changes.test.ts`, `blindLabelingIsBlind.test.ts` | protect legacy UI and blindness assumptions | verification | preserve as compatibility tests; add MLC-3 disabled/dark tests later |
| Loading contract test | `src/components/willab/loadingStateContract.test.ts` | includes the shared exercise overlay in loading-surface coverage | verification | preserve; unrelated to assignment/label semantics |

## 8. Table and adjacent-state classification

The classification vocabulary is strict:

- **product-state**: required to render or enforce an existing user action;
- **learning-only**: legacy material whose sole purpose is learning/evaluation;
- **mixed-purpose**: product state combined with prediction, judgment, or
  evaluation-like data;
- **unknown**: ownership, retention, selector, or runtime meaning is not proven.

| Relation/object | Classification | Evidence and incompatibility | Preserve/migrate decision | Explicit owner |
| --- | --- | --- | --- | --- |
| `diagnostic_exercise` | product-state content | mutable logical ID/version, library media and matching JSON; only one ID accepted | preserve; reviewed copy into immutable version/catalog, never automatic training import | Product/content reviewer + Señor Engineer |
| linked `journal_post`/video | product-state content | publication does not itself make an exercise safe/eligible | preserve; media enters new catalog only through explicit review/checksum | Product/content reviewer |
| `confident_voice_practice` | mixed-purpose | assignment, exact passage, user answer, machine assessment, professional verdict, custom/share state in one mutable row | preserve readable history; no canonical learning import; stop new writes only at atomic cutover | Señor Engineer |
| `confident_voice_practice_attempt` | mixed-purpose | product recording plus transcript, acoustic metrics, comparison, machine/user/coach yes/no in one row | preserve attempts; no adequacy/confidence training import; new attempts use canonical typed records | Señor Engineer |
| `voice_album_practice` | product-state | exact-attempt Album admission only | preserve; never treat membership as label | Señor Engineer |
| `owner_voice_album_routing` | product-state/self-report | practice start reads legacy yes/no route; styling/admission semantics are separate | preserve; do not infer MLC-3 response or effectiveness | Señor Engineer |
| `moment_suggestions`, legacy Feedback sets/exposure | mixed-purpose | current Manager candidate/product delivery state drives offer attachment | preserve V2 behavior until V3 cutover; prohibited as MLC-3 dataset input | Feedback V3 migration owner: Señor Engineer |
| `confidence_labels` and coach state | mixed-purpose evaluation | current route uses a definite legacy yes/no as reveal gate | preserve audit/product review; not an MLC-3 blind judgment | Blind-review migration owner: Señor Engineer |
| `snippets`, `v2_sessions`, source audio refs | product source with provenance relevance | identify source clip/Take but do not supply verified MLC-3 object hash alone | preserve; reference only through new exact lineage and verified object record | Lineage migration owner: Señor Engineer |
| practice attempt storage objects | mixed-purpose object | user playback + future evidence; path/URL exists, exact bytes not SHA-256-bound in practice table | preserve; compute canonical hashes only under authorized M3 flow | Object-lineage owner: Señor Engineer |
| `lounge_messages` coach-share action | product-state | explicit user delivery link; opening is not render-confirmed exposure | preserve; future exposure appended separately | Delivery owner: Señor Engineer |
| operational purpose registry for `personalized_exercise_recommendation` | product/compliance state | capability is registry-only/disabled and cannot authorize processing | preserve disabled until separate Product/legal activation | PLF owner + Product/legal |
| exercise-specific legacy learning-only tables | none found | current feature stores evaluation-like fields in mixed rows instead | no historical relabel/import | ML/data reviewer |
| purge selectors for `confident_voice_practice`, attempts, `voice_album_practice` | unknown | audit entries name `user_id`, while physical child tables use `owner_user_id`, `practice_id`, or `arc_id`; exact traversal is not demonstrated here | fail closed; correct through reviewed principal graph and synthetic deletion rehearsal before activation | Deletion owner: Señor Engineer |

## 9. Provenance and construct incompatibilities

The following legacy values are useful for current product history but invalid
as new MLC-3 supervision:

1. `eligible` from `exercise_eligibility` is product policy, never adequacy.
2. `priority` and `pattern` are hard-coded matcher output, not a learned need or
   outcome label.
3. `is_strongest` is the result of an unapproved comparison heuristic, not the
   predeclared MLC-3 primary endpoint.
4. owner `yes/no` fields omit the five-state confidence taxonomy and combine
   self-report with product completion state.
5. coach attempt `yes/no` is written after reveal in the current professional
   surface; it is evaluation-only, not an MLC-3 blind practice judgment.
6. `professional_coach_decision=yes/no/refine` is evaluation/product workflow,
   never confidence or exercise-effectiveness truth.
7. a coach-authored or shared exercise is not evidence that it was adequate.
8. an active/published library exercise is not evidence that it was eligible
   for this user or need.
9. opened, dismissed, no attempt, timeout, and Chat delivery are not outcomes.
10. Voice Album membership is a product quorum result, not training truth.
11. legacy audio URLs/paths do not prove exact underlying bytes.
12. historical rows predate the MLC-3 contract, candidate frame, assignment-
    time snapshot, consent/authority checks, and rendered exposure.

Therefore no historical exercise row may enter an MLC-3 dataset release by
copying, aliasing, relabeling, or reconstructing a missing exposure.

## 10. Required preservation and atomic cutover

### Preserve

- existing practice and attempt playback;
- owner selections/dismissals and qualitative assessments;
- explicit coach-shared exercise snapshots and Chat destinations;
- valid existing Voice Album practice entries;
- diagnostic content for review, without automatically promoting it;
- audit/retention evidence required by the approved deletion policy.

### Deactivate only at a future authorized cutover

- legacy offer attachment and matching;
- legacy new-practice and new-attempt writes;
- legacy mixed evaluation writes;
- legacy diagnostic mapping as the source of new assignments.

The cutover must use one atomic exercise-surface mode. Canonical writes and
serving may activate only as legacy matching/evaluation writes deactivate.
Rollback may stop canonical serving/writes but may not reactivate legacy
learning/evaluation writes. Legacy product history remains readable.

There is no authorized deletion. Unknown dependencies, selector mismatches,
unclassified provider/object calls, or incomplete UI routing block cutover.

## 11. Verification required before M3-2 or later cutover

M3-1 adds no tests because it changes no executable behavior. The following
tests are mandatory in the slices that own the corresponding code:

### Static dependency/isolation tests

- every source occurrence of the audited names maps to this document;
- canonical exercise dataset/release/training/evaluation code cannot import,
  query, or accept rows from the four legacy tables;
- no runtime alias maps `diagnostic_exercise` to the canonical learning
  surface without registry resolution;
- no product route writes both legacy and canonical learning provenance;
- the operational-purpose gate and exercise serving flag cannot diverge.

### Database/security tests

- canonical writes are RPC-only, append-only, RLS-protected, and principal-
  bound;
- complete catalogue/candidate sets include every eligible and excluded
  version with typed reasons;
- exact source/attempt audio objects have independently verified SHA-256;
- assignment-time snapshots reject later events;
- blind reveal is impossible before immutable judgment submission;
- authenticated client render is required for exposure;
- retries return the same assignment and do not redraw;
- legacy direct writers cannot execute after cutover;
- dataset builders reject every legacy table and any record without current
  authorization and release-time hash verification.

### Product compatibility tests

- old practices, attempts, shared exercises, and Album entries remain readable;
- a practice attempt never increments Take count or changes Ideal Text;
- no score/model verdict enters user payloads;
- five-state confidence answers stay separate from exercise assignment;
- at most three attempts remain enforced per new practice session;
- next Take never waits for exercise/coach work;
- no exercise is displayed when purpose processing is unavailable;
- deterministic top-only serving remains enforced until a separate endpoint
  and 80/20 exposure contract is approved.

### Deletion tests

- synthetic principal traversal reaches practices through owner/Take lineage,
  attempts through practice lineage, Album entries through attempt/project
  lineage, and every source/attempt object;
- cross-principal or incomplete graphs fail closed;
- shared exercise media is retained while still referenced by unaffected
  users and deleted only under its own content/retention authority;
- unknown relations/selectors produce reviewed blockers, never silent success.

## 12. M3-2 entry gate

M3-2 may be requested only after Product/Founder and ML/data accept this audit.
Its scope must remain the dark catalog and lineage foundation described by
`MLC-3-D2`:

- registry amendment for `exercise_adequacy_classification`;
- immutable exercise/need/version/catalog tables;
- exact object SHA-256 lineage;
- canonical learning-profile identity;
- authorization, review, RLS, and RPC contracts;
- no producer, route, UI, dataset, training, evaluation, promotion, serving,
  deployment, or deletion activation.

The following are explicit blockers, not M3-2 shortcuts:

- acoustic-need feature contracts still require individual ML/data approval;
- the outcome label/endpoint/horizon contract is not approved;
- 80/20 user exposure is not approved;
- `personalized_exercise_recommendation` is not operationally active;
- existing exercise media has not been promoted into an immutable reviewed
  catalogue with checksums and safety/need contracts;
- legacy deletion traversal selectors require repair and rehearsal;
- historical exercise data is not eligible for import or relabeling.

> **M3-1 AUDIT COMPLETE — Feedback Policy V3 is contractually defined and the
> legacy exercise dependency graph is classified. No executable change or
> activation has occurred.**
