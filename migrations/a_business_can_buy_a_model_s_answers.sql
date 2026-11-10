-- a_business_can_buy_a_model_s_answers (the models' API and its money;
-- founder, the Claude Code chat, 5 to 9 November 2026: N528 items 6, 7 and
-- 11, N531, N563, N566 items 8 to 10, N577, N581, N583; the locked
-- prototype docs/design/model-launchpad-2026-11-09/, version 8).
--
-- Builds on a_person_can_teach_and_start_ai_models (0516). The rules live in
-- services/model_api.py, which has no storage of its own; these tables only
-- hold what it reads.
--
--   ai_models (2 columns)  The price of one answer, in stored token units,
--                          set by the model's founder above what an answer
--                          costs to run (N531 item 3, N583 item 3), and when.
--   ai_model_versions      One row per trained version of a model (N531 item
--                          2: "shares are fixed per version"; N566 item 9:
--                          "versions pinned"): its number, its stage
--                          (training, passed, released, retired), the
--                          provider's model it runs on, the founder of the
--                          model when it was made (who keeps the fixed 10%,
--                          N577 item 2), its card (good at, not so good at,
--                          not for) and its exam result.
--   ai_model_shares        Who trained a version and how much: one row per
--                          (version, teacher), with their points (a point for
--                          each answer that counted, N583 item 4) and those
--                          answers. Fixed when the version is made; a share
--                          is a teacher's points over the version's total.
--   ai_model_api_keys      A buyer's key to one model (N528 item 7, N566 item
--                          9): only its SHA-256 hash and its last four
--                          characters are stored, never the key. Test or
--                          live, the version it is pinned to, the free test
--                          answers left (100), a monthly limit, and whether
--                          its users' questions may teach the model.
--   ai_model_calls         One row per answer the API gave: the key, the
--                          buyer, the version, whether it was sure, and the
--                          price split in the order N531 item 1 and N577 set
--                          (running costs, WillpowerLab's 20% of the margin,
--                          the founder's 10% of the rest, the teachers' rest).
--                          The question and the answer are NOT kept here.
--   ai_model_payouts       What a version owes a person for a month, and
--                          whether it was paid (in tokens until the legal
--                          terms are signed, N531 item 4, N583 item 4).
--
-- Read and written by the backend (service role) only; nothing for anon or
-- authenticated. RLS on, no policies. No environment variable needed. No new
-- ring row: everything here sits behind the ring row ai_models (0516).
-- Account erasure: services/data_purge_registry.py deletes a person's keys,
-- shares and payouts, and clears the buyer and the founder on the calls and
-- versions they leave behind (the teachers' earnings stay accounted for).
--
-- Idempotent and additive: CREATE ... IF NOT EXISTS, ADD COLUMN IF NOT
-- EXISTS, constraints added only when missing; nothing is dropped and no
-- existing row is written, rewritten or removed. One transaction.
--
-- Rollback (a new forward migration): leave the tables and columns; dropping
-- them is a separate, previewed retention operation.

BEGIN;

ALTER TABLE public.ai_models ADD COLUMN IF NOT EXISTS price_units  INTEGER     NULL;
ALTER TABLE public.ai_models ADD COLUMN IF NOT EXISTS price_set_at TIMESTAMPTZ NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint
                    WHERE conname = 'ai_models_price_positive'
                      AND conrelid = 'public.ai_models'::regclass) THEN
        ALTER TABLE public.ai_models
            ADD CONSTRAINT ai_models_price_positive
            CHECK (price_units IS NULL OR price_units > 0);
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS public.ai_model_versions (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id        UUID        NOT NULL REFERENCES public.ai_models(id) ON DELETE CASCADE,
    number          INTEGER     NOT NULL,
    status          TEXT        NOT NULL DEFAULT 'training',
    base_model      TEXT        NOT NULL DEFAULT 'gpt-4o-mini',
    provider_model  TEXT        NULL,
    founder_id      UUID        NULL REFERENCES auth.users(id) ON DELETE SET NULL,
    card            JSONB       NOT NULL DEFAULT '{}'::jsonb,
    exam            JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    released_at     TIMESTAMPTZ NULL,
    CONSTRAINT ai_model_versions_number CHECK (number >= 1),
    CONSTRAINT ai_model_versions_status CHECK (status IN ('training', 'passed', 'released', 'retired')),
    CONSTRAINT ai_model_versions_released_at CHECK (status <> 'released' OR released_at IS NOT NULL),
    CONSTRAINT ai_model_versions_base_len CHECK (char_length(base_model) BETWEEN 1 AND 120),
    CONSTRAINT ai_model_versions_provider_len CHECK (provider_model IS NULL OR char_length(provider_model) <= 200),
    CONSTRAINT ai_model_versions_card_object CHECK (jsonb_typeof(card) = 'object'),
    CONSTRAINT ai_model_versions_exam_object CHECK (jsonb_typeof(exam) = 'object'),
    CONSTRAINT ai_model_versions_once UNIQUE (model_id, number)
);

CREATE INDEX IF NOT EXISTS idx_ai_model_versions_founder ON public.ai_model_versions (founder_id)
    WHERE founder_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.ai_model_shares (
    version_id  UUID          NOT NULL REFERENCES public.ai_model_versions(id) ON DELETE CASCADE,
    user_id     UUID          NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    points      NUMERIC(14,3) NOT NULL DEFAULT 0,
    answers     INTEGER       NOT NULL DEFAULT 0,
    created_at  TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (version_id, user_id),
    CONSTRAINT ai_model_shares_points CHECK (points >= 0),
    CONSTRAINT ai_model_shares_answers CHECK (answers >= 0)
);

CREATE INDEX IF NOT EXISTS idx_ai_model_shares_user ON public.ai_model_shares (user_id);

CREATE TABLE IF NOT EXISTS public.ai_model_api_keys (
    id                   UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    model_id             UUID        NOT NULL REFERENCES public.ai_models(id) ON DELETE CASCADE,
    buyer_id             UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    version_id           UUID        NOT NULL REFERENCES public.ai_model_versions(id) ON DELETE CASCADE,
    key_hash             TEXT        NOT NULL,
    key_tail             TEXT        NOT NULL,
    kind                 TEXT        NOT NULL DEFAULT 'test',
    free_left            INTEGER     NOT NULL DEFAULT 0,
    monthly_limit_units  BIGINT      NULL,
    allow_training       BOOLEAN     NOT NULL DEFAULT false,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at         TIMESTAMPTZ NULL,
    revoked_at           TIMESTAMPTZ NULL,
    CONSTRAINT ai_model_api_keys_kind CHECK (kind IN ('test', 'live')),
    CONSTRAINT ai_model_api_keys_hash_shape CHECK (key_hash ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ai_model_api_keys_tail_len CHECK (char_length(key_tail) = 4),
    CONSTRAINT ai_model_api_keys_free_left CHECK (free_left >= 0 AND (kind = 'test' OR free_left = 0)),
    CONSTRAINT ai_model_api_keys_limit CHECK (monthly_limit_units IS NULL OR monthly_limit_units > 0),
    CONSTRAINT ai_model_api_keys_hash_once UNIQUE (key_hash)
);

CREATE INDEX IF NOT EXISTS idx_ai_model_api_keys_buyer ON public.ai_model_api_keys (buyer_id, model_id);
CREATE INDEX IF NOT EXISTS idx_ai_model_api_keys_model ON public.ai_model_api_keys (model_id);
CREATE INDEX IF NOT EXISTS idx_ai_model_api_keys_version ON public.ai_model_api_keys (version_id);

CREATE TABLE IF NOT EXISTS public.ai_model_calls (
    id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    key_id          UUID        NULL REFERENCES public.ai_model_api_keys(id) ON DELETE SET NULL,
    buyer_id        UUID        NULL REFERENCES auth.users(id) ON DELETE SET NULL,
    model_id        UUID        NOT NULL REFERENCES public.ai_models(id) ON DELETE CASCADE,
    version_id      UUID        NOT NULL REFERENCES public.ai_model_versions(id) ON DELETE CASCADE,
    test            BOOLEAN     NOT NULL DEFAULT false,
    sure            BOOLEAN     NOT NULL DEFAULT false,
    price_units     INTEGER     NOT NULL DEFAULT 0,
    cost_units      INTEGER     NOT NULL DEFAULT 0,
    fee_units       INTEGER     NOT NULL DEFAULT 0,
    founder_units   INTEGER     NOT NULL DEFAULT 0,
    teachers_units  INTEGER     NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ai_model_calls_nonnegative CHECK (price_units >= 0 AND cost_units >= 0 AND fee_units >= 0
                                                 AND founder_units >= 0 AND teachers_units >= 0),
    CONSTRAINT ai_model_calls_split_adds_up CHECK (
        price_units = 0 OR price_units = cost_units + fee_units + founder_units + teachers_units),
    CONSTRAINT ai_model_calls_test_is_free CHECK (NOT test OR price_units = 0)
);

CREATE INDEX IF NOT EXISTS idx_ai_model_calls_key ON public.ai_model_calls (key_id, created_at)
    WHERE key_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ai_model_calls_buyer ON public.ai_model_calls (buyer_id)
    WHERE buyer_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ai_model_calls_version ON public.ai_model_calls (version_id, created_at);

CREATE TABLE IF NOT EXISTS public.ai_model_payouts (
    id          UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    version_id  UUID        NOT NULL REFERENCES public.ai_model_versions(id) ON DELETE CASCADE,
    user_id     UUID        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    role        TEXT        NOT NULL,
    month       DATE        NOT NULL,
    units       BIGINT      NOT NULL DEFAULT 0,
    status      TEXT        NOT NULL DEFAULT 'owed',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    paid_at     TIMESTAMPTZ NULL,
    CONSTRAINT ai_model_payouts_role CHECK (role IN ('founder', 'teacher')),
    CONSTRAINT ai_model_payouts_status CHECK (status IN ('owed', 'paid')),
    CONSTRAINT ai_model_payouts_paid_at CHECK (status <> 'paid' OR paid_at IS NOT NULL),
    CONSTRAINT ai_model_payouts_units CHECK (units >= 0),
    CONSTRAINT ai_model_payouts_month_start CHECK (month = date_trunc('month', month)::date),
    CONSTRAINT ai_model_payouts_once UNIQUE (version_id, user_id, role, month)
);

CREATE INDEX IF NOT EXISTS idx_ai_model_payouts_user ON public.ai_model_payouts (user_id, status);

ALTER TABLE public.ai_model_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_model_shares   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_model_api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_model_calls    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_model_payouts  ENABLE ROW LEVEL SECURITY;

REVOKE ALL ON TABLE public.ai_model_versions, public.ai_model_shares, public.ai_model_api_keys,
                    public.ai_model_calls, public.ai_model_payouts
    FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.ai_model_versions, public.ai_model_shares,
                    public.ai_model_api_keys, public.ai_model_calls, public.ai_model_payouts
    TO service_role;

COMMIT;
