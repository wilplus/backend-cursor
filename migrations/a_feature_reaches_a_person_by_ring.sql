-- A feature reaches a person by ring (founder 2026-09-29, rings design note).
--
-- One rollout mechanism for every gated feature. A person has one ring (a
-- plain integer; a missing row means the default ring in ring_settings, with
-- no attributes). A feature carries the lowest ring that gets it, an optional
-- attribute rule (an AND of "key is in list"), an optional consent purpose,
-- and a kill switch. The rule, verbatim from the accepted design:
--
--   A feature is on for a person when the row is not killed, the person's
--   ring is >= the feature's ring, the row's attribute rule matches them
--   (AND of "key is in list"), and, for a feature with a consent purpose,
--   that consent is current for that person.
--
-- Rings decide REACH, never provenance (L3). A ring never creates consent
-- and a consent never moves a ring: the consent half of the check only READS
-- the two existing consent doors (the Phase-1 tick through
-- get_phase1_consent_choices_v1, the Phase-2 purpose through
-- get_mlc2_principal_consent_status_v1) and writes nothing. A one-way row
-- (a learning pipe) can be killed and never unkilled here; the confidence
-- chain's writer state, MLC2_CONFIDENCE_CUTOVER_MODE, stays a code constant
-- and stays "dark". No learning pipe is turned on by this file.
--
-- Writes go only through the SECURITY DEFINER RPCs below (R-1, as 0389):
-- service_role holds SELECT and nothing else on every table here, with one
-- named exception: DELETE on the three person-keyed tables (principal_rings,
-- principal_ring_changes, ring_announcement_decisions), because the Phase-1
-- purge (services/data_purge.py, registry "delete") removes a person's rows
-- through the service key and a person's ring, attributes and history must
-- go with them. Every change to a feature row, a person row or the default
-- ring is one row in an append-only change table: UPDATE is refused by
-- trigger everywhere, DELETE too on the two feature/setting change tables;
-- principal_ring_changes admits the purge's DELETE and nothing else.
--
-- Seed: the seven rows the code reads after this migration, at rings where
-- NOBODY is today (default ring 2; the rows sit at 3, 4 and 5 and no person
-- row is created at 4 or 5), so the two canaries stay exactly as closed as
-- the environment left them. The MLC-3 cohort and allow-list are copied in
-- at the exercise service's ring, so the people who have the exercise
-- service today keep it; the old tables are kept and no longer read by the
-- gate.
--
-- Additive and idempotent (CREATE ... IF NOT EXISTS, CREATE OR REPLACE,
-- INSERT ... ON CONFLICT DO NOTHING). Degrades gracefully: a table this
-- database lacks (owner_principals on a narrow lane, the MLC-3 lists, either
-- consent chain) is skipped or read as "no consent", never an error. No
-- environment variable is read (CONFIG-FIRST). Never DROP.

BEGIN;

-- ── Tables ──────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.feature_rings (
    feature         TEXT PRIMARY KEY
                    CHECK (feature ~ '^[a-z][a-z0-9_]{1,79}$'),
    min_ring        INTEGER NOT NULL CHECK (min_ring >= 0),
    attribute_rule  JSONB NULL
                    CHECK (attribute_rule IS NULL
                           OR jsonb_typeof(attribute_rule) = 'object'),
    consent_purpose TEXT NULL
                    CHECK (consent_purpose IS NULL OR consent_purpose IN
                           ('personalised_practice',
                            'pooled_model_improvement')),
    killed          BOOLEAN NOT NULL DEFAULT false,
    one_way         BOOLEAN NOT NULL DEFAULT false,
    note            TEXT NOT NULL DEFAULT '',
    changed_by      TEXT NULL,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.principal_rings (
    principal_id    UUID PRIMARY KEY,
    ring            INTEGER NOT NULL CHECK (ring >= 0),
    attributes      JSONB NOT NULL DEFAULT '{}'::jsonb
                    CHECK (jsonb_typeof(attributes) = 'object'),
    changed_by      TEXT NULL,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.ring_settings (
    key             TEXT PRIMARY KEY,
    value           JSONB NOT NULL,
    changed_by      TEXT NULL,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Announcements are founder-held copy. Rows ship as placeholders only
-- ("[founder copy] ..."); the panel edits them. `retired_at` retires one
-- instead of deleting it (never DELETE FROM in a migration).
CREATE TABLE IF NOT EXISTS public.ring_announcements (
    feature          TEXT PRIMARY KEY
                     REFERENCES public.feature_rings(feature)
                     ON DELETE RESTRICT,
    title            TEXT NOT NULL,
    body             TEXT NOT NULL,
    requires_consent BOOLEAN NOT NULL DEFAULT false,
    retired_at       TIMESTAMPTZ NULL,
    changed_by       TEXT NULL,
    changed_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- One row per (person, feature) decision; a re-announcement (a later
-- changed_at on the announcement) makes the feature pending again.
CREATE TABLE IF NOT EXISTS public.ring_announcement_decisions (
    principal_id    UUID NOT NULL,
    feature         TEXT NOT NULL,
    decision        TEXT NOT NULL CHECK (decision IN ('accepted', 'not_now')),
    decided_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (principal_id, feature)
);

-- Append-only change tables. Every write RPC below inserts one row.
CREATE TABLE IF NOT EXISTS public.feature_ring_changes (
    id              BIGSERIAL PRIMARY KEY,
    feature         TEXT NOT NULL,
    min_ring        INTEGER NOT NULL,
    attribute_rule  JSONB NULL,
    consent_purpose TEXT NULL,
    killed          BOOLEAN NOT NULL,
    one_way         BOOLEAN NOT NULL,
    note            TEXT NOT NULL DEFAULT '',
    changed_by      TEXT NULL,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.principal_ring_changes (
    id              BIGSERIAL PRIMARY KEY,
    principal_id    UUID NOT NULL,
    ring            INTEGER NOT NULL,
    attributes      JSONB NOT NULL DEFAULT '{}'::jsonb,
    changed_by      TEXT NULL,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.ring_setting_changes (
    id              BIGSERIAL PRIMARY KEY,
    key             TEXT NOT NULL,
    value           JSONB NOT NULL,
    changed_by      TEXT NULL,
    changed_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_feature_ring_changes_feature
    ON public.feature_ring_changes (feature, id);
CREATE INDEX IF NOT EXISTS idx_principal_ring_changes_principal
    ON public.principal_ring_changes (principal_id, id);
CREATE INDEX IF NOT EXISTS idx_principal_rings_ring
    ON public.principal_rings (ring);

-- ── Row level security and grants (R-1 shape, as 0389) ─────────────────────

DO $rls$
DECLARE
    v_table TEXT;
    role_name TEXT;
BEGIN
    FOREACH v_table IN ARRAY ARRAY[
        'feature_rings', 'principal_rings', 'ring_settings',
        'ring_announcements', 'ring_announcement_decisions',
        'feature_ring_changes', 'principal_ring_changes',
        'ring_setting_changes'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',
                       v_table);
        EXECUTE format('REVOKE ALL ON TABLE public.%I FROM PUBLIC', v_table);
        FOREACH role_name IN ARRAY ARRAY[
            'anon', 'authenticated', 'service_role'
        ] LOOP
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
                EXECUTE format('REVOKE ALL ON TABLE public.%I FROM %I',
                               v_table, role_name);
            END IF;
        END LOOP;
        -- Reads stay with the service key (the panel lists and the readiness
        -- monitor read these); writes go through the definer RPCs only.
        IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
            EXECUTE format('GRANT SELECT ON TABLE public.%I TO service_role',
                           v_table);
            -- The purge's door, on the person-keyed tables only.
            IF v_table IN ('principal_rings', 'principal_ring_changes',
                           'ring_announcement_decisions') THEN
                EXECUTE format('GRANT DELETE ON TABLE public.%I TO service_role',
                               v_table);
            END IF;
        END IF;
    END LOOP;
END;
$rls$;

-- ── Append-only, trigger-enforced ───────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.reject_ring_change_mutation()
RETURNS trigger LANGUAGE plpgsql SET search_path = public AS $$
BEGIN
    RAISE EXCEPTION 'ring change tables are append-only';
END;
$$;
REVOKE ALL ON FUNCTION public.reject_ring_change_mutation()
    FROM PUBLIC, anon, authenticated;

DO $appendonly$
DECLARE
    v_table TEXT;
    v_events TEXT;
BEGIN
    FOREACH v_table IN ARRAY ARRAY[
        'feature_ring_changes', 'principal_ring_changes',
        'ring_setting_changes'
    ] LOOP
        -- A person's history goes when the person is purged; a feature's or
        -- a setting's history never goes.
        v_events := CASE WHEN v_table = 'principal_ring_changes'
                         THEN 'UPDATE' ELSE 'UPDATE OR DELETE' END;
        IF NOT EXISTS (
            SELECT 1 FROM pg_trigger
             WHERE tgrelid = ('public.' || v_table)::regclass
               AND tgname = v_table || '_append_only'
        ) THEN
            EXECUTE format(
                'CREATE TRIGGER %I BEFORE %s ON public.%I '
                'FOR EACH ROW EXECUTE FUNCTION '
                'public.reject_ring_change_mutation()',
                v_table || '_append_only', v_events, v_table);
        END IF;
    END LOOP;
END;
$appendonly$;

-- ── Reads ───────────────────────────────────────────────────────────────────

-- The default ring for a person with no row. Falls back to 2 when the
-- setting is somehow absent, which is where the seed below puts it.
CREATE OR REPLACE FUNCTION public.ring_default_v1()
RETURNS INTEGER
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = public
AS $$
    SELECT COALESCE(
        (SELECT (value #>> '{}')::integer FROM ring_settings
          WHERE key = 'default_ring'
            AND jsonb_typeof(value) = 'number'),
        2);
$$;
REVOKE ALL ON FUNCTION public.ring_default_v1() FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ring_default_v1() TO service_role;

-- Whether the named consent is current for this person. READ ONLY, and
-- through the doors that already exist: the Phase-1 tick, or the Phase-2
-- bundled grant. A door this database does not have, an unknown principal
-- or a policy in an invalid state all answer false (closed).
CREATE OR REPLACE FUNCTION public.ring_consent_is_current_v1(
    p_principal UUID,
    p_purpose TEXT
) RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public
AS $$
DECLARE
    answer JSONB;
BEGIN
    IF p_principal IS NULL OR p_purpose IS NULL THEN
        RETURN false;
    END IF;
    IF p_purpose = 'personalised_practice' THEN
        IF to_regproc('public.get_phase1_consent_choices_v1(uuid)') IS NULL THEN
            RETURN false;
        END IF;
        BEGIN
            EXECUTE 'SELECT public.get_phase1_consent_choices_v1($1)'
               INTO answer USING p_principal;
        EXCEPTION WHEN OTHERS THEN
            RETURN false;
        END;
        RETURN COALESCE((answer ->> 'has_receipt')::boolean, false)
           AND COALESCE((answer ->> 'personalised_practice')::boolean, false);
    ELSIF p_purpose = 'pooled_model_improvement' THEN
        IF to_regproc('public.get_mlc2_principal_consent_status_v1(uuid)')
           IS NULL THEN
            RETURN false;
        END IF;
        BEGIN
            EXECUTE 'SELECT public.get_mlc2_principal_consent_status_v1($1)'
               INTO answer USING p_principal;
        EXCEPTION WHEN OTHERS THEN
            RETURN false;
        END;
        RETURN COALESCE((answer ->> 'configured')::boolean, false)
           AND COALESCE((answer ->> 'granted')::boolean, false);
    END IF;
    RETURN false;
END;
$$;
REVOKE ALL ON FUNCTION public.ring_consent_is_current_v1(UUID, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ring_consent_is_current_v1(UUID, TEXT)
    TO service_role;

-- Whether the legal policy behind a consent purpose exists yet. The panel's
-- "yes" for a Phase-2 purpose stays disabled until this says true. Reads
-- only; registers nothing.
CREATE OR REPLACE FUNCTION public.ring_consent_policy_exists_v1(
    p_purpose TEXT
) RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public
AS $$
DECLARE
    found BOOLEAN := false;
BEGIN
    IF p_purpose = 'personalised_practice' THEN
        IF to_regclass('public.processing_policy_versions') IS NULL THEN
            RETURN false;
        END IF;
        EXECUTE 'SELECT EXISTS (SELECT 1 FROM public.processing_policy_versions '
                || 'WHERE status = ''active'' AND activated_at <= now() '
                || 'AND (retired_at IS NULL OR retired_at > now()))'
           INTO found;
        RETURN found;
    ELSIF p_purpose = 'pooled_model_improvement' THEN
        IF to_regclass('public.ml_consent_policies') IS NULL THEN
            RETURN false;
        END IF;
        EXECUTE 'SELECT EXISTS (SELECT 1 FROM public.ml_consent_policies '
                || 'WHERE active_from <= now() '
                || 'AND (retired_at IS NULL OR retired_at > now()))'
           INTO found;
        RETURN found;
    END IF;
    RETURN false;
END;
$$;
REVOKE ALL ON FUNCTION public.ring_consent_policy_exists_v1(TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ring_consent_policy_exists_v1(TEXT)
    TO service_role;

-- The reach half of the rule: not killed, ring, attribute rule. No consent.
-- An unknown feature is off. A missing person is the default ring with no
-- attributes. Values in the rule's lists are compared as text, so a rule
-- may write {"bucket": ["0","1"]} against an attribute stored as a number.
CREATE OR REPLACE FUNCTION public.feature_reaches_v1(
    p_feature TEXT,
    p_principal UUID
) RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public
AS $$
DECLARE
    row_feature feature_rings;
    my_ring INTEGER;
    my_attributes JSONB := '{}'::jsonb;
BEGIN
    SELECT * INTO row_feature FROM feature_rings WHERE feature = p_feature;
    IF row_feature.feature IS NULL OR row_feature.killed THEN
        RETURN false;
    END IF;
    SELECT ring, attributes INTO my_ring, my_attributes
      FROM principal_rings WHERE principal_id = p_principal;
    IF my_ring IS NULL THEN
        my_ring := ring_default_v1();
        my_attributes := '{}'::jsonb;
    END IF;
    IF my_ring < row_feature.min_ring THEN
        RETURN false;
    END IF;
    IF row_feature.attribute_rule IS NOT NULL THEN
        IF EXISTS (
            SELECT 1 FROM jsonb_each(row_feature.attribute_rule) AS rule(key, allowed)
             WHERE jsonb_typeof(rule.allowed) <> 'array'
                OR (my_attributes ->> rule.key) IS NULL
                OR NOT EXISTS (
                    SELECT 1 FROM jsonb_array_elements_text(rule.allowed) AS v(item)
                     WHERE v.item = (my_attributes ->> rule.key))
        ) THEN
            RETURN false;
        END IF;
    END IF;
    RETURN true;
END;
$$;
REVOKE ALL ON FUNCTION public.feature_reaches_v1(TEXT, UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.feature_reaches_v1(TEXT, UUID) TO service_role;

-- The whole rule: reach, and the consent door when the row names one.
CREATE OR REPLACE FUNCTION public.feature_is_on_v1(
    p_feature TEXT,
    p_principal UUID
) RETURNS BOOLEAN
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public
AS $$
DECLARE
    purpose TEXT;
BEGIN
    IF NOT feature_reaches_v1(p_feature, p_principal) THEN
        RETURN false;
    END IF;
    SELECT consent_purpose INTO purpose FROM feature_rings
     WHERE feature = p_feature;
    IF purpose IS NULL THEN
        RETURN true;
    END IF;
    RETURN ring_consent_is_current_v1(p_principal, purpose);
END;
$$;
REVOKE ALL ON FUNCTION public.feature_is_on_v1(TEXT, UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.feature_is_on_v1(TEXT, UUID) TO service_role;

-- Everything a login needs in one read: the person's ring and attributes,
-- the features on for them, and the announcements pending for them. An
-- announcement is pending when the feature REACHES the person (ring, rule,
-- not killed), is not yet on for them because its consent is absent (or
-- needs no consent), has an active announcement, and the person has not
-- decided since that announcement last changed. The list never carries a
-- score, a verdict or anyone else's data.
CREATE OR REPLACE FUNCTION public.features_on_for_v1(
    p_principal UUID
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public
AS $$
DECLARE
    my_ring INTEGER;
    my_attributes JSONB := '{}'::jsonb;
    has_row BOOLEAN := false;
    on_list JSONB;
    pending JSONB;
BEGIN
    SELECT ring, attributes, true INTO my_ring, my_attributes, has_row
      FROM principal_rings WHERE principal_id = p_principal;
    IF my_ring IS NULL THEN
        my_ring := ring_default_v1();
        my_attributes := '{}'::jsonb;
        has_row := false;
    END IF;
    SELECT COALESCE(jsonb_agg(f.feature ORDER BY f.feature), '[]'::jsonb)
      INTO on_list
      FROM feature_rings f
     WHERE feature_is_on_v1(f.feature, p_principal);
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
                'feature', a.feature,
                'title', a.title,
                'body', a.body,
                'requires_consent', a.requires_consent,
                'consent_purpose', f.consent_purpose,
                'consent_policy_available',
                    CASE WHEN f.consent_purpose IS NULL THEN NULL
                         ELSE ring_consent_policy_exists_v1(f.consent_purpose)
                    END,
                'announced_at', a.changed_at
            ) ORDER BY a.feature), '[]'::jsonb)
      INTO pending
      FROM ring_announcements a
      JOIN feature_rings f ON f.feature = a.feature
     WHERE a.retired_at IS NULL
       AND feature_reaches_v1(f.feature, p_principal)
       AND (f.consent_purpose IS NULL
            OR NOT ring_consent_is_current_v1(p_principal, f.consent_purpose))
       AND NOT EXISTS (
           SELECT 1 FROM ring_announcement_decisions d
            WHERE d.principal_id = p_principal
              AND d.feature = a.feature
              AND d.decided_at >= a.changed_at);
    RETURN jsonb_build_object(
        'principal_id', p_principal,
        'ring', my_ring,
        'has_ring_row', has_row,
        'default_ring', ring_default_v1(),
        'attributes', my_attributes,
        'features_on', on_list,
        'pending_announcements', pending);
END;
$$;
REVOKE ALL ON FUNCTION public.features_on_for_v1(UUID)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.features_on_for_v1(UUID) TO service_role;

-- The principals a feature reaches (ring, rule, not killed), for the
-- readiness monitor's "only ring-eligible principals wrote canonical rows"
-- and the panel's people-on count. Reach only: consent is per person and
-- is asked at write time by the check above.
CREATE OR REPLACE FUNCTION public.ring_eligible_principals_v1(
    p_feature TEXT
) RETURNS SETOF UUID
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = public
AS $$
    SELECT pr.principal_id FROM principal_rings pr
     WHERE feature_reaches_v1(p_feature, pr.principal_id);
$$;
REVOKE ALL ON FUNCTION public.ring_eligible_principals_v1(TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ring_eligible_principals_v1(TEXT)
    TO service_role;

-- Aggregate counts per feature for the panel: how many people with a ring
-- row the feature reaches, and how many of those are on (consent too). A
-- person with no row is the default ring, which the panel shows beside the
-- counts; if the default ring reaches a feature the count says so.
CREATE OR REPLACE FUNCTION public.feature_ring_counts_v1()
RETURNS JSONB
LANGUAGE sql SECURITY DEFINER STABLE SET search_path = public
AS $$
    SELECT COALESCE(jsonb_object_agg(f.feature, jsonb_build_object(
        'reaches', (SELECT count(*) FROM principal_rings pr
                     WHERE feature_reaches_v1(f.feature, pr.principal_id)),
        'on', (SELECT count(*) FROM principal_rings pr
                WHERE feature_is_on_v1(f.feature, pr.principal_id)),
        'default_ring_reaches',
            NOT f.killed AND f.attribute_rule IS NULL
            AND ring_default_v1() >= f.min_ring,
        'consent_policy_available',
            CASE WHEN f.consent_purpose IS NULL THEN NULL
                 ELSE ring_consent_policy_exists_v1(f.consent_purpose) END
    )), '{}'::jsonb)
      FROM feature_rings f;
$$;
REVOKE ALL ON FUNCTION public.feature_ring_counts_v1()
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.feature_ring_counts_v1() TO service_role;

-- Readiness for the confidence chain, read against the RING rows instead of
-- the retired founder email and principal variable. Aggregate counts only,
-- never a recording, a transcript or a packet. Every learning table is
-- guarded: a database without it (a narrow lane) reports 0 and says so
-- with `tables_present`.
CREATE OR REPLACE FUNCTION public.get_ring_confidence_readiness_v1()
RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER STABLE SET search_path = public
AS $$
DECLARE
    confidence_row feature_rings;
    canonical_row feature_rings;
    eligible UUID[];
    eligible_count INTEGER := 0;
    eligible_grants INTEGER := 0;
    eligible_receipts INTEGER := 0;
    other_receipts INTEGER := 0;
    other_events INTEGER := 0;
    has_consent BOOLEAN := to_regclass('public.ml_consent_events') IS NOT NULL
        AND to_regclass('public.ml_consent_policies') IS NOT NULL
        AND to_regclass('public.ml_consent_event_purposes') IS NOT NULL;
    has_receipts BOOLEAN :=
        to_regclass('public.ml_confidence_producer_receipts') IS NOT NULL;
    has_events BOOLEAN := to_regclass('public.ml_canonical_events') IS NOT NULL;
BEGIN
    SELECT * INTO confidence_row FROM feature_rings
     WHERE feature = 'confidence_learning_writes';
    SELECT * INTO canonical_row FROM feature_rings
     WHERE feature = 'canonical_take_rows';
    SELECT COALESCE(array_agg(p), '{}'::uuid[]) INTO eligible
      FROM ring_eligible_principals_v1('confidence_learning_writes') AS p;
    eligible_count := cardinality(eligible);
    IF has_consent THEN
        EXECUTE $q$
            SELECT count(*) FROM public.ml_consent_events consent_event
              JOIN public.ml_consent_policies policy
                ON policy.version = consent_event.consent_policy_version
             WHERE consent_event.acquisition_principal_id = ANY($1)
               AND consent_event.event_kind = 'grant'
               AND policy.active_from <= now()
               AND (policy.retired_at IS NULL OR policy.retired_at > now())
               AND NOT EXISTS (
                   SELECT 1 FROM public.ml_consent_events withdrawal
                    WHERE withdrawal.event_kind = 'withdraw'
                      AND withdrawal.supersedes_event_id = consent_event.id
                      AND withdrawal.occurred_at <= now())
               AND (SELECT count(*) FROM public.ml_consent_event_purposes purpose
                     WHERE purpose.consent_event_id = consent_event.id
                       AND purpose.purpose IN ('personalized_coaching',
                                               'pooled_model_improvement')
                       AND purpose.article_6_basis = '6(1)(a)') = 2
        $q$ INTO eligible_grants USING eligible;
    END IF;
    IF has_receipts THEN
        EXECUTE 'SELECT count(*) FROM public.ml_confidence_producer_receipts r '
                'WHERE r.acquisition_principal_id = ANY($1)'
           INTO eligible_receipts USING eligible;
        EXECUTE 'SELECT count(*) FROM public.ml_confidence_producer_receipts r '
                'WHERE NOT (r.acquisition_principal_id = ANY($1))'
           INTO other_receipts USING eligible;
    END IF;
    IF has_events THEN
        EXECUTE 'SELECT count(*) FROM public.ml_canonical_events e '
                'WHERE e.learning_surface_id = ''confidence_classification'' '
                'AND NOT (e.acquisition_principal_id = ANY($1))'
           INTO other_events USING eligible;
    END IF;
    RETURN jsonb_build_object(
        'ring_readiness_contract_version', 'rings-confidence-readiness-v1',
        'confidence_ring_row_present', confidence_row.feature IS NOT NULL,
        'confidence_ring_row_killed', COALESCE(confidence_row.killed, false),
        'confidence_ring_row_one_way', COALESCE(confidence_row.one_way, false),
        'confidence_ring_min_ring', confidence_row.min_ring,
        'canonical_take_rows_row_present', canonical_row.feature IS NOT NULL,
        'canonical_take_rows_row_killed', COALESCE(canonical_row.killed, false),
        'eligible_principal_count', eligible_count,
        'eligible_bundled_consent_grant_count', eligible_grants,
        'eligible_producer_receipt_count', eligible_receipts,
        'noneligible_producer_receipt_count', other_receipts,
        'noneligible_canonical_event_count', other_events,
        'tables_present', jsonb_build_object(
            'consent', has_consent, 'receipts', has_receipts,
            'events', has_events),
        'aggregate_health_only', true
    );
END;
$$;
REVOKE ALL ON FUNCTION public.get_ring_confidence_readiness_v1()
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.get_ring_confidence_readiness_v1()
    TO service_role;

-- ── Writes ──────────────────────────────────────────────────────────────────

-- Create or move a feature row. `killed` is not touched here (kill_feature_v1
-- is the only way), and a killed one-way row refuses every edit: that pipe
-- is over. Records one change row.
CREATE OR REPLACE FUNCTION public.set_feature_ring_v1(
    p_feature TEXT,
    p_min_ring INTEGER,
    p_attribute_rule JSONB,
    p_consent_purpose TEXT,
    p_note TEXT,
    p_one_way BOOLEAN,
    p_changed_by TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    existing feature_rings;
    saved feature_rings;
BEGIN
    IF p_feature IS NULL OR p_feature !~ '^[a-z][a-z0-9_]{1,79}$' THEN
        RAISE EXCEPTION 'RING_FEATURE_INVALID';
    END IF;
    IF p_min_ring IS NULL OR p_min_ring < 0 THEN
        RAISE EXCEPTION 'RING_VALUE_INVALID';
    END IF;
    IF p_attribute_rule IS NOT NULL AND (
        jsonb_typeof(p_attribute_rule) <> 'object'
        OR EXISTS (SELECT 1 FROM jsonb_each(p_attribute_rule) r
                    WHERE jsonb_typeof(r.value) <> 'array')
    ) THEN
        RAISE EXCEPTION 'RING_RULE_INVALID';
    END IF;
    IF p_consent_purpose IS NOT NULL AND p_consent_purpose NOT IN
       ('personalised_practice', 'pooled_model_improvement') THEN
        RAISE EXCEPTION 'RING_CONSENT_PURPOSE_INVALID';
    END IF;
    SELECT * INTO existing FROM feature_rings WHERE feature = p_feature
       FOR UPDATE;
    IF existing.feature IS NOT NULL AND existing.one_way AND existing.killed THEN
        RAISE EXCEPTION 'RING_ONE_WAY_KILLED';
    END IF;
    -- A one-way row never becomes two-way again (the OR below keeps it).
    INSERT INTO feature_rings (feature, min_ring, attribute_rule,
                               consent_purpose, one_way, note, changed_by,
                               changed_at)
    VALUES (p_feature, p_min_ring, p_attribute_rule, p_consent_purpose,
            COALESCE(p_one_way, false), COALESCE(p_note, ''), p_changed_by,
            now())
    ON CONFLICT (feature) DO UPDATE SET
        min_ring = EXCLUDED.min_ring,
        attribute_rule = EXCLUDED.attribute_rule,
        consent_purpose = EXCLUDED.consent_purpose,
        one_way = feature_rings.one_way OR EXCLUDED.one_way,
        note = EXCLUDED.note,
        changed_by = EXCLUDED.changed_by,
        changed_at = EXCLUDED.changed_at
    RETURNING * INTO saved;
    INSERT INTO feature_ring_changes (feature, min_ring, attribute_rule,
                                      consent_purpose, killed, one_way, note,
                                      changed_by, changed_at)
    VALUES (saved.feature, saved.min_ring, saved.attribute_rule,
            saved.consent_purpose, saved.killed, saved.one_way, saved.note,
            saved.changed_by, saved.changed_at);
    RETURN to_jsonb(saved);
END;
$$;
REVOKE ALL ON FUNCTION public.set_feature_ring_v1(
    TEXT, INTEGER, JSONB, TEXT, TEXT, BOOLEAN, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.set_feature_ring_v1(
    TEXT, INTEGER, JSONB, TEXT, TEXT, BOOLEAN, TEXT) TO service_role;

-- The kill switch. An ordinary row is the same switch back; a one-way row
-- goes to killed and never back (the confidence chain's contract: rollback
-- to killed, never back to dark). The pipe's own kill is applied by the
-- Python caller, which reads this row: services/rings.py.
CREATE OR REPLACE FUNCTION public.kill_feature_v1(
    p_feature TEXT,
    p_killed BOOLEAN,
    p_changed_by TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    existing feature_rings;
    saved feature_rings;
BEGIN
    IF p_killed IS NULL THEN
        RAISE EXCEPTION 'RING_VALUE_INVALID';
    END IF;
    SELECT * INTO existing FROM feature_rings WHERE feature = p_feature
       FOR UPDATE;
    IF existing.feature IS NULL THEN
        RAISE EXCEPTION 'RING_FEATURE_UNKNOWN';
    END IF;
    IF existing.one_way AND existing.killed AND NOT p_killed THEN
        RAISE EXCEPTION 'RING_ONE_WAY_KILLED';
    END IF;
    UPDATE feature_rings
       SET killed = p_killed, changed_by = p_changed_by, changed_at = now()
     WHERE feature = p_feature
    RETURNING * INTO saved;
    INSERT INTO feature_ring_changes (feature, min_ring, attribute_rule,
                                      consent_purpose, killed, one_way, note,
                                      changed_by, changed_at)
    VALUES (saved.feature, saved.min_ring, saved.attribute_rule,
            saved.consent_purpose, saved.killed, saved.one_way, saved.note,
            saved.changed_by, saved.changed_at);
    RETURN to_jsonb(saved);
END;
$$;
REVOKE ALL ON FUNCTION public.kill_feature_v1(TEXT, BOOLEAN, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.kill_feature_v1(TEXT, BOOLEAN, TEXT)
    TO service_role;

-- One person's ring and attributes. A NULL ring keeps the current ring (or
-- takes the default for a new row); NULL attributes keep the current ones.
-- Attribute keys are lower-case identifiers; values are scalars.
CREATE OR REPLACE FUNCTION public.set_principal_ring_v1(
    p_principal UUID,
    p_ring INTEGER,
    p_attributes JSONB,
    p_changed_by TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    existing principal_rings;
    saved principal_rings;
    next_ring INTEGER;
    next_attributes JSONB;
BEGIN
    IF p_principal IS NULL THEN
        RAISE EXCEPTION 'RING_PRINCIPAL_INVALID';
    END IF;
    IF p_ring IS NOT NULL AND p_ring < 0 THEN
        RAISE EXCEPTION 'RING_VALUE_INVALID';
    END IF;
    IF p_attributes IS NOT NULL AND (
        jsonb_typeof(p_attributes) <> 'object'
        OR EXISTS (SELECT 1 FROM jsonb_each(p_attributes) a
                    WHERE a.key !~ '^[a-z][a-z0-9_]{0,39}$'
                       OR jsonb_typeof(a.value) IN ('object', 'array'))
    ) THEN
        RAISE EXCEPTION 'RING_ATTRIBUTES_INVALID';
    END IF;
    SELECT * INTO existing FROM principal_rings
     WHERE principal_id = p_principal FOR UPDATE;
    next_ring := COALESCE(p_ring, existing.ring, ring_default_v1());
    next_attributes := COALESCE(p_attributes, existing.attributes, '{}'::jsonb);
    INSERT INTO principal_rings (principal_id, ring, attributes, changed_by,
                                 changed_at)
    VALUES (p_principal, next_ring, next_attributes, p_changed_by, now())
    ON CONFLICT (principal_id) DO UPDATE SET
        ring = EXCLUDED.ring,
        attributes = EXCLUDED.attributes,
        changed_by = EXCLUDED.changed_by,
        changed_at = EXCLUDED.changed_at
    RETURNING * INTO saved;
    INSERT INTO principal_ring_changes (principal_id, ring, attributes,
                                        changed_by, changed_at)
    VALUES (saved.principal_id, saved.ring, saved.attributes,
            saved.changed_by, saved.changed_at);
    RETURN to_jsonb(saved);
END;
$$;
REVOKE ALL ON FUNCTION public.set_principal_ring_v1(UUID, INTEGER, JSONB, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.set_principal_ring_v1(UUID, INTEGER, JSONB, TEXT)
    TO service_role;

-- Many people to one ring, attributes kept. One change row per person.
CREATE OR REPLACE FUNCTION public.set_principal_rings_bulk_v1(
    p_principals UUID[],
    p_ring INTEGER,
    p_changed_by TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    one UUID;
    moved INTEGER := 0;
BEGIN
    IF p_ring IS NULL OR p_ring < 0 THEN
        RAISE EXCEPTION 'RING_VALUE_INVALID';
    END IF;
    IF p_principals IS NULL OR cardinality(p_principals) = 0
       OR cardinality(p_principals) > 500 THEN
        RAISE EXCEPTION 'RING_BULK_SIZE_INVALID';
    END IF;
    FOREACH one IN ARRAY p_principals LOOP
        PERFORM set_principal_ring_v1(one, p_ring, NULL, p_changed_by);
        moved := moved + 1;
    END LOOP;
    RETURN jsonb_build_object('moved', moved, 'ring', p_ring);
END;
$$;
REVOKE ALL ON FUNCTION public.set_principal_rings_bulk_v1(UUID[], INTEGER, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.set_principal_rings_bulk_v1(UUID[], INTEGER, TEXT)
    TO service_role;

-- The default ring for people with no row. Applies at the next check, to
-- everyone without a row, which is what "default" means here.
CREATE OR REPLACE FUNCTION public.set_ring_default_v1(
    p_ring INTEGER,
    p_changed_by TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    saved ring_settings;
BEGIN
    IF p_ring IS NULL OR p_ring < 0 THEN
        RAISE EXCEPTION 'RING_VALUE_INVALID';
    END IF;
    INSERT INTO ring_settings (key, value, changed_by, changed_at)
    VALUES ('default_ring', to_jsonb(p_ring), p_changed_by, now())
    ON CONFLICT (key) DO UPDATE SET
        value = EXCLUDED.value,
        changed_by = EXCLUDED.changed_by,
        changed_at = EXCLUDED.changed_at
    RETURNING * INTO saved;
    INSERT INTO ring_setting_changes (key, value, changed_by, changed_at)
    VALUES (saved.key, saved.value, saved.changed_by, saved.changed_at);
    RETURN to_jsonb(saved);
END;
$$;
REVOKE ALL ON FUNCTION public.set_ring_default_v1(INTEGER, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.set_ring_default_v1(INTEGER, TEXT)
    TO service_role;

-- Create, edit or retire (p_retired = true) the announcement for a feature.
-- The copy is founder-held; the panel keeps it as "[founder copy]"
-- placeholders until signed off. A change makes the announcement pending
-- again for everyone it reaches.
CREATE OR REPLACE FUNCTION public.set_ring_announcement_v1(
    p_feature TEXT,
    p_title TEXT,
    p_body TEXT,
    p_requires_consent BOOLEAN,
    p_retired BOOLEAN,
    p_changed_by TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    saved ring_announcements;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM feature_rings WHERE feature = p_feature) THEN
        RAISE EXCEPTION 'RING_FEATURE_UNKNOWN';
    END IF;
    IF p_title IS NULL OR length(btrim(p_title)) = 0 OR length(p_title) > 200
       OR p_body IS NULL OR length(p_body) > 4000 THEN
        RAISE EXCEPTION 'RING_ANNOUNCEMENT_INVALID';
    END IF;
    INSERT INTO ring_announcements (feature, title, body, requires_consent,
                                    retired_at, changed_by, changed_at)
    VALUES (p_feature, p_title, p_body, COALESCE(p_requires_consent, false),
            CASE WHEN COALESCE(p_retired, false) THEN clock_timestamp()
                 ELSE NULL END,
            p_changed_by, clock_timestamp())
    ON CONFLICT (feature) DO UPDATE SET
        title = EXCLUDED.title,
        body = EXCLUDED.body,
        requires_consent = EXCLUDED.requires_consent,
        retired_at = EXCLUDED.retired_at,
        changed_by = EXCLUDED.changed_by,
        changed_at = EXCLUDED.changed_at
    RETURNING * INTO saved;
    RETURN to_jsonb(saved);
END;
$$;
REVOKE ALL ON FUNCTION public.set_ring_announcement_v1(
    TEXT, TEXT, TEXT, BOOLEAN, BOOLEAN, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.set_ring_announcement_v1(
    TEXT, TEXT, TEXT, BOOLEAN, BOOLEAN, TEXT) TO service_role;

-- A person's answer to an announcement. 'accepted' records that they said
-- yes to being shown the feature; it creates NO consent (L3): the consent
-- itself is recorded by the consent routes, and the feature turns on only
-- when feature_is_on_v1 sees that consent. 'not_now' keeps them where they
-- were and stops the sheet until the announcement is changed again.
CREATE OR REPLACE FUNCTION public.record_ring_announcement_decision_v1(
    p_principal UUID,
    p_feature TEXT,
    p_decision TEXT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    saved ring_announcement_decisions;
BEGIN
    IF p_principal IS NULL THEN
        RAISE EXCEPTION 'RING_PRINCIPAL_INVALID';
    END IF;
    IF p_decision IS NULL OR p_decision NOT IN ('accepted', 'not_now') THEN
        RAISE EXCEPTION 'RING_DECISION_INVALID';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM ring_announcements
                    WHERE feature = p_feature AND retired_at IS NULL) THEN
        RAISE EXCEPTION 'RING_ANNOUNCEMENT_UNKNOWN';
    END IF;
    INSERT INTO ring_announcement_decisions (principal_id, feature, decision,
                                             decided_at)
    VALUES (p_principal, p_feature, p_decision, clock_timestamp())
    ON CONFLICT (principal_id, feature) DO UPDATE SET
        decision = EXCLUDED.decision,
        decided_at = EXCLUDED.decided_at
    RETURNING * INTO saved;
    RETURN to_jsonb(saved);
END;
$$;
REVOKE ALL ON FUNCTION public.record_ring_announcement_decision_v1(UUID, TEXT, TEXT)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_ring_announcement_decision_v1(UUID, TEXT, TEXT)
    TO service_role;

-- ── Seed ────────────────────────────────────────────────────────────────────
-- ON CONFLICT DO NOTHING throughout: a second run, or a row the founder has
-- already moved, is left alone.

INSERT INTO public.ring_settings (key, value, changed_by)
VALUES ('default_ring', '2'::jsonb, 'migration:0392')
ON CONFLICT (key) DO NOTHING;

INSERT INTO public.feature_rings
    (feature, min_ring, attribute_rule, consent_purpose, killed, one_way, note,
     changed_by)
VALUES
    ('exercise_service', 3, NULL, 'personalised_practice', false, false,
     'MLC-3 D2/D4 service loop. Absorbs mlc3_service_cohort_members and '
     'mlc3_service_principal_allowlist (seeded at this ring); '
     'MLC3_SERVICE_ENABLED stays the building switch and the DB enrollment '
     'wristband is still issued after this check passes.',
     'migration:0392'),
    ('exercise_service_ui', 3, NULL, NULL, false, false,
     'The exercise service surfaces in the app, served per person through '
     'features_on in the bootstrap payload; NEXT_PUBLIC_MLC3_SERVICE_UI_ENABLED '
     'stays the building switch.',
     'migration:0392'),
    ('coach_inline_authoring', 4, NULL, NULL, false, false,
     'D5 inline blind batch and authoring for the coach whose queue it is; '
     'replaces the legacy coach queue for that coach. '
     'MLC3_COACH_INLINE_AUTHORING_ENABLED stays the building switch.',
     'migration:0392'),
    ('confident_moment_bundles', 4, NULL, NULL, false, false,
     'Confident Moment coaching bundle routes (third answer lane). '
     'CONFIDENT_MOMENT_BUNDLE_V1_ENABLED stays the building switch.',
     'migration:0392'),
    ('rooting_coverage', 4, NULL, NULL, false, false,
     'Root actions on a bundle; needs confident_moment_bundles. '
     'ROOTING_COVERAGE_V1_ENABLED stays the building switch.',
     'migration:0392'),
    ('canonical_take_rows', 5, NULL, NULL, false, false,
     'Replaces the data-foundation canary (DATA_FOUNDATION_CANARY_ENABLED + '
     'ADMIN_EMAIL + MLC2_CONFIDENCE_CANARY_PRINCIPAL_ID): whose Takes get a '
     'canonical Recording Attempt row. Nobody is at this ring after the '
     'migration; the founder moves themself here from the panel.',
     'migration:0392'),
    ('confidence_learning_writes', 5, NULL, 'pooled_model_improvement', false,
     true,
     'The confidence chain''s "who". One-way: killing it is permanent and '
     'moves the writer state to killed. The writer state itself '
     '(MLC2_CONFIDENCE_CUTOVER_MODE) stays a code constant, dark today; '
     'this row never turns the pipe on.',
     'migration:0392')
ON CONFLICT (feature) DO NOTHING;

-- Placeholders only; the founder writes the words in the panel.
INSERT INTO public.ring_announcements
    (feature, title, body, requires_consent, changed_by)
VALUES
    ('confidence_learning_writes',
     '[founder copy] A new way for willab to learn from your practice',
     '[founder copy] Explain that anonymous confidence moments may be used to '
     'improve the model; link the policy; two buttons: not now / yes.',
     true, 'migration:0392'),
    ('exercise_service',
     '[founder copy] Exercises matched to your moments',
     '[founder copy] Explain the practice tick; one button: turn on in my '
     'data choices.',
     true, 'migration:0392')
ON CONFLICT (feature) DO NOTHING;

-- The MLC-3 guest list moves in, at the exercise service's ring. The people
-- who have the service today keep it. Additive: the old tables stay and the
-- gate no longer reads them. Skipped, with a notice, where a database lacks
-- either table (a narrow rehearsal lane).
DO $seed$
DECLARE
    seeded INTEGER := 0;
BEGIN
    IF to_regclass('public.mlc3_service_cohort_members') IS NOT NULL THEN
        INSERT INTO public.principal_rings (principal_id, ring, attributes,
                                            changed_by)
        SELECT DISTINCT m.acquisition_principal_id, 3, '{}'::jsonb,
               'migration:0392:mlc3_service_cohort_members'
          FROM public.mlc3_service_cohort_members m
        ON CONFLICT (principal_id) DO NOTHING;
        GET DIAGNOSTICS seeded = ROW_COUNT;
        RAISE NOTICE '0392: % cohort members seeded at ring 3', seeded;
    ELSE
        RAISE NOTICE '0392: mlc3_service_cohort_members absent here; skipped';
    END IF;
    IF to_regclass('public.mlc3_service_principal_allowlist') IS NOT NULL THEN
        INSERT INTO public.principal_rings (principal_id, ring, attributes,
                                            changed_by)
        SELECT DISTINCT a.acquisition_principal_id, 3, '{}'::jsonb,
               'migration:0392:mlc3_service_principal_allowlist'
          FROM public.mlc3_service_principal_allowlist a
         WHERE a.state = 'active'
        ON CONFLICT (principal_id) DO NOTHING;
        GET DIAGNOSTICS seeded = ROW_COUNT;
        RAISE NOTICE '0392: % allow-listed principals seeded at ring 3', seeded;
    ELSE
        RAISE NOTICE '0392: mlc3_service_principal_allowlist absent here; skipped';
    END IF;
    -- The seed rows above are changes too.
    INSERT INTO public.principal_ring_changes (principal_id, ring, attributes,
                                               changed_by, changed_at)
    SELECT pr.principal_id, pr.ring, pr.attributes, pr.changed_by, pr.changed_at
      FROM public.principal_rings pr
     WHERE pr.changed_by LIKE 'migration:0392:%'
       AND NOT EXISTS (SELECT 1 FROM public.principal_ring_changes c
                        WHERE c.principal_id = pr.principal_id);
END;
$seed$;

INSERT INTO public.feature_ring_changes
    (feature, min_ring, attribute_rule, consent_purpose, killed, one_way, note,
     changed_by, changed_at)
SELECT f.feature, f.min_ring, f.attribute_rule, f.consent_purpose, f.killed,
       f.one_way, f.note, f.changed_by, f.changed_at
  FROM public.feature_rings f
 WHERE f.changed_by = 'migration:0392'
   AND NOT EXISTS (SELECT 1 FROM public.feature_ring_changes c
                    WHERE c.feature = f.feature);

INSERT INTO public.ring_setting_changes (key, value, changed_by, changed_at)
SELECT s.key, s.value, s.changed_by, s.changed_at
  FROM public.ring_settings s
 WHERE s.changed_by = 'migration:0392'
   AND NOT EXISTS (SELECT 1 FROM public.ring_setting_changes c
                    WHERE c.key = s.key);

COMMENT ON TABLE public.feature_rings IS
    'One row per gated feature: the lowest ring that gets it, an attribute '
    'rule, an optional consent purpose, and the kill switch. Written only '
    'through set_feature_ring_v1 and kill_feature_v1.';
COMMENT ON TABLE public.principal_rings IS
    'One row per person with a ring: their ring and attributes. A missing '
    'row is the default ring (ring_settings.default_ring) with no attributes.';
COMMENT ON FUNCTION public.feature_is_on_v1(TEXT, UUID) IS
    'The rule: not killed, ring >= min_ring, attribute rule matches, and the '
    'consent purpose (if any) is current for the person. Read only.';

COMMIT;
