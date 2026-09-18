# `power_score` — classification under Regulation (EU) 2024/1689 (AI Act)

    artifact_kind:       power_score_classification
    version:             1.0
    approving_authority: [[FOUNDER: named person or firm]]
    approved_at:         [[FOUNDER: ISO-8601 UTC timestamp of signature]]
    object_key:          [[FOUNDER: storage path of the signed PDF]]
    sha256:              [[computed from the signed PDF at registration time]]
    metadata: {
      "pipeline_version": "voice-confidence-universal-v3",
      "biometric_identification": false,
      "sex_gender_inference": false,
      "emotion_intention_inference": [[COUNSEL — see §9; the registration RPC
                                       accepts only false]]
    }

**STATUS: DRAFT — NOT APPROVED, NOT SIGNED.** §§2-4 are a factual description of
the code, written by engineering, and can be checked line by line against the
cited files. §§5-8 set out the legal questions and the arguments on both sides.
§9 is where the determination goes and it is deliberately left empty. This
document does not conclude that the feature is fine.

---

## 1. Why this document is the one that decides whether the feature can run

Two of the three registrable metadata booleans are straightforward. The third —
`emotion_intention_inference` — is the question of whether WillpowerLab's
confidence feature is an emotion recognition system. If it is:

- Annex III point 1(c) makes it **high-risk**, with the full Chapter III
  provider obligations (risk management, data governance, technical
  documentation, logging, human oversight, accuracy/robustness, quality
  management, conformity assessment, CE marking, registration);
- Article 50(3) adds a deployer information duty;
- and Article 5(1)(f) **prohibits** it outright in workplace and education
  contexts — a prohibition, not a tier, in force since 2 February 2025.

That is why the founder's brief says this document "has to be a real analysis of
what your code actually computes — not a statement that it's fine."

## 2. What `power_score` is

`services/power_phrase_ranking.py`, 88 lines, pure, no database and no model
call:

```
power_score = 2.0·coach_term + 1.0·activation + 0.6·slide_stickiness
            + 1.0·machine_confidence
```

- `coach_term` — `0.0`, or `-1.0` when a human coach has explicitly tagged the
  piece `to_work_on`. The map is one-sided on purpose; `"strong"` is not in it.
  This is a recorded human decision, not an inference.
- `activation` — `overall_score`, which `services/lab_recording.py` computes as
  `0.5·topic_stickiness + 0.5·slide_stickiness`. Both are language-model reads
  over the **transcript text**. Falls back to `1/rank`.
- `slide_stickiness` — a language-model read over the transcript text.
- `machine_confidence` — `services/voice_confidence.rank_term(metrics)`, which
  returns `None` unless `VOICE_CONFIDENCE_RANKING_ENABLED` is set. It is **off by
  default**. `None` contributes exactly `0.0`.

So `power_score` itself performs no acoustic processing at all. Three of its
four terms are derived from text or supplied by a human. The fourth is the
voice-confidence composite, and in the shipped default configuration it
contributes nothing.

**What the output is used for:** ranking candidate phrases from the user's own
speech, to decide which of them to surface back to that same user. It is not a
decision about the person, it produces no eligibility outcome, and it is never
shown. `power_score` is internal by design and fence-tested as such.

**What it is not:** it is not a "confidence score for the user", and it is not
the thing the product name suggests. Anyone assessing this feature from the
identifier alone will assess the wrong thing.

## 3. What the voice-confidence composite is

`services/voice_confidence.py`, version stamp `voice-confidence-universal-v3`.
This is the component that carries the legal question.

**Inputs.** Eight numeric fields already present in the metrics blob the audio
pipeline computes: `f0_sd`, `dynamic_db`, `f0_mean`, `wpm`, `pause_ratio`,
`pause_ms`, `f0_mid_end_delta`, `intensity_envelope`. No audio is re-read, no
provider is called, and no text is used.

**Normalisation.** Every feature is z-scored against **the speaker's own
baseline** — never an absolute scale across speakers or rooms. The baseline is
resolved cross-take over at most 5 prior sessions requiring at least 8 samples,
else within the current take requiring at least 6 usable pieces, else `None`.

**Combination.** Seven cues with fixed weights summing to 1.0:

| Cue | Feature(s) | Sign | Weight |
|---|---|---|---|
| pitch range | `f0_sd` | + | 0.18 |
| loudness range | `dynamic_db` | + | 0.20 |
| pausing | `pause_ratio`, `pause_ms` | − | 0.18 |
| mean pitch | `f0_mean` | − | 0.13 |
| speech rate | `wpm` | + | 0.13 |
| terminal contour | `f0_mid_end_delta` | + | 0.09 |
| energy front-load | `intensity_envelope` | − | 0.09 |

The weighted sum is renormalised by the weight actually present, so a partial
blob sits on the same scale as a complete one.

**Output.** `to_spectrum()` subtracts a 0.25 neutral dead zone from the
magnitude and squashes through `tanh`, giving a value in `[-1, 1]` to three
decimal places. `band()` maps that to a five-point internal label:
`confident` / `close_to_confident` / `neutral` / `unconfident` / `doubtful`.

**Provenance of the cue directions.** Jiang & Pell (2017), *Speech
Communication* 88:106-126. The directions come from that paper; the weights are
the product's own and the module says so in terms: "PROVISIONAL-LITERATURE-TILTED,
NOT CALIBRATED".

**Four properties that matter legally, all enforced in code:**

1. **No learning.** The weights are module-level constants. The module states:
   "There is intentionally NO machinery here to tune them on data — they are
   constants, full stop." Nothing about the composite adapts after deployment.
2. **No demographic input.** `voice-confidence-universal-v3` is one universal,
   sex-blind cue contract. `tests/test_phase1_compliance_contract.py::test_universal_voice_confidence_has_no_demographic_runtime_contract`
   parses the module's AST and fails if the identifiers `sex`, `gender`,
   `profile_sex`, `sex_source`, `male`, `female` or `speaker_sex` appear at all.
   The product neither collects speaker sex nor infers it from pitch.
3. **Never surfaced.** AC-9. The score, the band and the cue z-scores never reach
   a user payload, and this is fence-tested in `tests/test_voice_confidence.py`.
   No number, ratio, badge or classifier output is shown to anyone.
4. **Never shown to the coach.** The composite is "NOT learned and NOT on the
   coach packet", so it cannot anchor a human labeller to a machine opinion.

**Honest absence.** Fewer than three measurable cues, or no baseline, returns
`None` — never a fabricated neutral `0.0`. Unmeasured is recorded as unmeasured.

## 4. Is the composite, on its own, an "AI system"?

Article 3(1) requires a machine-based system that "infers, from the input it
receives, how to generate outputs", operating with varying autonomy and possibly
exhibiting adaptiveness. Recital 12 excludes systems "based on the rules defined
solely by natural persons to automatically execute operations".

The composite is a fixed-coefficient weighted sum with hand-set constants, no
learned parameters and no adaptiveness. There is a real argument that, taken
alone, it falls outside Article 3(1).

**That argument should not be relied on, for two reasons.** First, WillpowerLab
as a whole is unambiguously an AI system: it transcribes with a speech model and
generates the Ideal Text and Feedback with a language model. The unit of
analysis under the AI Act is the system placed on the market, and the composite
is a component of that system. Second, an argument that turns on the composite
being "just arithmetic" is fragile against the first time anyone fits the
weights to data — which the module currently forbids, but by comment rather than
by control.

**Recommended framing for the determination:** classify the WillpowerLab system,
and answer the three metadata questions about what that system does with voice.

## 5. Biometric identification — `biometric_identification: false`

Article 3(35) defines biometric identification as automated recognition of
human features "for the purpose of establishing the identity of a natural
person by comparing biometric data of that individual to biometric data of
individuals stored in a database".

**Facts.** There is no voiceprint, no enrolment, no template store and no
1:N or 1:1 matching anywhere in the pipeline. The per-speaker baseline is
retrieved *by an already-known* `user_id` — identity is an input to the
baseline lookup, never an output of it. The composite cannot answer "who is
speaking"; it is not capable of it and is not used for it.

**Assessment.** `false` is well supported. This is the cleanest of the three.

One point for counsel to note rather than resolve: the stored per-speaker
acoustic baseline (`services/acoustic_baseline.py`) is a persisted statistical
profile of an individual's voice. It is not used to identify and could not
identify at this feature resolution, but it is personal data and belongs in the
RoPA and the retention schedule as such.

## 6. Sex or gender inference — `sex_gender_inference: false`

**Facts.** Sex routing was retired as executable behaviour on 2026-08-29 by
founder amendment. `power_score` has no challenge/threat or sex inputs;
confidence uses one universal, sex-blind cue contract. Two tests enforce it:
the AST identifier scan in §3, and
`test_power_score_has_no_retired_direction_inputs`, which fails if `_W_D`,
`_W_B` or `_DIRECTION_TERM` reappear.

Mean pitch (`f0_mean`) is used as a cue, and pitch correlates with sex at the
population level — but it enters only as a within-speaker z-score against that
same speaker's own baseline, which removes the between-speaker component that
would carry the correlation. No sex category is assigned, stored or read.

**Assessment.** `false` is well supported for the running system.

**Two caveats to record in the signed document.** Historical rows created under
the retired routed contracts still exist. They are audit-only, receive no new
writes, and are explicitly "never compatibility aliases, product evidence, or
training input" — and `_RANKABLE_VERSIONS` refuses to rank values produced under
a superseded weighting, so they cannot re-enter. Their deletion is a separately
authorised, previewed retention operation:
`migrations/pending/cleanup_retired_sex_data.sql`, held out of
`migrations/manifest.txt` and test-enforced to stay out. A `false` here is a
statement about the active pipeline, not a statement that the historical rows
are gone. The signed document should say which of the two it means.

## 7. Emotion or intention inference — the contested one

Article 3(39): an emotion recognition system is "an AI system for the purpose of
identifying or inferring emotions or intentions of natural persons on the basis
of their biometric data". Two cumulative conditions.

### 7.1 Condition (ii) — is this "biometric data"?

Article 3(34) AI Act defines biometric data as personal data resulting from
specific technical processing relating to the physical, physiological or
behavioural characteristics of a natural person. Unlike Article 4(14) GDPR, the
AI Act text does **not** carry the qualifier "which allow or confirm the unique
identification". Recital 14 nonetheless says the notion should be interpreted in
light of the GDPR definition.

- *Narrow, GDPR-aligned reading:* fundamental frequency, pause structure and
  intensity envelope cannot and do not uniquely identify anyone here, so they
  are not biometric data, and Article 3(39) fails at condition (ii) regardless
  of anything else.
- *Broad, literal reading:* they are exactly "personal data resulting from
  specific technical processing relating to the physiological and behavioural
  characteristics of a natural person", and the identification qualifier is
  absent from the AI Act text on purpose.

**Do not build the determination on the narrow reading alone.** It is a real
argument and it may well be right, but it rests on a qualifier the legislator
removed, and it would fail entirely if a court or the Commission adopts the
literal reading. Assume condition (ii) is met and decide on condition (i).

### 7.2 Condition (i) — is "confidence" an emotion or an intention?

**The case for `false`:**

1. Recital 18 enumerates what the legislator had in mind: happiness, sadness,
   anger, surprise, disgust, embarrassment, excitement, shame, contempt,
   satisfaction, amusement. Confidence and doubt are not among them, and are
   not of the same kind — they are epistemic states about one's own knowledge,
   not affective states.
2. Recital 18 expressly excludes physical states such as pain and fatigue,
   showing that not every inferable internal state is an "emotion".
3. The underlying literature frames confidence and doubt as metacognitive
   states — a speaker's feeling of knowing — rather than as emotions.
4. The product's own stated question is about **how assured the delivery
   sounds**, not about how the speaker feels. On that framing the composite
   characterises an acoustic performance, not a person's inner state — closer
   to measuring that someone spoke quietly than to inferring that they were sad.
5. The output never reaches a user, a coach, or any third party. It selects
   which of the user's own sentences to replay to them.
6. There is no profiling consequence: no eligibility, ranking against other
   people, price, access or report follows from it.

**The case against, which must be weighed honestly:**

1. Article 3(39) says "emotions **or intentions**", which is broader than the
   Recital 18 list, and the Commission's guidelines on prohibited practices
   treat that list as illustrative rather than closed.
2. **The code's own vocabulary contradicts the framing in point 4 above.**
   `band()` returns `doubtful` and `unconfident`. Those are predicates about a
   person, not about a waveform. The module docstring describes "locating the
   moment on a confidence SPECTRUM". A regulator reading the source will read
   attribution of a state to a speaker, whatever the product copy says.
3. Sourcing the cue directions to an affective-prosody paper makes "we only
   measure acoustics" harder to hold: the directions are meaningful *because*
   they were validated against human confidence judgements.
4. "It is never surfaced" limits the harm, and is a strong mitigation, but
   Article 3(39) turns on **purpose**, not on disclosure. An internal-only
   emotion recognition system is still an emotion recognition system.

**Engineering's view, offered as input and not as the determination:** `false`
is arguable and may well be correct, but it is not currently *earned* by the
code. Point 2 above is fixable and should be fixed before signature — see §9.

### 7.3 Biometric categorisation

Article 3(40) — assigning natural persons to categories on the basis of
biometric data. The five-point `band()` label is, on the broad reading of §7.1,
an assignment to a category. But Article 5(1)(g) prohibits categorisation only
to deduce race, political opinions, trade union membership, religious or
philosophical beliefs, sex life or sexual orientation, and Annex III point 1(b)
makes categorisation high-risk only "according to sensitive or protected
attributes". None of those is inferred here, and sex routing is retired (§6).

**Not prohibited under 5(1)(g); not high-risk under Annex III 1(b).**

## 8. Risk tier, on the assumption that §7 lands on `false`

- **Article 5 prohibitions.** 5(1)(f) prohibits AI systems inferring emotions in
  the areas of workplace and education institutions. If §7 lands on `false`, it
  does not apply. **If §7 lands on `true`, this is the controlling provision,
  and it is a prohibition — no compliance programme cures it.**
- **Annex III point 1(c)** (emotion recognition): not high-risk if §7 is `false`.
- **Annex III point 3** (education): not engaged. Self-directed practice by an
  adult on their own account is not determining access to, or evaluating
  learning outcomes in, an education or vocational training institution.
- **Annex III point 4** (employment): not engaged. The system is not used for
  recruitment or selection, nor to evaluate or monitor the behaviour and
  performance of persons in a work-related contractual relationship.
- **Article 6(1)** (safety component of a regulated product): not engaged.

**Conclusion: not high-risk, as currently deployed — contingent entirely on the
deployment fence.** Points 3, 4 and 5(1)(f) are all deployment-dependent, not
code-dependent. Every one of them can be crossed without changing a line of
code, by selling the same product to an employer or a school.

**This is the single largest live risk in the classification and it must be
recorded as a condition on the approval, not as an observation.**

**Founder confirmation, 2026-09-17: inbound B2B interest exists, but no company
has used the service.** So Article 5(1)(f) is prospective, not historical — there
is a fence to hold rather than an exposure to remediate. That is the good
version of this fact, and it has a short shelf life: the fence has to be real
before the first employer signs up, not after.

**The fence needs both halves.** The contractual half is the "Not for employers
or schools" section of the Terms, which prohibits workplace and education
deployment expressly. The technical half does not exist yet. A prohibition a
user can ignore by clicking through is evidence of intent, not a control, and
counsel should say how much weight it can carry on its own.

**One further route to high-risk that does not depend on §7.** Article 6(3)
allows an Annex III system to escape high-risk classification where it performs
only a narrow procedural task — but its final subparagraph removes that
derogation entirely for any system that performs **profiling of natural
persons**. A per-speaker composite, baselined against that person's own history
and used to rank what they are shown, should be assessed against the profiling
definition in Article 4(4) GDPR before anyone relies on the Article 6(3) filter.
If it is profiling, the filter is unavailable and the only question left is
whether Annex III point 1(c) is engaged at all — which returns to §7.

Concretely, the deployment conditions:

- the Terms' "Not for employers or schools" section stays in force and is not
  weakened in any later version;
- no employer, school or institutional dashboard, and no route by which a third
  party receives a user's reads;
- no deployment where use is directed, mandated or monitored by an employer or
  an education institution;
- the coach surface stays user-initiated and asynchronous, and the composite
  stays off the coach packet;
- any B2B or education offering requires this document to be re-versioned
  **before** the first such user records anything.

Article 50 transparency obligations apply irrespective of tier and are handled
in document 03. Article 4 (AI literacy of staff, in force since 2 February 2025)
applies to the provider regardless and is not addressed here.

## 9. Determination

*To be completed by the approving authority. Engineering has not filled this in
and must not.*

    biometric_identification:    [ ] false   [ ] true
    sex_gender_inference:        [ ] false   [ ] true
    emotion_intention_inference: [ ] false   [ ] true
    high-risk under Annex III:   [ ] no      [ ] yes — point ____
    prohibited under Article 5:  [ ] no      [ ] yes — point ____

### Before signing `emotion_intention_inference: false` — status

The determination in §7.2 rests on the framing that the composite measures how a
delivery *sounds* rather than how a speaker *feels*. Two things in the code said
the opposite. **Both have since been changed** (commit `e5e02d6` on `main`,
2026-09-17, *"Phase-1 legal pack, band-label rename, retention seed and the
consent-version findings"*, #544):

1. ~~Rename the `band()` labels.~~ **Done.** `confident` / `close_to_confident` /
   `neutral` / `unconfident` / `doubtful` are now `delivery_signal_high` /
   `_mid_high` / `_neutral` / `_mid_low` / `_low`. Internal only; no user-visible
   effect. A normalizer maps the historical values, because the old strings are
   persisted in existing rows and three modules read them —
   `label_quorum.machine_proposal` string-matched all five and would otherwise
   have silently started returning "no opinion".
2. ~~Rewrite the module docstring's construct sentence.~~ **Done.** The scale now
   describes the audio, and the docstring states expressly that whether a
   listener would call a reading *confident* is a separate qualitative judgement
   the module does not make.

3. **A third change you did not ask for, disclosed for the same reason.**
   `services/confidence_labels.py::band_of()` returned `confident` / `neutral` /
   `doubtful` / `unscored` — the same vocabulary, in the file whose name makes it
   the first place an auditor of this construct would look. It was renamed on
   2026-09-17 to `delivery_signal_high` / `_neutral` / `_low`, keeping
   `unscored`, which describes the absence of a measurement rather than a
   speaker.

   It is disclosed because the alternative reads badly: had we renamed only the
   function this document named, we would have changed exactly what was asked
   about and left the identical vocabulary in place next to it. That is
   document-driven rather than principled, and it is a worse position than
   either doing all of it or doing none of it.

   It is a smaller change than item 1. The value is computed in memory from a
   score, consumed by one caller for queue bucketing, and never persisted,
   surfaced or transmitted — so unlike `band()` there is no history in the old
   spellings and no normalizer was required.

### ⚠️ Counsel must be told this plainly

**Those labels were renamed *because* this question was raised, on 2026-09-17,
after the analysis in §7 was written.** They were not always so named. A rename
made in support of a determination is a different thing from one that predates
the question, and counsel should weigh it knowing which it is. It is recorded
here rather than left to be discovered.

**The rename removes a contradiction. It does not answer the question.** The
strongest argument for inclusion is untouched by it: the composite is z-scored
**against the individual speaker's own baseline**, which makes the output a
statement about *this person relative to their own norm* rather than a property
of an audio file in the abstract. Renaming the output does not change what is
computed. A vocabulary that matched the framing was a precondition for the
framing being honest, not evidence that the framing is correct.

### If the determination is `true`

Do not sign a `false`. `register_phase1_policy_v1` will refuse the registration
(`POWER_SCORE_CLASSIFICATION_CONFLICT`), and that refusal is the control
working, not an obstacle to route around. The options are, in order of
preference:

1. Remove the composite from the product and ship confidence qualitatively from
   non-acoustic evidence. `VOICE_CONFIDENCE_ENABLED=0` is an existing kill
   switch and `rank_term` already returns `None` with ranking disabled, so the
   live loop survives it: an unstamped piece contributes `0.0` and ranks as it
   did before the composite existed.
2. Accept high-risk status and complete Chapter III. This is a substantial
   programme and is very unlikely to be proportionate at this stage.
3. Change the gate, by explicit founder decision, so the classification can
   record `true` — and then live with what `true` implies, including the
   Article 5(1)(f) deployment prohibition.

### Signature

    Name:      ______________________________
    Firm:      ______________________________
    Date:      ______________________________
    Reference: ______________________________

*Article and recital numbering above should be verified by counsel against the
text of Regulation (EU) 2024/1689 as published in the Official Journal. The code
descriptions in §§2-4 are verifiable against the cited files at commit
`e849306`.*
