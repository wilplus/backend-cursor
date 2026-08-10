# SPEC — Immutable source data and provenance

**Status:** DESIGN, awaiting founder review. Nothing here is built.
**Phase A of Task III.** Phase B (quorum + cross-user consent) is ON HOLD
pending the privacy/TOS review — nothing in this document reads another
user's data.

---

## 0 · The one-paragraph version

Three kinds of fact decide what a stored number *means*: the **detector**
that produced it, the **threshold** it was judged against, and the **label** a
human attached. Change any one without a version stamp and every historical
row silently changes meaning — while still looking perfectly valid. This spec
makes each of the three versioned and append-only, so a comparison across time
is either provably like-for-like or provably refused.

---

## 1 · The concrete danger, stated in the founder's own terms

> "I have a system that compares across databases, so if fillers are corrupted
> all my data goes nuts."

That is not hypothetical. Here is the entire filler detector today
(`utils/metrics.py`):

```python
DEFAULT_FILLERS = ["um", "uh", "like", "you know", "er", "ah", "so"]
```

A bare module-level list, **no version anywhere**. Add "actually" and every
`fillers` figure ever computed becomes incomparable with every figure computed
afterwards. Nothing in the schema records which list was in force, so:

* no query can separate the two eras;
* the drift layer reads a step-change as a *behaviour* change in the speaker;
* the corpus mixes both silently and cannot be un-mixed afterwards.

`so` in that list is worth staring at: it is a filler *and* a conjunction, so
this detector's precision is a real open question — and the day someone
tightens it is exactly the day the history breaks.

**The same shape applies to two more things.** `fire_at` thresholds (all `None`
today — so the *first* value set is itself a version-0 → version-1 event), and
coach labels, which are currently overwritten in place on a re-rate.

---

## 2 · What is already right (the pattern to extend, not invent)

Three places already do this correctly, and the design below is deliberately
the same shape rather than a new idea:

| where | what it stamps | why it works |
|---|---|---|
| `dimension_evaluations` | `benchmark_version` **in the uniqueness key** | re-evaluating under the same version REPLACES; a new version ADDS. Both eras coexist and are separable |
| `reference_distribution` | `version` (`frozen_v1`, `frozen_v2`…) | a re-fit mints a new frozen reference rather than editing the old one (Appendix G.7) |
| `intervention_arms` | `control_salt`, `withhold_salt`, rates | the policy is stamped **per row**, so rows either side of a salt change are two experiments with no way to confuse them |

The gap is that the *inputs* to those tables — detector definitions,
thresholds, labels — carry no such stamp. A versioned evaluation of an
unversioned detector is a precise measurement of an unknown thing.

---

## 3 · Proposed schema

Three tables. All append-only; none replaces an existing table.

### 3.1 `detector_version` — what produced a number

```
detector_version
  detector_id      TEXT        -- 'fillers', 'pause_ms', 'dynamic_db', …
  version          TEXT        -- 'fillers-v1'
  definition       JSONB       -- the lexicon / parameters, VERBATIM
  definition_hash  TEXT        -- sha256 of the canonical definition
  fit_stage        TEXT        -- 'bootstrap' | 'provisional' | 'frozen'
  effective_from   TIMESTAMPTZ
  retired_at       TIMESTAMPTZ NULL
  note             TEXT
  PRIMARY KEY (detector_id, version)
```

**`definition_hash` is the load-bearing column.** A version string is a promise
a human can forget to keep; the hash is a fact. Boot-time check: hash the live
`DEFAULT_FILLERS`, compare to the row for the current version, and **refuse to
start** (or hard-log, see §5) on a mismatch. That converts "someone edited the
lexicon and forgot to bump" from an invisible corruption into a loud failure.

**`fit_stage`** is the founder's requested field and answers a different
question from `version`: *how much should you trust this?*

* `bootstrap` — first pass, small n, expected to move
* `provisional` — stable but not defended
* `frozen` — never changes again; a change mints a new version

A comparison that spans two `fit_stage`s is not automatically wrong, but it is
never automatically right either — analysis can filter on it, which it cannot
do today at all.

### 3.2 `label_revision` — append-only coach labels

Coach labels are currently **overwritten**: a re-rate replaces the rater's row
(`state_ratings`). So "did this coach change their mind, and when?" is
unanswerable, and a mistaken bulk edit is unrecoverable.

```
label_revision
  id             BIGSERIAL PRIMARY KEY
  snippet_id     TEXT NOT NULL
  rater_id       TEXT NOT NULL
  state_id       TEXT NOT NULL
  value          TEXT NULL          -- yes | no | neutral
  unrateable     BOOLEAN NOT NULL DEFAULT false
  question_id    TEXT NULL
  question_version TEXT NULL
  saw_model_output BOOLEAN NOT NULL DEFAULT false
  supersedes_id  BIGINT NULL        -- the revision this replaced
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
```

`state_ratings` stays exactly as it is and remains the "current answer" read —
**no read path changes**. This table is written alongside it, and the current
row becomes a derived view of the newest revision per (snippet, rater, state).

Nothing is deleted, ever. A re-rate appends and points `supersedes_id` at what
it replaced.

**Why this matters beyond tidiness:** invariant I1 hard-codes
`saw_model_output: false`. If a surface ever regresses and shows a machine read
next to the controls, revisions let you find *exactly which rows* were written
in that window. With overwrite-in-place you can only throw the whole corpus
away.

### 3.3 `threshold_version` — what a number was judged against

```
threshold_version
  dimension_id     TEXT
  version          TEXT
  fire_at          DOUBLE PRECISION NULL
  clear_at         DOUBLE PRECISION NULL
  tier             TEXT              -- T1|T2|T3|CORPUS_REL
  fit_stage        TEXT
  effective_from   TIMESTAMPTZ
  note             TEXT
  PRIMARY KEY (dimension_id, version)
```

Every `fire_at` in `dimension_registry` is `None` today, so **nothing has been
judged against a threshold yet** — which makes this the cheapest possible
moment to add the stamp. The first real threshold is itself a versioning event,
and D24 already says T1/T2 thresholds must never adapt; this is where that stops
being a comment and becomes a row.

---

## 4 · What this does NOT do

* **No read path changes.** Every existing consumer keeps reading what it reads
  today. These tables are written beside the current ones, not in front of them.
* **No backfill of history.** Rows written before this shipped genuinely have
  unknown provenance, and stamping them with today's version would be a
  *fabricated* provenance — strictly worse than a null. They stay unstamped and
  are therefore visibly, honestly, "pre-provenance".
* **No cross-user reads.** Phase B is on hold; nothing here touches another
  user's data.
* **No new user-facing anything.** AC-9 is untouched: none of this reaches a
  client schema.

---

## 5 · The one decision I need from you

**What should a definition-hash mismatch do on boot?**

* **(a) Refuse to start.** Maximum safety: corrupt data becomes impossible,
  because the process that would write it will not run. Cost: an unbumped
  lexicon edit takes production down.
* **(b) Log loudly and keep running, marking new rows `provenance: suspect`.**
  The loop never breaks (LIVE LOOP), and the suspect rows are separable
  afterwards. Cost: you must actually watch for the log.

**I lean (b)** — the LIVE LOOP fence says never break the running
record→transcribe→coach→read loop, and a mismatch is recoverable *if* it is
visible and the affected rows are marked. (a) trades a certain outage for an
uncertain corruption, which is the wrong way round when the corruption is
already contained by the marker.

---

## 6 · Migration plan (3 migrations, all additive)

| # | file | what |
|---|---|---|
| 0257 | `add_detector_version.sql` | §3.1 + seed row for `fillers-v1` carrying today's lexicon and its hash |
| 0258 | `add_label_revision.sql` | §3.2 + a one-time snapshot of current `state_ratings` rows as revision 1 (this backfill is honest: those rows *are* the current answer) |
| 0259 | `add_threshold_version.sql` | §3.3, no seed — nothing has a threshold yet |

All idempotent, all non-destructive, none touching an existing column. Safe to
apply before or after the code deploys; every write path degrades to today's
behaviour when a table is absent.

---

## 7 · Build order, once approved

1. the three migrations
2. `services/provenance.py` — canonical definition serialisation + hashing,
   pure and testable
3. the boot check (per §5's answer)
4. `label_revision` writes alongside the existing rating write
5. stamp `detector_version` on new `dimension_evaluations` rows

Steps 1–3 are the foundation and could ship alone; 4–5 are each independently
revertible.
