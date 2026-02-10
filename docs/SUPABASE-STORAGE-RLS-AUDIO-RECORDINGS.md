# Fix 403 on audio upload: Supabase Storage RLS for `audio_recordings`

The 403 **"new row violates row-level security policy"** when the browser uploads to Supabase Storage is from **Storage RLS** on `storage.objects` for bucket **`audio_recordings`**. The browser is trying to **INSERT** an object at:

`audio_recordings/<USER_ID>/<SESSION_ID>/<FILE>.webm`

and Supabase rejects it because there is **no INSERT policy** (or the policy doesn’t allow this user for that path).

---

## 1. Confirm the path matches the logged-in user

The first folder in the path **must** equal the authenticated user’s id. In the browser console (student account), run:

```js
const { data } = await supabase.auth.getUser();
data.user.id
```

That value **must equal** the first folder in your upload path (e.g. `5e33e0f1-0945-458c-8987-eadf43acf955`).

- **If it does not match:** RLS will correctly block the upload. Fix: the backend must generate `storage_path` using the **authenticated student’s** `auth.uid()` / JWT `sub`. The backend gets `user_id` from the JWT in `recording-upload-url`; that must be the same as the Supabase auth user id the frontend uses when calling `supabase.storage.upload()`.
- **If it matches:** Add the Storage policies below.

---

## 2. Add Storage RLS policies (SQL)

Run these in **Supabase** → **SQL Editor** (adjust bucket name if yours is different; default here is `audio_recordings`).

### Allow authenticated users to upload into their own folder

```sql
create policy "audio_recordings_insert_own_folder"
on storage.objects
for insert
to authenticated
with check (
  bucket_id = 'audio_recordings'
  and (storage.foldername(name))[1] = auth.uid()::text
);
```

### If you use `upsert: true`, also allow update (recommended)

`supabase.storage.upload(..., { upsert: true })` can require UPDATE permission.

```sql
create policy "audio_recordings_update_own_folder"
on storage.objects
for update
to authenticated
using (
  bucket_id = 'audio_recordings'
  and (storage.foldername(name))[1] = auth.uid()::text
)
with check (
  bucket_id = 'audio_recordings'
  and (storage.foldername(name))[1] = auth.uid()::text
);
```

### Optional: allow the user to read their own uploads (only if the client needs it)

```sql
create policy "audio_recordings_select_own_folder"
on storage.objects
for select
to authenticated
using (
  bucket_id = 'audio_recordings'
  and (storage.foldername(name))[1] = auth.uid()::text
);
```

---

## 3. Retry the upload

After adding the policies, retry **Send**. The Storage request should return **200** (or 2xx), and the app can then call **POST** recording-1 with `storage_path` and `duration_seconds`.

---

## If it still fails

**1) Upload request is unauthenticated (no bearer token)**  
In Network tab, open the failing Storage request and check **Request Headers**. It should include `Authorization: Bearer <jwt>`. If missing, the frontend Supabase client used for `storage.from(bucket).upload(...)` is not using the logged-in session (e.g. use the client that has `supabase.auth.getSession()` set).

**2) Bucket name mismatch**  
The failing URL uses bucket `audio_recordings`. Ensure the app is not sometimes using `recordings` or another bucket (e.g. mock or env returning a different bucket).

**3) Backend `user_id` vs Supabase `auth.uid()`**  
Backend builds `storage_path` as `{user_id}/{session_id}/{uuid}.webm` where `user_id` comes from the JWT passed to recording-upload-url. That JWT must be the **same** Supabase user as the one in the browser (so the first path segment equals `auth.uid()`). If the BFF forwards a different token or the backend uses a different claim, the path won’t match and RLS will block.

---

## Reference

- Backend path format: `routes/homework.py` → `_storage_path_for_session` returns `f"{user_id}/{session_id}/{uuid}.webm"`.
- Setup overview: `docs/HOMEWORK-DIRECT-UPLOAD-SETUP.md`.
