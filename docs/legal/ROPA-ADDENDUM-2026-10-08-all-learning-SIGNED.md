# Record of Processing Activities — addendum: the learning lanes (Privacy 3.5) — SIGNED by the founder 2026-10-08

**SIGNED by the founder, 8 October 2026** (in chat: "I sign the 3.5 pack of 8 October 2026 as drafted"; decisions log N68). **Counsel has not seen these changes**; the founder signed knowing that.

**Addendum to:** `docs/legal/ROPA-ART30.md` (v0.1 DRAFT). **Date:** 2026-10-08.
**Replaces:** activity A9 "Model improvement and training", whose retention line reads "n/a — this activity does not run". From the publication of Privacy 3.5 and each lane's switch PR, it runs, for speakers who say yes. A9 is split into A9a to A9g below; A14 is new. Every other activity stands.
**Reads with:** `docs/legal/DPIA-ADDENDUM-2026-10-08-all-learning-SIGNED.md` (P1–P7) and `legal/phase1-2026.1/24-retention-rows-learning-lanes-SIGNED-2026-10-08.md`.

Common to A9a–A9g unless a row says otherwise:

- **Controller:** Artur Willoński, operating as "WillpowerLab".
- **Art 6 basis:** 6(1)(a) consent, the training yes under training-only-v2
  (`legal/phase1-2026.1/23-training-consent-wording-v2-SIGNED-2026-10-08.md`); Art 9(2)(a)
  explicit consent where a speaker's words are used (counsel question 9 open
  on how the yes is recorded).
- **Consent evidence:** `ml_consent_events`, `ml_consent_snapshots`; kept six
  years after withdrawal or erasure (v1.1 row).
- **Withdrawal reaches:** the weekly refresh (pairs, releases voided and
  swept), the door-3 sweep (provider files), every run starting afterwards.
- **Not:** advertising, analytics about a person, sale, any third party's own
  models (OpenAI is instructed not to train its models).

### A9a — Fine-tuning feedback models (door 3)
- **Purposes:** train the models that write praise lines, clearer versions, exercise scripts, the coach's line on a moment and the coach's word for a Take
- **Categories of subject:** speakers who said yes; coaches (their final texts)
- **Categories of data:** passage text; the coach's final text. No audio, no ids in the file
- **Coach side:** the coach agreement permits training use of coaches' words (founder confirmed 2026-10-08)
- **Recipients / transfers:** OpenAI, United States; SCCs in OpenAI's DPA (founder confirmed signed 2026-10-08); fine-tuning files deleted at the end of each run and on withdrawal
- **Retention:** training copies until withdrawal or erasure; provider files until the run ends
- **Systems:** `feedback_pairs`, `pair_releases`, `pair_release_owners`, the training-run rows; `services/model_training.py`

### A9b — Deploying trained models (door 4)
- **Purposes:** serve a fine-tuned model to write feedback for every speaker
- **Categories of data:** the model; at serving time, the passage being answered (as today, A5)
- **Basis:** serving is A5 (6(1)(b)); the trained-on text rests on A9a's consent
- **Safeguards:** evaluation report passed; regurgitation check; `kill` returns the stock model within one request (`services/model_promotion.py`)
- **Retention:** until replaced or killed

### A9c — Training corpus copies
- **Purposes:** keep training material independent of the speaker's project
- **Categories of data:** words of each shown moment; the coach's blind yes or no. **No audio** (decision D1; the copy job's audio branch is removed before the switch)
- **Retention:** until withdrawal or erasure; survives a project deletion while the yes is on
- **Systems:** `training_corpus_items`; `services/training_corpus.py`

### A9d — Learned speaking-error detectors
- **Purposes:** tune the detectors that spot rushing and compression
- **Categories of subject:** speakers who said yes; coaches (their blind answers)
- **Categories of data:** gate-6a blind answers; eight timing features per clip
- **Recipients:** none outside WillpowerLab
- **AI Act:** `legal/phase1-2026.1/02-power-score-classification-v1.2-NOTE-SIGNED-2026-10-08.md`
- **Retention:** answers die with the recording (v1.2 row `coach-audit-answers-v1`); fitted weights until replaced
- **Systems:** `error_presence_audit`; `services/detector_candidates.py`

### A9e — V4 coach sheets and the blind block pick
- **Purposes:** teach and check the software that chooses feedback moments
- **Categories of data:** clips with words and audio; the speaker's words beside a reworded version; answers and preference pairs
- **Recipients:** coaches (no name, blind)
- **Retention:** with the recording, and on withdrawal
- **Systems:** migration 0453's tables; `services/v4_coach_sheets.py`

### A9f — Learned exercise order
- **Purposes:** order equally fitting exercises by how often they helped
- **Categories of data:** per try, whether the re-recorded fragment came out better; pooled rates per exercise
- **Retention:** tries as practice records (v1.4); rates until replaced (no personal data)
- **Systems:** `services/exercise_learned_order.py`, `services/exercise_evaluation.py`

### A9g — Release of pairs (door 2), restated
- Unchanged from today for the three answer surfaces; extended to the two coach-word surfaces once the speaker's yes is under v2.

### A14 — Imported training corpus (new)
- **Purposes:** build examples on which coaches judge speaking patterns and moments, and on which the software is checked and trained
- **Categories of subject:** people speaking on imported recordings; not users. Coaches (their answers)
- **Categories of data:** audio, transcript, measurements, coaches' answers; no name
- **Source:** recordings WillpowerLab holds the rights to use (founder confirmed 2026-10-08)
- **Art 6 basis:** 6(1)(f) as drafted (decision D4; N58 names no article). Art 9: no condition named; with counsel
- **Information:** Art 14 by publication (Privacy 3.5 §4c)
- **Recipients / transfers:** OpenAI, United States (transcription), SCCs; coaches
- **Retention:** while the right to use is held; on request or objection
- **Systems:** `corpus_processing_bases`, `corpus_import_registrations`, `corpus_provider_permits`; `services/training_import.py`

## Sub-processor table (§2): one change

| Recipient | Role | Activities | Location | Safeguard | Verified? |
|---|---|---|---|---|---|
| OpenAI | Processor | transcription and analysis (A3, A5); **fine-tuning (A9a), serving fine-tuned models (A9b), transcription of imported audio (A14)** | United States | DPA + SCCs; deletion on instruction covers fine-tuning files | DPA signed (founder, 2026-10-08); filed copy and date to be recorded |
