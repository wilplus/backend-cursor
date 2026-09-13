# MLC-3 Confident Moment Coaching Bundle — Founder Contract Delta D3

**Status:** founder-authored delta; **design review required before executable
implementation**.

**Scope:** product and data-contract reconciliation only. This document changes
no executable code and authorizes no migration, deployment, activation, real
collection, dataset release, training, evaluation, or promotion.

## 1. Frozen implementation bases

The implementation base is the production-aligned `origin/main` state fetched
on 2026-09-10, not the HEAD of an older feature worktree.

| Repository | Authoritative repository | Base ref | Base commit |
| --- | --- | --- | --- |
| Backend | `https://github.com/wilplus/backend-cursor.git` | `origin/main` | `4acaa2c997c1c0a4ff93c4fa0fbb4adc7868db92` |
| Frontend | `https://github.com/wilplus/frontend-cursor.git` | `origin/main` | `0f88bd4a3f96d0f39c6679a232a1a32837f0dde6` |

Future implementation worktrees must be created from these exact commits. A
newer base requires a new conflict audit and interface-manifest revision.

## 2. Reviewed source inventory

### 2.1 Production-base contracts

| Contract | SHA-256 at backend base |
| --- | --- |
| `docs/CANONICAL_PRODUCT_CONTRACT.md` | `ab64f402ae2e5dba78735e1cbd43c0440051c83bdffe5cf63f196414c219e8b2` |
| `docs/take-feedback-policy-v3-ml-review.md` | `08ef9dac5539c96254b8925fbf64a638dada353dd91554d39df0071c1ed0d8d5` |
| `docs/ROOTING-PHRASE-QUALIFICATION-V1-IMPLEMENTATION.md` | `aa8bf140a0d45a6299c92d1daa4166b75fc93acd2e2797d2d26527d3be7501a8` |
| `docs/MLC3-FIRST-CLIENT-SERVICE-D2.md` | `b465b3070e543ed1c3395a1de34dfd21686f6c808d7007bc3944bc28ba662fd8` |
| `docs/MLC3-COACH-GUIDANCE-DELIVERY-D3.md` | `b3d65c5a06d67e99bdf20f0024f46fb70c445ceef6b817bafdcc764b990295d1` |
| `docs/MLC3-COACH-INLINE-EXERCISE-AUTHORING-D5.md` | `cc4544d358bea690d99f3e3a4b1d99c944654e4626ffbd7df8193f9f742e1438` |
| `docs/MLC3-GENERAL-USER-SERVICE-D4.md` | `4ee8cc5f1dda8cf5e727fefdaef12a1a96a85d9fcd01c74e8953564026bf1085` |
| `docs/MLC3-EXERCISE-ADEQUACY-DESIGN.md` | `6d0168c11c1fcce1d429a66aa61985b04f81639cab16fd6f6a8e5fa97da18b3d` |
| `docs/MLC2-FOUNDATION.md` | `0cb14d5705f54b22026237201339a31be08f7dacbcaa0b08b71b39d236eb9b62` |
| `docs/PRODUCTION-DATA-FOUNDATION.md` | `9c33d4e4dba3ccb5701a3160e2c0621bd05894d995167077d4ad9fd8cfa53e9f` |
| `docs/MIGRATIONS.md` | `4d49311be2f3ebc1110588ce9b80f2224a3f33a7feb094842712a9e46a8d9543` |

The accepted RPQ design file referenced by the implementation packet is not
present on `origin/main`; its accepted checksum is recorded historically as
`73cf48f9ba012bd77f14536b39827a03358d29d751f497acc137cef60f2b5f50`.
The released RPQ implementation packet above is therefore the inspectable base
authority for implementation-shape reconciliation.

### 2.2 Accepted but not present on production base

| Contract | SHA-256 | Status |
| --- | --- | --- |
| `MLC3-PERSONALIZED-ACOUSTIC-MATCHING-D2.md` | `23be7a2feaf4fed92c098a3e46703d0ea26cf7d0c53d9231684f8c62be030195` | ML/data design accepted; local disabled implementation only |
| `MLC3-PERSONALIZED-ACOUSTIC-MATCHING-OPERATIONAL-D2.md` | `ea11e5fea543625ba05f5d4de343078c7c454fabbe7c5edf3b50717c364a2de5` | ML/data operational design accepted; no population artifact approved |

### 2.3 Founder-locked inputs for this delta

- `docs/cursor-prompts/MLC3-CONFIDENT-MOMENT-COACHING-EXECUTION-PROMPT.md`
- `docs/MLC3-DATASET-AND-LEARNING-READINESS-D1.md`

These two documents are founder-authored inputs, not ML/data or Engineering
acceptances. Their numerical and dataset provisions require separate review.

## 3. Non-negotiable retained boundaries

This delta retains without reinterpretation:

1. **L1:** Ideal Text is the sole canonical document. A Take, model, or coach
   never silently rewrites accepted text.
2. **L2:** Detectors create Candidates; only Manager-selected Feedback may
   surface. Candidate inventory and the active Manager budget stay complete.
3. **L3:** machine, owner, blind coach, blind peer, product action, acoustic
   movement, preference, and authoring provenance remain separate.
4. **AC-9 and construct fence:** no score, ratio, rank, probability, model
   verdict, or unreviewed construct is shown to users.
5. **Blind coach:** before immutable judgment and reviewer-specific complete
   batch reveal, only opaque audio and the five-state question are visible.
6. **Live loop:** machine feedback is immediate; coach review and authoring are
   asynchronous and never block the next Take.
7. **Exposure:** preparation and delivery are not exposure. Authenticated
   visible render is its own immutable event.
8. **Service authority:** `personalized_exercise_recommendation` and
   `coach_review` must both be operational and authorized on the same current
   receipt and policy. Optional pooled authorization never gates coaching.
9. **Speaker and comparison:** source and practice have separate exact
   acquisition/target-speaker bindings; comparison requires current same-speaker
   equality and capture comparability.
10. **Learning:** no ninth learning surface. Product evidence remains
    `dataset_eligible=false` until a separately reviewed immutable release.

## 4. Manager budget reconciliation

The Confident Moment Coaching Bundle is a **presentation container**, not a new
Feedback family, candidate lane, Manager slot, or learning surface.

The current V3 budget remains:

- **Take 1:** exactly one relative-best `confident_voice` item per valid
  slide-bounded block; no Actionable Improvement or Praise.
- **Take 2+:** exactly one relative-best `confident_voice` item per valid block,
  plus zero or one globally selected `rewrite_clarity` item and zero or one
  globally selected `great_formulation` item for the Take.
- `no_defensible_candidate` remains honest absence for Improvement or Praise.

The bundle only projects those already-selected items:

| Canonical family | Bundle presentation |
| --- | --- |
| `confident_voice` | exact playback plus one qualitative confidence question; it is the bundle anchor |
| `rewrite_clarity` with replacement wording | typed `Feedback Language / Rephrase` |
| `rewrite_clarity` with an observation but no replacement | typed `Feedback Language / Comment` with actionable purpose |
| `great_formulation` | typed positive `Feedback Language / Comment` with praise purpose |

Praise is therefore not deleted, merged into correction data, or removed from
the Manager budget. It becomes a positive Comment only at the interaction
layer and retains `great_formulation`, praise response, exposure, and learning
provenance.

`Feedback Language` is one product/service abstraction with two output kinds,
`comment` and `rephrase`. It does **not** merge the existing canonical learning
surfaces (`correction_generation`, `coach_comment_generation`,
`praise_generation`, `praise_selection`, and `correction_selection`) into an
undifferentiated dataset. Model reuse across typed surfaces requires a separate
training/evaluation design.

## 5. Bundle anchoring and ordinary corrections

Every selected V3 Confident Voice item is a **feedback anchor** whether or not
it later becomes an orange/rooting phrase. The UI must continue to use tentative
language for a relative-best item; anchor status is not objective confidence.

A selected ordinary verbal/structure item attaches to the nearest selected V3
confidence anchor on the same Slide, using deterministic distance over exact
Paragraph/evidence-span order. It quotes the exact corrected passage inside the
bundle. Attachment neither changes the item's canonical family nor declares
the ordinary passage confident.

If an already-selected Manager correction has no usable same-Slide confidence
anchor, it receives exactly one minimal, exact-Paragraph, non-orange
presentation trigger at the corrected Paragraph's canonical position. The
trigger freezes the existing Manager membership, candidate, family, evidence,
Paragraph, document snapshot, policy and canonical presentation identity; its
stable identity is
`membership_id + candidate_id + paragraph_id + document_snapshot_id +
no-anchor-trigger-policy-version`. It creates no confidence anchor, automatic
root, owner root, qualification, new candidate, or additional Manager slot.

Preparation and delivery create no rendered exposure or response. On the first
authenticated visible render, the client acknowledges the exact canonical
presentation and the existing feedback exposure ledger creates or reuses
exactly one rendered-exposure receipt. Only a later explicit response may bind
that exact receipt. Before render, exposure is absent; before response, response
is absent. Dismissal, skip, silence and timeout remain unanswered. Foreign,
stale or mismatched exposure identity fails closed. No parallel exposure ledger
or learning label is created.

Implementation acceptance must prove: preparation creates zero exposure and
response rows; one visible render creates exactly one exposure; exact render
retry reuses it; a later response binds it without a second exposure; and an
absent, foreign or stale exposure cannot authorize a response.

Triggers sort by canonical Slide index, Paragraph position, selected Manager
order and candidate UUID bytes. Missing or stale exact Paragraph identity fails
closed rather than relocating the correction to another Slide.

Only one highest-priority unresolved correction is expanded at a time. The
complete frozen selected set and every response remain unchanged underneath
that progressive disclosure.

## 6. Rooting phrase has three independent axes

Do not encode one overloaded `root_status`. Preserve:

1. **Activation origin**
   - `automatic_product_selection`
   - `owner_selection`
2. **Persistence**
   - `automatic_replaceable`
   - `owner_locked`
3. **Qualification**
   - `not_qualified_reference`
   - `qualified_confident_reference`

An automatic orange root is not owner approval. An owner-selected or locked
orange root is not a confidence label. A qualified confident reference requires
its separate machine + speaker action + canonical blind-coach quorum on the
exact clip. A root may independently be owner-locked and quorum-qualified.

### 6.1 Automatic root eligibility

Automatic product selection may use a Manager-selected relative-best V3 clip
only when all of these product-routing conditions are current:

- exact candidate/membership/rendered-exposure lineage;
- exact playable audio and exact transcript clause;
- server-derived semantic result is `aligned`;
- owner response for that exact clip is exactly `confident_yes`;
- owner response is not `confident_no`, `confident_not_sure`, or
  `confident_audio_unclear`;
- current Ideal Text content/Paragraph/Slide/block identity;
- no current owner lock in that block; and
- current service, retention, media, speaker, and deletion authority.

This is a product-routing rule, not absolute machine-reference eligibility and
not a training label. V3 rank/selection alone is insufficient.

`confident_in_between` never activates an automatic orange root. It may open an
explicit owner proposal/selection path; if selected, the origin is
`owner_selection`, qualification remains `not_qualified_reference`, and the
response remains owner self-report rather than confidence truth.

### 6.2 Wording and re-recording

- `Update the text` may apply an exact accepted Rephrase to Ideal Text through
  the canonical user-controlled revision path.
- Corrected or manually written wording must be re-recorded before it can become
  an evidence-backed automatic or qualified root.
- A new qualified attempt may replace an automatic root, but never an
  owner-locked root without explicit approval.
- A worse, ambiguous, or invalid new attempt remains separate evidence and does
  not replace the prior root.
- The owner may deliberately choose such an attempt as an orange root; its
  origin is `owner_selection` and it is not a qualified reference.
- The prior root remains restorable during post-Take review. Recording Mode for
  the next Take displays only the current root, not restoration controls.

## 7. Root coverage policy

The founder-requested coverage schedule is:

| Review after | Target | Selection priority |
| --- | ---: | --- |
| Take 1 | 30% of Slides, always including Slide 1 | Slide 1, then uncovered Slides in canonical deck order |
| Take 2 | 80% of Slides | uncovered and weakest-supported Slides first |
| Take 3 | 100% of Slides | every remaining Slide receives a proposal |
| Take 4+ | maintain 100% | improve evidence without replacing owner locks |

For `N` immutable deck Slides, the target counts are `max(1, ceil(.30*N))`,
`max(previous_target, ceil(.80*N))`, and `N`. Each selected root remains subject
to the existing maximum of one active root per 75-word block.

Coverage target and achieved coverage are separate. The system never fabricates
speech, confidence, alignment, or owner agreement to make a target look met.
When no automatically eligible phrase exists by Take 3, it proposes the
strongest exact aligned transcript clause. The owner may select another exact
clause or write intended wording; edited wording requires re-recording. If the
owner declines every proposal, achieved coverage remains honestly below target.

The `30/80/100` policy is therefore a progression target, not permission to
override owner control or evidence gates.

## 8. Exact phrase extraction

- At most one root per Slide-bounded 75-word V3 block.
- Prefer one exact complete clause or sentence of 5–20 normalized words.
- Extraction selects a contiguous exact transcript span and changes no words.
- When no complete 5–20-word clause exists, use the shortest exact complete
  clause even when longer.
- No new blended score is computed. V3 has already selected the relative-best
  confidence anchor for each valid Slide-bounded block. Root routing never
  re-ranks raw detector Candidates or combines confidence with semantic values.
- The complete clause inventory for one selected anchor is derived only from
  its exact canonical transcript/evidence text and frozen token order. Candidate
  spans are the maximal contiguous exact spans ending at canonical punctuation
  `.`, `?`, `!`, `;`, `:` or the evidence-span boundary. Empty spans are
  discarded. Prefer inventory items containing 5–20 normalized word tokens;
  if none exists, retain the shortest non-empty complete span. Ties resolve by
  fewer tokens, earlier canonical start token, earlier end token, then the
  lowercase SHA-256 of exact UTF-8 span text.
- Across eligible anchors, coverage routing is lexicographic: mandatory Slide 1
  first; Slides without a current root before already-covered Slides; canonical
  Slide index; canonical 75-word block index; V3 membership item order; anchor
  candidate UUID bytes. Take 2+ therefore fills uncovered Slides first without
  inventing a cross-modal strength score.
- Inputs with absent/non-finite V3 routing evidence, missing exact tokens,
  uncertain/not-aligned semantics, non-`confident_yes` owner response, stale
  content, or invalid authority/media/speaker leaves are excluded with a typed
  reason. Missingness can never improve ordering.
- The replay hash freezes the complete selected-membership inventory, exact
  candidate/evidence/text hashes, transcript/tokenizer and semantic-policy
  versions, owner-response/exposure identities, Ideal Text snapshot, root heads,
  coverage policy version and the ordered eligible/excluded result. Changed
  input produces a successor decision, never reinterpretation.
- This lexicographic policy is product routing only. It creates no score,
  confidence label, selector-learning surface, or user-visible metric.
- A vocally strong but not-aligned clause is withheld from automatic rooting.
  Present the Rephrase/Comment path first; re-recording is required before the
  revised wording becomes evidence-backed.
- `uncertain` semantic alignment routes immediately to a correction or owner
  selection path and asynchronous review; it never waits for the coach.

## 9. User interaction and coach update reconciliation

The user overlay presents, in order:

1. exact audio playback and qualitative confidence question;
2. concise Comment;
3. Rephrase when needed, with `Update the text` and `Cancel`;
4. eligible Exercise, with an optional skip that never blocks the Take;
5. exact-fragment re-recording; and
6. final `Save the text` and `Cancel` controls for owner persistence.

`Cancel` dismisses that correction for the current Take. A new version may
appear only from new Take evidence or a later exact coach-authored revision.

The coach's blind judgment is private. After complete-batch reveal, a separate
coach-authored Comment, Rephrase, or Exercise may create a user-facing update:

- before owner action, the latest coach-authored version supersedes the visible
  unresolved machine wording while machine history remains immutable;
- after owner completion, the update appears in the next relevant Take and
  never reopens the completed overlay;
- it never changes Ideal Text or an owner-locked root without owner approval;
- its exact anchor buzzes until the authenticated user renders the update;
- after render it stays accessible without buzzing; and
- no separate notification is emitted merely because the update exists.

## 10. Exercise and adequacy reconciliation

The accepted D3/D5 boundaries remain:

- general written/video guidance may attach to any eligible revealed frozen
  Feedback item without manufacturing an acoustic need;
- an MLC-3 exercise requires exact Confident Voice need provenance, complete
  catalogue inventory, deterministic hard-gate result, and exact no-match or
  selected-version lineage;
- the source Take is `source_before_exercise`;
- only a recording after confirmed exercise playback is
  `practice_after_exercise`;
- authoring, assignment, delivery, render, playback, re-recording, acoustic
  movement, owner preference, and blind-coach comparison are separate events;
- a private draft does not become a reusable catalogue version without the
  accepted publication, content, safety, rights, media, and provenance review;
  and
- no exercise event automatically means helped, improved, adequate, or
  effective.

PAM-D2 and PAM-OP-D2 generalize matching beyond `rushed_phrase_endings`, but
they remain unimplemented and require a separately reviewed population artifact
for the exact language, speaking goal, and capture class. Until that artifact
exists, generalized PAM operations return
`approved_population_reference_unavailable`. Existing accepted deterministic
service behavior must not be silently replaced by fabricated reference values.

## 11. Evidence and dataset reconciliation

The backend may collect exact product evidence while every new record remains
`dataset_eligible=false`. Eligibility, immutable dataset membership, training,
evaluation, promotion, and serving are distinct approvals.

- blind coach five-state judgment may later support
  `confidence_classification` under its exact contract;
- machine Comment/Rephrase plus exact user and coach response lineage may later
  support the existing typed language surfaces;
- exercise matching remains deterministic initially;
- exercise adequacy requires comparable same-speaker before/after acoustics,
  explicit owner A/B preference, and independent blind-coach A/B comparison;
- video played, phrase locked, exercise uploaded, and re-recording completed are
  behavioral product events, never labels alone; and
- no blanket flag converts historical product rows into ML data.

The founder-locked numerical thresholds in
`MLC3-DATASET-AND-LEARNING-READINESS-D1.md` require their own checksum-pinned
ML/data design review before dataset or training implementation.

## 12. Onboarding and presentation-context boundary

The proposed removal of `What should this presentation achieve?` is a separate
founder copy/schema amendment. Before removal, prove that the retained audience,
topic, CTA/intended-action, deck, and transcript fields contain equivalent
required intent without losing historical provenance.

Presentation type is inferred from authoritative setup, deck, and transcript.
Only genuine ambiguity may trigger one user clarification after Take 1 and
before the first structure-level observation. Presentation-wide observations
remain typed Comments attached to the relevant bundle; they are not scores and
do not become new Feedback families.

## 13. Review gates before implementation

This D3 records the founder/Product decision for the automatic-root amendment,
the target interpretation, the non-orange no-anchor trigger, and the closed
lexicographic routing policy. Executable implementation must not begin until
the revised delta receives ML/data design acceptance and the interface manifest
is regenerated against its accepted checksum.

1. **Dataset thresholds:** accept them only after independent ML/data review;
   they cannot make records eligible or authorize model work by themselves.
2. **PAM serving:** no generalized acoustic matching, machine-reference
   eligibility, or personal baseline may serve without the separately reviewed
   population artifact and implementation/release/activation sequence.

## 14. Decision-filter result

```text
VERDICT:  REJECT
CATEGORY: F1-SURFACE / F2 boundary
WHY:      The founder has now made the automatic-root policy an explicit,
          provenance-separated Product amendment, but the checksum-pinned D3
          still requires independent ML/data acceptance before it can replace
          the currently locked owner-only root rule.
REDIRECT: Submit D3 for ML/data design re-review. If accepted, regenerate and
          checksum-pin the interface manifest before any executable work.
```

`FILTER: REJECT — cat F1-surface/F2 boundary — fences clear — locks BREAKS:L1
under the current canonical root rule until D3 is accepted — redirect: obtain
ML/data acceptance and re-freeze the interface manifest before implementation.`
