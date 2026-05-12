# Snippet CTA → Conversation: V2 Roadmap

Branch: `claude/snippet-cta-conversation-flow-Y5tWN`

## Context

Today the snippet CTA flow is functional but narrow:
- Each CTA click opens a 2-turn coaching conversation (awareness + trial re-performance).
- The model sees the snippet's `transcript` + `admin_comment` + the user's first reply.
- Cross-user follow-up outcomes feed a global few-shot pool.
- `follow_up_outcome` is upserted (latest-wins) — no attempt history.
- No long-term per-user memory; the bot is amnesic across CTA clicks.
- Admin manually writes every annotation; no AI assistance.
- Snippet labels (charisma/stress) drive routing but the system doesn't learn from them.

This roadmap upgrades the flow into a compounding system that captures proprietary IP (admin coaching framework, voice uncertainty signal, per-user progression data) while staying privacy-safe for B2B.

## Architecture vision (end state)

```
User clicks snippet CTA
         ↓
System loads in parallel:
  ├── Snippet (transcript + admin_comment + acoustic features)
  ├── Learner Profile (per-user sticky note, admin-overridable)
  ├── Tenant Few-Shot Pool (top exchanges from same company)
  └── Entity Links (related past moments, progression patterns)
         ↓
LLM call with structured output (no parser fragility)
         ↓
User answers + optional self-rating before AI reveal
         ↓
Trial re-recording → new coaching_attempts row (1:N, never overwrites)
         ↓
Background loop:
  ├── Score the exchange (fact-checked before persist)
  ├── Update learner profile (respecting admin locks)
  ├── Propagate to related entities (snippets, tenant aggregates)
  ├── Generate admin-draft annotations on new snippets
  └── (Eventually) regenerate user's mirror doc
         ↓
Next CTA click → AI starts with deeper context
```

Short conversations. Long memory. Hard tenant walls. Admin in the loop.

---

## Implementation order

Ship in this sequence. Each phase is shippable independently behind a feature flag.

| # | Phase | Effort | Dependencies |
|---|---|---|---|
| 0 | Structured Outputs | 0.5d | — |
| 1 | Tenant-Scoped Few-Shot | 1.5d | — |
| 5 | Fact-Check Guard | 0.5d | 0 |
| 2 | Coaching Attempts (1:N) | 2d | 0 |
| 8 | Self-Rating Gap | 1d | 2 |
| 9 | Admin-Draft Annotations + Profile Override | 4d | 0, 5 |
| 3 | Learner Profile | 3d | 0; richer with 2, 9 |
| 4 | Entity Propagation | 2d | 2, 3 |
| 7 | Skill-File Refactor | 2d | 0 |
| 6 | Mirror Endpoint | 3d | 2, 3, 4, 5 |

**Total: ~19–20 engineering days (≈4 weeks with review buffer).**

MVP cut (ship for testing platform first): Phases **0, 1, 5, 2, 8, 9, 3**. Defer 4, 6, 7.

---

## Phase 0 — Structured Outputs

**Goal:** Force JSON Schema on every LLM call. Kills parser fragility. Prerequisite for Phases 2, 3, 5, 6, 9.

**Touch points**
- `services/coaching_outcomes.py:241-311` — `_llm_score_exchange`
- `routes/v2_routes.py:8244-8354` — `/coaching/turn` output
- New module: `services/llm_schemas.py`

**Steps**
1. Define schemas in `services/llm_schemas.py`:
   ```python
   EXCHANGE_SCORE_SCHEMA = {
     "type": "object", "additionalProperties": False,
     "required": ["specificity", "emotional_movement", "engagement", "rationale"],
     "properties": {
       "specificity":        {"type": "number", "minimum": 0, "maximum": 1},
       "emotional_movement": {"type": "number", "minimum": 0, "maximum": 1},
       "engagement":         {"type": "number", "minimum": 0, "maximum": 1},
       "rationale":          {"type": "string", "maxLength": 240},
     },
   }

   AWARENESS_TURN_SCHEMA = {
     "type": "object", "additionalProperties": False,
     "required": ["validation_bubble", "challenge_bubble", "advance"],
     "properties": {
       "validation_bubble": {"type": "string", "maxLength": 280},
       "challenge_bubble":  {"type": "string", "maxLength": 280},
       "advance":           {"type": "boolean"},
       "next_stage":        {"type": ["string","null"], "enum": ["trial","complete",None]},
     },
   }
   ```
2. Switch OpenAI calls to `response_format={"type":"json_schema", "json_schema": {...,"strict":True}}`.
3. Delete regex / `_extract_json_block` fallbacks. Keep one `try/except` for transport errors only.
4. Replace `split("|||")` + `"[ADVANCE]" in text` in `/coaching/turn` with schema fields.
5. Unit test each schema against 5 sample inputs.

**Risk:** verify `gpt-4o-mini` is pinned to a version that supports JSON Schema (≥ `gpt-4o-mini-2024-07-18`).

---

## Phase 1 — Tenant-Scoped Few-Shot Pool

**Goal:** Wall off exemplars by company. Eliminate NDA risk from cross-tenant prompt leakage.

**Touch points**
- `services/db.py:5423-5506` — `get_top_followup_examples`
- `routes/v2_routes.py:7325-7396` — `_build_few_shot_block`
- New migration

**Schema**
```sql
CREATE TABLE IF NOT EXISTS companies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name TEXT NOT NULL,
  email_domain TEXT UNIQUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE users ADD COLUMN company_id UUID REFERENCES companies(id);

ALTER TABLE charisma_snippets
  ADD COLUMN sharing_scope TEXT DEFAULT 'tenant_only';
  -- 'tenant_only' | 'canonical' | 'private'

CREATE TABLE few_shot_retrievals (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  requesting_snippet_id UUID,
  exemplar_snippet_ids UUID[],
  retrieved_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Steps**
1. Backfill `users.company_id` by email domain; auto-create personal companies for single-user accounts.
2. Add WHERE clause to `get_top_followup_examples`: join through `users.company_id`, filter `sharing_scope IN ('tenant_only','canonical')`.
3. Cold-start fallback: when in-tenant pool < N, top up with `canonical` (admin-vetted, sanitized).
4. Audit log every retrieval to `few_shot_retrievals` for compliance trail.
5. Rollout behind `FEW_SHOT_TENANT_SCOPED` flag; back-test pool depth before flipping default.

---

## Phase 5 — Fact-Check Guard

**Goal:** Stop hallucinated LLM outputs from corrupting downstream data (few-shot pool, profile, mirror).

**Touch points**
- `services/coaching_outcomes.py:75-182` — insert verification step
- New helper: `services/fact_check.py`

**Steps**
1. `fact_check_outcome(attempt, source_snippet) -> {passed, issues}`:
   - **Phrase verification:** any quoted span in `rationale` must exist (substring or fuzzy ≥0.85) in `user_answer.text` or `source_snippet.transcript`.
   - **Specificity floor:** if `specificity > 0.7` but `rationale` cites zero user-input verbatim, downgrade to 0.5 and flag.
2. On failure: still insert the attempt (preserve evidence), but set `is_eligible_for_few_shot = false`, log to `fact_check_failures`.
3. Few-shot retrieval filters on `is_eligible_for_few_shot = true`.
4. Same guard runs on Phase 9 admin drafts and Phase 6 mirror outputs.

**Effort: ~0.5d** (no extra LLM call; pure string match). Add LLM verifier later if drift persists.

---

## Phase 2 — Coaching Attempts (1:N History)

**Goal:** Stop overwriting `follow_up_outcome`. Preserve every attempt to power Before/After UX and progression data.

**Touch points**
- New migration + table
- `services/db.py` — new `insert_coaching_attempt`, `list_coaching_attempts_for_snippet`
- `services/coaching_outcomes.py:75-182` — UPSERT → INSERT
- `routes/v2_routes.py` — new `GET /coaching/progress?snippet_id=…`
- Backfill: `scripts/backfill_coaching_attempts.py`

**Schema**
```sql
CREATE TABLE coaching_attempts (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  snippet_id UUID NOT NULL REFERENCES charisma_snippets(id) ON DELETE CASCADE,
  user_id UUID NOT NULL,
  attempt_number INT NOT NULL,
  source TEXT NOT NULL,
  question_text TEXT,
  user_answer_text TEXT,
  user_answer_duration_ms INT,
  user_answer_word_count INT,
  evaluator_model TEXT,
  score NUMERIC(4,3),
  components JSONB,
  acoustic_features JSONB,
  rationale TEXT,
  trial_recording_id UUID REFERENCES recordings(id),
  is_eligible_for_few_shot BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (snippet_id, attempt_number)
);
CREATE INDEX idx_coaching_attempts_snippet ON coaching_attempts(snippet_id, attempt_number);
CREATE INDEX idx_coaching_attempts_score ON coaching_attempts(score DESC) WHERE score IS NOT NULL;
```

**Steps**
1. Migrate schema; backfill existing `follow_up_outcome` JSONBs as `attempt_number=1`.
2. Replace UPSERT with `INSERT … attempt_number = COALESCE(MAX,0)+1` inside a transaction.
3. Re-point `get_top_followup_examples` to rank by `MAX(score)` per snippet.
4. New endpoint:
   ```json
   GET /coaching/progress?snippet_id=…
   → {
     "attempts": [{"n":1,"score":0.42,...}, {"n":2,"score":0.78,...}],
     "delta": {"score":+0.36, "energy":+0.24, "pace_wpm":-36}
   }
   ```
5. Join acoustic features from `recording_1_job` output into `acoustic_features` for trial attempts.
6. Cap at 10 attempts per snippet (or prune > 30 days old non-best attempts via cron).

---

## Phase 8 — Self-Rating Gap

**Goal:** Capture user's self-assessment before AI reveal. Gap between self-rating and AI rating becomes a unique signal — surfaces blind spots.

**Touch points**
- Extend `coaching_attempts` table
- Frontend: pre-reveal prompt
- Feeds Phase 3 (calibration_bias in profile)
- Feeds Phase 6 (calibration section in mirror)

**Schema**
```sql
ALTER TABLE coaching_attempts
  ADD COLUMN self_rating       SMALLINT,         -- 1..5, null if skipped
  ADD COLUMN self_rating_at    TIMESTAMPTZ,
  ADD COLUMN calibration_gap   NUMERIC(4,3);     -- ai_score - (self-1)/4
```

**Steps**
1. Frontend: after upload, before score reveal, show *"How do you think that went?"* with 5 buttons + skip.
2. New endpoint `POST /coaching/self-rating { attempt_id, self_rating }` — persists, computes gap, returns it for immediate feedback.
3. Feed into Phase 3 profile diffs as `calibration_bias` and `calibration_blind_spots`.
4. Surface "Calibration trend" tile in UI so users see why it matters.
5. Telemetry: track skip rate; if >40%, A/B test "rate after seeing score" variant.

---

## Phase 9 — Admin-Draft Annotations + Profile Override

**Goal:** Convert admin labor from blank-page authoring to triage. AI proposes drafts, admin approves/edits/rejects. Every edit becomes training data. Same `is_locked` mechanism on every profile field.

This is the **highest IP-value phase** — every admin edit teaches the system the coach's house style, building a proprietary dataset no competitor can replicate.

**Touch points**
- New service: `services/admin_drafts.py`
- Extend `charisma_snippets` with draft fields + review status
- New table `admin_edit_history` (training data)
- New table `admin_settings` (house style summary)
- Extend `learner_profiles` with `locked_fields`
- New endpoints: `GET /admin/draft-queue`, `POST /admin/draft/:id/(approve|edit|reject)`
- Frontend: admin queue UI

**Schema**
```sql
ALTER TABLE charisma_snippets
  ADD COLUMN draft_admin_comment       TEXT,
  ADD COLUMN draft_follow_up_question  TEXT,
  ADD COLUMN draft_coach_label         TEXT,
  ADD COLUMN draft_confidence          NUMERIC(4,3),
  ADD COLUMN draft_model               TEXT,
  ADD COLUMN draft_generated_at        TIMESTAMPTZ,
  ADD COLUMN review_status             TEXT DEFAULT 'pending',
  ADD COLUMN reviewed_by               UUID,
  ADD COLUMN reviewed_at               TIMESTAMPTZ;

CREATE INDEX idx_snippets_review_queue
  ON charisma_snippets(review_status, draft_confidence DESC)
  WHERE review_status = 'pending';

CREATE TABLE admin_edit_history (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  snippet_id UUID NOT NULL REFERENCES charisma_snippets(id),
  admin_id UUID NOT NULL,
  field TEXT NOT NULL,
  draft_value TEXT,
  final_value TEXT,
  edit_distance NUMERIC(4,3),
  edited_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_admin_edits_training ON admin_edit_history(field, edited_at DESC);

CREATE TABLE admin_settings (
  admin_id UUID PRIMARY KEY,
  house_style_summary TEXT,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE learner_profiles
  ADD COLUMN locked_fields JSONB DEFAULT '{}'::jsonb;
```

**Part A — Draft generation pipeline**
1. After `extract_recording_snippets` creates a new snippet, fire background job `generate_admin_draft(snippet_id)`.
2. LLM context: snippet transcript + acoustic features + last 10 admin annotations from same admin/tenant + admin's `house_style_summary`.
3. Structured output:
   ```json
   {
     "draft_admin_comment": "...",
     "draft_follow_up_question": "...",
     "draft_coach_label": "charisma|stress|other",
     "confidence": 0.0-1.0,
     "rationale": "..."
   }
   ```
4. Fact-check pass (Phase 5) before persist.
5. `review_status = 'pending'`; low-confidence flagged but still queued.

**Part B — Admin queue UI**
- `GET /admin/draft-queue?tenant_id=…&sort=confidence_asc|chronological`
- Three actions per row: approve / edit / reject
- Diff display showing AI's draft vs admin's final
- Bulk-approve for `confidence > 0.85`

**Part C — Training loop**
1. Every approval/edit logged to `admin_edit_history` with `edit_distance`.
2. Weekly cron regenerates `admin_settings.house_style_summary` from last 50 edits per admin.
3. House style injected into future draft prompts.
4. Confidence calibration: high edit-distance on high-confidence drafts triggers prompt review.

**Part D — Profile override**
1. `apply_diff()` skips any field listed in `locked_fields`.
2. Admin UI: 🔒 toggle on every profile field.
3. All lock toggles logged with `admin_id` + timestamp.

**Part E — Auto-labeler (absorbed)**
`draft_coach_label` is just one field of the draft pipeline. Admin edits to label train future label proposals. No separate auto-labeler phase needed.

**Anti-anchoring control**
Every 10th draft hides the AI suggestion; admin writes blind. Track drift between blind and primed annotations — quality watchdog.

**Cold-start gate**
Per-tenant: `ADMIN_DRAFTS_ENABLED` stays off until 30+ baseline admin annotations exist.

---

## Phase 3 — Learner Profile

**Goal:** Per-user "sticky note" injected into every prompt. Auto-updated from coaching attempts. Admin-overridable.

**Schema**
```sql
CREATE TABLE learner_profiles (
  user_id UUID PRIMARY KEY,
  role TEXT,
  strengths JSONB DEFAULT '[]'::jsonb,
  weaknesses JSONB DEFAULT '[]'::jsonb,
  coach_instruction TEXT,
  goals JSONB DEFAULT '[]'::jsonb,
  calibration_bias NUMERIC(4,3),
  calibration_blind_spots JSONB DEFAULT '[]'::jsonb,
  locked_fields JSONB DEFAULT '{}'::jsonb,   -- from Phase 9
  total_sessions INT DEFAULT 0,
  version INT DEFAULT 1,
  updated_at TIMESTAMPTZ DEFAULT NOW()
);
```

**Steps**
1. `services/learner_profile.py`:
   - `propose_profile_diff(profile, latest_attempt) -> ProfileDiff` (structured output)
   - `apply_diff(user_id, diff)` — caps lists at top 5 by `confidence × recency_decay`; **skips locked fields**.
2. Inject context block in `_generate_llm_question` and `/coaching/turn`:
   ```
   LEARNER CONTEXT (authoritative; do not re-ask):
   {"role":"VP of Sales","known_weakness":"speaks too fast under stress",
    "coach_instruction":"Be direct, no fluff."}
   ```
3. Cap injected JSON at ~120 tokens. Log final prompt size; alert on regressions.
4. Profile updater consumes Phase 8 calibration data.
5. Privacy: strictly per-user; integration test for cross-user leak prevention.
6. Weekly decay cron: weakness/strength `last_seen > 90 days` halves confidence; below 0.2 removed.

---

## Phase 4 — Entity Propagation

**Goal:** After each coaching session, walk the graph and update related entities. Turns isolated moments into a connected map.

**Schema**
```sql
CREATE TABLE entity_links (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  source_type TEXT NOT NULL,
  source_id UUID NOT NULL,
  target_type TEXT NOT NULL,
  target_id UUID NOT NULL,
  relation TEXT NOT NULL,           -- 'similar_moment' | 'progression_of' | 'shares_pattern'
  confidence NUMERIC(4,3),
  created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_entity_links_target ON entity_links(target_type, target_id);

CREATE TABLE tenant_pattern_stats (
  company_id UUID NOT NULL,
  intent TEXT NOT NULL,
  pattern_tag TEXT NOT NULL,
  count INT DEFAULT 0,
  avg_score NUMERIC(4,3),
  avg_calibration_bias NUMERIC(4,3),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  PRIMARY KEY (company_id, intent, pattern_tag)
);
```

**Steps**
1. Background job after each `coaching_attempts` insert:
   - Find related snippets (same user, same `coach_label`, similar transcript embedding) → `entity_links` rows.
   - Update `tenant_pattern_stats` aggregates.
   - Surface `related_moments` in `/coaching/start` response.
2. Cap propagation depth at 1 hop.
3. Cap links per source at 10; prune stale via cron.
4. Daemon thread; failures log, never block.

---

## Phase 7 — Skill-File Refactor

**Goal:** Extract inline Python prompt strings to standalone markdown skill files with frontmatter. Thin harness, fat skills.

**Steps**
1. Create `services/skills/` with files:
   - `first_question_charisma.md` / `first_question_stress.md`
   - `awareness_charisma.md` / `awareness_stress.md`
   - `score_exchange.md`
   - `profile_diff.md` (Phase 3)
   - `admin_draft.md` (Phase 9)
   - `mirror_generate.md` (Phase 6)
   - `fact_check.md` (Phase 5)
2. Skill file format:
   ```markdown
   ---
   id: awareness_stress
   triggers: [intent=stress, stage=awareness]
   inputs: [admin_comment, user_transcript, user_first_reply, learner_profile, few_shot_examples]
   output_schema: awareness_turn_v1
   model: gpt-4o-mini
   temperature: 0.6
   max_tokens: 200
   ---
   # System
   ...
   ```
3. Build `services/skill_loader.py` — parses frontmatter, returns callable with model/schema/prompt bundled.
4. Add `services/skills/__manifest__.json` listing all skills + triggers.
5. Refactor existing endpoints to dispatch by skill id. **No new functionality** — purely structural. Integration tests must show identical behavior.

Pays off when adding a third intent (e.g., "negotiation moments") becomes one new markdown file instead of branching through 8000 lines.

---

## Phase 6 — Mirror Endpoint

**Goal:** Generate a personalized doctrine doc per user: left column = framework principle, right column = how it shows up in user's own history with citations. The headline UX moat.

**Schema**
```sql
CREATE TABLE user_mirrors (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID NOT NULL,
  framework TEXT NOT NULL,
  version INT NOT NULL,
  content JSONB NOT NULL,
  source_attempt_ids UUID[],
  generated_at TIMESTAMPTZ DEFAULT NOW(),
  superseded_at TIMESTAMPTZ
);
CREATE INDEX idx_user_mirrors_active ON user_mirrors(user_id) WHERE superseded_at IS NULL;
```

**Content shape**
```json
{
  "sections": [
    {
      "framework_principle": "Adrenaline is performance fuel, not panic.",
      "framework_source": "Brooks 2014 reappraisal",
      "your_evidence": [
        {
          "snippet_id": "...",
          "moment_summary": "Apr 14 — investor pitch, budget question",
          "transcript_quote": "I... uh, the runway is...",
          "acoustic_signal": "pace +47% above baseline, energy -22%",
          "attempt_progression": [{"n":1,"score":0.42},{"n":2,"score":0.78}]
        }
      ],
      "your_pattern": "Pace spikes occur on numeric questions, not interpersonal ones.",
      "actionable_drill": "Before answering any number question, one beat of breath."
    },
    {
      "framework_principle": "Your Calibration",
      "your_pattern": "On stress moments you rate yourself +0.24 above the AI. Bring this gap to your awareness."
    }
  ],
  "compounding_marker": "v7 — 3 new evidence pieces since v6"
}
```

**Pipeline**
1. Load: learner profile + last 20 attempts + related snippets via entity links + acoustic features.
2. LLM call with structured output (skill file from Phase 7).
3. Fact-check pass (Phase 5) — every `transcript_quote` must verify; every `snippet_id` must exist.
4. Persist with monotonic version; supersede prior.

**Triggers**
- On-demand: user clicks "Generate my mirror"
- Auto: every N completed coaching sessions
- Diff display: "What changed since last version"

---

## Feature flags

| Flag | Default | Flip when |
|---|---|---|
| `STRUCTURED_OUTPUTS_ENABLED` | on | Phase 0 merge |
| `FEW_SHOT_TENANT_SCOPED` | off → on | backfill verified, pool depth tested |
| `FACT_CHECK_FLAGGING` | on | Phase 5 merge |
| `FACT_CHECK_ENFORCING` | off → on | 1 week observation |
| `COACHING_ATTEMPTS_DUAL_WRITE` | on during migration | drop after backfill verified |
| `SELF_RATING_PROMPT` | beta tenants | skip rate < 40% confirmed |
| `ADMIN_DRAFTS_ENABLED` | per-tenant, off until 30+ baseline annotations | baseline reached |
| `ADMIN_DRAFTS_AUTO_LABEL` | off → on after 100 labeled snippets | label accuracy verified |
| `PROFILE_FIELD_LOCKS` | on | Phase 9 merge |
| `HOUSE_STYLE_LEARNING` | on after 50 edits per admin | automatic |
| `LEARNER_PROFILE_INJECT` | per-tenant rollout | manual |
| `ENTITY_PROPAGATION_ENABLED` | per-tenant | after Phase 3 stable |
| `SKILLS_FROM_FILES` | on after Phase 7 | immediately on merge |
| `MIRROR_ENDPOINT` | beta tenants | after fact-check enforcing on |

---

## IP captured by the MVP cut (Phases 0–9, excluding 4/6/7)

Five proprietary datasets that did not exist before, built passively from work already happening:

1. **`admin_edit_history`** — labeled training data of (AI draft → admin final). Encodes coach's house style. **No competitor can replicate without your admins.**
2. **`coaching_attempts`** — append-only progression dataset per user per moment. Powers Before/After proof.
3. **`learner_profiles`** — per-user accumulated knowledge that compounds across sessions.
4. **`acoustic_features`** on every attempt — pitch variance, hesitation markers, pace. Foundation for proprietary uncertainty-detection model.
5. **Self-rating gap data** (in `coaching_attempts`) — calibration signal unique to your product.

Voice stays central. Text is the substrate; voice is the moat. Specifically: **uncertainty detection in voice** is the proprietary audio signal worth the most long-term investment.

---

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Tenant-scoped pool too thin at start | Canonical (admin-vetted) topup pool |
| Admin rubber-stamps drafts | Every 10th draft hidden, blind-write spot-check |
| Profile drift / bad inferences | Admin lock on any field via `locked_fields` |
| Hallucinated evidence in mirror | Fact-check pass requires `snippet_id` to exist + quotes to verify |
| Storage growth from 1:N attempts | Cap 10/snippet; prune non-best > 30 days |
| Token bloat from profile injection | Cap at ~120 tokens; alert on regressions |
| Auto-labeler drift from admin style | Edit-distance watchdog on `admin_edit_history` |
| Self-rating skip rate too high | A/B test post-reveal variant if >40% |
| Few-shot retrieval performance | Denormalized `best_attempt_score` on `charisma_snippets` |

---

## The one-sentence pitch (post-MVP)

Every coaching conversation starts fresh and finishes in under 60 seconds — but the AI coach already knows your role, your patterns under stress, your top-performing colleagues' best answers, and your own self-perception blind spots, all without your data ever leaving your company.

---

## Open questions for product / business

- **First tenant for `FEW_SHOT_TENANT_SCOPED` rollout** — who has enough volume to test the pool depth?
- **Self-rating UX** — 1–5 buttons, or two-slider (confidence + execution)?
- **Mirror cadence** — every 5 sessions automatic, or fully on-demand?
- **Admin draft confidence threshold** — at what score does bulk-approve become safe?
- **Voice tier-2 model** — build uncertainty detection in-house, fine-tune Whisper, or buy?
