# Retention schedule v1.3 — the financial-records row (for the founder's signature)

    artifact_kind:       retention_schedule
    version:             1.3 — supersedes 1.2 (signed 2026-10-02); never edited in place, see 04 §5
    approving_authority: Artur Willoński (founder and controller)
    approved_at:         2026-10-05 (the day the controller decided the period; the document records a date, not a time)
    object_key:          phase1-2026.1/legal/retention-schedule-v1.3.pdf
    sha256:              [[computed from the signed PDF at registration time]]
    control_version:     phase1-retention-schedule-v1.3
    author:              Artur Willoński, founder and controller; not reviewed by outside counsel

**STATUS: DRAFT, for the controller's signature.** The controller decided the
period on 5 October 2026, in chat: financial records are "kept for 5 years".
v1.3 is **v1.2 unchanged, plus the one row below.** Every period, rule and
open point in `06-retention-schedule-v1.0-DRAFT.md`, in v1.1's two rows
(`11-…`) and in v1.2's three rows (`18-…`) carries over word for word, except
that v1.0 §3 is now answered.

**Why now.** v1.0 §3 left `financial_evidence` open, and the purge is
all-or-nothing: with that one category unresolved, erasing an account that
has any token or AI-usage row deletes nothing at all. The same day the
controller decided that purchases are one-time packages (contract §8), so the
product takes payment and the token ledger records each sale.

---

## 1. Addition to the published schedule (v1.0 §1, after v1.2 §1)

| Category | Period | Trigger |
|---|---|---|
| Records of what you bought and how your tokens were used | 5 years from the end of the financial year in which the record was made | the end of that financial year |

Everything else about the account (recordings, transcripts, the Ideal Text,
feedback) is deleted when the account is deleted, as v1.0 §1 says. Only these
records stay, and only for this period.

## 2. Addition to the rules to seed (v1.0 §2, after v1.2 §2)

| `rule_code` | `evidence_category` | `retention_until_rule` | What it covers |
|---|---|---|---|
| `financial-evidence-v1` | `financial_evidence` | `financial_year_end_plus_5_years` | `token_ledger`, `llm_usage`; disposition `retain` in `services/data_purge_registry.py` |

This answers v1.0 §3 with its option 2, a bounded period, at five years, the
period v1.0 §3 names for accounting records in Poland (*ustawa o
rachunkowości*, art. 74). The controller adopts it as his own determination;
counsel may still confirm whether the art. 74 period applies to a seller
operating as *działalność nieewidencjonowana*, and whether `llm_usage`, which
is a cost record rather than a sale, should instead be detached (option 1).
Either answer would be a v1.4, not an edit of this one.

**What the row does and does not do.** Seeded active, it lets an account
erasure complete: every other row of the account is deleted, and these two
tables' rows are kept and marked with this rule. **Nothing yet deletes them
when the five years end.** The scheduled clean-up that enforces periods (audio
at 12 months, logs at 90 days, these at five years) is a separate piece of
work that the controller approves before its first real run.

## 3. How the row reaches the database

`scripts/phase1_retention_rules_v1_3.sql`, run by hand once: it registers this
document under `(retention_schedule, 1.3)` by the signed PDF's `object_key`
and `sha256` (both read from `SIGNED-ARTIFACTS.md` after the upload), then
inserts the one row with `ON CONFLICT (rule_code) DO NOTHING`. It refuses to
run while the hash or date placeholder is still in the file. Nothing in it is
a migration.

## 4. Signature

By signing, the approving authority adopts v1.2 unchanged together with the
additions in §1 and §2 above, and records v1.0 §3 as answered by them.

    Name:      Artur Willoński
    Firm:      None — natural person, no company (działalność nieewidencjonowana)
    Date:      5 October 2026
    Reference: WILLAB-PHASE1-2026.1-RET-v1.3
