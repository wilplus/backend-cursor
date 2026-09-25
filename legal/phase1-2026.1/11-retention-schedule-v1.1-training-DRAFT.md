# Retention schedule v1.1 — the training rows (DRAFT: counsel checks, founder signs)

    artifact_kind:       retention_schedule
    version:             1.1
    approving_authority: Artur Willoński (founder and controller)
    approved_at:         [[at signature]]
    object_key:          phase1-2026.1/legal/retention-schedule-v1.1.pdf
    sha256:              [[computed from the signed PDF at registration time]]
    control_version:     phase1-retention-schedule-v1.1

**STATUS: DRAFT.** Prepared by engineering at the founder's request
(SPEC-DECISIONS-LOG §N11, answer 6: "I prepare it with the training and yes/no
rows; the lawyer checks; you sign"). v1.1 is **v1.0 unchanged plus the rows
below**. Every period, rule and open point in
`06-retention-schedule-v1.0-DRAFT.md` carries over word for word, including §3
(the `financial-evidence-v1` placeholder) and §3b (the two categories awaiting
confirmation).

**Signing v1.1 does not switch anything on.** It gives the database the rules
it needs; the rules are seeded inactive. Training copies need three further
reviewed changes before one is kept (P5 packet §4, items 4, 6 and 11), and
training itself stays off until the trainer is named (§N11 answer 3).

**It also unblocks account erasure for everyone.** v1.0 is signed but not yet
uploaded or seeded, so production holds no active retention rule and every real
erasure stops at `review_required` (§N9). Uploading this document, or v1.0 on
its own, is what lets an erasure finish.

---

## 1. Additions to the published schedule (v1.0 §1)

| Category | Period | Trigger |
|---|---|---|
| Training copies (only if you turned on **Help improve WillpowerLab**) | until you turn it off or delete your account | turning it off, or account deletion |
| The record of your training choice | as long as it is useful for training our models | — |

A project deletion does not end the first period while the switch is on. The
founder signed that wording on 2026-09-26 (§N10).

## 2. Additions to the rules to seed (v1.0 §2)

| `rule_code` | `evidence_category` | `retention_until_rule` | What it covers |
|---|---|---|---|
| `training_corpus` | `training_corpus` | `training_consent_withdrawn_or_account_erased` | Training copies: `training_corpus_items` and their audio under `training-corpus/` |
| `consent-evidence-v1` | `consent_evidence` | `useful_for_training` | The yes and no records: `ml_consent_events`, `ml_consent_snapshots` |

**`training_corpus` is the exact name the database checks** (migration 0375,
`record_training_corpus_item_v1`). A rule under any other name leaves the
database refusing every copy, so the name must not change at registration.

**These two rules do different jobs.**

- `training_corpus` is not an erasure exception. Account erasure always deletes
  training copies (the registry marks them `delete`). The rule is the proof
  that a copy has a signed period at all: without an active rule the database
  refuses to keep one.
- `consent-evidence-v1` *is* an erasure exception. Today the two consent tables
  are marked `external_review` and no rule is consulted, so an erasure of anyone
  who ever answered the training switch stops for a person to check. Once this
  rule is signed, one registry change moves them to `retain` under
  `consent_evidence`, and the erasure finishes on its own. That change is
  engineering's, not this document's (P5 packet §4, item 9).

## 3. What counsel is asked to check

1. **The consent-record period.** The founder chose "as long as it is useful
   for training our models" (§N11 answer 1). No date or event ends it, so no
   job can enforce it; a person decides. Engineering offered "while any model
   trained on the person's data is in use" as a period the system could check;
   the founder chose counsel's wording. Is it specific enough under Art. 5(1)(e),
   and does the published schedule need a review date?
2. **What the consent records hold.** Identifiers, timestamps, the policy
   version, the hash of the switch wording and the control used. No audio, no
   words spoken. Is keeping them after erasure justified as accountability
   evidence (Art. 5(2), 7(1), 17(3)(e)), or is "useful for training" a
   different purpose that needs its own basis?
3. **The training-copies period** has no fixed maximum (counsel's §N10 answer 4
   confirms this).

## 4. Signature

By signing, the approving authority adopts v1.0 unchanged together with the
additions in §1 and §2, and acknowledges that v1.0 §3 and §3b remain open.

    Name:      Artur Willoński
    Firm:      None — natural person, no company (działalność nieewidencjonowana)
    Date:      [[at signature]]
    Reference: WILLAB-PHASE1-2026.1-RET-v1.1
