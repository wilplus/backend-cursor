# Ranking eval — best-per-slide selection vs the founder's judgment

**Status: protocol RATIFIED (founder, 2026-08-03). Not yet run.**

The measurement for F1's second load-bearing piece: `power_score` +
`select_best_per_slide` decide which spoken line represents each slide in
the assembled best speech. The weights are hand-set and, until this runs,
have never been compared to a human judgment. The selector's losing
candidates are invisible in the product, so **no one — including the
founder — has ever seen the counterfactuals**. This eval is the first time
they exist side by side.

```
VERDICT:  ADVANCE-F1
CATEGORY: F1-SUPPORT
WHY:      Gates two named in-flight F1 pieces: the calibration of the
          power_score blend (L2) and the flip of
          VOICE_CONFIDENCE_RANKING_ENABLED (founder-specced validation
          gate). Read-only; no fence touched (AC-9 internal, blind coach
          preserved, L1/L2 untouched until verdicts say otherwise).
REDIRECT: n/a — this is redirect target (3), sharpening the blended
          best-slide ranking.
```

## The ratified protocol (decision record)

| # | Decision | Ratified choice |
|---|----------|-----------------|
| 1 | Unit / scope | One case = one **(session, slide)** with ≥2 candidate lines. Single takes qualify (the ranker never sees `take_index`). **Decked sessions only** — usage is decked. Deckless + training imports are out of v1: counted, never silent. Imports route to the confidence corpus instead. |
| 2 | Rubric | The rater answers exactly one question: **"Which of these would I put in their best speech?"** — holistic, said + delivered together. |
| 3 | Modality | **Listen to every candidate** (the rubric contains delivery, so transcript-only labeling would contradict it). Tool: the local labeling page. |
| 4 | Sample | All users' decked spoken sessions, **both languages**. (Current reality: the founder's own takes — no customers yet. Consequence, stated: the rater judges their own delivery; blindness to the machine pick survives, take-recognition bias does not. Revisit with first real users.) |
| 5 | Sequencing | Selector eval **now**, with `confidence_on` computed offline from the stamped reads (no flag touched). Confidence-model validation later — its human side falls out of the 1000-label corpus goal (intensity 1–5 through the queue). |
| 6 | Failure modes | None known — the founder has never seen the selector's alternatives (approve-bias on the *suggestions* layer ≠ selection judgment). Random draw + strata carry discovery; no oversampling. |
| 7 | Cadence / size | Spread over days (page resumes via localStorage). Default 30 base cases (10/band), `--per-band` to scale. |
| 8 | "Synthetic" audio | Resolved: it's **imported real speech** (YouTube talks, pitches) → confidence corpus lane. The Subsystem-S wall (machine-generated data) is not implicated. |
| 9 | Escape hatch | **Forced choice always** + a *"none of these belong in a best speech"* checkbox. Report scores twice: all cases, and garbage-flagged excluded. **Actions key off the clean pass.** |
| 10 | Noise ceiling | **~10 disguised repeats** at the end of the run, letters reshuffled, indistinguishable from fresh cases. Self-agreement across pairs (matched by picked snippet) = the ceiling. |
| 11 | Decision rules | R0–R5 below, agreed before any number existed. |

## The rules (R0–R5)

**Verdict standard for R1–R3:** judged on cases where challenger and
shipped **differ**; *decided* = exactly one matched the human;
**clear win = ≥6 decided cases AND ≥2/3 challenger share.** Fewer than 6 →
`insufficient_data` → extend the set; a coin flip is not a conclusion.

- **R0 — Ceiling.** Self-agreement < 0.70 → refine the **rubric**, convict
  nothing. All other verdicts print as `GATED_BY_R0`.
- **R1 — Sentence gate.** `no_sentence_gate` clear win → demote
  completeness from hard sort key to tiebreak in `select_best_per_slide`.
  Shipped holds → the gate stays, validated instead of assumed.
- **R2 — Coverage double-count.** `debiased_coverage` clear win → fix the
  activation input so slide coverage enters `power_score` once, not twice
  (`overall_score` = 0.5·topic + 0.5·slide already contains it;
  `lab_recording.py:759`).
- **R3 — The voice term.** `confidence_on` clear win → evidence to flip
  `VOICE_CONFIDENCE_RANKING_ENABLED` (founder sign-off). Loss → the
  composite goes back for calibration before it ever moves a pick.
- **R4 — Dedupe cost.** `shipped_local` − `shipped_assembly` agreement gap,
  report-only.
- **R5 — Floor.** Shipped (clean pass) more than 20 points below the
  ceiling → offline weight sweep against these labels + a **fresh**
  confirmation batch (weights tuned on labels can't be validated on them).

## Variants scored

| Variant | One isolated change |
|---|---|
| `shipped_local` | the production per-slide pick |
| `shipped_assembly` | after cross-slide dedupe (an earlier slide can steal a later slide's line) |
| `no_sentence_gate` | completeness demoted to tiebreak |
| `debiased_coverage` | topic recovered as 2·overall − slide |
| `confidence_on` | stamped voice-confidence served into the blend |

Drift-proofing: picks come from the **real** `select_best_per_slide` /
`power_score` imports. The one mirrored piece is the snippet→candidate
field mapping (`build_best_presentation:626-694`, cited line-by-line in
`services/ranking_eval.py`).

## Running it

```bash
# 1. Draw (needs the app's Supabase env; read-only):
./venv/bin/python scripts/export_ranking_eval.py --out /tmp/ranking_eval --seed 7
# → labeling_page.html (open in browser), key.csv (KEEP CLOSED), blind_sheet.csv

# 2. Label on the page — forced choice, listen first, checkbox for garbage
#    slides, optional "why" (feeds the coach corpus). Progress auto-saves.
#    Finish → "Download answers" → ranking_answers.csv

# 3. Score:
python scripts/score_ranking_eval.py \
    --answers ranking_answers.csv --key /tmp/ranking_eval/key.csv
```

Export warnings that change what the numbers mean (printed, act on them):
**stamped confidence coverage = 0** → R3 structurally cannot differ (pieces
predate the composite; record fresh takes); **audio URL failures** → those
cases can't honor the listen-first rubric.

## What agreement can and cannot say

30–50 cases with one rater can **demote a rule that fights human judgment,
catch a structural bias, and justify one flag flip**. It cannot certify the
ranker "good" — it is a regression net and a tiebreak for named suspects.
The disagreement list (with the rater's `why` notes) is the actual product
insight; the rates only say where to listen.

## Fences

AC-9 — internal, coach-side; no score, verdict, or agreement rate ever
rides a user payload. BLIND — the rater surface carries no machine read;
bands and repeat markers live key-side only. L1/L2 — untouched by the
measurement; only ratified verdicts may change selection code, each as its
own gate-routed PR.
