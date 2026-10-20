# BE handoff — Task 9: admin Tab 4 (Files) Next.js page

Status: **BE complete. Pure FE work — Next.js page + BFF proxy.** Three small premise corrections in the brief, none blocking. Two optional BE enhancements you might want before shipping the page (delete + pagination); flagged at the bottom.

---

## Premise corrections

| Brief said | Reality |
|---|---|
| Endpoint at `v2_routes.py:14538` | Actually at **`routes/v2_routes.py:15263`**. Line 14538 is mid-snippet-PATCH logic, unrelated. Not blocking — the endpoint exists. |
| "This is a Next.js page" with no scope qualifier | This is the **admin Tab 4** Files tab on the per-user admin-detail page. The endpoint is `@require_admin`, not user-facing. If you meant a user-facing "my uploads" page, that endpoint doesn't exist today and would be a different task. |
| "Backend done" | Confirmed for **read + playback**. No DELETE endpoint exists. No pagination on the GET. If either matters for v1 UX, flag and I add — both are small. |

---

## The endpoint FE wires against

```http
GET /v2/admin/users/<user_id>/files
Authorization: Bearer <admin JWT>
Optional query: ?expires_in=<seconds>   # 60..604800; default 3600 (1h)
```

```jsonc
// 200 response
{
  "user_id": "<uuid>",
  "files": [
    {
      "id":           "<uuid>",
      "session_id":   "<uuid>" | null,   // file may or may not be bound to a session
      "file_name":    "talk-2026-05-15.mp4",
      "file_type":    "audio" | "video",
      "content_type": "video/mp4",
      "size_bytes":   12345678,
      "r2_url":       "https://..." | null,   // cached public URL when bucket is public
      "playback_url": "https://...",          // ALWAYS populated — see TTL notes
      "created_at":   "2026-05-15T14:39:00Z"
    }
    // ...newest first, no pagination
  ],
  "total": 17
}
```

400 INVALID_INPUT on bad UUID, 500 V2_ERROR on anything else, 403 FORBIDDEN if the caller's JWT isn't on the admin allowlist (handled by `@require_admin`).

---

## How `playback_url` works (important — TTL behavior)

The handler decorates every row with a `playback_url` so FE never round-trips for a "give me a play link" call:

| Storage setup | `playback_url` is | TTL |
|---|---|---|
| Public R2 bucket | The cached `r2_url` from the row (same value as `r2_url`) | Permanent (it's a public URL) |
| Private R2 bucket | A fresh **signed URL** minted per-request via `presigned_get_user_media` | `expires_in` seconds (default 3600 = 1h, max 604800 = 7 days, min 60s) |

**FE consequence**: if your Files page sits open for >1h on a private-bucket deploy, the signed URLs in your local state go stale. Two reasonable patterns:

- **Cheap**: re-fetch the list on play-click. Fresh signed URLs on every request. Simple. Slight latency on every play.
- **Less cheap**: track `fetched_at`; if `now - fetched_at > 50min`, re-fetch the list silently. Smooth UX, slightly more code.

Pass `?expires_in=21600` (6h) on the GET if you want a longer TTL than the default — most public-deployment use cases probably want this.

Same URL works for **play AND download**:
```tsx
<audio src={file.playback_url} controls />
<video src={file.playback_url} controls />
<a href={file.playback_url} download={file.file_name}>Download</a>
```

No separate download endpoint — same R2 URL, just the right HTML element.

---

## FE deliverables

### BFF route
`src/app/api/admin/users/[userId]/files/route.ts`. Same forward-the-bearer-token pattern as the other admin BFF routes. Pass `?expires_in` through from query to upstream.

### Files tab UI

Suggested columns / fields per row (everything's already in the response):

| Column | Source | Format hint |
|---|---|---|
| Icon | `file_type` ("audio" → 🎵, "video" → 🎬) | Lucide audio/video icons |
| File name | `file_name` | Truncate at ~40 chars with full-name tooltip on hover |
| Type | `content_type` | Display the second part — `mp4`, `webm`, `mp3` |
| Size | `size_bytes` | Format as B/KB/MB/GB |
| Session | `session_id` | Link to that session's detail tab if non-null; "Unlinked" otherwise |
| Created | `created_at` | Format with `date-fns` — e.g. "15 May 2026 14:39" or relative "2 days ago" |
| Play | `playback_url` + `file_type` | Inline `<audio>`/`<video>` modal OR a small dropdown player |
| Download | `playback_url` + `file_name` | `<a download>` anchor with download icon |

### Empty state
`total === 0` → "No files uploaded yet. Files appear here after the user uploads via the in-app uploader or the `/v2/user/upload-media` endpoint."

### Error state
GET fails / 500 → "Couldn't load files. Try refresh." with a retry button.

---

## What BE could add if FE asks

Two enhancements that are NOT in scope of "the existing endpoint" but you'd probably want before this page is genuinely production-ready:

| Feature | What | LOC | Open question for you |
|---|---|---|---|
| **DELETE** `/v2/admin/users/<user_id>/files/<file_id>` | Admin removes a file (R2 delete + row delete). Useful for user-requested data removal (GDPR Art. 17 right-to-erasure) and admin cleanup of mis-uploaded files. | ~25 | Should it be hard-delete (irreversible) or soft-delete (`deleted_at` column, file hidden from this endpoint)? My recommendation: **soft-delete** with a manual hard-delete cron weekly, lets you recover from accidental clicks. |
| **Pagination** on GET | `?limit=N&offset=N` query params + `has_more` in response. Today returns all files in one shot — fine for normal users with <50 files, problematic if any user is a power-uploader with hundreds. | ~10 | Need it for v1 or defer until a user actually hits the pain? Default: defer. |

Reply with which (if either) you want and I ship in a follow-up commit. Don't block the FE page on these — the read endpoint is enough to ship the v1 UI.

---

## Acceptance criteria (when FE ships)

1. Admin navigates to `/admin/users/<id>` Tab 4 → page loads → file list renders with the columns above.
2. Click play on an audio row → inline player streams via `playback_url`.
3. Click play on a video row → same, but with a `<video>` element.
4. Click download → file downloads with `file_name` as the saved name.
5. Empty user (no uploads) → empty state copy.
6. Stale signed URL (page open > 1h on private-bucket deploy) → either silent refresh or the play-click triggers a fresh fetch (depending on which strategy you pick).
7. Non-admin token → 403 from BFF (admin gate is BE-enforced via `@require_admin`).

---

## Reply with

- "Ship the FE page" — confirms scope is the admin Files tab and BE work is done. Move forward.
- (Optional) which of the two BE enhancements above to add: DELETE / pagination / both / neither

No further BE work unless you ask for one of the enhancements.
