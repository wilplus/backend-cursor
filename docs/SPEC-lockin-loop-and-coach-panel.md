# SPEC — The lock-in loop, offers, and the coach panel

**Status:** FOUNDER-DECIDED 2026-08-10; paragraph versioning, feedback
families, and blindness boundary superseded by the founder's 2026-08-26 lock.
The current rules below and `CANONICAL_PRODUCT_CONTRACT.md` win over historical
quotes retained elsewhere.

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

## 2 · The paragraph state machine (feedback, commit, and root)

Editing, resolving Feedback, and locking are distinct transitions. After the
frozen Feedback inventory for a Paragraph is resolved, the user must explicitly
choose **Lock for next Take** or **Keep evolving**. A lock is the only hard
version commit; it preserves the exact Paragraph words through future Takes.
Editing or accepting a rewrite saves words but does not silently lock them.
Keep evolving explicitly permits a later Take's selected working version to
replace that Paragraph; locked Paragraphs remain exact.

State machine per Paragraph:

```
open ──Take Feedback──► review ──resolve all──► commit boundary
  ▲                                              │              │
  │                                      Keep evolving     Lock for next Take
  │                                              │              │
  └──────────────────────────────────────────────┘              ▼
                                                             locked
                                                               │
                                                    ask exact orange root
                                                    │ choose │ skip
```

Locked words never change without an explicit edit/unlock. Future vocal
Feedback may still refer to them, but it cannot mutate them. Each edit, lock,
unlock, keep-evolving choice, and root choice appends an immutable revision.
After locking, orange is a separate exact-span choice: accept the proposed
root, choose different exact words in the same Paragraph, or skip. Editing or
unlocking clears stale root metadata.

## 3 · Offers — rendering, source of truth, budget

- **Frozen contract:** every valid Take returns exactly three Feedback items:
  the best Confident Voice candidate, the best actionable verbal/structure
  improvement, and the best evidence-backed praise.
- **Ranking:** each family evaluates its complete pool and selects the best
  available candidate, not the first match. Weak evidence uses tentative
  language. It may be modest; it may never be invented.
- **Stability:** all three identities are frozen before the user responds.
  Resolving one never reveals a fourth or substitutes a hidden candidate.
- Offers ride the existing gate: lanes → `intervention_candidates.select()`
  → layer filter → arbitrate/freeze → Feedback. The manager
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

- **BLIND COACH holds:** before the coach submits an immutable independent
  judgment, the coach sees neither the machine prediction, user self-report,
  nor other ratings. They become visible only after submission. The original
  judgment cannot be edited; reconsideration is a new revision with its own
  timestamp and provenance.
- Non-confident-voice feedback is coach-editable/commentable before it
  surfaces (the existing why/replacement coach-final fold supports this).

## 6 · Definition of done (the founder's demo)

> "I record Take 2 → Blocking Loading Screen → I receive exactly three
> frozen Feedback items → I resolve them → I choose Lock for next Take or
> Keep evolving per Paragraph → after locking I choose or skip its exact
> orange root phrase. I continue until the presentation is ready."

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
3. **Feedback appears:** next Take → GET Ideal Text → the frozen exact-three
   set renders. If absent, §6.3 of the handoff enumerates the exact
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
