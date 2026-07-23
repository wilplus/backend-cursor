# willab backlog — status as of 2026-07-23

**Theme: human feedback on how you present — for $5 each.**

The versioning engine is now built (was the cluster the founder re-described
most). This backlog is updated against shipped commits; each item carries a
user story.

## What shipped since the last backlog

| Item | Shipped as | Status |
|---|---|---|
| V-1 approval memory / no-revert | #223 ledger · #224 protected phrases · #229–#232 | ✅ DONE |
| V-2 sub-chunk analytics | #238 emphasis · #223 replace narrowing | ✅ DONE |
| V-3 versioning spec | #237 `VERSIONING_SPEC.md` | ✅ DONE |
| R-1 re-read button while loading | #234 + #235 | ✅ DONE |
| C-1 audio-only annotation mode | #239 | ✅ DONE |
| C-3 v1-limitations decision | #240 — SHIP | ✅ CLOSED |
| Master Document (new) | #232 | ✅ DONE |
| Full-transcript ideal text (new) | #229 | ✅ DONE |
| Context-aware recording + per-project badge (new) | #233 · #236 | ✅ DONE |

---

## Epic 1 — Versioning & Assembly Engine (the differentiator — now built)

**V-1 — Approval memory & no-revert** · Feature · ✅ DONE
> As a speaker across takes, I want changes I approved to stay applied and
> never re-surface, so my text improves instead of resetting.

Phrase-keyed decision ledger bakes approved changes into every later
version; dismissed never return; wording repeated in ≥2 takes locks as
"your voice"; reasoning shows only for the current step's new changes.

**V-2 — Sub-chunk emphasis** · Feature · ✅ DONE
> As a reviewer, I want an edit to mark only the exact phrase, so the whole
> paragraph isn't underlined.

300-char sections for structure; replace/emphasis target 20–50 char
sub-spans (emphasis narrows to the say-it-stronger key phrase).

**V-3 — Versioning spec** · Documentation · ✅ DONE
> As a builder, I want the evolution rules pinned once, so future work
> doesn't re-derive intent.

`VERSIONING_SPEC.md`, confirmed against shipped code. The founder's
understanding was correct and is now the spec.

**MD-1 — The Master Document** · Feature · ✅ DONE (new)
> As a speaker, I want one text per project that evolves take by take —
> best-take-wins by approval, each fragment badged with its take of origin.

Persistent per-project master; new takes offer approve-gated block
upgrades → the 48/20/32 mix.

**E-1 — Progressive shortening** · Feature (large) · P2 — NEXT candidate
> As I get fluent, I want the ideal text to compress from full transcript →
> concepts + key words, so it becomes a cue sheet, not a script.

Now buildable — the engine underneath is stable.

## Epic 1b — Context-Aware Recording & Projects (new — shipped)

**CR-1 — Record inside a project** · Feature · ✅ DONE
> As a speaker continuing a project, I want the "record another take" button
> to drop me straight into recording with the project's setup, not back out
> to the chat.

`continue_arc_id` (strict, no heuristics) + `GET …/setup` inheritance.

**CR-2 — Per-project take numbering** · Feature · ✅ DONE
> As a speaker with several projects, I want each to keep its own count
> (3.0 vs 15.0), never a global tally.

`take_count` badge, per-arc, climbs on every take.

---

## Epic 2 — Ideal-Text & Recording UX

**R-1 — Re-read button appears only when loading is done** · Bug · ✅ DONE
> As a speaker who just re-read, I want the next-take button only when
> processing is finished, so I don't start a take mid-load and orphan the
> mic.

`reread_done` gates on completion; `reread_processing` holds the loading
state; a live mic can never outlive the recording screen.

**D-1 — Ideal-text card chat-bubble styling** · Design→Build · P2
> As a user in the chat, I want the ideal-text card to read as a distinct,
> polished attachment.

**D-2 — Paragraphs of ≤5 lines** · Polish · P3
> As a reader, I want the ideal text in short paragraphs, for reading ease.

**D-3 — Pace-up UI (tag + 1-2-3 list + inline playback/mic)** · Feature · P2
> As a speaker, I want a "pace↑" cue with an approvable list and a
> hear-it/re-record-it control in the same modal.

**E-2 — Text-mode toggle (full ↔ key-words / presentation mode)** · Feature · P2
> As a presenter, I want to switch between the full text and a
> key-phrase/milestone view to track where I am.

**E-3 — Length-selection explainer overlay** · Feature · P2
> As a user picking 30/45/60 min, I want the cost/coverage explainer before
> committing.

---

## Epic 3 — Coach Side & Annotation Goal

**C-1 — Audio-only annotation mode** · Feature · ✅ DONE
> As the coach, I want to upload audio and get labelable snippets without
> ideal-text assembly, to bank annotations toward 1,000.

`POST /coach/annotation-uploads` → the existing queue + snippet UI,
`annotation_mode` on the row.

**C-3 — v1-limitations gate** · Question · ✅ CLOSED — SHIP (A closed by V-2;
B a later enhancement).

**C-2 — Snippet-length adjustment (coach side)** · Feature · P2
> As the coach, I want to adjust snippet length, for cleaner shadow-model
> training data.

---

## Epic 4 — Content Safety / Threat-Language (P2)

**S-1** *spot threat/challenge language at the content level from a rationaled
wordlist.* · **S-2** *detect that tone in the voice when the words don't
carry it (ML).* · **S-3** *cap on corrected flags? + label swears
"unnecessary"* — partly answered: the profanity lane already labels swears +
narrows to the carrying sentence, and suggestion caps are per-take
constants; S-1/S-2 remain net-new.

## Epic 5 — Setup, Context & Simulation (P2; X-4 PARKED)

**X-1** context-document upload (≤20 pp) · **X-2** simulation
context-generation engine · **X-3** timeframe-fit note per take · **X-4**
simulation scenario design (parked — needs a plan on paper first).

## Epic 6 — Onboarding (P2)

**O-1** screen-by-screen onboarding, PM-designed.

## Verify — both closed ✅

VER-1 (new project mid-arc) and VER-2 (auto-minor / approve-major behavior)
— confirmed and baked into the spec.

---

## No open decisions. C-3 was the last one, and it shipped.

## Order of attack (engine + annotation lever now done)

1. **T5** — run the end-to-end tester gate (validates the engine delivers a
   pay-worthy text).
2. **E-1** progressive shortening — highest-leverage remaining engine work,
   now on stable ground.
3. **Coach/safety feeders** — C-2, S-1/S-2 (feed the shadow model + the
   annotation goal).
4. **UX & setup** — D-1/D-3, E-2/E-3, X-1/X-2/X-3.
5. **O-1 onboarding** — once the loop is feature-complete.
6. **Polish** — D-2, whenever there's slack.
