# Admin Dashboard Design — Architecture & UX Specification

**Date:** 2026-04-08  
**Status:** Designed, pending implementation  

---

## Overview

The Admin Dashboard is a dual-hemisphere AI training system. It is not a standard backend panel — it is two completely different apps nested under two main tabs.

| Tab | Name | Purpose |
|---|---|---|
| Tab 1 | **The Copilot Inbox** | Agentic Pipeline — trains the AI to think, diagnose, and communicate like Artur |
| Tab 2 | **The Acoustic Dojo** | Specialised Pipeline — trains the AI to hear stress and charisma like Artur |

---

## The Two Pipelines

### Specialised Pipeline (The Ear)
Trains perceptual models (Whisper / FFmpeg) to detect non-tangible acoustics — stress tremor, charisma triggers, vocal energy — exactly as Artur detects them. Outputs a score signal used by the mechanical scoring engine.

### Agentic Pipeline (The Voice & Brain)
Trains generative models (GPT / future Llama) to diagnose students, empathise with them, and communicate like Artur. Outputs tasks, messages, video scripts, coach insights, grades, and student profile classifications.

---

## Scoring Architecture (Already Built)

Before the admin layer, every session produces three score layers:

| Layer | Column | Source | Timing |
|---|---|---|---|
| 1 | `mechanical_score` | Deterministic: stage_score + dynamic_db + filler penalty | Immediate on job completion |
| 2 | `ai_task_score` | GPT: did student address the task? | Async, shadow mode |
| 3 | `coach_override_score` | Human: Artur's ground truth | Post-hoc, async |

**Display score** = `coach_override_score` OR `(mechanical × 0.5 + ai_task × 0.5)` OR `mechanical` OR `session.score`

---

## TAB 1 — The Copilot Inbox (Agentic Pipeline)

### Core Mental Model: Cohort-Centric Batching

Students are grouped into **[Profile + Stage]** cohorts before being shown to the coach. This eliminates context-switching and enables batch approval.

**Do not** show a random list of 20 students. Show grouped Action Stacks:
```
🗂️  Stressor · Stage 2   (4 students pending)
🗂️  Drifter · Stage 1    (2 students pending)
🗂️  The Master · Stage 5 (1 student pending)
```

Clicking a stack locks the coach into one pedagogical mindset for the entire batch.

---

### Student Learning Profile

Every student is classified by two dimensions:

#### Dimension 1: Behavioral Profile
Examples (not exhaustive — Artur defines these):
- The Stressor
- The Drifter
- The Perfectionist-Avoider
- The Master

#### Dimension 2: Progression Stage (1–5)

Stage is computed automatically using **two conditions, both required**:

| Stage | Min sessions | Score EMA (rolling avg last 3 sessions) |
|---|---|---|
| 1 | 1+ | < 45% |
| 2 | 3+ | 45–60% |
| 3 | 6+ | 60–72% |
| 4 | 10+ | 72–83% |
| 5 | 15+ | 83%+ |

**Hysteresis rule:** Stage is harder to lose than to gain.
- Drop below threshold for 1 session → stay at current stage
- Drop below threshold for 2 consecutive sessions → demote

This prevents cohort grouping from flickering across days.

#### Stage Override (Manual Correction → DPO Signal)

Coach can manually override stage. Fields:
- `computed_stage` — algorithm output, never manually changed
- `coach_override_stage` — coach correction (null = no override)
- `stage_override_justification` — why (chip annotation)

**Display stage** = `coach_override_stage OR computed_stage`

**DPO training signal:** rows where `coach_override_stage ≠ computed_stage` = labeled training example.

**UI:**
```
Stage: 2  [computed]   [↺ Override]
```
Override opens: dropdown (1–5) + annotation chips:
`[ Prior experience ]` `[ Score inflated ]` `[ Needs more time ]` `[ Custom ]`

---

### Two-Column Progressive Layout

#### Column 1 — Context & Classification (Left)
Grounds the coach in *who* the student is before reviewing their work.

- **Profile Card:** AI declares classification
  - Display: "🤖 AI Classified: The Stressor"
  - AI justification: "High WPM (180), Low Context (40), Self-rating lower than actual"
  - `[✓ Confirm]` or `[↺ Override]` → dropdown + chip annotation
- **Stage Card:** computed stage + override option (see above)
- **Key metrics snapshot:** WPM, filler count, score trend (last 3 sessions)

#### Column 2 — The Approval Stack (Right)

A single vertical scrolling feed with two visually distinct blocks.

---

### Block A — Post-Hoc Audit (Already Delivered to Student)

**Visual cue:** Greyed background, "Delivered" badge. No urgency.

| Item | Column | Action |
|---|---|---|
| AI Score | `ai_task_score` + `mechanical_score` | Read-only reference |
| AI Coach Insight | `coach_insight` | Click to rewrite → `coach_corrected_insight` |
| is_insight_audited | `is_insight_audited` | `[✓ Good as-is]` sets to true |

**DPO signal:**
- `coach_insight` = rejected response
- `coach_corrected_insight` = chosen response
- Only rows where `is_insight_audited = true AND coach_corrected_insight IS NOT NULL` are used for fine-tuning

---

### Block B — Pre-Hoc Action Items (Pending Approval)

**Visual cue:** White background, highlighted border. These are blocking — student hasn't seen anything yet.

| Item | Source | Action |
|---|---|---|
| Grade | AI suggestion | Edit inline |
| Homework comment | AI draft | Edit inline |
| Next task | AI recommendation (profile + stage) | Edit or swap |
| Video script | AI draft | Edit inline |
| Email message | AI draft, personalised | Edit inline |

**The Magic UX:**
- If AI nailed everything → scroll to bottom → `🚀 Approve All & Send`
- If one item is wrong → click into that text box, edit it
- On edit → annotation chips appear inline (no forced free text):
  `[ Tone too robotic ]` `[ Task was wrong ]` `[ Factually incorrect ]` `[ Custom ]`

Chip selection = the RLHF annotation. One tap, data saved.

---

### Batch Flow: Cohort → Master Task → Rapid-Fire Personalization

**Step 1 — Cohort selection**
Coach clicks "Stressor · Stage 2 (4 pending)". Locked into one mindset.

**Step 2 — Master Task approval**
AI proposes one task for the entire cohort.
```
AI Suggestion: Focus Task #14 — The 2-Second Pause Drill
[✓ Approve for Cohort]  [↺ Change Task]
```
One click. Pedagogical decision made for all 4 students simultaneously.

**Step 3 — Rapid-fire personalization**
Carousel of 4 students. AI has already personalised the message for each, injecting the master task into their specific history.

```
Jana K.  → "Hey Jana, your WPM spiked again. Let's do Task #14..."  [Space to approve]
Tom W.   → "Tom, loved the real estate hook! Fix that hesitation with Task #14..."  [Space to approve]
```

Keyboard shortcuts:
- `Space` = approve current student, advance to next
- `E` = open edit mode
- `Tab` = next section within student card
- `Shift+Enter` = approve all items for student, advance

---

### Session Card Structure

Each student card in the carousel is divided into two temporal halves:

```
┌──────────────────────────────────────────────┐
│ Jana K. · Session #12 · 74% · 2h ago        │
├── REVIEW (Session 12) ──────────────────────┤
│ Score · Grade · Comment · AI Coach Insight  │
│ [Post-hoc — student may have seen score]    │
├── PLAN (Session 13) ────────────────────────┤
│ Profile · Stage · Task · Message · Script   │
│ [Pre-send — nothing delivered yet]          │
└──────────────────────────────────────────────┘
```

**Important:** If only one half has actionable items, the other collapses. A new student has no Post-Hoc block. A student mid-cycle with no homework ready has no Pre-Hoc block.

---

### Send Homework — Per-Student MVP

Every student profile page has a persistent "Next Homework" section at the bottom, independent of the cohort flow. This is the MVP path:

```
┌──────────────────────────────────────────┐
│ Next Homework                            │
│                                          │
│ Profile: Stressor · Stage 2             │
│ Task:    [AI suggestion]          [✎]   │
│ Message: [draft]                  [✎]   │
│ Video:   [url]                    [✎]   │
│                                          │
│ [Send to Jana]                           │
│                                          │
│ + 2 similar students ›                  │
└──────────────────────────────────────────┘
```

"Similar students" = same profile + same stage + haven't done this task.
Shown as an optional expansion. Coach can ignore it or send to all in one extra click.

**Automation path (future):** When ready to scale, remove the human approval step. The infrastructure is identical — just skip the UI gate.

---

### New Database Columns Required (Tab 1)

All on `v2_sessions` unless noted:

| Column | Table | Type | Purpose |
|---|---|---|---|
| `coach_corrected_insight` | v2_sessions | text | Coach rewrite of AI coach insight |
| `is_insight_audited` | v2_sessions | boolean | True once coach has reviewed |
| `mechanical_score` | v2_sessions | integer | ✅ Already added |
| `ai_task_score` | v2_sessions | integer | ✅ Already added |
| `coach_override_score` | v2_sessions | integer | ✅ Already added |
| `coach_override_justification` | v2_sessions | text | ✅ Already added |

On `v2_student_profiles` (or `user_sniper_profile`):

| Column | Type | Purpose |
|---|---|---|
| `behavioral_profile` | text | AI-classified profile type |
| `behavioral_profile_justification` | text | AI's evidence |
| `coach_override_profile` | text | Coach correction |
| `profile_override_justification` | text | Why coach changed it |
| `computed_stage` | integer (1–5) | Algorithm output |
| `coach_override_stage` | integer (1–5) | Coach correction |
| `stage_override_justification` | text | Why coach changed it |
| `consecutive_below_threshold` | integer | Hysteresis counter |

---

### New Endpoints Required (Tab 1)

| Method | Path | Purpose |
|---|---|---|
| PATCH | `/v2/admin/students/:id/sessions/:sid/insight-audit` | Save `coach_corrected_insight`, flip `is_insight_audited` |
| PATCH | `/v2/admin/students/:id/profile-classification` | Override behavioral profile + justification |
| PATCH | `/v2/admin/students/:id/stage-override` | Override stage + justification |
| GET | `/v2/admin/cohorts` | Returns students grouped by `[profile + stage]` with pending counts |
| POST | `/v2/admin/cohorts/:profile/:stage/approve-task` | Approve master task for entire cohort |

---

## TAB 2 — The Acoustic Dojo (Specialised Pipeline)

### Purpose

Train the AI's perceptual layer. Not about pedagogy or language — purely about acoustic signal recognition. Coach acts as a sensory instrument, not an editor.

### UI Design

- **Dark mode.** Full focus. One thing on screen at a time.
- **10-second audio/video snippet** — loops automatically.
- **Two binary prompts per clip:**
  - "Tremor / stress detected in voice?"
  - "High charisma trigger?"
- **Controls:**
  - Swipe right / `→` = YES
  - Swipe left / `←` = NO
  - 1.0 second lock before swipe registers (prevents mindless swiping)

### Clip Sources

- Student recordings (pulled from `recordings` table, sliced into 10s segments)
- External web clips (imported manually for general charisma/stress training)

### Gamification

- **Dojo Streak counter** — labels provided today
- **Weekly leaderboard** — if multiple coaches use the system, ranked by labels provided
- **Progress bar** — towards next "belt" level (e.g. 100 labels = Yellow Belt)

### Data Model

New table: `acoustic_labels`

| Column | Type | Purpose |
|---|---|---|
| `id` | uuid | Primary key |
| `clip_source` | text | `student_recording` or `external` |
| `recording_id` | uuid | FK to recordings (if student) |
| `start_ms` | integer | Clip start within recording |
| `end_ms` | integer | Clip end (max 10,000ms) |
| `external_url` | text | If source is external |
| `label_stress` | boolean | Stress/tremor detected |
| `label_charisma` | boolean | Charisma trigger detected |
| `labeled_by` | uuid | Admin user who labeled |
| `labeled_at` | timestamptz | When |
| `confidence` | integer (1–3) | Optional: how sure was the coach |

### Pipeline Connection

Labels feed back into:
1. **Whisper prompt tuning** — clips labeled as high-stress inform the disfluent prompt strategy
2. **Mechanical score modifiers** — confirmed stress patterns become negative modifiers on `dynamic_db` thresholds
3. **Future proprietary model** — the labeled dataset trains a dedicated stress/charisma classifier that runs alongside Whisper

---

## DPO Training Data Summary

Every correction in both tabs generates a training pair:

| Signal | Rejected | Chosen | Source |
|---|---|---|---|
| Score | `ai_task_score` | `coach_override_score` | Tab 1 Post-Hoc |
| Insight | `coach_insight` | `coach_corrected_insight` | Tab 1 Post-Hoc |
| Profile | `behavioral_profile` | `coach_override_profile` | Tab 1 Classification |
| Stage | `computed_stage` | `coach_override_stage` | Tab 1 Classification |
| Task | AI suggestion | Coach edit | Tab 1 Pre-Hoc |
| Message | AI draft | Coach edit | Tab 1 Pre-Hoc |
| Stress | — | `label_stress` | Tab 2 Dojo |
| Charisma | — | `label_charisma` | Tab 2 Dojo |

When ready to fine-tune: filter for rows where `coach_override IS NOT NULL` (or `is_audited = true`). Treat AI output as rejected, coach output as chosen.

---

## Implementation Priority

### Phase 1 — Foundation (next sprint)
1. `computed_stage` calculation in session completion pipeline
2. `coach_override_stage` + `behavioral_profile` columns
3. `coach_corrected_insight` + `is_insight_audited` columns
4. `PATCH /insight-audit` endpoint
5. `GET /cohorts` endpoint

### Phase 2 — Copilot Inbox UI
1. Cohort grouping view (left sidebar)
2. Two-column student card (Context + Approval Stack)
3. Block A (Post-Hoc audit) + Block B (Pre-Hoc approval)
4. Annotation chips on edit
5. "Approve All & Send" button
6. Rapid-fire carousel with keyboard shortcuts

### Phase 3 — Acoustic Dojo
1. `acoustic_labels` table
2. Clip slicing from recordings
3. TikTok-style swipe UI (dark mode)
4. Streak + leaderboard gamification

### Phase 4 — Automation
1. Stage auto-advancement without coach intervention
2. Task recommendation engine (profile + stage → task pool lookup)
3. AI-generated personalised messages pre-filled before coach review
4. Gradual removal of human gates as model confidence increases
