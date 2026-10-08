# Retention rows for the learning lanes (Privacy 3.5)

**DRAFT — for the founder's signature; counsel not yet consulted on these changes.**

    artifact_kind:       retention_schedule (rows to be carried by the next signed schedule version)
    version:             the next version after v1.4; v1.5 is already reserved for N50 P1–P7 (reverted by #909 and to re-land), so these rows ride whichever version is signed next
    approving_authority: Artur Willoński (founder and controller)
    approved_at:         [[at signature]]
    author:              engineering, from Privacy 3.5 §4a, §4c and §7; not a lawyer
    rests on:            22-privacy-terms-3.5-all-learning-DRAFT.md, 23-training-consent-wording-v2-DRAFT.md

**What this is.** The periods Privacy 3.5 publishes for the new data, set
out as schedule rows and as rules to seed, so that no new category exists
without a signed period (Art 5(1)(e); the lesson of v1.0 §3 and of
`11-retention-schedule-v1.1-training-DRAFT.md`). Every row already in v1.4
stands unchanged; in particular the `training_corpus` and
`consent-evidence-v1` rows of v1.1 keep their periods, and the corpus row's
"never audio" holds (22-…, D1).

**Signing these rows switches nothing on.** A `data_retention_rules` row needs
`legal_artifact_id`, a signed schedule; the rows below are seeded when that
schedule is signed and registered, each inactive until its lane's switch PR,
like v1.1's.

## 1. Additions to the published schedule

| Category | Period | Trigger |
|---|---|---|
| Training copies (only with **Help improve WillpowerLab**): the words of practised passages, what the coach wrote about them (the three answer kinds, the coach's line on a moment, the coach's word for a Take), and a coach's yes or no about a shown moment. Text only, never audio | until the speaker turns the choice off or deletes the account; then deleted here and at OpenAI | turning it off (including a training-only-v1 yes retired by v2), or account deletion |
| Fine-tuning files at OpenAI | until the training run that used them finishes, and in any case on the owner's withdrawal | the run's end (the poll), or a withdrawal (the sweep) |
| A coach's answer given for §4a (V4 "Pick the moment for feedback", "Which sounds surer", the blind block pick) and the preference pair it stores | with the recording: deleted with the source Take, never after it; and when the speaker turns the choice off | deletion of the recording, withdrawal, or deletion of the coach's account |
| A trained model, a fitted detector, the learned exercise order | until replaced or retired; they hold no copy of a speaker's text or measurements (tested for text, section 3) | replacement, or a failed regurgitation check (the model is then not used, and is retrained without the withdrawn text) |
| Evaluation reports and the golden set | as v1.4 has them for job evidence and product records; a golden-set row naming an owner is deleted with that owner's erasure (the set is then refused until re-sealed) | erasure of the owner; replacement of the report |
| An imported corpus recording (Privacy §4c), its transcript, measurements and coaches' answers on it | while WillpowerLab holds the right to use the recording; deleted when that right ends, or on the speaking person's request or objection | the right ending, a request or objection, or the founder's deletion |
| The record of the training choice | six years after the speaker turns it off or deletes the account (v1.1, unchanged; counsel question 7 open) | turning it off, or account deletion |

## 2. Additions to the rules to seed (proposals; engineering confirms each name against the purge registry before seeding)

| `rule_code` | `evidence_category` | `retention_until_rule` | What it covers |
|---|---|---|---|
| `training_corpus` | `training_corpus` | `training_consent_withdrawn_or_account_erased` | unchanged from v1.1; now also the coach-word pairs once doors 2 to 4 carry them |
| `learning-coach-answers-v1` | `learning_coach_answers` | `deleted_with_source_recording_or_on_withdrawal` | the V4 coach sheet answers and preference pairs (migration 0453's tables) and the blind block pick, keyed to the Take, the speaker and the coach |
| `learned-artifacts-v1` | `learned_artifacts` | `until_replaced` | fine-tuned model ids, fitted detector weights, learned exercise rates; no personal data by design; listed so the erasure inventory can say why they stay |
| `corpus-import-v1` | `corpus_import` | `while_rights_held_or_on_request` | training-import sessions, their audio objects, transcripts, measurements and coach answers (the N58 lane) |

`deleted_with_source_recording_or_on_withdrawal`, `until_replaced` and
`while_rights_held_or_on_request` are new rule shapes; if the purge code has
no such rule, the row is seeded only with the code that enforces it, as v1.4's
two rules waited for 0424 and 0425.

## 3. What counsel is asked to check

1. Whether "while we hold the right to use it" is a period (counsel said of
   "as long as it is useful" on 2026-10-01 that it is not). If not, a fixed
   number for imported recordings: engineering suggests the shorter of the
   licence's end and three years after import, for the founder to name.
2. Whether keeping a model trained on a withdrawn speaker's text, after the
   regurgitation check passes, needs a period of its own.
