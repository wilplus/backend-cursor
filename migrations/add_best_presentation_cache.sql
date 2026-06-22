-- willab Part B (2026-06-22) — cache the composed best-presentation.
--
-- GET /v2/explore/arc/<id>/best-presentation ran the ~2-4s LLM compose on
-- EVERY open. The composed slides only change when a take is added, the coach
-- publishes (re-ranks / confirms breakthroughs), so we cache the composed
-- payload keyed by arc + a content SIGNATURE. On a hit (signature unchanged)
-- we return the cached payload and skip the LLM. User pencil-edits are applied
-- on read (cheap), so they do NOT need to bust this cache.
--
-- payload = the composed pre-edit best-presentation
--   { "slides": [...], "presentation_ref": str|null }
-- signature = hash over the arc's takes (session ids + results_published_at +
--   take_index) — see services/best_presentation.py::_bp_signature.
--
-- Best-effort: get/upsert_best_presentation_cache degrade gracefully if this
-- table is missing (the GET just recomputes every time, as today). Idempotent.

CREATE TABLE IF NOT EXISTS public.best_presentation_cache (
    arc_id      TEXT PRIMARY KEY,
    signature   TEXT NOT NULL,
    payload     JSONB NOT NULL,
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Rollback (manual):
--   DROP TABLE IF EXISTS public.best_presentation_cache;
