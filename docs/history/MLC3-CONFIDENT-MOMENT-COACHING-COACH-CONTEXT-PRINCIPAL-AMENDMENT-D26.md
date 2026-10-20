# MLC-3 Confident Moment Coaching Bundle — Coach Context Principal Amendment D26

Status: proposed narrow executable-interface correction; implementation remains
blocked pending independent ML/data and Engineering acceptance.

## 1. Parent and sole correction

D26 binds D25 (SHA-256
`81dfec670fb56584ee5f431a828e5de2aa8d55be29b7e18c43c6c5018aa0c2b0`)
and all accepted D3/D11–D24 parents. It changes only the coach-context wrapper's
acquisition-principal input. Every response shape, assignment binding,
blindness, lock, currentness, permission, deletion, non-learning and disabled-
gate clause remains unchanged.

D16 requires the coach GET route to make one database call, but its v1 SQL
signature also requires `p_acquisition_principal_id`. The coach request has no
authoritative acquisition principal, so the current application performs a
separate Project lookup before the wrapper. Browser input cannot close this
gap, and two application reads cannot provide one serialized snapshot.

## 2. Database-derived principal wrapper

Add the sole runtime wrapper:

```text
project_confident_moment_coach_authoring_context_v2(
  p_project_id uuid,
  p_reviewer_principal_id uuid,
  p_idempotency_key text
) -> jsonb
```

Under D11/D25 locks, PostgreSQL derives the exact acquisition principal from
the immutable current Project ownership and D4 rollout/enrollment lineage. It
then revalidates that principal, the two required service purposes, reviewer
authority, deletion state, batch/reveal/assignment bindings and every D16–D25
leaf before returning the exact closed coach context.

The request/browser never supplies, selects or overrides the acquisition
principal. A missing, ambiguous, foreign, stale or changed Project/principal
lineage fails closed. The derived identity enters the context/idempotency hash;
an identical key cannot replay across a changed principal.

The v1 four-argument wrapper is removed from runtime reachability: revoke it
from `PUBLIC`, `anon`, `authenticated` and `service_role`. It may delegate
internally only if v2 supplies the database-derived identity; no application
caller remains.

## 3. Exact application caller

The route `GET /v2/coach/guidance/batches/{arc_id}` makes exactly one database
request through:

```text
services/confident_moment_bundle_repository.py::
  ConfidentMomentBundleRepository.project_coach_authoring_context
  -> project_confident_moment_coach_authoring_context_v2
```

The repository method accepts only Project ID, authenticated reviewer principal
ID and idempotency key. `routes/v2/coach_guidance_delivery.py` performs no
Project identity lookup or supplemental canonical table read in the Bundle
branch. The database response is validated and passed through exactly.

## 4. Regressions

1. The Bundle coach GET performs one RPC and no Project/table lookup.
2. Exact current Project/principal/reviewer returns the frozen D16–D25 context.
3. Browser or query acquisition-principal fields are rejected/ignored before
   authority and never reach SQL.
4. Foreign, missing, ambiguous, changed or deleted Project ownership and stale
   enrollment/service purpose fail with no context or authoring write.
5. A principal change racing projection in both commit orders yields one fully
   validated old snapshot before the writer proceeds or typed retry/failure;
   never a mixed context.
6. v1 is not executable by any runtime role; signature/caller audits require
   exactly the v2 tuple and reject the former two-call application path.

## 5. Boundaries

The wrapper is fixed-search-path `SECURITY DEFINER`, executable only by
`service_role`; private helpers remain inaccessible. It creates no product,
judgment, dataset or learning row. All Bundle, rooting, PAM, serving,
collection, dataset, training, evaluation and promotion gates remain disabled.

`VERDICT: D26 PROPOSED FOR ML/DATA AND ENGINEERING INTERFACE REVIEW`
