# FE handoff — generated Journal cover images (paste into a fresh Claude session in `frontend-cursor`)

You are working in the willab frontend (Next.js, `/Users/arturwillonski/Documents/frontend-cursor`). The BE side is branch `feat/journal-cover-images` in `backend-cursor` — the contracts below are pinned and safe to build against.

**One token.** The Journal CMS gets a "Draw a cover" button: the model reads the post, writes an image brief, draws it, and the file lands in the same R2 bucket an uploaded cover already uses. A notes box steers the next attempt, "Regenerate" re-runs it, and every attempt is kept so Regenerate is never destructive.

Everything lives in the **Cover media** block of `src/app/cms/page.tsx` (~lines 704-806). The closest existing analogue in this repo is `src/app/cms/CommunitySection.tsx` — same auth, same generate/regenerate/notes shape, same error mapping. Read it first; you will be repeating its patterns almost exactly.

---

## 0. What already exists (do not rebuild)

- `adminPresign` + `uploadToStorage` (`src/services/api/journalAdmin.ts:337,366`) — the **manual upload** path. It stays. Generation is a second way to fill the same field, not a replacement.
- The cover preview + the "Cover image URL" text input (`page.tsx:728,795`). The generated cover writes to that same `cover_image_url`, so the preview needs no changes.
- `getBackendUrl()` BFF passthrough shape — copy `src/app/api/v2/internal/journal/media/presign/route.ts` verbatim for each new route.

---

## 1. BFF routes to add

Four passthroughs, byte-identical in shape to the presign route (`runtime = "nodejs"`, relay status + body verbatim, never log the password):

| file | upstream |
|---|---|
| `src/app/api/v2/internal/journal/image/generate/route.ts` | `POST /v2/internal/journal/image/generate` |
| `src/app/api/v2/internal/journal/image/list/route.ts` | `POST /v2/internal/journal/image/list` |
| `src/app/api/v2/internal/journal/image/select/route.ts` | `POST /v2/internal/journal/image/select` |
| `src/app/api/v2/internal/journal/image/delete/route.ts` | `POST /v2/internal/journal/image/delete` |

⚠️ **Give `generate` a long timeout — longer than you think.** Measured against the live API: **23s for a first draw, 98s for a steered regenerate.** Set `maxDuration` on this route to **180**, and make sure your client-side fetch has no shorter timeout of its own. If the platform cuts the request off, the CMS sees a 504 while the backend is still drawing — and the image completes, gets paid for, and lands in the history strip with nobody watching. (That is recoverable: it shows up in `items` on the next `list`. It still looks like a failure to the founder.)

---

## 2. API client (`src/services/api/journalAdmin.ts`)

Password rides in the body, same as every other admin call.

```ts
export type CoverImage = {
  id: string;
  journalPostId: string;
  imageUrl: string;
  altText: string;
  prompt: string;          // the brief the model was given
  revisedPrompt: string;   // what the image model says it drew ("" for most)
  notes: string;           // the steer that produced THIS attempt
  parentImageId: string | null;
  flags: string[];         // ["construct"] ⇒ show the warning, do not hide
  model: string | null;
  size: string | null;
  quality: string | null;
  createdAt: string | null;
};
```

```
adminGenerateCoverImage(password, {
  postId,            // required
  notes?,            // the steer for THIS attempt
  parentId?,         // refine a specific earlier attempt
  fresh?,            // true ⇒ ignore history, brief from the essay alone
  attach?,           // default TRUE — writes the result onto the post's cover
})
adminListCoverImages(password, postId)
adminSelectCoverImage(password, imageId)   // promote an earlier attempt
adminDeleteCoverImage(password, imageId)   // clear a candidate from the strip
```

### `generate` → 200

```jsonc
{
  "image": { /* CoverImage — the attempt just drawn */ },
  "items": [ /* CoverImage[] — the whole strip, newest first, max 24 */ ],
  "post":  { /* the updated admin post shape, or null when attach was false */ },
  "attached": true,
  "brief_source": "model",      // or "fallback" — see §5
  "attach_error": "…"           // present ONLY when the image was drawn but
                                // could not be saved onto the post
}
```

`items` comes back on every generate, so **re-render the strip from the response** — do not fire a second `list` call after a draw.

`list` → `{ items }`. `select` → `{ post, image }`. `delete` → `{ deleted }`.

---

## 3. The UI

Inside the **Cover media** block, under the existing preview + URL input.

**a) The draw button.** `Draw a cover` when the post has no generated attempt, `Regenerate` once it does. Disabled while a draw is in flight and when the post has neither a title nor a body (the BE 400s on that — a post with nothing to read has nothing to draw).

**b) The notes box.** A one-line textarea above the button, placeholder something like *"darker, no hands, less literal"*. It is the steer for the **next** attempt. Send it as `notes`.

Two things make this feel right, and both are already handled backend-side — just don't fight them:
- A note is applied **to the previous brief**, not to the essay from scratch. "Darker" means the cover on screen, darker. So **keep the note in the box after a draw** — the founder usually stacks steers ("darker" → "darker, and no hands"). Don't clear it.
- Regenerate with an **empty** note deliberately draws a *different* scene rather than a near-copy. That is the intended behaviour of a bare Regenerate; do not add a hidden "make it different" note of your own.

**c) The strip.** Thumbnails of `items`, newest first, horizontally scrollable. The one whose `imageUrl` matches `editing.cover_image_url` gets a selected ring. Click a thumbnail → `adminSelectCoverImage` → replace `editing` with the returned `post`. That is the **undo for Regenerate** and it is the whole reason the history exists. A small ✕ on hover → `adminDeleteCoverImage` (removes the candidate; the file stays in storage, so a post still pointing at it does not break).

**d) The brief, collapsed.** A `<details>` under the strip showing `prompt` (and `revisedPrompt` when non-empty). The founder should be able to see what was asked for — it is the fastest way to understand why an image came out wrong, and it makes the notes box legible.

**e) Alt text.** The draw writes `cover_alt` too, and **overwrites it on every attempt on purpose** — alt text describes the image, and the image just changed. Nothing to build; just don't cache the old alt in local state across a draw. Re-render the alt input from the returned `post`.

**f) Immediate feedback (the story asks for this explicitly).** The wait is **23-100 seconds** — a bare spinner over that reads as broken, and it is the single biggest UX risk in this feature. Use the existing CMS button-busy pattern plus a status line that changes at least twice: `Writing the brief…` → `Drawing…` (~3s) → `Still drawing — this one is taking a while…` (~35s). It is a timed label, not real progress; that is fine, and it is what keeps a 90-second draw from looking like a hang. Keep the previous image visible underneath the whole time — never blank the preview while drawing.

---

## 4. Error mapping

Relay the backend's own `error` string; it is written to be shown. The codes that need distinct handling:

| status | code | what to show |
|---|---|---|
| 400 | `IMAGE_REJECTED` | The safety system refused the brief. **Keep the notes box populated** and tell the founder to reword — a retry of the same brief will fail identically. |
| 400 | `INVALID_INPUT` | Field error (empty post, `parent_id` from another post). |
| 401 | `UNAUTHORIZED` | Wrong password — same as every other CMS call. |
| 503 | `DISABLED` | Either the kill switch is off **or** storage is unconfigured; the message says which. Not retryable — do not offer "Try again". |
| 503 | `V2_ERROR` | Transient draw failure. **This one is retryable** — offer the retry. |
| 200 + `attach_error` | — | The image drew and stored but could not be saved onto the post. Show the image in the strip with a warning; the founder can click the thumbnail to retry the attach via `select`. Never discard it. |

---

## 5. `brief_source: "fallback"`

The brief normally comes from a text model. When that call fails, the backend falls back to a deterministic brief built from the title + excerpt + notes and draws anyway — a worse image, but a working button. Show a quiet note ("drew from a basic brief") when `brief_source === "fallback"`; it explains an oddly literal cover without the founder having to guess.

---

## 6. Fences — do not cross these

- **`flags: ["construct"]` is a WARNING, never a hide.** It means the retired score vocabulary reached the generated alt text or brief. Show it above the strip item; the founder edits or rerolls. Do not filter the item out, and do not auto-rewrite the copy.
- **No public surface.** These candidates are CMS-only. Nothing under `src/app/journal/**`, `src/services/api/journal.ts`, or `journalServer.ts` may read them — the public site sees only `cover_image_url` / `cover_alt` on the post itself.
- **`cover_kind` is never changed by a draw.** On a video post the drawn image is the poster frame; flipping the kind would drop the video.
- **Do not add generation to the public site or to any user-facing surface.** This is a founder-only CMS tool.

---

## 7. Test

1. Unlock the CMS, open a post with a body, click **Draw a cover** → an image appears in the preview and in the strip; the alt input fills in.
2. Type `darker, no hands` → **Regenerate** → the new cover is recognisably the same scene, darker. The note stays in the box.
3. Clear the note → **Regenerate** → a *different* scene.
4. Click the first thumbnail → the preview and alt revert to that attempt.
5. Save the post → reload the CMS → the strip is still there (it is server-side) and the cover survived.
6. Wrong password → 401 on every one of the four calls.

---

## Operational note (BE, not FE — for whoever deploys)

`migrations/add_journal_post_image.sql` must run before the strip persists. Without it the draw still works and still sets the cover; only the history is empty. Env: `JOURNAL_IMAGE_ENABLED` (default on), optional `JOURNAL_IMAGE_MODEL` / `_SIZE` / `_QUALITY` / `JOURNAL_IMAGE_STYLE`. Storage reuses the existing `R2_JOURNAL_*` config — if covers upload today, generation stores fine.
