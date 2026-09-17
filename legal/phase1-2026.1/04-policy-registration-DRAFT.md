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
| `allowed_countries` | `["pl"]` | §3 |
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
- **Trailing newline: [[FOUNDER/ENG: include it or strip it — pick one]].** The
  files as committed end with a newline. If the registration script reads the
  file and strips it, the same script must be what produces the hash the
  frontend compares against.
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

## 3. Allowed countries

`accept_phase1_processing_authorization_v1` lowercases and trims what the client
sends and requires an exact match against the array. So the frontend's country
picker and this list must use the same vocabulary, and the schema is indifferent
to which one.

**Recommendation: ISO 3166-1 alpha-2, lowercase, and start with `["pl"]`.**

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
it. Verify against `routes/phase2_guard.py` and
`services/processing_purposes.py` what the practice routes do in that state
before activating — the guard reads the registry, and the registry says
operational.

### Registry control versions

`register_phase1_policy_v1` flips every supplied purpose to `operational = true,
authorizes_processing = true` and writes the five control fields. The registry's
own CHECK constraint refuses an authorizing purpose with any of them missing.

| `purpose_id` | `capability_version` | `retention_control_version` | `deletion_control_version` | `rights_control_version` |
|---|---|---|---|---|
| `recording_voice_processing` | `phase1-recording-intake-v1` | `[[FOUNDER: name it once §7 of the Privacy Policy is filled in]]` | `phase1-purge-audio-objects-v1` | `phase1-subject-rights-v1` |
| `transcription_feedback` | `phase1-transcription-feedback-v1` | `[[FOUNDER: same]]` | `phase1-purge-derived-content-v1` | `phase1-subject-rights-v1` |

`reviewed_at`: the timestamp of the founder/counsel review that these versions
record. Not `now()` at registration time — that would assert a review happened
at the moment of a database call.

**These strings are claims, and 0335 set the standard for them.** That migration
deliberately shipped last, after the controls it names existed, because
"declaring them before they existed would have been the paper-only claim this
whole boundary exists to prevent." The same applies here:

- `phase1-purge-audio-objects-v1` names the deletion path completed in
  migration 0312. That exists.
- The **retention control does not exist yet.** `data_retention_rules` is created
  but unseeded, and `data_purge.py` has a `RETENTION_RULE_UNRESOLVED` path for
  exactly that state. A retention control version cannot honestly be declared
  until the rules are seeded and match the periods published in Privacy Policy
  §7. **This is the item that blocks registration.**

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

1. Counsel's determination in document 02 §9.
2. The four `[[FOUNDER: …]]` decisions in the copy documents, including every
   retention period in Privacy Policy §7.
3. `data_retention_rules` seeded to match those periods, so the
   `retention_control_version` above names something real.
4. Article 50 gaps 1, 2 and 3 from document 03 — in particular the acceptance
   screen, which does not exist in the frontend today. Without it there is no
   way for a user to accept, and therefore no receipt and no recording under
   `enforce`.
5. The staging rehearsal in `docs/PHASE1-PROCESSING-RUNBOOK.md` §"Required
   staging verification".
6. Signed DPAs and a transfer mechanism for every party in document 01 §2.

Items 3 and 4 are engineering work, not paperwork. They are the real critical
path.
