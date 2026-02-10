# Final task: generation, context, and display

## Is AI called to write it?

**Yes.** The backend calls OpenAI to generate the final task text.

- **Where:** `services/openai_service.py` → `generate_final_task()`
- **When:** On **POST /v2/homework/session/<session_id>/metric-answers** (after the user submits the three metric answers).
- **Model:** `gpt-4o-mini`, temperature 0.3, max_tokens 120.

---

## What the task consists of (middle steps)

1. **Recording 1 (warm-up)**  
   User records; backend transcribes, scores, and:
   - Calls **`generate_context_short(transcript)`** → 2–3 sentence summary of the warm-up (AI).
   - Selects a focus task (per-student, global, or default "Pay attention to your breathing").
   - Stores **context_short**, **selected_task_id** on the session; returns **task_block** (metric_question_1/2/3 only).

2. **Metrics step**  
   User answers the three metric questions (e.g. self-ratings for pacing, strength, clarity). No AI call here.

3. **Submit metric answers**  
   Backend:
   - Reads **context_short** and **selected_task_id** from the session.
   - Resolves focus task → **focus_task_title**, **focus_task_prompt** (or default).
   - Calls **`generate_final_task(context_short, focus_task_title, focus_task_prompt, metric_answer_1, metric_answer_2, metric_answer_3)`**.
   - Saves **final_task_text** on the session and returns **`final_task`** in the response.

4. **Step 3 (final recording)**  
   Frontend shows the **final_task** text so the user knows what to do for the second recording.

---

## What context is extracted and passed to the AI

| Input to `generate_final_task` | Source |
|--------------------------------|--------|
| **context_short** | AI summary of recording 1 (from `generate_context_short(transcript)`), stored on session after recording-1. |
| **focus_task_title** | From the selected focus task (or default "Pay attention to your breathing"). |
| **focus_task_prompt** | Same focus task’s prompt text (or default). |
| **metric_answer_1, 2, 3** | User’s answers to the three metric questions from the metrics step. |

All of this is **backend**-derived; the frontend only sends the three metric answers. If **context_short** is empty (e.g. transcript empty or `generate_context_short` failed), the AI still runs but with empty context, which can lead to generic output.

---

## Is there a hardcoded formula?

**Partly.**

1. **Prompt template (hardcoded)**  
   The backend uses a fixed prompt structure in `openai_service.generate_final_task()`:
   - Sentence 1: "Based on [context from recording 1], your task is: [focus_task]."
   - Sentence 2: "Focus especially on [metric_answer_1], [metric_answer_2], and [metric_answer_3]."
   - The prompt *asks* for exactly 2 sentences, 20–50 words, no extra commentary. The model is **not** post-processed or validated for that; output is returned as-is (or fallback on error).

2. **Fallback (hardcoded)**  
   If the OpenAI client is missing or the API call fails, the backend returns a deterministic fallback:
   - `"Based on {context_short[:100]}, your task is: {focus_task}. Focus especially on {focus_phrase}."`
   - No "60 seconds" or "short summary" appears in backend code.

3. **No "60 seconds" or "short summary" in backend**  
   The phrase *"For your final recording, deliver a short summary in under 60 seconds"* does **not** appear in this repo. So it is either:
   - **AI output** when context is sparse (empty/short context_short, default focus task, generic metric answers), or
   - **Frontend placeholder/fallback** when `final_task` is missing, empty, or not yet loaded.

4. **"Exactly 2 sentences" is a target, not enforced**  
   The backend *asks* the model for exactly 2 sentences (prompt + system message) but does **not** post-process or validate the response. There is no split/trim or retry loop. So when debugging, treat "2 sentences" as the **target format**; the model may occasionally return more/fewer or different structure unless you add enforcement.

---

## Verify the generic "60 seconds summary" source (<2 min)

There are only three real sources. Rule of thumb:

| If… | Then… |
|-----|--------|
| Response **`final_task`** is generic | Backend/LLM/prompt/context problem. |
| Response **`final_task`** is good but UI shows generic | Frontend display/fallback problem. |

### A) Frontend hardcoded fallback (most common)

In the **frontend** repo, run a repo-wide search for:

- `60 seconds`
- `short summary`
- The exact string you see in the UI (e.g. "For your final recording, deliver a short summary in under 60 seconds")

If it exists, the UI is substituting it when `final_task` is missing/empty.

### B) Backend hardcoded fallback

In the **backend** repo, same search: `60 seconds`, `short summary`.  
If not present (confirmed in this repo), it’s not deterministic backend text.

### C) LLM output

If the **Network** response from **POST .../metric-answers** contains that generic sentence as **`final_task`**, then it’s coming from the model (or a prompt/context that leads to that). Fix by improving context (e.g. non-empty **context_short**) or tightening the prompt.

---

## Fix by branch (Step 1 → Branch A or B)

Fix depends on **where the generic "60 seconds summary" text is coming from**. There are only two real branches, and the code changes are different.

### Step 1 — Decide which branch you're in (1 minute)

Open DevTools → Network → find the **POST** request:

`POST …/v2/homework/session/<session_id>/metric-answers` (or the BFF `/api/.../metric-answers`)

Look at the JSON response:

- **If `final_task` in the response already contains the generic "60 seconds summary"**  
  → **Backend/LLM branch** (fix prompt/context/fallback).
- **If `final_task` in the response is good, but UI shows the generic text anyway**  
  → **Frontend/BFF branch** (display/fallback/mapping bug).

Everything below is "how to fix" for each branch.

---

### Branch A — Response `final_task` is generic (backend/LLM issue)

#### A1) Ensure `context_short` is actually populated

If `context_short` is empty, the model will produce generic tasks.

Check for the session that produced the bad task:

```sql
SELECT id, context_short, selected_task_id, final_task_text
FROM public.v2_sessions
WHERE id = '<SESSION_ID>';
```

**Fix if context_short is empty:**

- Ensure recording-1 completion reliably:
  - stores transcript
  - calls `generate_context_short(transcript)`
  - writes `context_short` to the session
- Add logging around context generation failures (don't swallow exceptions silently).

#### A2) Make the prompt explicitly forbid "60 seconds / short summary"

Even with good context, the model might drift. Add a hard constraint in `generate_final_task()` prompt like:

- "Do NOT mention time limits (seconds/minutes)"
- "Do NOT say 'short summary'"
- "Do NOT reference '60 seconds'"
- "Use the user's context_short explicitly (quote or paraphrase one detail)."

That single change typically eliminates that generic pattern.

#### A3) If you have a deterministic fallback, make it match your desired format

If OpenAI fails and you return a fallback string, ensure that fallback also does **not** contain generic "final recording" instructions.

---

### Branch B — Response `final_task` is good but UI shows generic (frontend/BFF issue)

This is the most common situation.

#### B1) Remove/limit the frontend placeholder

Find where the "60 seconds summary" string is defined (search the frontend repo). Replace it with a true loading state:

- While waiting for `final_task_text` → show "Loading your task…"
- If API error → show "Couldn't load task. Tap to retry."
- **Do not** show a "fake" task as a fallback.

#### B2) Ensure UI renders only these two sources (and nothing else)

Final task screen should display:

1. **`response.final_task`** immediately after **POST metric-answers**, and/or  
2. **`session.final_task_text`** from **GET session/status** on resume

Make sure the code does **not** do something like:

- `finalTask = api.final_task || DEFAULT_PLACEHOLDER_TEXT`

It should be:

- if missing → loading/error state, not a substitute task.

#### B3) Check BFF passthrough and key mapping

If the browser calls `/api/...`, confirm the BFF route returns the full backend payload and doesn't rename keys.

Common bug:

- backend returns `{ final_task: "..." }`
- BFF returns `{}` or `{ finalTask: ... }`
- frontend looks for `final_task` → doesn't find it → uses placeholder

**Fix:** BFF should return the backend JSON unchanged (or the frontend must match the transformed key).

---

### Verification (after you change something)

1. Do **POST metric-answers** and confirm response JSON contains **`final_task`** with the correct personalized text.
2. Refresh the page and confirm **GET session/status** contains **`session.final_task_text`**, and UI displays it (no placeholder).
3. Confirm the generic "60 seconds summary" string never appears anywhere except maybe a temporary loading label.

---

### If you paste one thing, we can tell you exactly which fix to apply

Paste the **URL + JSON response** from **POST …/metric-answers** and say what the **UI showed**. That immediately determines Branch A vs Branch B and the exact file-level fix (prompt/context vs UI/BFF fallback).

---

## Validate actual API responses

Design intent:

- After **recording-1:** response includes **task_block** (metric_question_1/2/3 only; no focus task for display).
- After **metric-answers:** response includes **final_task**.
- **GET session/status** (resume): includes **session.final_task_text** when status is `final_task_ready` or later.

Capture real responses for:

1. **POST /v2/homework/session/<id>/recording-1** (or the endpoint that completes rec-1)
2. **POST /v2/homework/session/<id>/metric-answers**
3. **GET /v2/homework/session/status** (resume path)

Check:

- **`final_task`** exists in metric-answers response and has the expected content.
- **`session.final_task_text`** (or equivalent) exists in status response after metric-answers.
- Frontend uses **one of those two sources** and does **not** override with a fallback/placeholder.

---

## Resume / display precedence

When the student reloads or resumes on the “Final task” step:

- **Preferred:** Show **`session.final_task_text`** from **GET /v2/homework/session/status**.
- **Or:** Show **`final_task`** from the **POST metric-answers** response and keep it in client state for that session.
- **Avoid:** Any third “placeholder” or default text that can mask real backend output.

Many “wrong text on screen” bugs come from resume logic using a placeholder instead of DB-backed **final_task_text**.

---

## Backend-side checks when final task is generic

If a session produced a generic final task, inspect it in Supabase:

```sql
SELECT id, user_id, status, context_short, selected_task_id, final_task_text, created_at
FROM public.v2_sessions
WHERE id = '<SESSION_UUID>';
```

- If **context_short** is null/empty → issue is upstream (transcription, or **generate_context_short()** failed/skipped). Verify the transcript exists (wherever stored) and that **generate_context_short()** is not failing silently.
- If **final_task_text** is generic in DB → backend/LLM/prompt/context; if **final_task_text** is good in DB but UI shows generic → frontend display/fallback or resume logic.

---

## Frontend vs backend

| Responsibility | Where |
|----------------|--------|
| **Generation** | **Backend.** `generate_final_task()` builds the 2-sentence instruction and returns it in **POST metric-answers** as **`final_task`** and stores it as **session.final_task_text**. |
| **Display** | **Frontend.** It should show the **`final_task`** from the metric-answers response (or **`session.final_task_text`** from **GET /v2/homework/session/status** when resuming). |

If the text shown is generic ("deliver a short summary in under 60 seconds") instead of the personalized 2-sentence task:

- **Backend:** Ensure **context_short** is actually set after recording-1 (transcript not empty, `generate_context_short` not failing). If context is empty, the AI may produce generic text. Check session in DB for **context_short** and **final_task_text** after metric-answers.
- **Frontend:** Ensure the "Final task" card displays **only** the value from the API (**response.final_task** or **session.final_task_text**), and does **not** use a fallback string like "For your final recording, deliver a short summary in under 60 seconds" when the API value is empty or missing.

---

## Quick checks

1. **Backend:** After **POST metric-answers**, inspect the response body for **`final_task`**. Is it the generic sentence or the expected personalized task?
2. **Backend:** For that session, check **context_short** and **final_task_text** in the DB (see [Backend-side checks](#backend-side-checks-when-final-task-is-generic) above). If **context_short** is null/empty, fix recording-1/transcription/context generation.
3. **Frontend:** In the Network tab, confirm the "Final task" screen uses **final_task** or **final_task_text** from the API and that there is no hardcoded fallback.

---

## Debug end-to-end (one-shot)

To determine definitively whether the generic text is from backend or frontend:

1. Paste **one** Network response: the **URL** and **full JSON body** of **POST .../metric-answers** (the response that should contain **`final_task`**).
2. Say what the **UI actually displayed** on the final task screen.

From that we can tell:

- If **`final_task`** in the response is generic → backend/LLM/prompt/context issue.
- If **`final_task`** in the response is good but the UI showed generic → frontend display or fallback issue.
