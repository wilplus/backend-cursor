# Signing sheet — the 3.5 pack, 8 October 2026

**DRAFT — for the founder's signature; counsel not yet consulted on these changes.**
Asked by the founder on 2026-10-08: open every learning pipe, documents to sign today.
One rule throughout: **anything that learns across people happens only for speakers who hold the training yes** (consent, Art 6(1)(a) + 9(2)(a), opt-in, withdrawable). Signing publishes nothing and opens nothing.

## What you sign (one line each)

| # | Document | What changes |
|---|---|---|
| 1 | `copy/privacy-3.5.txt` | §4a rewritten: coach's words (incl. moment line, Take word), coach answers, measurements, separate copies; models write for every speaker; regurgitation test; earlier yes counts as off. New §4c for imported recordings. §2, §3, §4, §5, §7, §9 follow. |
| 2 | `copy/terms-3.5.txt` | §8: "the sound of your recordings" is never trained on; licence gains a second purpose (serving the models to every speaker); coach's words licensed by the coach agreement. §11: a coach may hear a moment for §4a. |
| 3 | `22-privacy-terms-3.5-all-learning-DRAFT.md` | Changelog 3.4 → 3.5, the lane map, decisions D1–D4, what code must be true first (E1–E8). |
| 4 | `23-training-consent-wording-v2-DRAFT.md` | The new switch sentence, eight lines above it, the registration SQL (v1 retired at the instant v2 starts). |
| 5 | `24-retention-rows-learning-lanes-DRAFT.md` | Periods for training copies, provider files, §4a coach answers, learned models, imported recordings. |
| 6 | `02-power-score-classification-v1.2-NOTE-DRAFT.md` | Document 02 v1.2: the learned detector (§3c), and gate 6d's "until counsel confirms" replaced by three conditions; counsel still asked. |
| 7 | `docs/legal/DPIA-ADDENDUM-2026-10-08-all-learning-DRAFT.md` | Seven new operations, ten risks, measures; no Art 36 consultation indicated. |
| 8 | `docs/legal/ROPA-ADDENDUM-2026-10-08-all-learning-DRAFT.md` | A9 split into A9a–A9g; new A14 (imported corpus); OpenAI's row widened. |

**Decisions drafted one way (say so if not):** D1 the corpus copy copies no audio (the code's audio branch goes first). D2 passages from before the yes may be used (matches the pair refresh). D3 a v1 yes counts as off until given again. D4 the corpus import rests on legitimate interest, Art 6(1)(f).

## The sentence to sign

> I sign the 3.5 pack of 8 October 2026 as drafted: Privacy 3.5, Terms 3.5, the training switch wording v2 with its eight lines, the retention rows, document 02 v1.2, and the DPIA and ROPA addenda, with D1 to D4 as drafted, knowing counsel has not seen them.

## Confirmed by the founder, 2026-10-08 (in chat, as relayed to this session)

1. **OpenAI DPA:** he has signed OpenAI's data processing agreement (it carries the EU SCCs and deletion on instruction, which covers fine-tuning files: `docs/LEARNING-DOORS.md`, "The OpenAI side"). Its date and a filed copy are to be recorded.
2. **Coach agreement:** it lets coaches' words be used for training.
3. **Imported audio:** he holds the rights to any audio he imports into the training corpus.

## After signing, in order

1. Engineering records the signature here, assembles document 02 v1.2's full text (v1.1 + the note) and folds 24's rows into the next retention schedule version.
2. Render PDFs with `scripts/render_doc_pdf.py`: 23, 02 v1.2, the retention version; unsigned hashes into `SIGNED-ARTIFACTS.md`.
3. You sign them (PAdES) and upload each to its `object_key`; signed hashes into `SIGNED-ARTIFACTS.md` (Current).
4. Publish 3.5: engineering copies `scripts/phase1_policy_publish_3_4.sql` to a 3.5 script carrying the two copy files' exact bytes (effective date = the day you run it); you run it by hand in the Supabase SQL editor per `docs/PHASE1-PROCESSING-RUNBOOK.md` ("Policy registration and activation"). Note the version id it creates.
5. Register 02 v1.2 and the retention version by their hashes (scripts as for 03 v1.1 and 06 v1.4).
6. Frontend PR with the strings below (signed), deployed; then at once register the training policy row in the Supabase SQL editor (23's SQL: retire v1 and register v2 at the same instant, hashes filled in).
7. Users re-accept 3.5 ("Accept the update"), then say yes again on the card or at "Turn on the learning?".
8. Then the switch PRs, one per lane, each only after its E-item holds (22, §4) and naming the 3.5 line it relies on: doors 3 and 4 per surface, the coach-word surfaces (E2), corpus copy (E1), import (E7), detector training (E3), V4 sheets and block pick (E4), learned exercise order (E5).

## Consent-screen words to sign (frontend, design-locked; not edited here)

`trainingBeforeLines` in frontend-cursor/src/lib/legal/dataConsentCopy.ts, the four lines become eight:

1. "Text and numbers only. No recording of your voice, and no clip of one, is ever copied or sent for training."
2. "Off unless you turn it on. Saying no costs you nothing." (unchanged)
3. "Your coach's words include their line on a moment and their word for a take."
4. "The numbers are measurements such as your pace and pauses, and whether an exercise helped you. They stay with us."
5. "A coach may hear a moment of yours, without your name, to answer a question that teaches our software."
6. "The trained models write feedback for every speaker. We test that they do not repeat your text."
7. "OpenAI trains the text models for us, in the United States, under the European Commission's standard contractual clauses."
8. "Turning it off deletes your training copies and keeps you out of any new training. A model already trained stays." (unchanged)

The switch sentence (served by the backend, fingerprinted): "Use my practice text, my coach's words and answers about it, and measurements of my practice to train the models that give every WillpowerLab speaker feedback."
`introWithTraining` becomes: "Your recordings are used to run your own coaching. Their words, and numbers measured from them, train models only if you turn on Help improve WillpowerLab."
Unchanged: "Help improve WillpowerLab", "Turn off training?", its body, "Turn on the learning?", "Yes", "Skip".
**Layout question for you:** the locked consent prototype shows four lines above the switch; eight lines is a change to a locked screen. Say "eight lines as listed" or ask for a prototype first.
