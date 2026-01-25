# Pre-Recording Questionnaire Implementation

## Overview

The backend now supports personalized pre-recording questions based on a user questionnaire that calculates a difficulty cursor and determines the session mode.

## API Endpoint

### `POST /session/start`

**Request Body (optional questionnaire):**
```json
{
  "questionnaire": {
    "mood": "positive" | "negative",
    "readiness": 1-10,
    "inspiration_needed": true | false
  }
}
```

**Response:**
```json
{
  "session_id": "uuid",
  "pre_questions": [
    {
      "id": "generated-0",
      "question_text": "Personalized question...",
      "order_index": 0
    }
  ],
  "cursor": 0.42,
  "mode": "guided" | "open"
}
```

## How It Works

1. **Questionnaire Input** (optional):
   - `mood`: "positive" (🙂) or "negative" (🙁)
   - `readiness`: Integer 1-10
   - `inspiration_needed`: Boolean (YES = true, NO = false)

2. **Cursor Calculation**:
   - Formula: `cursor = ((readiness - 1) / 9) * mood_multiplier`
   - `mood_multiplier`: 1.0 for positive, 0.7 for negative
   - Range: 0.0 (easiest) to 1.0 (hardest)

3. **Mode Determination**:
   - `inspiration_needed = true` → "guided" (more structure)
   - `inspiration_needed = false` → "open" (more freedom)

4. **Command Selection**:
   - 20 commands across 5 tiers (0.00-0.80 cursor range)
   - Commands selected based on cursor range and mode compatibility
   - 3 questions generated per session

5. **Question Generation**:
   - **Production**: Uses OpenAI GPT-4o-mini to generate personalized questions
   - **Development**: Uses template fallback system

## Command Tiers

- **Tier 1** (0.00-0.15): Safety & permission (easiest)
- **Tier 2** (0.15-0.30): Low activation
- **Tier 3** (0.30-0.45): Warm-up speaking
- **Tier 4** (0.45-0.60): Engagement & structure
- **Tier 5** (0.60-0.80): Challenge & edge (hardest)

## Database Schema

The `recording_sessions` table now includes:
- `mood` (TEXT)
- `readiness` (INTEGER)
- `inspiration_needed` (BOOLEAN)
- `cursor` (NUMERIC)
- `mode` (TEXT)

## Testing

### Test with questionnaire:
```bash
curl -X POST http://localhost:5000/session/start \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "questionnaire": {
      "mood": "negative",
      "readiness": 2,
      "inspiration_needed": true
    }
  }'
```

### Test without questionnaire (defaults):
```bash
curl -X POST http://localhost:5000/session/start \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

## Files Created/Modified

1. **`services/question_service.py`** (NEW):
   - Command definitions (20 commands)
   - Cursor calculation
   - Mode determination
   - Command selection
   - Question generation (AI + templates)

2. **`routes/session.py`** (MODIFIED):
   - Updated `/session/start` to accept questionnaire
   - Generates personalized questions

3. **`services/db.py`** (MODIFIED):
   - Updated `create_session()` to accept questionnaire data
   - Added `create_pre_question()` method

4. **`supabase-schema-complete.sql`** (MODIFIED):
   - Added questionnaire columns to `recording_sessions` table

## Notes

- If no questionnaire is provided, defaults to `cursor=0.5` and `mode="open"`
- Questions are generated dynamically (not stored in database)
- In dev mode, uses template fallback (no OpenAI calls)
- In production, uses OpenAI for personalized generation
