# Phase-1 processing policy `phase1-2026.1` — drafting pack

**Status: partly signed, NOT registrable.** `SIGNED-ARTIFACTS.md` is the single
authority on which artifacts are signed and what their hashes are — this line
said "nothing here is signed" long after `01` and `06` were signed on
2026-09-19, which is exactly the drift that comes of recording the same fact in
two places. Do not restate signature state here; link to that file.

**Not registrable** remains true and is the load-bearing half: `04` §5 and
`SIGNED-ARTIFACTS.md` both require all four rows to carry a hash before
`register_phase1_policy_v1` may be called, and `02` and `03` are blank pending
re-signature.

This pack is the written material needed to register and activate one Phase-1
processing policy through `register_phase1_policy_v1` / `activate_phase1_policy_v1`
(`migrations/add_phase1_processing_boundary.sql`, as replaced by
`migrations/enable_practice_phase1_purpose.sql`). It exists so that when the
blocker lifts, the only things missing are a counsel signature, a handful of
dates, and the hashes.

Read `docs/PHASE1-PROCESSING-RUNBOOK.md` first. This pack supplies the content
that runbook refuses to let anyone invent in code.

## Contents

| File | What it is | Becomes |
|---|---|---|
| `01-product-legal-approval-v1.0-DRAFT.md` | Lawful-basis determination for every operation performed on a recording | `processing_legal_artifacts.artifact_kind = 'product_legal_approval'` |
| `02-power-score-classification-v1.0-DRAFT.md` | AI Act determination for what `power_score` and the voice-confidence composite actually compute | `… = 'power_score_classification'` |
| `03-article-50-assessment-v1.0-DRAFT.md` | Article 50 transparency assessment and compliance record | `… = 'article_50_assessment'` |
| `copy/terms-2.0.txt` | Terms of Service, full text | `processing_policy_versions.terms_copy` |
| `copy/privacy-2.0.txt` | Privacy Policy, full text | `… .privacy_copy` |
| `copy/ai-notice-1.0.txt` | AI notice, full text | `… .ai_notice_copy` |
| `copy/agreement-1.0.txt` | The "I agree and continue" screen, exact words | `… .agreement_copy` |
| `04-policy-registration-DRAFT.md` | Versions, countries, per-purpose lawful bases, registry control versions, the RPC payload shape | the `register_phase1_policy_v1` call |
| `05-us-counsel-brief-DRAFT.md` | Instructions to US counsel: BIPA, CCPA, all-party consent, US terms | — (US counsel's own determination) |
| `06-retention-schedule-v1.0-DRAFT.md` | The retention and destruction schedule | `… = 'retention_schedule'`, and the rows in `data_retention_rules` |
| `07-vendor-actions-DRAFT.md` | Who to contact for each DPA, with the text to send | — (executed agreements, filed) |
| `10-training-policy-changes-DRAFT.md` | Privacy 3.1 → 3.2: the training changes, revised 2026-10-01 to counsel's fixes (text only, six-year consent record, the regurgitation sentence) | `copy/privacy-3.2.txt` (approved by the founder 2026-10-01, N15; effective 1 October 2026; PUBLISHED as `phase1-2026-10-01`, active since 2026-10-01 09:00 UTC) |
| `11-retention-schedule-v1.1-training-DRAFT.md` | Retention schedule v1.1: v1.0 plus the training rows | `… = 'retention_schedule'` v1.1, and two more rows in `data_retention_rules` |
| `12-terms-training-licence-DRAFT.md` | Terms 3.1 → 3.2: the licence to reproduce and adapt the speaker's text for training (counsel's fix, 2026-10-01) | `copy/terms-3.2.txt` (approved by the founder 2026-10-01, N15; effective 1 October 2026; PUBLISHED as `phase1-2026-10-01`, active since 2026-10-01 09:00 UTC) |
| `13-training-consent-wording-SIGNED-2026-10-01.md` | The switch sentence and the four lines above it, counsel's wording, signed by the founder 2026-10-01 | `configure_mlc2_training_consent_policy_v1` (the copy, its hash, the evidence PDF) |
| `14-founder-determinations-2026-10-02/` | The founder's eight answers of 2026-10-02 that held four gates shut (6a, Phases 4 and 5, 6d, door 2), one record each; author line "founder and controller; not reviewed by outside counsel" | the four documents below |
| `15-coach-blind-check-privacy-line-and-balancing-test-SIGNED-2026-10-02.md` | Gate 6a: the Privacy and Terms lines, the legitimate-interest balancing test, the opt-out, the retention row (Q1, Q2) | `copy/privacy-3.3.txt`, `copy/terms-3.3.txt` (signed 2026-10-02; `scripts/phase1_policy_publish_3_3.sql`), one `data_retention_rules` row (`18-…`) |
| `17-door-2-coach-word-surfaces-shut-2026-10-02.md` | Door 2 stays shut for `coach_moment_line` and `coach_take_word` until the speaker's yes covers them (Q8), and what would open it | — (a record) |
| `02-power-score-classification-v1.1-DRAFT.md` | Document 02 v1.1: scope extended to the speaking-error detectors (§3b), Q6 recorded with its condition (§8), the determination restated (§9). Supersedes v1.0 by version bump, never in place; signed by the founder 2026-10-02 (rendered for the PAdES signature the same day) | `… = 'power_score_classification'` v1.1, by the signed PDF's hash once uploaded |
| `16-share-switch-wording-SIGNED-2026-10-02.md` | Phases 4 and 5: the Terms and Privacy wording for the per-recording share switch, the listener's answer as their own data, the path and the retention rows (Q3 to Q5) | the same 3.3 copies (signed 2026-10-02), `PEER_SHARE_POLICY_VERSION`, two `data_retention_rules` rows (`18-…`) |
| `18-retention-schedule-v1.2-blind-check-and-lending-DRAFT.md` | Retention schedule v1.2: v1.0 unchanged, v1.1's two training rows, and the three rows of 15 §3 and 16 §3; prepared for the founder's PAdES signature 2026-10-02 | `… = 'retention_schedule'` v1.2 and five rows in `data_retention_rules` (`scripts/phase1_retention_rules_v1_2.sql`) |
| `19-retention-schedule-v1.3-financial-records-DRAFT.md` | Retention schedule v1.3: v1.2 unchanged, plus the financial-records row (five years from the end of the financial year), answering v1.0 §3; signed by the founder (PAdES) 2026-10-05 | `… = 'retention_schedule'` v1.3 and one row in `data_retention_rules` (`scripts/phase1_retention_rules_v1_3.sql`) |
| `20-retention-schedule-v1.4-product-records-and-job-evidence-DRAFT.md` | Retention schedule v1.4 (N48.4 Q15 A): v1.3 unchanged, plus two rules — product records deleted with the account or the project (41 registry entries), job evidence kept 12 months (9) — 5 more product records after one read-only check, and 142 entries set out as proposals for the founder, not adopted by the signature (adopted the same evening for a v1.5, N50 P1–P7); signed by the founder (PAdES) 2026-10-05 (D1 A, N50), for counsel to read | `… = 'retention_schedule'` v1.4 and two rows in `data_retention_rules` (`scripts/phase1_retention_rules_v1_4.sql`, run by hand after the upload and only after 0424 and 0425 are deployed) |
| `03-article-50-assessment-v1.1-DRAFT.md` | Document 03 v1.1 (N48.4 Q22 A): §6 says what the screens label today (frontend `main` at `9a928fd6`), and four statements v1.0 still carried are corrected; no conclusion moves. Supersedes v1.0 by version bump, never in place; signed by the founder (PAdES) 2026-10-05 (D2 A, N50) | `… = 'article_50_assessment'` v1.1 (`scripts/phase1_register_article_50_v1_1.sql`, run by hand after the upload) |
| `21-counsel-questions-2026-10.md` | The counsel brief of October 2026 (N48.4 Q23 A, Q22 A, Q21 A, Q18 B, Q15 A and the open counsel items): eleven numbered questions, the first being document 02's condition, each with the document and lines to read | — (counsel's answers; a dated, signed letter for question 1) |
| `22-privacy-terms-3.5-all-learning-SIGNED-2026-10-08.md` | Privacy 3.4 → 3.5 and Terms 3.4 → 3.5 (founder 2026-10-08, "open every learning pipe"): every learning lane under the one training yes, the changelog, decisions D1–D4 and the code each switch needs first (E1–E8). SIGNED by the founder 2026-10-08 with D1–D4 as drafted (N68); counsel has not seen it. Not yet published | `copy/privacy-3.5.txt`, `copy/terms-3.5.txt` |
| `23-training-consent-wording-v2-SIGNED-2026-10-08.md` | The switch sentence v2 and its eight lines (the coach's words, answers and measurements, models for every speaker), and the registration call that retires v1. SIGNED by the founder 2026-10-08 (N68), counsel has not seen it; rendered for the PAdES signature the same day (`SIGNED-ARTIFACTS.md`) | `configure_mlc2_training_consent_policy_v1` (training-only-v2), once v1 can be retired (N68: the table is append-only) |
| `24-retention-rows-learning-lanes-SIGNED-2026-10-08.md` | Retention rows for the learning lanes and the imported corpus, for the next schedule version. SIGNED by the founder 2026-10-08 (N68), counsel has not seen it | `… = 'retention_schedule'` (next version) and its `data_retention_rules` rows |
| `02-power-score-classification-v1.2-NOTE-SIGNED-2026-10-08.md` | Document 02 v1.2 as a note on v1.1: the learned detector (§3c) and gate 6d's condition. SIGNED by the founder 2026-10-08 (N68), counsel has not seen it | `02-power-score-classification-v1.2-SIGNED-2026-10-08.md` |
| `02-power-score-classification-v1.2-SIGNED-2026-10-08.md` | Document 02 v1.2, full text: v1.1 with the signed note's three changes applied (§3c, the §9 note on detector training, the metadata). Supersedes v1.1 by version bump, never in place; rendered for the PAdES signature 2026-10-08; NOT counsel-reviewed | `… = 'power_score_classification'` v1.2, by the signed PDF's hash once uploaded |
| `SIGN-3.5-2026-10-08.md` | One-page signing sheet for 22, 23, 24, 02 v1.2 and the DPIA and ROPA addenda (`docs/legal/`): the sentence to sign, the founder's three confirmations, the steps after, the consent-screen words; the signature recorded 2026-10-08 | — |

The four `copy/*.txt` files are deliberately plain text with no front matter,
headers, or commentary: their **exact bytes** are what gets hashed and what a
user later proves they agreed to. Do not add anything to them that is not meant
to be read by a user on the acceptance screen.

## What only the founder can supply

**Scope, settled 2026-09-17 and CORRECTED 2026-09-18: freemium, Poland and
intended EU/EEA, operated by a natural person with no entity.** Operating as a
natural person is a fully compliant configuration — GDPR does not require a
legal person. The other two halves of the 2026-09-17 settlement were wrong: the
line here read *"Poland only, free"* and described it as settled, both halves
were withdrawn on 18 September, and the pack is written against the corrected
version. The correction is sourced in code, not recalled:

- **Not free — payment is real but unexercised.** `services/token_prices.py:51`
  — `TIERS` carries `free` / `practice` / `coaching` / `intensive` at 0 / 12 /
  39 / 89 USD (`:53-56`), free being 12,000 tokens a month, all four in
  `SOLD_TIERS` (`:85`), and the backend holds a live Stripe key, so checkout is
  reachable in production now. **No customer has ever been charged** — the
  capability is live, the transaction history is empty. Terms §1 was corrected
  accordingly in `ad43af8`.
- **Not Poland only.** Documents 01 and 03 are to be scoped for the EU
  generally. `09-counsel-cover-note.md` states the correction and the three
  consequences counsel is asked to take into account (the
  *działalność nieewidencjonowana* revenue threshold, the Consumer Rights
  Directive, and scope).

So `allowed_countries` is **not** settled at `["pl"]`. It is `["pl"]` today, and
widening it depends on the per-country Art 9(4) conditions the cover note asks
counsel for at ask 5, since Member States may impose further conditions on
biometric processing. **Document 04 must not harden the list before that answer
arrives.** Retention periods (document 06) are still settled.

**Parked, not cancelled.** The US (document 05) and a merchant of record return
together with incorporating — with no entity, Illinois BIPA's private right of
action would land on a natural person. Paid plans are no longer on that list;
they shipped ahead of it, which is what forced this correction. Document 01 §2
names the trigger conditions and explains why incorporating *before* the first
policy
registration is much cheaper than after it.

**Still outstanding.** Each is marked `[[FOUNDER: …]]` at the point of use.

1. **Approving authority and approval date** for each signed document — a named
   person or firm. The `mlc2-bundled-consent-v1.json` precedent recorded the
   founder as the authority "recording the approved counsel determination".
   Document 02 should not be signed that way; see its §9.
2. **The email provider's name**, and the transfer mechanism for each vendor
   (document 07 collects these).
3. **Sign-off on all four copy documents** (LIVE LOOP fence: user-facing copy is
   founder-signed before it ships).

## What only counsel can supply

EU counsel: the determination in document 02, and review of 01 and 03, scoped
for the EU/EEA rather than Poland alone (see the correction above). US counsel
is not needed until we incorporate; document 05 is parked on that, not on
geography.

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

(`migrations/enable_practice_phase1_purpose.sql:205-211` →
`POWER_SCORE_CLASSIFICATION_CONFLICT` is raised at `:211`. The same gate is in the
superseded `migrations/add_phase1_processing_boundary.sql:1554-1560`; both are
kept because the boundary migration is the one already applied in production.)

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
