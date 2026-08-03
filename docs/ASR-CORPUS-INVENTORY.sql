-- ASR golden set — what labeled data do we already have?
-- (run in Supabase → SQL Editor, paste the output back)
--
-- Answers Ask #0 in evals/asr/README.md: is building the corpus a
-- "record 40 takes" job or a "label the 10 gaps" job? Every row of human
-- transcript correction we already hold is ground truth on REAL willab audio
-- in real conditions — a better sample than anything we could stage, because
-- it is drawn from the distribution the product actually sees.
--
-- Read-only. Nothing here is user-facing (AC-9); this is an internal
-- engineering read, same as docs/F1-BOUNDARY-REPORT.sql.
--
-- Prerequisites: migrations/add_snippet_transcripts.sql (transcript/language/
-- words on both snippet tables) and add_coach_transcript_correction.sql.
-- If section 1 errors on a missing column, that migration has not run in this
-- environment — which is itself part of the answer.
--
-- THE ONE THING TO KNOW BEFORE READING THE NUMBERS: snippets and takes
-- answer DIFFERENT questions and are not interchangeable.
--
--   * A SNIPPET is a ~3s clip with its own audio (storage_path). A corrected
--     snippet transcript gives WER ground truth and accent coverage — cheap,
--     plentiful, and exactly what the accent bake-off needs. It does NOT
--     give slide-boundary truth: a 3s clip rarely spans a slide tap.
--   * A DECKED TAKE (full recording + slide_advances) is the only thing that
--     can produce SLIDE-BUCKET AGREEMENT — the metric that decides the
--     migration.
--
-- So section 1 and section 3 both need to come back non-zero. A large
-- section 1 with an empty section 3 means we can measure accuracy and still
-- cannot answer the actual question.


-- ── 1. COACH transcript corrections (the richest source) ─────────────────
-- coach_snippet_drafts.transcript_corrected = a coach rewrote the ASR output.
-- Joined to both snippet tables since snippet_id may point at either.
WITH corrections AS (
    SELECT d.session_id,
           d.snippet_id,
           d.transcript_corrected,
           COALESCE(c.storage_path, s.storage_path)     AS storage_path,
           COALESCE(c.transcript,   s.transcript)       AS asr_transcript,
           COALESCE(c.language,     s.language)         AS language,
           COALESCE(c.words,        s.words)            AS asr_words,
           COALESCE(c.duration_ms,  s.duration_ms)      AS duration_ms
      FROM coach_snippet_drafts d
      LEFT JOIN charisma_snippets c ON c.id = d.snippet_id
      LEFT JOIN stress_snippets   s ON s.id = d.snippet_id
     WHERE d.transcript_corrected IS NOT NULL
       AND length(trim(d.transcript_corrected)) > 0
)
SELECT
    '1. coach corrections'                                   AS section,
    count(*)                                                 AS rows_total,
    -- with_audio IS the usable-for-WER count: the CTE already requires a
    -- non-empty human transcript, so audio is the only other thing needed.
    count(*) FILTER (WHERE storage_path IS NOT NULL)         AS usable_for_wer,
    count(*) FILTER (WHERE asr_transcript IS NOT NULL)       AS with_asr_text,
    count(*) FILTER (WHERE asr_words IS NOT NULL)            AS with_asr_word_times,
    count(DISTINCT session_id)                               AS distinct_sessions,
    round(sum(COALESCE(duration_ms, 0)) / 60000.0, 1)        AS total_minutes
  FROM corrections;


-- ── 2. USER transcript edits (the user fixed their own readout) ──────────
-- Snippet-targeted edits carry audio; chunk-targeted ones are deckless
-- full-transcript chunks with no per-chunk audio, so they are counted apart.
SELECT
    '2. user edits'                                          AS section,
    count(*)                                                 AS rows_total,
    count(*) FILTER (WHERE e.snippet_id IS NOT NULL)         AS snippet_targeted,
    count(*) FILTER (WHERE e.chunk_index IS NOT NULL)        AS chunk_targeted,
    count(*) FILTER (WHERE c.storage_path IS NOT NULL
                        OR s.storage_path IS NOT NULL)       AS usable_for_wer
  FROM user_transcript_edits e
  LEFT JOIN charisma_snippets c ON c.id = e.snippet_id
  LEFT JOIN stress_snippets   s ON s.id = e.snippet_id;


-- ── 3. DECKED takes — the only source of slide-boundary truth ────────────
-- A take qualifies when it has a real tap timeline: >= 2 advances (one tap
-- beyond the recording-start entry) means at least one boundary a word can
-- be on the wrong side of.
--
-- The column is intake_context, NOT session_context: the latter is the API
-- field name the routes emit, the former is where it is actually stored
-- (routes/v2_routes.py:9249 maps one to the other).
SELECT
    '3. decked takes'                                        AS section,
    count(*)                                                 AS sessions_total,
    count(*) FILTER (
        WHERE jsonb_typeof(intake_context->'slide_advances') = 'array'
          AND jsonb_array_length(intake_context->'slide_advances') >= 2
    )                                                        AS with_slide_timeline,
    count(*) FILTER (
        WHERE jsonb_typeof(intake_context->'slides') = 'array'
          AND jsonb_array_length(intake_context->'slides') > 0
    )                                                        AS with_slides,
    count(*) FILTER (
        WHERE intake_context ? 'slide_clock_offset_ms'
    )                                                        AS with_measured_clock_offset,
    count(*) FILTER (WHERE boundary_metrics IS NOT NULL)      AS with_boundary_metrics,
    count(*) FILTER (WHERE slide_transcripts IS NOT NULL)     AS with_slide_transcripts
  FROM v2_sessions;


-- ── 4. LANGUAGE spread (our only stored proxy for accent) ────────────────
-- NOTE: language is not accent. A heavily-accented L2 English take is
-- language='en' and indistinguishable here from a native one. This bounds
-- the NON-ENGLISH strata only; the L2-accent strata still need a human to
-- tag them (Ask #1).
SELECT
    '4. language spread'                                     AS section,
    COALESCE(language, '(null)')                             AS language,
    count(*)                                                 AS snippets
  FROM (
      SELECT language FROM charisma_snippets WHERE transcript IS NOT NULL
      UNION ALL
      SELECT language FROM stress_snippets   WHERE transcript IS NOT NULL
  ) t
 GROUP BY 1, 2
 ORDER BY snippets DESC
 LIMIT 15;


-- ── 5. Does the recordings table still point at retained audio? ──────────
-- Column names differ across the R2 migration, so this asks the catalog
-- instead of guessing. Send back whatever it lists — that tells me how to
-- pull full-take audio for the decked takes in section 3.
SELECT
    '5. recordings audio columns'                            AS section,
    column_name,
    data_type
  FROM information_schema.columns
 WHERE table_schema = 'public'
   AND table_name   = 'recordings'
   AND (column_name ILIKE '%audio%'
     OR column_name ILIKE '%storage%'
     OR column_name ILIKE '%url%'
     OR column_name ILIKE '%path%'
     OR column_name ILIKE '%key%')
 ORDER BY column_name;
