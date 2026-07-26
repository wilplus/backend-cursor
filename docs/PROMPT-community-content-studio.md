# PROMPT — Community Content Studio (one button in the CMS → 3 community posts)

> **STATUS 2026-07-26 — §2 (backend) is BUILT** on `feat/community-content-studio`:
> service, LLM spec, config flag, 5 db methods, 4 routes, migration, 55 tests green.
> §3 (frontend) is NOT built — the handoff for it is
> [PROMPT-FE-community-content-studio.md](PROMPT-FE-community-content-studio.md),
> which carries the live endpoint contract. This document remains the design record:
> the decision-filter verdict, the fences, and why the shape is what it is.
> Small deltas from §3 as built are noted in the FE handoff; that one wins.

**Founder-directed, 2026-07-25 (v2 — supersedes the standalone paste-page spec).**

Content model source of truth: `WillLab_Community_Content_Strategy.docx` (Draft v1,
23 July 2026) → committed as [WillLab_Community_Content_Strategy.md](WillLab_Community_Content_Strategy.md),
distilled for the prompt in **Appendix A** below.

Repos: `backend-cursor` (Flask) + `frontend-cursor` (Next.js). Branch off `origin/main`
in each; gate-routed PRs. **The Journal CMS this extends landed in `43abfe7`
(PR #254)** — `routes/journal.py`, `services/journal.py`,
`migrations/add_journal_posts.sql`, FE `src/app/cms/page.tsx` +
`src/services/api/journalAdmin.ts`. Read those before writing anything; this feature
is an extension of that surface and must match its patterns exactly.

---

## 0. Decision-filter verdict — already run, do not re-litigate

```
VERDICT:  JUSTIFIED-SCAFFOLDING (founder-directed, 2026-07-25)
CATEGORY: SCAFFOLDING
WHY:      A founder-only marketing tool bolted onto the Journal CMS. It moves
          NEITHER F1 piece (per-slide transcription accuracy, best-per-slide
          ranking) and unblocks no in-flight F1/F2 task. Same class as the
          Journal itself (#254) and the dev-bugs collector. The
          "more members → more takes → better ranking" argument is explicitly
          NOT the justification — that is R3 laundering and it is rejected.
          Fences: AC-9 clean (no scores; founder-only surface). CONSTRUCT fence
          enforced in code (§2.6). BLIND COACH untouched. LIVE LOOP untouched —
          this lives entirely inside the journal blueprint, which #254 already
          fenced off the record → transcribe → coach → read loop with an
          isolation test; extend that test, don't weaken it.
          L1 held by construction: the input is a journal_post body, the output
          goes to one new table, and no F1 assembly module may import the
          service (§2.7).
REDIRECT: n/a — founder override. Nearest F1 work remains (1) word→slide
          bucketing at the two-clocks boundary, (2) transcription fidelity on
          hard/accented audio.
```

---

## 1. What we are building

The founder writes the week's ideal-text essay into the CMS as an ordinary **journal
post** — that post *is* format ① Technique. Under the body field there is **one
button**. It sends that post to GPT-4o, which derives the other three community
formats from the strategy doc — **Myth-bust**, **Fear**, **Win** — and they appear as
three more items in the CMS queue, nested under their parent post. The founder edits
them if he wants, hits Copy, and pastes into Skool.

### Founder-locked scope (asked and answered — do not redesign these)

- **Community-only.** The three derived items are **not** journal posts. They live in
  their own table, they have no slug, no `status`, no `published_at`, and **no public
  route may ever serve them**. A "Win" post is `share yours below 👇` — a Skool
  thread, not an article on www.willpowerlab.com.
- **The CMS is the only surface.** There is no `/coach/content` page, no coach-JWT
  route, no paste-only textarea. v1 of this document specified those; they are
  cancelled.
- **① is never generated.** The journal post body is the anchor, echoed as a copy
  block. The model only produces ②③④.

### Non-goals

No scheduling, no auto-posting, no Skool/LinkedIn integration, no editorial board
(that's Notion, strategy doc §3), no 5th "external post" format (§5-A), no
promote-a-community-post-to-the-blog action, no user-facing surface.

---

## 2. Backend (`backend-cursor`)

### 2.1 Strategy doc as a loadable file

Create `services/prompts/` (text only, no `__init__.py`) and commit **Appendix A
verbatim** as `services/prompts/community_content_strategy.md`. This is "the document
in the system's memory": the founder edits that file and redeploys to change the
content model — no code change.

### 2.2 New service — `services/community_content.py`

Model it on `services/say_it_stronger.py`: docstring with an explicit FENCES block,
pure helpers, one `chat_complete`, a paranoid `_clean_payload`.

```python
FORMATS = ("myth_bust", "fear", "win")

def load_strategy() -> str: ...
    # services/prompts/community_content_strategy.md, module-cached. Returns ""
    # if unreadable (logs a warning) — the caller then refuses to generate
    # rather than calling the model without the doc.

def build_system_prompt() -> str: ...          # §2.4 preamble + the strategy doc
def build_user_prompt(post: dict, *, formats, notes) -> str: ...
def generate_community_posts(post: dict, *, formats=FORMATS,
                             notes: str | None = None) -> dict | None: ...
def serialize_community_item(row: dict) -> dict: ...
```

`post` is the parent journal row — pass **`title`, `excerpt`, `body`**. Body is plain
text with blank-line paragraphs (`services/journal.py` guarantees that), so it goes in
as-is. Cap the body at 20 000 chars in the prompt (`_MAX_SOURCE_CHARS`); the journal
allows 200 000 and a book-length essay would blow the context and the bill.

`notes` — optional founder steer ("lean harder on the freeze"), ≤500 chars.

**SYNCHRONOUS** (unlike say_it_stronger's fire-and-forget): the founder is sitting
there watching a spinner.

Keep `serialize_community_item` here rather than in `services/journal.py` — that
module's contract is `journal_post` and should stay that way.

### 2.3 LLM spec — `services/llm_config.py`

Add after `SPEC_CONTEXTUAL_FOLLOWUP`, with a docstring (the module states that new
surfaces are declared here, never inline at the call site):

```python
SPEC_COMMUNITY_CONTENT = LLMSpec(
    model=STRONG_MODEL,      # gpt-4o — founder-specified. This is public-facing
                             # copy under the founder's own name; mini is not enough.
    temperature=0.7,         # marketing copy: warmth over determinism
    max_tokens=2400,         # 3 posts, the longest (Fear) up to ~1300 chars
    response_format=None,    # strict json_schema override, next to the service
)
```

### 2.4 System prompt

**Role preamble → hard rules → the strategy doc → output contract.** Preamble in this
spirit:

> You are the content editor for WillLab, a free personal-growth community run by one
> person. You are given ONE finished essay — the week's "Technique" post, which the
> founder already wrote by talking it into his own app. Your job is to rotate that
> single idea into the community's other post formats, exactly as the strategy
> document below prescribes. You are not writing new ideas. You are turning one idea
> to a different angle.

Hard rules — all load-bearing, enumerate them explicitly:

1. **Never introduce a fact, statistic, study, researcher, or claim that is not in the
   source essay.** If the essay cites research you may refer to it in the essay's own
   terms; you may never add, sharpen, or name a new one. Inventing science here means
   the founder posts a fabricated citation under his own name.
2. **The founder's first-person voice**, matched to the source essay's register.
3. **Same language as the source essay.** A Polish essay gets Polish posts.
4. **Plain text for Skool.** No markdown, no headings, no hashtags, no links. Line
   breaks and blank lines only. At most one emoji, and only leading the Win post.
5. Never use: charisma score, stress score, threat, ratio, classifier, KPI. Never
   quote a number as a measure of the reader's performance.
6. **Never mention the app inside a post body.** App mentions come back as the two
   separate opt-in lines the founder appends himself.
7. If the essay is too thin to derive a format honestly, keep that format short and
   true to the essay — never pad with generic advice.

### 2.5 Response schema

Next to the service, `"strict": True`, same style as `_RESPONSE_SCHEMA` in
`say_it_stronger.py`. **Re-enforce every cap in `_clean_payload`** — do not trust the
schema to bound anything.

```python
_RESPONSE_SCHEMA = {
  "name": "community_posts",
  "schema": {
    "type": "object", "additionalProperties": False,
    "required": ["pillar_id", "pillar_name", "theme", "posts",
                 "soft_cta_line", "app_proof_line"],
    "properties": {
      "pillar_id":   {"type": "integer"},                      # 1–6, doc §2
      "pillar_name": {"type": "string", "maxLength": 80},
      "theme":       {"type": "string", "maxLength": 120},     # e.g. "The Re-Entry Note"
      "posts": {"type": "array", "maxItems": 3, "items": {
        "type": "object", "additionalProperties": False,
        "required": ["format", "title", "body"],
        "properties": {
          "format": {"type": "string", "enum": ["myth_bust", "fear", "win"]},
          "title":  {"type": "string", "maxLength": 120},
          "body":   {"type": "string", "maxLength": 2200},
        }}},
      "soft_cta_line":  {"type": "string", "maxLength": 300},
      "app_proof_line": {"type": "string", "maxLength": 300},
    },
  },
  "strict": True,
}
```

Per-format recipes for the prompt (strategy doc §4):

| format | recipe | target |
|---|---|---|
| `myth_bust` | Derive by **inversion**. Name the false belief the technique corrects, flip it. Shape: `Myth: [belief].` → the flip in 3–4 lines → one-line reframe. Short and shareable. | 500–900 chars |
| `fear` | Derive by **confession**. Name the emotion under the technique — what the member is quietly afraid of. Confess the founder's own version first, then invite raised hands. Pure vulnerability, ends on a real question. | 700–1300 chars |
| `win` | Derive by **prompting** — members write it, not the founder. One leading emoji + a warm share-your-example prompt, primed with the founder's own example from the essay ("you go first"). | 350–700 chars |

`soft_cta_line` — only meaningful when `pillar_id == 6` (Communicating clearly, the
app-bridge pillar; strategy doc §6 "Contextual"). Other pillars return `""`.

`app_proof_line` — the §5-D seam line ("this started as a rambly voice note; my tool
cleaned it into this"), phrased for *this* essay. Always generated, always returned
separately, **never auto-attached** — the founder pastes it on the weeks he wants it.

### 2.6 `_clean_payload` — validation and guards

Pure, no I/O, fully unit-testable:

- Drop posts with an empty `body` or unknown `format`; dedupe by `format`.
- Truncate `body` 2200, `title` 120, the two lines 300.
- Clamp `pillar_id` to 1–6; outside that → `pillar_id=None, pillar_name=""` (don't guess).
- Strip markdown that slipped through: `**`, `__`, leading `#` on a line.
- **Construct guard** — reuse the `_GUARD_CONSTRUCT_RE` pattern from
  `say_it_stronger.py` (lift to a shared helper, or copy with a comment pointing at
  the original). A tripping body is **not dropped**: it comes back with
  `flags: ["construct"]`. These are drafts a human reviews — a visible warning beats a
  silent deletion.
- **Fabrication flag** — if a derived body contains a digit, or a research-sounding
  token (`study`, `research`, `scientists`, `percent`, `%`), that does **not** appear
  in the source essay, append `"verify"` to that post's `flags`. Soft signal only,
  never a block ("3 minutes" is legitimate).
- Returns:

```python
{
  "pillar_id": int | None, "pillar_name": str, "theme": str,
  "posts": [{"format", "title", "body", "flags": [str], "char_count": int}],
  "soft_cta_line": str, "app_proof_line": str,
  "model": SPEC_COMMUNITY_CONTENT.model, "version": 1,
  "generated_at": "<iso8601 utc>",
}
```

### 2.7 Fences to enforce in tests

- **Public isolation.** No route under `/v2/journal/*` (the anonymous surface) may read
  `journal_community_post`. #254 already ships an isolation test — extend it rather
  than adding a parallel one.
- **L1.** No F1 assembly module may import this service. Grep-fence over
  `services/best_presentation.py`, `services/ideal_text_block.py`,
  `services/ideal_text_report.py`, `services/cross_take_selection.py`,
  `services/charisma_snippet_service.py` — none may contain `community_content`.
  (Mirrors the L1 grep-fence already documented in `say_it_stronger.py`.)

### 2.8 Migration — `migrations/add_journal_community_posts.sql`

Idempotent throughout. Header comment in the house style — copy the register of
`migrations/add_journal_posts.sql`, including its RLS paragraph.

```sql
CREATE TABLE IF NOT EXISTS journal_community_post (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    journal_post_id uuid NOT NULL
                    REFERENCES journal_post(id) ON DELETE CASCADE,

    kind            text NOT NULL,          -- myth_bust | fear | win
    title           text NOT NULL DEFAULT '',
    body            text NOT NULL DEFAULT '',
    flags           jsonb NOT NULL DEFAULT '[]'::jsonb,

    -- Batch-level fields, denormalized onto each row on purpose: three rows
    -- always come from one generation, and a single-format regenerate must not
    -- need a second table to keep the other two consistent. See §2.10.
    pillar_id       integer,
    pillar_name     text,
    theme           text,
    soft_cta_line   text NOT NULL DEFAULT '',
    app_proof_line  text NOT NULL DEFAULT '',

    model           text,
    generated_at    timestamptz,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now()
);

-- One row per (post, format): regenerating a format REPLACES it rather than
-- piling up drafts. Also the upsert conflict target (§2.9).
CREATE UNIQUE INDEX IF NOT EXISTS journal_community_post_parent_kind_idx
    ON journal_community_post (journal_post_id, kind);
```

Plus, in the same defensive `DO $$ … END $$` style the journal migration uses, a CHECK
that `kind IN ('myth_bust','fear','win')` — a CHECK, not a PG enum, per the house
precedent stated in that file.

**RLS is load-bearing, not boilerplate:**

```sql
ALTER TABLE journal_community_post ENABLE ROW LEVEL SECURITY;
```

No policies, on purpose. The FE inlines `NEXT_PUBLIC_SUPABASE_ANON_KEY` into the
browser bundle, so without this anyone could `GET /rest/v1/journal_community_post`
straight through PostgREST and read every unpublished draft. RLS-on-zero-policies
locks out `anon`/`authenticated` entirely while the backend's service-role key
bypasses it. **Every new public-schema table gets this in its creating migration** —
the standing rule from the 2026-07-25 RLS sweep.

Rollback comment at the bottom, as the other migrations have. **Name this migration in
the PR description** — "on main" ≠ "run in prod".

### 2.9 DB methods — `services/db.py`

Follow the defensive pattern of the journal methods and
`upsert_user_arc_ideal_notes` (~`services/db.py:9763`): guard args, try/except,
detect the missing-table error and log `run migrations/add_journal_community_posts.sql`,
return falsy instead of raising.

```python
def upsert_journal_community_posts(self, journal_post_id, items) -> list
    # Upsert on (journal_post_id, kind). `items` is 1..3 rows — a single-format
    # regenerate passes one and leaves the siblings untouched.
def list_journal_community_posts(self, journal_post_id=None) -> list
    # No id → every row (the CMS loads all of them once and groups client-side).
def get_journal_community_post(self, item_id) -> Optional[dict]
def update_journal_community_post(self, item_id, changes) -> Optional[dict]
    # title/body only; stamps updated_at.
def delete_journal_community_post(self, item_id) -> bool
```

Deleting the parent journal post cascades — no application-level cleanup needed.

### 2.10 Routes — extend `routes/journal.py`

New section under the existing ADMIN block, same conventions: **POST only, password in
the body**, first line of every handler is `ok, err = _journal_admin_ok()`, reuse
`_body()` / `_invalid()`, `logger.error(..., exc_info=True)` in each except. Do **not**
add a new blueprint and do **not** add anything to the public section.

```
POST /v2/internal/journal/community/generate
  body { password, post_id, formats?: ["myth_bust"|"fear"|"win"], notes? }
  200 { items: [ {...}, ... ], pillar_id, pillar_name, theme,
        soft_cta_line, app_proof_line }
  400 INVALID_INPUT (missing/blank post_id, bad formats, empty post body)
  401 · 404 (unknown post_id) · 503 (password unconfigured, flag off, or the
      strategy doc / LLM is unavailable) · 500

POST /v2/internal/journal/community/list    { password, post_id? } → 200 { items }
POST /v2/internal/journal/community/update  { password, id, title?, body? } → 200 { item }
POST /v2/internal/journal/community/delete  { password, id } → 200 { deleted }
```

`generate` behaviour:

1. Load the parent via `db.get_journal_post_by_id(post_id)`; 404 if absent.
2. Refuse with 400 when the parent's `body` is blank — there is nothing to derive from.
3. Call `generate_community_posts`; `None` → `503 {"code":"V2_ERROR","error":"Could not generate right now"}`.
4. **Single-format regenerate rule:** when `formats` names fewer than all three, keep
   the batch-level fields (`pillar_id`, `pillar_name`, `theme`, `soft_cta_line`,
   `app_proof_line`) from the existing sibling rows and write only the new row's
   `title`/`body`/`flags`. A one-post reroll must not silently re-theme the week.
5. Upsert and return the full current set for that post, not just the regenerated one.

`update` accepts `title`/`body` only — the founder edits the draft; the model's
`flags` are cleared on a manual edit (he has looked at it).

### 2.11 Kill-switch

`COMMUNITY_CONTENT_ENABLED` in `config.py` alongside the other flags, **default ON**.
Off → `generate` 503s; list/update/delete keep working so existing drafts stay
readable. Cheap insurance on an LLM-cost surface, per house convention.

### 2.12 Tests — `test_community_content.py`

New root-level file (the repo keeps tests at root). **Use the stub-isolation
convention** — `setUpModule` saves and stubs `services.db`; `tearDownModule`
**restores the saved original**, never a bare `pop` (a bare pop spawns a second
`DatabaseService` singleton and silently breaks other modules' patches). Copy the
header of `test_say_it_stronger.py:1-33`.

1. `load_strategy()` is non-empty and the system prompt contains all six pillar names —
   i.e. the doc actually reaches the model.
2. `build_user_prompt` includes title/excerpt/body, the requested formats and the
   notes; truncates a >20 000-char body.
3. `_clean_payload`: drops empty bodies; dedupes formats; strips `**markdown**`;
   truncates; clamps a bogus `pillar_id`; computes `char_count`.
4. Construct guard: a body containing `charisma score` is **present** with
   `flags == ["construct"]`, not dropped.
5. Fabrication flag: a body citing "a 2019 study" absent from the essay gets `"verify"`;
   a number that *is* in the essay does not.
6. `generate_community_posts` returns `None` on: empty body, missing strategy doc, LLM
   import failure, `chat_complete` → None, malformed JSON. Never raises.
7. Routes: 401 wrong password; 503 unconfigured password; 503 flag off; 400 missing
   `post_id`; 400 blank parent body; 404 unknown `post_id`; 200 shape with the service
   patched.
8. Single-format regenerate preserves the siblings' `theme`/`pillar`/lines (§2.10.4).
9. **Public isolation** — extend #254's isolation test: no `/v2/journal/*` handler
   references `journal_community_post`.
10. **L1 grep-fence** over the five assembly modules in §2.7.

Full suite must stay green (~1765 tests):

```bash
python3 -m unittest discover -s . -p 'test_*.py' -q
```

---

## 3. Frontend (`frontend-cursor`)

Everything lands in the existing CMS. **No new page, no new route.**

### 3.1 API client — `src/services/api/journalAdmin.ts`

Add four calls using the existing private `post()` helper (password in body, every
call a POST — the module header explains why). Mirror the existing `AdminResult<T>`
return shape and `readError` handling.

```ts
export type CommunityKind = "myth_bust" | "fear" | "win";

export interface CommunityPost {
  id: string;
  journalPostId: string;
  kind: CommunityKind;
  title: string;
  body: string;
  flags: string[];            // "construct" | "verify"
  pillarName: string | null;
  theme: string | null;
  softCtaLine: string;
  appProofLine: string;
}

adminGenerateCommunity(password, postId, opts?: {formats?, notes?})
adminListCommunity(password, postId?)
adminUpdateCommunity(password, id, changes)
adminDeleteCommunity(password, id)
```

Note for whoever writes the fetch: **gpt-4o with 2400 max_tokens takes 10–25s.** Make
sure no proxy or client timeout is shorter, and surface honest progress copy.

### 3.2 BFF proxies

Four new routes under `src/app/api/v2/internal/journal/community/` —
`generate/`, `list/`, `update/`, `delete/`, each a `route.ts`. Copy an existing one
verbatim (e.g. `src/app/api/v2/internal/journal/posts/update/route.ts`) — same relay
shape, same `runtime`, same status passthrough. Nothing clever.

### 3.3 The CMS page — `src/app/cms/page.tsx`

Two additions. Match the file's existing register (the `BTN_*` / `INPUT_CLS` /
`LABEL_CLS` constants, `busy` gating, `StatusPill`).

**(a) The button and cards — a new section 8, directly under the body textarea**
(currently the last block in the editor, ~`src/app/cms/page.tsx:895`). This is the
"under the blog post" the founder asked for.

- Heading `Community posts`, with the pillar + theme shown once generated
  (`Focus & attention · The Re-Entry Note`).
- **One primary button.** `Generate community posts` when the post has none;
  `Regenerate all` when it does — and that variant confirms first, because it
  replaces existing edited drafts.
- Disabled with an explanatory `title` when the post is unsaved (`!editing.id`) or the
  body is empty — same affordance the Publish button already uses for unsaved drafts.
- While running: spinner + honest copy — `Writing three posts, about 20 seconds…`.
- Then three cards in posting order — **Tue Fear · Thu Myth-bust · Sat Win** (strategy
  doc §4 cadence). Each card: day badge, format name, title, body in a
  whitespace-preserving block, char count, and
  - **Copy** — `navigator.clipboard.writeText(body)`, 2s `Copied ✓`.
  - **Edit** — inline textarea, saves via `adminUpdateCommunity`.
  - **Regenerate** — this format only.
  - **Flag warnings** above the body when `flags` is non-empty:
    `construct` → "uses retired score vocabulary — reword before posting";
    `verify` → "contains a claim that isn't in your post — check before posting".
- Above the three cards, a **Copy post body** button — that's format ① Technique,
  taken from `editing.body` client-side. It never round-trips through the API and has
  no Regenerate.
- Below them, the two opt-in lines, each with its own Copy button and one line of
  when-to-use: `app_proof_line` ("append to the Technique post every other week or
  so") and `soft_cta_line` (rendered only when non-empty).

**(b) The queue — the left-hand list** (~`src/app/cms/page.tsx:486-585`). Load every
community item once with `adminListCommunity(password)` alongside the post list, group
by `journalPostId`, and render each post's items **indented directly beneath it** as
compact rows: a `COMMUNITY` pill in a visibly different colour from `StatusPill`, the
format name, and the truncated title. Clicking one opens the parent post's editor and
scrolls to (and briefly highlights) that card in section 8 — **one editing surface, two
ways in**. No reorder arrows, no preview eye, no publish control on these rows: they
can never be published, and the UI should make that obvious.

### 3.4 FE tests

Extend the existing CMS/journal vitest coverage rather than starting a new file:
`Copy post body` writes `editing.body` verbatim to a mocked clipboard with no network
call, and a community row renders no publish affordance.

---

## 4. Delivery checklist

- [ ] BE PR: strategy file, `services/community_content.py`, `SPEC_COMMUNITY_CONTENT`,
      5 db methods, 4 routes in `routes/journal.py`, migration,
      `COMMUNITY_CONTENT_ENABLED`, `test_community_content.py`.
- [ ] Full BE suite green; #254's isolation test extended, not weakened.
- [ ] PR description names the migration: `migrations/add_journal_community_posts.sql`.
- [ ] FE PR: 4 client calls, 4 BFF proxies, CMS section 8 + nested queue rows, tests.
- [ ] Verify end to end on a real essay: write a post, save, generate, confirm three
      items appear both under the body and nested in the queue, copy each of the four
      blocks, confirm the Technique block is byte-identical to the post body, and
      confirm the community items are absent from `/v2/journal/posts` and from
      `/blog`.

## 5. Open questions for the founder (ship the default if unanswered)

1. **Language** — English-only community, or mirror the essay's language?
   Default: mirror.
2. **Post-length ranges** (§2.5) are inferred from the strategy doc's descriptions, not
   stated in it. Tune after the first real week.
3. **Deleting the parent** cascades its three community drafts away. Assumed correct;
   say so if you'd rather they survive.

---

## Appendix A — `services/prompts/community_content_strategy.md`

Commit the block below verbatim as that file.

```markdown
# WillLab community — content model

Source: WillLab Community Content Strategy, Draft v1, 23 July 2026.
This file is the content model the generator works from. Edit it to change the
model; no code change is needed.

## The spine (one line)

Work with your wiring, not against it — do your best work, and say it well,
without grinding yourself down.

Broad enough to cover focus, starting, mental load, perfectionism, and
communication; specific enough that a member can describe it to a friend as "a
community about doing good work without burning yourself out, and getting your
ideas across." The "say it well" half is the natural bridge to the app.

## The six pillars (a post always belongs to exactly one)

1. **Focus & attention** — switching, deep work, protecting a block.
2. **Mental load & capture** — brain-dump, second brain, offloading.
3. **Social energy & presence** — warm-ups, coming across warm not cold.
4. **Starting & momentum** — beating the freeze, tiny first steps.
5. **Letting go & self-compassion** — "good enough," releasing perfect.
6. **Communicating clearly** — curse of knowledge, one point / three angles.
   This is the app-bridge pillar: posts here may carry a soft app mention.

## The one mechanic: one essay → four posts

The founder makes exactly ONE thing per week — the Technique essay, talked into
his own app and refined by it. The other three posts are the SAME IDEA ROTATED,
not new ideas. Never write four original things.

### ① TECHNIQUE — the anchor (already written; never regenerated)

Shape: The science → The how → Try it (you go first). This is the input, not an
output.

### ② MYTH-BUST — derive by INVERSION

Take the technique's core claim, name the false belief it corrects, and flip it.
Shape: "Myth: [common belief]." → the flip in 3–4 lines → one-line reframe.
Short, shareable, mid-week.

### ③ FEAR — derive by CONFESSION

Name the emotion underneath the technique — what the member is quietly afraid
of. Confess your own version of it first, then invite raised hands. Pure
vulnerability plus a question. This format drives the most comments; it must end
on a real question, not a rhetorical one.

### ④ WIN — derive by PROMPTING (members write it, not the founder)

Turn the technique into a share-your-example thread: one leading emoji, a warm
prompt, and the founder's own example first ("you go first"). Lightest lift,
highest engagement. It is a prompt, not an essay.

## Posting cadence

| Day | Post | Why then |
|---|---|---|
| Mon | Technique | the anchor essay |
| Tue | Fear | confession → comments early in the week |
| Thu | Myth-bust | short, shareable, mid-week |
| Sat | Win | member-fill thread → weekend engagement |

## Voice and format rules

- First person, the founder's own voice, matched to the source essay's register.
- Plain text for Skool: no markdown, no headings, no hashtags, no links. Line
  breaks and blank lines only. At most one emoji, leading the Win post.
- Warm, direct, non-lecturing. No corporate jargon ("leverage", "synergy",
  "utilize", "in order to").
- Never invent a fact, statistic, study, or researcher that is not in the source
  essay.
- Never quote a score, ratio, or classifier of any kind about the reader.
- Never mention the app inside a post body. App mentions are separate opt-in
  lines the founder appends himself.

## The two separate app lines (never inside a post body)

- **Soft CTA** (pillar 6 only, strategy doc §6 "Contextual"): one sentence, in
  the founder's voice, along the lines of "I built a tool for exactly this;
  members get in first."
- **App-as-proof seam** (strategy doc §5-D, used roughly biweekly): one sentence
  showing the seam — this post started as a short rambly voice note and the
  founder's own tool cleaned it into this. Phrase it for the specific essay.
```
