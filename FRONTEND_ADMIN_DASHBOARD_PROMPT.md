# Frontend: Admin Dashboard Implementation Prompt

## Overview

Build an admin dashboard that allows admins to:
1. View recordings that need feedback
2. Provide feedback for users to improve AI analysis quality
3. View user context and feedback history

---

## Backend API Endpoints (Ready ✅)

All endpoints require admin authentication (JWT token with admin email in `admin_users` table).

### 1. Save Admin Feedback
**POST** `/admin/feedback`

**Request:**
```json
{
  "user_id": "uuid",
  "recording_id": "uuid",  // Optional
  "general_notes": "User speaks too fast when nervous...",
  "custom_instructions": "When analyzing this user's recordings, emphasize:\n- Pacing and rhythm\n- Breathing techniques",
  "max_words": 150,  // Optional, default 120
  "specific_questions": [  // Optional
    {
      "question_text": "How did you feel about pacing?",
      "question_type": "post"
    }
  ]
}
```

**Response:**
```json
{
  "status": "success",
  "message": "Admin feedback saved successfully"
}
```

### 2. Get User Admin Context
**GET** `/admin/user/:userId/context`

**Response:**
```json
{
  "user_id": "uuid",
  "general_notes": "User speaks too fast...",
  "custom_instructions": "Focus on pacing...",
  "max_words": 150,
  "specific_questions": [
    {
      "id": "uuid",
      "question_text": "...",
      "question_type": "post"
    }
  ]
}
```

### 3. List Recordings
**GET** `/admin/recordings?limit=20&offset=0&needs_feedback=false`

**Query Params:**
- `limit` (default: 20)
- `offset` (default: 0)
- `needs_feedback` (boolean, default: false) - Filter recordings that need feedback

**Response:**
```json
{
  "recordings": [
    {
      "id": "uuid",
      "user_id": "uuid",
      "session_id": "uuid",
      "transcription_text": "...",
      "coaching_report": "...",
      "created_at": "2026-01-25T...",
      "words_per_minute": 145,
      "filler_words_count": {...},
      "audio_url": "https://..."
    }
  ],
  "limit": 20,
  "offset": 0,
  "count": 15
}
```

---

## Required Pages/Components

### 1. Admin Login/Auth Check
- Verify user is admin (check JWT token)
- Redirect to login if not admin
- Store admin token in localStorage/sessionStorage

### 2. Recordings List Page
**Route:** `/admin/recordings` or `/admin`

**Features:**
- List all recordings (paginated)
- Filter by "needs feedback" (recordings without admin notes)
- Show recording details:
  - User ID
  - Recording ID
  - Transcription preview
  - Coaching report preview
  - Created date
  - Metrics (WPM, filler count)
- Click recording → Navigate to feedback page
- Search/filter functionality

**UI Example:**
```
┌─────────────────────────────────────────────────┐
│ Admin Dashboard                                 │
├─────────────────────────────────────────────────┤
│ [Filter: All] [Needs Feedback] [Search...]     │
├─────────────────────────────────────────────────┤
│ Recording 1                                     │
│ User: 5402278f-38f6-4538-8c1b-b65c6912f5da     │
│ Transcription: "This is a test recording..."   │
│ WPM: 145 | Fillers: 12                         │
│ [View Details] [Provide Feedback]              │
├─────────────────────────────────────────────────┤
│ Recording 2                                     │
│ ...                                             │
└─────────────────────────────────────────────────┘
```

### 3. Feedback Form Page
**Route:** `/recordings/:recordingId/feedback?user_id=:userId`

**Features:**
- Extract `recordingId` and `user_id` from URL
- Load existing feedback (if any) using `GET /admin/user/:userId/context`
- Form fields:
  - **General Notes** (textarea, required)
    - Placeholder: "User speaks too fast when nervous..."
  - **Custom Instructions** (textarea, required)
    - Placeholder: "When analyzing this user's recordings, emphasize:\n- Pacing and rhythm\n- Breathing techniques"
  - **Max Words** (number input, optional, default: 120)
    - Min: 50, Max: 500
- Show recording context:
  - Transcription preview
  - Current coaching report
  - User's previous recordings (if available)
- Submit button → Calls `POST /admin/feedback`
- Success message → Redirect to recordings list

**UI Example:**
```
┌─────────────────────────────────────────────────┐
│ Provide Feedback                                 │
├─────────────────────────────────────────────────┤
│ Recording: dfc436db-c73c-49de-a3c3-d308674ff611 │
│ User: 5402278f-38f6-4538-8c1b-b65c6912f5da      │
├─────────────────────────────────────────────────┤
│ Recording Context:                               │
│ Transcription: "This is a test..."              │
│ Current Report: "Your speech shows..."          │
├─────────────────────────────────────────────────┤
│ General Notes: *                                 │
│ ┌─────────────────────────────────────────────┐ │
│ │ User speaks too fast when nervous...        │ │
│ │                                              │ │
│ └─────────────────────────────────────────────┘ │
│                                                  │
│ Custom Instructions: *                           │
│ ┌─────────────────────────────────────────────┐ │
│ │ When analyzing this user's recordings:       │ │
│ │ - Focus on pacing                            │ │
│ │ - Emphasize breathing                        │ │
│ └─────────────────────────────────────────────┘ │
│                                                  │
│ Max Words: [120] (50-500)                        │
│                                                  │
│ [Cancel] [Save Feedback]                         │
└─────────────────────────────────────────────────┘
```

### 4. User Context View (Optional)
**Route:** `/admin/user/:userId`

**Features:**
- Show all admin feedback for a user
- Show user's recordings
- Edit existing feedback

---

## Implementation Details

### Authentication

```typescript
// Check if user is admin
async function checkAdminStatus(token: string): Promise<boolean> {
  try {
    // Try to access an admin endpoint
    const response = await fetch('/api/admin/recordings?limit=1', {
      headers: {
        'Authorization': `Bearer ${token}`
      }
    });
    return response.status !== 403;
  } catch {
    return false;
  }
}

// Get admin token (from your auth system)
function getAdminToken(): string | null {
  return localStorage.getItem('admin_token') || 
         sessionStorage.getItem('admin_token') ||
         getTokenFromSupabaseSession();
}
```

### API Client

```typescript
// api/admin.ts

const BACKEND_URL = process.env.NEXT_PUBLIC_BACKEND_URL || 'https://flask-backend-production-ab37.up.railway.app';

export async function saveAdminFeedback(data: {
  user_id: string;
  recording_id?: string;
  general_notes: string;
  custom_instructions: string;
  max_words?: number;
  specific_questions?: Array<{
    question_text: string;
    question_type: 'pre' | 'post';
  }>;
}): Promise<{ status: string; message: string }> {
  const token = getAdminToken();
  if (!token) throw new Error('Not authenticated');
  
  const response = await fetch(`${BACKEND_URL}/admin/feedback`, {
    method: 'POST',
    headers: {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(data)
  });
  
  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.error || 'Failed to save feedback');
  }
  
  return response.json();
}

export async function getUserAdminContext(userId: string) {
  const token = getAdminToken();
  if (!token) throw new Error('Not authenticated');
  
  const response = await fetch(`${BACKEND_URL}/admin/user/${userId}/context`, {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  });
  
  if (!response.ok) {
    throw new Error('Failed to fetch user context');
  }
  
  return response.json();
}

export async function getAdminRecordings(params: {
  limit?: number;
  offset?: number;
  needs_feedback?: boolean;
}) {
  const token = getAdminToken();
  if (!token) throw new Error('Not authenticated');
  
  const queryParams = new URLSearchParams();
  if (params.limit) queryParams.set('limit', params.limit.toString());
  if (params.offset) queryParams.set('offset', params.offset.toString());
  if (params.needs_feedback !== undefined) {
    queryParams.set('needs_feedback', params.needs_feedback.toString());
  }
  
  const response = await fetch(`${BACKEND_URL}/admin/recordings?${queryParams}`, {
    headers: {
      'Authorization': `Bearer ${token}`
    }
  });
  
  if (!response.ok) {
    throw new Error('Failed to fetch recordings');
  }
  
  return response.json();
}
```

### React Component Example

```typescript
// components/AdminFeedbackForm.tsx

'use client';

import { useState, useEffect } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { saveAdminFeedback, getUserAdminContext } from '@/api/admin';

export default function AdminFeedbackForm({ recordingId }: { recordingId: string }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const userId = searchParams.get('user_id');
  
  const [formData, setFormData] = useState({
    general_notes: '',
    custom_instructions: '',
    max_words: 120
  });
  
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  const [existingFeedback, setExistingFeedback] = useState<any>(null);
  
  // Load existing feedback
  useEffect(() => {
    if (userId) {
      getUserAdminContext(userId)
        .then(data => {
          setExistingFeedback(data);
          if (data.general_notes) {
            setFormData(prev => ({ ...prev, general_notes: data.general_notes }));
          }
          if (data.custom_instructions) {
            setFormData(prev => ({ ...prev, custom_instructions: data.custom_instructions }));
          }
          if (data.max_words) {
            setFormData(prev => ({ ...prev, max_words: data.max_words }));
          }
        })
        .catch(err => console.error('Failed to load existing feedback:', err));
    }
  }, [userId]);
  
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!userId) return;
    
    setLoading(true);
    try {
      await saveAdminFeedback({
        user_id: userId,
        recording_id: recordingId,
        ...formData
      });
      setSuccess(true);
      setTimeout(() => {
        router.push('/admin/recordings');
      }, 2000);
    } catch (error: any) {
      alert(`Error: ${error.message}`);
    } finally {
      setLoading(false);
    }
  };
  
  return (
    <div className="max-w-4xl mx-auto p-6">
      <h1 className="text-2xl font-bold mb-4">Provide Feedback</h1>
      
      <div className="bg-gray-100 p-4 mb-6 rounded">
        <p><strong>Recording ID:</strong> {recordingId}</p>
        <p><strong>User ID:</strong> {userId}</p>
      </div>
      
      {success && (
        <div className="bg-green-100 border border-green-400 text-green-700 px-4 py-3 rounded mb-4">
          Feedback saved successfully! Redirecting...
        </div>
      )}
      
      <form onSubmit={handleSubmit} className="space-y-6">
        <div>
          <label className="block text-sm font-medium mb-2">
            General Notes *
          </label>
          <textarea
            value={formData.general_notes}
            onChange={(e) => setFormData({ ...formData, general_notes: e.target.value })}
            placeholder="User speaks too fast when nervous. Needs to focus on pacing."
            rows={5}
            className="w-full border rounded p-2"
            required
          />
        </div>
        
        <div>
          <label className="block text-sm font-medium mb-2">
            Custom Instructions for AI Analysis *
          </label>
          <textarea
            value={formData.custom_instructions}
            onChange={(e) => setFormData({ ...formData, custom_instructions: e.target.value })}
            placeholder="When analyzing this user's recordings, emphasize:&#10;- Pacing and rhythm&#10;- Breathing techniques&#10;- Slowing down during key points"
            rows={8}
            className="w-full border rounded p-2"
            required
          />
          <p className="text-sm text-gray-500 mt-1">
            These instructions will be included in the AI prompt for future analysis.
          </p>
        </div>
        
        <div>
          <label className="block text-sm font-medium mb-2">
            Max Words for Report
          </label>
          <input
            type="number"
            value={formData.max_words}
            onChange={(e) => setFormData({ ...formData, max_words: parseInt(e.target.value) })}
            min={50}
            max={500}
            className="border rounded p-2"
          />
          <p className="text-sm text-gray-500 mt-1">
            Maximum words for the coaching report (default: 120)
          </p>
        </div>
        
        <div className="flex gap-4">
          <button
            type="button"
            onClick={() => router.back()}
            className="px-4 py-2 border rounded"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={loading}
            className="px-4 py-2 bg-blue-600 text-white rounded disabled:opacity-50"
          >
            {loading ? 'Saving...' : 'Save Feedback'}
          </button>
        </div>
      </form>
    </div>
  );
}
```

---

## Routing Setup

### Next.js App Router

```typescript
// app/recordings/[recordingId]/feedback/page.tsx

import AdminFeedbackForm from '@/components/AdminFeedbackForm';

export default function FeedbackPage({ params }: { params: { recordingId: string } }) {
  return <AdminFeedbackForm recordingId={params.recordingId} />;
}
```

### Next.js Pages Router

```typescript
// pages/recordings/[recordingId]/feedback.tsx

import { useRouter } from 'next/router';
import AdminFeedbackForm from '@/components/AdminFeedbackForm';

export default function FeedbackPage() {
  const router = useRouter();
  const { recordingId } = router.query;
  
  if (!recordingId) return <div>Loading...</div>;
  
  return <AdminFeedbackForm recordingId={recordingId as string} />;
}
```

---

## Testing Checklist

- [ ] Admin can log in and access dashboard
- [ ] Recordings list loads and displays correctly
- [ ] "Needs feedback" filter works
- [ ] Clicking recording navigates to feedback form
- [ ] Feedback form loads existing feedback (if any)
- [ ] Submitting feedback saves successfully
- [ ] Success message shows and redirects
- [ ] Error handling works (403, 500, network errors)
- [ ] Mobile responsive design

---

## Environment Variables

Add to your frontend `.env`:

```
NEXT_PUBLIC_BACKEND_URL=https://flask-backend-production-ab37.up.railway.app
```

---

## Design Recommendations

1. **Clean, professional UI** - Use a modern design system (Tailwind, Material-UI, etc.)
2. **Clear navigation** - Breadcrumbs, back buttons
3. **Loading states** - Show spinners during API calls
4. **Error messages** - User-friendly error handling
5. **Success feedback** - Confirmation messages
6. **Responsive** - Works on mobile and desktop

---

## Backend Status

✅ All endpoints are implemented and tested
✅ Admin authentication works
✅ Email includes feedback link
✅ Admin notes are used in AI analysis

**You just need to build the frontend UI!** 🚀
