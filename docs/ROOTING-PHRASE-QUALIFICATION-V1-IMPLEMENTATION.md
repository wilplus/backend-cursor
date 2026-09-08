# RPQ-V1 dependency restoration and local implementation review packet

Status: checksum-pinned corrective local implementation for ML/data re-review.
The exact response-boundary candidate/membership/exposure provenance finding
and all earlier findings are addressed. All runtime and UI gates are
structurally disabled. The migrations are pending and unassigned. This packet
authorizes nothing.

## Review bases and accepted design

- Backend base: `0dcce9be57e3be9a60f232b4aa05e46fc9f31bd5`
- Frontend base: `57fa0ad9f40470ca8fb5a813da3027dc4bfdaf1b`
- Accepted design: `ROOTING-PHRASE-QUALIFICATION-V1-DESIGN.md`
- Accepted design SHA-256:
  `73cf48f9ba012bd77f14536b39827a03358d29d751f497acc137cef60f2b5f50`
- Design source used for this local snapshot:
  `/private/tmp/willab-feedback-provenance-backend/docs/ROOTING-PHRASE-QUALIFICATION-V1-DESIGN.md`

`RPQ-PRODUCT-DELTA-1` is excluded. The V3 Manager budget is unchanged: one
selected Confident Voice item per applicable valid Slide-bounded approximately
75-word block; Take 1 remains confidence-only; Take 2+ may additionally include
at most one global rewrite and one global praise.

## Backend checksum pin

| File | SHA-256 |
|---|---|
| `migrations/pending/add_feedback_v3_serving_restoration.sql` | `55759bc243ed2512d7dbd2c9b3d9912bcf600b4ad117a50b22426d6a1c54a065` |
| `migrations/pending/add_mlc3_practice_foundation_restoration.sql` | `228e6b3026dbd711af72f4b99a6f7a446f441f2f16fa3d55cebb80915afb05ff` |
| `migrations/pending/add_mlc3_fresh_offer_and_paired_review_restoration.sql` | `f110244124d2c30154e78eb37ff5d7dfe0f2a08162d1a5caf622ba66e0d3439d` |
| `migrations/pending/add_rooting_phrase_qualification_v1.sql` | `18c4a906fe0f15e848cb779f1cd88e21a30e3a02e6315e48e64610918281ce24` |
| `tests/integration/rpq_restoration_prerequisites.sql` | `c0aa046f3b1e3b2d37632d19afb132762abb367889ae1d3a5b3e1ad5b787dcf0` |
| `tests/test_rooting_phrase_qualification_postgres.py` | `cff03852cec4897524c56b7e4d0c1c90ed87c9b61bcd7cc255c8c5f252b94181` |
| `tests/test_rooting_phrase_qualification_v1.py` | `502d22db10ef48a017eb9bf28ea84128dcff25dcd20a6c25b8077b5fead41eb6` |
| `services/rooting_phrase_qualification_v1.py` | `52ca92c3eb327b74eb6b6f83ededc222a2fb9f7cc34af7932f477c42ba7603c4` |
| `routes/v2/rooting_phrase_qualification.py` | `6da183e86c5e959282c3cdd999ce95e43a82e7047c76307d564628b848942b04` |
| `routes/v2_routes.py` | `bf57093d1a0d7940f775eaa90c130a454d4df17e4749c8e8ee950ce01a830938` |
| `services/data_purge_registry.py` | `e50526104e5d026587a5a6f1fbd9008ff3d6c6009880122fe9356c7d117e5d7b` |
| `tests/test_phase1_deletion_completion.py` | `ddfb302c2fd5ec9ff94fd804bac69fc16ef94a8ac27596bc0a1d7ac09db34c1b` |
| `services/feedback_data_contract.py` | `778d56342d1d5ad1bcd8f9db91fe957625a9cd4ea055470235b87566e6887532` |
| `services/take_feedback_responses.py` | `7d243d522bbae8d247de9401bc9f7049c68abb1ac1ab7772a62bf783af0e57c5` |
| `services/db.py` | `deb369d94cb908d9651005801455d681d7292482f6c14fc511f907b44e229219` |
| `routes/v2/user_sessions.py` | `987b5d795f88724fb6e1eca0290649483663439a5a81d0c32b9d4224a19acd4c` |
| `routes/v2/explore_ideal_text.py` | `ff75879dbe55f5378674e1fe00fae60c92dbb32e24f3e8fd177f0fc57eb4822e` |
| `tests/test_feedback_data_contract.py` | `cd73997cabead3dc14996cdf780b7ff7ffa9dab9fcf1b43a53ab468aafa79018` |
| `tests/test_take_feedback_responses.py` | `a34d4f753e5d321cb888a42d138634d980bb4d894668967841f924a8f94ebab6` |

## Frontend checksum pin

| File | SHA-256 |
|---|---|
| `src/components/willab/DeckChunkModal.tsx` | `f003f069c37ca1048253eeae2bec3b9f906764b71fcd727f5a530805fb406583` |
| `src/components/willab/DeckLockMark.tsx` | `21e89aca4d235eae9fd3ba434e06205280c18a1ab888fe18110068c098b9136f` |
| `src/components/willab/deckSurface.test.ts` | `85c3df271ba478e5cb561ef0af515f2fa705d16053c961954ad2417166687098` |
| `src/components/willab/RootingPhraseQualificationActions.tsx` | `3a1d24a2755619fe0599c68e0b9d426bae90ec78db353497daa2316226f2aa34` |
| `src/lib/willab/rootingPhraseQualification.ts` | `d916bb6aa1943aaf6f1c469f97f44d6ba66fe8af8ac63778f43eaaea992d9354` |
| `src/lib/willab/rootingPhraseQualification.test.ts` | `4a2ebf7cd4fc20b2d4207ade7e0cc5e9bf746cac553ddc65e750f310875d870d` |
| `src/services/api/idealText.ts` | `49b8fe3346605e3e24856d0c170d796ef6946d048964a3e6ad8057d6668ef209` |
| `src/services/api/takeFeedback.ts` | `aa0f2e9caba05420d51bfde86b99acd3594f44debb3a483e6c29ea29e7674876` |
| `src/services/api/takeFeedback.test.ts` | `ca7d6f49a0334032f23095a6328c0ddd89b05400923ca9ec162acd64cd280189` |

## Restored dependency contracts

### Feedback V3

- Immutable, complete Manager candidate membership with selected and typed-
  excluded candidates.
- Exact principal, Project, Take, recording, snippet, interval, evidence and
  current Ideal Text content identity.
- Five-state owner responses remain separate; only exact `confident_yes` can
  support the unchanged Confident Voice RPQ path.
- A live-membership helper revalidates the entire source pool and document
  after blocking waits and on replay.

### MLC-3 P1 practice

- Fresh-offer-only session origin; dark assignments cannot be converted.
- Operation-specific `practice_processing` authority, current source and purge
  checks before and after contention.
- Durable pre-write recovery with `local_synthetic` as the only permitted
  storage provider.
- Exact practice Recording Attempt and audio-object hash, server-derived
  transcript/attempt/measurement/validity hashes, and immutable raw evidence.
- Revisioned first-valid selection; an unresolved earlier attempt remains
  pending rather than being silently skipped.

### MLC-3 P2 service and review

- Complete fresh-offer inventory and deterministic nearest-compatible
  exercise selection from the accepted N1 snapshot.
- Offer assignment, delivery, rendered exposure and playback remain distinct;
  exposure/playback event kinds are rejected in this disabled slice.
- Exact before/first-valid-after pairs, immutable randomized order, independent
  five-state preference and cross-session reviewer-context history.
- Honest no-match offers can create a request and authoring draft only after an
  exact blind Confidence judgment and post-judgment reveal. Drafts do not
  publish catalogue exercises.

## RPQ-V1 contracts

- The phrase is derived from the exact selected Manager candidate and its exact
  evidence span. The Manager quote and evidence exact text must both exist and
  be identical. For rewrite candidates, the Manager proposed text and evidence
  replacement text must both exist and be identical. `COALESCE` fallback is not
  used. Another substring from the same Paragraph is rejected.
- Accepted rewrite origin requires both the exact owner's immutable
  `accept_proposed` correction decision and the canonical `user_edit` Paragraph
  revision from that exact Take. At response time, the canonical decision RPC
  freezes the selected `candidate_id`, a canonical output SHA-256 and
  `feedback-candidate-output-v1`; the database binds candidate and evidence with
  a composite foreign key. Historical evidence-only decisions remain preserved
  but cannot authorize RPQ. The accepted decision must be the current leaf of
  its immutable `supersedes_id` chain; a later `keep_original` invalidates it.
  The exact decision chain is serialized through the boundary so a concurrent
  revision cannot race root creation. Candidate ID, evidence ID, exact proposed
  output, current decision ID and Paragraph revision all participate in the
  frozen content identity. Manual origin requires a canonical `user_edit`
  revision and may not be declared from a baseline row.
- Candidate identity is deliberately strict: regenerating an identical wording
  creates a distinct output hash because the hash includes the candidate ID and
  its complete immutable generation envelope. It requires a new explicit user
  response and never inherits an earlier candidate's acceptance.
- The response boundary no longer resolves a reusable `candidate_key`. The
  client submits the opaque candidate ID together with its exact frozen V3
  membership and canonical exposure IDs. PostgreSQL resolves that exact tuple
  inside the exact Take, Project, owner and current content snapshot, and
  requires the membership item and exposure to be selected at the same frozen
  position. The historical key-only RPC signature is revoked and always fails.
- Decision idempotency includes candidate, membership and exposure IDs. Two
  regenerated sets may reuse the same display key without colliding: stale A
  cannot bind B, explicit B creates a distinct decision, and exact B replay
  returns the same immutable decision.
- Runtime roles can read correction decisions but cannot write the table
  directly. All new correction decisions go through the canonical validating
  RPC, whose idempotent replay checks the exact candidate/output binding.
- Paragraph lock and root activation remain distinct product actions. The
  combined owner control updates the authoritative `ideal_text_part.locked_at`,
  writes its canonical lock revision and writes the separate root action in one
  transaction. Any failed root write rolls the canonical lock back.
- Lock/root metadata updates preserve the immutable Ideal Text content identity;
  wording, order or Paragraph identity changes still advance the document
  generation and invalidate stale RPQ work.
- Exact content version, Manager item, Slide/block, text span, semantic result,
  current source/audio lineage and live processing authority are revalidated on
  creation, replay, after advisory locks and immediately before activation.
- Re-record activation additionally invokes the authoritative live-practice
  helper after contention and verifies the exact selected attempt/audio hash.
- Unchanged Confident Voice requires the exact selected item and exact
  `confident_yes` response.
- Accepted rewrite/manual wording requires the first valid exact re-recording;
  `capture_valid` is technical routing only and is not confidence or
  improvement.
- Project goal and Slide context are frozen server-side from the authoritative
  Project and immutable Ideal Text document snapshot. Semantic execution must
  reference that exact input snapshot; callers cannot supply goal/context
  hashes, and cross-content or cross-project input reuse fails closed.
- Semantic uncertainty requires an independent owner routing action. Those
  actions are excluded from judgments, preference pairs and all learning
  surfaces.
- One active root per V3 block, immutable replace/remove history, honest Slide
  pending state, and no fabricated root fallback.
- Core root state exposes no score and remains product provenance only.

## Stable first paint

The bookmark control is rendered beside every Paragraph from the initial core
document paint. Optional feedback enrichment may change its fill or attention
state, but never its presence. The RPQ controls and route are compiled in only
as typed placeholders and return nothing while their hard constants remain
false.

## Verification evidence

- Fresh disposable PostgreSQL apply: passed.
- Populated-database reapply of all four pending migrations: passed.
- Combined dark-assignment, N1, V3, P1/P2 and RPQ PostgreSQL suite:
  **115 passed**.
- Corrective RPQ PostgreSQL subset: **24 passed**. It covers Manager phrase A/B
  rejection, quote/evidence disagreement, proposed/replacement disagreement,
  exact-candidate acceptance, two frozen sets reusing one candidate key, stale
  A versus explicit B response isolation, exact B replay,
  regenerated-identical-candidate rejection,
  `accept_proposed` superseded by `keep_original` including during contention,
  declared rewrite/manual rejection, exact-Take rewrite identity, server-derived
  semantic inputs, cross-project semantic reuse, canonical-lock rollback,
  expiry/withdrawal/deletion, and direct/re-record contention.
- RPQ and deletion static suites: **27 passed**.
- Backend official `scripts/local_ci.sh`: **4,888 passed, 220 skipped, 113
  subtests passed**; manifest, runner tests, Ruff and mypy passed.
- Frontend focused exact-response/RPQ suite: **41 passed**; TypeScript and BFF
  boundary checks passed.
- Frontend TypeScript and BFF boundary checks passed. The unchanged full
  frontend suite completed **1,467 tests in 133 files**, but Vitest reported
  three worker-start errors in unrelated jsdom suites under the host's Node
  20.19.3 (`webidl.util.markAsUncloneable` unavailable); it is therefore not
  represented as a clean full-suite pass.
- `git diff --check`: passed in both repositories.

## Known limitations and hard gates

- All four migrations remain under `migrations/pending/`; the release manifest
  is unchanged.
- `RPQ_V1_RUNTIME_ENABLED = False` and `RPQ_V1_UI_ENABLED = false` are compile-
  time hard stops. The backend routes return `404 RPQ_V1_DISABLED`.
- Practice storage accepts only `local_synthetic`; live R2 is not registered.
- No offer delivery, render confirmation, playback or real microphone capture
  is possible.
- Semantic execution, live adapters, real content collection, production coach
  access and catalogue publication are not implemented or authorized here.
- No dataset, training, model evaluation or promotion path reads these rows.
- No migration number, commit, push, merge, deployment, activation or
  production data operation is included.

## Corrective review request

> **ML/DATA IMPLEMENTATION RE-REVIEW REQUEST — RPQ-V1 exact response-boundary
> candidate/membership/exposure provenance**
>
> Review this checksum-pinned corrective snapshot against accepted design
> SHA-256 `73cf48f9…2b5f50`. Verify that Manager quote equals evidence exact text,
> Manager proposed text equals evidence replacement text, and no fallback can
> substitute one for the other. Verify that the canonical response RPC freezes
> the exact selected candidate ID, frozen V3 membership ID and exposure ID plus
> canonical generated-output hash/version at decision time, and that RPQ
> requires this exact binding. Two candidate sets may reuse one candidate key:
> a stale A response must not bind B, explicit B must create a distinct decision,
> and exact replay must be idempotent. Confirm the key-only RPC is inaccessible
> and decision idempotency includes the exact candidate/membership/exposure.
> Verify that accepted rewrite authority uses the current
> unsuperseded immutable correction-decision revision and exact-Take canonical
> `user_edit` revision, including when a later `keep_original` commits during
> contention. Confirm the previously accepted authoritative lock, live
> authorization, semantic-input, deletion and disabled boundaries remain intact.
>
> No migration assignment, push, deployment, activation, real collection,
> datasets, training, evaluation or promotion is authorized.

After ML/data acceptance, request an independent Engineering implementation
review of the same checksum-pinned snapshot, including concurrency,
idempotency, RLS/RPC permissions, apply/reapply and rollback safety.

```text
VERDICT:  ADVANCE-F1-SURFACE after independent re-review
CATEGORY: F1-SURFACE
WHY:      Exact Manager content, canonical lock, live authority and semantic
          provenance now fail closed without weakening the V3 budget.
REDIRECT: Obtain ML/data re-review, then Engineering implementation review;
          keep every gate disabled.
```
