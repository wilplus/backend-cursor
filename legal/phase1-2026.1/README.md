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
