# PHASE A0 — Findings

_Generated 2026-05-16T21:25:51.017434+00:00 by `scripts/phase_a0_diagnostics.py`. Read-only diagnostic. No production code written._

> **This is the gate before any A1–A4 phase starts.** Read the verdicts at the bottom; the counts above are provenance, not policy.

## A0.1 — Has fine-tuning ever run?

- **Promoted:** `False`
- **Reason:** runtime_config row absent

→ **No fine-tune has ever been promoted; even the admin copilot is running stock `gpt-4o-mini`.**

## A0.2 — In-context (few-shot) learning loop health

### Totals

- `charisma_snippets.follow_up_outcome` non-null (legacy): **3**
- `coaching_attempts` total rows (canonical): **7**

### Eligible-for-few-shot per skill

- `stress`: **6** eligible attempts
- `unknown`: **1** eligible attempts

### Eligible-for-few-shot per skill × tenant

- skill `stress`:
  - tenant `(no_company_id)`: **6** eligible attempts
- skill `unknown`:
  - tenant `(no_company_id)`: **1** eligible attempts

### Pitfall-#10 — starvation set (the A1 backfill target)

- **0 sessions** have admin_comment set on at least one snippet AND results_published_at IS NULL.
- Each of these sessions' admin edits are invisible to admin_annotation_events today; they will land there once the A1 backfill cron runs.

## A0.3 — admin_annotation_events: field × chip breakdown

- _(no rows in admin_annotation_events — annotation capture has never fired)_

## A0.4 — Verdicts (gate the next phases)

### Fine-tune corpus viability

NOT VIABLE — no admin_annotation_events rows at all (table empty). Fine-tuning is impossible until publish-time annotation capture has been firing for at least a few weeks of active admin review.

### Few-shot loop status

Per-skill few-shot loop state: stress=starved (6), unknown=starved (1)

  - stress: 6 eligible attempts → **starved** (thresholds: ≥50 healthy, ≥10 partial, below = starved)
  - unknown: 1 eligible attempts → **starved** (thresholds: ≥50 healthy, ≥10 partial, below = starved)
  - pitfall-#10 starvation set (reviewed-but-unpublished sessions): **0 sessions** have admin_comment but no publish stamp. These are the corpus the A1 backfill cron will recover into admin_annotation_events.

### Tenant viability (for shared-vs-per-tenant model decision)

NOT APPLICABLE — no NULL-chip rows in admin_annotation_events to attribute to any tenant. Per-tenant viability is undecidable until the global corpus is non-zero.

---

## Next steps (per Phase A spec build-order)

1. **Always:** A1 (few-shot backfill cron) — ships regardless of the verdict above; it's the only phase that improves Track A (the user-facing AI).
2. **If fine-tune viability = VIABLE:** A3 (fine-tune pipeline) may proceed for the channel that cleared the floor — per the spec's settled decisions (1–7 in A3.1). Promote stays human-gated regardless (A3.4); the volumetric retrain trigger (A3.2a) reads the FLOOR from this document's channel counts.
3. **If fine-tune viability = NOT YET VIABLE:** **Do not build A3.** Re-run this diagnostic after the A1 backfill cron has been firing for ≥ 1 week and re-evaluate.

**Thresholds used in this report** (documented so a human can audit the verdicts):
- Fine-tune viability floor per channel: `200` clean pairs
- Tenant-isolation viability floor per (tenant, channel): `500` clean pairs
- Few-shot healthy/partial/starved per skill: `50` / `10` / below

These are DIAGNOSTIC thresholds for the verdicts in this report — they are NOT the auto-promote thresholds the spec (A3.4) forbids, which remain unwritten by design.

