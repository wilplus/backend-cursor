# FE handoff — the Life Panel document dock, answered (2026-07-31)

**From:** Backend
**Answers:** `BE handoff: the Life Panel document dock (kind-aware drafting)` (FE, 2026-07-31)
**Branch:** `claude/life-panel-doc-dock-be-m6e8rc`

```
FILTER: JUSTIFIED-SCAFFOLDING — cat {SCAFFOLDING} — fences {clear} — locks {clear}
        redirect: tighten word→slide bucketing at the two-clocks boundary
```

**One migration to run.** `migrations/add_life_items_origin_document.sql` —
adds one nullable column to `life_items`. Everything else in this change works
with or without it (see §4); nothing else is needed to unblock Phrases,
Principles and Wins. **No flag to flip.**

Ship your branch whenever you like. The three ordering guarantees you listed
in §4 all still hold, and none of them is load-bearing for us any more: `kind`
is now honoured rather than ignored, so the retry-without-the-field path costs
you nothing and will not fire.

---

## 1. The ask: done

`POST /v2/life/setup/propose-from-document` takes an optional `kind`, one of
the closed nine, and now emits **`phrase`, `principle` and `win`** on top of
`bet` / `goal` / `habit` / `distraction`. `apply-proposed` creates every one of
them. The two endpoints read from ONE tuple —
`life_import.DOC_DRAFT_KINDS` — and a test asserts the agreement rather than
trusting a comment, because the failure mode you described (tick, Add, "that
did not go through", nothing to do about it) is not one either of us would see
in review.

**How the hint works, and what it deliberately does not do.**

The document is read **twice** when the hint names a kind the old pass could
not produce:

| Hint | Passes run | What comes back |
|---|---|---|
| *(omitted)* | the original one | exactly what it returned yesterday |
| `goal` · `habit` · `distraction` · `bet` | the original one | exactly what it returned yesterday |
| `phrase` · `principle` · `win` | the original one **+ a lines pass for that kind** | the hinted rows **first**, then everything else the document holds |
| `task` · `event` | the original one | accepted, adds nothing — see below |

So your §2.3 holds literally: a strategy document opened from Phrases still
offers its goals, and the hinted rows simply lead, because that is the view
the person is standing on. Returning nothing for the hinted kind stays a real
answer and your empty state is the right thing to show.

**`task` and `event` are accepted and change nothing.** Both are real kinds,
so they pass validation and the un-hinted answer comes back — but neither gets
a pass of its own, on purpose. `/v2/life/timeline` already renders dated goals
as markers, so an `event` pass would draft a second, separately tickable copy
of every dated goal the base pass drafts; `task` would do the same for the
undated ones. Two tickable rows for one written line is a worse answer than an
honest empty one. If Timeline or Today should draft their own kinds later,
that is a real decision and we would rather take it deliberately than inherit
it from a fan-out.

**An unknown kind is a 400, not a shrug.** A tenth kind is an FE change (your
§3.3) — so a backend that quietly accepted one would be drafting rows nothing
on your side can display. `{"kind": "reflection"}` → 400
`INVALID_INPUT`. The nine spell exactly as in your table.

**One additive field on the response:** `kind`, echoing the hint we honoured
(`null` when none was sent). Nothing else about the shape moved.

```jsonc
{
  "document": { "id": "…", "file_name": "…", "status": "processed", "char_count": 812 },
  "items": [
    { "kind": "phrase", "title": "The line itself.", "body": "",
      "collection": "wall", "external_id": "phrase:sha:…", "order_key": 1000, "status": "active" }
  ],
  "kind": "phrase",
  "written": false
}
```

`body` is empty unless the line was longer than 500 characters, in which case
`title` holds the first 500 and `body` holds the whole thing — a 600-character
phrase keeps every character it was written with, and a normal one does not
render twice on your review row.

**One thing to expect in `count`.** `external_id` is a content hash, and the
unique index on `(user_id, external_id)` is what makes drafting the same file
twice idempotent. So a ticked line the user *already has* — same kind, same
text, whether imported or drafted before — is not duplicated, and
`created`/`count` come back one short of what was ticked. That is the existing
behaviour for goals and it is the one we want: the row is already in the list
above, so the screen still ends up right. It also means two identical lines
inside one document arrive as one drafted row rather than two rows where only
the first could ever be created.

---

## 2. Your three confirmations

### 2.1 `collection` out, `bet` in — and phrases default to `"wall"`

**The asymmetry is real but it is not a requirement.** `collection` is the
column; `bet` is what the goals surface calls it. `apply-proposed` has always
accepted **either** spelling on the way in (`sanitize_confirmed_item` reads
`bet or collection`), so your mapper is belt-and-braces and can stay exactly as
it is. If you ever want to drop the translation, send `collection` and it will
land identically.

**Yes to the wall.** Drafted phrases now carry `collection: "wall"` on the way
out, so you render them under Wall without inventing anything. And it is
defaulted again on the way in: a phrase that arrives with no collection is
filed on the wall rather than under "Uncollected". An explicit collection you
send always wins.

### 2.2 The un-hinted "draft again" call

Confirmed, and it is slightly better than "latest": it is **the newest
`processed` document for that user**, owner-scoped, `created_at DESC`. A newer
upload that failed extraction (`extraction_failed`) never shadows an older
readable one — so the "draft from my document" button on a user with three
uploads reads the most recent one anything could be read out of, which is the
behaviour that matches the button's words. It is unchanged from today; the
dock just makes it reachable from nine places instead of one.

If you ever want "draft from *that* one", `document_id` still does it.

### 2.3 The nine are closed on our side too

Confirmed, and now enforced: the hint is validated against the same nine, and
the draftable set is a subset of them with a test asserting it. We will not
ship a tenth kind without telling you first — and if we ever try, the suite
goes red before the rows vanish on your side.

---

## 3. Provenance — decided: a third origin column

`life_items` gains **`origin_document_id uuid`**, nullable, no foreign key.

**Why not "nothing at all".** You put it exactly right: a principle from a file
would otherwise be indistinguishable from one the engine derived from a
`#mistake` case, and `/panel/principles/:id` renders the five slots and the
application log for both. The two existing columns cannot say it — `origin_case_id`
would point at a case that never happened, `origin_note_id` at a note nobody
typed — and the `source: 'import'` enum lives on `life_notes`, not on items.

**How it is filled.** `apply-proposed` accepts an optional top-level
`document_id`; every row created in that request carries it. It is
**resolved, never guessed**: the id must resolve to one of the caller's own
documents, and if it does not (deleted between drafting and ticking, or never
theirs) we log it, skip the stamp and **still create the rows**. The
provenance is a nicety; the rows the user ticked are the job.

**Nothing is required of you.** Send nothing and rows are created unstamped,
exactly as today. Whenever it is convenient, send back the `document.id` you
already receive from `propose`:

```jsonc
POST /v2/life/setup/apply-proposed
{
  "document_id": "uuid-from-the-propose-response",   // OPTIONAL
  "items": [ { "kind": "phrase", "title": "…", "bet": "wall", … } ]
}
```

`origin_document_id` also rides `serialize_item`, so it is on every item
payload you already read (and on the user's export) — `null` for every row
that did not come from a file. No FK, deliberately: the panel's hard delete
removes documents and items independently, and a cascade would turn "delete my
uploads" into "delete the rows I made from them".

**A principle created this way keeps `status: "active"`.** The `proposed`
triage state exists so a bad prompt day cannot *silently* corrupt sixty
principles earned over four years — silently being the load-bearing word. This
row was displayed verbatim and individually ticked by the person who wrote it.
That is N5's approve, and there is nothing left for triage to catch.

---

## 4. What happens if the migration has not run yet

The apply path tries the insert with the provenance field; if the column is not
there, it retries once without it and creates the row. **A migration nobody has
run costs the stamp, never the row the user ticked.** There is a test for it,
because "on `main`" is not "run in prod".

---

## 5. Traffic

Noted, and it is fine: `GET /v2/life/setup/documents` is a metadata-only,
owner-scoped, indexed read (`user_id, created_at DESC`), capped at 20 rows, and
it never carries `extracted_text`. Once per page load is nothing.

One thing worth knowing on your side: a **hinted** draft on Phrases, Principles
or Wins makes **two** model calls instead of one, so it is slower than the
goals draft you are used to — same order of magnitude, not a different one. It
is metered separately in our cost ledger (`life_doc_draft_kind`) so we can see
what the dock actually costs.

---

## 6. The fences, held

- **N5** — drafting still writes nothing. `propose` returns rows and stops
  (`"written": false` is still stated on the wire), and the widened kind set
  did not add a single write to that path. Tested for the hinted call too.
- **Extracted text only** — unchanged. The binary is still discarded at upload;
  the second pass reads the same stored text the first one does.
- **AC-9 / N4** — no score, no count-of-things-missing, no percentage. The new
  response field is a kind name.
- **L-6** — unchanged. Every read here is owner-scoped, nothing drafted from
  one person's document can reach another's, and none of it is coach-visible.
- **L-2a** — the three bets are still seeded from `lp.BETS` at their locked
  rank on every draft, hinted or not, and an invented bet is still refused at
  apply.

---

## 7. Your acceptance list, mapped

| # | Your step | Ours |
|---|---|---|
| 1 | Phrases → drafted `phrase` rows | `phrase` pass; rows lead the response, `collection: "wall"` |
| 2 | Untick one, Add → only the ticked ones | unchanged N5 path, now accepting `phrase` |
| 3 | Principles and Wins | same, per kind |
| 4 | Goals byte-identical | a `goal` hint runs the original pass **only** — same rows, same bets, same due labels, same single model call. Asserted by a test that compares the hinted result to the un-hinted one |
| 5 | Today, un-hinted, unchanged | no hint → the original call, unchanged |

## 8. Not ours, agreed

The orphaned `/panel/data` is a founder decision between re-hanging the link
and changing the consent copy. `POST /v2/life/export` and
`DELETE /v2/life/data` are untouched and still serve.
