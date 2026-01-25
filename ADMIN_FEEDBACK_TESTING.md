# Admin Feedback System - Testing Guide

## Prerequisites

1. **Backend running** (Railway or local)
2. **Supabase database** with admin tables set up
3. **A user account** to provide feedback for
4. **Your email** that you use to log in

---

## Step 1: Make Yourself an Admin

### Option A: Using Supabase SQL Editor

1. Go to your Supabase project → SQL Editor
2. Run this SQL (replace with your email):

```sql
-- Create admin_users table if it doesn't exist
CREATE TABLE IF NOT EXISTS admin_users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  role TEXT DEFAULT 'super_admin',
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMP DEFAULT now()
);

-- Insert yourself as admin (replace with your actual email)
INSERT INTO admin_users (email, role, is_active)
VALUES ('your-email@example.com', 'super_admin', true)
ON CONFLICT (email) DO UPDATE SET is_active = true;
```

### Option B: Check if admin_users table exists

If the table doesn't exist, create it first:

```sql
CREATE TABLE admin_users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email TEXT UNIQUE NOT NULL,
  role TEXT DEFAULT 'super_admin',
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMP DEFAULT now()
);
```

---

## Step 2: Get Your JWT Token

### Option A: From Frontend (Easiest)

1. Log in to your frontend app
2. Open browser console (F12)
3. Run:
   ```javascript
   // Get token from localStorage or wherever you store it
   localStorage.getItem('supabase.auth.token') 
   // OR
   const session = await supabase.auth.getSession()
   console.log(session.data.session.access_token)
   ```

### Option B: Using get_token.py Script

If you have the `get_token.py` script:

```bash
python get_token.py your-email@example.com your-password
```

---

## Step 3: Get a User ID to Test With

You need a `user_id` (UUID) to provide feedback for. Get it from:

1. **Supabase Dashboard** → Table Editor → `auth.users` → Find a user's `id`
2. **Or from your frontend** - Check the user profile endpoint response
3. **Or from a recording** - Check any recording's `user_id` field

---

## Step 4: Test Admin Feedback Endpoints

### Test 1: Save Admin Feedback

```bash
curl -X POST https://your-backend-url.railway.app/admin/feedback \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "USER_UUID_HERE",
    "general_notes": "User speaks too fast when nervous. Needs to focus on pacing.",
    "custom_instructions": "When analyzing this user's recordings, emphasize:\n- Pacing and rhythm\n- Breathing techniques\n- Slowing down during key points",
    "max_words": 150
  }'
```

**Expected Response:**
```json
{
  "status": "success",
  "message": "Admin feedback saved successfully"
}
```

### Test 2: Get User Admin Context

```bash
curl -X GET https://your-backend-url.railway.app/admin/user/USER_UUID_HERE/context \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

**Expected Response:**
```json
{
  "user_id": "uuid",
  "general_notes": "User speaks too fast when nervous...",
  "custom_instructions": "When analyzing this user's recordings...",
  "max_words": 150,
  "specific_questions": []
}
```

### Test 3: List Recordings (Admin View)

```bash
curl -X GET "https://your-backend-url.railway.app/admin/recordings?limit=10&offset=0&needs_feedback=false" \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

**Expected Response:**
```json
{
  "recordings": [...],
  "limit": 10,
  "offset": 0,
  "count": 5
}
```

---

## Step 5: Verify Admin Notes Are Used in Analysis

### Test Flow:

1. **Provide admin feedback** (Step 4, Test 1)

2. **User uploads a new recording** (via frontend)

3. **User submits post-answers** (via frontend)

4. **Check the coaching report** - It should include:
   - Admin observations
   - Custom instructions applied
   - Personalized analysis

### Verify in Database:

```sql
-- Check admin notes were saved
SELECT * FROM professional_notes WHERE user_id = 'USER_UUID';
SELECT * FROM professional_notes_report_tech WHERE user_id = 'USER_UUID';

-- Check the coaching report includes admin context
SELECT 
  transcription_text,
  coaching_report,
  created_at
FROM recordings 
WHERE user_id = 'USER_UUID' 
ORDER BY created_at DESC 
LIMIT 1;
```

The `coaching_report` should reference the admin's observations and follow the custom instructions.

---

## Step 6: Test Error Cases

### Test 1: Non-Admin Access (Should Fail)

```bash
# Use a token from a non-admin user
curl -X POST https://your-backend-url.railway.app/admin/feedback \
  -H "Authorization: Bearer NON_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_id": "uuid", "general_notes": "test"}'
```

**Expected Response:**
```json
{
  "code": "FORBIDDEN",
  "error": "Admin access required"
}
```
**Status:** 403

### Test 2: Missing user_id (Should Fail)

```bash
curl -X POST https://your-backend-url.railway.app/admin/feedback \
  -H "Authorization: Bearer YOUR_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"general_notes": "test"}'
```

**Expected Response:**
```json
{
  "code": "INVALID_INPUT",
  "error": "user_id required"
}
```
**Status:** 400

---

## Step 7: Test Complete Flow

### End-to-End Test:

1. **Create admin user** (Step 1)
2. **Get admin token** (Step 2)
3. **Get a test user_id** (Step 3)
4. **Provide feedback for user** (Step 4, Test 1)
5. **Verify feedback saved** (Step 4, Test 2)
6. **User uploads recording** (via frontend)
7. **User submits post-answers** (via frontend)
8. **Check coaching report** - Should include admin context

### Expected Result:

The coaching report should:
- ✅ Reference admin observations (e.g., "User speaks too fast when nervous")
- ✅ Follow custom instructions (e.g., focus on pacing and breathing)
- ✅ Be personalized to the user
- ✅ Use the max_words limit if set

---

## Troubleshooting

### Issue: "Admin access required" (403)

**Solution:**
- Verify your email is in `admin_users` table
- Check `is_active = true`
- Verify you're using the correct JWT token (from the admin account)

### Issue: Admin notes not appearing in analysis

**Solution:**
- Verify admin notes were saved: `SELECT * FROM professional_notes WHERE user_id = '...'`
- Check that the recording was created AFTER admin notes were added
- Verify post-answers were submitted (coaching report is generated when post-answers are submitted)
- Check Railway logs for errors during report generation

### Issue: Can't find admin_users table

**Solution:**
- Create the table using SQL from Step 1
- Or check if it exists with a different name
- Verify you have the correct Supabase project

---

## Quick Test Script

Save this as `test_admin_feedback.sh`:

```bash
#!/bin/bash

# Configuration
BACKEND_URL="https://your-backend-url.railway.app"
TOKEN="YOUR_JWT_TOKEN"
USER_ID="USER_UUID_HERE"

echo "🧪 Testing Admin Feedback System"
echo "================================"

# Test 1: Save feedback
echo -e "\n1️⃣  Saving admin feedback..."
RESPONSE=$(curl -s -X POST "$BACKEND_URL/admin/feedback" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{
    \"user_id\": \"$USER_ID\",
    \"general_notes\": \"Test: User speaks too fast\",
    \"custom_instructions\": \"Focus on pacing\",
    \"max_words\": 120
  }")

echo "Response: $RESPONSE"

# Test 2: Get context
echo -e "\n2️⃣  Getting user admin context..."
CONTEXT=$(curl -s -X GET "$BACKEND_URL/admin/user/$USER_ID/context" \
  -H "Authorization: Bearer $TOKEN")

echo "Context: $CONTEXT"

# Test 3: List recordings
echo -e "\n3️⃣  Listing recordings..."
RECORDINGS=$(curl -s -X GET "$BACKEND_URL/admin/recordings?limit=5" \
  -H "Authorization: Bearer $TOKEN")

echo "Recordings: $RECORDINGS"

echo -e "\n✅ Tests complete!"
```

Make it executable and run:
```bash
chmod +x test_admin_feedback.sh
./test_admin_feedback.sh
```

---

## Next Steps

After testing:
1. ✅ Verify admin feedback saves correctly
2. ✅ Verify admin notes appear in coaching reports
3. ✅ Test with frontend admin dashboard (if implemented)
4. ✅ Monitor Railway logs for any errors

The admin feedback system is ready to use! 🎉
