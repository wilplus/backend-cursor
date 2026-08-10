# CLAUDE.md — willab backend

## ⭐ The one goal (north star — founder-hardcoded 2026-06-22, changes ONLY by explicit founder decision)

**F1 — THE MVP, THE CRITICAL PATH (fully deterministic/code).** voice → PERFECT transcript, segmented EXACTLY 1:1 per slide (every word bucketed to the slide on screen when it was spoken) → across takes, RANK + SELECT the best version of each slide → assembled into the user's best speech. Automatic; a learning layer may improve it but never gates it. **Two load-bearing pieces: (a) perfect per-slide transcription, (b) best-text-per-slide ranking. Everything else is scaffolding.**

**F2 — the overlay, SECOND priority.** Identify where the voice turned stress → charisma (internally threat → challenge = "breakthrough"). Starts MANUAL (coach labels), shadow-learns, gets less manual over time = the COACH-CLONE. F1 and F2 are intertwined — the charisma signal feeds the F1 ranking blend.

**LOCKED choices** (contradicting one = REJECT unless the founder re-locks the north star): **L1** "best version of a slide" = SELECT the best ACTUAL take, VERBATIM + a LIGHT AI continuity polish (chosen, NOT AI-rewritten). **L2** ranking is BLENDED — delivery/acoustic quality + the charisma (challenge/threat) signal lifting rank (`power_score`); not delivery-only, not charisma-only. **L3** the clone learns the WHOLE coach review (breakthroughs + strong / to-work-on + Insights), not just breakthrough detection.

**FENCES** (breaking one = automatic REJECT, not tradeable for UX/speed/engagement/demand): **AC-9** never surface scores/verdicts/numbers to users (the read is qualitative). **CONSTRUCT** "charisma" is a qualitative badge only, never a surfaced score/ratio/classifier (bans the number, not the idea). **BLIND COACH** coach labels stay blind; the shadow model never surfaces a guess as a badge. **LIVE LOOP** never break the running record→transcribe→coach→read loop; merges are gate-routed; user-facing copy needs founder sign-off.

## 🛂 Run the WILLAB DECISION FILTER on EVERY decision before work starts

Every proposed decision — feature, refactor, bugfix, library, copy, infra, prompt edit — passes this gate first. Be adversarial: assume the proposer half-rationalized it. Run in order, stop at the first REJECT, always emit the verdict block.

1. **STATE & SPLIT** — restate it in one sentence + what it concretely changes; split bundles and run each.
2. **FENCE CHECK (first, hard stop)** — touches AC-9 / construct / blind-coach / live-loop / surfaced copy? → **REJECT**. (First on purpose: a fence breach that *sounds* like an F1 win — e.g. "surface a charisma score for progress" — must die here.)
3. **LOCKED-CHOICE CHECK** — AI-rewrites slide text (L1)? ranks delivery-only or charisma-only / drops `power_score` from the blend (L2)? narrows the clone to breakthroughs-only (L3)? Any yes → **REJECT**. *Refactor guard:* "cleaner architecture / modularize" must PROVE it leaves L1/L2/L3 + the live loop untouched; no behavior change ⇒ no priority.
4. **CLASSIFY (one tier)** — **F1-CORE** (changes per-slide transcription accuracy/timing OR best-per-slide ranking) · **F1-SURFACE** (perf/scale/correctness hardening of an *existing F1 surface* — assembly/compose/record→take/read path — justified even if it "unblocks nothing", but it must touch a real F1 surface, not Lounge/chat) · **F1-SUPPORT** (required to ship a load-bearing piece, naming a *specific in-flight F1 task*; rhetoric isn't enough) · **F2** · **SCAFFOLDING** (Lounge/cadence/PWA/audits/chat/onboarding/infra/cosmetics) · **DRIFT** (serves a NEW goal/surface/construct no F1/F2 piece needs — engagement, a new score, a coach-only feature). Can't place it by a concrete mechanism ⇒ default to the stricter of SCAFFOLDING/DRIFT.
5. **RATIONALIZATION SCAN** — hunt the two laundering moves hardest: **"more usage → more takes → better ranking"** (engagement dressed as F1-support → DRIFT, R3); **"foundation / unblocks F1 later / it's a platform"** (demand the named in-flight task; none ⇒ PARK, R11). Full catalog R1–R14 in the doc.
6. **CONTENTION** — F1-CORE wins all ties. F1-SURFACE sits behind open F1-CORE. F1-SUPPORT passes only with the named in-flight task. F2 yields to F1-CORE. SCAFFOLDING passes only as the named unblocker of in-flight F1/F2. **DRIFT vs DEFER:** off-goal + serves a non-F1 goal = REJECT-DRIFT; off-goal but neutral & legit-someday with nothing in flight = DEFER.
7. **VERDICT + REDIRECT (always emit):**

```
VERDICT:  [ADVANCE-F1 / ADVANCE-F1-SURFACE / ADVANCE-F2 / JUSTIFIED-SCAFFOLDING / DEFER / REJECT]
CATEGORY: [F1-CORE / F1-SURFACE / F1-SUPPORT / F2 / SCAFFOLDING / DRIFT]
WHY:      <the mechanism it does/doesn't move F1 (or F2); cite any fence/Lx/R# hit>
REDIRECT: <if not a clean ADVANCE-F1: the nearest F1-advancing action. Default targets, in order:
           (1) tighten word→slide bucketing at the two-clocks boundary
           (2) improve transcription fidelity on hard/accented audio
           (3) sharpen the blended best-slide ranking (delivery + power_score)
           (4) reduce manual coach load in the F2 shadow loop
           For a locked/fence breach: the compliant version, or "founder north-star change required.">
```

**Rule of thumb:** when in doubt, the answer is "make per-slide transcription or best-per-slide ranking better." If it isn't that and can't name the in-flight F1/F2 task it unblocks, it doesn't win.

→ **Full procedure, rationalization catalog (R1–R14), and worked examples (A–J): [docs/willab_decision_filter.md](docs/willab_decision_filter.md).**

## Standing engineering constraints

- **Never break the live loop.** New work branches off `origin/main`; ship via gate-routed PRs (branch → PR → CI green → squash-merge). Never auto-drop tables/columns/migrations.
- **AC-9 split-sink:** no scores/verdicts to users — the read is qualitative. Coach labels stay blind (shadow model never surfaces a guess).
- **Migrations are idempotent** (`IF NOT EXISTS`) and degrade gracefully. **⚠️ In prod, "on `main`" DOES mean "run in prod": `MIGRATE_ON_BOOT=1` is set, so `bin/railway-web.sh` applies pending migrations during container start — merging a migration IS running it, before the app process boots.**
- **CONFIG-FIRST RULE** (2026-08-10, learned from a live incident). When a migration's correctness depends on an environment variable — a rename, a column swap, anything where the code must be told where to look — **set that variable on EVERY Railway service (web, worker, cron) BEFORE merging the PR. The config waits for the code, never the reverse.** Railway variables are per-service, and a *writer* service missing the variable is the worst case: the web app looks healthy while background jobs silently drop their writes. Verify from each service's **boot log**, not the Railway UI — the UI shows what you set, the log shows what the process read. Ship the variable-reading code and the migration in the same PR so one container start does the whole cutover. If that is impossible, keep the migration out of `migrations/manifest.txt` until the config lands. Full rationale: [docs/MIGRATIONS.md](docs/MIGRATIONS.md).
- **Product copy is held for founder sign-off.** The master document has a construct fence (`_CONSTRUCT_RE`) + CI probe — never surface the retired charisma/stress *score* vocabulary.
