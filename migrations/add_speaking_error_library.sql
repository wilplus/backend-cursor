-- THE SPEAKING ERROR LIBRARY (founder 2026-09-15).
--
-- The goal this serves, in the founder's words: "we have the library of the
-- errors so we can recognise them and we have the exercise matching algorithm
-- and they should go hand in hand."
--
-- Until now the problem vocabulary lived in two half-places: three bare
-- strings inside `diagnostic_exercise.acoustic_problem_tags`, written by an
-- administrator, and a mapping from acoustic signals to those same strings
-- inside services/confident_voice_practice.py. Nothing said what any of them
-- MEANT, and nothing stopped the two halves drifting apart.
--
-- WHY THIS IS A TABLE AND NOT A PYTHON ENUM. Naming an error is a coach's job
-- and must not require a deploy; DETECTING one is code and cannot happen
-- without one. Those are different rates of change, so they get different
-- homes — and `status` is the seam between them:
--
--     observed  — a human named this pattern and wrote down what it is.
--                 No code can find it yet. This is the engineering backlog,
--                 visible to both sides.
--     detected  — code can find it in audio. Only these may route an
--                 exercise.
--
-- A `detected` row MUST name its detector. That is the CONSTRUCT fence made
-- structural rather than aspirational: a measured state with no written
-- operational definition, and no named thing doing the measuring, is exactly
-- the defect that retired "charisma" on 2026-08-13. The same trick as
-- `diagnostic_exercise`'s active-assets CHECK — the database refuses the
-- claim, so nobody has to remember the rule.
--
-- THE ID SHAPE IS ALSO LOAD-BEARING. Matching is string overlap between this
-- vocabulary and an exercise's tags. `word compression` and `word_compression`
-- would not match, would raise no error, and would simply route nothing — a
-- silent failure with no signal. The regex makes that unrepresentable.
--
-- PROVENANCE (L3). A row here is a NAME and a DEFINITION. It is never evidence
-- that the pattern occurred in any particular recording. A coach naming a
-- pattern is a hypothesis; a detector firing on a clip is a detector verdict.
-- `observed_by` records who asserted the name, and nothing in this table may
-- be read as a machine prediction, an owner answer, or a coach judgement about
-- a specific take.

CREATE TABLE IF NOT EXISTS public.speaking_error (
    error_id      TEXT PRIMARY KEY,
    label         TEXT NOT NULL,
    -- What is measured, in terms a detector could be written or checked
    -- against. Not a description of the fix.
    definition    TEXT NOT NULL,
    -- The single question this state answers. One thing, never two.
    asks          TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'observed'
                  CHECK (status IN ('observed', 'detected')),
    -- The signal name(s) in services/confident_voice_practice.py that detect
    -- it. Required for 'detected'; meaningless for 'observed'.
    detector_ref  TEXT NULL,
    -- Who named it, for an entry that arrived from observation.
    observed_by   TEXT NULL,
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT speaking_error_detected_needs_detector CHECK (
        status <> 'detected' OR detector_ref IS NOT NULL
    ),
    CONSTRAINT speaking_error_id_shape CHECK (
        error_id ~ '^[a-z][a-z0-9_]{1,62}$'
    )
);

-- The three names the catalogue and the matcher already speak. Their
-- definitions are written FROM the thresholds that implement them, not from
-- an intention — a definition that does not describe what the code actually
-- measures is decoration, and would leave the fence no better off than the
-- unwritten one it replaces.
INSERT INTO public.speaking_error (
    error_id, label, definition, asks, status, detector_ref
) VALUES
(
    'rushing',
    'Rushing',
    'The passage leaves too little silence between its words for a listener '
    'to keep up. Measured on the aligned word timings as pauses occupying '
    'under 8% of the clip (pause_ratio < 0.08), or pause regularity under '
    '0.5. Eligibility additionally requires pace above the speaker''s own '
    'session median, so this describes density, not speed alone.',
    'Did this passage give the listener room to follow it?',
    'detected',
    'insufficient_pauses,irregular_rushed_pacing'
),
(
    'word_compression',
    'Word compression',
    'Individual words are given less time and separation than a listener '
    'needs to resolve them. Measured as a median inter-word gap under 0.07s '
    'with at least half the gaps that tight, or words occupying more than '
    '78% of the clip, or word recognition confidence under 0.82.',
    'Were the words given enough time to be heard as separate words?',
    'detected',
    'reduced_word_separation,dense_articulation,reduced_intelligibility'
),
(
    'ending_compression',
    'Ending compression',
    'The end of the passage is given materially less time per word than the '
    'passage as a whole. Measured as the mean duration of the closing words '
    'falling below 78% of the clip''s mean word duration '
    '(ending_duration_ratio < 0.78).',
    'Did the speaker shorten the end of this passage?',
    'detected',
    'compressed_ending'
)
ON CONFLICT (error_id) DO NOTHING;

ALTER TABLE public.speaking_error ENABLE ROW LEVEL SECURITY;
GRANT ALL ON TABLE public.speaking_error TO service_role;
