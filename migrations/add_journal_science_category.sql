-- Journal: add the 'science' category + seed the two research-paper posts
-- (founder 2026-07-30 — /science is consolidated into the blog; the page is
-- deleted on the FE and permanently redirected to /blog).
--
-- Run manually in Supabase, like every migration in this repo. Idempotent:
-- the CHECK is drop+re-add (the amendment path add_journal_posts.sql
-- anticipated — a CHECK can be widened with a plain ALTER, unlike a PG
-- enum), and the seeds are ON CONFLICT (slug) DO NOTHING against the
-- table's UNIQUE slug key, so a re-run never duplicates or overwrites a
-- post the founder has since edited.
--
-- Keep in lockstep with services/journal.py CATEGORIES and the FE's
-- JOURNAL_CATEGORIES in services/api/journal.ts.

ALTER TABLE journal_post
    DROP CONSTRAINT IF EXISTS journal_post_category_check;

ALTER TABLE journal_post
    ADD CONSTRAINT journal_post_category_check
    CHECK (category IN ('physiology', 'physical_exercise', 'philosophy',
                        'voice', 'language', 'science', 'others'));

-- Document the body's token extension where a DBA will look for it. A
-- COMMENT is metadata only — no data or constraint change, safe to re-run.
COMMENT ON COLUMN journal_post.body IS
    'Plain text; blank line = new paragraph. No HTML/Markdown. The FE '
    'additionally renders two line-level tokens: [image: url | alt] and '
    '[file: url | label] (BODY TOKEN SPEC in the FE services/api/journal.ts). '
    'The backend treats the body as opaque text.';

-- Seed the two papers that lived on the deleted /science page. Titles and
-- descriptions copied verbatim from src/app/science/page.tsx PAPERS; the
-- bodies use the [file: …] token pointing at the PDFs, which stay in the
-- FE's public/papers/ (site-relative URLs are allowed by the token spec).
-- published_at is the consolidation date; sort_order 0 like every other row.
INSERT INTO journal_post
    (slug, title, excerpt, category, body,
     author_name, status, published_at, read_time_min, cover_kind)
VALUES
    (
        'ebcp-emotion-based-collaborative-prompting',
        'EBCP — Emotion-Based Collaborative Prompting',
        'Our framework for using small cognitive-load primes to surface a speaker''s authentic baseline before any training interventions.',
        'science',
        E'Our framework for using small cognitive-load primes to surface a speaker''s authentic baseline before any training interventions.\n\n[file: /papers/EBCP.pdf | Read the paper (PDF)]',
        'Willpower Lab',
        'published',
        '2026-07-30T00:00:00Z',
        1,
        'image'
    ),
    (
        'necp-naming-emotions-collaborative-prompting',
        'NECP — Naming Emotions Collaborative Prompting',
        'How naming emotions in the corporate workplace reduces emotional bias in competence assessments and provides a scalable method for measuring learnability.',
        'science',
        E'How naming emotions in the corporate workplace reduces emotional bias in competence assessments and provides a scalable method for measuring learnability.\n\n[file: /papers/naming-emotions-paper.pdf | Read the paper (PDF)]',
        'Willpower Lab',
        'published',
        '2026-07-30T00:00:00Z',
        1,
        'image'
    )
ON CONFLICT (slug) DO NOTHING;
