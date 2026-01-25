# Frontend TypeScript Error Fix

## Error
```
Type error: Type 'AdminFeedbackRequest' is not assignable to type '(BodyInit & AdminFeedbackRequest) | null | undefined'.
```

## Problem
The `proxyJson` function expects `body` to be compatible with `BodyInit`, but you're passing a plain object.

## Solution

### Fix 1: Stringify the Body (Recommended)

Update your Next.js API route:

```typescript
// src/app/api/admin/feedback/route.ts

import { NextRequest, NextResponse } from 'next/server';

interface AdminFeedbackRequest {
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

export async function POST(request: NextRequest) {
  try {
    const body: AdminFeedbackRequest = await request.json();
    console.log("[API /admin/feedback] Request body:", body);
    
    // ✅ Fix: Stringify the body before passing to proxyJson
    return proxyJson("/admin/feedback", {
      method: "POST",
      body: JSON.stringify(body),  // ✅ Convert to string
      headers: {
        "Content-Type": "application/json"
      }
    });
  } catch (error) {
    console.error("Error in admin/feedback route:", error);
    return NextResponse.json(
      { error: "Failed to process request" },
      { status: 500 }
    );
  }
}
```

### Fix 2: Update proxyJson Function Type

If `proxyJson` is your custom function, update its type signature:

```typescript
// utils/api.ts or wherever proxyJson is defined

async function proxyJson(
  endpoint: string,
  options: {
    method: string;
    body?: string | FormData | null;  // ✅ Accept string (JSON) or FormData
    headers?: Record<string, string>;
  }
) {
  const backendUrl = process.env.BACKEND_URL || 'https://flask-backend-production-ab37.up.railway.app';
  
  const response = await fetch(`${backendUrl}${endpoint}`, {
    method: options.method,
    body: options.body,
    headers: {
      'Content-Type': 'application/json',
      ...options.headers
    }
  });
  
  return response.json();
}
```

### Fix 3: Type Assertion (Quick Fix)

If you can't modify the function, use type assertion:

```typescript
export async function POST(request: NextRequest) {
  try {
    const body: AdminFeedbackRequest = await request.json();
    
    return proxyJson("/admin/feedback", {
      method: "POST",
      body: JSON.stringify(body) as any,  // ✅ Type assertion
      headers: {
        "Content-Type": "application/json"
      }
    });
  } catch (error) {
    console.error("Error:", error);
    return NextResponse.json({ error: "Failed" }, { status: 500 });
  }
}
```

## Backend Response Format (Verified ✅)

The backend returns:
```json
{
  "status": "success",
  "message": "Admin feedback saved successfully"
}
```

**Status Code:** 200

**Error Responses:**
- `400`: `{"code": "INVALID_INPUT", "error": "user_id required"}`
- `403`: `{"code": "FORBIDDEN", "error": "Admin access required"}`
- `500`: `{"code": "FEEDBACK_ERROR", "error": "..."}`

## Complete Fixed Example

```typescript
// src/app/api/admin/feedback/route.ts

import { NextRequest, NextResponse } from 'next/server';

interface AdminFeedbackRequest {
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

interface AdminFeedbackResponse {
  status: string;
  message: string;
}

export async function POST(request: NextRequest) {
  try {
    const body: AdminFeedbackRequest = await request.json();
    
    // Validate required fields
    if (!body.user_id) {
      return NextResponse.json(
        { code: "INVALID_INPUT", error: "user_id required" },
        { status: 400 }
      );
    }
    
    const backendUrl = process.env.BACKEND_URL || 'https://flask-backend-production-ab37.up.railway.app';
    const token = request.headers.get('authorization')?.replace('Bearer ', '');
    
    if (!token) {
      return NextResponse.json(
        { code: "UNAUTHORIZED", error: "Missing authorization token" },
        { status: 401 }
      );
    }
    
    // ✅ Fix: Stringify body and set proper headers
    const response = await fetch(`${backendUrl}/admin/feedback`, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${token}`,
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(body)  // ✅ Stringify the body
    });
    
    const data: AdminFeedbackResponse = await response.json();
    
    if (!response.ok) {
      return NextResponse.json(data, { status: response.status });
    }
    
    return NextResponse.json(data, { status: 200 });
    
  } catch (error) {
    console.error("Error in admin/feedback route:", error);
    return NextResponse.json(
      { code: "INTERNAL_ERROR", error: "Failed to process request" },
      { status: 500 }
    );
  }
}
```

## Key Points

1. **Body must be a string** when sending JSON to fetch API
2. **Set Content-Type header** to `application/json`
3. **Backend expects JSON** in request body
4. **Backend returns JSON** with `status` and `message` fields

## Testing

After fixing, test with:

```typescript
const response = await fetch('/api/admin/feedback', {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    user_id: "uuid",
    general_notes: "Test notes",
    custom_instructions: "Test instructions"
  })
});

const data = await response.json();
// Should return: { status: "success", message: "Admin feedback saved successfully" }
```

The backend is working correctly - this is purely a frontend TypeScript type issue! 🚀
