# OPS — feature flags and what is waiting on a release decision

Every boolean flag the backend reads, what it gates, and — for the ones that
are OFF — **what has to happen before they go on**. A flag with no owner and
no exit condition becomes permanent by accident: nobody can reconstruct what
it was protecting against, so nobody dares flip it.

Flags live in Railway environment variables. A flip is a config change, not a
deploy — reversible in seconds, and scoped to one environment. That is why the
code defaults are conservative and mostly left alone.

**Reading a row:** `default` is what the code returns with the variable
*absent*. An explicit `0` in the environment always wins.

---

## Retired in place

### `stress_snippets` — no writer, no reader, rows kept (2026-08-10)

Founder decision. **The table is not dropped and the rows are not deleted.**
They are human-generated coach labels that cannot be re-derived: the clip
generator that produced the candidates was deleted (PR #368) and the model
that ranked them went before that.

What went, in order: the label writer and the whole `v2_*_stress_snippet*`
accessor family (#368), then the AI-draft writer, the coach-prefill draft
generator, and the stress branch of the publish-time annotation capture in
`record_snippet_publish_annotations`. That last one was a **second** reader,
found while doing this work — it walked the session's recordings on every
publish to look for stress rows, so it cost two queries per publish to find
nothing new.

`migrations/retire_stress_snippets.sql` (0261) writes a `COMMENT` and nothing
else — no DROP, no DELETE, no TRUNCATE. Safe to run at any time; running it
late costs nothing.

`coach_label_notes` **stays** in `_PUBLISH_CAPTURE_FIELDS`. Events written
before today carry that field name and the idempotency probe keys on the
tuple; removing it would make the backfill unable to recognise its own prior
writes.

Enforcement is `test_stress_snippets_retired.py`, not a database trigger — a
trigger raising on INSERT can only ever fire in production, on a path that was
probably a mistake but might have been deliberate. The test fails in CI
instead, and says what to do instead: **if the lane is ever revived, mint a
new table** rather than mixing fresh rows into a frozen corpus — the same rule
`detector_version` applies to a changed definition.

`scripts/cleanup_corrupt_stress_snippets.py` is left runnable on purpose. The
point of keeping the rows is that a human can still operate on them.

---

## Cutovers in flight

### `SNIPPETS_TABLE` — unset (= `charisma_snippets`)

**Not a feature flag. A migration affordance with an expiry date.** It exists
so renaming the snippet table is a config change instead of a deploy, and it
should be deleted once the rename has settled.

`charisma_snippets` was named after the ML generator — the one of its four
producers that no longer exists (deleted 2026-08-10, PR #368). The three live
ones are interview turns, funnel cold-start rows and willab Lab auto-cuts.
`services/snippet_tables.py` has the full note.

**The cutover, in order:**

| # | step | how long | reversible by |
|---|---|---|---|
| 1 | deploy the code reading `SNIPPETS_TABLE` | a deploy | it is a no-op; nothing to revert |
| 2 | run `migrations/rename_charisma_snippets_to_snippets.sql` — renames **and** reloads the PostgREST schema cache | seconds | the reverse `ALTER` **plus `NOTIFY`** at the bottom of that file |
| 3 | set `SNIPPETS_TABLE=snippets` in Railway | seconds | unset it |

> **The PostgREST schema cache bit this cutover on 2026-08-10.** PostgREST
> answers from a cached schema, a `RENAME` does not reliably invalidate it,
> and this codebase swallows the resulting "not found in schema cache" error
> by design — so the rename looked perfect in SQL while the app silently
> wrote nothing. The migration now carries `NOTIFY pgrst, 'reload schema';`
> inside its transaction, so the reload is atomic with the rename.
>
> **If a rename ever appears to have done nothing, run this first:**
> ```sql
> NOTIFY pgrst, 'reload schema';
> ```
> It is also the fix's other half on the way *back* — a rollback without it
> leaves PostgREST serving the name you just reverted. The same failure is
> already on the record at `services/db.py:8711` (PGRST204, 2026-05-11).

**Have the Railway tab open before step 2.** Between 2 and 3 the running code
queries a table that no longer exists; PostgREST returns 404 and this codebase
swallows those exceptions by design, so snippet writes would stop **silently**
— no error page, no alert. Keep that window to seconds.

**Verify step 3 took effect BEFORE testing anything.** On restart the process
logs which table it resolved:

```
snippets: table resolved to 'snippets' (SNIPPETS_TABLE env)
snippets: 'snippets' is readable
```

`(default)` instead of `(SNIPPETS_TABLE env)` means the variable did not
reach the process — the restart did not complete, or the running commit
predates the code that reads it. A `SNIPPET TABLE UNREACHABLE` line at
CRITICAL means the name resolved but the table cannot be read; snippet
writes are failing silently right now, so roll back.

This log is the whole lesson of the 2026-08-10 attempt: every possible cause
looked identical from outside the process, and twenty minutes went into
distinguishing causes that this one line separates instantly. **Read it
before running any other check.**

**Then verify the data** (should return rows, and match the count from before):

```sql
SELECT COUNT(*) FROM public.snippets;
SELECT source_type, COUNT(*) FROM public.snippets GROUP BY source_type;
```

Then exercise one real write — record a Lab take, or submit an interview
answer — and confirm the row lands. A clean `SELECT` only proves the rename;
it does not prove the app is pointed at it.

**No compatibility view is created, deliberately.** `add_rls_all_public_tables.sql`
records that `anon` can reach this table directly through PostgREST and "RLS
is the only control on it". A view runs with its owner's rights unless it is
declared `security_invoker = true`, so a compat view would silently reopen
that hole while the service-role backend showed no symptom at all.

**Not renamed:** the storage prefix `charisma_snippets/<session>/…` and the
existing column names. Object keys are immutable history — every clip already
uploaded lives under that prefix, and rewriting it would point at nothing.

**When it is done:** collapse `services/snippet_tables.py` to a plain constant
and delete the Railway variable. A table name that stays configurable forever
is a table name nobody can grep for.

---

## Live experiments

### `MANAGER_CONTROLS_ENABLED` — default **ON** (2026-08-10)

The manager engine's three randomisations are **running and being recorded.**
The unit is the **lane** (`lane:polish`, `lane:wording`, …), not a registry
dimension — deliberately, since no registry dimension can fire (every row still
has `fire_at = None`).

| arm | rate | effect on a real user |
|---|---|---|
| `gamma_control` | 12% | that (user, lane) pair receives **nothing from that lane, permanently** |
| `intervention_randomisation` | 20% | a note that WON the budget is **not shown** |
| `epsilon_explore` | 10% | rank 2 surfaces instead of rank 1 |

**Health check** — the query that tells you it is really running:

```sql
SELECT arm, COUNT(*) FROM intervention_arms GROUP BY arm;
```

Roughly 12% `CONTROL` and 20% `WITHHELD` among what would have surfaced. **An
empty CONTROL arm means the controls are running and the record is not** — the
exact silent failure the table exists to prevent.

**Three things had to land in the same change as the flip, and did:**

1. **`arm_rows()` is persisted** (`_record_arms`), gated on the controls
   actually having run — rows written with the arms inert would stamp the
   policy as if an assignment had happened when none did.
2. **The exploration roll is deterministic**, per (user, session).
   `random.random` would have been wrong: this surface is polled, so a fresh
   draw per request would re-decide the branch every few seconds and swap the
   notes on screen while the student watched.
3. **The session key is the arc's latest spoken take.** The doc-level
   `take_session_id` is `None` under the master flag, which would have
   short-circuited `is_withheld` to False (withhold arm never firing) *and*
   made the writer drop every row for an empty session id.

**To switch it off:** set `MANAGER_CONTROLS_ENABLED=0` in Railway. No deploy,
no code change; the arms go inert in one place.

**Salts are versioned** (`CONTROL_SALT`, `WITHHOLD_SALT`, `EXPLORE_SALT`).
Changing one reshuffles every assignment and splices two incompatible
experiments together, so a salt change is a new experiment with a new name,
never an edit.

---

## Flags that are ON by default

| flag | gates |
|---|---|
| `LLM_USAGE_ENABLED` | LLM call accounting |
| `PIECES_CANONICAL_ENABLED` | pieces as the canonical document unit |
| `SENTENCE_BOUNDARY_SPLIT_ENABLED` | sentence-boundary piece splitting |
| `VOICE_CONFIDENCE_ENABLED` | the voice-confidence measure (computed) |
| `VOICE_CONFIDENCE_SEX_INFERENCE_ENABLED` | its speaker-sex normalisation |

---

## Flags that are OFF by default

Off for different reasons, and the difference matters. "Not built on the other
side yet" is not the same as "we turned this off because it was wrong".

| flag | gates | why it is off |
|---|---|---|
| `LIVING_TRANSCRIPT_ENABLED` | the document IS the full transcript; also the entire `changes` block | **already ON in prod.** The code default stays 0 because flipping it also swaps the document source for every environment at once |
| `MASTER_DOCUMENT_ENABLED` | the persistent master document + block upgrade offers | needs a migrated skeleton; degrades gracefully when off |
| `MOMENT_SUGGESTIONS_ENABLED` | the star machinery the other suggestion lanes reuse | prerequisite for the two below |
| `POLISH_AS_SUGGESTIONS_ENABLED` | serve verbatim text + offer the polish as approvable stars | on top of `MOMENT_SUGGESTIONS_ENABLED` |
| `DELIVERY_STARS_ENABLED` | delivery advice stars | |
| `STRUCTURAL_STARS_ENABLED` | structural advice stars | |
| `BLOCK_VARIANTS_ENABLED` | the per-block variants picker | |
| `INSTANT_IDEAL_TEXT_ENABLED` | machine draft served free at take 3 | needs FE variant handling (deploy order: BE → FE → flip) |
| `ASYNC_ANALYSIS_ENABLED` | the async analysis queue | see `OPS-PIPELINE-QUEUE-RUNBOOK.md` |
| `COACH_PREFILL_ENABLED` | coach review prefill | |
| `DELIVERY_ALIGNMENT_ENABLED` | delivery alignment pass | |
| `TAKE_ALIGNMENT_ENABLED` | cross-take alignment pass | |
| `TOKEN_PRICING_ENABLED` | token-priced credits | see `PRICING-TOKENS-PLAN.md` |
| `VOICE_CONFIDENCE_RANKING_ENABLED` | voice confidence as a RANKING term | **off by decision** — ranking-inert until validated (`dimension_registry`: `conf`, `disabled_reason`) |

---

## Retired

| flag | what happened |
|---|---|
| `KEY_POINTS_ENABLED` | **removed 2026-08-07.** The presentation-mode cue sheet was deferred: a highlighted verbatim opening phrase is indistinguishable on screen from an intervention that explains nothing. The call site is gone, so the variable does nothing — deleted from Railway. `services/key_points.py` and its tests are kept; re-wiring needs the E-2 full↔key-words toggle first |

---

## When you add a flag

Put it in this table in the same commit. A flag that only exists in
`os.getenv` is a flag nobody will find when they are deciding what to turn on,
and the reason it was off will be gone long before the flag is.

If it is OFF, write the **exit condition** — what has to be true to turn it on
— not just what it gates.
