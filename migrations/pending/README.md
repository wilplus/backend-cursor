# migrations/pending — written, reviewed, NOT in the manifest yet

`scripts/migrate.py` globs `migrations/*.sql` — **not** recursively. Anything in
this directory is therefore invisible to `verify`, `status` and `apply`. That is
the point.

## Why this directory exists

A destructive migration sitting in `manifest.txt` un-applied **blocks every
deploy**. The Railway migrate step runs `migrate.py` on boot, hits the
`DROP COLUMN` guard, and aborts:

```
ABORT  0254 drop_dead_snippet_metric_columns.sql contains DROP COLUMN.
       CLAUDE.md: never auto-drop tables/columns/migrations.
```

That guard is correct and must not be weakened — automation must never drop a
column. But the consequence is a hard rule:

> **Do not add a destructive migration to `manifest.txt` until the moment you
> are ready to apply it by hand.**

The already-applied destructive files (`drop_reread_lane.sql` and friends) do
not block anything, because `migrate.py` skips what the ledger records as
applied. Only an un-applied one stops the line.

## Workflow

1. Write the `.sql` here. Review it, verify the data question it depends on.
2. When you are ready to run it: `git mv` it up into `migrations/`, append the
   manifest row, and apply it by hand
   (`migrate.py apply --allow-destructive`, or paste it into the SQL editor and
   insert the ledger row).
3. Both halves land in the same commit, so the manifest is never ahead of
   reality.

## What is parked here now

**`drop_dead_snippet_metric_columns.sql`** — drops the six dead metric columns
on `charisma_snippets` (PM-9, #358).

BLOCKED ON A DATA QUESTION, not on review. The pre-flight count came back:

| column | rows with data |
|---|---|
| `wpm` | 0 |
| `fillers` | 0 |
| `pause_ms` | 97 |
| `dynamic_db` | 93 |
| `pitch_center` | 94 |
| `energy` | 94 |

`wpm` and `fillers` being 0 confirms the PM-9 diagnosis — they were never
written, which is exactly why they were the two coming back NULL everywhere.

But four columns DO hold data, and `db.update_snippet_metrics` (the writer
named in the diagnosis) wrote all six in one payload — so it cannot be the
source of a four-out-of-six pattern. Some other, older path wrote them and has
not been identified.

Before this can move up:

1. Confirm the same figures are present in each row's `metrics` blob — the
   query is at the bottom of the `.sql`. If a row holds a value only in the
   column, dropping destroys it and this needs a copy-into-blob step first.
2. Identify what wrote them, or at least establish from `created_at` that the
   path is retired and nothing writes them today.

Nothing is broken while this waits. `services/snippet_values` resolves
column → blob → derivation, so those 97 rows read correctly with the columns
present, and would read correctly from the blob without them.
