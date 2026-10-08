# DPIA addendum — every learning lane under the training yes (Privacy 3.5) — SIGNED by the founder 2026-10-08

**SIGNED by the founder, 8 October 2026** (in chat: "I sign the 3.5 pack of 8 October 2026 as drafted"; decisions log N68). **Counsel has not seen these changes**; the founder signed knowing that.

**Controller:** Artur Willoński, operating as "WillpowerLab" — Poland (EU)
**Addendum to:** `docs/legal/DPIA-2026-09-17.md` (v0.1 DRAFT, not yet adopted)
**Date:** 2026-10-08 · **Prepared by:** engineering, as counsel-support; not legal advice
**Trigger:** DPIA §7 names "any change to the sub-processor list" and new processing as review events; the founder's decision of 2026-10-08 to open every learning lane is both (a new use by OpenAI, fine-tuning, and seven new processing operations).
**Reads with:** `legal/phase1-2026.1/22-privacy-terms-3.5-all-learning-SIGNED-2026-10-08.md` (the lanes, decisions D1–D4, prerequisites E1–E8), `legal/phase1-2026.1/23-training-consent-wording-v2-SIGNED-2026-10-08.md`, `legal/phase1-2026.1/24-retention-rows-learning-lanes-SIGNED-2026-10-08.md`, `legal/phase1-2026.1/02-power-score-classification-v1.2-NOTE-SIGNED-2026-10-08.md`.

The main DPIA's §2.4 status note says training is not processed. From the
publication of Privacy 3.5 and the first switch PR, that stops being true for
speakers who say yes. This addendum is the assessment of that change; it does
not rescore the main DPIA's risks.

## 1. The new processing (Art 35(7)(a))

| # | Operation | Data | Subjects | Recipient / place | Basis |
|---|---|---|---|---|---|
| P1 | Fine-tuning (door 3) on five text surfaces: praise line, clearer version, exercise script, the coach's line on a moment, the coach's word for a Take | the passage text as transcribed; the coach's final text | speakers with the v2 yes; coaches | OpenAI, United States (fine-tuning files; deleted when a run finishes and on withdrawal) | 6(1)(a) + 9(2)(a) (speaker); coach agreement (coach) |
| P2 | Deployment (door 4): a fine-tuned model writes feedback for every speaker | the model; any speaker's passage at serving time (as today) | every speaker (as recipient of output); trained-on speakers (risk of reproduction) | OpenAI (serving, as today) | serving: 6(1)(b) as today; the trained-on text: 6(1)(a) + 9(2)(a) |
| P3 | Corpus copy | the words of each shown moment; the coach's blind yes or no on it. No audio (D1) | speakers with the v2 yes | our storage | 6(1)(a) + 9(2)(a) |
| P4 | Corpus import | third-party audio, transcript, measurements, coach answers | people speaking on imported recordings (not users) | OpenAI (transcription), coaches | 6(1)(f) as drafted (D4) |
| P5 | Learned detectors | coaches' blind answers (gate 6a) and eight timing features of the clip | speakers with the v2 yes; coaches | our systems | 6(1)(a) |
| P6 | V4 coach sheets and the blind block pick | clips with words and audio; the speaker's words beside a reworded version; the coach's answer and preference pair | speakers with the v2 yes; coaches | coaches; our systems | 6(1)(a) + 9(2)(a) (words shown) |
| P7 | Learned exercise order | whether an exercise helped, per try, pooled into a rate per exercise | speakers with the v2 yes | our systems | 6(1)(a) |

## 2. Necessity and proportionality (Art 35(7)(b))

- **One basis for all learning.** Consent, separate, never pre-ticked, never
  a condition, refusable with no loss of service, withdrawable on the same
  card (counsel 2026-10-01; main DPIA M1.1, M1.3, M1.5). The alternative,
  legitimate interest for P5 to P7 (smaller intrusion: no text leaves, the
  outputs are a few weights), was not taken: counsel's advice was "never
  legitimate interest" for training, and one switch is the clearer
  promise. The cost is a smaller, consenting-only pool, which may bias the
  learned detector and the exercise order towards speakers who say yes;
  recorded as R-L7.
- **Minimisation.** Text and numbers only (no audio to training, D1); no
  user id, coach id or Take in a release file (door 2); the eight-word test
  before deployment; fitted artefacts hold weights, not data.
- **Storage limitation.** Rows in `legal/phase1-2026.1/24-retention-rows-learning-lanes-SIGNED-2026-10-08.md`.

## 3. Risks and measures (Art 35(7)(c)+(d))

Scored as the main DPIA scores, on the stated user base; rescore at launch.

| # | Risk | L × S | Measures (existing / new) | Residual |
|---|---|---|---|---|
| R-L1 | **A deployed model reproduces a speaker's text to another speaker** (P2), including sensitive content a speaker said | low × high | existing: 8-word regurgitation check against withdrawn speakers' text, fails the model for good (`services/golden_evaluation.py`); memorisation rate recorded against all trained text. **New, recommended before door 4 for any surface:** gate on the memorisation rate too, not only on withdrawn text; the coach-word surfaces first, because a Take word may name personal matters | medium until the gate exists, then low |
| R-L2 | **The coach's own words** used without the coach's knowledge (P1) | low × medium | coach agreement covers training use (founder confirmed 2026-10-08); the speaker's yes still required (Nowak; counsel 2026-10-01) | low |
| R-L3 | **A v1 yes read as covering the coach-word surfaces** | high × medium if not handled | D3: v1 retired at the instant v2 starts; every v1 yes counts as off; the speaker is asked again | low |
| R-L4 | **Transfer to the US for fine-tuning** (P1) | medium × medium | OpenAI DPA with SCCs and deletion on instruction (founder confirmed signed, 2026-10-08); files deleted at the end of each run and on withdrawal (`services/model_training.py`); text only | low; transfer impact assessment to be filed with the DPA |
| R-L5 | **Third-party voices imported without their knowledge** (P4): no Art 13 moment, Art 14 by publication only; incidental Art 9 content with no Art 9(2) condition named | medium × medium | founder holds the rights (confirmed 2026-10-08); no name attached; never shown to users; Privacy §4c; objection by email; deletion when the right ends. **Open:** the Art 9 condition for incidental sensitive content (counsel); E7, a person can be deleted on request | medium |
| R-L6 | **Promises ahead of code** (main DPIA RISK-2 pattern): 3.5 promises no audio copy, consent-filtered sheets, detector fit and exercise rates | high × high if a switch flips first | E1–E8 in `legal/phase1-2026.1/22-privacy-terms-3.5-all-learning-SIGNED-2026-10-08.md`, each a precondition of its switch PR, which names the 3.5 line it relies on | low if E1–E8 hold |
| R-L7 | **Consent-only pools bias the learned detector and exercise order** | medium × low | shadow first; the fair test and the jar's bars; live only by a reviewed change | low |
| R-L8 | **Coach hears words in V4 sheets** (P6), which the gate-6a balancing test excluded ("no words") | medium × low | consent of the speaker (not legitimate interest); no name; blind exposure record; weekly caps (`services/v4_coach_sheets.py`) | low |
| R-L9 | **Article 9 record disagreement** (counsel question 9): Privacy says 9(2)(a), the yes record says not applicable | n/a — accuracy of records | open with counsel; v2 registration does not change it | open |
| R-L10 | **AI Act**: the learned detector and document 02's engaged condition | — | `legal/phase1-2026.1/02-power-score-classification-v1.2-NOTE-SIGNED-2026-10-08.md`; shadow first; counsel question 1 | as main DPIA RISK-3 |

## 4. Art 36 prior consultation

Not indicated on the measures above, on the same reasoning as the main DPIA
§7. Revisit if counsel's answer to question 1 is `true` on any line, or if
R-L1's gate is not built before door 4 opens for a coach-word surface.

## 5. Open questions for counsel (added to `legal/phase1-2026.1/21-counsel-questions-2026-10.md` when it is next sent)

1. Is a model fine-tuned on consenting speakers' text, which passes the
   regurgitation test, anonymous within EDPB Opinion 28/2024, so that keeping
   and serving it after a withdrawal is not processing of that speaker's data?
2. Is the 8-word window enough, or must memorisation gate deployment?
3. Does the v2 sentence, with its eight lines, make the consent specific and
   informed for all seven operations, or should P5 to P7 be their own
   choice?
4. The basis for P4 (D4), and an Art 9(2) condition for incidental sensitive
   content in imported audio.
5. Whether "while we hold the right to use it" is a retention period.
6. The transfer impact assessment OpenAI's SCCs need for fine-tuning files.
7. Questions 6, 7 and 9 of the October brief, as they bear on v2.

*Prepared as counsel-support. Not legal advice and not privileged. Requires
founder adoption and review by a qualified lawyer.*
