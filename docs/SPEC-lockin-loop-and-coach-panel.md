# SPEC — The lock-in loop, offers, and the coach panel

**Status:** FOUNDER-DECIDED 2026-08-10 ("Treat this as the exact product
spec", "Do Not Deviate"). This document is the target the debugging/fixing
session builds toward. Where it quotes the founder, it quotes verbatim.

**Companions:** `docs/DEBUG-HANDOFF-2026-08-10.md` (verified system maps §6 —
trust those over memory), `docs/SPEC-parts-locking-and-layers.md` (R1–R7,
composition/accentuation), Appendix H (manager engine, `BUDGET_CEILING = 3`).

**Root cause of the outage this spec follows, confirmed by the founder:** the
star-lane flags were disabled on the WORKER service — the generation moved
into the worker on 2026-08-03 (#322) and the flags stayed web-only. Founder
has now enabled them. The engine was starved, not broken.

---

## 1 · The student loop — STRICTLY BLOCKING

> "Users must be locked out of the old text with a 'Working on your text'
> screen until the new text is ready."

Record → blocking "Working on your text" screen → new text. Every take. The
old text is **inaccessible** during analysis — no browse-with-banner.

**Delta vs today:** W4/W5 (FE #254) deliberately routed the user *through*
the wait — tap opens the overlay in a loading state, stale text never
renders, but the surrounding surfaces stay reachable. The spec supersedes
that with a hard block. The existing `analysisPending` wiring is the right
substrate; the change is that it takes over the screen instead of one
overlay. (FE map §6.4 of the handoff names the marker lifecycle and its one
writer — fix the sync-201 no-marker hole while in there, or the blocking
screen will fail to appear exactly when uploads complete fast.)

## 2 · The paragraph state machine (lock-in & approvals)

A paragraph LOCKS in exactly three ways:

1. the user **manually edits** it (today's auto-lock — shipped, #253/#363);
2. the user **accepts a change** on it;
3. the user **explicitly clicks "Lock it"**.

**UI flow:** offer renders as **Accept / Reject chips** → on Accept, the chip
becomes a **"Lock it" button** → clicking locks the paragraph.

So accepting alone does NOT lock (it arms the lock). State machine per part:

```
open ──(offer survives budget)──► offered ──Accept──► accepted ──"Lock it"──► locked
  │                                  │ Reject                                   ▲
  │                                  ▼                                          │
  │                               open (offer resolved, never re-offered       │
  │                                     — decision ledger)                      │
  ├──(user types an edit)──────────────────────────────────────────────────────┤
  └──(user clicks "Lock it" directly)──────────────────────────────────────────┘
```

**The locked rule:**

> "Ordinary AI corrections skip locked text entirely. The ONLY exception is
> if a 'Confident Voice' is detected on a locked paragraph in a future take —
> then it shows a small 'better version pending...' prompt."

**Delta vs today (IMPORTANT — narrows R1):** the current layer filter
(SPEC-parts-locking-and-layers) allows the whole ACCENTUATION layer
(bold/advice) on locked parts. The founder's rule is stricter: locked parts
take **nothing** except the confident-voice "better version pending…" prompt.
Accentuation on locked parts is now founder-overruled. Update
`filter_by_layer` semantics accordingly: `locked → {confident_voice_pending}
only`; `open → composition + accentuation` (subject to budget).

## 3 · Offers — rendering, source of truth, budget

- **Rendering registry** (visual style is DRIVEN BY THE INTERVENTIONS OPS
  TABLE, not hardcoded per surface):
  - **Confident Voice → Star** (qualitative badge — CONSTRUCT fence: badge,
    never a number).
  - **Other feedback → Underline or Bold text.**
- **Budget:** "Max 3 feedbacks surfaced per recording" — this is exactly
  `manager_engine.BUDGET_CEILING = 3` (Appendix H). The founder's iterative
  intent, verbatim: "the user corrects their presentation iteratively over
  multiple takes." Do not raise the ceiling to surface more at once.
- Offers ride the existing gate: lanes → `intervention_candidates.select()`
  → layer filter (as amended by §2) → arbitrate/budget → chips. The manager
  engine remains the sole door (#363); nothing bypasses it to the UI.

## 4 · The anchoring requirement (CRITICAL, founder-flagged)

> "To know which spoken fragment fits which text paragraph, we must show the
> user where they are in their practice *during* the official recording
> (e.g., displaying the first few words of that paragraph). This anchors the
> speech to the text so we can accurately map the new text to the old
> paragraph, even if the user massively diverges."

A live "you are here" display during recording: the current paragraph's
opening words on screen while the user speaks. This is F1-CORE adjacent — it
creates deterministic speech→paragraph anchors, the same mechanism family as
slide-click/two-clocks word bucketing. Design note for the build: the anchor
the user *sees* is the anchor the mapper *uses*; log the on-screen paragraph
id + timestamps with the take so alignment consumes ground truth rather than
inferring it.

## 5 · The coach panel

One scrollable **Lab** panel (per B7 in the handoff): star review as the
body, confident voices as the strip at the top, YouTube/uploaded-video
labeling a separate view in the same design language. **Two states
everywhere:**

| state | behavior |
|---|---|
| **Live users** | full feedback loop + ideal text generation |
| **Uploaded recordings** | **Confident-voice recognition ONLY** — "no ideal text rewriting since there is no next official recording" |

Coach flow, verbatim: "Each chunk of recording within a window goes to the
feedback engines and confident voice engine. All of that is sent to the
Coach for approval in the star review. Confident voice is blind
triangulation, but other feedbacks can be edited/commented on by the coach."

- **BLIND COACH holds:** confident-voice stays blind triangulation — the
  coach never sees the machine's guess while labeling.
- Non-confident-voice feedback is coach-editable/commentable before it
  surfaces (the existing why/replacement coach-final fold supports this).

## 6 · Definition of done (the founder's demo)

> "I record Take 2 → Blocking Loading Screen → I see Accept Chips (max 3) →
> I accept one → Button changes to 'Lock it' → I lock it. I continue this
> loop iteratively until the whole presentation is ready."

Plus coach side: open the Lab → star review populated from real takes →
label a confident-voice clip blind → edit one ordinary feedback.

## 7 · Restore-first sequence (founder answer #6: restore, then rebuild)

Verify at every step with the probes built 2026-08-10 — no step is done on
faith:

1. **Stars flow again** (flags now on): record ONE normal-length take (not a
   3-sentence one — short takes stamp a neutral acoustic read and cannot fire
   the acoustic lane; handoff §6.2). Check worker log for
   `moment_suggestion:` (SINGULAR) → expect `stored>0`, then
   `SELECT COUNT(*) FROM moment_suggestions WHERE created_at > now() - interval '1 hour';`
2. **Document layer on, config-first:** offers CANNOT surface without
   `LIVING_TRANSCRIPT_ENABLED` (hard prerequisite for all seven lanes) and
   the reshuffle-per-take stops ONLY with `MASTER_DOCUMENT_ENABLED` on —
   BOTH read per-process, so set on web AND worker together (CONFIG-FIRST
   rule; the worker writes the skeleton, the web serves it). Expect the
   first take after the flip to build the skeleton; the served document
   stops being the latest-take transcript.
3. **Offers appear:** next take → GET ideal text → `changes` non-empty (max
   3), chips render. If empty, §6.3 of the handoff enumerates the exact
   remaining conditions (span byte-match, `key_moments` must be empty,
   controls arms).
4. **Then and only then** build the new UI: blocking screen (§1), the
   accept→Lock-it state machine (§2), the rendering registry (§3), the
   anchoring display (§4), the coach panel rebuild (§5).
5. Somewhere in 1–4, land the sweep-chain ownership fix (handoff §6.5) —
   independent, small, stops the continuous query burn.

## 8 · Fences check (run once here so the build doesn't re-litigate)

- **AC-9 / CONSTRUCT:** chips, stars, underline/bold are qualitative; no
  score, ratio, or classifier output surfaces. Confident Voice is a badge.
- **BLIND COACH:** confident-voice labeling stays blind (§5, founder
  restated it himself).
- **L1:** offers are select-plus-light-polish, accept-gated; nothing
  AI-authors the canonical text; locks protect the user's chosen words.
- **L2:** ranking stays blended; the budget limits *surfacing*, not ranking.
- **L3:** coach edits/comments on ordinary feedback keep the whole-review
  capture; uploaded-mode confident-voice-only is a *source* restriction, not
  a narrowing of what the clone learns from live reviews.
- **LIVE LOOP:** every user-facing string in the new UI ("Working on your
  text", "Lock it", "better version pending...") is founder copy from this
  spec — anything beyond these exact strings needs sign-off before shipping.

`FILTER: ADVANCE-F2 (spec capture) — cat {F2/F1-SURFACE} — fences {clear} —
locks {clear} — redirect: n/a (founder-directed; restore-first per §7)`
