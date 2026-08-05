# Appendix E — Research Findings and Required Amendments

**Last updated:** 2026-08-05.

**Companion to SPEC.md v3.** Six targeted searches, run against the confidence/prosody literature. **Four of the six change the spec.** Amendments are listed per finding and consolidated in E.7.

---

## E.1 · Weighted multi-cue confidence composites — essentially none exist

**Answer: one published hit, one proprietary, everything else univariate.**

### The one hit — usable as a prior

**Jiang & Pell (2018), "Predicting confidence and doubt in accented speakers," Speech Prosody 2018.** 6 speakers, 18 raters, XGBoost, 7 acoustic predictors, permutation feature importances rescaled 0–100:

| Cue | Native model | Foreign-accented | Regional |
|---|---|---|---|
| mean F0 | **100.0** | **100.0** | 98.7 |
| duration | 83.2 | — | — |
| F0 range | 65.1 | — | 27.8 |
| amplitude range | 38.1 | 19.9 | **100.0** |
| mean amplitude | — | 38.0 | — |
| SD HNR | 13.7 | — | — |

https://www.isca-archive.org/speechprosody_2018/jiang18_speechprosody.pdf

**This is the only external anchor that exists for your cue weights.** Note the ordering is unstable across accent groups — amplitude range goes from 38 to 100 depending on the speaker population. That instability is itself informative: it argues against a single fixed weight table and toward per-population re-fitting, which is what your `benchmark_version` machinery already supports.

### Everything else

- **PASCAL (Niebuhr)** claims a weighted composite over 6–9 prosodic features with non-linear "sweet spot" relationships — **weights withheld, patent pending.** Validated only against oral-exam grades, n=21, r²=0.56.
- **Jiang & Pell (2017)**, the paper `voice_confidence.py` is built on, runs **separate mixed-effects models per cue**. An LDA is mentioned; no loadings are reported.
- Rosenberg & Hirschberg, Pon-Barry, Kirkland, Levitan, the *Nature Communications* 2021 reverse-correlation paper: all univariate correlations, significance tests, or aggregate-only classifiers. None publishes per-cue weights.
- A 2026 systematic review of persuasion acoustics surveys this literature and identifies no weighted composite either.

**AMENDMENT E-1.** `services/voice_confidence.py`'s composite is, as far as the published record goes, **novel**. That is a defensible position and it should be stated as such in any external material — not as "based on the literature," which overclaims. The literature gives cue *directions*; the weighting is yours.

**AMENDMENT E-2.** Add the Jiang & Pell 2018 importances as a **comparison prior** in the validation export. When your weights are re-fit at 200 labels, report the rank correlation between your fitted weights and this table. Divergence is not a failure — it is a finding worth reporting, and it is the only external benchmark available.

---

## E.2 · The sex reversal rests on n=6 — and may be a measurement artefact

**This is the finding with the most direct consequence for shipped code.**

### What Jiang & Pell actually did

6 talkers total — **3 female, 3 male**. The interaction *was* formally tested: **Speaker Sex × Confidence Level on f0 variation, F(3, 1552) = 25.70, p < .001**, with opposite slopes (female: f0 variance highest when confident; male: highest when unconfident).

**But df = 1552 counts utterances, not speakers.** The test is well-powered against utterance noise and tells you almost nothing about generalisation across the sex population. Three talkers per cell.

### No replication exists

- Jiang's own 2018 follow-up used 6 speakers again and did not re-test the interaction.
- A 2022 Wuxi-dialect confidence study (4 speakers) excluded sex as a factor.
- A 2019 JASA study on female confidence cues has **no male comparison group**, so it cannot test the reversal.

### The artefact risk — and it is testable

Women's f0 baseline is ~70% higher (median ≈195 Hz vs ≈114 Hz, a ~9-semitone gap). **The same semitone excursion is more Hz at a higher baseline.** If f0 variance was measured on a Hz scale, an apparent sex reversal can be a scale artefact rather than a real sign flip. Jiang & Pell's measure was normalised (max−min after normalisation) but the source does not state it was semitone-based, and this could not be resolved from the available text.

**AMENDMENT E-3 — run this check before trusting cue 1's sign flip.** Recompute f0 variability in **semitones** on your own corpus and re-test the sex × confidence interaction.

- If the reversal survives semitone normalisation → it is real, and `_CUES_BY_SEX` cue 1 is correctly specified.
- If it disappears → cue 1 should not flip, and the sex-routing table is unnecessary *for that cue* (the three weight-shifting cues may still stand).

This is cheap, decisive, and it is the single highest-value experiment available on your existing data. The §5.3 justification for keeping the sex-routed table — *a sign flip cannot be absorbed by within-speaker z-scoring* — holds **only if the flip is real.**

### The better-replicated sex effect is on the perception side

Same acoustics, attributed differently by perceived speaker gender: a female-pitched voice with rising intonation rated less confident than an acoustically identical male-pitched voice (JASA 151(5), 2022). **The effect vanished in multi-talker conditions** (n≈200, open-access companion). A 2025 JSLHR mouse-tracking study replicates the direction.

**AMENDMENT E-4.** The listener-side bias is better evidenced than the production-side reversal. Panel design should account for it: if raters hear a single speaker in isolation, gender stereotyping is maximal; interleaving speakers of both sexes within a rating session measurably reduces it. **Randomise speaker sex within each rater's queue** — this costs nothing and mitigates the better-supported bias.

---

## E.3 · Perception penalty magnitudes — the pitch leg is strong, the vocal-fry leg is weaker than represented

### Klofstad's pitch work — the only calibratable numbers in the literature

- Manipulation: **±0.5 ERB**. Female 189–207 Hz unaltered → 214–233 raised / 170–190 lowered. Male 91–116 → 110–136 / 81–98.
- **The low-pitch preference is 4–5× stronger for female speakers**: competence F(1,786)=40.08, p<.001, **partial η² = .05** vs ~.01 for male voices. Voting preference F(1,788)=30.78, η²=.04. Replicated in a 2016 CCES sample (N=804): ~71% chose the lower-pitched female clip vs ~60% for male.
- Real-world anchor: across 796 US House candidates, **a 40 Hz pitch decrease predicted a 13.9-percentage-point increase in win probability** (β=−.01, p=.038).

**This asymmetry — η²=.05 vs .01 — is the strongest evidence for sex-conditional calibration in the whole body of work.** It should be the primary citation in §5.2, not vocal fry.

### Vocal fry — correcting the earlier framing

Vocal fry has been cited repeatedly as justification. The evidence is weaker than that use implied:

- Anderson et al. (2014), N=800: the female-specific penalty is significant but **small** — partial η² ≈ **0.79–1.26%** across trustworthiness, competence, education, hireability. Attractiveness n.s.
- **A credible artefact critique exists.** Speakers *imitated* fry rather than producing it naturally; imitated-fry sentences ran 2–29% longer; pitch dropped even on fry-free words; no acoustic measures of creak (jitter, shimmer, CPP) were reported. The penalty may reflect general unnaturalness.
- **The direction is not stable.** Anderson et al. (2018, N=463) crossed pitch × rate × fry and found a significant three-way interaction — fry rated *favourably* at high pitch + fast rate, unfavourably at low pitch + fast rate. It is not a main effect.
- A 2022 replication found a much larger effect (ηp² .25–.39) but with n=29 listeners.

**AMENDMENT E-5.** Demote vocal fry from a justification to a supporting note in §5.2. Lead with Klofstad's η² asymmetry. Do not build a creak-percentage detector — no publishable threshold exists, and the sign is conditional on co-occurring pitch and rate.

### Uptalk — confirmed thin

No controlled perception experiment isolating uptalk's competence effect by speaker sex with usable effect sizes. The widely-cited claims are sociolinguistic correlation (Linneman) or journalism. **Earlier assessment stands; keep it off the dimension list.**

---

## E.4 · Thresholds — (A) empty, (B) exactly what was needed

### (A) No confidence-specific cutoff has ever been published

Searched perceptual-threshold, categorical-boundary, and ROC/operating-point framings. Jiang & Pell 2017, the *Nature Communications* 2021 reverse-correlation paper, and a 2026 systematic review all report slopes, correlations and directions — **never a boundary value.** No paper applies ROC/signal-detection cutoff analysis to confidence perception.

This confirms Appendix D.0: for confidence, T1 does not exist and cannot be manufactured.

### (B) Psychoacoustic JNDs — these become detector floors

| Parameter | JND | Source |
|---|---|---|
| **F0 excursion → prominence** | **1.5 semitones** produces a detectable difference in perceived prominence | Rietveld & Gussenhoven (1985), *J. Phonetics* 13(3) |
| **Speech tempo** | **~10%** (9.0% accelerating, 11.5% decelerating; 2IAX task, natural Dutch speech) | Quené (2007), *J. Phonetics* 35(3) |
| **Pause duration** | Abrupt drop in perceived willingness above **600–800 ms** | Roberts & Francis (2013), *JASA* 133(6) |
| **F0 glide detection** | `G_thr = 0.16 / T²` semitones/sec — below this an F0 change is heard as a step, not movement | 't Hart, Collier & Cohen (1990) |
| **Amplitude masking** | A **10–20 dB drop within tens of ms can fully mask an F0 change of up to half an octave** | 't Hart, Collier & Cohen (1990), p.36 |
| Intensity JND in speech | **Not published** as a speech-specific figure. Genuine gap. | — |

**AMENDMENT E-6 — add a perceptual floor to every SPEAKER_REL detector.** An acoustic change below JND cannot be perceived, so flagging it is a *guaranteed* false positive regardless of how many z-scores it spans.

```python
PERCEPTUAL_FLOOR = {
    "f0_excursion":  1.5,    # semitones
    "speech_rate":   0.10,   # proportion change
    "pause":         0.60,   # seconds
}
# fire only if BOTH:  |z| > fire_at  AND  raw_delta > PERCEPTUAL_FLOOR[cue]
```

**AMENDMENT E-7 — implement the amplitude-masking guard.** If an F0 excursion co-occurs with a ≥10 dB amplitude drop inside a few tens of milliseconds, **suppress the f0-based finding.** The listener cannot hear the pitch change; a panel will rate "no difference" and the detector will look wrong when it is the physics that is wrong.

**AMENDMENT E-8 — do not conflate 250 ms with 600–800 ms.** The 250 ms figure common in fluency research is an *analyst's convention* for what counts as a pause at all. The perceptual threshold at which a pause changes a social judgment is **600–800 ms**. Use 250 ms for segmentation, 600 ms for firing.

---

## E.5 · Panel size — 2 raters is far below what a percept needs

**This is the finding that most challenges current Album Engine design.**

| Evidence | Number |
|---|---|
| Affective trait ratings (trustworthiness, warmth, dominance) — the closest analogue to confidence | **25–36 naive raters per stimulus → α = .88–.93** (McAleer, Todorov & Belin; corrected reading — the headline "320 listeners" is *total*, each rating one trait across 64 voices) |
| Voice quality, naive crowd vs trained clinician | **≥9 naive MTurk listeners** converge on trained-SLP reliability (Mehta et al., *J. Voice* 2015) |
| Trained vs naive ICC gap, same task | **.73 vs .53** — roughly 0.20 ICC from experience alone (Helou et al., CAPE-V overall severity) |
| Formal G-theory decision study (L2 speech, best available methodological analogue) | comprehensibility: **15 trained / 50 untrained** for G ≥ .90 · accentedness: **60 trained / 80+ untrained** |
| CAPE-V / GRBAS single-rater ICC | .75–.85 overall severity; **.56–.70** for harder dimensions (roughness, strain) |

**No G-theory decision curve exists for CAPE-V or GRBAS itself** — reported ICCs are for the panel that happened to be used.

**AMENDMENT E-9 — restate the Album panel standard honestly, in three tiers.**

```
n = 2         DIRECTIONAL ONLY. Not a validated label. Never enters training as ground truth.
n ≥ 9         Actionable. Approximates trained-rater reliability (Mehta et al.).
n = 25–36     Validated. α ≈ .88–.93 for affective traits. Gold-set standard.
```

Two consequences the spec must absorb:

1. **The `coach + owner` fallback (§9.1) is n=2 with one non-blind rater.** Under this table it is *directional only* — it cannot produce a validated label, and it must not train the recognizer as though it could. §9.1's existing framing ("one expert plus a self-report, not a panel of two") was right; this quantifies how far short it falls.
2. **Cross-user peer play is no longer a nice-to-have.** It is the only route to n≥9, and n≥9 is the floor for anything actionable. The open consent question in §9.2 is now a **blocking dependency for the Album Engine producing usable labels at all**, not just for its statistical quality.

**AMENDMENT E-10.** The 40-clip gold set should carry **25–36 ratings per clip**, not 2. That is 1,000–1,440 ratings — infeasible from coaches, entirely feasible from the game lane. This is the strongest argument yet for the peer lane, and it re-scopes the 40-clip pass: coach adjudication *plus* deep peer coverage on the same clips.

---

## E.6 · Within-speaker normalisation — the counter-evidence hits §5.1 directly

**§5.1 currently makes speaker-relative normalisation primary. The evidence is genuinely mixed, and one counter-example is specifically about charisma.**

### For

- **Feature warping** (Sethu, Epps & Ambikairajah, DSP 2007): binary neutral-vs-anger **91.6% → 95.2%** (+3.6 pp); 5-class **35.3% → 41.6%** (+6.3 pp, ~18% relative).
- **Rosenberg & Hirschberg** z-scored f0 per speaker explicitly to control for gender and individual baseline. The speaker-normalised z-score of mean f0 correlated with charisma at p<.01 **across both sexes**, whereas raw f0 measures reached significance **only for male speakers**. Normalisation *fixed* a sex-specific failure — directly relevant to E.2.
- Speaker-dependent models consistently outperform speaker-independent ones across the SER literature.

### Against

- **Niebuhr et al. explicitly tested a baseline-corrected (speaker-normalised) f0 measure against charisma and it performed *worse*** than raw arithmetic mean f0, which was the best-performing measure. The "acoustic fingerprint" paper uses **absolute** f0 measures throughout — mean, SD, coefficient of variation, percentile range — not within-speaker normalisation.
- **Mariooryad & Busso (2014)**: speaker whitening slightly *decreased* accuracy on the full feature set (55.32% → 54.45%), improving only ~2.4% relative after feature selection.

### The resolution

The two results are not in conflict once you separate what is being normalised:

> **Normalise the dynamics. Keep the level.**
>
> Within-speaker signal — f0 *range*, amplitude *range*, rate *variation*, proportion-of-own-range — is where normalisation helps.
> Between-speaker signal — absolute mean f0 — carries genuine trait information, and normalising it away removes real signal.

**AMENDMENT E-11 — amend §5.1.** Speaker-relative normalisation is primary **for dynamic/range cues**. For absolute-level cues (mean f0), compute **both** the raw and the speaker-normalised value, carry both as features, and let the re-fit decide. This costs one extra column and resolves a genuine contradiction in the literature rather than picking a side without evidence.

**AMENDMENT E-12 — the baseline minimum in D.4 is invented.** No paper in this literature publishes a minimum duration or utterance count for a stable speaker baseline. The "3 recordings / 8 minutes" figure has no source. Mark it `T3-cold`, derive it empirically from your own data (the point at which a speaker's running z-score stabilises), and stop presenting it as a requirement with a basis.

---

## E.7 · Consolidated amendments

| # | Amendment | Touches | Priority |
|---|---|---|---|
| **E-3** | Re-test cue 1's sex reversal in **semitones**; the sign flip may be a Hz-scale artefact | `voice_confidence.py` v2, §5.3 | **Do this first — cheap, decisive, and it validates or kills the sex-routing table** |
| **E-9** | Restate Album panel standard as 3 tiers (n=2 directional / n≥9 actionable / n=25–36 validated) | §9.1, §9.2 | **High — n=2 cannot produce a training label** |
| **E-10** | Gold set needs 25–36 ratings per clip, not 2 | §12.3 | **High — re-scopes the 40-clip pass** |
| **E-6** | Perceptual floor on every SPEAKER_REL detector (1.5 ST, 10%, 600 ms) | Appendix D | **High — eliminates a class of guaranteed false positives** |
| **E-7** | Amplitude-masking guard: suppress f0 findings under a ≥10 dB co-occurring drop | Appendix D | Medium |
| **E-11** | Normalise dynamics, keep level; carry both raw and normalised mean f0 | §5.1 | Medium |
| **E-5** | Demote vocal fry to a supporting note; lead §5.2 with Klofstad's η²=.05 vs .01 | §5.2 | Medium |
| **E-4** | Randomise speaker sex within each rater's queue | §9.1 | Low cost, do it now |
| **E-2** | Add Jiang & Pell 2018 importances as a comparison prior in the validation export | validation export | Low |
| **E-12** | Mark the D.4 baseline minimum as invented; derive empirically | Appendix D.4 | Low |
| **E-1** | State the composite as novel, not literature-derived, in external material | positioning | Low |
| **E-8** | 250 ms is segmentation; 600 ms is firing. Do not conflate | Appendix D | Low |

**Two things worth noting about the shape of these results.**

Nobody has published a weighted confidence composite, no confidence threshold exists anywhere, and the minimum-baseline question is unanswered. **Those are not gaps in the search — they are gaps in the field**, and each is a place where your corpus produces a first rather than a replication.

The counterweight: the sex reversal is one 6-talker study with a plausible scale artefact, and 2 raters is roughly an eighth of what a stable affective percept needs. Both are load-bearing in the current design, and both are cheap to check before they become expensive.
