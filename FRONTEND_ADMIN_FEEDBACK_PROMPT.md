# Frontend Implementation: Admin Feedback System

## Backend Status: ✅ COMPLETE

The backend is fully implemented with:
- ✅ `POST /admin/feedback` - Save admin feedback
- ✅ `GET /admin/user/:userId/context` - Get admin notes for a user
- ✅ `GET /admin/recordings` - List recordings for admin review
- ✅ Analysis function updated to use admin notes
- ✅ Email includes feedback link

## Frontend Implementation Guide

### 1. Admin Feedback Form

Create a form component to submit admin feedback:

```typescript
// AdminFeedbackForm.tsx
interface AdminFeedbackFormData {
  user_id: string;
  recording_id?: string;
  general_notes: string;
  custom_instructions: string;
  max_words?: number;
  specific_questions?: Array<{
    question_text: string;
    question_type: 'pre' | 'post';
  }>;
}

const submitAdminFeedback = async (data: AdminFeedbackFormData) => {
  const response = await fetch('/api/admin/feedback', {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(data)
  });
  
  if (!response.ok) {
    throw new Error('Failed to save feedback');
  }
  
  return response.json();
};
```

### 2. Get User Admin Context

Fetch admin notes for a user:

```typescript
const getUserAdminContext = async (userId: string) => {
  const response = await fetch(`/api/admin/user/${userId}/context`, {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  });
  
  return response.json();
};

// Response:
// {
//   user_id: string;
//   general_notes: string | null;
//   custom_instructions: string | null;
//   max_words: number;
//   specific_questions: Array<{...}>;
// }
```

### 3. List Recordings for Admin

Get recordings that need feedback:

```typescript
const getAdminRecordings = async (needsFeedback: boolean = false) => {
  const params = new URLSearchParams({
    limit: '20',
    offset: '0',
    needs_feedback: needsFeedback.toString()
  });
  
  const response = await fetch(`/api/admin/recordings?${params}`, {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  });
  
  return response.json();
};
```

### 4. Admin Authentication

The backend checks if the user is an admin by:
- Getting email from JWT token payload
- Checking if email exists in `admin_users` table with `is_active = true`

**To make a user an admin:**
1. Add their email to `admin_users` table in Supabase
2. Set `role` to 'super_admin', 'coach', or 'reviewer'
3. Set `is_active = true`

### 5. Email Feedback Link

The email sent to admin includes a link like:
```
https://your-admin-dashboard.com/recordings/{recording_id}/feedback?user_id={user_id}
```

**Frontend should:**
- Extract `recording_id` and `user_id` from URL params
- Pre-fill the feedback form with user context
- Allow admin to submit feedback

## Complete Flow

1. **User uploads recording** → Backend analyzes (with admin notes if available)
2. **Email sent to admin** → Includes feedback link
3. **Admin clicks link** → Opens feedback form
4. **Admin submits feedback** → Stored in database
5. **Next recording** → Uses admin feedback in analysis

## API Endpoints

### POST /admin/feedback
**Auth:** Admin only
**Body:**
```json
{
  "user_id": "uuid",
  "recording_id": "uuid",  // Optional
  "general_notes": "User tends to rush when nervous...",
  "custom_instructions": "Focus on pacing and breathing...",
  "max_words": 120,  // Optional
  "specific_questions": [  // Optional
    {
      "question_text": "How did you feel about pacing?",
      "question_type": "post"
    }
  ]
}
```

### GET /admin/user/:userId/context
**Auth:** Admin only
**Response:**
```json
{
  "user_id": "uuid",
  "general_notes": "User tends to rush...",
  "custom_instructions": "Focus on pacing...",
  "max_words": 120,
  "specific_questions": [...]
}
```

### GET /admin/recordings
**Auth:** Admin only
**Query params:**
- `limit` (default: 20)
- `offset` (default: 0)
- `needs_feedback` (boolean, default: false)

**Response:**
```json
{
  "recordings": [...],
  "limit": 20,
  "offset": 0,
  "count": 10
}
```

## Frontend Checklist

- [ ] Create admin feedback form component
- [ ] Add admin authentication check
- [ ] Create recordings list page for admins
- [ ] Handle feedback link from email (extract params)
- [ ] Display existing admin notes when viewing user
- [ ] Show which recordings need feedback
- [ ] Allow updating existing feedback

## Testing

1. **Make yourself an admin:**
   ```sql
   INSERT INTO admin_users (email, role, is_active)
   VALUES ('your-email@example.com', 'super_admin', true);
   ```

2. **Test feedback endpoint:**
   ```bash
   curl -X POST http://localhost:5000/admin/feedback \
     -H "Authorization: Bearer YOUR_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "user_id": "user-uuid",
       "general_notes": "Test notes",
       "custom_instructions": "Test instructions"
     }'
   ```

3. **Test getting context:**
   ```bash
   curl -H "Authorization: Bearer YOUR_TOKEN" \
     http://localhost:5000/admin/user/USER_ID/context
   ```

The backend is ready! Implement the frontend admin dashboard to complete the flow.
