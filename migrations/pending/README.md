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

Nothing. `drop_dead_snippet_metric_columns.sql` was applied by hand on
2026-08-06, recorded as `0254`, and only then moved up into `migrations/`.

That order is the point. It sat here because the pre-flight count showed four
of the six columns held rows; once the follow-up query proved **zero** rows held
a value only in a column (every figure was also in the `metrics` blob) and the
writing path was shown to have stopped on 2026-06-01, it was safe to drop.

Keep this directory. The next destructive migration belongs here first.
