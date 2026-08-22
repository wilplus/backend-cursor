# WILLAB DECISION FILTER

**What this is:** an anti-drift gate for the willab north star. **Run it on EVERY proposed decision — feature, refactor, bugfix, library, copy, infra, prompt edit — BEFORE work starts.** You are adversarial by construction: assume the proposer has half-convinced themselves with a good-sounding rationalization, and your job is to catch it. Work the procedure in order, stop at the first REJECT, and always emit the VERDICT + REDIRECT block.

> A compact, self-sufficient version of this gate lives in the repo `CLAUDE.md` (always-on). This file is the full procedure + rationalization catalog + worked examples.

---

## THE GOAL (the only thing this filter protects)

**F1 — THE MVP, THE CRITICAL PATH.** voice → durable Recording Attempt →
perfect transcript segmented exactly 1:1 per slide → project-specific Ideal Text
after Take 1 → evidence-backed Manager Feedback after every Take. Ideal Text is
the sole canonical presentation document. Later Takes propose improvements but
never rebuild or silently overwrite it.
- **Three load-bearing pieces:** **(a)** perfect per-slide transcription,
  **(b)** coherent initial Ideal Text with stable Paragraph identity, and
  **(c)** Manager arbitration that surfaces at most three defensible Feedback
  items. The record → process → Ideal Text → next-Take loop never waits for a
  coach.

**F2 — the asynchronous learning and confidence overlay, SECOND priority.**
Machine Feedback and coach review retain one auditable lineage. Confident Voice
asks one qualitative question about how assured the delivery sounds. Voice Album
admission requires Machine Yes + User Yes + Coach Yes about the exact same
recording. Owner answers are routing signals, never blind training labels.

> **⚠️ 2026-08-13 — the charisma construct is RETIRED (founder re-lock).** F2 read "stress → charisma (internally threat → challenge = breakthrough)" until this date. That construct had no written operational definition, so nothing could say what a rater was being asked — the exact defect SPEC §1.4 exists to prevent — and §17 names charisma explicitly as something `confidence` must NOT be folded together with. It was not just wording: it was ROUTING LIVE FEEDBACK (`_W_D`/`_W_B` inside `power_score`, and the replace/emphasize/no-star decision in the star lane), so retiring it was a code change, not a docs change. The coach's challenge/threat rows in `training_labels` are a CORPUS, not a construct claim, and are versioned rather than rewritten (SPEC §3.2).

**LOCKED CHOICES** (founder re-locked 2026-08-22; complete contract:
[`CANONICAL_PRODUCT_CONTRACT.md`](CANONICAL_PRODUCT_CONTRACT.md)):
- **L1 — One canonical document.** Ideal Text is persistent and user-controlled.
  Take 1 creates it; later Takes never replace it with a transcript or best-of
  assembly. Best Presentation as a separate product artifact is retired.
- **L2 — Manager-gated Feedback.** Detectors create Candidates; only Manager-
  approved Candidates surface. The budget is at most three, evidence-first,
  Confident Voice first when defensible, and unused family capacity is
  reassigned rather than manufactured.
- **L3 — Provenance walls.** Machine prediction, owner routing, blind peer
  rating, coach judgment, and detector verdict remain separate. Voice Album
  membership requires Machine Yes + User Yes + Coach Yes on the exact recording.

**FENCES** (breaking one = automatic REJECT — not tradeable for UX, speed, engagement, or demand):
- **AC-9** — never surface scores / verdicts / numbers to users. The read is qualitative.
- **CONSTRUCT** — every measured state traces to a **written operational definition** (SPEC §1.4/§17) and asks exactly ONE thing; a state with no entry cannot ship. It surfaces qualitatively ONLY — never a score, ratio, or classifier output. (Bans the surfaced number, not internal use. "Charisma" failed the definition half and was retired 2026-08-13.)
- **BLIND COACH** — coach labels stay blind; the shadow model never surfaces its guess as a badge.
- **LIVE LOOP** — never break record→process→Ideal Text→next Take; coach review is asynchronous; merges are gate-routed; user-facing copy needs founder sign-off.
- **NORTH-STAR LOCK** — the goal changes ONLY by explicit founder decision. Silent drift is the enemy you exist to stop.

---

## EVALUATION PROCEDURE (run in order; stop at the first REJECT)

**STEP 1 — STATE & SPLIT.** Restate the decision in one sentence and what it concretely changes (code path, surface, data, copy, dependency). If it bundles several things, split them and run each separately.

**STEP 2 — FENCE CHECK (hard stop, FIRST — before any F1 classification).** Does it touch AC-9, the construct fence, blind coach, the live loop, or surfaced copy? Any violation → **REJECT**. *First on purpose: a fence breach that also sounds like an F1 improvement ("surface a confidence score so users see progress") must die here before it can masquerade as ADVANCE.*

**STEP 3 — LOCKED-CHOICE CHECK (second hard gate, separate from fences).** Any YES → **REJECT**:
1. Rebuilds or silently changes Ideal Text from a later transcript, best-of assembly, machine proposal, or coach action? → breaks **L1**.
2. Surfaces a raw Candidate, bypasses Manager arbitration, exceeds the budget, or manufactures Feedback? → breaks **L2**.
3. Mixes owner routing, peer rating, coach judgment, machine prediction, or detector verdict provenance; or reuses one recording's signal for another? → breaks **L3**.

*Refactor guard:* a cleaner-architecture claim must prove it leaves L1/L2/L3 and the live loop untouched. **No behavior change ⇒ no priority.**

**STEP 4 — CLASSIFY (pick exactly ONE tier):**
- **F1-CORE** — changes per-slide transcription accuracy, initial Ideal Text coherence/Paragraph identity, or Manager evidence selection and arbitration.
- **F1-SURFACE** — hardens record→Take, Ideal Text read/edit/protect, Feedback decisions, or root-roadmap delivery.
- **F1-SUPPORT** — required for a load-bearing piece to ship/run, naming a **specific, currently-in-flight F1 task** it unblocks. Rhetorical line-of-sight is NOT enough (see R11).
- **F2** — coach-review lineage, provenance-safe learning, Confident Voice, and exact-recording Voice Album admission.
- **SCAFFOLDING** — Lounge, cadence, PWA, audits, chat, onboarding, profile, infra, cosmetics.
- **DRIFT** — introduces or serves a NEW goal/surface/construct no F1/F2 piece needs (engagement, retention, a new score, a coach-only feature), or reframes the product away from F1+F2.

If you cannot place it in F1-CORE/SURFACE/SUPPORT/F2 by a **concrete mechanism**, it is SCAFFOLDING or DRIFT — default to the stricter.

**STEP 5 — RATIONALIZATION SCAN.** Name any R# in play (appendix) and apply its counter-move. A decision standing only on a rationalization → **REJECT/PARK**. The two laundering moves to hunt hardest:
- **“More usage → more Takes → better learning”** is engagement dressed as F1-support and remains DRIFT.
- **"Foundation / it unblocks F1 later / it's a platform"** → demand the named, near-term, in-flight F1/F2 task. None ⇒ scaffolding dressed as critical path (**R11**). PARK.

**STEP 6 — CRITICAL-PATH & CONTENTION TEST.**
- **F1-CORE** → PASS, top priority; **wins all ties** by default.
- **F1-SURFACE** → PASS as justified-scaffolding (behind open F1-CORE work).
- **F1-SUPPORT** → PASS only if the in-flight F1 task is named; else demote to SCAFFOLDING.
- **F2** → PASS if it improves coach-review lineage, provenance-safe learning, or exact-recording Album admission without delaying F1-CORE.
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
           (3) improve initial Ideal Text coherence without silent later changes
           (4) sharpen Manager evidence selection or reduce manual coach load
           For a locked/fence breach: the compliant version that keeps the lock/fence,
           or "founder north-star change required.">
```

**One-line PR / thread stamp (for auditability):**
`FILTER: [ADVANCE-F1|F1-SURFACE|ADVANCE-F2|SCAFFOLD|DEFER|REJECT] — cat {F1-core|F1-surface|F1-support|F2|scaffold|drift} — fences {clear|BREAKS:x} — locks {clear|BREAKS:Lx} — redirect: {…}`

**Rule of thumb:** improve per-slide transcription, initial Ideal Text coherence, or Manager Feedback quality. If a proposal does none of those and cannot name the in-flight F1/F2 task it unblocks, it does not win.

---

## WORKED EXAMPLES (the battery — this filter is self-checking against these)

| # | Decision | Verdict | Category | Trigger |
|---|----------|---------|----------|---------|
| **A** | Fix `recordStartRef` two-clocks offset | **ADVANCE-F1** | F1-CORE | improves word→slide bucketing = piece (a) |
| **B** | Streaks + leaderboard for retention | **REJECT** | DRIFT | engagement goal (R3); leaderboard also flirts AC-9; "more takes→better ranking" laundering rejected |
| **C** | Later Take silently rewrites Ideal Text | **REJECT** | — | breaks **L1**; later Takes may propose but never overwrite |
| **D** | 0–100 confidence score for users | **REJECT** | — | breaks **AC-9 + CONSTRUCT** (R6); caught at STEP 2 before it can pose as F1 signal |
| **E** | Cache the canonical Ideal Text read path at scale | **JUSTIFIED-SCAFFOLDING** | F1-SURFACE | performance-hardens a real F1 surface |
| **F** | Surface raw detector candidates “for speed” | **REJECT** | — | bypasses Manager and breaks **L2** |
| **G** | Richer Lounge bot persona, more jokes | **REJECT** | DRIFT/SCAFFOLDING | no nameable in-flight F1/F2 link; "hardens engagement" ≠ F1 surface (R1) |
| **H** | Whisper accuracy on accented speech / vocab priming | **ADVANCE-F1** | F1-CORE | raises transcription fidelity = piece (a) |
| **I** | Use owner Yes as blind model ground truth | **REJECT** | — | mixes provenance and breaks **L3** |
| **J** | CSV export of transcripts | **DEFER** | SCAFFOLDING | legitimate, neutral, off critical path, nothing it unblocks is in flight |

*Self-check: B and G die as DRIFT/REJECT (non-F1 goal); J merely DEFERs (neutral). E passes via the F1-SURFACE lane while G/B do not. D and I die at the FENCE step before any F1 framing can rescue them.*

---

## APPENDIX — RATIONALIZATION CATALOG (name the one in play; apply the counter-move)

| # | Rationalization | Counter-move |
|---|---|---|
| R1 | “It improves UX.” | UX alone is scaffolding. Does it raise transcript accuracy, Ideal Text correctness, or Feedback quality? No ⇒ no critical-path priority. |
| R2 | "Cleaner / better architecture / nice refactor." | Cleanliness isn't a goal. Justified only if it unblocks F1/F2 or removes a live-loop risk. Prove it doesn't touch L1/L2/L3 or the loop. No behavior change ⇒ no priority. |
| R3 | "Boosts engagement / retention / time-in-app." | Engagement is the classic drift vector and is **never** an F1 unblock. Value is a better speech, not more sessions. DRIFT. |
| R4 | "The coach asked for it." | The coach is a labeler inside F2, not the founder. Route to "does it reduce manual coach load via the shadow loop?" New coach-only surface w/ no shadow path = drift. Only the FOUNDER moves the north star. |
| R5 | "Quick / low-effort / while we're in here." | Cheap off-goal is still off-goal; "while we're in here" is how fences erode. Quick + on-path ⇒ do it; quick + off-path ⇒ still waits. |
| R6 | "Users want a score / number / rating." | AC-9 + CONSTRUCT. Surfacing any score/ratio/confidence-number = REJECT regardless of demand. Redirect to a qualitative read. |
| R7 | “Let each Take regenerate the Ideal Text.” | Breaks L1. Generate a proposal and require explicit user acceptance. |
| R8 | “Show every strong detector output.” | Breaks L2. Route Candidates through Manager arbitration and its evidence budget. |
| R9 | "Ship the shadow guess as a badge — it's accurate enough." | Breaks BLIND COACH + CONSTRUCT. Shadow learns silently; coach labels stay blind. Redirect: measure shadow-vs-coach agreement OFF-SURFACE. |
| R10 | “Owner agreement is good enough training data.” | Breaks L3. Owner answers remain routing signals, separate from blind and coach labels. |
| R11 | "It unblocks F1/F2 later / it's a foundation / a platform." | The favorite laundering move. Demand the **named, near-term, in-flight** F1/F2 task and the line of sight. None ⇒ tier-3 scaffolding dressed as critical path. Park. |
| R12 | “The learning layer will fix the live pipeline.” | F1 must work without the learning layer. Fix transcription, Ideal Text, or Manager arbitration first. |
| R13 | "Just a tiny copy tweak / user-facing change." | User-facing copy needs founder sign-off (LIVE LOOP). Small ≠ exempt. Route to sign-off; never auto-ship surfaced copy. |
| R14 | "It's urgent / there's a deadline / a demo." | Urgency justifies sequencing, never fence-breaking or north-star change. Redirect to the fastest ON-goal thing that meets the deadline. |

**Generalize clause:** if the rationalization isn't listed, name the tier it really sits in, check it against every FENCE and every Lx, and treat any "foundation / later / cleaner / wanted / urgent" framing as a drift flag until a concrete, in-flight F1/F2 unblock is shown. When in doubt, protect F1.
