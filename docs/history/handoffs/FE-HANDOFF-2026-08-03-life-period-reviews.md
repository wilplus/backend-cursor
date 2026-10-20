# FE handoff — the monthly + quarterly reviews (piece 5, 2026-08-03)

**From:** Backend
**Program:** founder-agreed 2026-08-02 — piece 5: *the monthly + quarterly
reviews read the reflections layer*
**Branch:** `claude/life-panel-doc-dock-be-m6e8rc`

```
FILTER: JUSTIFIED-SCAFFOLDING — cat {SCAFFOLDING} — fences {clear} — locks {clear}
        redirect: tighten word→slide bucketing at the two-clocks boundary
```

**One migration to run.** `migrations/add_life_period_reviews.sql` — one new
table, RLS in the same file. Deploy order does not matter: with the table
absent every GET still answers (the saved-review slot arrives as the skeleton)
and only the save returns a 500. **No flag to flip** — the endpoints sit
behind the existing three-tier gate.

---

## 1. What this is

The Sunday review, one and two cadences up — built the way the evening was
built: **hold the period against its own measure.** The GET puts three things
next to each other, all in the founder's own words, none of them computed:

1. **The period's strategy document** — the monthly document on the month
   review, the quarterly on the quarter. What was intended.
2. **The period's reflections** — every `#thoughts` / `#reflections` /
   `#observations` note captured inside the window, oldest first. What
   actually happened (the piece-4 reality layer, re-read).
3. **The period's goals** — due inside the window (each carrying its own
   `measure`), plus the undated ones shelved at this horizon.

The month additionally reads **its weeks** (the saved Sunday reviews); the
quarter reads **its months** (the saved monthly reviews). The founder writes
the synthesis; the system writes none of it. No model call fires anywhere on
these four endpoints.

## 2. Endpoints

```
GET  /v2/life/month?month_start=YYYY-MM-DD      any date folds to its month
POST /v2/life/month                             {month_start?, goals_moved?,
                                                 becoming_sentence?, reviewed_on?}
GET  /v2/life/quarter?quarter_start=YYYY-MM-DD  any date folds to its quarter
POST /v2/life/quarter                           {quarter_start?, …same fields}
```

Both params optional — omitted, the current period. The fold key is the first
day of the period (quarters: Jan/Apr/Jul/Oct 1), and the POST upserts on it,
so saving twice edits one row.

## 3. GET payload

```jsonc
{
  "review": {                       // the saved row — or, unsaved, the
    "period": "month",              // two-field skeleton {period, period_start}
    "period_start": "2026-08-01",
    "goals_moved": [],              // verbatim what the founder typed
    "becoming_sentence": null,
    "reviewed_on": null,
    "id": "…"
  },
  "document": { "horizon": "monthly", "body": "…", "version": 3, … } | null,
  "reflections": [ { "id": "…", "body": "…", "tag": "thoughts",
                     "created_at": "…" }, … ],   // OLDEST FIRST
  "reflections_held_back": 0,       // see §4
  "goals":   [ /* serialize_item, due_at inside the window, incl. done */ ],
  "undated": [ /* serialize_item, no due_at, horizon == this period   */ ],
  "weeks":  [ /* month only — serialize_week rows, week_start in window */ ],
  "months": [ /* quarter only — saved month reviews inside the quarter  */ ]
}
```

Notes that matter for rendering:

- **`document` can be `null`** (setup incomplete, or docs not generated).
  Render the review without the intended-side column; do not block it.
- **`goals` keeps the card's Dalio order** (order_key). `done` rows are
  included on purpose — reviewing the month means seeing what finished. Each
  goal carries `measure` (its own stated criterion) when one exists.
- **`weeks` / `months` contain only saved rows.** An unreviewed week simply
  is not there; that absence is the honest record, not a bug.
- **A goal with an unparseable `due_at` degrades to `undated`** rather than
  vanishing — same rule as the timeline.

## 4. The reflections cap is honest

The payload carries at most **100** reflections. When the window holds more,
the **most recent 100** survive (still oldest→newest) and
`reflections_held_back` says exactly how many fell off. If you show the list,
show the number too when it is non-zero — a truncation the reader cannot see
reads as "covered everything". It is a queue count, same class as the week's
`queued_held_back`; it is not a score and must not be styled as one.

## 5. What is deliberately absent

- **No `proposals`.** L-2b routes queued strategy proposals to the **weekly**
  review and nowhere else. Do not add a proposal strip to these screens — a
  second surfacing surface widens the change budget by the back door.
- **No `displaced_goals`** (the Sunday gate) and **no untagged-note review**
  (weekly by spec §5). The month and the quarter read; the week decides.
- **No numbers.** Nothing in the payload counts, grades or scores the period
  (AC-9): no completion ratio, no habit percentage, no goals-hit count. The
  BE will not add one; please do not derive one client-side either.

## 6. POST accepts three fields and drops the rest

`goals_moved` (array, the founder's own wording per goal), `becoming_sentence`
(free text), `reviewed_on` (date). Anything else in the body is ignored —
tested, including a smuggled `progress_score`. Response: `{"review": …}`.

## 7. ⚠️ Copy needs founder sign-off (LIVE LOOP)

Every sentence a user reads on these two screens is new product copy and ships
only with founder sign-off. Specifically to draft and hold:

- the month/quarter **becoming question** wording (the weekly asks *"am I
  becoming the man I described?"* — the longer-range phrasing is the
  founder's to choose, not ours);
- the **goals-moved prompt** wording;
- the **empty states** (no document / no reflections / no saved weeks);
- the **held-back line** ("N earlier reflections not shown" or the founder's
  own words).

BE ships field names only; none of the strings above exist server-side.
