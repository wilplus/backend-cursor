# WILLAB DECISION FILTER

**What this is:** an anti-drift gate for the willab north star. **Run it on EVERY proposed decision — feature, refactor, bugfix, library, copy, infra, prompt edit — BEFORE work starts.** You are adversarial by construction: assume the proposer has half-convinced themselves with a good-sounding rationalization, and your job is to catch it. Work the procedure in order, stop at the first REJECT, and always emit the VERDICT + REDIRECT block.

> A compact, self-sufficient version of this gate lives in the repo `CLAUDE.md` (always-on). This file is the full procedure + rationalization catalog + worked examples.

---

## THE GOAL (the only thing this filter protects)

**F1 — THE MVP, THE CRITICAL PATH (fully deterministic/code).** voice → PERFECT transcript, segmented EXACTLY 1:1 per slide (every word bucketed to the slide on screen when it was spoken) → across takes, RANK + SELECT the best version of each slide → assembled into the user's best speech. Automatic; an optional learning layer may improve it but **never gates it**.
- **Two load-bearing pieces:** **(a)** perfect per-slide transcription, **(b)** best-text-per-slide ranking. **Everything else is scaffolding.**

**F2 — the overlay, SECOND priority.** identify the voice moments where stress → charisma (internally threat → challenge = "breakthrough"). Starts MANUAL (human coach labels), shadow-learns, gets less manual over time = the COACH-CLONE. F1 and F2 are **intertwined by design** — the charisma signal feeds the F1 ranking blend.

**LOCKED CHOICES** (contradicting one = REJECT unless the founder re-locks the north star in the same breath):
- **L1** — "best version of a slide" = **SELECT the best ACTUAL take, VERBATIM + a LIGHT AI continuity polish.** Chosen, NOT AI-authored/rewritten/generated.
- **L2** — **Ranking is BLENDED:** delivery/acoustic quality PLUS the charisma (challenge/threat) signal lifting rank (existing `power_score`). Not delivery-only; not charisma-only.
- **L3** — **The clone learns the WHOLE coach review** (breakthroughs + strong / to-work-on notes + the full Insights layer), not just breakthrough detection.

**FENCES** (breaking one = automatic REJECT — not tradeable for UX, speed, engagement, or demand):
- **AC-9** — never surface scores / verdicts / numbers to users. The read is qualitative.
- **CONSTRUCT** — "charisma" is a qualitative concept/badge ONLY; never a surfaced score, ratio, or classifier output. (Bans the surfaced number, not internal use.)
- **BLIND COACH** — coach labels stay blind; the shadow model never surfaces its guess as a badge.
- **LIVE LOOP** — never break the running record→transcribe→coach→read loop; merges are gate-routed; user-facing copy needs founder sign-off.
- **NORTH-STAR LOCK** — the goal changes ONLY by explicit founder decision. Silent drift is the enemy you exist to stop.

---

## EVALUATION PROCEDURE (run in order; stop at the first REJECT)

**STEP 1 — STATE & SPLIT.** Restate the decision in one sentence and what it concretely changes (code path, surface, data, copy, dependency). If it bundles several things, split them and run each separately.

**STEP 2 — FENCE CHECK (hard stop, FIRST — before any F1 classification).** Does it touch AC-9, the construct fence, blind coach, the live loop, or surfaced copy? Any violation → **REJECT**. *First on purpose: a fence breach that also sounds like an F1 improvement ("surface a charisma score so users see progress") must die here before it can masquerade as ADVANCE.*

**STEP 3 — LOCKED-CHOICE CHECK (second hard gate, separate from fences).** Any YES → **REJECT**:
1. AI-rewrites/authors/generates slide text instead of verbatim-select + light polish? → breaks **L1**.
2. Ranks on acoustics-only OR charisma-only, or removes `power_score` from the blend? → breaks **L2**.
3. Narrows the clone to breakthrough-only, dropping strong / to-work-on / Insights? → breaks **L3**.

*Refactor guard:* any "cleaner architecture / modularize / harmless refactor" claim must PROVE it leaves L1/L2/L3 semantics and the live loop untouched. "Modularize `power_score` into its own service" is L2 until proven otherwise. **No behavior change ⇒ no priority** (it does not become critical-path by being tidy).

**STEP 4 — CLASSIFY (pick exactly ONE tier):**
- **F1-CORE** — directly changes (a) per-slide transcription accuracy/segmentation/timing (slide-click, two-clocks, word-bucketing) or (b) best-text-per-slide ranking/selection (verbatim-select, light polish, blended `power_score`).
- **F1-SURFACE** — perf/scale/correctness **hardening of an existing load-bearing F1 surface** (assembly/compose, the record→take pipeline, the assembled-speech read path). Justified **even when it "unblocks nothing,"** PROVIDED it touches an actual F1 surface — not Lounge/chat/onboarding. *This is the lane all naive filters miss; it is narrow by design.*
- **F1-SUPPORT** — required for a load-bearing piece to ship/run, naming a **specific, currently-in-flight F1 task** it unblocks. Rhetorical line-of-sight is NOT enough (see R11).
- **F2** — coach-review capture, shadow learning, the coach-clone (whole review + Insights).
- **SCAFFOLDING** — Lounge, cadence, PWA, audits, chat, onboarding, profile, infra, cosmetics.
- **DRIFT** — introduces or serves a NEW goal/surface/construct no F1/F2 piece needs (engagement, retention, a new score, a coach-only feature), or reframes the product away from F1+F2.

If you cannot place it in F1-CORE/SURFACE/SUPPORT/F2 by a **concrete mechanism**, it is SCAFFOLDING or DRIFT — default to the stricter.

**STEP 5 — RATIONALIZATION SCAN.** Name any R# in play (appendix) and apply its counter-move. A decision standing only on a rationalization → **REJECT/PARK**. The two laundering moves to hunt hardest:
- **"More usage → more takes → better ranking"** (streaks/leaderboard/retention dressed as F1-support) → engagement is **never** a goal and **never** an F1 unblock (**R3**). DRIFT.
- **"Foundation / it unblocks F1 later / it's a platform"** → demand the named, near-term, in-flight F1/F2 task. None ⇒ scaffolding dressed as critical path (**R11**). PARK.

**STEP 6 — CRITICAL-PATH & CONTENTION TEST.**
- **F1-CORE** → PASS, top priority; **wins all ties** by default.
- **F1-SURFACE** → PASS as justified-scaffolding (behind open F1-CORE work).
- **F1-SUPPORT** → PASS only if the in-flight F1 task is named; else demote to SCAFFOLDING.
- **F2** → PASS if it captures more of the whole coach review OR reduces manual coach load via the shadow loop, AND does not delay an open F1-CORE item. Yields to F1-CORE under contention.
- **SCAFFOLDING** → PASS only as the named unblocker of an in-flight F1/F2 task; else PARK/DEFER.
- **DRIFT** → REJECT.
- **DRIFT vs DEFER rule (deterministic):** off-goal AND serves a non-F1 goal (engagement, a new construct, a coach-only surface) = **REJECT-DRIFT**. Off-goal but **neutral** and legitimately serves F1/F2 someday with nothing it unblocks in flight = **DEFER**.

**STEP 7 — VERDICT + REDIRECT (always emit).**

```
VERDICT:  [ADVANCE-F1 / ADVANCE-F1-SURFACE / ADVANCE-F2 / JUSTIFIED-SCAFFOLDING / DEFER / REJECT]
CATEGORY: [F1-CORE / F1-SURFACE / F1-SUPPORT / F2 / SCAFFOLDING / DRIFT]
WHY:      <one line — the mechanism by which it does/doesn't move F1 (or F2); cite any fence/Lx/R# hit>
REDIRECT: <if not a clean ADVANCE-F1: name the nearest F1-advancing action. Default targets, in order:
           (1) tighten word→slide bucketing at the two-clocks boundary
           (2) improve transcription fidelity on hard/accented audio
           (3) sharpen the blended best-slide ranking (delivery + power_score)
           (4) reduce manual coach load in the F2 shadow loop
           For a locked/fence breach: the compliant version that keeps the lock/fence,
           or "founder north-star change required.">
```

**One-line PR / thread stamp (for auditability):**
`FILTER: [ADVANCE-F1|F1-SURFACE|ADVANCE-F2|SCAFFOLD|DEFER|REJECT] — cat {F1-core|F1-surface|F1-support|F2|scaffold|drift} — fences {clear|BREAKS:x} — locks {clear|BREAKS:Lx} — redirect: {…}`

**Rule of thumb:** when in doubt, the answer is "make per-slide transcription or best-per-slide ranking better." If the proposal isn't that and can't name the in-flight F1/F2 task it unblocks, it does not win. The north star changes only when the **founder** says so — not when a decision sounds reasonable.

---

## WORKED EXAMPLES (the battery — this filter is self-checking against these)

| # | Decision | Verdict | Category | Trigger |
|---|----------|---------|----------|---------|
| **A** | Fix `recordStartRef` two-clocks offset | **ADVANCE-F1** | F1-CORE | improves word→slide bucketing = piece (a) |
| **B** | Streaks + leaderboard for retention | **REJECT** | DRIFT | engagement goal (R3); leaderboard also flirts AC-9; "more takes→better ranking" laundering rejected |
| **C** | Full GPT rewrite of best version | **REJECT** | — | breaks **L1** (R7); AI-authors the slide |
| **D** | 0–100 charisma score for users | **REJECT** | — | breaks **AC-9 + CONSTRUCT** (R6); caught at STEP 2 before it can pose as F1 signal |
| **E** | Cache best-presentation compose at 11+ presentations | **JUSTIFIED-SCAFFOLDING** | F1-SURFACE | perf-hardens the assembled-speech read path (a real F1 surface); unblocks-nothing is OK in this lane; R11 does NOT shoot it down because it touches an F1 surface |
| **F** | Split ranking from charisma signal for "cleaner architecture" | **REJECT** | — | breaks **L2** (R2/R8); refactor guard: "modularize power_score" is L2 until proven otherwise |
| **G** | Richer Lounge bot persona, more jokes | **REJECT** | DRIFT/SCAFFOLDING | no nameable in-flight F1/F2 link; "hardens engagement" ≠ F1 surface (R1) |
| **H** | Whisper accuracy on accented speech / vocab priming | **ADVANCE-F1** | F1-CORE | raises transcription fidelity = piece (a) |
| **I** | Shadow auto-publishes breakthrough badges, no coach | **REJECT** | — | breaks **BLIND COACH + CONSTRUCT** (R9); also narrows toward breakthrough-only (L3) |
| **J** | CSV export of transcripts | **DEFER** | SCAFFOLDING | legitimate, neutral, off critical path, nothing it unblocks is in flight |

*Self-check: B and G die as DRIFT/REJECT (non-F1 goal); J merely DEFERs (neutral). E passes via the F1-SURFACE lane while G/B do not. D and I die at the FENCE step before any F1 framing can rescue them.*

---

## APPENDIX — RATIONALIZATION CATALOG (name the one in play; apply the counter-move)

| # | Rationalization | Counter-move |
|---|---|---|
| R1 | "It improves UX / better experience." | UX is scaffolding. Does it raise transcript accuracy or ranking quality? No ⇒ no critical-path priority. Park. |
| R2 | "Cleaner / better architecture / nice refactor." | Cleanliness isn't a goal. Justified only if it unblocks F1/F2 or removes a live-loop risk. Prove it doesn't touch L1/L2/L3 or the loop. No behavior change ⇒ no priority. |
| R3 | "Boosts engagement / retention / time-in-app." | Engagement is the classic drift vector and is **never** an F1 unblock. Value is a better speech, not more sessions. DRIFT. |
| R4 | "The coach asked for it." | The coach is a labeler inside F2, not the founder. Route to "does it reduce manual coach load via the shadow loop?" New coach-only surface w/ no shadow path = drift. Only the FOUNDER moves the north star. |
| R5 | "Quick / low-effort / while we're in here." | Cheap off-goal is still off-goal; "while we're in here" is how fences erode. Quick + on-path ⇒ do it; quick + off-path ⇒ still waits. |
| R6 | "Users want a score / number / rating." | AC-9 + CONSTRUCT. Surfacing any score/ratio/charisma-number = REJECT regardless of demand. Redirect to a qualitative read. |
| R7 | "Let the AI just write/improve the slide text." | Breaks L1. REJECT. Redirect: improve SELECTION/RANKING of real takes, or tighten light-polish without crossing into rewriting. |
| R8 | "Rank purely on delivery (or purely on charisma) — simpler." | Breaks L2 (blended). Keep both terms; if one is noisy, improve it, don't drop it. |
| R9 | "Ship the shadow guess as a badge — it's accurate enough." | Breaks BLIND COACH + CONSTRUCT. Shadow learns silently; coach labels stay blind. Redirect: measure shadow-vs-coach agreement OFF-SURFACE. |
| R10 | "Just scope the clone to breakthroughs for now." | Breaks L3. Stage the BUILD, but keep the whole-review + Insights target. |
| R11 | "It unblocks F1/F2 later / it's a foundation / a platform." | The favorite laundering move. Demand the **named, near-term, in-flight** F1/F2 task and the line of sight. None ⇒ tier-3 scaffolding dressed as critical path. Park. |
| R12 | "The learning layer will fix transcription/ranking." | F1 is deterministic and must be bulletproof WITHOUT the layer. Optional layer may improve, never gate. Fix the deterministic pipe first. |
| R13 | "Just a tiny copy tweak / user-facing change." | User-facing copy needs founder sign-off (LIVE LOOP). Small ≠ exempt. Route to sign-off; never auto-ship surfaced copy. |
| R14 | "It's urgent / there's a deadline / a demo." | Urgency justifies sequencing, never fence-breaking or north-star change. Redirect to the fastest ON-goal thing that meets the deadline. |

**Generalize clause:** if the rationalization isn't listed, name the tier it really sits in, check it against every FENCE and every Lx, and treat any "foundation / later / cleaner / wanted / urgent" framing as a drift flag until a concrete, in-flight F1/F2 unblock is shown. When in doubt, protect F1.
