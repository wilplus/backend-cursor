-- Confident Voice micro-practice (MVP).
--
-- A diagnostic exercise is NOT a blog post.  A published journal entry only
-- becomes eligible after an administrator creates/enables an explicit row in
-- diagnostic_exercise.  Practice sessions keep machine, owner and coach
-- provenance in separate columns and never write presentation text/style.

CREATE TABLE IF NOT EXISTS public.diagnostic_exercise (
    exercise_id                   TEXT PRIMARY KEY,
    journal_post_id               UUID NULL
                                  REFERENCES public.journal_post(id)
                                  ON DELETE SET NULL,
    title                         TEXT NOT NULL,
    instruction                   TEXT NOT NULL,
    introduction_copy             TEXT NOT NULL,
    confident_introduction_copy   TEXT NULL,
    explanation_video_url         TEXT NULL,
    acoustic_problem_tags         TEXT[] NOT NULL DEFAULT '{}',
    supported_confidence_patterns TEXT[] NOT NULL DEFAULT '{}',
    matching_criteria              JSONB NOT NULL DEFAULT '{}'::jsonb,
    exclusions                     JSONB NOT NULL DEFAULT '{}'::jsonb,
    active                         BOOLEAN NOT NULL DEFAULT FALSE,
    version                        INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
    created_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT diagnostic_exercise_active_assets_check CHECK (
        active = FALSE OR
        (journal_post_id IS NOT NULL AND explanation_video_url IS NOT NULL)
    )
);

INSERT INTO public.diagnostic_exercise (
    exercise_id, title, instruction, introduction_copy,
    confident_introduction_copy, acoustic_problem_tags,
    supported_confidence_patterns, matching_criteria, exclusions, active,
    version
) VALUES (
    'hear-every-word-v1',
    'Hear every word',
    'Read the same text again, slightly more slowly. Give every word enough space to be heard clearly without forcing your voice.',
    'You’re close to a confident delivery here. Your pace is carrying energy, but some words become compressed. Try the same text again while giving each word enough space.',
    'Your original already carries confident energy. This is an optional refinement: try the same text again while giving each word enough space.',
    ARRAY['rushing', 'word_compression', 'ending_compression'],
    ARRAY['near_confident', 'confident', 'low_confidence_rushing_dominant'],
    '{"requires_multiple_acoustic_signals":true,"max_per_take":1}'::jsonb,
    '{"exclude_noise":true,"exclude_semantic_or_structural_issue":true,"exclude_weak_evidence":true}'::jsonb,
    FALSE,
    1
) ON CONFLICT (exercise_id) DO NOTHING;

CREATE TABLE IF NOT EXISTS public.confident_voice_practice (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_user_id               UUID NOT NULL REFERENCES auth.users(id)
                                ON DELETE CASCADE,
    project_id                  UUID NOT NULL,
    take_session_id             UUID NOT NULL REFERENCES public.v2_sessions(id)
                                ON DELETE CASCADE,
    snippet_id                  UUID NOT NULL REFERENCES public.snippets(id)
                                ON DELETE CASCADE,
    exercise_id                 TEXT NOT NULL
                                REFERENCES public.diagnostic_exercise(exercise_id),
    exercise_version            INTEGER NOT NULL,
    exercise_snapshot           JSONB NOT NULL,
    slide_index                 INTEGER NOT NULL CHECK (slide_index >= 0),
    paragraph_index             INTEGER NOT NULL CHECK (paragraph_index >= 0),
    evidence_span               JSONB NOT NULL,
    exact_passage               TEXT NOT NULL,
    original_audio_ref          TEXT NOT NULL,
    original_start_offset_ms    INTEGER NOT NULL DEFAULT 0,
    original_duration_ms        INTEGER NOT NULL,
    machine_assessment          JSONB NOT NULL,
    acoustic_evidence           JSONB NOT NULL,
    original_user_answer        TEXT NULL
                                CHECK (original_user_answer IN ('yes', 'no')),
    status                      TEXT NOT NULL DEFAULT 'open'
                                CHECK (status IN ('open', 'completed', 'dismissed')),
    selected_attempt_id         UUID NULL,
    final_user_answer           TEXT NULL
                                CHECK (final_user_answer IN ('yes', 'no')),
    professional_coach_decision TEXT NULL
                                CHECK (professional_coach_decision IN ('yes', 'no', 'refine')),
    coach_selected_exercise_id  TEXT NULL
                                REFERENCES public.diagnostic_exercise(exercise_id),
    coach_custom_exercise       JSONB NULL,
    coach_explanation_video_url TEXT NULL,
    coach_shared_exercise       JSONB NULL,
    coach_shared_by             UUID NULL REFERENCES auth.users(id)
                                ON DELETE SET NULL,
    coach_shared_at             TIMESTAMPTZ NULL,
    chat_emitted_at             TIMESTAMPTZ NULL,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at                   TIMESTAMPTZ NULL,
    CONSTRAINT confident_voice_practice_one_per_take UNIQUE (take_session_id),
    CONSTRAINT confident_voice_practice_moment_once UNIQUE (snippet_id, exercise_id)
);

CREATE TABLE IF NOT EXISTS public.confident_voice_practice_attempt (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    practice_id           UUID NOT NULL
                          REFERENCES public.confident_voice_practice(id)
                          ON DELETE CASCADE,
    attempt_index         INTEGER NOT NULL CHECK (attempt_index BETWEEN 1 AND 3),
    storage_path          TEXT NOT NULL,
    audio_ref             TEXT NOT NULL,
    mime_type             TEXT NOT NULL,
    duration_ms           INTEGER NOT NULL CHECK (duration_ms > 0),
    transcript            TEXT NOT NULL,
    transcript_alignment  JSONB NOT NULL,
    acoustic_metrics      JSONB NOT NULL,
    comparison            JSONB NOT NULL,
    assessment_key        TEXT NOT NULL,
    machine_confidence_decision TEXT NULL
                          CHECK (machine_confidence_decision IN ('yes', 'no')),
    coach_confidence_decision TEXT NULL
                          CHECK (coach_confidence_decision IN ('yes', 'no')),
    coach_confidence_decided_by UUID NULL REFERENCES auth.users(id)
                          ON DELETE SET NULL,
    coach_confidence_decided_at TIMESTAMPTZ NULL,
    is_strongest          BOOLEAN NOT NULL DEFAULT FALSE,
    kept                  BOOLEAN NOT NULL DEFAULT FALSE,
    user_answer           TEXT NULL CHECK (user_answer IN ('yes', 'no')),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT confident_voice_practice_attempt_order UNIQUE (practice_id, attempt_index)
);

ALTER TABLE public.confident_voice_practice_attempt
    ADD COLUMN IF NOT EXISTS machine_confidence_decision TEXT NULL
    CHECK (machine_confidence_decision IN ('yes', 'no'));
ALTER TABLE public.confident_voice_practice_attempt
    ADD COLUMN IF NOT EXISTS coach_confidence_decision TEXT NULL
    CHECK (coach_confidence_decision IN ('yes', 'no'));
ALTER TABLE public.confident_voice_practice_attempt
    ADD COLUMN IF NOT EXISTS coach_confidence_decided_by UUID NULL
    REFERENCES auth.users(id) ON DELETE SET NULL;
ALTER TABLE public.confident_voice_practice_attempt
    ADD COLUMN IF NOT EXISTS coach_confidence_decided_at TIMESTAMPTZ NULL;

-- Practice recordings have their own three-signal provenance.  Keeping one
-- never writes this table; only the later reconciliation after an explicit
-- coach judgment can do so.  It is separate from voice_album because those
-- rows are keyed by original snippets and an attempt is a new recording.
CREATE TABLE IF NOT EXISTS public.voice_album_practice (
    arc_id               UUID NOT NULL,
    practice_attempt_id  UUID NOT NULL
                         REFERENCES public.confident_voice_practice_attempt(id)
                         ON DELETE CASCADE,
    take_session_id      TEXT NULL,
    slide_index          INTEGER NULL,
    entered_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (arc_id, practice_attempt_id)
);

CREATE INDEX IF NOT EXISTS confident_voice_practice_owner_idx
    ON public.confident_voice_practice (owner_user_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS confident_voice_practice_coach_idx
    ON public.confident_voice_practice (take_session_id, status);
CREATE INDEX IF NOT EXISTS confident_voice_practice_attempt_practice_idx
    ON public.confident_voice_practice_attempt (practice_id, attempt_index);

ALTER TABLE public.diagnostic_exercise ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.confident_voice_practice ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.confident_voice_practice_attempt ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.voice_album_practice ENABLE ROW LEVEL SECURITY;

GRANT ALL ON TABLE public.diagnostic_exercise TO service_role;
GRANT ALL ON TABLE public.confident_voice_practice TO service_role;
GRANT ALL ON TABLE public.confident_voice_practice_attempt TO service_role;
GRANT ALL ON TABLE public.voice_album_practice TO service_role;

COMMENT ON TABLE public.diagnostic_exercise IS
    'Admin-curated mapping from a reviewed journal/video asset to a narrow acoustic diagnostic pattern.';
COMMENT ON TABLE public.confident_voice_practice IS
    'Optional in-modal Confident Voice practice; machine, owner, and coach judgments remain separate.';
COMMENT ON TABLE public.confident_voice_practice_attempt IS
    'Up to three same-passage audio attempts with separate machine, owner, and coach confidence decisions; never presentation edits.';
COMMENT ON TABLE public.voice_album_practice IS
    'Selected practice recordings admitted only when their own machine, owner, and professional-coach decisions all say yes.';
