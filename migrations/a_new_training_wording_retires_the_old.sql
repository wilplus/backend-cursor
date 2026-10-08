-- 0458 · A new training wording retires the old one, in one call
-- (founder 2026-10-08, the 3.5 pack, decisions log N68, D3; legal/
-- phase1-2026.1/23-training-consent-wording-v2-SIGNED-2026-10-08.md and
-- SIGN-3.5-2026-10-08.md, steps 4 and 6; 22-…, E6).
--
-- WHY. The founder signed training wording v2 (`training-only-v2`) and D3:
-- "registering v2 retires v1, and every existing yes counts as off until the
-- person says yes again" (Privacy 3.5 §4a, "If you said yes before version
-- 3.5"). Three things stood in the way:
--
--   * `ml_consent_policies` refuses every UPDATE and DELETE
--     (`ml_consent_policies_append_only` → `reject_mlc2_immutable_mutation`,
--     0302), so 23's hand-written `UPDATE … SET retired_at` is refused;
--   * `configure_mlc2_training_consent_policy_v1` (0373) refuses v2 while v1
--     has no `retired_at` at or before v2's `active_from`
--     (ANOTHER_TRAINING_POLICY_IS_ACTIVE);
--   * nothing retires a training policy.
--
-- WHAT. One guard with one door, and one function that walks through it:
--
--   guard_ml_consent_policy_mutation_v1   the trigger function on
--                     `ml_consent_policies` from now on, under the trigger's
--                     old name (`ml_consent_policies_append_only`). It
--                     refuses exactly what 0302's refused, with 0302's
--                     message, except one change: setting `retired_at` on a
--                     `training_only` row that has none, every other column
--                     unchanged, while the transaction-local setting
--                     `willab.training_policy_supersede` names that row's
--                     version. Only the function below sets it (the pattern
--                     of 0446's `willab.coach_answer_change`), and clears it
--                     again before it registers the successor. DELETE is
--                     always refused; a bundled_v1 row never changes; a
--                     retired row is never re-dated.
--   supersede_mlc2_training_consent_policy_v1(p_predecessor_version, then
--                     configure_…'s thirteen arguments, unchanged and in
--                     their order). In one transaction: checks the
--                     predecessor is THE training policy in force now (a
--                     training_only row, active_from <= now(), no
--                     retired_at, and no other training policy in force or
--                     waiting); refuses a switch instant in the past (a yes
--                     already recorded under the predecessor would be
--                     retired after the fact) or at/before the
--                     predecessor's start; refuses while any training copy
--                     made under a predecessor yes is still active (3.5 §4a
--                     promises a v1 yes is treated as switched off, which
--                     deletes its copies; the corpus copy is off, so there
--                     should be none, and if there are, a person decides,
--                     not this function); retires the predecessor at
--                     p_active_from; registers the successor through
--                     configure_mlc2_training_consent_policy_v1 itself, so
--                     every check 0373 makes (the copy hash, the evidence
--                     hash, the processing version, idempotency) is made.
--                     Either everything happens or nothing does.
--                     Called again with the same arguments it changes
--                     nothing and answers `replayed: true`; with any other
--                     arguments once the successor exists it is refused.
--
-- A V1 YES COUNTS AS OFF, CHECKED, NOT ADDED. Every reader of the training
-- yes already ties a grant to a policy in force NOW (active_from <= now()
-- AND (retired_at IS NULL OR retired_at > now())):
--   get_mlc2_training_consent_status_v2 (0373; the switch card, the chain's
--     ring_consent_is_current_v1 and create_mlc2_training_consent_snapshot_v1
--     (0430), the corpus copy record_training_corpus_item_v1 (0375), the
--     deletion's training read (0422));
--   the view training_consent_active_grants (0405; the weekly pair refresh,
--     which marks every pair of a v1-only owner not releasable and voids the
--     releases that hold one, and the door-3 sweep of 0406, which lists every
--     fine-tune run with such an owner for its provider files to go);
--   record_mlc2_training_consent_grant_v2 (0436), which refuses a new yes
--     under a retired policy (TRAINING_POLICY_NOT_ACTIVE).
-- So once the predecessor's retired_at has passed, its yes reads as off
-- everywhere, with no row rewritten. The consent events stay as they were:
-- the record of each yes and each withdrawal is evidence and is kept. A v1
-- yes can still be withdrawn (record_mlc2_consent_withdrawal_v2 reads no
-- policy window), and a person says yes again under v2 after re-accepting
-- the processing policy v2 names (C1, unchanged).
--
-- Idempotent: CREATE OR REPLACE, DROP TRIGGER IF EXISTS then CREATE TRIGGER;
-- applied twice it changes nothing. Writes no row. Locks: the trigger swap
-- on ml_consent_policies (a handful of rows; a brief exclusive lock for the
-- catalog change, no rewrite, no scan). Reads no environment variable.
--
-- Rollback (a new forward migration): recreate the trigger on
-- reject_mlc2_immutable_mutation(); DROP FUNCTION
-- public.supersede_mlc2_training_consent_policy_v1(TEXT, TEXT, TEXT, TEXT,
-- TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT[], TEXT, TEXT, TEXT, TIMESTAMPTZ);
-- DROP FUNCTION public.guard_ml_consent_policy_mutation_v1(). A policy
-- already retired stays retired.

BEGIN;

-- ── The guard, with one door ──────────────────────────────────────────────
-- (Its body names no table: it only decides whether the row change it is
-- shown may stand.)
CREATE OR REPLACE FUNCTION public.guard_ml_consent_policy_mutation_v1()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = public
AS $$
DECLARE
    door text := current_setting('willab.training_policy_supersede', true);
BEGIN
    -- The one door: the supersede function, retiring this very training
    -- policy in this transaction. Only retired_at may change, only from
    -- nothing to a moment, and every other column stays as it was.
    IF TG_OP = 'UPDATE'
       AND NULLIF(door, '') IS NOT NULL
       AND door = OLD.version
       AND OLD.grant_scope = 'training_only'
       AND OLD.retired_at IS NULL
       AND NEW.retired_at IS NOT NULL
       AND (to_jsonb(NEW) - 'retired_at') = (to_jsonb(OLD) - 'retired_at') THEN
        RETURN NEW;
    END IF;
    -- Everything else, as 0302: append-only.
    RAISE EXCEPTION 'MLC-2 canonical records are append-only';
END;
$$;

REVOKE ALL ON FUNCTION public.guard_ml_consent_policy_mutation_v1()
    FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS ml_consent_policies_append_only
    ON public.ml_consent_policies;
CREATE TRIGGER ml_consent_policies_append_only
    BEFORE UPDATE OR DELETE ON public.ml_consent_policies
    FOR EACH ROW EXECUTE FUNCTION public.guard_ml_consent_policy_mutation_v1();

-- ── Retire the training policy in force and register its successor ───────
CREATE OR REPLACE FUNCTION public.supersede_mlc2_training_consent_policy_v1(
    p_predecessor_version TEXT,
    p_approval_reference TEXT,
    p_approved_copy_sha256 TEXT,
    p_toggle_copy TEXT,
    p_consent_policy_version TEXT,
    p_terms_version TEXT,
    p_privacy_policy_version TEXT,
    p_approving_authority TEXT,
    p_approved_at TIMESTAMPTZ,
    p_jurisdictions TEXT[],
    p_evidence_object_key TEXT,
    p_evidence_sha256 TEXT,
    p_requires_processing_policy_version TEXT,
    p_active_from TIMESTAMPTZ
) RETURNS JSONB
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public
AS $$
DECLARE
    predecessor public.ml_consent_policies;
    successor public.ml_consent_policies;
    registered JSONB;
    retired_rows INTEGER;
BEGIN
    IF NULLIF(btrim(p_predecessor_version), '') IS NULL
       OR NULLIF(btrim(p_consent_policy_version), '') IS NULL
       OR p_active_from IS NULL THEN
        RAISE EXCEPTION 'TRAINING_POLICY_SUPERSEDE_INCOMPLETE';
    END IF;
    IF p_predecessor_version = p_consent_policy_version THEN
        RAISE EXCEPTION 'TRAINING_POLICY_CANNOT_SUPERSEDE_ITSELF';
    END IF;

    -- One supersession at a time, and the predecessor's row held still.
    PERFORM pg_advisory_xact_lock(
        hashtext('supersede_mlc2_training_consent_policy_v1'));
    SELECT * INTO predecessor FROM public.ml_consent_policies
     WHERE version = p_predecessor_version
       FOR UPDATE;
    IF predecessor.version IS NULL
       OR predecessor.grant_scope IS DISTINCT FROM 'training_only' THEN
        RAISE EXCEPTION 'TRAINING_POLICY_PREDECESSOR_UNKNOWN';
    END IF;

    -- The same call again: the successor exists and the predecessor was
    -- retired at exactly its start. configure_… then re-checks every other
    -- field (TRAINING_POLICY_IDEMPOTENCY_COLLISION on any difference).
    SELECT * INTO successor FROM public.ml_consent_policies
     WHERE version = p_consent_policy_version;
    IF successor.version IS NOT NULL THEN
        IF predecessor.retired_at IS DISTINCT FROM p_active_from
           OR successor.active_from IS DISTINCT FROM p_active_from THEN
            RAISE EXCEPTION 'TRAINING_POLICY_SUPERSEDE_COLLISION';
        END IF;
        registered := public.configure_mlc2_training_consent_policy_v1(
            p_approval_reference, p_approved_copy_sha256, p_toggle_copy,
            p_consent_policy_version, p_terms_version, p_privacy_policy_version,
            p_approving_authority, p_approved_at, p_jurisdictions,
            p_evidence_object_key, p_evidence_sha256,
            p_requires_processing_policy_version, p_active_from);
        RETURN registered || jsonb_build_object(
            'predecessor_version', predecessor.version,
            'predecessor_retired_at', predecessor.retired_at,
            'replayed', true);
    END IF;

    -- The predecessor is THE training policy in force now.
    IF predecessor.retired_at IS NOT NULL
       OR predecessor.active_from > now() THEN
        RAISE EXCEPTION 'TRAINING_POLICY_PREDECESSOR_NOT_ACTIVE';
    END IF;
    IF EXISTS (
        SELECT 1 FROM public.ml_consent_policies other
         WHERE other.grant_scope = 'training_only'
           AND other.version <> predecessor.version
           AND (other.retired_at IS NULL OR other.retired_at > now())
    ) THEN
        RAISE EXCEPTION 'ANOTHER_TRAINING_POLICY_IS_ACTIVE';
    END IF;

    -- The switch instant: not in the past (a yes already given under the
    -- predecessor would be retired after the fact), and after the
    -- predecessor began (0302's date check).
    IF p_active_from < now() THEN
        RAISE EXCEPTION 'TRAINING_POLICY_SWITCH_IN_THE_PAST';
    END IF;
    IF p_active_from <= predecessor.active_from THEN
        RAISE EXCEPTION 'TRAINING_POLICY_SWITCH_BEFORE_PREDECESSOR';
    END IF;

    -- A predecessor yes is treated as switched off (Privacy 3.5 §4a), and
    -- switching off deletes the training copies. This function deletes
    -- nothing: while any copy made under a predecessor yes is still active
    -- it refuses, and a person decides.
    IF to_regclass('public.training_corpus_items') IS NOT NULL THEN
        IF EXISTS (
            SELECT 1
              FROM public.training_corpus_items item
              JOIN public.ml_consent_events grant_event
                ON grant_event.id = item.training_grant_event_id
             WHERE grant_event.consent_policy_version = predecessor.version
               AND item.state = 'active'
        ) THEN
            RAISE EXCEPTION 'TRAINING_POLICY_PREDECESSOR_HAS_ACTIVE_COPIES';
        END IF;
    END IF;

    -- The door, for this row, in this transaction only.
    PERFORM set_config('willab.training_policy_supersede',
                       predecessor.version, true);
    UPDATE public.ml_consent_policies
       SET retired_at = p_active_from
     WHERE version = predecessor.version
       AND retired_at IS NULL;
    GET DIAGNOSTICS retired_rows = ROW_COUNT;
    PERFORM set_config('willab.training_policy_supersede', '', true);
    IF retired_rows <> 1 THEN
        RAISE EXCEPTION 'TRAINING_POLICY_PREDECESSOR_NOT_ACTIVE';
    END IF;

    -- The successor, through 0373's own registration and all its checks.
    registered := public.configure_mlc2_training_consent_policy_v1(
        p_approval_reference, p_approved_copy_sha256, p_toggle_copy,
        p_consent_policy_version, p_terms_version, p_privacy_policy_version,
        p_approving_authority, p_approved_at, p_jurisdictions,
        p_evidence_object_key, p_evidence_sha256,
        p_requires_processing_policy_version, p_active_from);
    RETURN registered || jsonb_build_object(
        'predecessor_version', predecessor.version,
        'predecessor_retired_at', p_active_from,
        'replayed', false);
END;
$$;

-- Rule 2 (tests/test_migration_security_rules.py). Browser roles call
-- nothing, and no runtime role either: the founder runs it by hand in the
-- SQL editor (as the owner), once per new training wording.
REVOKE ALL ON FUNCTION public.supersede_mlc2_training_consent_policy_v1(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT[], TEXT,
    TEXT, TEXT, TIMESTAMPTZ) FROM PUBLIC, anon, authenticated, service_role;

COMMENT ON FUNCTION public.supersede_mlc2_training_consent_policy_v1(
    TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TIMESTAMPTZ, TEXT[], TEXT,
    TEXT, TEXT, TIMESTAMPTZ) IS
    'Retires the training_only consent policy in force at p_active_from and '
    'registers its successor through configure_mlc2_training_consent_policy_v1, '
    'in one transaction (0458; founder D3, N68). Every yes under the '
    'predecessor reads as off from that instant. Deletes nothing. Run by hand.';

COMMIT;
