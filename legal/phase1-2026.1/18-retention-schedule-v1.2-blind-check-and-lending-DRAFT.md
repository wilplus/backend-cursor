# Retention schedule v1.2 — the blind-check row and the lending rows (for the founder's signature)

    artifact_kind:       retention_schedule
    version:             1.2 — supersedes 1.1 (never signed) and 1.0 (signed 2026-09-19); never edited in place, see 04 §5
    approving_authority: Artur Willoński (founder and controller)
    approved_at:         2026-10-02 (the day of the PAdES signature; the document records a date, not a time)
    object_key:          phase1-2026.1/legal/retention-schedule-v1.2.pdf
    sha256:              [[computed from the signed PDF at registration time]]
    control_version:     phase1-retention-schedule-v1.2
    author:              Artur Willoński, founder and controller; not reviewed by outside counsel

**STATUS: APPROVED BY THE CONTROLLER 2 October 2026; signed as a PDF by the controller's own act on this rendered file.** The founder
signed the wording records that carry these rows the same day
(`15-coach-blind-check-privacy-line-and-balancing-test-SIGNED-2026-10-02.md`
§3 and `16-share-switch-wording-SIGNED-2026-10-02.md` §3, in chat: "I sign it
all"). v1.2 is **v1.0 unchanged, plus v1.1's two training rows, plus the three
rows below.** Every period, rule and open point in
`06-retention-schedule-v1.0-DRAFT.md` carries over word for word, including §3
(the `financial-evidence-v1` placeholder) and §3b; so do v1.1's two rows from
`11-retention-schedule-v1.1-training-DRAFT.md`, whose six-year figure stands as
the founder's own (counsel asked on 2026-10-01 for a fixed period and the
founder adopted six years; the founder stated on 2026-10-02 that counsel has
answered everything put to it).

**Why a v1.2 and not a seeded v1.1.** `data_retention_rules.legal_artifact_id`
is `NOT NULL` and references a signed schedule. v1.1 was drafted for counsel's
check and never signed, so no row in the database points at it. One signature
on v1.2 covers all five new rows at once; v1.1 is superseded without ever
having been registered, which `04-policy-registration-DRAFT.md` §5 allows
(only a *registered* version is immutable).

**Signing v1.2 switches nothing on.** It gives the database the rules the
three gates it serves need before they flip (`ERROR_PRESENCE_AUDIT_ENABLED`,
`PEER_LANE_ENABLED`, `DELAYED_MEASURE_ENABLED`; each its own reviewed PR, after
Privacy 3.3 and Terms 3.3 are active and re-accepted).

---

## 1. Additions to the published schedule (v1.0 §1, after v1.1 §1)

| Category | Period | Trigger |
|---|---|---|
| A coach's blind-check answer (Yes, No, Can't tell) about one clip and one speaking pattern | with the recording — deleted with the source recording's Take, never after it | deletion of the recording, or of the coach's account |
| The lending switch for a recording (on, off, when) | with the recording's Take | deletion of the recording |
| A listener's answer about another user's clip, and a listener's vote in the delayed measure | until the listener deletes their account | account deletion (Q5) |

The first row is the rule v1.0 §1 already states for everything taken from a
recording: "Voice measurements are never outlived by their source." Privacy
3.3 §7 says each of the three in the user's words (the sentences signed in
`15-…` §1 and `16-…` §1).

## 2. Additions to the rules to seed (v1.0 §2, after v1.1 §2)

| `rule_code` | `evidence_category` | `retention_until_rule` | What it covers |
|---|---|---|---|
| `coach-audit-answers-v1` | `coach_audit_answers` | `deleted_with_source_recording` | `error_presence_audit` rows; keyed to the Take and to the coach in `services/data_purge_registry.py` |
| `voice-album-shares-v1` | `share_switch` | `deleted_with_source_recording` | `voice_album_shares`; keyed to the Take in `services/data_purge_registry.py` |
| `listener-answers-v1` | `listener_answers` | `account_erased` | `lend_your_ear_answers`, `delayed_measure_votes`; keyed to the listener's principal, account level in `services/data_purge_project_scope.py` |

**These three rows are proof, not exceptions.** All three tables carry the
`delete` disposition in the purge registry: an erasure deletes them and no
rule is consulted (v1.0 §2 explains the split). The rows exist so that the
period each table lives under is a signed one, as `training_corpus` is for
training copies (v1.1 §2), and so that a later change of disposition cannot
happen without a signed rule to point at. They are seeded active.

v1.1's two rows (`training_corpus`, `consent-evidence-v1`) are seeded with
them, by the same script, as v1.1 §2 describes them: `training_corpus` is the
exact name the database checks (migration 0375); `consent-evidence-v1` becomes
the erasure exception for the two consent tables only when the registry change
v1.1 §2 names is made, which is engineering's and not this document's.

## 3. How the rows reach the database

`scripts/phase1_retention_rules_v1_2.sql`, run by hand once, in order: it
registers this document under `(retention_schedule, 1.2)` by the signed PDF's
`object_key` and `sha256` (both read from `SIGNED-ARTIFACTS.md` after the
upload), then inserts the five rows with `ON CONFLICT (rule_code) DO NOTHING`.
It refuses to run while the hash placeholder is still in the file. Nothing in
it is a migration.

## 4. Signature

By signing, the approving authority adopts v1.0 unchanged together with v1.1's
additions and the additions in §1 and §2 above, and acknowledges that v1.0 §3
and §3b remain open.

    Name:      Artur Willoński
    Firm:      None — natural person, no company (działalność nieewidencjonowana)
    Date:      2 October 2026
    Reference: WILLAB-PHASE1-2026.1-RET-v1.2
