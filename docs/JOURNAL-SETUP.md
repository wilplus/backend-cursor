# Journal (blog) + CMS — BE setup

Public Journal on www.willpowerlab.com plus a password-gated in-house CMS.
Fully self-contained: the only table is `journal_post`, and nothing in the
record → transcribe → coach → read loop reads or writes it.

FE spec: `docs/journal-fe-prompt.md` in the `frontend-cursor` repo.

---

## 1. Run the migration

```bash
psql "$DATABASE_URL" -f migrations/add_journal_posts.sql
```

Idempotent (`IF NOT EXISTS` throughout, CHECK constraints added defensively),
so it is safe to run before or after the deploy and safe to re-run. Every DB
helper is best-effort — with the table absent the public index simply returns
`{"posts": [], "total": 0}` instead of erroring.

**The migration enables RLS, and that is load-bearing — do not drop it.** The
FE ships `NEXT_PUBLIC_SUPABASE_ANON_KEY` inlined in the browser bundle, so
anyone can read it out of the JS and call PostgREST directly. Without RLS the
default public-schema grants would let a visitor
`GET /rest/v1/journal_post?status=eq.draft` and read every unpublished draft,
and `PATCH`/`DELETE` published ones, without ever seeing
`JOURNAL_ADMIN_PASSWORD`. No policies are added on purpose: with RLS on and
zero policies, `anon` can do nothing, while the backend (service-role key)
bypasses RLS and keeps full access. Every public read is therefore served only
through `/v2/journal/*`, where the published filter applies.

The migration also backfills `published_at` for any published row missing one
(see §4 for why a NULL display date would pin a post to the top of the index).

## 2. Set the env vars (Railway)

| Var | Required | What it does |
|---|---|---|
| `JOURNAL_ADMIN_PASSWORD` | **yes, for the CMS** | Unset ⇒ every `/v2/internal/journal/*` endpoint answers **503 DISABLED**. The public read endpoints work regardless. |
| `R2_JOURNAL_BUCKET` | for uploads | Falls back to `R2_USER_MEDIA_BUCKET`, then `R2_BUCKET_NAME`. |
| `R2_JOURNAL_PUBLIC_BASE_URL` | for uploads | CDN / `pub-<hash>.r2.dev` base. Falls back to the user-media then generic R2 base. **No base URL ⇒ presign refuses** rather than stranding a file it cannot reference. |
| `JOURNAL_MAX_IMAGE_MB` / `_AUDIO_MB` / `_VIDEO_MB` | no | Per-kind caps. Defaults 10 / 50 / 500. |

R2 credentials are the shared existing ones (`R2_ACCOUNT_ID`,
`R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`) — no new credentials.

The R2 journal bucket must be **public-read** (or fronted by a CDN) since the
covers are served to anonymous visitors, and needs **CORS allowing PUT** from
the app origin so the browser can upload directly.

## 3. Endpoints

### Public — no auth, no session, no token

The FE server-renders these with ISR, so they must answer an anonymous
request. Drafts are invisible on every path: an unknown slug and a draft slug
return an identical 404, so unpublished work cannot be enumerated.

```
GET /v2/journal/posts?category=&q=&sort=&limit=&offset=
    → { posts: [card…], total }
    sort: newest (default) | oldest | curated
    category: one of the six keys, or omitted/all
GET /v2/journal/posts/<slug>   → the full post · 404 for draft/unknown
                                 503 (not 404) if the DB is unreachable, so a
                                 blip is never cached as "post not found"
GET /v2/journal/categories     → { categories: [{key, count}] }  (all six, 0s included)
```

The card shape never carries `body`, `status`, or `id`. The full post adds
`body`, `media_url`, author and SEO fields but still omits `status`/`id`.

### Admin — password in the BODY, so every route is POST

Mirrors the credits-admin pattern in `routes/internal_webhooks.py`. Wrong
password ⇒ **401 `{"error": "Wrong password"}`**; unset password ⇒ **503
DISABLED**. Compared with `hmac.compare_digest`; never logged.

```
POST /v2/internal/journal/posts/list       { password, limit?, offset? }
                                           → { posts, total }   (paged)
POST /v2/internal/journal/posts/get        { password, id }
POST /v2/internal/journal/posts/create     { password, ...fields }   → 201
POST /v2/internal/journal/posts/update     { password, id, ...fields }
POST /v2/internal/journal/posts/delete     { password, id }
POST /v2/internal/journal/posts/publish    { password, id }
POST /v2/internal/journal/posts/unpublish  { password, id }
POST /v2/internal/journal/reorder          { password, ids: [...] }
POST /v2/internal/journal/media/presign    { password, filename, content_type, kind }
```

A slug collision returns **409 `DUPLICATE_SLUG`**, never a 500.

`update` writes **only the keys present in the request**, so a save never
blanks a field the author did not touch.

## 4. The two semantics that are easy to get wrong

**`published_at` is the display date; `status` is visibility.** They are
independent, which is what lets a post be backdated.
- `publish` sets `status=published` and stamps `published_at` **only when it
  is still null** — an author-set date is never overwritten.
- `unpublish` sets `status=draft` and **keeps** `published_at`, so
  re-publishing restores the same display date.
- Setting `status: "published"` through `create`/`update` (the editor's own
  status control, rather than the publish button) **also** stamps a date when
  none exists. This is not cosmetic: Postgres orders `DESC` as NULLS FIRST and
  the Supabase client cannot emit `nullslast`, so a published post with a NULL
  date would pin itself to the top of the public index permanently.
- `read_time_min` is author-supplied and never derived. We do not count words.

**An explicit JSON `null` on `update` means "leave this alone", not "reset to
default".** A CMS form that serializes untouched optional inputs as `null`
would otherwise send `{"status": null}` and silently unpublish a live post.
Send only the keys you intend to change; `null` keys are dropped.

**`body` is PLAIN TEXT.** Paragraphs are separated by blank lines; the FE
splits on `/\n\s*\n/` and renders `<p>` elements, never
`dangerouslySetInnerHTML`. No HTML or Markdown is stored or interpreted, so
there is no XSS surface. `services/journal.normalize_body` normalizes CRLF,
strips control/zero-width/bidi characters, and collapses 3+ newlines to
exactly one blank line. If the body format ever grows markup, that function is
where sanitization has to start.

## 5. Media uploads: presigned direct-to-storage

```
CMS → POST /v2/internal/journal/media/presign
    → { upload_url, public_url, key, headers, expires_in, max_bytes }
CMS → PUT the file to upload_url with EXACTLY the returned headers
CMS → save public_url on the post (cover_image_url / media_url)
```

The bytes never transit Flask or the Next BFF — required, not an
optimization: Vercel's ~4.5MB serverless body limit already 413s on audio, and
Journal video is far larger. `Content-Type` is part of the signature, so the
PUT must echo the returned header verbatim or R2 answers
`SignatureDoesNotMatch`.

Object keys are `journal/<kind>/<uuid4><ext>` — randomized, never derived from
the client filename (no traversal, no collisions, no leaking local filenames
on a public URL). MIME allowlist per kind; caps 10/50/500 MB by default.

An author pasting an external `https://` URL skips presign entirely. Media
URLs are **https-only**: `http` would be mixed content and `javascript:` /
`data:` would be an injection vector in the `src` attribute.

## 6. Seeding the first post

The Journal renders as soon as one published post exists. Either use the CMS,
or insert directly:

```sql
INSERT INTO journal_post (slug, title, excerpt, category, read_time_min,
                          cover_kind, cover_image_url, cover_alt, body,
                          status, published_at)
VALUES ('why-your-voice-shakes', 'Why your voice shakes',
        'The physiology behind the wobble, and what actually settles it.',
        'physiology', 4, 'image', 'https://your-cdn/cover.jpg',
        'A microphone on a stand',
        E'First paragraph.\n\nSecond paragraph.', 'published', now());
```

## 7. Not built (deliberate)

- **Sitemap / RSS** — listed as optional in the spec; say the word.
- **Server-side video poster extraction and audio duration probing** — the CMS
  supplies `media_duration_sec`.
- Public reads are CDN-cacheable; no cache headers are set server-side yet
  (the FE's 300s ISR window is doing that job).
