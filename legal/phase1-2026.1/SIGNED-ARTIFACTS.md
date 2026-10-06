# Signed artifacts — what exists, and its fingerprint

The database registers each determination **by reference**: only `object_key`
and `sha256` reach `processing_legal_artifacts`. This file is the one place
that records which signed PDF is current, what its fingerprint is, and which
commit its markdown source was rendered from — so that "is the thing we
registered the thing we signed?" is a lookup rather than an investigation.

**The `sha256` is over the signed PDF's bytes as uploaded.** Not the markdown,
not the unsigned render. A PAdES signature is an incremental update appended to
the file, so signing changes the bytes and therefore the hash; the hash of the
unsigned render is never the right value.

## Current

| # | `object_key` | signed | `sha256` of the signed PDF |
|---|---|---|---|
| 01 | `phase1-2026.1/legal/product-legal-approval-v1.0.pdf` | 2026-09-19 | `2ca882c4314d7e1b805940c0f5af50b7736b7b2cfa5dc63704a4fb0c99784a6b` |
| 02 | `phase1-2026.1/legal/power-score-classification-v1.0.pdf` | 2026-09-22 | `9e31dd4105a2dcb1394c6bf22b700ca418df9b9b123cdd837df06af3cbdfbdc5` |
| 03 | `phase1-2026.1/legal/article-50-assessment-v1.0.pdf` | 2026-09-22 | `f79a5114e0047ca8b15a60b77023cde5bab79669f510120a8166f82359d70fc3` |
| 06 | `phase1-2026.1/legal/retention-schedule-v1.0.pdf` | 2026-09-19 | `73d078ea110c4419fc1c8b5322f90881716e66141cac5fa3a4221f0aa72a0c69` |
| 13 | `phase1-2026.1/legal/training-consent-wording-v1.pdf` | 2026-10-01 | `b1ec620ea7a8c85d8b351a7e1eadc31c81b52bfffc4cd0c7d4897053b0ce1632` |
| 02 v1.1 | `phase1-2026.1/legal/power-score-classification-v1.1.pdf` | 2026-10-02 | `e00536d02779d4687a02817348b978b8c4702b7e16bc5c51c102e4f4f2ac2ade` |
| 06 v1.2 | `phase1-2026.1/legal/retention-schedule-v1.2.pdf` | 2026-10-02 | `b0439d1847e4eff0d5e8eedc8efd3dcbed8317f9731e7319a91ec7abf529f479` |
| 06 v1.3 | `phase1-2026.1/legal/retention-schedule-v1.3.pdf` | 2026-10-05 | `59a25f9409e85e2289e8484baa4cc0fc74d5c6ed98dca2d22be443175473cfb4` |
| 06 v1.4 | `phase1-2026.1/legal/retention-schedule-v1.4.pdf` | 2026-10-05 | `f3a19127bd586913ebe5c0a1f2a97c5e24646c8e1fb44e3fef312346200afee6` |
| 03 v1.1 | `phase1-2026.1/legal/article-50-assessment-v1.1.pdf` | 2026-10-05 | `97a88b6946957e5849c3fa80b3a39d6c480d35080b7b4fa792d768f85667ad6c` |

`02 v1.1` and `06 v1.2` were rendered by `scripts/render_doc_pdf.py` on
2026-10-02 (unsigned sha256 `dc175ffc…c40e8` and `cec455cb…dc85c`) and signed
at 15:53:48 UTC the same day (PAdES, `/ETSI.CAdES.detached`); the founder sent
the signed files to the session on 2026-10-02, 141,626 and 112,482 bytes. In
each the unsigned render is a byte-identical prefix of the signed file, so
what was signed is exactly what was rendered. **Both are registered in
`processing_legal_artifacts` as of 2026-10-02** by their hashes: `02 v1.1`
under `(power_score_classification, 1.1)`, `06 v1.2` under
`(retention_schedule, 1.2)` with the five rules of `data_retention_rules`
pointing at it (the two scripts named below, run by the founder that day).
The upload of each signed file to its `object_key` is the founder's; the
hashes are of the signed files as received by the session. `02 v1.0` and
`06 v1.0` are superseded by version (their signatures stand for their
versions, 04 §5).

`01` and `06` were rendered from markdown that is byte-identical at
`6f7ded6`, so those signatures stand and nothing about them needs redoing.

`13` was rendered by `scripts/render_doc_pdf.py` on 2026-10-01 08:35 UTC and
signed at 09:02:46 UTC (PAdES, `/ETSI.CAdES.detached`, the qualified seal in
the founder's name). The unsigned render (sha256 `121f2da8…775d2a`) is a
byte-identical prefix of the signed file, so what was signed is exactly what
was rendered. Uploaded by the founder on 2026-10-01 11:20 CEST to the R2
bucket `coach-feedback-videos` (the backend's main bucket, `R2_BUCKET_NAME`)
at exactly that `object_key`, 108,961 bytes, `application/pdf`. The hash
above is the value `configure_mlc2_training_consent_policy_v1` took at
09:08 UTC the same day.

`02` and `03` were rendered by `scripts/render_doc_pdf.py` and
signed on 2026-09-22 at 21:02:08 UTC. Both signatures are PAdES
(`/SubFilter /ETSI.CAdES.detached`), and in each case the unsigned render is a
**byte-identical prefix** of the signed file — so what was signed is exactly
what was rendered, with the signature appended and nothing altered beneath it.

**All four rows now carry a hash.** That removes the blocker `04` §5 names, and
it removes only that one. Two things it does NOT do, both worth saying here
because this table is what people check:

- **It does not make either determination counsel-reviewed.** Both `02` and `03`
  still say so on their own first page. The re-signature fixed a citation and a
  path count; it changed no determination.
- **It does not clear `02`'s own condition**, which is the operative one now:
  the determination is *"conditional on counsel confirming before any person
  other than the founder records."* Registering the policy and letting a
  non-founder record are different acts, and only the first is unblocked.

The signed PDFs still have to reach `object_key` in storage. A hash recorded
here against a file nobody uploaded is a claim, not a record.

## Signed 2026-10-02 (closed; rendered and signed the same day)

Two renders made on 2026-10-02 for the founder's PAdES signature, by
`scripts/render_doc_pdf.py` from the markdown in the same commit as this
table. The founder signed the content in chat the same day ("I sign it all",
decisions log N24). The hash of the **unsigned** render is recorded so that
the signed file can be checked to be that render plus a signature and nothing
else (the byte-identical-prefix test above); it is never the value to
register.

| # | `object_key` | source | `sha256` of the UNSIGNED render |
|---|---|---|---|
| 02 v1.1 | `phase1-2026.1/legal/power-score-classification-v1.1.pdf` | `02-power-score-classification-v1.1-DRAFT.md` | `dc175ffc54b88a81155bdce439a40785bdabb783454f19d4408838c2641c40e8` |
| 06 v1.2 | `phase1-2026.1/legal/retention-schedule-v1.2.pdf` | `18-retention-schedule-v1.2-blind-check-and-lending-DRAFT.md` | `cec455cb8e7e65af5ca40787f0b07f5ce9d45496b2e4e44eee10bbbb4d4dc85c` |

Both were signed at 15:53:48 UTC on 2026-10-02 and their hashes are in the
**Current** table. The 3.3 publish (`scripts/phase1_policy_publish_3_3.sql`)
carries a provisional reference for 02 until the registration script runs,
as the 3.2 publish did. Neither signature makes either document
counsel-reviewed; both say so on their first page.

## Signed 2026-10-05 (closed; rendered and signed the same day)

One render made on 2026-10-05 by `scripts/render_doc_pdf.py` from the
markdown in the same commit as this table. The founder decided the period in
chat that day ("It should be kept for 5 years", decisions log N43). The hash
of the **unsigned** render is recorded so that the signed file can be checked
to be that render plus a signature and nothing else; it is never the value to
register.

| # | `object_key` | source | `sha256` of the UNSIGNED render |
|---|---|---|---|
| 06 v1.3 | `phase1-2026.1/legal/retention-schedule-v1.3.pdf` | `19-retention-schedule-v1.3-financial-records-DRAFT.md` | `9a94ebe930f68db2a6e8959859af5019d6feb479672ecb87f41de1ac43a2c046` |

Signed at 13:42:28 UTC on 2026-10-05 (PAdES, `/ETSI.CAdES.detached`, the
trusted signature in the founder's name); the founder sent the signed file to
the session the same day, 110,851 bytes. The unsigned render (67,131 bytes)
is a byte-identical prefix of the signed file, so what was signed is exactly
what was rendered. Its hash is in the **Current** table and in
`scripts/phase1_retention_rules_v1_3.sql`. **Registered in
`processing_legal_artifacts` as of 2026-10-05** under `(retention_schedule,
1.3)`, with `financial-evidence-v1` active in `data_retention_rules` pointing
at it (the script, run by the founder that day; its verify query returned the
one row). `financial_evidence` now resolves, so an account erasure no longer
stops on `token_ledger` or `llm_usage` rows. The upload of the signed file to
its `object_key` is the founder's. The signature does not make the document
counsel-reviewed; it says so on its first page.

## Signed 2026-10-05, evening (closed; rendered and signed the same day)

Two renders made on 2026-10-05 by `scripts/render_doc_pdf.py` from the
markdown in the same commit as this table, for the founder's PAdES signature:
the founder's answers Q15 A and Q22 A (decisions log N48.4), signed as D1 A
and D2 A on the Wave 3 sign-off page. The hash of the **unsigned** render is
recorded so that the signed file can be checked to be that render plus a
signature and nothing else; it is never the value to register.

| # | `object_key` | source | `sha256` of the UNSIGNED render |
|---|---|---|---|
| 06 v1.4 | `phase1-2026.1/legal/retention-schedule-v1.4.pdf` | `20-retention-schedule-v1.4-product-records-and-job-evidence-DRAFT.md` | `5dea1acf97cf4fa01df9966f5ca08f1c0680450b16338a14a159d7c4abbedd07` |
| 03 v1.1 | `phase1-2026.1/legal/article-50-assessment-v1.1.pdf` | `03-article-50-assessment-v1.1-DRAFT.md` | `2eb9c3f1efa9262ed7cb8e2b570797e591fa92d6132f7a6727f2623f0494ad08` |

Both signed at 20:05:07 UTC on 2026-10-05 (PAdES, `/ETSI.CAdES.detached`,
the trusted-signature seal, "Minister do spraw informatyzacji - pieczęć
podpisu zaufanego"). The signed files are 127,109 bytes (06 v1.4) and
132,605 bytes (03 v1.1); the unsigned renders (83,678 and 89,174 bytes) are
byte-identical prefixes of them, so what was signed is exactly what was
rendered. In each, the signature's ByteRange covers the whole file and the
CMS messageDigest equals the sha256 of the signed byte ranges. The session's
poppler `pdfsig` reports "Signature is Invalid" for this seal, exactly as it
does for the registered 02 v1.1 and 06 v1.3 files: the session verified the
prefix and the document digest, not the seal's certificate chain. Their
hashes are in the **Current** table.

**Not yet registered.** The upload of each signed file to its `object_key`
is the founder's. Then `03 v1.1` is registered under
`(article_50_assessment, 1.1)` by `scripts/phase1_register_article_50_v1_1.sql`,
and `06 v1.4` under `(retention_schedule, 1.4)`, with its two rules, by
`scripts/phase1_retention_rules_v1_4.sql`, which runs only after the purge
change and its job-plumbing grant (0424 and 0425) are deployed: the
script's header says why. Both scripts carry these hashes; check the
uploaded objects against them before running. `03 v1.0` and `06 v1.3` stay
signed for their versions (04 §5). Neither signature makes either document
counsel-reviewed; both say so on their first page, and both are put to
counsel (`21-counsel-questions-2026-10.md`, questions 2 and 3).

## Why 02 and 03 were re-signed (closed 2026-09-22)

Neither is a change of substance to what the founder decided. Both are
corrections that would have made a signed document say something untrue.

- **02** — #555 corrected §9's citation to `e5e02d6` (#544).
  That is the commit which renamed the band labels, in the section a lawyer is
  most likely to check, and the old citation resolved in neither repository. A
  determination citing a commit nobody can follow is worse than one more
  signature. The determination itself — `false` on all three booleans, not
  high-risk, not prohibited, conditional on counsel confirming before any
  person other than the founder records — is unchanged.
- **03** — an intermediate draft claimed the Article 50(2) marking covered
  "both export paths the product controls". There are four
  (`docs/AI-CONTENT-MARKING-PROPOSAL.md` §1), one of which was unmarked at the
  time. §3 now carries the four-path table, and the open `text/plain` decision
  is recorded as open rather than settled.

## Superseded — never register these

Kept so that a signed file found later can be identified rather than trusted.

| # | `sha256` | why it is not current |
|---|---|---|
| 01 | `e4d2abc23b4d8d81…` | signed over a render that read "STATUS: DRAFT — NOT APPROVED, NOT SIGNED" with a blank signature block |
| 02 | `a0eb28c47b2ffcd6…` | same defect, plus `emotion_intention_inference` still `[[COUNSEL]]` in the metadata while §9 ticked `false` |
| 02 | `a7e4bfce8eaeac2d9ed831003241047d22af03cc6b82a8b00064effbb1c86add` | correct in every other respect; superseded only by the citation fix to `e5e02d6` |
| 03 | `b7d366629b53c3d2…` | the "NOT SIGNED" render |
| 03 | `2853693158e9ac10cae745c34f20affb07230d45a2ed008bd1172a170dca15c6` | said the marking covered two export paths when there are four |
| 06 | `de8b455a8b327b5b…` | the "not yet signed as a PDF" render, blank signature block |

A superseded artifact is **superseded, never edited** — `04` §5 says
re-registering the same `(artifact_kind, version)` with any field changed raises
a version conflict, and that is the behaviour we want.
