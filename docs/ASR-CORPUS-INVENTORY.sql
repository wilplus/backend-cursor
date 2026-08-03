-- ASR golden set — what labeled data do we already have?
-- (run in Supabase → SQL Editor, paste the whole result back)
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
-- DEGRADES GRACEFULLY. Every section checks that its tables and columns
-- exist before touching them, so a partially-migrated environment returns
-- "NOT MIGRATED — run <file>" for that section instead of erroring out and
-- taking the other three with it. Section 0 reports the schema state first,
-- so a surprising number always has an explanation directly above it.
--
-- Depends on (section 0 tells you exactly which are missing):
--   migrations/add_coach_transcript_correction.sql   → section 1
--   migrations/add_snippet_transcripts.sql           → sections 1, 2, 4
--   migrations/add_user_transcript_edits.sql         → section 2
--   migrations/add_boundary_metrics.sql              → section 3 (optional)
--   migrations/add_slide_transcripts.sql             → section 3 (optional)
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
-- So sections 1 and 3 both need to come back non-zero. A large section 1
-- with an empty section 3 means we can measure accuracy and still cannot
-- answer the actual question.

DROP TABLE IF EXISTS asr_inventory;
CREATE TEMP TABLE asr_inventory (
    ord     int,
    section text,
    metric  text,
    value   text
);

DO $inv$
DECLARE
    has_drafts     bool := to_regclass('public.coach_snippet_drafts')  IS NOT NULL;
    has_charisma   bool := to_regclass('public.charisma_snippets')     IS NOT NULL;
    has_stress     bool := to_regclass('public.stress_snippets')       IS NOT NULL;
    has_edits      bool := to_regclass('public.user_transcript_edits') IS NOT NULL;
    has_sessions   bool := to_regclass('public.v2_sessions')           IS NOT NULL;
    has_recordings bool := to_regclass('public.recordings')            IS NOT NULL;

    has_corrected bool;
    has_snip_cols bool;
    has_boundary  bool;
    has_slidetx   bool;
    has_intake    bool;

    -- expression fragments, so a half-migrated env (only one snippet table)
    -- still counts what it has instead of refusing
    e_path text;
    e_text text;
    e_word text;
    e_dur  text;
    j_char text;
    j_str  text;

    FN_CORR constant text := 'migrations/add_coach_transcript_correction.sql';
    FN_SNIP constant text := 'migrations/add_snippet_transcripts.sql';
    FN_EDIT constant text := 'migrations/add_user_transcript_edits.sql';
BEGIN
    SELECT count(*) = 1 INTO has_corrected FROM information_schema.columns
     WHERE table_schema='public' AND table_name='coach_snippet_drafts'
       AND column_name='transcript_corrected';

    -- add_snippet_transcripts adds the same four columns to BOTH snippet
    -- tables; checking whichever one exists keeps a half-migrated env honest
    -- rather than half-counted.
    SELECT count(*) >= 4 INTO has_snip_cols FROM information_schema.columns
     WHERE table_schema='public'
       AND table_name = CASE WHEN has_charisma THEN 'charisma_snippets'
                             ELSE 'stress_snippets' END
       AND column_name IN ('transcript','language','words',
                           'transcribed_duration_ms');

    SELECT count(*) = 1 INTO has_boundary FROM information_schema.columns
     WHERE table_schema='public' AND table_name='v2_sessions'
       AND column_name='boundary_metrics';
    SELECT count(*) = 1 INTO has_slidetx FROM information_schema.columns
     WHERE table_schema='public' AND table_name='v2_sessions'
       AND column_name='slide_transcripts';
    SELECT count(*) = 1 INTO has_intake FROM information_schema.columns
     WHERE table_schema='public' AND table_name='v2_sessions'
       AND column_name='intake_context';

    -- ── 0. schema preflight ─────────────────────────────────────────────
    INSERT INTO asr_inventory VALUES
      (0,'0. preflight','a. coach_snippet_drafts',
         CASE WHEN has_drafts THEN 'present' ELSE 'MISSING TABLE' END),
      (0,'0. preflight','b.   .transcript_corrected',
         CASE WHEN has_corrected THEN 'present'
              ELSE 'NOT MIGRATED — run '||FN_CORR END),
      (0,'0. preflight','c. charisma_snippets',
         CASE WHEN has_charisma THEN 'present' ELSE 'MISSING TABLE' END),
      (0,'0. preflight','d. stress_snippets',
         CASE WHEN has_stress THEN 'present' ELSE 'MISSING TABLE' END),
      (0,'0. preflight','e.   snippet transcript/words cols',
         CASE WHEN has_snip_cols THEN 'present'
              ELSE 'NOT MIGRATED — run '||FN_SNIP END),
      (0,'0. preflight','f. user_transcript_edits',
         CASE WHEN has_edits THEN 'present'
              ELSE 'NOT MIGRATED — run '||FN_EDIT END),
      (0,'0. preflight','g. v2_sessions.intake_context',
         CASE WHEN has_intake THEN 'present' ELSE 'MISSING COLUMN' END),
      (0,'0. preflight','h. v2_sessions.boundary_metrics',
         CASE WHEN has_boundary THEN 'present' ELSE 'not migrated (optional)' END),
      (0,'0. preflight','i. v2_sessions.slide_transcripts',
         CASE WHEN has_slidetx THEN 'present' ELSE 'not migrated (optional)' END);

    -- Build the COALESCE/JOIN fragments once for sections 1 and 2.
    IF has_charisma AND has_stress THEN
        e_path := 'COALESCE(c.storage_path, s.storage_path)';
        e_text := 'COALESCE(c.transcript, s.transcript)';
        e_word := 'COALESCE(c.words, s.words)';
        e_dur  := 'COALESCE(c.duration_ms, s.duration_ms)';
    ELSIF has_charisma THEN
        e_path := 'c.storage_path'; e_text := 'c.transcript';
        e_word := 'c.words';        e_dur  := 'c.duration_ms';
    ELSE
        e_path := 's.storage_path'; e_text := 's.transcript';
        e_word := 's.words';        e_dur  := 's.duration_ms';
    END IF;
    j_char := CASE WHEN has_charisma
                   THEN 'LEFT JOIN charisma_snippets c ON c.id = d.snippet_id'
                   ELSE '' END;
    j_str  := CASE WHEN has_stress
                   THEN 'LEFT JOIN stress_snippets s ON s.id = d.snippet_id'
                   ELSE '' END;

    -- ── 1. COACH transcript corrections (the richest source) ────────────
    IF has_drafts AND has_corrected AND has_snip_cols
       AND (has_charisma OR has_stress) THEN
        EXECUTE format($q$
            INSERT INTO asr_inventory
            WITH corrections AS (
                SELECT d.session_id,
                       %s AS storage_path, %s AS asr_transcript,
                       %s AS asr_words,    %s AS duration_ms
                  FROM coach_snippet_drafts d %s %s
                 WHERE d.transcript_corrected IS NOT NULL
                   AND length(trim(d.transcript_corrected)) > 0
            ), agg AS (
                SELECT count(*) AS rows_total,
                       count(*) FILTER (WHERE storage_path   IS NOT NULL) AS usable,
                       count(*) FILTER (WHERE asr_transcript IS NOT NULL) AS asr_text,
                       count(*) FILTER (WHERE asr_words      IS NOT NULL) AS asr_words,
                       count(DISTINCT session_id)                         AS sessions,
                       round(sum(COALESCE(duration_ms,0))/60000.0, 1)     AS minutes
                  FROM corrections
            )
            SELECT 1, '1. coach corrections', m, v FROM agg,
              LATERAL (VALUES
                ('a. rows_total',                agg.rows_total::text),
                ('b. usable_for_wer (has audio)',agg.usable::text),
                ('c. with_asr_text',             agg.asr_text::text),
                ('d. with_asr_word_times',       agg.asr_words::text),
                ('e. distinct_sessions',         agg.sessions::text),
                ('f. total_minutes',             COALESCE(agg.minutes,0)::text)
              ) AS t(m,v) $q$,
            e_path, e_text, e_word, e_dur, j_char, j_str);
    ELSE
        INSERT INTO asr_inventory VALUES
          (1,'1. coach corrections','status',
             'SKIPPED — needs '||FN_CORR||' and '||FN_SNIP);
    END IF;

    -- ── 2. USER transcript edits ────────────────────────────────────────
    -- Snippet-targeted edits carry audio; chunk-targeted ones are deckless
    -- full-transcript chunks with no per-chunk audio, so they are split out.
    IF has_edits AND (has_charisma OR has_stress) THEN
        EXECUTE format($q$
            INSERT INTO asr_inventory
            WITH agg AS (
                SELECT count(*) AS rows_total,
                       count(*) FILTER (WHERE e.snippet_id  IS NOT NULL) AS snip,
                       count(*) FILTER (WHERE e.chunk_index IS NOT NULL) AS chunk,
                       count(*) FILTER (WHERE %s IS NOT NULL)            AS usable
                  FROM user_transcript_edits e %s %s
            )
            SELECT 2, '2. user edits', m, v FROM agg,
              LATERAL (VALUES
                ('a. rows_total',       agg.rows_total::text),
                ('b. snippet_targeted', agg.snip::text),
                ('c. chunk_targeted',   agg.chunk::text),
                ('d. usable_for_wer',   agg.usable::text)
              ) AS t(m,v) $q$,
            e_path,
            replace(j_char,'d.snippet_id','e.snippet_id'),
            replace(j_str, 'd.snippet_id','e.snippet_id'));
    ELSE
        INSERT INTO asr_inventory VALUES
          (2,'2. user edits','status','SKIPPED — needs '||FN_EDIT);
    END IF;

    -- ── 3. DECKED takes — the only source of slide-boundary truth ───────
    -- A take qualifies with >= 2 advances: one tap beyond the recording-start
    -- entry means at least one boundary a word can be on the wrong side of.
    -- Column is intake_context, NOT session_context — the latter is the API
    -- field name the routes emit (routes/v2_routes.py:9249).
    IF has_sessions AND has_intake THEN
        EXECUTE format($q$
            INSERT INTO asr_inventory
            WITH agg AS (
                SELECT count(*) AS total,
                       count(*) FILTER (
                         WHERE jsonb_typeof(intake_context->'slide_advances')='array'
                           AND jsonb_array_length(intake_context->'slide_advances')>=2
                       ) AS timeline,
                       count(*) FILTER (
                         WHERE jsonb_typeof(intake_context->'slides')='array'
                           AND jsonb_array_length(intake_context->'slides')>0
                       ) AS slides,
                       count(*) FILTER (
                         WHERE intake_context ? 'slide_clock_offset_ms'
                       ) AS offsets,
                       %s AS bmetrics, %s AS stx
                  FROM v2_sessions
            )
            SELECT 3, '3. decked takes', m, v FROM agg,
              LATERAL (VALUES
                ('a. sessions_total',             agg.total::text),
                ('b. with_slide_timeline (>=2)',  agg.timeline::text),
                ('c. with_slides',                agg.slides::text),
                ('d. with_measured_clock_offset', agg.offsets::text),
                ('e. with_boundary_metrics',      CASE WHEN agg.bmetrics < 0
                       THEN 'n/a (not migrated)' ELSE agg.bmetrics::text END),
                ('f. with_slide_transcripts',     CASE WHEN agg.stx < 0
                       THEN 'n/a (not migrated)' ELSE agg.stx::text END)
              ) AS t(m,v) $q$,
            CASE WHEN has_boundary
                 THEN 'count(*) FILTER (WHERE boundary_metrics IS NOT NULL)'
                 ELSE '-1::bigint' END,
            CASE WHEN has_slidetx
                 THEN 'count(*) FILTER (WHERE slide_transcripts IS NOT NULL)'
                 ELSE '-1::bigint' END);
    ELSE
        INSERT INTO asr_inventory VALUES
          (3,'3. decked takes','status','SKIPPED — no v2_sessions.intake_context');
    END IF;

    -- ── 4. LANGUAGE spread (our only stored proxy for accent) ───────────
    -- language is NOT accent: a heavily-accented L2 English take is
    -- language='en' and indistinguishable here from a native one. This
    -- bounds the NON-ENGLISH strata only; the L2-accent strata still need a
    -- human to tag them.
    IF has_snip_cols AND (has_charisma OR has_stress) THEN
        EXECUTE format($q$
            INSERT INTO asr_inventory
            SELECT 4, '4. language spread',
                   COALESCE(language,'(null)'), count(*)::text
              FROM ( %s ) t
             GROUP BY language ORDER BY count(*) DESC LIMIT 15 $q$,
            CASE
              WHEN has_charisma AND has_stress THEN
                'SELECT language FROM charisma_snippets WHERE transcript IS NOT NULL
                 UNION ALL
                 SELECT language FROM stress_snippets   WHERE transcript IS NOT NULL'
              WHEN has_charisma THEN
                'SELECT language FROM charisma_snippets WHERE transcript IS NOT NULL'
              ELSE
                'SELECT language FROM stress_snippets   WHERE transcript IS NOT NULL'
            END);
    ELSE
        INSERT INTO asr_inventory VALUES
          (4,'4. language spread','status','SKIPPED — needs '||FN_SNIP);
    END IF;

    -- ── 5. Where does full-take audio live? ─────────────────────────────
    -- Column names differ across the R2 migration, so this asks the catalog
    -- instead of guessing. Whatever it lists tells me how to pull audio for
    -- the decked takes in section 3.
    IF has_recordings THEN
        INSERT INTO asr_inventory
        SELECT 5,'5. recordings audio cols', column_name, data_type
          FROM information_schema.columns
         WHERE table_schema='public' AND table_name='recordings'
           AND (column_name ILIKE '%audio%' OR column_name ILIKE '%storage%'
             OR column_name ILIKE '%url%'   OR column_name ILIKE '%path%'
             OR column_name ILIKE '%key%');
        IF NOT EXISTS (SELECT 1 FROM asr_inventory WHERE ord = 5) THEN
            INSERT INTO asr_inventory VALUES
              (5,'5. recordings audio cols','(none matched)',
                 'no audio/storage/url/path/key column — say so and I will widen the probe');
        END IF;
    ELSE
        INSERT INTO asr_inventory VALUES
          (5,'5. recordings audio cols','status','MISSING TABLE recordings');
    END IF;
END
$inv$;

SELECT section, metric, value FROM asr_inventory ORDER BY ord, metric;
