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

## Epic L — Legal commitments (opened 2026-08-13)

Terms of Service v1.1 and Privacy Policy v1.1 went live on 2026-08-13. A
pre-publication audit against the code found several commitments in the copy
that the system does not yet keep. The founder ruled: publish, drop the claim
we are furthest from (the model-improvement opt-out), and track the rest here.

**Each item below is a live legal exposure, not a feature request.** The
published copy is what a user — or the UODO — will hold us to. Either build it
or amend the copy at the next revision; leaving it in this list indefinitely is
the one outcome that is not acceptable.

**L-1 — Model-improvement opt-out** · Feature · ⛔ BLOCKING THE NEXT REVISION
> As a user, I want to stop my recordings being used to train the models,
> without giving up the Service.

The only user-facing consent flags are `mic` / `share` / `email` / `terms`
(`add_consent_preferences_to_user_settings.sql`); there is no
model-improvement flag, and the frontend has no account-settings surface at
all. **The claim was REMOVED from both documents rather than published false.**
Terms §4 and Privacy §5 now offer only the Art. 21 objection route, served by
hand at the contact address. Restore the sentence when the toggle ships.

**L-2 — Per-recording sharing consent** · Feature · Published, unbuilt
> As a user, I want to choose per recording whether other people can hear it,
> and take it back later.

Terms §5 and Privacy §7 say sharing is "opt-in, per recording, and revocable at
any time". `share_consent` is one account-level boolean scoped to the coach —
not per-recording, and not the peer-rating surface. Needs a per-snippet consent
row, a revocation path that pulls the extract from circulation, and a control
in front of `/game`.

**L-3 — User data export** · Feature · Published, unbuilt
> As a user, I want to download my recordings, transcripts and Ideal Text
> before I delete my account.

Terms §10 promises it and Privacy §11 leans on it for GDPR Art. 20. No
user-facing export route exists — the export routes here are internal
(annotation export, dev-tasks) or belong to the Life panel. Portability
requests are served by hand meanwhile, against Art. 12(3)'s one-month clock.

**L-4 — Account deletion** · Feature · Published, unbuilt
> As a user, I want to delete my account and have my content go with it.

Terms §10 says "you may delete your account at any time"; Privacy §11 promises
Art. 17 erasure. Per-take and per-session deletes exist; whole-account erasure
does not. Manual until it does.

**L-5 — Voice-data retention maximum** · Ops · Published as criteria
> As a user, I want to know my audio does not sit on a disk forever.

Privacy v1.0 promised audio was "automatically deleted no later than 30 days".
**No retention or purge job exists** — the Railway crons are annotation-export,
dev-bugs, drift, life-reminders, migrate, web and worker. v1.1 states retention
*criteria* instead (permitted by Art. 13(2)(a)), but the founder's original
intent was a hard maximum. Set the period, then build the job that enforces it.

**L-6 — Sub-processor DPAs** · Ops · Confirm
Privacy §9 now lists Sentry, Resend and Cloudflare R2 alongside Supabase,
Railway, OpenAI and Stripe — added on code evidence. Confirm a DPA and a
transfer safeguard is actually in place for each. The frontend's hosting
provider is still unidentified and unlisted.

**L-7 — Terms §9 consumer-law review** · Ops · Confirm
§9 was rewritten away from the approved draft because the draft described
one-time per-presentation unlocks while the live model is recurring monthly
plans funding a token wallet. The rewrite is structural and unreviewed.
Two open points: whether the 14-day withdrawal wording is right for a
subscription, and whether the express immediate-performance consent is actually
captured at checkout — **it was not found in the token-wallet components.**

**L-8 — Prior-notice obligation** · Ops · Confirm
Terms §16 requires reasonable prior notice for material changes. v1.1 is
material. Confirm whether any user accepted v1.0; if so, they are owed notice.

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
