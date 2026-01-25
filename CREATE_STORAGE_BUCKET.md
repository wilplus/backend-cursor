# Create Supabase Storage Bucket

## Issue
The error `{"statusCode":"404","error":"Bucket not found","message":"Bucket not found"}` means the `audio_recordings` bucket doesn't exist in your Supabase Storage.

## Solution: Create the Bucket

### Option 1: Using Supabase Dashboard (Easiest)

1. Go to your Supabase project dashboard
2. Navigate to **Storage** (left sidebar)
3. Click **"New bucket"** or **"Create bucket"**
4. Fill in:
   - **Name:** `audio_recordings`
   - **Public bucket:** ✅ **YES** (check this box - makes files publicly accessible)
   - **File size limit:** 25 MB (or your preferred limit)
   - **Allowed MIME types:** `audio/*` (or leave empty for all types)
5. Click **"Create bucket"**

### Option 2: Using SQL (Alternative)

Run this in Supabase SQL Editor:

```sql
-- Note: This requires the storage extension to be enabled
-- Usually done via dashboard, but you can try:

-- Create the bucket via storage API (if available)
-- Most reliable way is through the dashboard
```

**Note:** The SQL method is less reliable. Use the Dashboard method above.

## Verify Bucket is Public

After creating the bucket:

1. Go to **Storage** → **audio_recordings**
2. Check that it shows **"Public"** badge
3. If it's private, click the bucket → Settings → Toggle **"Public bucket"** to ON

## Test

After creating the bucket:

1. Upload a new recording via your app
2. The audio should now be accessible
3. The URL should work: `https://your-project.supabase.co/storage/v1/object/public/audio_recordings/...`

## If Using Private Bucket

If you want to keep the bucket private (more secure):

1. Don't check "Public bucket" when creating
2. The backend will use signed URLs (which we already implemented)
3. Signed URLs expire after 1 hour (configurable)

The current code already supports both public and private buckets, but **public is simpler** for now.

---

**Quick Fix:** Create the bucket via Dashboard → Storage → New bucket → Name: `audio_recordings` → Public: ✅ → Create
