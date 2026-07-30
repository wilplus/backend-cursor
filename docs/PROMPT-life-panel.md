# The Life Panel — implementation document

**Status:** plan, not built. Spec of record — build prompts are
[PROMPT-BE-life-panel.md](PROMPT-BE-life-panel.md) and [PROMPT-FE-life-panel.md](PROMPT-FE-life-panel.md).
**Date:** 2026-07-26
**Gate:** two-tier — the principles engine is **public behind consent** (L-6); prayer and the
founder-only surfaces stay on the allowlist. `LIFE_PANEL_ENABLED` kills all of it.
**Scope:** absorb `principles-app`, `timeline`, and the daily/weekly governance system into
willpowerlab as gated trial features. Leave `pompeiana` standalone (see §3.4).

---

## 0. Decision filter

```
VERDICT:  JUSTIFIED-SCAFFOLDING (founder-directed)
CATEGORY: SCAFFOLDING
WHY:      Moves neither F1 load-bearing piece (per-slide transcription,
          best-per-slide ranking) nor F2. It is a new surface serving a new
          goal — a personal life-governance system. It passes on founder
          direction plus hard isolation from the live loop. No fence hit:
          nothing here surfaces a score to a product user (AC-9), no coach
          label leaks, no product copy on an F1 surface, L1/L2/L3 untouched.
PRECEDENT: Journal/CMS (PR #254) — founder-directed scaffolding, fenced off
          the live loop by an isolation test. Same shape, same fence.
GUARD:    Isolation is the price of admission. Any part of this that needs to
          modify an F1 path (record → transcribe → coach → read) is rejected
          and rerouted. The single permitted contact point is the chat router
          (§5), and it is guarded by a byte-identical-response test.
REDIRECT: Standing F1 target if this stalls — tighten word→slide bucketing at
          the two-clocks boundary.
```

---

## 1. The architecture decision

### 1.1 Answer: one codebase, one deploy, one database. `mvp.willpowerlab.com` as an alias, not a copy.

| | Decision |
|---|---|
| **Codebase** | `backend-cursor` + `frontend-cursor`. No new repo, no fork. |
| **Routes** | BE `/v2/life/*` · FE `/panel/*` |
| **Hostname** | `willpowerlab.com/panel` is canonical. `mvp.willpowerlab.com` MAY be added as a second hostname pointing at **the same deploy**, whose only effect is that `/` lands on `/panel` instead of the product home. |
| **Gate** | Server-side allowlist on `user_id`. Not a role, not a CSS hide — the payload omits the features entirely. |
| **Data** | Same Supabase instance, `life_*` table namespace, RLS on every table, never joined to product tables. |

### 1.2 Why not a full copy at `mvp.willpowerlab.com`

Rejected. The premise of the whole design is *the chat is for everything* — you type a case
into the same chat you already use, and the daily goal appears there each morning. A second
deploy forks the chat, the auth session, and the session state. Within a month every F1 fix
lands twice, by hand, and the divergence is how the live loop actually breaks.

A subdomain also buys **less isolation than it appears to**. If both hostnames read the same
Supabase — and they must, or you have two accounts — then a query bug leaks the same data
either way. The isolation that matters is at the table and RLS layer, not the DNS layer.

### 1.3 Why not "just leave them as separate apps and link out"

That is today's state, and it's what you asked to end. It also leaves your principles corpus
sitting in an unauthenticated Firestore document keyed by a 12-character share code (§4.2).

### 1.4 The two-tier gate (revised by L-6)

| Surface | Gate |
|---|---|
| Principles tab, `#` engine, setup, strategy docs, timeline | **consent** — public to any signed-in user who passed the consent screen |
| Prayer link, and anything founder-only | `LIFE_PANEL_ALLOWLIST` — comma-separated user ids, env var |
| All of the above | `LIFE_PANEL_ENABLED` — global kill switch, default OFF |

- **Not consented** → `/v2/life/*` returns 409 with a pointer to the Principles tab, except the
  consent and setup endpoints themselves. A `#` note is still stored (§6.2), not executed.
- **Not on the allowlist** → allowlisted entries are *absent from the payload*, and their
  endpoints 404 (not 403 — 403 confirms the surface exists). Nothing to discover, no copy.
- **Flag off** → every `/v2/life/*` route 404s and the menu payload is unchanged from today.

---

## 1.5 Locked system rules (founder, 2026-07-26)

These five override anything below them. They are not tradeable for convenience or capability.

**L-1 — The system never drafts reflections.** Reflections are written by the founder and
polished through the Ideal Text tool *externally*, then pasted in as structured input. This is
a manual copy-paste, **not an integration** — the panel makes no call into the F1 ideal-text
pipeline. The system may still propose the 👾 category (from the fixed six) and the ⚜️ new
principle one-liner, and may retrieve which existing principles bore on the case. It never
authors the reflective prose.

**L-2 (AMENDED 2026-07-26) — The system drafts the strategy docs; every change is gated.**
Superseding the "pure comparative mirror" form locked earlier the same day. GPT generates the
initial daily / weekly / monthly / quarterly / yearly / 5y / 10y / 20y documents from the
user's own setup answers, and proposes updates to them as new input arrives. Nothing lands
without an **approve** button, and every proposed change must display **one of the user's own
principles as its warrant**.

Two guards are mandatory consequences of this amendment, not optional extras:

- **L-2a — Immutable core.** Section I (The Anchor) and the *rank* of the three bets are
  hand-edited only. Never proposed, never redrafted. Without this, the standard the system
  judges alignment against is a standard the system wrote — and the 20-year vision can drift
  through eight months of individually reasonable approvals.
- **L-2b — Change budget.** At most **one** strategy-change proposal surfaced per day; the
  rest queue to the weekly review and arrive as a ranked batch of three. Unactioned proposals
  expire after two weeks rather than accumulating. Scarcity is what keeps "approve" meaningful;
  a daily stream of diffs becomes a rubber stamp within three weeks, and the rubber stamp *is*
  the drift.

**L-3 — Principles: surface paradoxes, never resolve them.** When two principles pull opposite
ways, both are shown and the founder weighs them. When a new principle appears to supersede an
old one, the system asks *"does this retire #12?"* — full veto; on "no", both stay active.

**L-4 — Zero nudges.** No pings, no notifications, no activity tracking, no silence detection,
no character checks. Not typing means living, not failing. The system is dormant until opened.

**L-5 — Application logging + 3-tier timeline.** Every time a principle is cited (in a case, a
comparison flag, or a conflict pair) it is logged as an application, so load-bearing principles
separate from decorative ones over months. The 60-year timeline renders at quarter / year /
decade zoom tiers.

**L-6 — Public feature, consented.** The Principles tab ships to **all users**, not the
allowlist. Page 1 explains what principles and `#` are; **page 2 is a consent screen** and must
be passed before any life data is written. Prayer stays coach-only for now. See §6.1 for what
going public costs.

### What L-4 costs, stated once

The system now catches only the drift you bring to it. Losing focus and not opening the app is
invisible to it by design. That is the accepted trade.

---

## 2. Privacy fence — load-bearing, read before writing any code

The corpus is not neutral productivity data. It contains addiction, sexual behaviour,
confession-shaped religious material, named third parties (family, ex-colleagues, a business
partner, women by first name), and financial history. It is being moved from a device-local
store into a server-backed multi-tenant product database.

**Hard rules, all testable:**

1. **RLS on every `life_*` table in its creating migration.** Not a follow-up sweep. The
   July 2026 audit found 57 exposed public tables; this class of data must not be number 58.
2. **`life_*` is never joined to a product table, and never written into the SHARED master
   document.** Amended 2026-07-26: principles / phrases / strategy MAY be injected into the
   **per-user** block of `master_doc_rag`, so untagged chat gets smarter for `#` users — the
   same mechanism the strong-sides library already uses.

   **Bound it exactly like the library does.** `services/master_doc_rag.py` caps the library at
   20 entries and trims each excerpt, and RULE K states the answer is "NEVER a dump of the
   strong-sides library." That cap is not cosmetic — the Lounge prompt already ran over its
   attention ceiling once (PRs #81–#89: rules moved out of the prompt into code, −22 lines of
   prompt, RULE-K hardening). Injecting 60 principles + a seven-horizon strategy document into
   that prompt would re-open the exact failure they fixed.

   Therefore: **retrieve top-N by relevance, hard cap, trim, never the whole corpus**, and
   re-run `tests/evals/master_doc_probe.py` with the injection on. If the probe baseline drops,
   the injection shrinks — the injection yields, never the probe.

   Injection happens at request time from the requesting user's own rows. Nothing crosses users.
   The isolation test asserts no product-side module imports the life module and that the
   *shared* master body is never written to.
3. **Third-party names.** The corpus names real people alongside claims about them. It stays
   private to one user forever — no sharing surface, no export-to-community, no "publish a
   principle" feature. If a principle is ever to be published, it is retyped by hand into the
   Journal, not exported from here.
4. **LLM calls.** Routing sends this content to GPT-4o. Use an API path with no training
   retention, log the *derivation output*, never the raw note body, and never send a full
   corpus dump as context — retrieve the ~10 relevant principles, not all 60.
5. **Own-data export and hard delete** ship in Phase 1, not "later". You must be able to get
   it out and wipe it.
6. **Pompeiana `scripture` never leaves the device** (§3.4).

---

## 3. Data model

Nine kinds, one items table, plus the case rows and the strategy doc. Sized for one user.

```
life_notes          raw capture, append-only, never edited, never deleted
  id · user_id · body · source ('chat'|'form'|'import') · created_at

life_cases          the Dalio reflection — five slots, one row
  id · user_id · case_at_hand · category (see 3.1) · principles_applied
  · reflections · occurred_on (nullable — some cases carry a date)
  · origin_note_id · created_at

life_items          everything else, discriminated by kind
  id · user_id · kind · title · body · status · order_key
  · horizon · due_label · due_at · bet_id · parent_id
  · origin_note_id · origin_case_id · created_at · updated_at

life_strategy       the weekly doc, versioned, never overwritten
  id · user_id · body · version · reviewed_on · created_at

life_days           one row per day — the daily card (§3.3)
life_weeks          one row per week — the weekly review (§3.3)
```

`kind ∈ { principle, win, phrase, bet, goal, task, habit, distraction, event }`

Note: the case fields live on `life_cases`, and the principle it produced is a `life_items`
row with `origin_case_id`. Splitting them (rather than the current app's single row) is
justified by the corpus: several cases produced **two** principles
("Focus on saving your own life first" + "Don't try to understand it all"), and several
carry **two** categories.

### 3.1 The mistake taxonomy — FIXED, six entries

Derived from the corpus. Not free-text, not emergent. GPT-4o must pick from this list; it may
*propose* a seventh only as a suggestion you approve.

| | Category | Corpus frequency |
|---|---|---|
| 👾 | Hubris | highest |
| 👾 | Blind spots | high |
| 👾 | Wishful thinking | high |
| 👾 | Too much pleasure | medium |
| 👾 | Frivolous decision making | low |
| 👾 | Perfectionist | low |

A case may carry more than one (the scooter/drift case carries Wishful thinking + Hubris).
Store as an array, render as multiple 👾 lines.

### 3.2 Bets and the goal cascade

The weekly doc's Section II is the spine. Three bets, **ranked, not equal**:

```
bet   rank 1  🟢 The Life      family · faith · community
bet   rank 2  🔵 The Company   willab — the active bet
bet   rank 3  🟣 The Dream     research · 7T · horizon 2035
```

Goals hang off a bet with a horizon and a due label copied verbatim from your own notation:

```
horizon  ∈ { now, month, quarter, year, five_year, ten_year }
due_label   free text as you write it — "[NOW]", "[Aug]", "[Dec]", "[Jul '27]", "2030", "2035"
due_at      parsed where unambiguous, nullable otherwise — the label is the source of truth
```

The rank is load-bearing: when the router proposes a task, it must be able to say which bet it
serves, and Bet 3 never outranks Bet 2 in a daily plan. That is your own stated rule
("It does not drive daily execution — Bet 2 does"), encoded.

### 3.3 The daily card and the weekly review

`life_days` — one row per date, the template rendered as data:

```
morning_checks      jsonb  — the habit checkboxes that ran
one_thing           text   — 🎯 TODAY'S ONE THING
focus_blocks        jsonb  — [{text, box}] ×3
distraction_flagged text   — the pre-start check, nullable
evening_habits_ran  bool
evening_one_thing   bool
evening_distraction text
evening_line        text   — "am I becoming the man I described?"
```

`life_weeks` — Sunday review: habits that failed and why · goals that moved + next action ·
main distraction · **one environmental change** · the becoming sentence.

The environmental-change field matters: your Section IV pairs every distraction with a design
response, not with willpower. `kind='distraction'` items carry `body` = the environmental
response, and the weekly review appends one new one per week.

### 3.4 Pompeiana — its own subdomain, shared login

`pompeiana.willpowerlab.com` — a **separate app** with its own deploy and its own screens, signed
in through willpowerlab auth. Not ported into the panel; linked from the hamburger (coach-only
for now).

Why it stays separate: zero-network by design, offline-first via service worker, 10 languages
from local JSON, and the README states the scripture text is deliberately NOT in the repo — the
user pastes it from their own legally-held Bible and it is stored locally only. Absorbing it
breaks the rule the app was built around and adds copyright exposure.

**Auth must be optional, or the offline guarantee dies.** This is the one hard constraint the
subdomain move introduces:

- Praying works **fully signed-out and fully offline**. Always. A login wall in front of a
  54-day novena breaks it on day 12 in a basement with no signal.
- Sign-in unlocks *cross-device continuity only*. Sign-out degrades to today's behaviour, not
  to a locked door.
- Sync payload is `{startDate, currentDay, progress, intention}` — nine integers and a string.
  **`scripture` never leaves the device.** Not synced, not backed up, not logged.
- SSO across `willpowerlab.com` → `pompeiana.willpowerlab.com`: cookie scoped to
  `.willpowerlab.com`, or a short-lived token handoff. Separate subdomain = separate service
  worker scope and a separate PWA install, which is correct and wanted.

The daily card's `☐ Pompeiana` checkbox stays a local habit tick in `life_days` — it does not
read the prayer app's state. Deliberate: coupling stays at zero.

### 3.6 Timeline — ported, re-skinned

Unlike prayer, the timeline lives **inside** the app at `/panel/timeline` and adopts the app's
visual design. The canvas renderer and interaction model port from the existing `index.html`;
the styling does not. Three zoom tiers (quarter / year / decade), 60-year horizon, goals as
bands coloured by bet (🟢🔵🟣 already match the existing `categoryColor` field).

### 3.5 Smart phrases

`kind='phrase'`, with a `collection` tag ("2022-24", "2025", "2026") and free text. Currently
these live inside the `prayer.v1` localStorage blob in principles-app — a single text field
being used as a dump. The importer splits that blob on quote boundaries into `phrase` rows;
anything it can't split stays as one note so nothing is lost.

The weekly doc's Section V ("The Principles Wall") is the same kind with `collection='wall'`.

---

## 4. Migration — the data-survival plan

**This runs before anything else is built.** Live data must survive and there is currently no
backup in an importable form.

### 4.1 Sources

| App | Where the data is | Export today |
|---|---|---|
| principles-app | localStorage `principles.v1` / `wins.v1` / `prayer.v1`, mirrored to Firestore collection `principles`, doc id = your sync code | **none** |
| timeline | localStorage `timeline.events.v1`, mirrored to Firestore project `timeline-aa2aa` | ✓ Export button |
| daily / weekly | the two documents pasted in this thread | manual |
| pompeiana | localStorage `pompeiana.v1`, device-only | **none** — stays put |

### 4.2 Exposure note

Both Firestore mirrors are unauthenticated. The 12-character sync code *is* the credential:
anyone holding it reads the entire corpus — every reflection quoted in this thread. There is
no rate limit and no audit trail. Migrating to willpowerlab auth + RLS closes this, and it is
an independent reason to do the migration beyond convenience.

### 4.3 Order of operations

1. **Add an Export button to principles-app** (~10 lines, standalone change to that repo, no
   willab code touched). Export on the device with the most data. This is step one because it
   is the only thing standing between you and an unrecoverable localStorage clear.
2. **Export timeline** with the existing button.
3. **Transcribe the daily + weekly docs** into `life_strategy` v1 and the bet/goal/habit rows.
4. Build the importers against those three JSON files.
5. Only after the imports verify: point the old apps at the new API, or retire them.

### 4.4 What the importer must preserve

- `createdAt` — the corpus spans 2022→2026 and the dates carry meaning.
- The exact category strings, mapped to the six-entry taxonomy; anything unmapped goes to a
  review queue rather than being silently coerced.
- Multi-principle and multi-category cases (they exist — see §3.1).
- The Polish text verbatim. No translation, no normalisation, no "cleanup" pass. Several
  reflections are code-switched mid-paragraph and that is the record.
- The manual order of the principles list (drag-to-reorder state) → `order_key`.

---

## 5. Chat integration — the one live-surface contact point

The panel's capture surface is the existing chat. This is the only place the trial features
touch shipped code, so it gets the tightest guard.

**Shape:**

```
POST /v2/chat/query
  ↓
  allowlist check  ──not listed──→  existing path, untouched, byte-identical
  ↓ listed
  life intent classifier (cheap, deterministic first, LLM second)
  ↓ no life intent
  existing path
  ↓ life intent
  /v2/life/* handler → response with a card + a link into /panel/<view>
```

**Guard:** a test that runs the full existing chat suite with a non-allowlisted user and
asserts responses are byte-identical to `main`. If that test is not green, the branch does not
merge. This is the same discipline as the Journal isolation test.

**Routing is by hashtag, not by classifier.** You declare the intent; the system does not
guess. Deterministic, free, and never wrong about what you meant.

| Tag | Route |
|---|---|
| `#principle` `#sin` `#mistake` `#error` `#problem` | principles engine — case → new principle |
| `#data` `#observation` `#reflection` `#idea` `#finding` | compared against the strategy doc; inconsistencies flagged, changes proposed under L-2 |
| `#win` `#wins` `#wygrane` `#liftmeup` | Wins |
| `#add` | add the text that follows to the smart-phrase wall |
| `#edit` | edit the editable fields of the daily card bubble above (§5.1) |
| *(none)* | capture only — no action, surfaced in a weekly untagged review |

**The phrase wall is a retrieval base, not a destination.** Every `#` note gets the single
best-fitting phrase from the wall attached to its answer — your own words returned to you at
the moment they apply. `#add` is the only way in.

Two rules on that: a **relevance floor** (if nothing clears the bar, attach nothing — a
mismatched aphorism on a `#sin` note about addiction is worse than silence), and **no repeat**
of the same phrase within a rolling window, or the wall collapses to three favourites.

`#liftmeup` is one word: hashtags break at whitespace, so `#lift me up` would parse as `#lift`
followed by prose.

**Discovery:** typing `#` alone opens an autocomplete list of the tags. Four aliases per route
are easy to build and impossible to memorise; the picker means the guide page never has to be
load-bearing. `#sin` stays a working alias but is kept off the public guide list.

**Intents, in build order:**

1. `capture` — every note lands in `life_notes` regardless of tag. Never fails, never blocks.
2. `case` (`#mistake`) — you paste the case and your own reflections. The system picks the 👾
   category from the fixed six, **retrieves which of your existing principles bore on it**, and
   proposes the ⚜️ one-liner for approval. It does not write the reflection (L-1).
   Slot 3 stops being a text field and becomes retrieval — this is the moment the archive
   turns into a machine. "I had no principles at that time" remains valid, and honest, for
   anything predating the corpus.
3. `goal-diff` (`#observation`) — compares the note against the whole document, reports any
   direct inconsistency (*"you noted X; Bet 2 short-term says Y"*), and proposes an edit with
   **one of your own principles displayed as its warrant** and an approve button. Subject to
   the L-2b budget: one per day, the rest queue to the weekly review. Never touches the
   immutable core (L-2a) — against that it reports, and stops.
4. `conflict` — when a retrieved set contains principles that pull opposite ways
   (*"Don't seek validation outside"* vs *"Seek honest feedback from trusted people"*), both are
   shown as a pair for you to weigh. The system never picks (L-3). This is what slot 3 asks for.
5. `retire` — a new principle that appears to supersede an old one prompts *"does this retire
   #12?"*. Veto is absolute; on "no", both stay active and the question is not re-asked.
6. `board` — "I'm stuck on X" routes to one of the five advisors from Section VI (Dalio,
   Munger, Jobs, John Paul II, Zanussi) by domain and answers in that lens. Says which one it
   picked and why. Holds your own line: none of them replaces prayer.
7. `lookup` — "what do I have on money?" retrieves the ~10 relevant principles/phrases, never
   the whole corpus.

**Propose, never commit.** Every derivation lands in a triage state and needs your approve.
A bad prompt day cannot silently corrupt sixty principles earned over four years.

**Pull, never push (L-4).** The daily card, the comparison flags, and the retire prompts all
wait for you to open the panel. Nothing notifies.

### 5.1 The daily card and `#edit`

For any user who has completed setup, the daily governance card is **generated at 05:00 and
waits silently** — no notification, no ping. Generation is scheduled; delivery is not.

`#edit <text>` edits the **most recent daily-card bubble** (not any bubble above it — the
target is pinned to the card, or the command is refused).

The card's **frame is fixed; its content is editable.** You cannot edit away the fact that
there *is* a ONE THING for the day; you can edit what that one thing is, and say why.

The "why" is the payload: it is captured as a candidate strategy correction, so tomorrow's card
is already right. If it also bears on a longer horizon, that becomes a normal L-2 proposal —
warrant principle displayed, approve button, inside the daily budget. A `#edit` never silently
reaches the 5- or 10-year document.

---

## 6. Views (the hamburger)

### 6.1 What shipping publicly costs (L-6)

The Principles tab is public. The corpus in §4 is the evidence for what people put in a box
like this: addiction, marriage doubt, money shame, named third parties. One founder's corpus in
a fenced table is a manageable risk. Every user's is a data-protection posture.

Required **in P1, not P4**: the consent screen (page 2 of setup), a retention statement, a
working hard-delete, and self-serve export. This roughly doubles P1 and is not negotiable
before the tab is visible to a non-allowlisted user.

**Decided (founder, 2026-07-26): no staged rollout.** The engine ships public with the guide —
no allowlisted first weeks. So the consent screen, retention statement, hard-delete and export
are launch blockers, not follow-ups, and the copy has no soft-launch in which to be tested.

### 6.2 The Principles tab is state-dependent

Three jobs, never on one page:

- **First visit** — page 1: what principles and `#` are, one page of text. Page 2: consent.
- **Setup (once)** — a Typeform-style flow, same pattern as speaking-project onboarding: daily
  / weekly / monthly / quarterly / yearly / 5y / 10y / 20y goals with dates, quantities, SMART
  fields. GPT then generates the document set. Editable forever after; downloadable as one
  document and re-uploadable.
- **Every visit after** — results: derived **principles on top** (click through to the full case
  and reasoning), the downloadable strategy document below.

**Setup is a hard gate (founder, 2026-07-26).** No progressive path: a `#` typed by a user who
hasn't completed setup does not run the engine. It returns a short redirect to the Principles
tab. Rejected alternative: engine-first, setup-later.

Three mechanics this makes load-bearing:

- **The typed note is kept, not dropped.** It lands in `life_notes` and is replayed through the
  engine the moment setup completes. Someone who reaches for `#mistake` is holding a thought
  they wanted recorded; losing it to a redirect teaches them the tag costs something.
- **Save-and-resume on the form.** Eight horizons is long enough that people will be
  interrupted partway. Without resume, an interruption is an abandonment, and the gate has no
  second door.
- **The redirect line is product copy on a live surface** → founder sign-off before it ships.

Consequence, stated once: the form is now the only entrance to the feature, so its completion
rate *is* the feature's adoption rate.

**Word round-trip:** re-upload produces a **diff you approve**, never a silent overwrite.
Arbitrary Word formatting reconciled back into structured sections will not round-trip cleanly,
so the diff is the safety net. Markdown or an in-app editor would be safer if you'll accept it.

### 6.3 The menu

| Entry | Source | Port cost |
|---|---|---|
| Principles | `life_cases` + `principle` items | UI exists — Next.js pages, swap localStorage for API |
| Wins | `win` items | UI exists |
| Phrases | `phrase` items | new, trivial list |
| Today | `life_days` + habits + one_thing | new — the daily card |
| Goals | bets → goals, ranked | new |
| Timeline | `event` items + goals with `due_at` | ported **and re-skinned** to app design (§3.6) |
| Distractions | `distraction` items | new, trivial |
| Strategy | `life_strategy` current version | new, read + edit + download/upload |
| Prayer | link out to `pompeiana.willpowerlab.com` (§3.4) | no port; coach-only for now |

The timeline is where goals become visible against the calendar: `[Aug]` goals render as
markers, bets as colour bands (🟢🔵🟣 already match the canvas's `categoryColor` field).

---

## 7. Phasing

| Phase | Content | Exit condition |
|---|---|---|
| **P0** | Inventory ✅ · **exports taken** · taxonomy frozen · strategy doc transcribed | three JSON files exist on disk |
| **P1** | BE: tables + RLS + `/v2/life/*` + allowlist + export/delete. Importers. | corpus is in Supabase, verified row-count and spot-check against the exports |
| **P2** | FE: `/panel` shell + hamburger + port principles/wins/timeline. Pompeiana linked. | you use the panel instead of the old apps for a week |
| **P3** | Chat: capture → case walker → daily card → goal diffs. Strategy doc as router context. | a case typed in chat becomes an approved principle |
| **P4** | Board · phrases · distractions · weekly review · (optional) pompeiana counter sync | weekly review runs in-app on a Sunday |

P1 before P2 deliberately: the data moves first. If the shell slips, the corpus is already
safe and RLS-protected. The reverse order gives you a nice shell over four silos, which is
where you are now.

Nothing is cut over big-bang. The old apps stay deployed and untouched until the matching view
exists and you have used it.

---

## 8. Open questions

1. **`mvp.willpowerlab.com` alias — want it, or is `/panel` enough?** It is ~10 lines of
   hostname routing and zero code fork. Only reason to want it: your daily landing page.
2. **Spendings app** — mentioned in the first message, never since, no path given. In or out
   of P1? Out is the cleaner default; the money shape is the one that doesn't fit `life_items`.
3. **Bet 3 in the daily card** — the daily shows 🟣 DREAM items, but the weekly says the dream
   "does not drive daily execution". Should the router be allowed to propose a daily task
   against Bet 3, or is it display-only?
4. **Case dating.** Most cases have no date; a few do ("03/01/2026"). Import puts undated
   cases at their `createdAt`. Acceptable, or do you want an undated bucket?
5. **Category proposal.** Locked at six. Confirm GPT may *suggest* a seventh for your approval,
   or should the list be closed entirely?

---

## 9. Migrations to run (when P1 lands)

Single file for the Supabase SQL Editor, idempotent (`IF NOT EXISTS`), RLS in the same file:

```
add_life_panel.sql   life_notes · life_cases · life_items · life_strategy
                     · life_days · life_weeks + RLS policies + indexes
```

Env to set: `LIFE_PANEL_ENABLED=0` (flip after FE deploy) · `LIFE_PANEL_ALLOWLIST=<user_id>`.
