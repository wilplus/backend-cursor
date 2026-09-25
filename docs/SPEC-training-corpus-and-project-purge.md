# SPEC — Training corpus, training consent and project-scoped purge

**Status:** DRAFT design. Docs only. Nothing here is built, switched on, or
authorized to run. Founder locks C1–C4 (2026-09-25) are recorded in
`docs/SPEC-DECISIONS-LOG.md` §N and are binding on this design.
**Owner:** founder. **Counsel:** required before Phase 5 (§8).
**Filter:** `ADVANCE-F2 — cat {F2: provenance-safe learning; P1 is F1-SURFACE} — fences {clear} — locks {clear: L3 walls kept, §4.4} — redirect: {n/a}`

---

## 0 · What this is for

A user deletes a project. Every piece of product data for that project goes.
If, and only if, that user currently holds an active training yes, the
separate training copies made from that project survive. They survive under a
written retention rule, and they go the moment the yes is withdrawn or the
account is erased.

Four things are needed, and none of them exists today:

1. a **project-scoped purge** (the only purge today is principal-wide);
2. a **training-only consent record**, stored in the MLC-2 tables;
3. a **training corpus**: separate copies, not pointers to product rows;
4. a **purge disposition** that keeps corpus copies only while the training
   yes is active.

## 1 · Decisions (founder locks, 2026-09-25)

| # | Decision |
|---|---|
| C1 | Training may return later only through a **new policy version that every user re-accepts**. |
| C2 | The training yes is stored in the **MLC-2 consent tables**. **Bundled-era yeses count for nothing.** Only a fresh yes counts: given under the new policy version, as its own act, separate from everything else. Anything recorded under `mlc2-bundled-consent-v1` is never a training yes and is never migrated into one. |
| C3 | Training copies survive a project delete **only** for users with an active training yes, and are purged on withdrawal. Account erasure purges them too. |
| C4 | DPIA correction #651 merged as it was. |

Also settled in the same review (founder, 2026-09-25):

- **Voice is not biometric data** in this product, on counsel's advice.
  `article_9_basis` is therefore `NULL` on a training grant.
- **No backfill.** There are no users whose data could enter the corpus
  lawfully; the corpus starts empty at the new policy version.
- **Honest delete copy** once training is live: *"Your project will be
  deleted. Recordings you shared for training stay until you withdraw that
  permission."* The exact text is held for founder sign-off (§8, P5).

## 2 · Where things stand (facts, 2026-09-25)

- **Training is not processed.** Policy `phase1-2026-09-23` registers no
  training purpose. The database refuses one (`PHASE2_PURPOSE_FORBIDDEN`,
  `POOLED_LEARNING_MUST_REMAIN_PHASE2`, `pooled_learning_eligible` pinned
  false), and `MLC2_*_ENABLED = False` plus `routes/phase2_guard.py` keep
  dataset, training and promotion off. See the DPIA §2.4 status note.
- **Only a principal-wide purge exists.** `data_purge_requests` carries an
  `acquisition_principal_id` and a `trigger_kind` in `service_termination |
  account_deletion | retention_expiry | third_party_audio_report |
  lawful_deletion`. `resolve_phase1_purge_subject_graph_v2` resolves a whole
  principal. There is no project coordinate.
- **Project delete is pulled.** The row-delete route (#647) could not remove a
  canonical Take. Takes are referenced `ON DELETE RESTRICT` by recording
  attempts, feedback candidates, Ideal Text core snapshots, Confident Moment
  bundles and Voice Album rows (manifest 0296/0297/0315/0327). The route was
  reverted by #649 and the picker's button by frontend #464.
- **The MLC-2 consent tables cannot hold a training-only yes as they stand:**
  - `ml_consent_policies` has `CHECK (required_for_service)` and
    `CHECK (bundled_ui)`. Only a required, bundled policy can be registered.
  - `record_mlc2_consent_grant_v1` always writes **both** purposes
    (`personalized_coaching` + `pooled_model_improvement`) and raises unless
    exactly 2 rows exist.
  - `record_mlc2_consent_withdrawal_v1` copies **every** purpose of the grant
    onto the withdraw event. Withdrawing training through it would also
    withdraw coaching.
  - `get_mlc2_principal_consent_status_v1` counts a grant only when it carries
    both purposes, and raises unless exactly one policy is active.
  - `ml_consent_event_purposes` itself is fine: one row per purpose, and
    `pooled_model_improvement` is an allowed value.
- **The purge registry already fences the MLC-2 lineage.** `ml_consent_events`,
  `ml_consent_snapshots`, `ml_purge_requests` and the legacy corpora
  (`training_labels`, `shadow_predictions`, `snippet_labels`, …) are
  `external_review`, which halts a purge for human resolution.
- **A second optional-consent writer exists.** Decisions log M6 keeps
  `accept_phase1_processing_authorization_v2` for pooled model improvement.
  §3.5 says which record is authoritative.

## 3 · The training consent record (C2)

### 3.1 Keep the tables, add versioned functions

The tables `ml_consent_policies`, `ml_consent_events`,
`ml_consent_event_purposes` and `ml_consent_snapshots` are reused. The `_v1`
functions are **left in place and never called by any new path**; they remain
for the audit trail. New functions are added beside them.

### 3.2 Schema changes (one additive migration, idempotent)

- `ml_consent_policies`:
  - relax `CHECK (required_for_service)` and `CHECK (bundled_ui)` so that
    `false` is storable;
  - add `grant_scope TEXT NOT NULL DEFAULT 'bundled_v1' CHECK (grant_scope IN
    ('bundled_v1', 'training_only'))`. Existing rows keep `bundled_v1`.
  - a `training_only` policy must have `required_for_service = false` and
    `bundled_ui = false` (table CHECK).
- No change to `ml_consent_event_purposes`.

### 3.3 `record_mlc2_training_consent_grant_v2`

Records **one** purpose row, `pooled_model_improvement`, with
`article_6_basis = '6(1)(a)'` and `article_9_basis = NULL`. It refuses unless:

- the policy is active, its `grant_scope = 'training_only'`, and
  `bundled_ui = false`;
- the terms, privacy and copy hashes match the policy's legal approval (same
  check as v1);
- `affirmative_action` shows **its own act**: `accepted = true`, the copy
  hash, and a `control` naming the training toggle. A yes captured on any
  other control (sign-up, the processing acceptance, a combined screen) is
  refused.

It is idempotent on `idempotency_key`, like v1.

### 3.4 `record_mlc2_consent_withdrawal_v2(purpose)`

Withdraws **one purpose** of a grant. The withdraw event copies only that
purpose row. For training it:

1. writes the withdraw event with the single `pooled_model_improvement` row;
2. enqueues the corpus purge for that principal (§6.3);
3. leaves every other purpose, and the product, untouched.

### 3.5 `get_mlc2_training_consent_status_v2` — the one reader

**Active training yes** means: the latest grant event for the principal
whose policy has `grant_scope = 'training_only'`, carrying a
`pooled_model_improvement` purpose row, with no later withdraw event
superseding it.

- Grants under a `bundled_v1` policy are **never** read, so
  `mlc2-bundled-consent-v1` acceptances cannot count (C2). This is enforced by
  the query, not by a data migration: nothing is copied or rewritten.
- It does not raise when more than one policy is active. It selects by
  `grant_scope`, unlike the v1 reader.
- **It is the only authority for "training yes".** The copy job (§4), the
  purge (§6) and any future training read path call it. The Phase-1 receipt's
  `pooled_learning_eligible`, and any value written by
  `accept_phase1_processing_authorization_v2` (M6), are **not** a training yes
  under this design (Q4 = A, §3.6).

### 3.6 The Phase-1 receipt and the training grant (Q4 = A)

Two separate acts create two separate records:

1. **Accepting the policy version** writes the Phase-1 receipt
   (`accept_phase1_processing_authorization_v2`). The receipt proves which
   policy version the user accepted, with its required purposes and the
   policy's *other* optional purposes. It **never** records a training tick,
   before or after P5. `pooled_learning_eligible` stays false, and the
   receipt writer refuses `pooled_model_improvement` as a chosen purpose.
2. **Turning the training toggle on** writes the MLC-2 training grant
   (§3.3). It is the only training yes.

`record_mlc2_training_consent_grant_v2` refuses unless the principal holds a
Phase-1 receipt for the policy version that introduced training. That is
how C1 (every user re-accepts) is enforced.

At P5 the new policy text describes training, so accepting it covers the
notice. The yes itself is still only the separate toggle.

Decisions-log M6 is amended, not dropped. The optional-consent writer keeps
its job for the policy's other optional purposes
(`personalized_exercise_recommendation`, `individual_learning_profile`); it
no longer covers pooled model improvement.

Per C2 the yes is **recorded per user**, **withdrawable on its own** without
leaving the product, and **read by the purge**.

## 4 · The training corpus (separate copies)

### 4.1 Copies, never pointers

Corpus items are **copies**: their own rows and their own storage objects. A
product delete must never be blocked by a corpus row, and a corpus purge must
never touch product data. So:

- **No foreign key** from corpus rows to `v2_sessions`, `projects`, snippets or
  any product row. An FK is exactly what blocked the reverted row delete.
  Lineage is kept **by value**: source ids stored as plain UUIDs, plus the
  source content's SHA-256.
- Audio bytes are copied to a **separate storage prefix** (proposed
  `training-corpus/<principal>/<item>`). They are never shared with the
  product object; the purge's shared-object check would block that anyway.

### 4.2 Tables (proposed)

`training_corpus_items`:

| Column | Notes |
|---|---|
| `id` | UUID PK |
| `acquisition_principal_id` | FK `owner_principals`, RESTRICT |
| `training_grant_event_id` | FK `ml_consent_events` (must be a `training_only` grant) |
| `consent_snapshot_id` | FK `ml_consent_snapshots`: consent state at copy time |
| `source_project_id`, `source_take_id`, `source_ref` | plain UUID/text, **no FK** |
| `source_sha256` | hash of the source bytes or row at copy time |
| `item_kind` | `audio_segment` (around Confident Voice items), `transcript_span`, `coach_label` (Q1, settled) |
| `label_provenance` | `machine`, `owner_routing`, `blind_peer`, `coach`, `detector`: one per row, never mixed (L3) |
| `storage_key`, `object_sha256` | for audio kinds |
| `retention_rule_id` | FK `data_retention_rules` |
| `state` | `active`, `purge_pending`, `purged` |
| `created_at` | |

### 4.3 When a copy is made

A copy job runs after a Take is processed. It copies **only** when
`get_mlc2_training_consent_status_v2` returns an active yes at that moment. It
records a consent snapshot, and it copies nothing from Takes recorded before
the grant. The job sits behind `phase2_guard` and stays dark until P5 (§8).

### 4.4 Provenance walls (L3)

Each item carries exactly one `label_provenance`. The copy never merges
owner routing, blind peer rating, coach judgment, machine prediction or
detector verdict into one row. It never copies one recording's signal onto
another recording's item.

## 5 · Retention rule

- A `data_retention_rules` row, `rule_code = 'training_corpus'`,
  `evidence_category = 'training_corpus'`. Its `legal_artifact_id` is the new
  policy version's legal artifact.
- `retention_until_rule`: **until the training yes is withdrawn or the account
  is erased.** No fixed maximum (Q2, settled).
- The rule is `active = false` until P5. With it inactive, the purge cannot
  keep any corpus item (fail closed).
- `legal/phase1-2026.1/06-retention-schedule-v1.0` gains a "Training copies"
  row at P5.

## 6 · Purge behaviour

> **Proven before building (N9, 2026-09-25).** A purge of an account with a
> real recorded take could not finish: retained recording-attempt evidence
> points at the project row ON DELETE RESTRICT. The project row is now kept as
> a tombstone with its content wiped (migration 0368), and
> `tests/test_take_purge_postgres.py` shows the run reaching `done`. Project
> scope (§6.1) builds on that. Production still stops at `review_required`
> until the retention schedule seeds its rules.

### 6.1 Project-scoped purge (prerequisite for C3)

- `data_purge_requests` gains a nullable `project_id` (FK `projects`), and
  `trigger_kind` gains `project_deletion`. A `project_deletion` request must
  carry a `project_id` owned by the principal; every other kind must not.
- A new resolver, `resolve_phase1_purge_project_graph_v1(principal, project)`,
  returns the same graph shape as the principal resolver, restricted to one
  project: its Takes, recordings, snippets, Ideal Text, feedback, Confident
  Moment bundles and Voice Album rows. Principal-level rows (account,
  consent, authorization evidence) are out of scope for a project purge.
- The same fail-closed invariants apply (DELETION-DEPENDENCY-AUDIT §invariants):
  freeze the graph and targets first, delete child before parent, and send any
  `external_review` match to `review_required`. Deleting child rows first is
  what handles the `ON DELETE RESTRICT` lineage the row delete could not.

### 6.2 The corpus dependency

The registry adds `training_corpus_items` (and its storage objects) with a new
disposition, **`retain_while_training_consented`**. At inventory freeze:

| Trigger | Training yes active? | Corpus items |
|---|---|---|
| `project_deletion` | yes | **retain** under `training_corpus` (rule must be active) |
| `project_deletion` | no | delete |
| `account_deletion` / `lawful_deletion` / `service_termination` | any | **delete** (C3) |
| training withdrawal (§6.3) | n/a | delete, all of that principal's items |

The disposition is resolved once, at freeze time, by calling
`get_mlc2_training_consent_status_v2`. The result is bound into the frozen
inventory hash. A withdrawal after freeze is honoured by the §6.3 purge, not
by editing a frozen run.

### 6.3 Withdrawal purge

`record_mlc2_consent_withdrawal_v2('pooled_model_improvement')` enqueues a
corpus-only purge for the principal: every `training_corpus_items` row and
object, with verified deletion and absence as for any other storage target.
Items already used in a trained model are not un-trained: **no retraining,
stop future use** (Q3, settled). A withdrawn user's items are never used in a
new training run, and the DPIA records this position at P5.

### 6.4 Execution — operator-confirmed (Q5, settled)

`project_deletion` requests **wait for an operator**, exactly like every other
purge today: execution requires `PHASE1_PURGE_EXECUTION_ENABLED=true` and an
operator repeating the request id. The user's tap creates the request; it does
not execute it. There is no automatic execution path.

That means the operator needs a queue: pending `project_deletion` requests,
each showing its frozen inventory (targets, retained corpus items and why) and
any `review_required` reason, with the confirm step. The freeze runs when the
request is created, so the operator confirms exactly what the user asked to
delete.

Settled 2026-09-25 (decisions log N8):

- **Target:** an operator confirms within **7 days** of the request. The
  legal ceiling is one month (Art. 12(3)); 7 days is the promise shown to the
  user.
- **Cancel:** the user can cancel a pending request until an operator
  confirms it. Nothing has been deleted before confirmation, so cancelling
  changes no data. A cancelled request keeps its row with a terminal
  `cancelled` state; it is never deleted or reused.
- **Queue:** the operator queue lives in the existing admin panel.

## 7 · Product surface

- The picker's ⋯ → **Delete** comes back, creating a `project_deletion`
  request. Because an operator confirms every purge (§6.4), the project does
  **not** vanish on tap. It shows a pending-deletion state and can't be
  opened or recorded into, and it disappears once the request reaches `done`.
  The UI never claims "deleted" before that. The wording is signed off
  (N8):

  | Where | Text |
  |---|---|
  | Confirm dialog title | Delete "&lt;project name&gt;"? |
  | Confirm dialog body | Every take in this project and its ideal text will be permanently deleted. This can't be undone. We'll finish within 7 days, and until then the project is locked. |
  | Confirm button | Request deletion |
  | Row label while pending | Deletion pending |
  | Undo while pending | Cancel deletion |
- **Copy:**
  - Before P5 (no training), the existing signed-off copy: *"Every take in this
    project and its ideal text will be permanently deleted. This can't be
    undone."*
  - From P5, for a user with an active training yes: the honest copy (§1).
- The training toggle lives on its own screen as its own act (§3.3). It is
  never on sign-up, never pre-ticked, and never a condition of using the
  product. Its copy needs founder sign-off.

## 8 · Phases

| Phase | What | Needs |
|---|---|---|
| **P1** | Project-scoped purge (§6.1), operator queue in the admin panel (§6.4), picker delete with pending state and cancel (§7); corpus absent | Migration via manifest. Founder go-ahead and copy given (N8) |
| **P2** | Consent schema + v2 functions + v2 reader (§3), with no `training_only` policy row | Migration only; stays dark |
| **P3** | Corpus tables + copy job (§4), behind `phase2_guard` | Migration; stays dark |
| **P4** | Registry disposition `retain_while_training_consented` + withdrawal purge (§6.2, §6.3) | Deletion-completion tests updated |
| **P5** | New policy version with the training purpose, the re-accept flow, the training toggle, the retention rule activated, honest delete copy | **Counsel review**, founder sign-off on copy, lifting `PHASE2_PURPOSE_FORBIDDEN` for this one purpose, updated Privacy text and retention schedule |

P1 is useful on its own and doesn't depend on any training decision. P2–P4
can land dark in any order after P1. Nothing reaches a user until P5.

## 9 · Questions

Settled by the founder, 2026-09-25:

- **Q1 — what to copy:** all of audio segments around Confident Voice items,
  transcript spans, and coach labels.
- **Q2 — retention:** until the training yes is withdrawn or the account is
  deleted. No fixed maximum.
- **Q3 — model lineage:** no retraining after withdrawal; stop future use.
- **Q4 — which record holds the training yes:** A. The MLC-2 training grant
  is the only training yes; the Phase-1 receipt records the accepted policy
  version and never a training tick (§3.6).
- **Q5 — execution:** a `project_deletion` purge waits for operator
  confirmation (§6.4).

No design questions remain open. Counsel review is still required before P5.

## 10 · Invariants the implementation must test

1. A grant under a `bundled_v1` policy never makes
   `get_mlc2_training_consent_status_v2` return an active yes.
2. `record_mlc2_training_consent_grant_v2` writes exactly one purpose row,
   and refuses a non-`training_only` or bundled policy.
3. Training withdrawal leaves `personalized_coaching` and all product data
   untouched.
4. No `training_corpus_items` column is a foreign key to a product table.
5. A `project_deletion` purge removes every product row and object of that
   project, including RESTRICT-linked lineage, and nothing from another
   project.
6. Corpus items survive a `project_deletion` only when the frozen inventory
   recorded an active training yes and an active `training_corpus` rule;
   account erasure always deletes them.
7. The copy job copies nothing when the reader returns no active yes.
8. `accept_phase1_processing_authorization_v2` refuses
   `pooled_model_improvement` as a chosen purpose, and every receipt keeps
   `pooled_learning_eligible = false`.
9. `record_mlc2_training_consent_grant_v2` refuses a principal with no
   receipt for the policy version that introduced training.
