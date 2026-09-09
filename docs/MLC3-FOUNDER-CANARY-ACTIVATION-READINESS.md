# MLC-3 Founder Canary Activation Readiness

Status: local, pre-activation review packet. No production gate is changed by
this work.

## Scope

The canary is one exact `acquisition_principal_id` and one existing active
coach. It exercises the already released chain:

`rendered V3 feedback → immutable response → fresh exercise offer → video
render/playback → practice microphone capture → exact R2 audio → first-valid
selection → owner preference → separate blind source/practice confidence
judgments → randomized A/B comparison → post-blind inline guidance/exercise
draft → new reviewed catalogue version`

The source Take is `source_before_exercise`; only the later recording after
confirmed exercise playback is a practice attempt. The flow creates no outcome
label and does not infer improvement.

## Fail-closed readiness contract

`scripts/check_mlc3_founder_canary_readiness.py` is an aggregate, SELECT-only
check. It requires:

- the exact founder acquisition principal and its authenticated account;
- one current processing authorization and no block/open purge;
- one active coach allowlist row and that coach's canonical principal;
- exactly one approved `rushed_phrase_endings` need contract;
- a frozen catalogue snapshot (zero matching versions remains the honest
  coach-authoring path);
- the complete Feedback → offer → playback → practice → pair → blind review →
  inline authoring RPC surface, using an exhaustive registry of exact
  `regprocedure` signatures;
- RLS, ownership and direct-write closure on every registered canary table;
  exact RPC execution for `service_role`; no RPC execution or table writes for
  `anon`/`authenticated`; and no reachable internal/legacy writer;
- a complete table-specific zero-state inventory covering Feedback, offer,
  practice, transcription, pair, confidence/reveal, guidance/media/publication
  and inline-authoring families;
- no unresolved founder practice or coach-guidance media operation;
- both `personalized_exercise_recommendation` and `coach_review` operational,
  processing-authorizing and present on the same current receipt and policy;
- private, distinct R2 buckets and a fresh checksum-bound production manifest
  proving synthetic write/read/byte-hash/delete in both exact buckets; the
  manifest must carry the same pinned release-operator signature and a retained
  authenticated Cloudflare control-plane export proving public access, the
  `r2.dev` domain and custom domains are all disabled for both buckets;
- a fresh Ed25519-signed deployment attestation derived from retained
  authenticated Railway and Vercel API exports, covering the exact web,
  worker and monitor inventory and the exact frontend production build; the
  monitor entry must bind the reviewed five-minute schedule, start command,
  code hash, founder acquisition principal and expected disabled contract;
  the
  verifier trusts only the public key pinned in this release, so a locally
  fabricated internally consistent JSON document cannot pass;
- pre-activation operational evidence that the production monitor covers D2
  and D5 integrity failures plus unresolved practice/coach media writes, and
  that a synthetic alert reached both Sentry and the operations sink;
- a fresh idempotent emergency-disable rehearsal proving the database contract
  and the two backend plus two frontend gates are all disabled after the
  documented rollback command; the signed evidence must contain two complete
  attempt receipts with exact before/after targets, operation IDs, timestamps
  and result hashes; operation IDs must differ, attempt timestamps must be
  monotonic, and attempt two must begin only after attempt one completes from
  its disabled result;
- zero `dataset_eligible=true` records;
- backend and frontend serving/inline gates still disabled;
- dataset creation, training, evaluation and promotion still disabled.

The report may be ready for activation review while the reviewed catalogue has
no matching N1 exercise: the product must then return
`coach_exercise_requested`, and the coach can author a case-specific exercise
after completing the blind batch. A catalogue snapshot and approved need
contract are still mandatory; neither the browser nor a human judgment may
invent eligibility.

## Activation sequence after both reviews

The activation mutations are intentionally absent from this packet. After
ML/data and Engineering acceptance, a separately authorized change must, in
one controlled window:

1. activate `mlc3-first-client-service-v1` with the exact private practice and
   coach-video buckets;
2. add only the reviewed founder `acquisition_principal_id` to the database
   allowlist;
3. set backend `MLC3_PILOT_ENABLED=true`,
   `MLC3_COACH_INLINE_AUTHORING_ENABLED=true`, and the singleton
   `MLC3_PILOT_PRINCIPAL_IDS` value;
4. deploy frontend presentation flags
   `NEXT_PUBLIC_MLC3_PILOT_UI_ENABLED=true` and
   `NEXT_PUBLIC_MLC3_COACH_INLINE_AUTHORING_ENABLED=true`;
5. run one founder flow, inspect immutable event/recovery counts, then stop or
   continue the canary explicitly.

Rollback disables the frontend flags, both backend gates, and the database
contract. It does not delete or reinterpret immutable records.

## Learning boundary

Product service and collection do not activate learning. All collected records
remain product evidence with `dataset_eligible=false`. A later dataset release
requires its own immutable release review, acquisition-specific pooling checks,
withdrawal/deletion revalidation, speaker-disjoint partitioning and an approved
surface-specific supervision contract. Training, evaluation and promotion stay
disabled even during the founder canary.

## Evidence still required before activation review can pass

- Resolve and independently verify the founder's exact
  `acquisition_principal_id` and the reviewing coach email.
- Run the live R2 synthetic-object write/read/delete rehearsal in the exact two
  production buckets with `scripts/rehearse_mlc3_founder_r2.py` and retain its
  canonical manifest. Supply a retained authenticated Cloudflare control-plane
  export for the exact buckets; the command fails before writing unless both
  are verified private. Sign the result with the pinned operator key. This uses
  64 random bytes and no user content.
- Produce the Railway/Vercel deployment attestation from authenticated API
  exports, then sign it with the private release-operator key corresponding to
  `config/mlc3_founder_attestation_public_key.pem`. The private key must remain
  in the managed operator secret store and must never enter the repository.
  The manifest must enumerate every Railway production service, the exact
  backend/frontend commits, effective product/learning gates, and the exact
  Vercel production build-time public flags.
- Retain the monitor/Sentry synthetic-alert receipt and an idempotent
  emergency-disable rehearsal inside that same signed attestation. The monitor
  must be a real member of the authenticated Railway service inventory.
- Independently review, deploy and production-verify release migration 0325,
  `add_mlc3_founder_canary_security_closure.sql`. Until both
  lower-level service-role grants are absent in production, readiness must
  remain blocked.
- Run the SELECT-only readiness checker against production while every gate is
  still disabled.
- Run the focused PostgreSQL, backend route, frontend mapping/render, BFF and
  browser flow suites against the exact checksum-pinned snapshot.

No step in this packet allowlists a principal, activates a service, collects a
real recording, creates a dataset, trains, evaluates or promotes a model.
