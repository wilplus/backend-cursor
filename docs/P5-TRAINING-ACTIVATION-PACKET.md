# P5 — switching training on: the packet for counsel and the founder

**Update 2026-09-26:** the founder signed the four wordings in §3 and relayed
counsel's answers to §2; both are recorded in `SPEC-DECISIONS-LOG.md` §N10.
Still open: counsel's drafted policy text, the named training processors, and
the signed retention schedule.

**Update 2026-09-26 (§N11):** the founder answered the eight open questions.
Drafts for counsel: `legal/phase1-2026.1/10-training-policy-changes-DRAFT.md`
(the Privacy Policy changes) and
`legal/phase1-2026.1/11-retention-schedule-v1.1-training-DRAFT.md` (the
training rows). Who trains is not decided, so training stays off.

**Status:** nothing in this document is switched on. P2 (0373), P3 (0375) and
P4 (0376) are built and dark. P5 is the only phase that reaches a user, and it
needs **counsel review** and **founder sign-off** before any line below is
changed. Design: [`SPEC-training-corpus-and-project-purge.md`](SPEC-training-corpus-and-project-purge.md).

`FILTER: ADVANCE-F2 — cat {F2: provenance-safe learning} — fences {AC-9 clear; LIVE LOOP: every user-facing line below is held for founder sign-off} — locks {L3 walls kept} — redirect: n/a`

---

## 1 · What P5 turns on, in one paragraph

A person who re-accepts the new policy version can, on a screen of its own,
turn on a separate "use my recordings to improve WillpowerLab" switch. While
it is on, after each Take we keep separate copies of the Confident Voice
moments they were shown: a short audio cut, its words, and a coach's label if
one exists. Copies survive a project delete only while the switch is on; they
are erased when the person turns it off or deletes their account. Nothing is
trained by P5 itself: training, datasets and model promotion stay behind
their own switches (`MLC2_TRAINING_ENABLED`, `MLC2_DATASET_RELEASES_ENABLED`,
`MLC2_PROMOTION_ENABLED`, all `False`).

## 2 · What counsel is asked to confirm

1. A training-only yes recorded on its own screen, never pre-ticked, never a
   condition of the service, withdrawable on its own, is valid consent under
   Art. 6(1)(a), 4(11) and 7(4).
2. Voice is not biometric data here (counsel's 2026-09-25 advice); training
   grants therefore carry no Art. 9 basis. Is anything a speaker *says* in a
   copied clip a reason to require Art. 9(2)(a)?
3. Copies may outlive a *project* delete while the yes is active (C3), and go
   on withdrawal or account erasure. Retention: "until the training yes is
   withdrawn or the account is erased", no fixed maximum (Q2).
4. After withdrawal: no retraining, stop future use; a model already trained
   is not un-trained (Q3). How must this be described?
5. Bundled-era yeses count for nothing and are never migrated (C2).
6. The new Privacy Policy text and the retention schedule row ("Training
   copies") — drafts to be supplied with the policy version.
7. The DPIA update: this design replaces the bundled-consent finding (#651).
8. Who trains, where: processors and transfers for any future training run
   (not part of P5, but the notice has to be honest about it).

## 3 · What the founder signs off (user-facing copy, LIVE LOOP)

- **The training switch**: its label and its one sentence. The exact text's
  SHA-256 becomes `approved_copy_sha256` of the training policy, and the
  database refuses a yes recorded against any other text.
- **The honest delete copy** for a person with an active yes (SPEC §1):
  *"Your project will be deleted. Recordings you shared for training stay
  until you withdraw that permission."*
- **The withdrawal confirmation** on the switch ("Turn off? Your training
  copies will be deleted.") — to be drafted.
- **The new policy version's text**, which every user re-accepts (C1).

## 4 · The engineering checklist, in order

Each item is a reviewed code change; none is a dashboard toggle.

1. **Make the `_v1` consent readers bundled-only** before a training policy
   exists. Today they assume one active policy of one kind:
   `get_mlc2_principal_consent_status_v1` raises when more than one policy is
   active, `configure_mlc2_consent_policy_v1` refuses while any other policy
   is active, and the MLC-2 canary readiness counts every policy. Each must
   filter `grant_scope = 'bundled_v1'`.
2. **The receipt writer refuses the training purpose.** When the processing
   policy starts naming training, `accept_phase1_processing_authorization_v2`
   must refuse `pooled_model_improvement` as a chosen optional purpose (SPEC
   §3.6, invariant 8). It is a D11 writer (0366): re-issue it with the
   preamble re-injected, as 0376 does for the object mark.
3. **Lift `PHASE2_PURPOSE_FORBIDDEN` for this one purpose only**, in the
   policy registry, with the new processing policy version.
4. **Register the training policy**: `configure_mlc2_training_consent_policy_v1`
   with the signed switch copy, its hash, the approval evidence, and the new
   processing policy version as `requires_processing_policy_version`.
5. **Seed the `training_corpus` retention rule** (active) with the new
   retention schedule artifact. Until it exists the database refuses every
   copy.
6. **Build the switch**: a route that records the yes
   (`record_mlc2_training_consent_grant_v2`, control `training_toggle`) and the
   withdrawal (`record_mlc2_consent_withdrawal_v2`), and then calls
   `services.training_corpus.enqueue_corpus_purge`; its own screen on Data &
   consent.
7. **A sweep for due copies**: add `purge_due_copies` for every principal with
   `purge_pending` copies to the worker's sweep chain, so an erasure never
   waits on a lost queue message.
8. **Coach labels that arrive after the copy ran**: copy them from the coach
   label write, or a sweep.
9. **Account erasure of a training-consented person** currently stops at
   `review_required` on the MLC-2 consent events (`external_review`), never on
   the corpus. Decide their disposition (likely retained as consent evidence
   under a rule) so the erasure can finish on its own.
10. **Project delete keeps copies** only with an active yes
    (`retain_while_training_consented`): lands with the project-scoped purge
    (P1), which does not exist yet.
11. **Flip `Config.MLC2_TRAINING_CORPUS_COPY_ENABLED = True`**, last, in its
    own reviewed change.

## 5 · What is already true (built, tested, dark)

| Piece | Where | Tested by |
|---|---|---|
| Training-only yes, its own act, needs the re-accepted policy | 0373 | `tests/test_training_consent_postgres.py` |
| Bundled-era yes never counts | 0373 reader | same |
| Withdrawal touches only the training purpose | 0373 | same |
| Copies are copies: no FK to product rows | 0375 | `tests/test_training_corpus_postgres.py` |
| A copy needs an active yes and an active rule, re-checked in the write | 0375 | same |
| Copy job: shown moments only, bytes removed if the copy is refused | `services/training_corpus.py` | `tests/test_training_corpus.py` |
| Withdrawal makes every copy due; erasure never takes an active one | 0376 | `tests/test_training_corpus_purge_postgres.py` |
| Account erasure reaches the copies' audio and rows | 0376 + registry | same |
