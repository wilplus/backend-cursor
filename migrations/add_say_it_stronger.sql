-- willab — "Say It Stronger" (founder 2026-07-07): per-snippet LLM rewrite
-- suggestions replace the raw acoustic numbers on the USER readout (the
-- numbers stay in `metrics`, in the ranking blend, and on the coach view —
-- nothing about the L2 blend changes; this is presentation-layer only).
--
-- Shape: JSONB
--   { "already_strong": bool,
--     "upgrades": [{ "original", "upgrade", "reason" }],   -- max 3
--     "rewrite_your_voice": str, "rewrite_polished": str,
--     "why": str|null,                                     -- qualitative only
--     "model": str, "version": 1, "generated_at": iso }
--
-- Generated fire-and-forget after processing (services/say_it_stronger.py),
-- write-once (only when NULL) so duplicate daemon runs are idempotent.
-- AC-9: the `why`/`reason` copy is guarded in code — no digits, no retired
-- construct vocabulary. L1: NEVER read by the best-presentation/ideal-text
-- assembly; suggestion overlay only.
--
-- Nullable + additive; the writer degrades gracefully when the column is
-- missing. Idempotent — safe to re-run.

ALTER TABLE public.charisma_snippets
    ADD COLUMN IF NOT EXISTS say_it_stronger JSONB NULL;

-- Rollback (manual):
--   ALTER TABLE public.charisma_snippets DROP COLUMN IF EXISTS say_it_stronger;
