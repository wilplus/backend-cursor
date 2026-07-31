-- willab — LLM/ASR usage ledger (Phase 0 of the token-pricing plan,
-- docs/PRICING-TOKENS-PLAN.md §7, founder-approved 2026-07-27).
--
-- WHY THIS EXISTS. The pricing model prices every metered action at measured
-- cost × 7. Today nothing measures. services/llm.py already LOGS
-- prompt_tokens/completion_tokens per surface, but a log line is not a
-- queryable series — so the ×7 multiplier in the plan is DERIVED (my
-- estimates), not MEASURED. This table is what turns it into a number.
-- Until it has run for a couple of weeks, every per-action price in §2 of the
-- plan is an educated guess.
--
-- ONE ROW PER MODEL CALL. Deliberately not aggregated: rollups can always be
-- derived from rows, rows can never be derived from a rollup, and the first
-- question anyone asks ("which surface is expensive on a LONG take?") needs
-- the per-call grain.
--
-- STORE THE RAW COUNTS, TREAT cost_usd AS DERIVED. OpenAI reprices. tokens_in
-- / tokens_out / audio_seconds are ground truth and stay true forever;
-- cost_usd is a convenience computed at write time from
-- services/llm_pricing.py. When prices change, backfill cost_usd from the raw
-- counts — never the other way round. price_version records which table
-- produced the number so a repricing is auditable.
--
-- user_id IS TEXT, NOT UUID, AND HAS NO FOREIGN KEY. Both deliberate, both
-- for the same reason: this is an observability sink, and the ONE failure mode
-- that ruins it is silently dropping rows. A UUID cast error on an odd caller,
-- or an FK violation from a deleted user, would do exactly that — the writer
-- swallows all exceptions by design, so a rejected row is lost with no trace.
-- Robustness beats referential tidiness here.
--
-- NOT A BILLING LEDGER. This measures what WE pay OpenAI. The user-facing
-- token balance is a separate append-only ledger (plan §7 Phase 1) and must
-- never be derived from this table: the whole point of the pricing model is
-- that the user price is a FLAT published number per action (fence §6.2 —
-- a cost-derived price varies with how the user performed, which is an AC-9
-- score wearing a billing costume).
--
-- Idempotent; RLS on, no policy (service-role only). Contains no user content
-- — surfaces and token counts only, never prompts or completions.

CREATE TABLE IF NOT EXISTS public.llm_usage (
    id            BIGSERIAL PRIMARY KEY,
    -- Stable lower_snake call-site tag ('say_it_stronger', 'whisper_take',
    -- 'master_doc_rag'). The unit of analysis — keep it stable per call site.
    surface       TEXT        NOT NULL,
    model         TEXT        NOT NULL,
    -- Chat calls: token counts. NULL for audio calls.
    tokens_in     INTEGER     NULL,
    tokens_out    INTEGER     NULL,
    -- Whisper: the billable unit is TIME, not tokens. NULL for chat calls.
    audio_seconds REAL        NULL,
    cost_usd      NUMERIC(12, 6) NULL,
    price_version TEXT        NULL,
    -- Attribution. All nullable: cron/admin/system contexts have no user, and
    -- a missing attribution must never cost us the cost row itself.
    user_id       TEXT        NULL,
    session_id    TEXT        NULL,
    arc_id        TEXT        NULL,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE public.llm_usage ENABLE ROW LEVEL SECURITY;

-- The three questions this table exists to answer, in index form:
--   "what did we spend last week?"        → created_at
--   "which surface is expensive?"         → surface, created_at
--   "what does one user/take cost?"       → user_id / session_id
CREATE INDEX IF NOT EXISTS idx_llm_usage_created
    ON public.llm_usage (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_usage_surface_created
    ON public.llm_usage (surface, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_usage_user_created
    ON public.llm_usage (user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_llm_usage_session
    ON public.llm_usage (session_id);

COMMENT ON TABLE public.llm_usage IS
    'What WE pay OpenAI, one row per model call. Phase 0 of token pricing. '
    'Raw counts are ground truth; cost_usd is derived and re-computable. '
    'Never a source for user-facing prices (fence AC-9 / plan §6.2).';

-- Rollback (manual, never automatic):
--   DROP TABLE IF EXISTS public.llm_usage;
