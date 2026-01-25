# Admin Feedback URL Implementation Guide

## Backend Status: ✅ Ready

The backend endpoint `POST /admin/feedback` is fully implemented and working.

## Quick Test (API)

You can test the feedback endpoint directly using curl:

```bash
curl -X POST https://flask-backend-production-ab37.up.railway.app/admin/feedback \
  -H "Authorization: Bearer YOUR_ADMIN_JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "5402278f-38f6-4538-8c1b-b65c6912f5da",
    "recording_id": "dfc436db-c73c-49de-a3c3-d308674ff611",
    "general_notes": "User speaks too fast when nervous. Needs to focus on pacing.",
    "custom_instructions": "When analyzing this user's recordings, emphasize:\n- Pacing and rhythm\n- Breathing techniques\n- Slowing down during key points",
    "max_words": 150
  }'
```

## Frontend Implementation

To make the URL `https://your-admin-dashboard.com/recordings/{recording_id}/feedback?user_id={user_id}` work, you need:

### 1. Create Admin Feedback Page

Create a page/component at the route: `/recordings/:recordingId/feedback`

**Example React/Next.js implementation:**

```typescript
// pages/recordings/[recordingId]/feedback.tsx or components/AdminFeedbackForm.tsx

import { useRouter } from 'next/router';
import { useState, useEffect } from 'react';

export default function AdminFeedbackPage() {
  const router = useRouter();
  const { recordingId } = router.query;
  const user_id = router.query.user_id as string;
  
  const [formData, setFormData] = useState({
    general_notes: '',
    custom_instructions: '',
    max_words: 120,
    specific_questions: []
  });
  
  const [loading, setLoading] = useState(false);
  const [success, setSuccess] = useState(false);
  
  // Optionally: Load existing feedback
  useEffect(() => {
    if (user_id) {
      fetch(`/api/admin/user/${user_id}/context`, {
        headers: {
          'Authorization': `Bearer ${getToken()}`
        }
      })
      .then(res => res.json())
      .then(data => {
        if (data.general_notes) setFormData(prev => ({ ...prev, general_notes: data.general_notes }));
        if (data.custom_instructions) setFormData(prev => ({ ...prev, custom_instructions: data.custom_instructions }));
        if (data.max_words) setFormData(prev => ({ ...prev, max_words: data.max_words }));
      });
    }
  }, [user_id]);
  
  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    
    try {
      const response = await fetch('/api/admin/feedback', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${getToken()}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          user_id: user_id,
          recording_id: recordingId,
          ...formData
        })
      });
      
      if (response.ok) {
        setSuccess(true);
        setTimeout(() => router.push('/admin'), 2000);
      } else {
        alert('Failed to save feedback');
      }
    } catch (error) {
      console.error('Error:', error);
      alert('Error saving feedback');
    } finally {
      setLoading(false);
    }
  };
  
  return (
    <div className="admin-feedback-page">
      <h1>Provide Feedback for Recording</h1>
      <p>Recording ID: {recordingId}</p>
      <p>User ID: {user_id}</p>
      
      {success && <div className="success">Feedback saved successfully!</div>}
      
      <form onSubmit={handleSubmit}>
        <div>
          <label>General Notes:</label>
          <textarea
            value={formData.general_notes}
            onChange={(e) => setFormData({ ...formData, general_notes: e.target.value })}
            placeholder="User speaks too fast when nervous..."
            rows={5}
          />
        </div>
        
        <div>
          <label>Custom Instructions for AI Analysis:</label>
          <textarea
            value={formData.custom_instructions}
            onChange={(e) => setFormData({ ...formData, custom_instructions: e.target.value })}
            placeholder="When analyzing this user's recordings, emphasize:&#10;- Pacing and rhythm&#10;- Breathing techniques"
            rows={8}
          />
        </div>
        
        <div>
          <label>Max Words for Report:</label>
          <input
            type="number"
            value={formData.max_words}
            onChange={(e) => setFormData({ ...formData, max_words: parseInt(e.target.value) })}
            min={50}
            max={500}
          />
        </div>
        
        <button type="submit" disabled={loading}>
          {loading ? 'Saving...' : 'Save Feedback'}
        </button>
      </form>
    </div>
  );
}

function getToken() {
  // Get your admin JWT token from wherever you store it
  return localStorage.getItem('admin_token') || '';
}
```

### 2. Update Email Link

The email already includes the feedback link. Make sure `ADMIN_DASHBOARD_URL` is set in your config:

**In Railway environment variables:**
- `ADMIN_DASHBOARD_URL` = `https://your-admin-dashboard.com`

**Or update `config.py`:**

```python
ADMIN_DASHBOARD_URL = os.getenv("ADMIN_DASHBOARD_URL", "https://your-admin-dashboard.com")
```

### 3. API Route (if using Next.js API routes)

If your frontend uses Next.js API routes, create:

```typescript
// pages/api/admin/feedback.ts

import type { NextApiRequest, NextApiResponse } from 'next';

export default async function handler(
  req: NextApiRequest,
  res: NextApiResponse
) {
  if (req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }
  
  const token = req.headers.authorization?.replace('Bearer ', '');
  if (!token) {
    return res.status(401).json({ error: 'Unauthorized' });
  }
  
  // Forward to your Flask backend
  const backendUrl = process.env.BACKEND_URL || 'https://flask-backend-production-ab37.up.railway.app';
  
  try {
    const response = await fetch(`${backendUrl}/admin/feedback`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(req.body)
    });
    
    const data = await response.json();
    return res.status(response.status).json(data);
  } catch (error) {
    return res.status(500).json({ error: 'Internal server error' });
  }
}
```

## Testing the Flow

1. **User uploads recording** → Email sent to admin
2. **Admin clicks link** → Opens feedback form
3. **Admin fills form** → Submits feedback
4. **Next recording** → Uses admin feedback in analysis

## Quick Test Without Frontend

You can test the entire flow using curl:

```bash
# 1. Get admin token (from your frontend or Supabase)
TOKEN="your-admin-token"

# 2. Submit feedback
curl -X POST https://flask-backend-production-ab37.up.railway.app/admin/feedback \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_id": "5402278f-38f6-4538-8c1b-b65c6912f5da",
    "recording_id": "dfc436db-c73c-49de-a3c3-d308674ff611",
    "general_notes": "User speaks too fast when nervous",
    "custom_instructions": "Focus on pacing and breathing",
    "max_words": 150
  }'

# 3. Verify it was saved
curl -X GET https://flask-backend-production-ab37.up.railway.app/admin/user/5402278f-38f6-4538-8c1b-b65c6912f5da/context \
  -H "Authorization: Bearer $TOKEN"
```

## Next Steps

1. **If you have a frontend:** Implement the feedback form page
2. **If you don't have a frontend yet:** Use the curl commands to test
3. **Set ADMIN_DASHBOARD_URL** in Railway environment variables

The backend is ready - you just need the frontend form! 🚀
