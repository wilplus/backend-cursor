# Session log — 2026-08-13/14/15 · the confidence unification, pricing v3, and the publish rescue

**For:** artur@willonski.com · **Context:** the OpenAI-tooling handoff. This is the
narrative record of one working session. The authoritative maps stay
[`docs/HANDOFF.md`](HANDOFF.md) and [`AGENTS.md`](../AGENTS.md); this file explains
*why* things changed, which is the part a fresh agent cannot reconstruct from a diff.

Everything below is **merged to `main` in both repos. Nothing is left open.**

---

## 0. The headline

Three of the four things shipped this session were the same bug wearing different
clothes: **a surface reading a signal that no human was actually producing.** The
product looked healthy and was quietly serving nothing.

| The claim the code made | What was actually true |
|---|---|
| "This is a key moment" | Read a construct whose coach control was deleted 2026-08-07. Frozen. **Zero key moments produced since.** |
| "The coach marked this strong" | No picker exists. The FE wrote `tag: cs.tag ?? "strong"`, so it meant *a coach typed a note.* |
| "Publish the analysis" | The button POSTed to a **410 tombstone**. 46 August sessions, 0 published. |

Each one passed its tests. Tests pin behaviour; none of them could tell that the
*input* had stopped arriving.

---

## 1. The confidence unification (BE #443, FE #302) — the main event

**Founder ruling, verbatim:** *"we don't have key moments anymore, we have confident
voice only!!!"*

### 1.1 What "key moment" used to mean — five answers, no definition

An audit found *key moment* had five different implementations across five surfaces
and **no SPEC §17 entry**, which is exactly the defect §1.4 exists to prevent. The two
that mattered:

- **The game** counted `training_labels.value == 'challenge'`.
- **The feedback page and the paid unlock** counted `challenge` **OR** `threat`.

So a `threat` moment was simultaneously a key moment behind the paywall and a **wrong
answer** in the game. Worse, the coach's challenge/threat control was deleted from the
FE on **2026-08-07** when the charisma construct was retired. The corpus froze that day.
Every session reviewed since produced **zero** key moments on every surface — including
the one people pay for.

Supporting data from the founder's console: exactly **one** paid unlock has ever
happened (legacy credits, already empty), and only 12 `strong` tags exist in total.

### 1.2 The `strong` tag was not the fix — it was the same bug again

The first proposed replacement was the coach's `strong` tag. I drafted a §17 entry for
it before checking whether anyone ever chose it. **Nobody does.**
`CoachReviewOverlay.tsx:212` wrote `tag: cs.tag ?? "strong"`, and
`insights_payload.py` defaulted a missing tag the same way at publish. There is no
picker. The value was manufactured by the act of typing a note.

That mattered far beyond labelling, because `power_score` was reading it:

```python
_COACH_TERM = {"strong": 1.0, "to_work_on": -1.0}
_W_C = 2.0   # the DOMINANT weight — the largest single term in the blend
```

**Every snippet a coach happened to write on got +2.0 in the F1 ranking** — more than
content quality, more than panel confidence, more than the machine delivery read — for
a judgment nobody made. A commented-on phrase could outrank a measurably better one.

### 1.3 What a key moment is now

**Confidence quorum = yes.** `conf-q-v1`, SPEC §17. That is the whole definition.

It is not a new construct. It is the ternary the coach is *already* answering, settled
through the existing `services/label_quorum.py` ledger — which by construction excludes
self-reports (rule 2) and machine proposals (rule 1). So a key moment is always **at
least two humans, neither of them the speaker.** One rating is weak supervision, never
ground truth (rule 3) — which is what keeps one person's opinion out of a paywall.

New module `services/key_moments.py` is the single selector:

- `confidence_verdicts(db, ids)` → `{snippet_id: settled_value}`; unsettled snippets are
  **absent**, not present-with-None, so a front-runner can never be mistaken for a finding.
- `key_snippet_ids(db, ids)` → the subset that settled on `yes`.
- One batched read. A read miss degrades to empty rather than raising — a page says "no
  key moments yet" instead of 500ing, and we never claim a moment is key when we could
  not read the votes.

Four surfaces now call it: **the game**, **the feedback page**, **the paid unlock**, and
**the Voice Album's "coach agrees" leg**.

### 1.4 The ranking change (the one to review hardest)

- **`strong` is deleted from the coach term.** The coach's live positive verdict is not
  lost — it moves to the confidence panel, where the coach actually rates and where §17
  says what the rating means.
- **`to_work_on` survives.** No default ever produced it, so those rows were explicitly
  chosen. The picker that wrote them was removed 2026-08-07, which *freezes* the value;
  it does not falsify it.
- **§7.1's authority invariant is now stated relatively:** a vetoed phrase never reaches
  *the same phrase untagged*, because every other term is available to both. That holds
  at any weight — it cannot rot the way "swing 4.0 beats swing 3.0" could.

`cross_take_selection._tag_from_coach_label` was also deleted: it synthesised a coach
term out of the **retired charisma classifier** (`coach_label == "charisma"` → strong),
and the tag it produced was never the coach's real veto anyway.

### 1.5 Two more surfaces that were quietly lying

- **`user_patterns.classify_moment`** took `(coach_label, coach_tag)` and read
  `challenge`/`strong` → positive. Three of its four inputs were dead, so mined
  "patterns" described *what the coach commented on*, dressed as what the speaker does
  well. Re-pointed onto the settled verdict.
- **The Lounge bot** was told a moment was `Best (coach marked "strong")`. The coach's
  *words* are real and still go to the bot; the fabricated verdict around them does not.
  The librarian guardrail follows, and now says explicitly: *do not upgrade a note into
  praise the coach did not write.*

### 1.6 What was deliberately NOT done, and why

`strong_sides_library.tag` is `TEXT NOT NULL CHECK (tag IN ('strong','to_work_on'))`.
An untagged note has **no legal value** there. Dropping the publish-time default would
make every new coach note fail the write and vanish from the corpus **L3** requires.

So the column stays (never auto-drop) and the publish-time default stays — but it is now
**inert**: nothing anywhere reads it as evidence. It means "a note exists", which is all
it ever meant. Making it honestly nullable is a migration on a live table and is a
separate, deliberate piece of work.

**Locks:** L1 untouched. L2 intact — content + confidence still blend, confidence still
enters exactly once. L3 intact — the note corpus is preserved, including historical
`to_work_on` rows, versioned not rewritten (SPEC §3.2).
**Fences:** AC-9 / BLIND COACH — the quorum SELECTS and is never serialized; publish
still gates the album; a test asserts no verdict, no `confidence`, no `quorum`, no
retired construct on the feedback wire.

---

## 2. The publish rescue (BE #442) — the P0 nobody had noticed

Chasing "46 August sessions, 0 published", the founder ran a real coach review and hit a
greyed-out publish button. Two independent breaks under an all-or-nothing gate:

1. **The FE's publish button POSTed to a route that had been turned into a 410
   tombstone.** Un-retired.
2. **The only code that sets `results_published_at` sat behind an `/internal` route with
   no BFF path** — unreachable from the browser at all.

Fixed with a shared `publish_one_session()` helper (contract → `v2_publish_session_results`
→ `refresh_voice_album`, never raises), partial publish, and blockers reduced to
`NO_TAKES` — the library floor became an **advisory**, not a blocker.

That last part came out of my own design flaw: `get_coach_snippet_drafts` returns `[]`
identically for "read failed" and "no drafts", so blocking on it would let one DB hiccup
grey out the publish button. The floor is re-checked per take at publish against fresh
reads instead.

> **Correction on the record:** I first hypothesised the publish contract required
> direction labels on every snippet. That was wrong — `services/training_labels.py:65`
> has `require_all=False`. I flagged it explicitly because it would have sent the founder
> hunting a bug that does not exist.

---

## 3. Pricing v3 (BE #440, FE #298/#299/#301)

Sold ladder is now **free / practice / coaching / intensive**. `PRICE_VERSION = "2026-08-14-v3"`.

- `SOLD_TIERS` split from `TIERS`, so retired tiers (`starter`/`pro`/`max`) stay
  *resolvable* — renewals still grant — without being sellable.
- **A latent webhook bug surfaced and was fixed.** `stripe_subscription_tiers.py`
  validated against a hardcoded `("free","starter","pro","max")` allowlist, so a
  subscription on any new tier would have silently granted nothing. It now validates
  against `TIERS`.
- Coach reviews are metered in **slots, not tokens**. Five never-charged actions were
  deleted; `COACH_ACTIONS` fixed from the dead `coach_review` to `coach_feedback`.
- Migration `0274` widens the tier CHECK to old ∪ new — additive, idempotent, no row rewritten.
- The Lounge **top-up bubble** shipped (3 tier chips, one tap to Stripe, snooze keyed on
  `period_ends_at`).
- `coached` → **`coaching`** across both repos, per the founder: *"in my product I have
  called it coaching"*. Flagged at the time that the tier key is what users actually read
  (raw-key rendering), so this was nearly free before the first subscription and would
  have been a live-data migration after.
- Grandfathering and the custom-consultation SKU were **dropped entirely**, as instructed.

---

## 4. Also shipped this session

| PR | What |
|---|---|
| BE #435 | §17 `lexical-dilution-v1` Verbal lane |
| BE #436 | Voice Album reads in **presentation order** (slide asc, `entered_at` tie-break) — it had been serving capture order |
| BE #437 | Game queue voice-source ordering: own → consented app users → YouTube corpus |
| BE #438 | `AGENTS.md` + `docs/HANDOFF.md` in both repos |
| BE #439 | The **label quorum ledger** — machine routes/never votes, owner ≠ peer, singleton = weak supervision, IDK is a response |
| FE #297 | e2e flipped to **blocking** |
| FE #300 | Coach panel: publish when you want, work-first ordering, notes that autosave |

**The IDK ruling** (founder, verbatim): *"IDK strictly means 'ambiguous to judge' (it is
a valid perceptual rating of the audio, not a technical 'I can't hear the clip'
failure)."* Encoded as `IDK_VALUES = ("neutral",)` with `unrateable` as a separate
non-response flag. This is why an agreed-IDK settles as `perceptually_ambiguous` — a real
finding about the moment — and is still **not** a key moment.

---

## 5. Open items for you

1. **Publish the arc you reviewed.** The rescue is merged; Railway applies migration 0274
   on the next container start (`MIGRATE_ON_BOOT=1` — merging a migration *is* running it).
2. **Run the corrected `admin_users` console SQL** — data changes to that table are
   your console only, never via migration.
3. **Verify the Stripe tier env var from each service's boot log**, not the Railway UI —
   the UI shows what you set, the log shows what the process read (CONFIG-FIRST rule).

**Deferred, with nothing in flight** (so: DEFER, not DRIFT): full §12.2 metadata
migration; §11.5/§11.6 modal auto-open policy; game-queue multi-source ingestion (needs a
consent surface); making `strong_sides_library.tag` honestly nullable.

---

## 6. Notes for whoever picks this up

- **`scripts/local_ci.sh` is the gate**, not an ad-hoc `pytest && ruff && mypy`. It
  rebuilds the `checks` job environment (python 3.12, pinned `ruff==0.15.8`,
  `mypy==2.3.0`). A dev box's system `mypy` was a major version behind and passed five
  real type errors the pinned one catches. `test_local_ci_mirror.py` fails if the script
  and the workflow drift apart.
- **Actions minutes are exhausted for the month.** Both jobs fail at *runner allocation*
  in 2–3 seconds — zero billable ms, no logs (HTTP 404, because the job never started).
  That is not a code failure and re-running cannot help. Founder ruling: **do not
  upgrade**; merge on local evidence and document the override in the squash commit.
- **The prompt lockfile is load-bearing.** Editing prompt text fails
  `test_prompt_registry.py` until you run `python -m services.prompts.registry update`.
  It caught the Lounge-bot copy change in this session — working exactly as intended.
- **The decision filter in `CLAUDE.md` is not decoration.** Run it before starting, emit
  the verdict block, and stamp the PR. The two laundering moves to hunt hardest are
  *"more usage → more takes → better ranking"* (R3, engagement dressed as F1-support) and
  *"it's a foundation / it unblocks F1 later"* (R11 — demand the named, in-flight task).
- **The lesson of this session, if there is one:** when a surface stops producing output,
  check whether its *input* still exists before debugging the surface. Three separate
  systems here were faithfully executing rules about data that had stopped arriving —
  and every one of them had green tests.
