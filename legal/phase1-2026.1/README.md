# Phase-1 processing policy `phase1-2026.1` — drafting pack

**Status: DRAFT. Nothing here is signed, approved, or registrable as it stands.**

This pack is the written material needed to register and activate one Phase-1
processing policy through `register_phase1_policy_v1` / `activate_phase1_policy_v1`
(`migrations/add_phase1_processing_boundary.sql`, as replaced by
`migrations/enable_practice_phase1_purpose.sql`). It exists so that when the
blocker lifts, the only things missing are a counsel signature, four founder
decisions, and the hashes.

Read `docs/PHASE1-PROCESSING-RUNBOOK.md` first. This pack supplies the content
that runbook refuses to let anyone invent in code.

## Contents

| File | What it is | Becomes |
|---|---|---|
| `01-product-legal-approval-v1.0-DRAFT.md` | Lawful-basis determination for every operation performed on a recording | `processing_legal_artifacts.artifact_kind = 'product_legal_approval'` |
| `02-power-score-classification-v1.0-DRAFT.md` | AI Act determination for what `power_score` and the voice-confidence composite actually compute | `… = 'power_score_classification'` |
| `03-article-50-assessment-v1.0-DRAFT.md` | Article 50 transparency assessment and compliance record | `… = 'article_50_assessment'` |
| `copy/terms-2.0-DRAFT.txt` | Terms of Service, full text | `processing_policy_versions.terms_copy` |
| `copy/privacy-2.0-DRAFT.txt` | Privacy Policy, full text | `… .privacy_copy` |
| `copy/ai-notice-1.0-DRAFT.txt` | AI notice, full text | `… .ai_notice_copy` |
| `copy/agreement-1.0-DRAFT.txt` | The "I agree and continue" screen, exact words | `… .agreement_copy` |
| `04-policy-registration-DRAFT.md` | Versions, countries, per-purpose lawful bases, registry control versions, the RPC payload shape | the `register_phase1_policy_v1` call |

The four `copy/*.txt` files are deliberately plain text with no front matter,
headers, or commentary: their **exact bytes** are what gets hashed and what a
user later proves they agreed to. Do not add anything to them that is not meant
to be read by a user on the acceptance screen.

## What only the founder can supply

Nothing in this pack invents any of these. Each is marked `[[FOUNDER: …]]` at
the point of use.

1. **Approving authority** for each of the three legal documents — a named
   person or firm. The `mlc2-bundled-consent-v1.json` precedent recorded the
   founder as the authority "recording the approved counsel determination".
   Document 02 should not be signed that way; see its §9.
2. **Approval date** for each document.
3. **Retention periods** for every data category except the two that are already
   implemented in code (practice attempts, 30 days, `services/practice_retention.py`;
   orphan objects, 24 hours, `queue_phase1_orphan_audio_v1`). The Privacy Policy
   leaves these blank on purpose.
4. **Allowed countries**. `04` recommends `["pl"]` and explains the cost of more.
5. **Sign-off on all four copy documents** (LIVE LOOP fence: user-facing copy is
   founder-signed before it ships).

## What only counsel can supply

The determination in document 02. The pack drafts the analysis and lays out the
facts and the arguments on both sides; it does not reach the conclusion for you.
The pack is written by an engineer reading the code, not by a lawyer.

## Hashes

Not computed here, on purpose. `register_phase1_policy_v1` recomputes
`sha256(copy)` and raises `POLICY_COPY_HASH_MISMATCH` on any disagreement, so a
hash committed before the founder's final edits is worse than no hash — it looks
authoritative and is wrong. Compute at registration time from the exact bytes
that will be passed as `terms_copy` / `privacy_copy` / `ai_notice_copy` /
`agreement_copy`:

```
sha256sum legal/phase1-2026.1/copy/terms-2.0.txt
```

Canonicalisation must be fixed before the first hash is taken and never changed
afterwards: **UTF-8, LF line endings, no BOM, and the file's trailing newline
either included in the hashed string or stripped — pick one and write it down
in `04`.** A mismatch here is the difference between a user's receipt verifying
and not verifying.

## Two structural findings that came out of drafting

These are not drafting notes. They are things about the system that the founder
should decide on before any of this is registered.

### 1. The schema only admits one answer to document 02

`register_phase1_policy_v1` refuses the registration unless the
`power_score_classification` artifact carries all three of:

```
metadata.biometric_identification    = false
metadata.sex_gender_inference        = false
metadata.emotion_intention_inference = false
```

(`enable_practice_phase1_purpose.sql` lines 205-211 → `POWER_SCORE_CLASSIFICATION_CONFLICT`.)

A compliance record whose only registrable value is "no" is a weak control: it
does not verify the determination, it applies pressure to it. If counsel's
honest answer to the third one is "yes, or arguably yes", the correct response
is to change the product or the gate — not to sign the document that fits.
Document 02 §9 sets out what would have to change in each case.

The first two are well supported by the code as it stands. The third is the
genuinely contested one.

### 2. Optional purposes get no consent evidence

`accept_phase1_processing_authorization_v1` writes
`processing_authorization_receipt_purposes` rows only for purposes where
`required_for_core_service` is true:

```sql
SELECT receipt.id, pp.purpose_id, pp.lawful_basis_code
  FROM processing_policy_purposes pp
 WHERE pp.policy_id = policy.id AND pp.required_for_core_service
```

So a purpose declared optional in the policy is declared to the user and then
never consented to in a way the receipt can prove. There is no second surface
that captures it. This is why `04` recommends a v1 policy containing only the
two genuinely required core purposes, and why `coach_review`,
`individual_learning_profile` and `personalized_exercise_recommendation` are
held back for a v1.1 that ships alongside an optional-consent capture. Confirm
against the service layer (`services/processing_authorization.py`) before
relying on this reading.

## Sequencing

**0. Form the *sp. z o.o.* first.** Founder decision 2026-09-17. It changes the
controller identity, and therefore the Privacy Policy, and therefore its hash —
so a policy registered before the company exists has to be registered again, and
every user who accepted has to accept again. Formation takes one to two weeks and
runs in parallel with the engineering. See document 01 §2.

1. Founder fills the remaining `[[FOUNDER: …]]` blanks and signs off the four copy files.
2. Counsel reviews 01 and 03, and makes the determination in 02.
3. Signed PDFs go to storage; only `object_key` + `sha256` reach the database.
4. Hashes computed from final bytes; `04`'s payload assembled.
5. Staging rehearsal per the runbook, then `register_phase1_policy_v1`.
6. `activate_phase1_policy_v1`, then `PLF1_PROCESSING_AUTHORIZATION_MODE=enforce`
   on **web, worker and every cron service**, verified from each boot log
   (CONFIG-FIRST rule).

Step 6 before step 5 takes the product down: with `enforce` set and no active
policy, `get_phase1_processing_authorization_v1` returns
`PROCESSING_POLICY_INACTIVE` and every recording is refused.
