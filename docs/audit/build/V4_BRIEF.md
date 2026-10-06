# V4 decision record and Developer brief (verbatim from https://claude.ai/artifact/UXiVaBvGLRTg83kjmHKY6E, founder-signed 2026-10-05/06)

## Decision rows
M1 agreed — Three learned models. Recognizer (how willfident is each moment), Picker (which moment, which feedback), Feedback writer (praise, clearer versions, exercise scripts). The existing exercise picker (keep or swap) sits beside them.
M2 agreed — Fixed rules are never learned. Praise only on a confident read; rewrite or exercise only on a weak one; slide coverage; the honest empty lane; V3 as fallback.
M3 agreed — Two models, not one. The recognizer measures and stays frozen and universal; the picker decides and personalises.
M4 agreed — Two loops. Fast loop (seconds, machine only) decides on every Take and never waits for a coach. Slow loop (1–2 days, weekly) corrects through human ratings and batch re-learning.
M5 agreed — Teaching chain. Humans check the recognizer; the recognizer teaches the picker every day. The recognizer is trained first.
M6 agreed — Global plus personal. Personal share = n ÷ (n + 8), half personal after 8 Takes. Only the picking is personalised; willfidence stays universal.
M7 agreed — Inferred learning. Spoken adoption plus next-Take rise; durability at Take N+2; testing on past data from the 20% random picks and logged pick chances; the coach's normal walk (praise vs error, practice judgements); coach edit diffs; natural A/B from Take N vs N+1 words; edit size; exercise effect from detectors.
M8 agreed — Inference guards. Speaker taps are never labels (L3). Inferred labels live in a separate, versioned weak lane. Golden sets stay human-only. A small sample is audited by hand.
M9 agreed — With one coach. Main picker teacher is the next-Take rise. Golden set = coach and founder agree. Coach re-picks about 10% after 2–3 weeks. Coach is asked only where the picker is unsure, about 10 a week.
M10 agreed — Training stays off until the founder opens it: 200 new pairs per surface and the golden evaluation (C6).
Screens table — Picker: coach "Pick the moment for feedback" (proposed); user: no tap, inferred from Record Take N. Recognizer·sound: coach "Judge this moment" (built), "Pick the most confident" (built, off; accuracy check only); user "Lend your ear" on other people's clips (backend built, no screen). Recognizer·words: coach "Which sounds surer, Yes / No" (proposed); user none (L3). Exercise picker: coach Keep it / Swap it / Make a new one (built, dark); user no tap. Feedback writer: coach "Your clearer version, Your video, Where it lives, A word for this Take" (built); user none. Wording on every proposed coach screen goes through the coach-panel lock.
P1 agreed — Allowed first, best second. The sound read decides which kind of feedback a moment may carry; the picker ranks within that.
P2 agreed — Ranking, live, machine only: rank = importance × (1 − S·W) × sureness; importance = LLM role tag from a fixed, versioned list; gap = 1 − S·W; sureness = evidence strength × (1 − disagreement between machine reads); low → tentative wording · very low → fall back to V3.
P3 agreed — Confident Voice stays on the best-sounding moment of each block (contract 24b).
P4 signed — Ship as V4 in a dark run beside V3. Guardrail: slide coverage 70 / 80 / 100% must hold. Every candidate's pick chance is logged.
P5 agreed — Success = willfidence on that paragraph rises in the next Take, measured instantly by the machine and corrected later by humans.
P6 agreed — Coach words queue: 40% above threshold · 40% below · 20% random, shuffled, coach blind to the slice. One Yes / No per pair, which also gives the feedback writer a DPO pair.
Willfidence — S = (coach + peer + machine) ÷ 3; W = (H + A + T + F + N) ÷ 5 (hedging · slide alignment · cohesion · 1 − filler rate · naturalness); Willfident = S·W, Hollow = S(1 − W), Hidden = (1 − S)W, Lost = (1 − S)(1 − W); willfidence (Take or person) = average of S·W over the random moments; spread Δ = max(c,p,m) − min(c,p,m). Internal only (AC-9), every input stored separately (L3), frozen as willfidence-v1.
W1 agreed — Moments: machine picks plus 20% random. Only the random ones are scored; machine picks are kept as "peak".
W2 agreed — Unrateable is left out, after a backup rater. Under 10 moments: "not enough data". Over 30% dropped: "audio problem".
W3 agreed — Words weights start equal and are later learned from the Yes / No pairs.
W4 agreed — Study use: anchor for testing links to stress (validated scale) and sales (CRM), with consent, pseudonymised, never fed back into the product.
Q1 agreed — Votes: Yes 1 · In-between 0.5 · No 0. Several peers are averaged. The machine contributes its raw value.
Q2 signed — Soft training labels: a clip is labelled with the share who said Yes. Needs 3–5 raters per training clip. The test set stays hard (settled quorum only).
Q3 agreed — The training label ledger keeps its humans-only quorum. The machine's vote exists only inside the willfidence KPI.
Founder rules changed (signed): 1 the machine votes in willfidence's SOUND for the KPI only (was D8 "router not rater"); 2 willfidence covers sound and words (was D19); 3 soft labels for training, hard test set; 4 V4 after a dark run (was "V3 is the served policy"); 5 new coach screens and wording (coach-panel lock); 6 spoken adoption as an inferred signal (L3 borderline).
O1 open — The exact role list and values for importance. O2 open — the "very low sureness" cut-off for V3 fallback. O3 open — written definitions for each WORDS dimension, and the external anchor for the sales link.
H1 decided — Voice Album lost the speaker's Yes. The speaker answers "Does this sound confident to you?" right after saving helper words.
H2 decided — Max 3 vs coverage: the walk takes the speaker through at most 3 paragraphs; coverage 70/80/100% stays as the backend target; other paragraphs keep their orange bar.
H3 decided — "Reached" before WORDS exists: S × the partial W from today's word signals (fillers, hedging, slide alignment, cohesion).
H4 decided — Peer lane: Lend your ear and the share switch are parked until the legal policy version and counsel.
H5 decided — Order: measure first (dark), the new walk second, after V4 proves itself.
H6 decided — Role tag cost: one batched LLM call per Take.
H7 decided — Founder time: about 10 golden-set blocks a week, matching the coach.
H8 decided — Coach screens: Pick the moment and Which sounds surer in Phase 1; the paragraph stack in Phase 2.
O4 decided — "Reached" bar set from Phase 1 data: the S×partial W level where the blind coach says "Yes, confident" about 7 in 10; placeholder 0.6 dark only; internal, never shown.
O5 decided — Practice read under 5 s for 9 in 10 attempts; if late or failed never block: show Next / Practise again, treat as "not reached yet", log the late read.

## Developer brief (verbatim)
PHASE 1 · MEASURE (speakers see nothing new)
1.1 Pick logging. Extend the V3 shadow frame: every candidate, its chance of being picked, the random seed, policy version.
1.2 Random 20%. Per Take, a seeded random 20% of moments, stored apart from the machine's picks.
1.3 Willfidence-v1 (machine only). Per moment: S = machine sound read; W = mean of the word signals that exist today (1 - filler rate, 1 - hedging, slide alignment, LLM topic cohesion). Store S, W, the four boxes, judge spread. Version stamp "willfidence-v1-machine". Never in any user payload (AC-9).
1.4 Fast read on practice attempts. Compute S and partial W on every practice clip. Target (O5): result within 5 s for 9 in 10 attempts (p90 <= 5 s), measured from Stop. Measure and report it. Never block: past the limit, or on failure, the walk treats the attempt as "not reached yet" and offers Next / Practise again; the late read is still stored. The live loop never waits.
1.4b Reached-bar calibration (O4). From 1.3 reads + blind coach answers (1.8/1.9 and existing labels), find the S x partial W level where coaches say Yes about 7 in 10. Placeholder 0.6 until enough answers exist (dark only). Version the bar; never in any user payload (AC-9).
1.5 Outcome per pick. For each picked paragraph: willfidence in Take N vs Take N+1, matched by paragraph identity. Store "rose / didn't". This is the picker's main teacher.
1.6 V4 picker, dark. Within what the sound read allows (praise only on a confident read; rewrite/exercise only on weak): rank = importance x (1 - S*W) x sureness. importance = ONE batched LLM call per Take tagging each moment's role from a fixed, versioned list. sureness = evidence strength x (1 - disagreement between machine reads); below a cut-off, fall back to V3. Runs beside V3, serves nothing. Slide coverage 70/80/100% stays as a backend target (guardrail).
1.7 Vote gradation. Store answer counts per clip (soft-label data). The training label ledger keeps its humans-only quorum; the machine never votes there.
1.8 Coach sheet "Pick the moment for feedback" (blind; words + audio; "None needs it"). Golden set = blocks where coach and founder pick the same moment. Founder answers the same sheet. About 10 blocks a week each; queue only blocks where the picker is unsure, plus a random share.
1.9 Coach sheet "Which sounds surer" (Yes / No / Can't tell). Queue 40% above threshold, 40% below, 20% random, shuffled, coach blind to the slice. The system varies only the word qualities it is least sure of. Store as WORDS labels and as DPO pairs. Training stays off.
EXIT GATE: V4 beats V3 on golden-set agreement AND next-Take rise; coverage holds; practice read p90 <= 5 s; reached bar calibrated (1.4b).
PHASE 2 · THE NEW WALK (after the founder switches V4 on)
2.1 Serve V4.
2.2 New feedback walk (speaker screens are under the design lock: built by the designer session): Ideal Text -> tap an orange paragraph -> overlay. Inside one paragraph: intervention 1..n (clearer version, exercise, praise, or future kinds in the same slot), each ends in Practise. After each attempt the fast read decides: not reached -> next intervention (or Practise again / Skip when none left); reached (S x partial W >= the bar from 1.4b) -> helper words (up to 4) -> the speaker's own "Does this sound confident to you?" (five answers; keeps Voice Album three-yes alive) -> next paragraph. The walk takes the speaker through at most 3 paragraphs per Take; other paragraphs keep their orange bar and open on tap. End card: "Record Take N+1" / "Back to the text". No number or verdict is ever shown.
2.3 Coach screen "This paragraph's feedback": the stack of interventions and what the speaker did, in words.
2.4 A coach answer joins the paragraph's stack as its next intervention.
PARK (do not build now)
- P-a Lend your ear screen and the Voice Album share switch (waits for the legal policy version and counsel).
- P-b Training door: recognizer on soft labels, weekly picker re-learning, DPO feedback writer at 200 pairs.
- P-c Personal layer (n / (n + 8)) and per-speaker feedback-type learning.
- P-d Inferred "weak lane" signals (spoken adoption, durability, coach edit diffs).
- P-e Full WORDS (all five qualities; lexical-dilution detector) and full willfidence with peer votes.
- P-f "Pick the most confident" switch-on, learned exercise ordering (E8), Students, two-coach golden set, the stress/sales validation study.
HARD RULES: AC-9; L3 speaker taps never training labels; live loop never waits for a coach; migrations idempotent; config before code; local_ci gate; every new user-facing string needs founder sign-off.
OPEN: O1 (1.6), O2 (1.6), O3 (Phase 2 full W).
