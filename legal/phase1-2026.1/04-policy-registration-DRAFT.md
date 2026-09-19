# Policy `phase1-2026.1` — registration settings

**STATUS: DRAFT.** Values marked `[[FOUNDER: …]]` are decisions, not defaults.

This is the input to `register_phase1_policy_v1(p_policy, p_product_legal,
p_power_score_classification, p_article50, p_purposes, p_actor)` and then
`activate_phase1_policy_v1`. Both are `service_role` only; browser and
authenticated roles have no grant.

---

## 1. The policy record

| Field | Value | Note |
|---|---|---|
| `version` | `phase1-2026.1` | Unique. Never reused; a changed policy is a new version. |
| `terms_version` | `2.0` | Live copy is 1.2. A new major, because 2.0 removes the pooled-training consent rather than amending it. |
| `privacy_version` | `2.0` | Same reason. |
| `ai_notice_version` | `1.0` | New document; there is no predecessor. |
| `allowed_countries` | `["pl"]` | Poland for the first registration. **NOT settled** — widening waits on per-country Art 9(4) conditions (cover-note ask 5). Do not harden this list before that answer. |
| `minimum_age` | `18` | Fixed by CHECK; no other value is accepted. |
| `created_by` | `Artur Willoński` | The person registering the policy, not the approving authority. |
| `status` on registration | `approved` | Set by the RPC. `active` comes from `activate_phase1_policy_v1`. |

## 2. Copy canonicalisation — fix this before the first hash

`register_phase1_policy_v1` recomputes `sha256` over the exact string passed and
raises `POLICY_COPY_HASH_MISMATCH` on any difference. The client later sends
four hashes and `accept_phase1_processing_authorization_v1` raises
`PROCESSING_POLICY_STALE` if any one differs. So the byte-level rules have to be
decided once and never drift:

- **UTF-8**, no BOM.
- **LF** line endings, never CRLF.
- **Trailing newline: INCLUDED. DECIDED 2026-09-18, and this line does not
  change again.** The hashed string is the file's bytes exactly as committed,
  final LF included — nothing is stripped, trimmed or appended anywhere between
  the file and the RPC.

  Chosen because it is the only rule that needs no code to obey. `sha256sum`,
  `openssl dgst`, Python's `hashlib.sha256(path.read_bytes())` and a Postgres
  `sha256(convert_to($1,'UTF8'))` over the same string all agree on it with no
  preparation step, so there is no stripping helper that one caller can forget
  and no second implementation to drift. A strip-first rule is one line of code
  in every place a hash is computed, and the first place that omits it produces
  a receipt that will not verify.

  All four files end with exactly one LF today, verified 2026-09-18. Keep it
  that way: an editor configured to trim trailing newlines will silently change
  a registered policy's hash, and a registered policy can only be superseded,
  never corrected.
- **No normalisation of the text itself** — no smart quotes, no whitespace
  collapsing, no template interpolation anywhere between the file and the RPC.

Recommended: hash the file bytes exactly as committed, newline included, and
make the frontend compare against the hash returned by
`get_phase1_processing_authorization_v1` rather than recomputing it. The
authoritative text is `policy.terms_copy` from that RPC; the frontend should
render it and never hold its own copy (see document 03, gap 3).

```
sha256sum legal/phase1-2026.1/copy/terms-2.0.txt \
          legal/phase1-2026.1/copy/privacy-2.0.txt \
          legal/phase1-2026.1/copy/ai-notice-1.0.txt \
          legal/phase1-2026.1/copy/agreement-1.0.txt
```

Compute after the founder's final edits and after the `-DRAFT` suffix is
removed, never before.

### The four hashes — COMPUTED 2026-09-19

Both preconditions are met. The copy is final (zero `[[…]]` blanks; the three
internal notes that were inside these files moved to the conditions section at
the foot of this document on 2026-09-18), and the `-DRAFT` suffix came off in
the same commit that records these values.

Over the file bytes exactly as committed, final LF included, per the rule above:

| file | bytes | `sha256` |
|---|---:|---|
| `copy/terms-2.0.txt` | 9,146 | `620148dedc09b94a3e9b75285734686ae35d21b8e3a2532a03a08c291daf294f` |
| `copy/privacy-2.0.txt` | 10,915 | `8f622637d852e28ae9eff3e1e85a1136a52c2e9bb93478329758d04beab8e972` |
| `copy/ai-notice-1.0.txt` | 1,804 | `bacdf6c61759ea7a89bb2beb1d20f1616c26e33eaec3ce66ec57dec481665f6b` |
| `copy/agreement-1.0.txt` | 848 | `89035b5232cc555842469ff2aa2efe20ca726e4a254ee171827e9c572041c0e9` |

```json
  "terms_copy_sha256": "620148dedc09b94a3e9b75285734686ae35d21b8e3a2532a03a08c291daf294f",
  "privacy_copy_sha256": "8f622637d852e28ae9eff3e1e85a1136a52c2e9bb93478329758d04beab8e972",
  "ai_notice_copy_sha256": "bacdf6c61759ea7a89bb2beb1d20f1616c26e33eaec3ce66ec57dec481665f6b",
  "agreement_copy_sha256": "89035b5232cc555842469ff2aa2efe20ca726e4a254ee171827e9c572041c0e9"
```

**Verify before registering, not after.** Re-run the `sha256sum` block above and
compare. If any value differs, something edited a copy file after this line was
written and the difference must be understood before anything is registered —
not papered over by updating this table.

For the avoidance of doubt, these are the values the **stripped** rule would
have produced, recorded once so that a mismatch can be diagnosed rather than
guessed at: `terms` `2208147…`, `privacy` `b6da8ef…`, `ai-notice` `9533b8d…`,
`agreement` `5855b4e…`. **If `register_phase1_policy_v1` reports a mismatch and
the value it computed is one of those four, a caller stripped the trailing
newline** — fix the caller, never the table.

### A note on the four determination documents' filenames

`01`, `02`, `03` and `06` keep their `-DRAFT.md` source names even though they
are signed. That is deliberate and not an oversight: what is signed and
registered is the **PDF at the `object_key`**, whose name has never carried the
suffix, and each signed PDF's footer cites its markdown source by the path it
had when it was rendered. Renaming those sources now would break that
back-reference for no gain. The copy files are different — their *bytes* are
the registered artifact, so they are named as what they are.

## 3. Allowed countries

`accept_phase1_processing_authorization_v1` lowercases and trims what the client
sends and requires an exact match against the array. So the frontend's country
picker and this list must use the same vocabulary, and the schema is indifferent
to which one.

**DECIDED (founder, 2026-09-17): `["pl"]` for v1. The United States arrives on
a v1.1 policy.** ISO 3166-1 alpha-2, lowercase.

This settles the contradiction between this section and `05-us-counsel-brief`
§11, which read "We serve Illinois. Not a question." while this section said a
non-EEA country could not be added without re-versioning documents 01, 02 and
03. Both statements were true; they could not both be acted on. Poland-first
means 01, 02 and 03 stay as they are, written against EU law, and the US
analysis lands on its own policy version rather than forcing a re-version of
three documents that are not yet signed.

Doc 05 now carries a PARKED banner saying the same thing from the other side,
and adds the reason that matters more than sequencing: serving Illinois as a
natural person puts BIPA's per-person statutory damages on the founder
personally. The US returns with incorporation, not merely with a version bump.

Why one country to begin with: one supervisory authority (UODO), one language of
counsel, one consumer-law regime, and one set of national rules on age and on
the recording of voices. The Terms name Polish law and Polish courts, and §16 of
the Terms is straightforward for a Polish consumer and immediately more
complicated for a Spanish one.

What each expansion actually costs, so the decision is priced:

- **EEA-wide** (`["at","be",...]` — enumerate; there is no wildcard): consumer
  terms must hold up in each member state, and the mandatory-rules carve-out in
  Terms §16 starts doing real work. Counsel should confirm the Terms and the
  Privacy Policy before the list grows.
- **Outside the EEA:** a different legal analysis entirely. Documents 01, 02 and
  03 are written against EU law. Do not add a non-EEA country without
  re-versioning them.

Codes must be lowercase in the array. `activate_phase1_policy_v1` will not fix a
mixed-case entry, and the comparison is exact.

## 4. Purposes

### In the v1 policy

| `purpose_id` | `lawful_basis_code` | `required_for_core_service` |
|---|---|---|
| `recording_voice_processing` | `gdpr_6_1_b_contract` | `true` |
| `transcription_feedback` | `gdpr_6_1_b_contract` | `true` |

`lawful_basis_code` is free-form `TEXT` with no constraint and no existing
convention in the repo. Recommended vocabulary, so the column stays queryable:
`gdpr_6_1_a_consent`, `gdpr_6_1_b_contract`, `gdpr_6_1_c_legal_obligation`,
`gdpr_6_1_f_legitimate_interest`, and `gdpr_9_2_a_explicit_consent` where
Article 9 applies alongside. Decide it here and write it down, because nothing
in the schema will stop the next policy from spelling it differently.

The Article 9(2)(a) explicit consent for incidental special-category content is
captured by the agreement copy, not by a purpose row — there is no field for it.
Note that in document 01 so the mapping is not lost.

### Held out of the v1 policy, and why

`coach_review`, `individual_learning_profile`,
`personalized_exercise_recommendation`.

All three are defensible purposes. The blocker is mechanical:
`accept_phase1_processing_authorization_v1` writes
`processing_authorization_receipt_purposes` only `WHERE
pp.required_for_core_service`. An optional purpose is therefore shown to the
user and leaves no consent evidence. For `coach_review`, whose basis is consent,
that is the absence of the lawful basis itself, not a paperwork gap.

### ⚠️ CONDITIONAL DESIGN CONSTRAINT — if OpenAI disclosure needs its own consent

US counsel brief document 05 §4 Q4 asks whether disclosure of recordings to
OpenAI requires consent separate from the main authorisation. **The answer is
not given here.** What is recorded here is the schema consequence, because it
lands on this document's registration design and would otherwise be discovered
during implementation.

**If the answer is yes, the Phase-1 receipt path cannot carry it.** The same
mechanical fact above applies: only purposes marked `required_for_core_service`
produce receipt-purpose rows, so a *separate, optional* consent leaves no
evidence at all. That leaves exactly two shapes, and both have a cost:

1. **A new purpose marked `required_for_core_service`.** It would then write
   evidence — but marking a separate consent as required for the core service
   bundles it back into the main authorisation, which is precisely the Art 7(4)
   problem DPIA RISK-1 exists to remediate. Trading one defect for the one we
   are already fixing.
2. **A second evidence surface**, distinct from the Phase-1 receipt, recording
   optional consents with their own lineage. Nothing of the kind exists, and it
   would need its own authorisation boundary, its own retention category and its
   own place in the purge registry.

**Neither is picked here, and neither should be built before counsel answers.**
Building shape 2 speculatively is a new evidence surface with no live consumer;
building shape 1 is a documented regression. The point of recording it now is
that "yes" is not a copy change — it is a schema change — and the estimate
should reflect that when the answer arrives.

**Note on document 05.** It is PARKED: the founder's decision is Poland first,
US on v1.1 (BIPA damages land on the founder personally). This constraint is
recorded against the question; the brief is not sent.

Marking them required instead would make agreeing to coach review and practice a
condition of using the product — the Article 7(4) bundling that document 01 §3
is structured to avoid.

**What this costs:** under `enforce`, coach review and practice do not run until
a v1.1 policy ships alongside a consent surface that can record an optional
purpose. That is a real product cost and it is the founder's decision.

**Note on `personalized_exercise_recommendation`:** migration 0335 already set it
`operational = true, authorizes_processing = true` with real control versions,
on founder authorisation. Leaving it out of the policy does not undo that; it
means no policy currently carries it, so no receipt can authorise processing for
it. The guard reads the registry, and the registry says operational, so verify
against `routes/phase2_guard.py` and `services/processing_purposes.py` what the
practice routes do in that state before activating.

What is no longer a risk: **#543 (`c1effd5`) removed V3 Manager arbitration's
dependency on this purpose.** Confident Voice feedback previously sat behind an
exercise enrollment that could not be obtained, so holding the purpose out of
the policy would have taken V3 down with it. It no longer can — the exercise
context is an enrichment, and an unauthorised exercise path means the bookmark
shows the Confident Voice question instead of the practice panel.

### Registry control versions

`register_phase1_policy_v1` flips every supplied purpose to `operational = true,
authorizes_processing = true` and writes the five control fields. The registry's
own CHECK constraint refuses an authorizing purpose with any of them missing.

| `purpose_id` | `capability_version` | `retention_control_version` | `deletion_control_version` | `rights_control_version` |
|---|---|---|---|---|
| `recording_voice_processing` | `phase1-recording-intake-v1` | `phase1-retention-schedule-v1` | `phase1-purge-audio-objects-v1` | `phase1-subject-rights-v1` |
| `transcription_feedback` | `phase1-transcription-feedback-v1` | `phase1-retention-schedule-v1` | `phase1-purge-derived-content-v1` | `phase1-subject-rights-v1` |

`reviewed_at`: the timestamp of the founder/counsel review that these versions
record. Not `now()` at registration time — that would assert a review happened
at the moment of a database call.

**These strings are claims, and 0335 set the standard for them.** That migration
deliberately shipped last, after the controls it names existed, because
"declaring them before they existed would have been the paper-only claim this
whole boundary exists to prevent." The same applies here:

- `phase1-purge-audio-objects-v1` names the deletion path completed in
  migration 0312. That exists.
- `phase1-retention-schedule-v1` names document 06. Periods were approved by the
  founder on 2026-09-17 and the schedule is drafted, **but the rules are not yet
  seeded**: `data_retention_rules` is still empty and `data_purge.py` has a
  `RETENTION_RULE_UNRESOLVED` path for exactly that state. The control version
  becomes honest when the seeding migration lands, not when document 06 is
  written. **Until then this still blocks registration.**

### The `reviewed_at` trap for an already-operational purpose

If a v1.1 adds `personalized_exercise_recommendation`, the payload must repeat
**0335's exact stored values**, including its `reviewed_at`, or
`register_phase1_policy_v1` raises `PURPOSE_CONTROL_VERSION_CONFLICT`. 0335 set
`reviewed_at = now()` at migration time, so that timestamp is not in any file —
read it out of the database and pass it verbatim:

```sql
SELECT capability_version, reviewed_at, retention_control_version,
       deletion_control_version, rights_control_version
  FROM public.processing_purpose_registry
 WHERE id = 'personalized_exercise_recommendation';
```

Expected: `confident-voice-practice-v1`,
`practice-retention-option-a-30d-v1`, `phase1-purge-practice-objects-v1`,
`phase1-subject-rights-v1`.

## 5. Legal artifact references

Each of the three documents is registered by reference, not by content. Only the
storage key and the fingerprint of the signed PDF go into the database.

```json
{
  "artifact_kind": "product_legal_approval",
  "version": "1.0",
  "approving_authority": "[[FOUNDER]]",
  "approved_at": "[[FOUNDER: ISO-8601 UTC]]",
  "object_key": "[[FOUNDER: storage path]]",
  "sha256": "[[sha256 of the signed PDF]]",
  "metadata": {"policy_version": "phase1-2026.1"}
}
```

`power_score_classification` additionally **must** carry:

```json
"metadata": {
  "pipeline_version": "voice-confidence-universal-v3",
  "biometric_identification": false,
  "sex_gender_inference": false,
  "emotion_intention_inference": false
}
```

Any other value raises `POWER_SCORE_CLASSIFICATION_CONFLICT` or
`POWER_SCORE_PIPELINE_VERSION_UNAPPROVED`. See document 02 §9 and README finding
1: if counsel's answer is not `false`, the answer is to change the product or the
gate, not the document.

Re-registering an existing `(artifact_kind, version)` with any field changed
raises a version conflict. Bump the artifact version; never edit in place.

## 6. Registration and activation

Idempotent by design. A byte-identical replay returns the same `policy_id` and
writes no second `phase1_authorization_admin_events` row.

```
SELECT public.register_phase1_policy_v1(
  :policy::jsonb, :product_legal::jsonb, :power_score::jsonb,
  :article50::jsonb, :purposes::jsonb, 'Artur Willoński'
);
```

Then, after staging review only:

```
SELECT public.activate_phase1_policy_v1(:version, :actor, :reason);
```

Activation freezes the cutoff and creates exact-job carryovers for accepted
non-terminal work, so recordings already in flight are not stranded by the
cutover.

**Order matters and getting it wrong takes the product down.** Set
`PLF1_PROCESSING_AUTHORIZATION_MODE=enforce` only *after* activation. With
`enforce` set and no active policy,
`get_phase1_processing_authorization_v1` returns `PROCESSING_POLICY_INACTIVE`,
`finalize_phase1_recording_intake_v1` raises, and every recording is refused.

Per the CONFIG-FIRST rule: set the variable on **web, worker and every cron
service**, and verify from each service's boot log rather than the Railway UI.
A worker without it is the worst case — the app looks healthy while background
jobs behave differently from the web tier.

## 7. Blockers before this can be registered

Reviewed 2026-09-19. Four of the six are closed; the ones that remain are
storage, database and paperwork, and none of them is a decision.

1. ~~Counsel's determination in document 02 §9.~~ **Closed as a blocker,
   carried as a condition.** The founder determined it himself on 2026-09-19 —
   `false` on all three booleans, not high-risk, not prohibited — recorded in
   the `approving_authority` field as *not counsel-reviewed*, and subject to one
   written gate: **counsel must confirm before any person other than the founder
   records.** Every recording made to date is the founder's own voice, so today
   the only affected data subject is the person who made the determination. That
   stops being true the moment someone else records, and **that** is the
   condition to hold, not registration.
2. ~~The four `[[FOUNDER: …]]` decisions in the copy documents.~~ **Closed
   2026-09-18.** Zero blanks remain in `copy/*.txt`; the three internal notes
   that were sitting inside them moved to the conditions section below, where
   they cannot be rendered to a user. Hashes are in §2.
3. `data_retention_rules` seeded to match document 06 §1, so the
   `retention_control_version` above names something real. **Open.** §3b's two
   proposed categories (`deletion_evidence`, `transparency_evidence`) still need
   the founder's confirmation, and `financial-evidence-v1` carries option 2's
   bounded period as a marked placeholder until counsel answers.
4. ~~Article 50 gaps 1, 2 and 3 from document 03 — in particular the acceptance
   screen, which does not exist in the frontend today.~~ **Closed.** The
   acceptance screen shipped in frontend #389 (`f4607888`) and the Art 50(2)
   marking in #406 (`ae212ee9`). One decision inside gap 1 is open — whether the
   `text/plain` clipboard flavour carries a visible marker line — and document
   03 §8 records why it does not hold activation.
5. The staging rehearsal in `docs/PHASE1-PROCESSING-RUNBOOK.md` §"Required
   staging verification". **Open.**
6. Signed DPAs and a transfer mechanism for every party in document 01 §2.
   **Open**, and the one outstanding action is the founder's: the Art 28(3)(h)
   email to OpenAI drafted in `docs/legal/PROCESSOR-CONTACT-LOG.md` as attempt 2
   and never sent. Stripe is an independent controller for payments, not a
   processor, so there is no DPA to chase there — a recipient to disclose, which
   the Privacy Policy now does.

**Plus one that was never on this list and should have been:** all four signed
PDFs uploaded to their `object_key`s with their fingerprints recorded. Two of
the four are signed and current; two are being re-signed. See
[`SIGNED-ARTIFACTS.md`](SIGNED-ARTIFACTS.md), which is the file to check before
registering anything.

Item 3 is the only remaining engineering work. Items 5, 6 and the uploads are
sequence, not design.

---

## Conditions carried out of the copy files (moved here 2026-09-18)

The four `copy/*.txt` files are rendered to users **verbatim, whitespace and
all**, and their exact bytes are what the four SHA-256 hashes cover. Anything
inside them is read by a user. Three internal notes were sitting in them in
`[[…]]` form and would have been displayed on the acceptance screen and the
public pages. They are removed from the copy and recorded here instead.

**Nothing in this section is user-facing. Nothing in it may go back into a copy
file.**

### C1 — Controller identity, on business registration

Terms §1 and Privacy §1 name **Artur Willoński, a natural person operating under
the name "WillpowerLab"**. That is accurate today and a lawful configuration —
GDPR does not require a legal person.

**On registering a business, both blocks must name the registered entity, its
address and its number.** That changes the Privacy Policy, which changes its
SHA-256, which makes **every existing receipt stale** and asks every user to
accept again. Document 01 §2 prices this: the cheapest moment to incorporate is
before the first policy registration; the cost scales with the user count at the
moment it is made. Taking payment will in all likelihood cross the
unregistered-activity threshold and force the question.

### C2 — The 14-day withdrawal right, before this version is registered

Terms §2 states the EU/EEA consumer right to withdraw from a paid plan **in
full**, with no limitation. That is deliberate and currently correct.

A subscription that starts immediately only loses that right where the consumer
**expressly asks for it to start at once AND acknowledges losing it**. Checkout
asks neither question today. So **no sentence limiting the withdrawal right may
appear in the Terms until checkout asks both** — the Terms follow the checkout,
never the reverse. Counsel confirms the wording (cover-note ask on consumer
law); engineering adds both to checkout as its own work package.

### C3 — A further AI provider

Privacy §5 names **OpenAI as the only AI provider** that receives audio or
transcripts. If any other AI provider is added, it must be named there and
**this policy re-versioned before that provider receives anything**. A new
provider under an unchanged policy version is a receipt proving agreement to a
recipient list the user never saw.
