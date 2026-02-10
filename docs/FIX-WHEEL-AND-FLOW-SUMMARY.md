# Fix the wheel and the homework flow — what’s wrong and what to do

One-page summary of what’s broken, why it might be failing, and the order of fixes.

---

## 1. What’s wrong

| Problem | What you see |
|--------|---------------|
| **Wheel not updating** | Strength/pace dartboard stays static (e.g. -160 dB, ~60 WPM) and doesn’t move in real time while recording. |
| **409 “Session must be in warm_up for recording-1”** | User is on step 1 (Warm-up) but backend session is already in a later status (e.g. `final_task_ready`). Send or recording-upload-url returns 409. |
| **403 on Send (Storage)** | After clicking Send, upload to Supabase Storage fails with 403 “new row violates row-level security policy”. |
| **Recording / next step only after refresh** | After completing recording-1 or metric-answers, the UI doesn’t advance until the page is refreshed. |

---

## 2. Why it might be failing

### Wheel

- **Chunk requests never sent** – PCM pipeline not started on the step that shows the wheel, or it’s torn down (e.g. after BFF change or re-render / applyStatusToState). **Check:** Network tab → any repeated `recording-metrics-chunk` requests?
- **Chunk requests return 401** – BFF `getV2AccessToken()` is null (no session in BFF context). **Check:** Status code of chunk request.
- **Chunk requests return 404** – Wrong URL; often **sessionId is undefined** because in Next 15 `params` is a Promise and wasn’t awaited. **Check:** URL of the failing request (e.g. `.../session/undefined/recording-metrics-chunk`).
- **Chunk requests return 400** – Backend expects **raw PCM** body; frontend might send JSON or empty body. **Check:** Request payload type and size.
- **Chunk requests return 200 but wheel static** – Backend is fine; frontend doesn’t update wheel state from the chunk response (wrong state setter, or component unmounted / wrong instance).

### Flow (409 / wrong step)

- **Step not from backend** – UI step comes from local state or URL, not from **GET session/status** → `session.status`. So the UI can show “step 1” while the session is already `final_task_ready` and the backend returns 409 for recording-1/upload-url.
- **No refetch after mutations** – After recording-1, metric-answers, or recording-2 succeed, the frontend doesn’t call **GET session/status** and re-derive the step, so the next step doesn’t appear until refresh.

### 403 on Send (Storage)

- **No Storage RLS policy** – Supabase bucket `audio_recordings` has no INSERT policy (or the policy doesn’t allow this user/path). The first path segment must equal `auth.uid()`. **Fix:** Add policies from `docs/SUPABASE-STORAGE-RLS-AUDIO-RECORDINGS.md`.

---

## 3. What to do (order)

1. **Storage 403 on Send**  
   Add the three Storage RLS policies for `audio_recordings` (insert, update, select) as in **`docs/SUPABASE-STORAGE-RLS-AUDIO-RECORDINGS.md`**. Confirm in the browser that `auth.uid()` matches the first folder in the path. Then retry Send.

2. **Flow: step from status**  
   - On load (and when entering homework), call **GET session/status**, derive step from `session.status` (warm_up→1, task_block→2, final_task_ready→3, post_questions→4, completed→5), and use that as the only source of truth for “current step”.  
   - After recording-1, metric-answers, and recording-2 succeed, call **GET session/status** again and apply the result to state (e.g. `applyStatusToState(statusRes)`) so the UI advances without refresh.  
   See **`docs/ROOT-CAUSE-SESSION-STATUS-MISMATCH.md`** and **`docs/PROMPT-FIX-SESSION-NOT-FOUND-RECORDING.md`**.

3. **Wheel: confirm chunk requests**  
   On the step where the wheel is shown, open **Network** tab and filter by **recording-metrics-chunk**.  
   - **No requests** → Start the PCM pipeline when that step mounts; don’t tear it down on re-render.  
   - **401** → Fix BFF auth (getV2AccessToken / cookies).  
   - **404** → Fix BFF: in Next 15 use `const { sessionId } = await params;` and ensure sessionId is defined before building the URL. Use the updated reference route in **`docs/homework-bff-routes/session/[sessionId]/recording-metrics-chunk/route.ts`** (params + header mapping).  
   - **400** → Frontend must send **raw PCM** in the body; BFF must forward it as arrayBuffer.  
   - **200** → Backend is OK; fix frontend: use the chunk response (e.g. `voiced_ratio`, `pause_score` or your wheel fields) to update the wheel component state.

4. **Wheel: header names**  
   If the frontend sends **X-Chunk-Seq** / **X-Chunk-Start-Ms**, the BFF must map them to **X-Seq** / **X-T-Ms** for the backend (or change the frontend to send X-Seq / X-T-Ms). The reference route in this repo already does that fallback.

---

## 4. Backend reference (this repo)

- **Chunk route (Flask):** `routes/homework.py` → `recording-metrics-chunk` (expects raw PCM, X-Sample-Rate, X-Seq, X-T-Ms).  
- **BFF reference (copy into frontend repo):** `docs/homework-bff-routes/session/[sessionId]/recording-metrics-chunk/route.ts` (Next 15 params + header mapping).  
- **Storage RLS SQL:** `docs/SUPABASE-STORAGE-RLS-AUDIO-RECORDINGS.md`.  
- **Status → step:** `docs/ROOT-CAUSE-SESSION-STATUS-MISMATCH.md`, `docs/PROMPT-FIX-SESSION-NOT-FOUND-RECORDING.md`.  
- **Trace-back wheel:** `docs/TRACEBACK-WHEEL-STOPPED-AFTER-BFF-CHANGE.md`.

No backend (Flask) changes are required for the wheel or flow; fixes are in **Supabase (Storage RLS)**, **BFF (chunk route: params + headers, auth)**, and **frontend (status as source of truth, refetch after mutations, chunk pipeline lifecycle, wheel state from chunk response)**.
