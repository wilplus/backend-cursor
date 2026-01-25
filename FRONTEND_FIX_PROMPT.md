# Frontend Fix: Post-Questions Question IDs

## Problem

The backend now returns post-questions with **real UUID question IDs** from the database (not temporary IDs like "set-2-q1").

## What Changed in Backend

1. **Questions are now created in database** when recording is uploaded
2. **Real UUIDs are returned** instead of temporary IDs
3. **Question structure is the same**, just with real IDs

## Frontend Response Format (No Change Needed)

The response format is the same, just with real UUIDs:

```json
{
  "recording_id": "uuid",
  "status": "recording_uploaded",
  "post_questions": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",  // Real UUID now
      "question_text": "How present were you while speaking? (1-5)",
      "question_type": "scale",
      "question_set_id": 1,
      "order_index": 0
    },
    {
      "id": "550e8400-e29b-41d4-a716-446655440001",  // Real UUID
      "question_text": "Did you notice yourself using filler words?",
      "question_type": "binary",
      "question_set_id": 1,
      "order_index": 1
    },
    {
      "id": "550e8400-e29b-41d4-a716-446655440002",  // Real UUID
      "question_text": "What moment felt the most real?",
      "question_type": "free_text",
      "question_set_id": 1,
      "order_index": 2
    }
  ]
}
```

## Frontend: No Changes Required!

The frontend should already work because:
- ✅ The response structure is the same
- ✅ `id` field is still present (just real UUIDs now)
- ✅ `question_type` is still present
- ✅ `question_set_id` is still present
- ✅ `order_index` is still present

## What to Verify

1. **Check that questions are displayed** - Should work as before
2. **Check that answers are submitted correctly** - The `question_id` in answers should be the UUID from `post_questions[].id`
3. **No errors when submitting** - Should work since IDs are now valid UUIDs

## If Frontend Has Issues

If the frontend was storing or manipulating the temporary IDs in any way, you may need to:

1. **Clear any cached question IDs** - If you were storing "set-X-qY" format
2. **Verify answer submission** - Make sure `answer.question_id` uses the UUID from the response
3. **Check for any ID validation** - Remove any checks for "set-" prefix

## Testing

After backend restart:
1. Upload a recording
2. Check the response - `post_questions[].id` should be real UUIDs
3. Submit answers - Should work without UUID errors

The frontend should work without changes since the structure is the same!
