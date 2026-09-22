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

`01` and `06` were rendered at `4e92203` and their markdown is byte-identical at
`6f7ded6`, so those signatures stand and nothing about them needs redoing.

`02` and `03` were rendered at `8ddaab2` by `scripts/render_doc_pdf.py` and
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

## Why 02 and 03 were re-signed (closed 2026-09-22)

Neither is a change of substance to what the founder decided. Both are
corrections that would have made a signed document say something untrue.

- **02** — #555 corrected §9's citation from `81369c0` to `e5e02d6` (#544).
  That is the commit which renamed the band labels, in the section a lawyer is
  most likely to check, and `81369c0` resolves in neither repository. A
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
| 02 | `a7e4bfce8eaeac2d9ed831003241047d22af03cc6b82a8b00064effbb1c86add` | correct in every other respect; superseded only by the `81369c0` → `e5e02d6` citation fix |
| 03 | `b7d366629b53c3d2…` | the "NOT SIGNED" render |
| 03 | `2853693158e9ac10cae745c34f20affb07230d45a2ed008bd1172a170dca15c6` | said the marking covered two export paths when there are four |
| 06 | `de8b455a8b327b5b…` | the "not yet signed as a PDF" render, blank signature block |

A superseded artifact is **superseded, never edited** — `04` §5 says
re-registering the same `(artifact_kind, version)` with any field changed raises
a version conflict, and that is the behaviour we want.
