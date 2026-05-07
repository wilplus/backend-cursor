-- Add follow_up_question column to charisma_snippets.
-- Used by the Infinite Retention Loop: when an admin labels a snippet,
-- the LLM pre-computes a contextual follow-up question which is stored
-- here and served directly as the first message in the retention chat,
-- instead of generating it on the fly every time the user clicks a snippet.
--
-- Admin can also manually override the generated question from the snippet
-- editor panel (PATCH /admin/snippets/<id>/comment).

ALTER TABLE charisma_snippets
    ADD COLUMN IF NOT EXISTS follow_up_question TEXT NULL;

COMMENT ON COLUMN charisma_snippets.follow_up_question IS
    'Pre-generated (or admin-edited) follow-up question for the Infinite Retention Loop. '
    'Charisma snippets get a deepening-energy question; stress snippets get a cognitive-load '
    'question. Served directly as the first AI message when the user clicks the snippet. '
    'NULL = not yet generated (falls back to dynamic LLM generation at query time).';
