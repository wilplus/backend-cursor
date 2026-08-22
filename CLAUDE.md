# CLAUDE.md — willab backend

## ⭐ The one goal (founder re-locked 2026-08-22)

**F1 — THE MVP, THE CRITICAL PATH.** voice → durable Recording Attempt →
perfect transcript segmented exactly 1:1 per slide → project-specific Ideal Text
after Take 1 → evidence-backed Manager Feedback after every Take. Ideal Text is
the sole canonical presentation document. Later Takes propose improvements but
never rebuild or silently overwrite it. The load-bearing pieces are per-slide
transcription, coherent initial Ideal Text with stable Paragraph identity, and
Manager arbitration that surfaces at most three defensible Feedback items. The
record → process → Ideal Text → next-Take loop never waits for a coach.

**F2 — the asynchronous learning and confidence overlay, SECOND priority.**
Machine Feedback and coach review retain one auditable lineage. Confident Voice
asks one qualitative question about how assured the delivery sounds. Voice Album
admission requires Machine Yes + User Yes + Coach Yes about the exact same
recording. Owner answers are routing signals, never blind training labels.

> **⚠️ 2026-08-13 — the charisma construct is RETIRED (founder re-lock).** F2 used to be written as "stress → charisma (internally threat → challenge = breakthrough)". That construct had no written operational definition, so nothing could say what a rater was being asked — the exact defect SPEC §1.4 exists to prevent — and §17 names charisma explicitly as something `confidence` must NOT be folded together with. It was not merely aspirational text: it was ROUTING LIVE FEEDBACK (`_W_D`/`_W_B` in `power_score`, and the replace/emphasize/no-star decision in the star lane). Both are re-pointed onto `confidence` in code. The coach's challenge/threat rows in `training_labels` are a corpus, not a construct claim, and are versioned rather than rewritten (SPEC §3.2).

**LOCKED choices** (complete contract:
[`docs/CANONICAL_PRODUCT_CONTRACT.md`](docs/CANONICAL_PRODUCT_CONTRACT.md)):
**L1** Ideal Text is the one persistent, user-controlled document; later Takes
never rebuild or silently change it, and Best Presentation is retired.
**L2** Detectors create Candidates and only Manager-approved Candidates surface,
with an evidence-first budget of at most three.
**L3** Machine prediction, owner routing, blind peer rating, coach judgment, and
detector verdict remain separate; Album membership requires Machine Yes + User
Yes + Coach Yes on the exact recording.

**FENCES** (breaking one = automatic REJECT): **AC-9** never surface scores, verdicts, ratios, or classifier numbers to users. **CONSTRUCT** every measured state has one written operational definition and asks exactly one thing. **BLIND COACH** coach labels stay blind and model guesses never surface as badges. **LIVE LOOP** never break record→process→Ideal Text→next Take; coach review is asynchronous. User-facing copy needs founder sign-off.

## 🛂 Run the WILLAB DECISION FILTER on EVERY decision before work starts

Every proposed decision — feature, refactor, bugfix, library, copy, infra, prompt edit — passes this gate first. Be adversarial: assume the proposer half-rationalized it. Run in order, stop at the first REJECT, always emit the verdict block.

1. **STATE & SPLIT** — restate it in one sentence + what it concretely changes; split bundles and run each.
2. **FENCE CHECK (first, hard stop)** — touches AC-9 / construct / blind-coach / live-loop / surfaced copy? → **REJECT**. (First on purpose: a fence breach that *sounds* like an F1 win — e.g. "surface a confidence score for progress" — must die here.)
3. **LOCKED-CHOICE CHECK** — rebuilds or silently changes Ideal Text (L1)? surfaces raw Candidates, bypasses Manager, exceeds the budget, or manufactures Feedback (L2)? mixes label provenance or reuses signals across recordings (L3)? Any yes → **REJECT**. Refactors must prove L1/L2/L3 and the live loop remain intact.
4. **CLASSIFY (one tier)** — **F1-CORE** changes per-slide transcription, initial Ideal Text coherence/identity, or Manager evidence arbitration. **F1-SURFACE** hardens record→Take, Ideal Text read/edit/protect, Feedback decisions, or root-roadmap delivery. **F1-SUPPORT** is required for a named in-flight F1 task. **F2** covers coach-review lineage, provenance-safe learning, Confident Voice, and Voice Album. Everything else is **SCAFFOLDING** or **DRIFT**.
5. **RATIONALIZATION SCAN** — “more usage” is not an F1 goal. “Foundation,” “cleaner,” or “later” requires a named in-flight F1/F2 task. No concrete mechanism means park or reject.
6. **CONTENTION** — F1-CORE wins all ties. F1-SURFACE sits behind open F1-CORE. F1-SUPPORT passes only with the named in-flight task. F2 yields to F1-CORE. SCAFFOLDING passes only as the named unblocker of in-flight F1/F2. **DRIFT vs DEFER:** off-goal + serves a non-F1 goal = REJECT-DRIFT; off-goal but neutral & legit-someday with nothing in flight = DEFER.
7. **VERDICT + REDIRECT (always emit):**

```
VERDICT:  [ADVANCE-F1 / ADVANCE-F1-SURFACE / ADVANCE-F2 / JUSTIFIED-SCAFFOLDING / DEFER / REJECT]
CATEGORY: [F1-CORE / F1-SURFACE / F1-SUPPORT / F2 / SCAFFOLDING / DRIFT]
WHY:      <the mechanism it does/doesn't move F1 (or F2); cite any fence/Lx/R# hit>
REDIRECT: <if not a clean ADVANCE-F1: the nearest F1-advancing action. Default targets, in order:
           (1) tighten word→slide bucketing at the two-clocks boundary
           (2) improve transcription fidelity on hard/accented audio
           (3) improve initial Ideal Text coherence without silent later changes
           (4) sharpen Manager evidence selection or reduce manual coach load
           For a locked/fence breach: the compliant version, or "founder north-star change required.">
```

**Rule of thumb:** improve per-slide transcription, initial Ideal Text coherence, or Manager Feedback quality. If a change does none of those and cannot name the in-flight F1/F2 task it unblocks, it does not win.

→ **Full procedure, rationalization catalog (R1–R14), and worked examples (A–J): [docs/willab_decision_filter.md](docs/willab_decision_filter.md).**

## Standing engineering constraints

- **Never break the live loop.** New work branches off `origin/main`; ship via gate-routed PRs (branch → PR → CI green → squash-merge). Never auto-drop tables/columns/migrations.
- **When Actions is out of minutes, the gate is `scripts/local_ci.sh`** (2026-08-11). This repo is private, so its CI minutes come out of the account allowance; when the allowance runs out mid-month every run fails at *runner allocation* — two red X's, zero billable ms, and no logs to download at all (HTTP 404, because the job never started). That is not a code failure and re-running it cannot help. Founder ruling: **DO NOT UPGRADE** — merge on local evidence and document the override in the squash commit. `scripts/local_ci.sh` **is** that evidence: it rebuilds the `checks` job's environment (python 3.12, the pinned `ruff`/`mypy`, `requirements.txt`) and runs its steps in the job's order. An ad-hoc `pytest && ruff && mypy` is **not** the job — the system `mypy` on a dev box was a major version behind CI's pin and passed five real type errors the pinned one catches. `test_local_ci_mirror.py` fails if the script and the workflow drift apart.
- **AC-9 split-sink:** no scores/verdicts to users — the read is qualitative. Coach labels stay blind (shadow model never surfaces a guess).
- **Migrations are idempotent** (`IF NOT EXISTS`) and degrade gracefully. **⚠️ In prod, "on `main`" DOES mean "run in prod": `MIGRATE_ON_BOOT=1` is set, so `bin/railway-web.sh` applies pending migrations during container start — merging a migration IS running it, before the app process boots.**
- **CONFIG-FIRST RULE** (2026-08-10, learned from a live incident). When a migration's correctness depends on an environment variable — a rename, a column swap, anything where the code must be told where to look — **set that variable on EVERY Railway service (web, worker, cron) BEFORE merging the PR. The config waits for the code, never the reverse.** Railway variables are per-service, and a *writer* service missing the variable is the worst case: the web app looks healthy while background jobs silently drop their writes. Verify from each service's **boot log**, not the Railway UI — the UI shows what you set, the log shows what the process read. Ship the variable-reading code and the migration in the same PR so one container start does the whole cutover. If that is impossible, keep the migration out of `migrations/manifest.txt` until the config lands. Full rationale: [docs/MIGRATIONS.md](docs/MIGRATIONS.md).
- **Product copy is held for founder sign-off.** The master document has a construct fence (`_CONSTRUCT_RE`) + CI probe — never surface the retired charisma/stress *score* vocabulary — and, since 2026-08-13, never surface the charisma/threat construct at all.
