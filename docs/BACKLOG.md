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

**Where the documents live.** Both are JSX in the frontend repo, not markdown:

| Published as | Source file | Version |
|---|---|---|
| `willpowerlab.com/terms` | `frontend-cursor/src/app/terms/page.tsx` | Terms of Service **v1.1**, effective 2026-08-13 |
| `willpowerlab.com/privacy` | `frontend-cursor/src/app/privacy/page.tsx` | Privacy Policy **v1.1**, effective 2026-08-13 |

Each item names its exact section below. Both files also carry the same list in
their docblocks, so it is visible to whoever edits the copy next. The engine-side
view — which detector each obligation binds — is the *legal constraint* column on
the intervention-contract page.

**L-1 — Model-improvement opt-out** · Feature · ⛔ BLOCKING THE NEXT REVISION
> As a user, I want to stop my recordings being used to train the models,
> without giving up the Service.

**Document:** Terms **§4** "How your content improves the Service" · Privacy
**§5** "How your content improves our models" and **§11** (Art. 21 bullet).

The only user-facing consent flags are `mic` / `share` / `email` / `terms`
(`add_consent_preferences_to_user_settings.sql`); there is no
model-improvement flag, and the frontend has no account-settings surface at
all. **The claim was REMOVED from both documents rather than published false.**
Terms §4 and Privacy §5 now offer only the Art. 21 objection route, served by
hand at the contact address. Restore the sentence when the toggle ships.

**Note the operational cost while it is open:** Privacy §5 says "write to us and
we will stop using your content to improve our models." There is no exclusion
flag, so honouring one objection today means finding and pulling that user's
labels by hand — inside Art. 12(3)'s one month.

**L-2 — Per-recording sharing consent** · Feature · Published, unbuilt
> As a user, I want to choose per recording whether other people can hear it,
> and take it back later.

**Document:** Terms **§5** "Community sharing and peer review" · Privacy **§7**
of the same name.

Both say sharing is "opt-in, per recording, and revocable at any time".
`share_consent` is one account-level boolean scoped to the coach — not
per-recording, and not the peer-rating surface. Needs a per-snippet consent row,
a revocation path that pulls the extract from circulation, and a control in
front of `/game`.

**The most acute item on this list.** It is the only one describing a
*disclosure to third parties*: if `/game` is reachable by real users today, one
user's voice is audible to another under consent that does not have the shape
the published text describes. Confirm reachability first; everything else here
is a right we serve slowly, this one is data already moving.

**L-3 — User data export** · Feature · Published, unbuilt
> As a user, I want to download my recordings, transcripts and Ideal Text
> before I delete my account.

**Document:** Terms **§10** "Account termination" (final sentence) · Privacy
**§11** (Art. 20 portability bullet).

No user-facing export route exists — the export routes here are internal
(annotation export, dev-tasks) or belong to the Life panel. Portability
requests are served by hand meanwhile, against Art. 12(3)'s one-month clock.

**L-4 — Account deletion** · Feature · Published, unbuilt
> As a user, I want to delete my account and have my content go with it.

**Document:** Terms **§10** "Account termination" (opening sentence) · Privacy
**§11** (Art. 17 erasure bullet).

Per-take and per-session deletes exist; whole-account erasure does not. Manual
until it does.

**L-5 — Voice-data retention maximum** · Ops · Published as criteria
> As a user, I want to know my audio does not sit on a disk forever.

**Document:** Privacy **§10** "Data retention" (Voice Data bullet).

Privacy v1.0 promised audio was "automatically deleted no later than 30 days".
**No retention or purge job exists** — the Railway crons are annotation-export,
dev-bugs, drift, life-reminders, migrate, web and worker. v1.1 states retention
*criteria* instead (permitted by Art. 13(2)(a)), but the founder's original
intent was a hard maximum. Set the period, then build the job that enforces it.
Art. 5(1)(e) storage limitation is the exposure.

**L-6 — Sub-processor DPAs** · Ops · Confirm
**Document:** Privacy **§9** "Sub-processors and international transfers".

The table now lists **Sentry, Resend, Cloudflare R2 and Vercel** alongside
Supabase, Railway, OpenAI and Stripe. Confirm a DPA and a transfer safeguard is
actually in place for each — **§9 asserts both, so an unsigned DPA makes the
published policy false.**

**Vercel is the lesson, not just a row.** It was missing from the first draft
because the audit read the repository, and the repository never names its own
host — it surfaced only when Vercel ran the checks on the v1.1 PR. **A
sub-processor list cannot be audited from the tree alone.** The next pass reads
the Vercel and Supabase dashboards, DNS, and the Railway service variables.

**L-7 — Terms §9 consumer-law review** · Ops · Confirm
**Document:** Terms **§9** "Payments, plans, and cancellation".

§9 was rewritten away from the approved draft because the draft described
one-time per-presentation unlocks while the live model is recurring monthly
plans funding a token wallet. The rewrite is structural and unreviewed.
Two open points: whether the 14-day withdrawal wording is right for a
subscription, and whether the express immediate-performance consent is actually
captured at checkout — **it was not found in the token-wallet components.**

**L-8 — Prior-notice obligation** · Ops · Confirm
**Document:** Terms **§16** "Changes to these Terms" · Privacy **§14**
"Changes to this Policy".

Both require notice for material changes, and v1.1 is material. Confirm whether
any user accepted v1.0; if so, they are owed notice. `user_consents` is the
ledger that answers this — one row per accepted version.

---

### Added 2026-08-13 (second pass) — obligations that exist with no document at all

L-1 to L-8 are commitments the published copy makes. **These three are the
reverse: obligations that bind us whether or not anything is written, and
nothing is written.** None of them lives in Terms or Privacy — each needs its
own artefact.

**L-9 — Data Protection Impact Assessment (GDPR Art. 35)** · Ops · ⛔ None exists
> As the controller, I need to have assessed the risk before the processing
> runs, not after.

**Document: NONE — a DPIA is a standalone internal record.** It is not part of
Terms or Privacy and cannot be satisfied by them; it is what a regulator asks
for first. Nothing in either repo resembles one.

Art. 35(3) triggers this is close to: systematic and extensive evaluation of
personal aspects by automated processing (delivery profiling across takes), and
processing that may involve special-category data (the voice inference behind
`voice_confidence` / CONF). A DPIA has to be in place **before** the processing
starts, so if it is required it is already late. It also feeds L-11 and the
open Art. 9 question directly — do this one first, because its output decides
what the other two say.

**L-10 — Records of processing activities (GDPR Art. 30)** · Ops · ⛔ None exists
> As the controller, I need a written record of what we process and why.

**Document: NONE — a standalone processing register**, internal, produced on
request to the UODO. Privacy §2 and §9 contain much of the raw material
(categories, purposes, recipients, transfers) but a privacy policy is not an
Art. 30 record and does not discharge the duty.

The under-250-employees exemption in Art. 30(5) **does not apply** here: it
lapses when processing is other than occasional, or involves special-category
data. Recording every user continuously is not occasional. Cheap to produce
once — mostly assembling what Privacy §2, §9 and §10 already say.

**L-11 — EU AI Act, emotion recognition** · Ops · ⛔ Unassessed
> As the operator, I need to know which AI Act duties attach to inferring a
> speaker's state from their voice.

**Document:** the *prohibition* is already mirrored — Terms **§7**, final
bullet, bans employer and educational-institution use and promises account
termination. **The transparency duty has no document**, and the disclosure that
would carry it is Privacy **§6** "What we infer from your voice".

The system infers a state of the speaker from voice, which is what the AI Act's
emotion-recognition provisions govern: prohibited in workplace and education
contexts, and subject to a duty to inform people exposed to it elsewhere.
Applicability dates phase in through 2025–2026 — **verify the current position
with counsel rather than assuming.**

Two things to settle: whether our framing (coaching the speaker on their own
delivery, at their own request) lands inside or outside the emotion-recognition
definition, and whether Privacy §6 as written already discharges the
transparency duty or needs an in-product notice. Engine-side, this binds
exactly one detector — **CONF** — and nothing else on the intervention
contract; the other seven rows read text and infer nothing about the person.

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
