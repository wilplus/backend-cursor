# Reconciling the two legal packs

Two legal packs were built in parallel, on two branches with no shared history:

- `legal/phase1-2026.1/` — this pack, built around the Phase-1 processing
  boundary and what `register_phase1_policy_v1` requires.
- `docs/legal/` — a DPIA, an Article 30 record, an AI Act scoping memo, copy
  amendments, a consent artifact and an engineering brief.

Founder decision, 2026-09-17: **merge by role.** Neither pack wins wholesale.
This document records what was kept, what was superseded, and why — so the
reasoning survives, and so nobody re-derives a dropped approach later.

---

## 1. Kept from `docs/legal/`, unchanged

| File | Why it stays |
|---|---|
| `DPIA-2026-09-17.md` | A genuine gap here. Article 35 is plausibly engaged — systematic processing of voice with new technology — and this pack had no DPIA at all. |
| `ROPA-ART30.md` | Also a gap. Article 30(5)'s under-250 exemption does not apply: the processing is not occasional. |
| `ENGINEERING-BRIEF-GDPR-REMEDIATION.md` | Complements the work packages here rather than competing with them. Its WP4 — the technical B2C fence — is now more urgent, not less. |
| `AI-ACT-SCOPING-MEMO.md` | Converges with document 02 rather than contradicting it, and asks counsel the same two questions. Keep both: 02 is the artifact the database registers, the memo is the letter to counsel. |

## 2. Superseded, with reasons

### `legal/mlc2-split-consent-v2.json` — superseded by `04-policy-registration`

Its diagnosis is right. The `mlc2-bundled-consent-v1` construction bundled
personalised coaching with pooled model improvement and made both a condition of
service, which is the Article 7(4) problem, and this pack reached the same
conclusion independently (document 01 §3).

Its **mechanism** is superseded. Consent under the Phase-1 boundary is not a JSON
artifact. `register_phase1_policy_v1` takes the policy, three legal artifacts and
a purpose array; it recomputes `sha256` over every copy string and raises
`POLICY_COPY_HASH_MISMATCH` on a mismatch; and
`accept_phase1_processing_authorization_v1` writes a receipt bound to those
hashes. A JSON file beside the migrations cannot feed any of that, and the
boundary refuses a policy carrying a phase-2 purpose (`PHASE2_PURPOSE_FORBIDDEN`)
regardless of what a file says.

Keep the file as a record of the diagnosis. Do not activate it.

### `COPY-AMENDMENT-PROPOSAL-v1.3.md` — partly superseded

Amendments **A1** and **A2** are correct and this pack already implements both:
A2 (re-base recording on Article 6(1)(b)) is document 01 §3, reached
independently; A1's underlying finding is real and verified below.

The *approach* is superseded. Amending the live v1.2 React pages to v1.3 produces
copy that is not the copy the policy record holds. Under the boundary, the
authoritative text is `processing_policy_versions.terms_copy`, hashed, and the
pages must render it — a separately maintained page is the drift the hashing
scheme exists to detect (document 03, gap 3). This pack's `copy/*.txt` at v2.0
replaces the pages rather than patching them.

**But see §5: that is not a reason to leave a false statement live for weeks.**

## 3. What their pack corrected in mine

Credit where it is due — both were verified here before acceptance.

**The live copy contains two false statements.** Confirmed:

- `frontend-cursor/src/app/privacy/page.tsx:302` and `terms/page.tsx:287` say the
  voice inference is *"opt-in and off by default"*. It is not.
  `services/voice_confidence.py` `enabled()` returns true when
  `VOICE_CONFIDENCE_ENABLED` is unset, so computation is **on by default**.
  (Only *ranking* is off by default, behind a different flag.)
- `privacy/page.tsx:263` and `:460` assert OpenAI **zero data retention**. ZDR is
  a per-organisation approved application, not a default. Unless it has been
  applied for and granted, that statement is false and standard abuse-monitoring
  retention applies.

Neither is a drafting quibble. Both are representations to users about what
happens to their voice.

## 4. What this pack corrects in theirs

**The retention position conflicts, and both are dated 2026-09-17.**

`DPIA-2026-09-17.md` RISK-5 records life-of-account retention, taken against its
own advice of a fixed 90-day maximum. This pack records what the founder approved
here: audio **12 months after last use**, transcripts and derived documents until
account deletion, voice measurements deleted with their source audio, logs 90
days (document 06 §1). Those are the periods now written into Privacy §7 and
seeded by the engineer's migration.

The 12-month position is the stricter of the two and it **resolves RISK-5** rather
than accepting it: there is an actual limit, not an intention conditional on a
deletion route existing. **Founder: confirm which is authoritative.** If it is the
12-month position — and the code already assumes it is — RISK-5 should be
downgraded and its residual-risk note rewritten.

**`financial_evidence` is not accounting retention.** The DPIA maps accounting
retention to Article 6(1)(c). With the service free and taking no payment there
are no accounting records, but the category survives, because its dependencies
are `token_ledger` and `llm_usage` — internal per-user model cost records.
Document 06 §3 sets out the three options and does not default to one.

## 5. One thing neither pack handles, and it is urgent

Both packs fix the false live statements *eventually* — theirs by amending v1.2
to v1.3, mine by replacing the pages with v2.0 rendered from the policy record.

Both take weeks. **The statements are false today.**

That is a small, separate, immediate fix: correct those specific sentences on the
live pages now, under founder sign-off, and let both larger workstreams proceed
at their own pace. Waiting for the correct architecture before removing an
untrue sentence gets the order wrong.

## 6. One source of truth from here

- **Registration path** — this pack. It is what the code requires.
- **Assessment documents** — `docs/legal/`. DPIA and RoPA live there.
- **Counsel correspondence** — `docs/legal/EMAILS-TO-SEND.md`, with document 02
  attached as the technical basis for the AI Act questions.
- **The copy that ships** — `legal/phase1-2026.1/copy/*.txt` at v2.0, rendered
  from the policy record, never from a React page.
