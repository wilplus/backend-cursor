# Rooting Phrase Qualification V1 — Release Packet

## Scope

This package assigns the already accepted, checksum-pinned RPQ-V1 dependency
restoration and implementation to the backend release line. It does not change
the accepted product or ML/data semantics.

- Accepted backend implementation commit: `1b5f3e617295779b45f9771b2066a239eef25511`
- Accepted frontend implementation commit before rebase: `8c490b9774f73d896edf424c7296330a9920ac90`
- Accepted implementation-packet SHA-256 (unchanged):
  `aa8bf140a0d45a6299c92d1daa4166b75fc93acd2e2797d2d26527d3be7501a8`

## Assigned migrations

| Version | Migration | SHA-256 |
| --- | --- | --- |
| 0318 | `add_feedback_v3_serving_restoration.sql` | `6387fc933402b1a4379b221afbb51091ab9f0290b19c5fd566474056bc41c258` |
| 0319 | `add_mlc3_practice_foundation_restoration.sql` | `17a87a3fdb767c6f4fa704ba10e73b550b0986ca935be57d9af64d1ed8d26d6c` |
| 0320 | `add_mlc3_fresh_offer_and_paired_review_restoration.sql` | `402d342096fc6473fd90fb19b476809a25c347370c15c2a073ec1566d4ab2888` |
| 0321 | `add_rooting_phrase_qualification_v1.sql` | `b3d42dbe61e75989b7a75ddb392a6c6778914febaa85b2c921beb18e8f8fdc90` |

Manifest SHA-256:
`35ce296de36354622dff6f2cb9bba1884074781e0827ed18df1c0cbc63bae777`

## Release-only security adjustments

- Every newly introduced P2 and RPQ relation explicitly enables RLS in its
  defining migration in addition to the shared security loop.
- The trigger-only `advance_ideal_text_document_generation_v1()` function is
  explicitly non-executable by `PUBLIC`, `anon`, `authenticated`, and
  `service_role`.
- The structural gate test pins versions 0318–0321 while continuing to assert
  `serves_user=false` and `dataset_eligible=false`.

These are packaging and security declarations only. They do not alter the
accepted candidate, response, qualification, practice, or learning contracts.

## Verification

- Migration manifest: 321 contiguous migrations, 0001–0321; passed.
- Assigned migration apply/reapply on disposable PostgreSQL: passed.
- Combined dark-assignment, N1, V3, P1/P2 and RPQ PostgreSQL suite: 115 passed.
- Corrective RPQ PostgreSQL subset: 24 passed.
- Focused migration/security suite: 23 passed.
- Backend CI: 4,888 passed, 220 skipped, 113 subtests passed.
- Ruff: passed.
- mypy: passed.
- Frontend after rebasing onto the consent-gate hotfix: 1,506 passed;
  TypeScript and BFF checks passed.

## Runtime state

The release remains structurally disabled:

- RPQ serving/UI gates are false.
- Exercise serving, exposure, and real collection remain disabled.
- Persisted surfaces enforce `serves_user=false` and
  `dataset_eligible=false`.
- Dataset creation, training, evaluation, and promotion remain disabled and
  separately gated.

Production deployment of this package installs dark infrastructure only. A
separate reviewed activation is required before any user exposure or real data
collection.
