# Vocal-emotion acoustics — what we can measure, and where it stops

**Status:** reference doc (task T4 · 4.2). Primary source, not reconstructed.
**Backs:** the shipped arousal-capture signal (`services/delivery_stars.arousal_z`, PR #249).

## Source

Juslin, P. N., & Laukka, P. (2003). *Communication of Emotions in Vocal
Expression and Music Performance: Different Channels, Same Code?*
**Psychological Bulletin, 129(5), 770–814.** A meta-analysis of **104
vocal-expression studies**, built on **Scherer's (1986)** predictions. The
per-emotion cue patterns below are their **Table 7** (pp. 792–795); **bold in
that table = the most frequent finding across studies**, which is what's
distilled here. Cue definitions are their Table 6.

The five emotions this literature supports are **anger, fear, happiness,
sadness, tenderness** (p. 772). It is *tenderness*, not disgust — disgust is
dropped from vocal-emotion sets because it communicates poorly through voice.

## The phone-recordable cues (Table 7, vocal expression — dominant pattern)

Directions are **relative to the speaker's own neutral baseline** (the paper is
categorical High/Med/Low, Fast/Slow — absolute Hz/dB are speaker-specific,
which is why we z-score against each speaker's baseline).

| Acoustic cue *(phone-extractable)* | Anger | Fear | Happiness | Sadness | Tenderness |
|---|---|---|---|---|---|
| **Speech rate** | Fast | Fast | Fast | Slow | Slow |
| **Voice intensity** (loudness, mean) | High | High\* | High | Low | Low |
| **Intensity variability** | High | High | High | Low | Low |
| **F0 mean** (pitch) | High | High | High | Low | Low |
| **F0 variability** (pitch range) | High | High | High | Low | Low |
| **F0 contour** (direction) | Rising | Rising | Rising | Falling | Falling |
| **High-frequency energy** (spectral) | High | High\* | High | Low | Low |
| **Pauses** (proportion of silence) | Few | — | — | **Many** | — |
| **Voice onset / attack** | Fast | Slow | Fast | Slow | Slow |
| **Microstructural regularity** | Irregular | Irregular | Regular | Irregular | Regular |

Speech rate, voice intensity, and high-frequency energy are the paper's **three
major cues** — the most consistent across all 104 studies (p. 789).

### Cue definitions (Table 6, condensed)
- **F0 / pitch** — rate the vocal folds open/close; the lowest periodic component.
- **F0 contour** — the sequence of F0 across an utterance (intonation).
- **Intensity / loudness** — energy in the signal (dB); the effort to produce speech.
- **Speech rate** — units per duration (e.g., words/min).
- **Pauses** — number/duration of silences.
- **High-frequency energy** — proportion of energy above a cutoff; more = sharper voice.
- **Attack** — rise time of amplitude at voice onsets.

## The limitation — read this before building on it

**These cues assign *arousal* (activation), not the five emotions individually.**
Down the columns: anger / fear / happiness are near-identical (fast, loud,
high-pitch, rising, high-energy), and sadness / tenderness are their mirror.
So from phone audio one can **cleanly separate high-arousal from low-arousal**,
but **cannot reliably tell anger from happiness from fear**, because:

- The cues that *do* separate them — **formants (F1), jitter, precision of
  articulation, glottal waveform** (pp. 795–796) — **do not record reliably on
  a phone** (they need clean, close-mic audio and inverse filtering).
- **Fear is bimodal (\*):** mild fear is soft/low-energy, panic fear is
  loud/high-energy (p. 789), so it straddles the arousal axis.
- **Valence is not recoverable** from these cues (happiness vs. anger are both
  high-arousal; what differs isn't in the gross signal).
- **Tenderness has the fewest studies** (6 vs. ~30, Table 4) → least robust.

## What we built on this (the honest scope)

`services/delivery_stars.arousal_z(piece_metrics, baseline)` computes a
**continuous, graded arousal read** per snippet — the mean of the
speaker-normalized cues signed toward activation (wpm↑, dynamic_db↑, f0_sd↑,
pause_ratio↓). It reads the **arousal axis only**, never a discrete emotion,
and it is **captured, not surfaced** (AC-9: no scores/verdicts on user
payloads) and **not fed into ranking** (activation is not quality). See
`migrations/add_snippet_arousal.sql` and the memory note `willab_arousal_signal`.

A true five-way discrete-emotion classifier from phone audio is **not**
supported by this data. Surfacing any positive/negative "integrity" or emotion
verdict to a user would also breach AC-9 regardless of detector quality.
