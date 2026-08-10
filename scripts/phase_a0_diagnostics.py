#!/usr/bin/env python3
"""Phase A0 — diagnostics for the learning-system spec (BLOCKING).

Read-only audit of:
  A0.1 — runtime_config.openai_copilot_model (has any fine-tune ever
         been promoted?)
  A0.2 — few-shot eligibility loop health (per skill, per tenant) +
         the pitfall-#10 starvation set (reviewed-but-unpublished
         sessions whose admin edits never reached
         admin_annotation_events)
  A0.3 — admin_annotation_events capture volume by field_name ×
         reason_chip (NULL chip = training-useful diff signal)
  A0.4 — verdicts that gate whether A3 (fine-tune pipeline) is even
         worth running

Writes NOTHING to the database. Emits PHASE-A0-FINDINGS.md (default at
the repo root) for a human to read BEFORE any A1+ phase starts.

Usage:
    python3 scripts/phase_a0_diagnostics.py
    python3 scripts/phase_a0_diagnostics.py --out PHASE-A0-FINDINGS.md
    python3 scripts/phase_a0_diagnostics.py --sql-only

``--sql-only`` skips the live runtime and prints the SQL each section
runs, in case you prefer pasting into the Supabase SQL editor and
filling the findings manually. Useful when this script's environment
can't reach Supabase.

Why a script and not a SQL file: the verdicts (A0.4) are conditional
on the counts and want plain-English rendering. Easier in Python.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from services.snippet_tables import SNIPPETS_TABLE

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ── Sanity threshold for the fine-tune-viability verdict ────────────
#
# The Phase A spec phrases the floor as "a few hundred clean pairs"
# for a single channel to be plausibly fine-tunable. Below this, the
# expected eval delta from a fresh fine-tune is below the judge's
# typical noise floor on a small held-out set, so the run is theatre
# not learning. 200 is the explicit interpretation of "a few hundred"
# used by this audit; documented as such in the report.
#
# This is a DIAGNOSTIC floor for a human-readable verdict only — it
# is NOT a hardcoded auto-promote threshold (which the spec forbids
# in A3.4). The two concerns are different: this answers "is the
# corpus big enough to bother training?", not "is this candidate
# safe to promote?".
_VIABILITY_FLOOR = 200

# Per-tenant viability check uses a slightly higher floor — tenant-
# scoped corpora need to overshoot the global floor by enough margin
# that the resulting model isn't just the global average with extra
# variance.
_TENANT_VIABILITY_FLOOR = 500

# Few-shot pool sizes we read as "healthy" vs "partial" vs "starved".
# These mirror the in-context retrieval cap on a typical chat turn —
# a healthy pool means the retrieval window is exercised every
# request, partial means it's exercising on most calls, starved
# means the model is running on prompt without retrieval support.
_FEW_SHOT_HEALTHY_PER_SKILL = 50
_FEW_SHOT_PARTIAL_PER_SKILL = 10


# ── SQL the script runs (also what --sql-only prints) ──────────────
#
# Kept as named constants so the --sql-only fallback prints the same
# queries the live runtime executes.

SQL_A01_RUNTIME_CONFIG = """
-- A0.1 — has any fine-tune ever been promoted?
SELECT key, value, updated_at, updated_by
FROM   runtime_config
WHERE  key = 'openai_copilot_model';
""".strip()

SQL_A02_1_FOLLOW_UP_OUTCOMES_LEGACY = """
-- A0.2.1 — count snippets with the LEGACY follow_up_outcome JSONB set.
-- Canonical replacement is coaching_attempts; both counts reported
-- so we can see the migration tail.
SELECT COUNT(*) AS legacy_follow_up_outcome_count
FROM   charisma_snippets
WHERE  follow_up_outcome IS NOT NULL;
""".strip()

SQL_A02_1_COACHING_ATTEMPTS = """
-- A0.2.1 (canonical) — total coaching_attempts rows.
SELECT COUNT(*) AS coaching_attempts_count
FROM   coaching_attempts;
""".strip()

SQL_A02_2_ELIGIBLE_PER_SKILL = """
-- A0.2.2 + A0.2.3 — eligible-for-few-shot count per skill (charisma
-- / stress). Canonical source = coaching_attempts.is_eligible_for_few_shot.
SELECT skill_id, COUNT(*) AS eligible_count
FROM   coaching_attempts
WHERE  is_eligible_for_few_shot = TRUE
GROUP  BY skill_id
ORDER  BY skill_id;
""".strip()

SQL_A02_3_ELIGIBLE_PER_TENANT = """
-- A0.2.3 — eligible-for-few-shot pool broken down by skill × tenant.
-- Tenant = user_settings.company_id; NULL/unset company_id = solo
-- (un-tenanted) users — they share the global retrieval pool.
SELECT us.company_id AS tenant,
       ca.skill_id,
       COUNT(*)      AS eligible_count
FROM   coaching_attempts ca
JOIN   user_settings    us ON us.user_id = ca.user_id
WHERE  ca.is_eligible_for_few_shot = TRUE
GROUP  BY us.company_id, ca.skill_id
ORDER  BY eligible_count DESC;
""".strip()

SQL_A02_4_PITFALL10_STARVATION = """
-- A0.2.4 — pitfall-#10 starvation set: sessions where the admin
-- typed admin_comment on at least one snippet BUT the session was
-- never published, so record_snippet_publish_annotations() never
-- fired and the admin's edits never reached admin_annotation_events.
--
-- This is the corpus A1's backfill cron will recover.
SELECT COUNT(DISTINCT v.id) AS unpublished_but_reviewed_sessions
FROM   v2_sessions     v
JOIN   charisma_snippets cs ON cs.session_id = v.id
WHERE  v.results_published_at IS NULL
  AND  cs.admin_comment IS NOT NULL
  AND  TRIM(cs.admin_comment) <> '';
""".strip()

SQL_A03_FIELD_CHIP_BREAKDOWN = """
-- A0.3 — admin_annotation_events grouped by field_name × reason_chip.
-- The NULL-chip count per field_name is the actual usable fine-tune
-- corpus size for that channel (admin DIFFED the AI draft).
-- approved_as_is rows are positive-acceptance signal, not training
-- pairs.
SELECT field_name,
       COALESCE(reason_chip, 'NULL') AS chip,
       COUNT(*)                      AS row_count
FROM   admin_annotation_events
GROUP  BY field_name, chip
ORDER  BY field_name, chip;
""".strip()

SQL_A04_TENANT_VIABILITY = """
-- A0.4 — per-tenant clean-pair (NULL-chip) corpus size per channel.
-- The spec asks: does any single tenant have enough clean pairs to
-- fine-tune in isolation? Almost certainly no — this query confirms
-- with a number rather than a guess.
SELECT us.company_id AS tenant,
       e.field_name,
       COUNT(*)      AS null_chip_pairs
FROM   admin_annotation_events e
JOIN   user_settings           us ON us.user_id = e.user_id
WHERE  e.reason_chip IS NULL
GROUP  BY us.company_id, e.field_name
HAVING COUNT(*) > 0
ORDER  BY null_chip_pairs DESC;
""".strip()


# ── Live-runtime path (uses existing Supabase client) ───────────────


def _section_a01(db) -> dict:
    """Has any fine-tune ever been promoted?"""
    try:
        result = (
            db.client.table("runtime_config")
            .select("key, value, updated_at, updated_by")
            .eq("key", "openai_copilot_model")
            .limit(1)
            .execute()
        )
        rows = result.data or []
    except Exception as e:
        return {"error": str(e), "rows": []}

    if not rows:
        return {
            "promoted": False,
            "reason": "runtime_config row absent",
            "value": None,
            "updated_at": None,
        }
    row = rows[0]
    value = (row.get("value") or "").strip()
    if not value:
        return {
            "promoted": False,
            "reason": "row present but value is empty",
            "value": value or None,
            "updated_at": row.get("updated_at"),
        }
    if not value.startswith("ft:"):
        return {
            "promoted": False,
            "reason": (
                "row present and non-empty but value is not prefixed "
                "'ft:' — admin copilot is running stock model"
            ),
            "value": value,
            "updated_at": row.get("updated_at"),
        }
    return {
        "promoted": True,
        "reason": "fine-tune model present",
        "value": value,
        "updated_at": row.get("updated_at"),
    }


def _section_a02(db) -> dict:
    """Few-shot loop health + pitfall-#10 starvation count."""
    out: dict = {}

    # A0.2.1 — legacy + canonical totals
    try:
        legacy = (
            db.client.table(SNIPPETS_TABLE)
            .select("id", count="exact")
            .not_.is_("follow_up_outcome", "null")
            .limit(1)
            .execute()
        )
        out["legacy_follow_up_outcome_count"] = legacy.count
    except Exception as e:
        out["legacy_follow_up_outcome_count"] = None
        out["legacy_error"] = str(e)

    try:
        attempts = (
            db.client.table("coaching_attempts")
            .select("id", count="exact")
            .limit(1)
            .execute()
        )
        out["coaching_attempts_count"] = attempts.count
    except Exception as e:
        out["coaching_attempts_count"] = None
        out["attempts_error"] = str(e)

    # A0.2.2 + A0.2.3 — eligible per skill (and per skill × tenant)
    # PostgREST has no GROUP BY, so pull the eligible rows + aggregate.
    # Cap the pull to keep memory bounded — eligibility pool is small.
    out["eligible_per_skill"] = {}
    out["eligible_per_skill_tenant"] = {}
    try:
        eligible_attempts = (
            db.client.table("coaching_attempts")
            .select("id, skill_id, user_id")
            .eq("is_eligible_for_few_shot", True)
            .limit(20000)
            .execute()
            .data
        ) or []
        per_skill = Counter()
        user_ids = set()
        for row in eligible_attempts:
            per_skill[(row.get("skill_id") or "unknown")] += 1
            if row.get("user_id"):
                user_ids.add(row["user_id"])
        out["eligible_per_skill"] = dict(per_skill)

        # Tenant join via user_settings
        if user_ids:
            user_id_list = list(user_ids)
            # Supabase has an upper bound on .in_ payloads; chunk.
            chunk_size = 200
            user_to_tenant: dict[str, str | None] = {}
            for i in range(0, len(user_id_list), chunk_size):
                chunk = user_id_list[i : i + chunk_size]
                try:
                    settings_rows = (
                        db.client.table("user_settings")
                        .select("user_id, company_id")
                        .in_("user_id", chunk)
                        .execute()
                        .data
                    ) or []
                    for s in settings_rows:
                        user_to_tenant[s["user_id"]] = s.get("company_id")
                except Exception as e:
                    out["tenant_lookup_error"] = str(e)
                    break

            per_skill_tenant: dict[str, Counter] = defaultdict(Counter)
            for row in eligible_attempts:
                tenant = user_to_tenant.get(row.get("user_id"))
                tenant_key = tenant or "(no_company_id)"
                skill = row.get("skill_id") or "unknown"
                per_skill_tenant[skill][tenant_key] += 1
            out["eligible_per_skill_tenant"] = {
                k: dict(v) for k, v in per_skill_tenant.items()
            }
    except Exception as e:
        out["eligible_per_skill_error"] = str(e)

    # A0.2.4 — pitfall-#10 starvation set
    # Pull unpublished sessions and post-filter by snippet admin_comment
    # presence. Avoids relying on Supabase's nested-relation operators.
    try:
        unpublished_sessions = (
            db.client.table("v2_sessions")
            .select("id")
            .is_("results_published_at", "null")
            .limit(50000)
            .execute()
            .data
        ) or []
        unpublished_ids = [r["id"] for r in unpublished_sessions if r.get("id")]
        starvation_count = 0
        if unpublished_ids:
            chunk_size = 200
            counted_sessions: set[str] = set()
            for i in range(0, len(unpublished_ids), chunk_size):
                chunk = unpublished_ids[i : i + chunk_size]
                snip_rows = (
                    db.client.table(SNIPPETS_TABLE)
                    .select("session_id, admin_comment")
                    .in_("session_id", chunk)
                    .not_.is_("admin_comment", "null")
                    .execute()
                    .data
                ) or []
                for r in snip_rows:
                    sid = r.get("session_id")
                    if sid and (r.get("admin_comment") or "").strip():
                        counted_sessions.add(sid)
            starvation_count = len(counted_sessions)
        out["pitfall10_starvation_sessions"] = starvation_count
    except Exception as e:
        out["pitfall10_starvation_sessions"] = None
        out["pitfall10_error"] = str(e)

    return out


def _section_a03(db) -> dict:
    """admin_annotation_events grouped by field_name × reason_chip."""
    out: dict = {"by_field_chip": {}}
    try:
        # Pull all rows + group in Python (PostgREST has no GROUP BY).
        # The events table is bounded in size — full scan is fine.
        rows = (
            db.client.table("admin_annotation_events")
            .select("field_name, reason_chip")
            .limit(100000)
            .execute()
            .data
        ) or []
        per_field: dict[str, Counter] = defaultdict(Counter)
        for r in rows:
            field = r.get("field_name") or "(unknown)"
            chip = r.get("reason_chip")
            chip_key = chip if chip is not None else "NULL"
            per_field[field][chip_key] += 1
        out["by_field_chip"] = {
            k: dict(v) for k, v in per_field.items()
        }
        out["total_rows"] = len(rows)
    except Exception as e:
        out["error"] = str(e)
    return out


def _section_a04_tenant(db) -> dict:
    """Per-tenant clean-pair (NULL-chip) corpus per channel."""
    out: dict = {"per_tenant_field": {}}
    try:
        rows = (
            db.client.table("admin_annotation_events")
            .select("field_name, user_id, reason_chip")
            .is_("reason_chip", "null")
            .limit(100000)
            .execute()
            .data
        ) or []
        if not rows:
            return out

        user_ids = {r["user_id"] for r in rows if r.get("user_id")}
        user_to_tenant: dict[str, str | None] = {}
        chunk_size = 200
        user_id_list = list(user_ids)
        for i in range(0, len(user_id_list), chunk_size):
            chunk = user_id_list[i : i + chunk_size]
            try:
                settings_rows = (
                    db.client.table("user_settings")
                    .select("user_id, company_id")
                    .in_("user_id", chunk)
                    .execute()
                    .data
                ) or []
                for s in settings_rows:
                    user_to_tenant[s["user_id"]] = s.get("company_id")
            except Exception as e:
                out["tenant_lookup_error"] = str(e)
                break

        per_tenant_field: dict[str, Counter] = defaultdict(Counter)
        for r in rows:
            tenant = user_to_tenant.get(r.get("user_id"))
            tenant_key = tenant or "(no_company_id)"
            field = r.get("field_name") or "(unknown)"
            per_tenant_field[tenant_key][field] += 1
        out["per_tenant_field"] = {
            k: dict(v) for k, v in per_tenant_field.items()
        }
    except Exception as e:
        out["error"] = str(e)
    return out


# ── Verdict logic + report rendering ────────────────────────────────


def _verdict_fine_tune_viability(field_chip: dict) -> tuple[str, list[str]]:
    """Compute the A0.4 fine-tune-viability verdict.

    Reads NULL-chip counts per field (= clean diff pairs) and emits a
    plain-English verdict on whether ANY channel has enough corpus to
    justify a fine-tune run.
    """
    lines: list[str] = []
    null_counts: dict[str, int] = {}
    for field, chips in field_chip.items():
        null_counts[field] = chips.get("NULL", 0)

    if not null_counts:
        return (
            "NOT VIABLE — no admin_annotation_events rows at all "
            "(table empty). Fine-tuning is impossible until publish-"
            "time annotation capture has been firing for at least a "
            "few weeks of active admin review.",
            lines,
        )

    best_channel, best_count = max(
        null_counts.items(), key=lambda kv: kv[1]
    )
    for field in sorted(null_counts):
        lines.append(
            f"  - {field}: {null_counts[field]} clean pairs "
            f"(NULL chip = admin diffed the AI draft)"
        )

    if best_count >= _VIABILITY_FLOOR:
        return (
            f"VIABLE — channel `{best_channel}` has {best_count} "
            f"clean pairs (≥ floor {_VIABILITY_FLOOR}). At least one "
            "channel clears the bar to plausibly move the eval needle "
            "past the judge's noise floor. A3 may proceed for this "
            "channel; other channels remain conditional on their own "
            "counts.",
            lines,
        )

    return (
        f"NOT YET VIABLE — best channel is `{best_channel}` with "
        f"{best_count} clean pairs, below the {_VIABILITY_FLOOR} "
        "floor for the 'few hundred' bar in the spec. A fresh fine-"
        "tune on this corpus is theatre, not learning. **Do not "
        "proceed to A3.** Re-run this diagnostic after the A1 "
        "backfill cron has been firing for ≥ 1 week.",
        lines,
    )


def _verdict_few_shot_loop(
    eligible_per_skill: dict, pitfall10_count: int | None,
) -> tuple[str, list[str]]:
    """A0.4 few-shot loop verdict per skill."""
    lines: list[str] = []
    skill_states: list[str] = []
    for skill in sorted(eligible_per_skill):
        n = eligible_per_skill[skill]
        if n >= _FEW_SHOT_HEALTHY_PER_SKILL:
            state = "healthy"
        elif n >= _FEW_SHOT_PARTIAL_PER_SKILL:
            state = "partial"
        else:
            state = "starved"
        skill_states.append(f"{skill}={state} ({n})")
        lines.append(
            f"  - {skill}: {n} eligible attempts → **{state}** "
            f"(thresholds: ≥{_FEW_SHOT_HEALTHY_PER_SKILL} healthy, "
            f"≥{_FEW_SHOT_PARTIAL_PER_SKILL} partial, below = starved)"
        )
    if pitfall10_count is not None:
        lines.append(
            f"  - pitfall-#10 starvation set "
            f"(reviewed-but-unpublished sessions): "
            f"**{pitfall10_count} sessions** have admin_comment "
            "but no publish stamp. These are the corpus the A1 "
            "backfill cron will recover into admin_annotation_events."
        )
    verdict = (
        "Per-skill few-shot loop state: "
        + (", ".join(skill_states) if skill_states else "no eligible attempts at all (loop is fully starved)")
    )
    return verdict, lines


def _verdict_tenant_viability(per_tenant_field: dict) -> tuple[str, list[str]]:
    """A0.4 tenant viability — does any single tenant have enough
    clean pairs to fine-tune in isolation?"""
    lines: list[str] = []
    if not per_tenant_field:
        return (
            "NOT APPLICABLE — no NULL-chip rows in admin_annotation_"
            "events to attribute to any tenant. Per-tenant viability "
            "is undecidable until the global corpus is non-zero.",
            lines,
        )
    any_tenant_viable = False
    for tenant in sorted(per_tenant_field, key=lambda t: t):
        per_field = per_tenant_field[tenant]
        top_field = max(per_field, key=lambda f: per_field[f])
        top_count = per_field[top_field]
        verdict_for_tenant = (
            "VIABLE in isolation"
            if top_count >= _TENANT_VIABILITY_FLOOR
            else "below isolation floor"
        )
        if top_count >= _TENANT_VIABILITY_FLOOR:
            any_tenant_viable = True
        lines.append(
            f"  - tenant `{tenant}`: best channel `{top_field}` = "
            f"{top_count} clean pairs ({verdict_for_tenant} — "
            f"isolation floor {_TENANT_VIABILITY_FLOOR})"
        )
    if any_tenant_viable:
        verdict = (
            "AT LEAST ONE tenant has enough clean pairs to support an "
            "isolated fine-tune. This DOES NOT change the decision-3 "
            "policy (one shared model); it just means the option "
            "exists if a customer-specific tenant later overrides it."
        )
    else:
        verdict = (
            "NO single tenant has enough clean pairs to fine-tune in "
            "isolation. Confirms decision 3 (one shared model, tenant "
            "as in-context signal) — there is no near-term need to "
            "revisit it."
        )
    return verdict, lines


def render_report(
    *,
    a01: dict,
    a02: dict,
    a03: dict,
    a04: dict,
    timestamp: str,
) -> str:
    """Assemble PHASE-A0-FINDINGS.md."""
    fine_tune_verdict, ft_lines = _verdict_fine_tune_viability(
        a03.get("by_field_chip", {})
    )
    few_shot_verdict, fs_lines = _verdict_few_shot_loop(
        a02.get("eligible_per_skill", {}),
        a02.get("pitfall10_starvation_sessions"),
    )
    tenant_verdict, tenant_lines = _verdict_tenant_viability(
        a04.get("per_tenant_field", {})
    )

    parts: list[str] = []
    parts.append("# PHASE A0 — Findings\n")
    parts.append(
        f"_Generated {timestamp} by `scripts/phase_a0_diagnostics.py`. "
        "Read-only diagnostic. No production code written._\n"
    )
    parts.append(
        "> **This is the gate before any A1–A4 phase starts.** "
        "Read the verdicts at the bottom; the counts above are "
        "provenance, not policy.\n"
    )

    # ── A0.1
    parts.append("## A0.1 — Has fine-tuning ever run?\n")
    if a01.get("error"):
        parts.append(f"- ERROR reading runtime_config: `{a01['error']}`\n")
    else:
        parts.append(f"- **Promoted:** `{a01.get('promoted')}`")
        parts.append(f"- **Reason:** {a01.get('reason')}")
        if a01.get("value"):
            parts.append(f"- **Value:** `{a01['value']}`")
        if a01.get("updated_at"):
            parts.append(f"- **Updated at:** `{a01['updated_at']}`")
        parts.append("")
        if not a01.get("promoted"):
            parts.append(
                "→ **No fine-tune has ever been promoted; even the "
                "admin copilot is running stock `gpt-4o-mini`.**\n"
            )

    # ── A0.2
    parts.append("## A0.2 — In-context (few-shot) learning loop health\n")
    parts.append("### Totals\n")
    parts.append(
        f"- `charisma_snippets.follow_up_outcome` non-null (legacy): "
        f"**{a02.get('legacy_follow_up_outcome_count')}**"
    )
    parts.append(
        f"- `coaching_attempts` total rows (canonical): "
        f"**{a02.get('coaching_attempts_count')}**"
    )
    if a02.get("legacy_error"):
        parts.append(f"- _legacy query error: `{a02['legacy_error']}`_")
    if a02.get("attempts_error"):
        parts.append(f"- _attempts query error: `{a02['attempts_error']}`_")
    parts.append("")

    parts.append("### Eligible-for-few-shot per skill\n")
    skill_counts = a02.get("eligible_per_skill", {}) or {}
    if not skill_counts:
        parts.append("- _(no eligible attempts found)_\n")
    else:
        for skill in sorted(skill_counts):
            parts.append(f"- `{skill}`: **{skill_counts[skill]}** eligible attempts")
        parts.append("")

    parts.append("### Eligible-for-few-shot per skill × tenant\n")
    per_tenant = a02.get("eligible_per_skill_tenant", {}) or {}
    if not per_tenant:
        parts.append("- _(no eligible attempts with tenant attribution)_\n")
    else:
        for skill in sorted(per_tenant):
            parts.append(f"- skill `{skill}`:")
            tenants = per_tenant[skill]
            for tenant in sorted(tenants, key=lambda t: -tenants[t]):
                parts.append(
                    f"  - tenant `{tenant}`: **{tenants[tenant]}** "
                    "eligible attempts"
                )
        parts.append("")

    parts.append("### Pitfall-#10 — starvation set (the A1 backfill target)\n")
    starv = a02.get("pitfall10_starvation_sessions")
    if starv is None:
        parts.append(
            f"- _(query error: `{a02.get('pitfall10_error', 'unknown')}`)_\n"
        )
    else:
        parts.append(
            f"- **{starv} sessions** have admin_comment set on at "
            "least one snippet AND results_published_at IS NULL.\n"
            "- Each of these sessions' admin edits are invisible to "
            "admin_annotation_events today; they will land there "
            "once the A1 backfill cron runs.\n"
        )

    # ── A0.3
    parts.append("## A0.3 — admin_annotation_events: field × chip breakdown\n")
    field_chip = a03.get("by_field_chip", {}) or {}
    if a03.get("error"):
        parts.append(f"- ERROR: `{a03['error']}`\n")
    elif not field_chip:
        parts.append(
            "- _(no rows in admin_annotation_events — annotation "
            "capture has never fired)_\n"
        )
    else:
        parts.append(f"- Total rows scanned: **{a03.get('total_rows')}**")
        parts.append("")
        parts.append("| field_name | chip | rows |")
        parts.append("|---|---|---|")
        for field in sorted(field_chip):
            for chip in sorted(field_chip[field]):
                parts.append(
                    f"| `{field}` | `{chip}` | "
                    f"{field_chip[field][chip]} |"
                )
        parts.append("")
        parts.append(
            "**NULL-chip rows are the training-useful diff signal** "
            "(admin EDITED the AI draft). `approved_as_is` rows are "
            "positive-acceptance signal but not training pairs.\n"
        )

    # ── A0.4 verdicts
    parts.append("## A0.4 — Verdicts (gate the next phases)\n")
    parts.append("### Fine-tune corpus viability\n")
    parts.append(fine_tune_verdict + "\n")
    if ft_lines:
        parts.append("Per-channel clean-pair (NULL chip) counts:\n")
        parts.extend(ft_lines)
        parts.append("")

    parts.append("### Few-shot loop status\n")
    parts.append(few_shot_verdict + "\n")
    if fs_lines:
        parts.extend(fs_lines)
        parts.append("")

    parts.append("### Tenant viability (for shared-vs-per-tenant model decision)\n")
    parts.append(tenant_verdict + "\n")
    if tenant_lines:
        parts.extend(tenant_lines)
        parts.append("")

    # ── Footer / hand-off
    parts.append("---\n")
    parts.append(
        "## Next steps (per Phase A spec build-order)\n"
        "\n"
        "1. **Always:** A1 (few-shot backfill cron) — ships regardless "
        "of the verdict above; it's the only phase that improves "
        "Track A (the user-facing AI).\n"
        "2. **If fine-tune viability = VIABLE:** A3 (fine-tune "
        "pipeline) may proceed for the channel that cleared the floor "
        "— per the spec's settled decisions (1–7 in A3.1). Promote "
        "stays human-gated regardless (A3.4); the volumetric retrain "
        "trigger (A3.2a) reads the FLOOR from this document's "
        "channel counts.\n"
        "3. **If fine-tune viability = NOT YET VIABLE:** **Do not "
        "build A3.** Re-run this diagnostic after the A1 backfill "
        "cron has been firing for ≥ 1 week and re-evaluate.\n"
        "\n"
        f"**Thresholds used in this report** "
        f"(documented so a human can audit the verdicts):\n"
        f"- Fine-tune viability floor per channel: "
        f"`{_VIABILITY_FLOOR}` clean pairs\n"
        f"- Tenant-isolation viability floor per (tenant, channel): "
        f"`{_TENANT_VIABILITY_FLOOR}` clean pairs\n"
        f"- Few-shot healthy/partial/starved per skill: "
        f"`{_FEW_SHOT_HEALTHY_PER_SKILL}` / "
        f"`{_FEW_SHOT_PARTIAL_PER_SKILL}` / below\n"
        "\n"
        "These are DIAGNOSTIC thresholds for the verdicts in this "
        "report — they are NOT the auto-promote thresholds the spec "
        "(A3.4) forbids, which remain unwritten by design.\n"
    )
    return "\n".join(parts) + "\n"


def render_sql_only() -> str:
    """Print every SQL query the script runs, in spec order, so a
    human can paste them into the Supabase SQL editor manually."""
    blocks: list[tuple[str, str]] = [
        ("A0.1 — runtime_config.openai_copilot_model", SQL_A01_RUNTIME_CONFIG),
        ("A0.2.1 — follow_up_outcome (legacy)", SQL_A02_1_FOLLOW_UP_OUTCOMES_LEGACY),
        ("A0.2.1 — coaching_attempts (canonical)", SQL_A02_1_COACHING_ATTEMPTS),
        ("A0.2.2 + A0.2.3 — eligible per skill", SQL_A02_2_ELIGIBLE_PER_SKILL),
        ("A0.2.3 — eligible per skill × tenant", SQL_A02_3_ELIGIBLE_PER_TENANT),
        ("A0.2.4 — pitfall-#10 starvation set", SQL_A02_4_PITFALL10_STARVATION),
        ("A0.3 — admin_annotation_events field × chip", SQL_A03_FIELD_CHIP_BREAKDOWN),
        ("A0.4 — per-tenant clean-pair pool", SQL_A04_TENANT_VIABILITY),
    ]
    out: list[str] = ["-- Phase A0 diagnostic queries — paste into Supabase SQL editor in order."]
    for title, sql in blocks:
        out.append("")
        out.append(f"-- ─── {title} ───")
        out.append(sql)
    return "\n".join(out) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Phase A0 — read-only diagnostic. Emits PHASE-A0-"
            "FINDINGS.md unless --sql-only is set."
        )
    )
    parser.add_argument(
        "--out",
        type=str,
        default="PHASE-A0-FINDINGS.md",
        help="Path for the findings report (default: repo root).",
    )
    parser.add_argument(
        "--sql-only",
        action="store_true",
        help=(
            "Print the SQL each section runs and exit. Useful when "
            "this script's environment can't reach Supabase."
        ),
    )
    args = parser.parse_args()

    if args.sql_only:
        print(render_sql_only())
        return 0

    try:
        from services.db import db  # noqa: E402
    except Exception as e:
        print(
            f"ERROR — could not import services.db ({e}). "
            "Re-run with --sql-only and paste the queries into "
            "Supabase SQL editor manually.",
            file=sys.stderr,
        )
        return 2

    print("Running A0.1 — runtime_config.openai_copilot_model …")
    a01 = _section_a01(db)
    print(f"  → promoted={a01.get('promoted')} value={a01.get('value')}")

    print("Running A0.2 — few-shot loop health + pitfall-#10 …")
    a02 = _section_a02(db)
    print(
        f"  → eligible_per_skill={a02.get('eligible_per_skill')} "
        f"starvation_sessions={a02.get('pitfall10_starvation_sessions')}"
    )

    print("Running A0.3 — admin_annotation_events field × chip …")
    a03 = _section_a03(db)
    print(f"  → total_rows={a03.get('total_rows')}")

    print("Running A0.4 — per-tenant clean-pair pool …")
    a04 = _section_a04_tenant(db)

    timestamp = datetime.now(timezone.utc).isoformat()
    report = render_report(
        a01=a01, a02=a02, a03=a03, a04=a04, timestamp=timestamp,
    )

    out_path = os.path.abspath(args.out)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"\nReport written: {out_path}")
    print(
        "STOP. A human MUST read the verdicts before any A1–A4 phase "
        "starts."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
