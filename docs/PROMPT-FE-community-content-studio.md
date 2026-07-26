# FE HANDOFF — Community Content Studio (one button in the CMS)

**Backend is DONE and merged-ready** on branch `feat/community-content-studio`
(this repo). Nothing below is speculative — every endpoint exists and is covered by
`test_community_content.py` (55 tests, green).

**Repo to change:** `frontend-cursor`. Everything lands in the existing CMS. **No new
page, no new route, no middleware change.**

Design rationale + the decision-filter verdict live in
[PROMPT-community-content-studio.md](PROMPT-community-content-studio.md). Content model:
[WillLab_Community_Content_Strategy.md](WillLab_Community_Content_Strategy.md).

---

## 1. What it does

The founder writes the week's essay into the CMS as an ordinary journal post — that
post **is** format ① Technique. One button under the body derives the three other
community formats (② Myth-bust, ③ Fear, ④ Win) with GPT-4o. He edits them if he
wants, copies each one, and pastes into Skool by hand.

**These are not blog posts and can never become blog posts.** They live in their own
table with no slug, no status and no `published_at`; no public route serves them.
The UI must make that obvious: no publish control, no preview link, no reorder.

---

## 2. Backend contract (live)

Four endpoints, all **POST**, all password-in-body — identical to the CMS routes you
already call. Same 401 (wrong password) / 503 (`JOURNAL_ADMIN_PASSWORD` unset)
behaviour, same `{ code, error }` failure shape.

### `POST /v2/internal/journal/community/generate`

```jsonc
// request
{ "password": "…",
  "post_id":  "<journal post uuid>",
  "formats":  ["fear"],            // optional — omit for all three.
                                   // A subset is how per-card Regenerate works.
  "notes":    "lean on the freeze" // optional, ≤500 chars, founder's steer
}
// 200 — the FULL current set for the post, not just what was regenerated
{ "items": [ CommunityItem, … ] }
```

Failures: `400` missing `post_id` / bad `formats` / the post's body is empty ·
`401` · `404` unknown `post_id` · `503` kill-switch off or the model gave nothing
usable (retryable) · `500` generated but could not save.

**This call takes 10–25 s** (gpt-4o, 2400 max tokens). Make sure no proxy or client
timeout is shorter, and show honest progress copy.

### `POST /v2/internal/journal/community/list`

```jsonc
{ "password": "…", "post_id": "…" }   // omit post_id for EVERY item
→ 200 { "items": [ CommunityItem, … ] }
```

Load once with no `post_id` on CMS boot and group client-side by `journal_post_id`.

### `POST /v2/internal/journal/community/update`

```jsonc
{ "password": "…", "id": "<item uuid>", "title": "…", "body": "…" }
→ 200 { "item": CommunityItem }
```

Only `title`/`body` are writable. **Editing clears `flags`** server-side — they exist
to make the founder look at the draft, and he just has. `400` no id / no fields ·
`404` unknown id.

### `POST /v2/internal/journal/community/delete`

```jsonc
{ "password": "…", "id": "<item uuid>" } → 200 { "deleted": true }
```

### `CommunityItem`

```ts
{
  id: string;
  journal_post_id: string;
  kind: "myth_bust" | "fear" | "win";
  label: "Myth-bust" | "Fear" | "Win";  // server-supplied, don't re-derive
  day: "Thu" | "Tue" | "Sat";           // the content model's posting cadence
  title: string;
  body: string;                          // plain text, blank-line paragraphs
  char_count: number;
  flags: ("construct" | "verify")[];
  pillar_id: number | null;              // 1–6
  pillar_name: string;                   // "Focus & attention"
  theme: string;                         // "The Re-Entry Note"
  soft_cta_line: string;                 // "" unless pillar 6
  app_proof_line: string;
  generated_at: string | null;
  updated_at: string | null;
}
```

`pillar_name`, `theme`, `soft_cta_line` and `app_proof_line` are **batch-level** — the
same on all three items of a post. Read them off any one of them.

---

## 3. What to build

### 3.1 `src/services/api/journalAdmin.ts`

Four calls using the module's existing private `post()` helper and `AdminResult<T>`
shape. Add a `CommunityPost` interface and a `mapCommunityPost` mapper next to the
existing `mapJournalPost`.

```ts
adminGenerateCommunity(password, postId, opts?: { formats?: CommunityKind[]; notes?: string })
adminListCommunity(password, postId?)
adminUpdateCommunity(password, id, changes: { title?: string; body?: string })
adminDeleteCommunity(password, id)
```

### 3.2 BFF proxies

Four `route.ts` files under `src/app/api/v2/internal/journal/community/` —
`generate/`, `list/`, `update/`, `delete/`. Copy
`src/app/api/v2/internal/journal/posts/update/route.ts` verbatim and change the
upstream path. Nothing clever. **Check the generate proxy's timeout** against §2.

### 3.3 `src/app/cms/page.tsx` — two additions

Match the file's existing register: the `BTN_PRIMARY` / `BTN_GHOST` / `BTN_ICON` /
`INPUT_CLS` / `LABEL_CLS` constants, the `busy` gating, `StatusPill`.

**(a) Section 8 — directly under the body textarea** (currently the last block in the
editor, `src/app/cms/page.tsx:894-908`). This is the "under the blog post" the founder
asked for.

- Heading `Community posts`; once generated, show `{pillar_name} · {theme}` beside it.
- **One primary button.** `Generate community posts` when the post has none,
  `Regenerate all` when it does — and the regenerate variant **confirms first**,
  because it overwrites drafts he may have edited.
- Disabled with an explanatory `title` when `!editing.id` (unsaved) or the body is
  empty — the same affordance the Publish button already uses at
  `src/app/cms/page.tsx:601-612`.
- While running: spinner + `Writing three posts, about 20 seconds…`.
- **Copy post body** button above the cards — that's format ① Technique, taken from
  `editing.body` client-side. No API call, no Regenerate.
- Then three cards **in posting order: Tue Fear · Thu Myth-bust · Sat Win** (sort by
  the cadence, not by the array order the API returns). Each card:
  - day badge + `label` + `title`
  - the body in a whitespace-preserving block (`whitespace-pre-wrap`), `char_count`
  - **Copy** — `navigator.clipboard.writeText(body)`, 2 s `Copied ✓`
  - **Edit** — inline textarea → `adminUpdateCommunity`
  - **Regenerate** — this format only (`formats: [kind]`)
  - **Flag warnings above the body** when `flags` is non-empty:
    `construct` → "uses retired score vocabulary — reword before posting"
    `verify` → "contains a claim that isn't in your post — check before posting"
- Below the cards, the two opt-in lines, each with its own Copy button and one line of
  when-to-use:
  - `app_proof_line` — "append to the Technique post every other week or so"
  - `soft_cta_line` — render **only when non-empty** (pillar 6 posts only)

**(b) The queue — the left-hand list** (`src/app/cms/page.tsx:486-583`). Call
`adminListCommunity(password)` alongside `adminListPosts` in the existing refresh
(`src/app/cms/page.tsx:188-200`), group by `journal_post_id`, and render each post's
items **indented directly beneath it** as compact rows: a `COMMUNITY` pill in a
visibly different colour from `StatusPill`, the `label`, and the truncated `title`.

Clicking a row opens the parent post's editor and scrolls to (and briefly highlights)
that card in section 8 — **one editing surface, two ways in.**

These rows get **no reorder arrows, no preview eye, no publish control.** They can
never be published and the UI should say so by omission.

### 3.4 Tests

Extend the existing CMS/journal vitest coverage — don't start a new file:

- `Copy post body` writes `editing.body` verbatim to a mocked clipboard, with **no**
  network call.
- A community row renders no publish/preview affordance.
- `flags: ["verify"]` renders the warning.

---

## 4. Before it works in prod

Two ops steps, both on the backend side — flag them to whoever deploys:

1. **Run the migration**: `migrations/add_journal_community_posts.sql`
   (idempotent; creates `journal_community_post` with RLS on, zero policies).
2. `COMMUNITY_CONTENT_ENABLED` defaults **ON** — no env change needed. Set it to `0`
   only to kill the LLM spend; `list`/`update`/`delete` keep working when it's off, so
   existing drafts stay readable.

`JOURNAL_ADMIN_PASSWORD` is the same password the CMS already uses. There is no second
password for this surface.

---

## 5. Decisions already made (don't re-open)

| | |
|---|---|
| **Community-only** | Never journal posts. No slug/status/published_at exists on the row. |
| **CMS is the only surface** | No `/coach/content` page. No coach-JWT route. Auth is the CMS body-password. |
| **① is never generated** | The post body is echoed as a copy block, client-side. |
| **Flags warn, never drop** | A flagged draft is shown with a warning; a human reads every one before it goes out. |
| **Single-format reroll** | Inherits pillar/theme/app-lines from a surviving sibling, so one reroll can't re-theme the week. Handled server-side — nothing for the FE to do. |
| **Delete the parent** | Cascades its three community drafts away (DB-level `ON DELETE CASCADE`). |

## 6. Open, if you have an opinion

- **Language** — the model mirrors the source essay's language. English-only would be
  a one-line prompt change in `services/prompts/community_content_strategy.md`.
- **Post lengths** — the 500–900 / 700–1300 / 350–700 char targets are inferred from
  the strategy doc's descriptions, not stated in it. Tune after the first real week by
  editing that same file; no code change.
