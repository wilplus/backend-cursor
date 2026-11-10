-- a_person_can_teach_and_start_ai_models (the model launchpad's first
-- tables; founder, the Claude Code chat, 5 to 9 November 2026: N520, N523,
-- N526, N528, N531, N563, N566, N570, N577, N581; the locked prototype
-- docs/design/model-launchpad-2026-11-09/, version 8).
--
-- The rules live in services/model_launchpad.py, which has no storage of
-- its own; these tables only hold what it reads.
--
--   ai_models           One row per model, like a repository (N526 item 1):
--                       its name, its owner (whoever started it; NULL once
--                       the owner's account is erased, so a public model
--                       others teach outlives it, N528 item 11), Public or
--                       Private (N528 item 5), its stage (draft, learning,
--                       ready, archived; Archive deletes nothing), its field
--                       and description, where a draft stopped (N566 item
--                       2), its recipe card (N563 item 2, N570: the input,
--                       the steps, the teachers' question, the scale, the
--                       list) and its jars' targets (N528 item 8, N566 item
--                       5, N582 item 5).
--   ai_model_teachers   Who teaches a model and how: owner or contributor,
--                       when they came through the door ("This is my
--                       field", N528 item 2), the quiet trust check's state
--                       (learning, counts, stopped; N520 item 8) and when
--                       they were told it counts (once), and Pause (N563
--                       item 1). The rater model's estimate is kept for the
--                       median it is compared with and is never shown or
--                       returned (Never 1, N526 item 3).
--   ai_model_examples   What a model learns from (N563 item 4): its source
--                       (WillpowerLab Takes with the speaker's training yes,
--                       the founder's checked upload, a business's question,
--                       or a teacher's own), private (a company's own data,
--                       N563 item 3), the speaker it came from (so erasure
--                       and a withdrawn training yes reach it), who added
--                       it, a hidden known answer (N520 item 12) and whether
--                       it is in the sealed final exam. The machine's read
--                       sits in its own column and is never sent to a
--                       teacher before they answer (Never 2).
--   ai_model_answers    One teacher's answer to one step of one example for
--                       one model; whether it counted (N523 item 2). An
--                       answer that counts for two models (N566 item 7) is
--                       two rows, one per model, written together.
--   ai_model_invites    An invite to teach or to set up a model, kept in the
--                       chat after "Not now" (N528 item 3).
--
-- Read and written by the backend (service role) only; nothing for anon or
-- authenticated. RLS on, no policies. No environment variable needed. One
-- ring row, ai_models at ring 6, with its first audit entry.
-- Account erasure: services/data_purge_registry.py deletes a person's
-- teacher rows, answers, invites and the examples that came from their
-- Takes or that they added, and sets ai_models.owner_id to NULL.
--
-- Idempotent and additive: CREATE ... IF NOT EXISTS; nothing is dropped and
-- no existing row is written, rewritten or removed. One transaction.
--
-- Rollback (a new forward migration): leave the tables; dropping them is a
-- separate, previewed retention operation.

BEGIN;

CREATE TABLE IF NOT EXISTS public.ai_models (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    name         TEXT        NOT NULL,
    owner_id     UUID        NULL REFERENCES auth.users(id) ON DELETE SET NULL,
    owner_name   TEXT        NULL,
    visibility   TEXT        NOT NULL DEFAULT 'private',
    status       TEXT        NOT NULL DEFAULT 'draft',
    field        TEXT        NULL,
    description  TEXT        NULL,
    draft_step   TEXT        NULL,
    recipe       JSONB       NOT NULL DEFAULT '{}'::jsonb,
    targets      JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ai_models_name_len CHECK (char_length(btrim(name)) BETWEEN 1 AND 80),
    CONSTRAINT ai_models_owner_name_len CHECK (owner_name IS NULL OR char_length(owner_name) <= 80),
    CONSTRAINT ai_models_visibility CHECK (visibility IN ('public', 'private')),
    CONSTRAINT ai_models_status CHECK (status IN ('draft', 'learning', 'ready', 'archived')),
    CONSTRAINT ai_models_field_len CHECK (field IS NULL OR char_length(field) <= 120),
    CONSTRAINT ai_models_description_len CHECK (description IS NULL OR char_length(description) <= 600),
    CONSTRAINT ai_models_recipe_object CHECK (jsonb_typeof(recipe) = 'object'),
    CONSTRAINT ai_models_targets_object CHECK (jsonb_typeof(targets) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_ai_models_owner ON public.ai_models (owner_id);
CREATE INDEX IF NOT EXISTS idx_ai_models_listed ON public.ai_models (status, visibility);

CREATE TABLE IF NOT EXISTS public.ai_model_teachers (
    model_id          UUID        NOT NULL REFERENCES public.ai_models(id) ON DELETE CASCADE,
    user_id           UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    role              TEXT        NOT NULL DEFAULT 'contributor',
    company_line      TEXT        NULL,
    door_accepted_at  TIMESTAMPTZ NULL,
    trust_status      TEXT        NOT NULL DEFAULT 'learning',
    trust_kappa       DOUBLE PRECISION NULL,
    trust_changed_at  TIMESTAMPTZ NULL,
    trust_told_at     TIMESTAMPTZ NULL,
    paused_at         TIMESTAMPTZ NULL,
    joined_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (model_id, user_id),
    CONSTRAINT ai_model_teachers_role CHECK (role IN ('owner', 'contributor')),
    CONSTRAINT ai_model_teachers_trust CHECK (trust_status IN ('learning', 'counts', 'stopped')),
    CONSTRAINT ai_model_teachers_company_len CHECK (company_line IS NULL OR char_length(company_line) <= 120)
);

CREATE INDEX IF NOT EXISTS idx_ai_model_teachers_user ON public.ai_model_teachers (user_id);

CREATE TABLE IF NOT EXISTS public.ai_model_examples (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id       UUID        NOT NULL REFERENCES public.ai_models(id) ON DELETE CASCADE,
    source         TEXT        NOT NULL,
    private        BOOLEAN     NOT NULL DEFAULT false,
    speaker_id     UUID        NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    take_id        UUID        NULL,  -- no FK by design; Takes live elsewhere
    snippet_id     TEXT        NULL,
    added_by       UUID        NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    kind           TEXT        NULL,
    content        JSONB       NOT NULL DEFAULT '{}'::jsonb,
    known_answer   TEXT        NULL,
    in_exam        BOOLEAN     NOT NULL DEFAULT false,
    machine        JSONB       NULL,
    sureness       DOUBLE PRECISION NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ai_model_examples_source CHECK (source IN ('takes', 'upload', 'business', 'teacher')),
    CONSTRAINT ai_model_examples_teacher_has_adder CHECK (source <> 'teacher' OR added_by IS NOT NULL),
    CONSTRAINT ai_model_examples_takes_have_speaker CHECK (source <> 'takes' OR speaker_id IS NOT NULL),
    CONSTRAINT ai_model_examples_content_object CHECK (jsonb_typeof(content) = 'object'),
    CONSTRAINT ai_model_examples_sureness CHECK (sureness IS NULL OR (sureness >= 0 AND sureness <= 1)),
    CONSTRAINT ai_model_examples_known_not_exam CHECK (NOT (in_exam IS TRUE AND known_answer IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS idx_ai_model_examples_model ON public.ai_model_examples (model_id, created_at);
CREATE INDEX IF NOT EXISTS idx_ai_model_examples_speaker ON public.ai_model_examples (speaker_id)
    WHERE speaker_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ai_model_examples_added_by ON public.ai_model_examples (added_by)
    WHERE added_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ai_model_examples_snippet ON public.ai_model_examples (snippet_id)
    WHERE snippet_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.ai_model_answers (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    example_id   UUID        NOT NULL REFERENCES public.ai_model_examples(id) ON DELETE CASCADE,
    model_id     UUID        NOT NULL REFERENCES public.ai_models(id) ON DELETE CASCADE,
    teacher_id   UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    step         TEXT        NOT NULL DEFAULT 'rate',
    answer       TEXT        NULL,
    counted      BOOLEAN     NOT NULL DEFAULT false,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ai_model_answers_step CHECK (step IN ('rate', 'pick', 'words')),
    CONSTRAINT ai_model_answers_len CHECK (answer IS NULL OR char_length(answer) <= 4000),
    CONSTRAINT ai_model_answers_once UNIQUE (example_id, model_id, teacher_id, step)
);

CREATE INDEX IF NOT EXISTS idx_ai_model_answers_teacher ON public.ai_model_answers (teacher_id, created_at);
CREATE INDEX IF NOT EXISTS idx_ai_model_answers_model ON public.ai_model_answers (model_id, created_at);

CREATE TABLE IF NOT EXISTS public.ai_model_invites (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id     UUID        NOT NULL REFERENCES public.ai_models(id) ON DELETE CASCADE,
    inviter_id   UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    invitee_id   UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    thread_id    UUID        NULL,
    status       TEXT        NOT NULL DEFAULT 'open',
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    answered_at  TIMESTAMPTZ NULL,
    CONSTRAINT ai_model_invites_status CHECK (status IN ('open', 'not_now', 'accepted')),
    CONSTRAINT ai_model_invites_not_self CHECK (inviter_id <> invitee_id),
    CONSTRAINT ai_model_invites_once UNIQUE (model_id, invitee_id)
);

CREATE INDEX IF NOT EXISTS idx_ai_model_invites_invitee ON public.ai_model_invites (invitee_id);
CREATE INDEX IF NOT EXISTS idx_ai_model_invites_inviter ON public.ai_model_invites (inviter_id);

ALTER TABLE public.ai_models         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_model_teachers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_model_examples ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_model_answers  ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_model_invites  ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.ai_models, public.ai_model_teachers, public.ai_model_examples,
                    public.ai_model_answers, public.ai_model_invites
    FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.ai_models, public.ai_model_teachers,
                    public.ai_model_examples, public.ai_model_answers, public.ai_model_invites
    TO service_role;

-- The ring row: the founder and the people the founder adds first (ring 6),
-- as the chats began; the founder widens it from the rings panel.
INSERT INTO public.feature_rings (feature, min_ring, note, changed_by)
VALUES ('ai_models', 6,
        'The model launchpad (N528, N563, N566): the list of AI models, a '
        'model''s page, teaching it and the one queue.',
        'migration:a_person_can_teach_and_start_ai_models')
ON CONFLICT (feature) DO NOTHING;

INSERT INTO public.feature_ring_changes
    (feature, min_ring, attribute_rule, consent_purpose, killed, one_way, note,
     changed_by, changed_at)
SELECT f.feature, f.min_ring, f.attribute_rule, f.consent_purpose, f.killed,
       f.one_way, f.note, f.changed_by, f.changed_at
  FROM public.feature_rings f
 WHERE f.feature = 'ai_models'
   AND NOT EXISTS (SELECT 1 FROM public.feature_ring_changes c
                    WHERE c.feature = f.feature);

COMMIT;
