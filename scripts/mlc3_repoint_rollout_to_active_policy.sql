-- Re-point the MLC-3 coaching rollout at the processing policy in force.
-- Run BY HAND in the Supabase SQL Editor, right after a policy is activated.
-- Deliberately NOT in migrations/manifest.txt: a rollout change is a founder
-- act, like publishing the policy itself.
--
-- ── WHY THIS EXISTS (founder 2026-09-28) ────────────────────────────────
--
-- `activate_phase1_policy_v1` retires the old policy. Nothing moves the
-- coaching rollout with it: `mlc3_service_rollout_revisions.required_policy_id`
-- keeps naming the retired version. The dual-purpose resolver then compares
-- every NEW receipt (for the active policy) with the rollout's required
-- policy, they differ, and every person who accepted the new policy gets
-- MLC3_DUAL_PURPOSE_AUTHORITY_REQUIRED — coach exercises stop matching to
-- their recordings with no user-visible error.
--
-- That is what happened after phase1-2026-09-23 went live on 2026-09-24:
-- rollout revision 2 still required phase1-2026-09-20 until the founder ran
-- this block on 2026-09-28 (revisions 3 halted, 4 generally_available).
--
-- ── WHAT IT DOES ────────────────────────────────────────────────────────
--
-- Two revisions in ONE transaction, so a failure changes nothing:
--   1. halt_mlc3_service_rollout_v1 — `register_mlc3_general_rollout_v2`
--      only accepts a rollout that is disabled or halted;
--   2. register_mlc3_general_rollout_v2 — generally available again, with
--      the SAME activation-risk decision, capacity policy and version map as
--      the last generally available revision, now requiring the active
--      policy. Nothing the founder approved is changed but the policy.
--
-- Enrollments re-bind by themselves: the next Take calls
-- `ensure_mlc3_service_enrollment_v2`, which binds to the newest rollout
-- revision and the person's newest receipt.

-- ── CHECK FIRST (read-only) ─────────────────────────────────────────────
-- Run the next query alone. Only continue when it returns ONE row with
-- needs_repoint = true. False: the rollout already requires the active
-- policy, and there is nothing to do.

SELECT rr.revision_number, rr.rollout_state,
       required.version AS required_policy,
       active.version   AS active_policy,
       rr.rollout_state = 'generally_available'
         AND rr.required_policy_id IS DISTINCT FROM active.id AS needs_repoint
  FROM public.mlc3_service_rollout_revisions rr
  LEFT JOIN public.processing_policy_versions required
    ON required.id = rr.required_policy_id
  CROSS JOIN LATERAL (
      SELECT id, version FROM public.processing_policy_versions
       WHERE status = 'active' ORDER BY activated_at DESC LIMIT 1
  ) active
 ORDER BY rr.revision_number DESC
 LIMIT 1;

-- ── RE-POINT (writes; run once) ─────────────────────────────────────────
-- The activating user is the founder account; change the email only if
-- someone else is signing.

BEGIN;

SELECT public.halt_mlc3_service_rollout_v1(
  'Repoint the coaching rollout to the active processing policy',
  encode(extensions.digest(
    'mlc3-repoint-' || (SELECT version FROM public.processing_policy_versions
                         WHERE status = 'active'
                         ORDER BY activated_at DESC LIMIT 1),
    'sha256'), 'hex')
);

SELECT public.register_mlc3_general_rollout_v2(
  (SELECT id FROM public.processing_policy_versions
    WHERE status = 'active' ORDER BY activated_at DESC LIMIT 1),
  prev.activation_risk_decision_id,
  prev.capacity_policy,
  prev.policy_versions,
  (SELECT id FROM auth.users WHERE email = 'artur@willonski.com'),
  now(),
  encode(extensions.digest(
    'mlc3-repoint-' || (SELECT version FROM public.processing_policy_versions
                         WHERE status = 'active'
                         ORDER BY activated_at DESC LIMIT 1),
    'sha256'), 'hex')
)
FROM (
    SELECT * FROM public.mlc3_service_rollout_revisions
     WHERE rollout_state = 'generally_available'
     ORDER BY revision_number DESC
     LIMIT 1
) prev;

COMMIT;

-- ── VERIFY (read-only) ──────────────────────────────────────────────────
-- Expect the newest row generally_available and requiring the active
-- policy, the one below it halted.

SELECT rr.revision_number, rr.rollout_state, p.version AS required_policy
  FROM public.mlc3_service_rollout_revisions rr
  LEFT JOIN public.processing_policy_versions p ON p.id = rr.required_policy_id
 ORDER BY rr.revision_number DESC
 LIMIT 3;
