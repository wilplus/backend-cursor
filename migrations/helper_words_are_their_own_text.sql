-- The helper words are their own text (contract 14, founder 2026-09-25).
--
-- A Take now rewrites each Paragraph from what was said, and the locked helper
-- words persist through that rewrite until the user picks new ones. The phrase
-- therefore can no longer be required to sit at a character position inside
-- the Paragraph: the speaker may have said it differently this Take.
--
-- `root_start` / `root_end` stay as an optional render hint (both set, or
-- both NULL). Every existing row satisfies the looser rule, so this only
-- widens what may be written. Idempotent: drop-if-exists, then add.

ALTER TABLE public.ideal_text_part
    DROP CONSTRAINT IF EXISTS ideal_text_part_root_span;
ALTER TABLE public.ideal_text_part
    ADD CONSTRAINT ideal_text_part_root_span CHECK (
        (root_phrase IS NULL AND root_start IS NULL AND root_end IS NULL
         AND root_selected_at IS NULL)
        OR
        (root_phrase IS NOT NULL AND length(root_phrase) > 0
         AND root_selected_at IS NOT NULL
         AND (
             (root_start IS NULL AND root_end IS NULL)
             OR (root_start IS NOT NULL AND root_start >= 0
                 AND root_end IS NOT NULL AND root_end > root_start)
         ))
    );
