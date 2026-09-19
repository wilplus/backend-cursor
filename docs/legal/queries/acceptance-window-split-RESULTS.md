# Result: the acceptance window DID split across the 2026-06-06 rebrand

**Run 2026-09-18 against production** (Supabase SQL Editor, project `willpowerlab`,
branch `main`/PRODUCTION) using `acceptance-window-split.sql` in this directory.
Read-only; four `SELECT`s.

This file records the output. **It changes no conclusion in the pack** — the
provenance table in `legal/phase1-2026.1/accepted-versions/README.md` and counsel question Q-E in
`09-counsel-cover-note.md` still say the count is not established, and both are
on `claude/wonderful-cori-mayrpq`, which has not merged. They are updated from
this file once it does. The numbers are written down here so they are not
re-derived from a chat window.

---

## 1. Two accepted documents, not one

| accepted_document | acceptances | users | first (UTC) | last (UTC) |
|---|---|---|---|---|
| `terms-as-published-2026-05-07` | 22 | 22 | 2026-05-08 10:15:21.813569+00 | 2026-05-16 08:44:35.239744+00 |
| `terms-as-published-2026-06-06` | 4 | 4 | 2026-06-06 13:13:03.44357+00 | 2026-07-16 16:12:59.1247+00 |

22 + 4 = 26, and block 4 shows 26 rows across 26 distinct users, so **no user
accepted twice.** These are two disjoint populations: 22 people agreed to the
document naming *Willab* as the counterparty and never agreed to the later one;
4 different people agreed only to the document naming *WillpowerLab*.

That is a stronger statement than "the window straddled a change", and it is the
one Q-E has to be rewritten around.

## 2. `terms_version` cannot distinguish them

| terms_version | side | acceptances | users | first_accepted | last_accepted |
|---|---|---|---|---|---|
| 1.0 | pre-rebrand | 22 | 22 | 2026-05-08 10:15:21.813569+00 | 2026-05-16 08:44:35.239744+00 |
| 1.0 | post-rebrand | 4 | 4 | 2026-06-06 13:13:03.44357+00 | 2026-07-16 16:12:59.1247+00 |

**Both sides carry `terms_version` = 1.0.** Two materially different documents
were recorded under one label, so the version column is not evidence of what a
user accepted. Only `terms_accepted_at` separates them. Counsel must be told
this explicitly rather than left to infer it from a version field that looks
authoritative.

`created_at` tracks `terms_accepted_at` to within a second on the boundaries
(`2026-06-06 13:13:03.961341+00` against `…03.44357+00`), so the two columns
tell the same story at the extremes.

> **[[OPEN — one cell not yet read]]** The
> `rows_where_the_two_dates_disagree` column was cut off in the captured output
> and has not been read for either row. The min/max dates agree within each
> group, so 0 is the expected value, but **it has not been observed** and must
> not be recorded as 0 until it is.

## 3. The one boundary row, and why it falls on the later document

One acceptance landed inside the ±48h window:

| field | value |
|---|---|
| id | `a46fbbbe-ecdc-40dd-97f8-ec4a0082ea16` |
| user_id | `779678ed-af25-47cd-a682-7155e9544af1` |
| terms_version | 1.0 |
| terms_accepted_at | 2026-06-06 13:13:03.44357+00 |
| created_at | 2026-06-06 13:13:03.961341+00 |
| offset_from_boundary | 13:13:03.44357 |

The rebrand commit `9815b7a2` ("feat(brand): WillpowerLab rebrand — pure-white/
black/orange tokens + Logo") is on `main` with committer date
**2026-06-06T12:11:58Z**, confirmed through the GitHub API. It changed
`src/app/terms/page.tsx` (8 lines) and `src/app/privacy/page.tsx` (4), including
the two body-text lines naming the counterparty:

```
-  By creating an account or recording a voice sample on Willab,
+  By creating an account or recording a voice sample on WillpowerLab,
-  You must be at least 18 years old to use Willab.
+  You must be at least 18 years old to use WillpowerLab.
```

The acceptance is **61 minutes after** that commit reached `main`. The repository
was pushing directly to `main` in June, Vercel builds on push, and a build of
this application completes in minutes. So this row belongs to
`terms-as-published-2026-06-06`, and the 22/4 split in section 1 stands.

> **[[OPEN — inference, not observation]]** Deploy-from-push is inferred, not
> observed. The Vercel deployment log for 2026-06-06 would make it a fact. Until
> someone reads it, the 22/4 boundary rests on a one-hour margin and an
> assumption about build duration. Worth closing before signature: if the deploy
> took longer than 61 minutes, the split is 23/3 and one user moves documents.

**Method note.** A first attempt to establish this reported `9815b7a2` as "not
on `main`", which was wrong. The working clone is shallow (57 commits, back to
2026-08-27), so the ancestry check had no history to answer from.
`tests/test_legal_citations.py` skips its ancestry assertion on a shallow clone
for precisely this reason. Ancestry claims about June commits cannot be made
from this checkout and must go through the API or a full clone.

## 4. The population figures

| population | n |
|---|---|
| auth users | **67** |
| user_consents rows | **26** |
| distinct users in user_consents | **26** |
| user_settings rows | **7** |

This resolves WP0 question 1 and the discrepancy
`09-counsel-cover-note.md` currently asks counsel not to rely on.

The "7 rows versus 25 users" framing was misleading: `user_settings` is a sparse
table written when a user changes a setting, not a user registry. **The account
count is 67.**

**41 accounts hold no consent record at all** (67 − 26). Q-E already asks counsel
about those accounts; it can now name the number instead of describing it.

---

## What this changes, and where

Neither edit is made here — both files are on `claude/wonderful-cori-mayrpq`,
which has not merged, and editing them from another branch would collide with
the branch that owns them.

1. `legal/phase1-2026.1/accepted-versions/README.md` — the provenance table's "count not yet
   established" cells become 22 and 4, with the note that no user accepted both.
2. `09-counsel-cover-note.md` Q-E — rewritten for **two** accepted documents
   naming two different counterparties, carrying the `terms_version` = 1.0
   finding and the 41 accounts with no consent record.
3. Any DPIA severity rating reasoning from the user count uses 67, not 7 or 25.
