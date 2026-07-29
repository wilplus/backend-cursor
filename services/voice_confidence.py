"""Voice-confidence composite (founder spec 2026-07-27, sourced to Jiang & Pell
2017, Speech Communication 88:106-126) — the DELIVERY half of the L2 blend.

WHAT IT IS. Per piece, a fixed, acoustic-only composite locating the moment on a
confidence SPECTRUM: -1.0 (doubtful) … 0.0 (neutral band) … +1.0 (confident).
Seven cues read off the metrics blob the pipeline already computes, each
z-scored against the SPEAKER'S OWN baseline (never absolute across
speakers/rooms — the paper normalizes within-speaker and so do we), signed
toward confidence, weighted-summed, and squashed through tanh with a NEUTRAL
DEAD ZONE so a middling clip reads middling instead of being forced to a pole.

WHY IT EXISTS. power_score's `activation` term is fed by ``overall_score``,
which services/lab_recording.py computes as
``0.5 * topic_stickiness + 0.5 * slide_stickiness`` — both LLM reads over the
TRANSCRIPT TEXT. So before this module the "blended" ranking (L2) carried no
delivery/acoustic term at all; acoustics only gated which pieces were eligible
to be ranked (services/snippet_salience.py). This adds the missing half as its
OWN term, ALONGSIDE stickiness rather than replacing it (founder: "the
confidence of the voice score is one thing; the topic stickiness is another
thing and it is combined to give me the ultimate score").

THE CUES (direction from the paper; weights are OURS and provisional).
  1 pitch range      f0_sd              wider  → +confident   [Table 3: 1.32 vs 1.09]
  2 loudness range   dynamic_db         wider  → +confident   [Table 3: 1.47 vs 1.17] Tier-A
  3 mean pitch       f0_mean            higher → -confident   [Table 3: 0.51 vs 0.70]
  4 speech rate      wpm                faster → +confident   [Table 3 duration: 1.11 vs 1.38]
  5 pausing          pause_ratio/_ms    more   → -confident   [abstract + Table 4] Tier-A
  6 terminal contour f0_mid_end_delta   falls  → +confident   [Sec 3.2.1.1, Fig 4a]
  7 energy contour   intensity_envelope decays → +confident   [Sec 3.1.1.4, 3.2.1.3]

SEX CONDITIONING (v2, founder spec 2026-07-29 — same paper, Sec 3.1/3.2).
Cue 1 does not merely weigh differently by sex, it REVERSES:

    f0_sd wide  =  CONFIDENT in women   ("f0 variance highest in the
                                          CONFIDENT level" — female talkers)
    f0_sd wide  =  UNCONFIDENT in men   ("...highest in the UNCONFIDENT
                                          level" — male talkers)

Within-speaker z-scoring does NOT absorb this. Normalizing removes a scale
offset; this is a DIRECTION FLIP, so it survives normalization and a single
sex-blind weight mis-scores one sex no matter how well calibrated it is.
That is why an explicit sex term exists at all. Three cues shift strength but
keep direction: loudness range separates the levels harder in WOMEN; mean
loudness and pausing separate harder in MEN (men signal confidence chiefly by
getting LOUDER, and show the most differentiated pause pattern). We have no
absolute mean-loudness feature, so per the spec the male branch leans on
dynamic_db + a front-loaded intensity_envelope as the loudness proxy.

Sex is RESOLVED, in this order, by resolve_speaker_sex():
  declared    — user_settings.profile_sex, the only trustworthy source.
  not_stated  — the user was asked and declined. A HARD OPT-OUT: we do NOT
                then guess from their voice. Sex-blind weights.
  inferred    — no answer on file → route from the speaker's own baseline
                mean f0, with a deliberately WIDE dead band (145-185 Hz is
                left unrouted). The founder spec directs this ("you already
                infer sex-adjacent info from the pitch baseline; use it to
                route weights"); the dead band is ours, because a WRONG route
                inverts cue 1 and is worse than no route at all.
  unknown     — sex-blind weights = the exact v1 behaviour. Every speaker who
                predates this change lands here, so nothing about them moves.

The resolved value and its source ride the stamped blob (`sex`, `sex_source`)
so the validation export can slice declared-only and re-fit per sex without
the inferred rows contaminating the fit.

PERCEPTUAL ASYMMETRY — NOT MODELLED, ON PURPOSE. The paper also finds
listeners rate men as more confident overall, while women are judged on a
wider, more polarized scale. That is a bias in the LISTENER, not a property
of the speaker's voice, and this composite ranks a speaker against THEMSELVES
(every cue is z-scored within-speaker). Baking a cross-sex offset in would
import the bias into the ranking and could only ever matter if we compared
two different speakers' raw scores — which nothing here does. Reconsider only
if the composite is ever used across speakers.

SIGN NOTE ON CUE 6 — read this before "fixing" it. The spec sheet says
"negative f0_mid_end_delta (falls at end) -> +confidence". Our field is
``mean(middle third) - mean(last third)`` (services/audio_metrics.py), so a
voice that FALLS at the end yields a POSITIVE delta. The construct is
"falling terminal contour = confident"; in THIS codebase's convention that is
``sign = +1``. Flipping it to -1 to match the spec sheet's wording would invert
the cue.

DELIBERATELY EXCLUDED (spec sheet, "DO NOT USE"):
  * HNR / jitter / shimmer — track confidence in the paper, but nothing in this
    pipeline computes them; bare autocorrelation at 16 kHz cannot.
  * MFCC / spectral / chroma — no confidence mapping, absolute-scale, and only
    computed for the LLM-budget pieces (partial coverage).
  * emphasis_per_min / pause_regularity — plausible, not validated in the
    paper. Exploratory only; not in the composite.

FENCES.
  * AC-9 — internal ONLY. The score, the band, and the cue z-scores never reach
    a user payload. Fence-tested in test_voice_confidence.py.
  * CONSTRUCT — this is "confidence", not the retired charisma/stress score
    vocabulary, and it is never surfaced as a number, ratio, or badge.
  * BLIND COACH — NOT learned and NOT on the coach packet. Fixed
    literature-tilted weights, so it cannot anchor a labeling coach to a
    model's opinion (same reasoning as services/acoustic_read.py).
  * LIVE LOOP — pure + best-effort. Every entry point returns None/no-op rather
    than raising; a missing baseline means SILENCE, never a fabricated 0.0.

VALIDATION GATE (founder spec, "before trusting the label"). This module sets
DIRECTIONS, not proven weights. It computes and persists by default so a sample
can be drawn, but it enters the RANKING only behind
``VOICE_CONFIDENCE_RANKING_ENABLED`` (default OFF). Flip it once the composite
has been anchored against blinded human confidence ratings — see
scripts/export_confidence_validation.py.

The sex priors DO NOT weaken that gate, they sharpen what it has to prove. The
paper's sex split rests on 3 female + 3 male talkers; these are priors to TEST,
not settled weights. The version stamp is bumped to v2 precisely because a
sample must not silently mix scores produced under two different weightings —
`version` + `sex_source` on the blob are what let the validation draw stay
honest, and what a later per-sex re-fit keys on.
"""
from __future__ import annotations

import logging
import math
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# v1 = the sex-blind weights shipped in PR #280. v2 = the same seven cues,
# routed by speaker sex (cue 1 REVERSES). Bumped so a validation sample can
# never silently mix scores produced under the two weightings.
_VERSION = "voice-confidence-v2"

# The routing key. Not a demographic field — it selects a weight vector.
SEX_FEMALE = "female"
SEX_MALE = "male"
SEX_NOT_STATED = "prefer_not_to_say"   # asked and declined → hard opt-out
_SEX_VALUES = (SEX_FEMALE, SEX_MALE, SEX_NOT_STATED)

# Raw metric keys the composite reads. The readout's `features` block renames
# three of them (build_readout_features) — normalize_features folds both
# spellings onto these, because best_presentation reads `metrics` while the
# readout path hands over `features`.
CONFIDENCE_FEATURES = (
    "f0_sd", "dynamic_db", "f0_mean", "wpm",
    "pause_ratio", "pause_ms", "f0_mid_end_delta", "intensity_envelope",
)

_FEATURE_ALIASES = {
    "speech_rate": "wpm",
    "loudness_range": "dynamic_db",
    "mean_pause": "pause_ms",
}

# ── The seven cues ────────────────────────────────────────────────────────
# (cue_name, [(feature, sign), ...], weight). A cue spanning two features
# averages the z of whichever are present, so PAUSING counts once whether the
# blob carries pause_ratio, pause_ms, or both — the spec's "pause_ms OR
# pause_ratio", not double weight for one construct.
#
# WEIGHTS ARE PROVISIONAL-LITERATURE-TILTED, NOT CALIBRATED. The spec says
# start equal and tilt toward the Tier-A cues if you must; we tilt mildly
# (f0_sd + dynamic_db + pausing = 0.56 of the mass) because those three are the
# ones our own extraction measures most reliably. There is intentionally NO
# machinery here to tune them on data — they are constants, full stop. Tune
# later on a SEPARATE set from whatever the composite is evaluated on.
_CUES: list[tuple[str, list[tuple[str, float]], float]] = [
    ("pitch_range",      [("f0_sd", +1.0)],                          0.18),
    ("loudness_range",   [("dynamic_db", +1.0)],                     0.20),
    ("pausing",          [("pause_ratio", -1.0), ("pause_ms", -1.0)], 0.18),
    ("mean_pitch",       [("f0_mean", -1.0)],                        0.13),
    ("speech_rate",      [("wpm", +1.0)],                            0.13),
    ("terminal_contour", [("f0_mid_end_delta", +1.0)],               0.09),
    ("energy_frontload", [("intensity_envelope", -1.0)],             0.09),
]
# (weights sum to 1.0)

# ── The same seven cues, routed by sex ────────────────────────────────────
# Only cue 1 changes SIGN. Everything else keeps its direction and shifts
# weight, per the paper's per-sex level separations. Both tables sum to 1.0;
# ordering matches _CUES so a diff reads as a re-weighting, not a rewrite.
#
# WOMEN — pitch range is the top cue and it is POSITIVE, and the loudness-range
# gap between confidence levels is widest in women; both up-weighted from the
# blind table. Pausing is comparatively less diagnostic here, so it gives way.
_CUES_FEMALE: list[tuple[str, list[tuple[str, float]], float]] = [
    ("pitch_range",      [("f0_sd", +1.0)],                          0.24),
    ("loudness_range",   [("dynamic_db", +1.0)],                     0.24),
    ("pausing",          [("pause_ratio", -1.0), ("pause_ms", -1.0)], 0.13),
    ("mean_pitch",       [("f0_mean", -1.0)],                        0.13),
    ("speech_rate",      [("wpm", +1.0)],                            0.13),
    ("terminal_contour", [("f0_mid_end_delta", +1.0)],               0.07),
    ("energy_frontload", [("intensity_envelope", -1.0)],             0.06),
]

# MEN — THE REVERSAL LIVES HERE. pitch_range carries a MINUS sign: a wide pitch
# range trends UNCONFIDENT in male talkers.
#
# It is also down-weighted, to 0.08. Two reasons. The spec ranks it fifth of six
# male terms (above the terminal contour, below rate and mean pitch), so it is a
# trend rather than a separator. And it is the ONLY cue whose sign depends on
# the sex resolution being right — keeping its weight modest bounds the damage
# when a route is wrong. The practical consequence, which is intended: a wide
# pitch range ALONE will not carry a male read out of the neutral dead zone; it
# takes company. For women the same cue is the top signal and does so easily.
#
# The loudness proxy (dynamic_db + a front-loaded intensity_envelope, 0.39
# together) and pausing carry the mass instead: men signal confidence chiefly by
# getting louder, and show the most differentiated pause pattern (longest when
# unconfident). We have no absolute mean-loudness feature to use directly.
_CUES_MALE: list[tuple[str, list[tuple[str, float]], float]] = [
    ("pitch_range",      [("f0_sd", -1.0)],                          0.08),
    ("loudness_range",   [("dynamic_db", +1.0)],                     0.20),
    ("pausing",          [("pause_ratio", -1.0), ("pause_ms", -1.0)], 0.22),
    ("mean_pitch",       [("f0_mean", -1.0)],                        0.13),
    ("speech_rate",      [("wpm", +1.0)],                            0.13),
    ("terminal_contour", [("f0_mid_end_delta", +1.0)],               0.05),
    ("energy_frontload", [("intensity_envelope", -1.0)],             0.19),
]

_CUES_BY_SEX = {SEX_FEMALE: _CUES_FEMALE, SEX_MALE: _CUES_MALE}

# Below this many measurable cues the read is noise, not signal → None.
_MIN_CUES = 3

# Weighted-z magnitude that stays in the NEUTRAL band. The paper shows a real
# "close-to-confident" middle; without this every clip gets pushed to a pole.
_DEAD_ZONE = 0.25

# tanh scale on the post-dead-zone magnitude: a weighted-mean z of ~1.5
# (solidly atypical for this speaker) lands ~0.85.
_SQUASH_SCALE = 1.0

# Baseline resolution floors — identical to services/delivery_stars.py and
# services/acoustic_read.py so all three speak about "the speaker's own norm"
# on the same terms.
_BASELINE_MAX_SESSIONS = 5
_BASELINE_MIN_SAMPLES = 8
_MIN_PIECES_WITHIN_TAKE = 6

# Acoustic-fallback route thresholds, in Hz, on the speaker's BASELINE mean f0
# (not a single piece). Adult modal speaking f0 runs ~85-155 Hz male and
# ~165-255 Hz female, and the two distributions genuinely overlap. The 145-185
# band between these is left DELIBERATELY UNROUTED — far wider than the nominal
# overlap — because the cost is asymmetric: an unrouted speaker keeps the
# sex-blind weights (today's behaviour, no harm), while a mis-routed one gets
# cue 1 inverted. Our f0 also comes from bare autocorrelation, so the estimate
# deserves the extra margin. Never used when the user declined to state.
_F0_MALE_CEILING_HZ = 145.0
_F0_FEMALE_FLOOR_HZ = 185.0


def ranking_enabled() -> bool:
    """Does the composite enter power_score? ``VOICE_CONFIDENCE_RANKING_ENABLED``,
    default OFF — the founder spec gates shipping on anchoring the composite
    against blinded human ratings. Computation/persistence is NOT gated by this
    (capture-first, so the validation sample can be drawn)."""
    return (os.getenv("VOICE_CONFIDENCE_RANKING_ENABLED") or "0") \
        .strip().lower() in ("1", "true", "yes")


def enabled() -> bool:
    """Kill-switch for computing + persisting the read at record time. Default
    ON (it is pure arithmetic over metrics we already have — no LLM, no extra
    audio pass). Set VOICE_CONFIDENCE_ENABLED=0 as a live-loop safety valve."""
    return (os.getenv("VOICE_CONFIDENCE_ENABLED") or "1") \
        .strip().lower() not in ("0", "false", "no")


def sex_inference_enabled() -> bool:
    """Kill-switch for the ACOUSTIC fallback only (declared sex is unaffected).
    Default ON — without it this lane is inert until every user has answered,
    and the founder spec directs routing off the pitch baseline. Set
    VOICE_CONFIDENCE_SEX_INFERENCE_ENABLED=0 to fall back to declared-only,
    which makes every unanswered speaker sex-blind (= v1)."""
    return (os.getenv("VOICE_CONFIDENCE_SEX_INFERENCE_ENABLED") or "1") \
        .strip().lower() not in ("0", "false", "no")


def cues_for(sex: Any) -> list:
    """The weight table for a resolved sex. Anything that is not exactly
    'female' or 'male' — None, 'prefer_not_to_say', junk — gets the sex-blind
    table, which is v1 unchanged. Unknown is never a guess."""
    return _CUES_BY_SEX.get(sex, _CUES)


def normalize_sex(value: Any) -> Optional[str]:
    """Fold a stored/submitted value onto one of _SEX_VALUES, else None.
    Case- and whitespace-tolerant; anything unrecognized is None (sex-blind),
    never a coerced guess."""
    if not isinstance(value, str):
        return None
    v = value.strip().lower().replace("-", "_").replace(" ", "_")
    return v if v in _SEX_VALUES else None


def infer_sex_from_baseline(baseline: Optional[dict]) -> Optional[str]:
    """Sex-adjacent ROUTE from the speaker's own baseline mean f0, or None.

    Returns None — meaning "stay sex-blind" — for anything ambiguous: no
    baseline, no f0_mean, a nonsensical value, or a mean inside the wide
    unrouted band. This is a WEIGHT ROUTER, not a claim about the person: the
    result is never surfaced, never stored on their profile, and never shown to
    a coach. It exists only because the alternative for a speaker who hasn't
    answered is a composite that mis-scores them on cue 1.

    Pure (apart from reading the kill-switch env var)."""
    if not sex_inference_enabled() or not isinstance(baseline, dict):
        return None
    entry = baseline.get("f0_mean")
    if not entry:
        return None
    try:
        mean_hz = float(entry[0])
    except (TypeError, ValueError, IndexError):
        return None
    if not math.isfinite(mean_hz) or mean_hz <= 0:
        return None
    if mean_hz < _F0_MALE_CEILING_HZ:
        return SEX_MALE
    if mean_hz > _F0_FEMALE_FLOOR_HZ:
        return SEX_FEMALE
    return None


def resolve_speaker_sex(
    user_id: Any, baseline: Optional[dict], *, database=None,
) -> tuple[Optional[str], str]:
    """Which weight table this speaker gets, and on what authority.

    Returns ``(sex, source)`` where sex is "female" | "male" | None and source
    is one of:
      "declared"   — they told us (user_settings.profile_sex). Always wins.
      "not_stated" — they were asked and declined. sex is None and WE DO NOT
                     INFER: an opt-out that we route around by reading their
                     voice instead is not an opt-out. Sex-blind weights.
      "inferred"   — nothing on file, routed off the baseline mean f0.
      "unknown"    — nothing on file and the acoustics were ambiguous (or the
                     lookup failed). Sex-blind weights = v1 behaviour.

    Best-effort; never raises. A DB failure degrades to the acoustic route
    rather than to nothing, because a failed read is not a decline."""
    try:
        declared = None
        if user_id:
            try:
                if database is None:
                    from services.db import db as database
                getter = getattr(database, "get_user_speaker_sex", None)
                if callable(getter):
                    declared = normalize_sex(getter(str(user_id)))
            except Exception as e:
                logger.warning(
                    "voice_confidence: declared-sex lookup failed user=%s: %s",
                    user_id, e,
                )
        if declared in (SEX_FEMALE, SEX_MALE):
            return declared, "declared"
        if declared == SEX_NOT_STATED:
            return None, "not_stated"
        inferred = infer_sex_from_baseline(baseline)
        if inferred:
            return inferred, "inferred"
        return None, "unknown"
    except Exception as e:
        logger.warning("voice_confidence: sex resolve failed: %s", e)
        return None, "unknown"


def normalize_features(d: Any) -> dict:
    """Fold either metrics spelling (raw or readout-features) onto the
    canonical CONFIDENCE_FEATURES keys, dropping non-numeric and bool."""
    out: dict = {}
    if not isinstance(d, dict):
        return out
    for k, v in d.items():
        key = _FEATURE_ALIASES.get(k, k)
        if key in CONFIDENCE_FEATURES \
                and isinstance(v, (int, float)) and not isinstance(v, bool):
            out[key] = float(v)
    return out


def feature_stats(metric_dicts: Any, *, min_samples: int) -> Optional[dict]:
    """{feature: (mean, sd)} over a pool of metric dicts (either spelling),
    keeping features with >= min_samples values and non-zero spread. None when
    nothing clears the bar. Pure."""
    cols: dict = {f: [] for f in CONFIDENCE_FEATURES}
    for m in (metric_dicts or []):
        for f, v in normalize_features(m).items():
            cols[f].append(v)
    out: dict = {}
    for f, vals in cols.items():
        if len(vals) < min_samples:
            continue
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        sd = math.sqrt(var)
        if sd > 0:
            out[f] = (mean, sd)
    return out or None


def resolve_confidence_baseline(
    user_id: Any, current_piece_metrics: Any, *, database=None,
) -> tuple[Optional[dict], str]:
    """The speaker's own reference: cross-take history first, else this take's
    own pieces once there are >= 6 usable ones, else None (silent).

    Returns ``(baseline, kind)`` where kind is "user" | "take" | "none" — the
    kind rides the stamped blob so a later reader can tell a cross-take read
    from a within-take one. Mirrors delivery_stars.resolve_delivery_baseline.
    Best-effort; never raises."""
    try:
        if user_id:
            if database is None:
                from services.db import db as database
            hist: list = []
            try:
                sessions = database.v2_list_user_lab_sessions(
                    str(user_id), limit=_BASELINE_MAX_SESSIONS) or []
                for s in sessions:
                    sid = str(s.get("id") or "")
                    if not sid:
                        continue
                    for snip in (database.get_snippets_by_session(sid) or []):
                        m = snip.get("metrics")
                        if isinstance(m, dict):
                            hist.append(m)
            except Exception:
                hist = []
            stats = feature_stats(hist, min_samples=_BASELINE_MIN_SAMPLES)
            if stats:
                return stats, "user"
        usable = [m for m in (current_piece_metrics or [])
                  if isinstance(m, dict) and normalize_features(m)]
        if len(usable) >= _MIN_PIECES_WITHIN_TAKE:
            stats = feature_stats(usable, min_samples=_MIN_PIECES_WITHIN_TAKE)
            if stats:
                return stats, "take"
        return None, "none"
    except Exception as e:
        logger.warning("voice_confidence: baseline resolve failed: %s", e)
        return None, "none"


def confidence_z(piece_metrics: Any, baseline: Optional[dict],
                 sex: Optional[str] = None) -> Optional[tuple]:
    """The raw weighted-z composite for ONE piece, BEFORE the dead zone.

    Returns ``(z_sum, cues_present)`` or None when fewer than _MIN_CUES cues
    are measurable. The sum is RENORMALIZED by the weight actually present, so
    a piece carrying 4 of 7 cues sits on the same scale as one carrying all 7
    — without that, a partial blob is systematically dragged toward neutral and
    would read as "close-to-confident" purely because features were missing.

    ``sex`` picks the weight table (see cues_for). Omitted/unknown reproduces
    v1 exactly, which is what every pre-existing caller and every speaker
    without a resolved sex gets. Pure."""
    if not baseline:
        return None
    feats = normalize_features(piece_metrics)
    if not feats:
        return None

    total = 0.0
    weight_present = 0.0
    cues_present = 0
    for _name, members, weight in cues_for(sex):
        zs = []
        for feature, sign in members:
            v = feats.get(feature)
            base = baseline.get(feature)
            if v is None or not base:
                continue
            mean, sd = base
            if not sd:
                continue
            zs.append(sign * (v - mean) / sd)
        if not zs:
            continue
        total += weight * (sum(zs) / len(zs))
        weight_present += weight
        cues_present += 1

    if cues_present < _MIN_CUES or weight_present <= 0:
        return None
    return total / weight_present, cues_present


def to_spectrum(z_sum: float) -> float:
    """Weighted z -> the [-1, 1] spectrum value, with the NEUTRAL DEAD ZONE.

    The dead zone is subtracted from the MAGNITUDE (not a hard clamp), so the
    curve leaves neutral continuously instead of jumping — a clip just outside
    the band reads as barely-leaning, which is what "close-to-confident" means.
    Everything inside the band is exactly 0.0."""
    magnitude = max(0.0, abs(float(z_sum)) - _DEAD_ZONE)
    if magnitude <= 0.0:
        return 0.0
    return round(math.copysign(math.tanh(_SQUASH_SCALE * magnitude), z_sum), 3)


def band(value: Any) -> Optional[str]:
    """The internal 5-point spectrum label — confident / close_to_confident /
    neutral / unconfident / doubtful.

    AC-9: for the validation harness and logs ONLY. This is a VERDICT; it must
    never reach a user payload (fence-tested)."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    v = float(value)
    if v == 0.0:
        return "neutral"
    if v >= 0.5:
        return "confident"
    if v > 0.0:
        return "close_to_confident"
    if v > -0.5:
        return "unconfident"
    return "doubtful"


def read_for_piece(piece_metrics: Any, baseline: Optional[dict],
                   baseline_kind: str = "user",
                   sex: Optional[str] = None,
                   sex_source: str = "unknown") -> Optional[dict]:
    """The stamped blob for ONE piece, or None when unmeasurable::

        {"score": float in [-1, 1],   # + confident, - doubtful, 0 neutral band
         "band": str,                 # internal label (never surfaced)
         "baseline": "user" | "take",
         "cues": int,                 # how many of the 7 were measurable
         "sex": "female"|"male"|"unknown",   # which weight table was used
         "sex_source": "declared"|"inferred"|"not_stated"|"unknown",
         "version": "voice-confidence-v2"}

    ``sex``/``sex_source`` are stamped so a later reader can tell WHY a score
    came out as it did, and so the validation export can restrict a re-fit to
    declared rows. They are internal, like the rest of the blob (AC-9).

    Pure. None is an HONEST ABSENCE (no baseline, too few cues) — never a
    fake-neutral 0.0, which would be indistinguishable from a real middling
    read and would quietly enter the ranking as one."""
    result = confidence_z(piece_metrics, baseline, sex)
    if result is None:
        return None
    z_sum, cues = result
    score = to_spectrum(z_sum)
    return {
        "score": score,
        "band": band(score),
        "baseline": baseline_kind if baseline_kind in ("user", "take") else "take",
        "cues": cues,
        "sex": sex if sex in (SEX_FEMALE, SEX_MALE) else "unknown",
        "sex_source": sex_source if sex_source in (
            "declared", "inferred", "not_stated") else "unknown",
        "version": _VERSION,
    }


def attach_voice_confidence(pieces: list, *, baseline: Optional[dict] = None,
                            baseline_kind: str = "user",
                            sex: Optional[str] = None,
                            sex_source: str = "unknown") -> None:
    """Stamp ``metrics["voice_confidence"]`` on every piece dict, in place.

    ``pieces`` = the record-time piece dicts (each with a "metrics" dict). A
    piece with no metrics, or too few measurable cues, gets NOTHING stamped —
    downstream then passes None to power_score, which is a no-op. ``sex`` is
    resolved ONCE per take by the caller (resolve_speaker_sex) and applied to
    every piece; it is a property of the speaker, not of the moment. Never
    raises."""
    try:
        if not baseline:
            return
        for p in (pieces or []):
            if not isinstance(p, dict):
                continue
            m = p.get("metrics")
            if not isinstance(m, dict) or not m:
                continue
            read = read_for_piece(m, baseline, baseline_kind, sex, sex_source)
            if read is not None:
                m["voice_confidence"] = read
    except Exception as e:
        logger.warning("voice_confidence: attach failed (non-fatal): %s", e)


def rank_term(metrics: Any) -> Optional[float]:
    """The value to hand power_score's ``voice_confidence`` kwarg — the stamped
    score, or None.

    None whenever the ranking flag is OFF, the piece was never stamped (older
    takes), or the blob is malformed. None is power_score's documented no-op,
    so the ranking is byte-for-byte unchanged until the flag is flipped."""
    if not ranking_enabled():
        return None
    if not isinstance(metrics, dict):
        return None
    read = metrics.get("voice_confidence")
    if not isinstance(read, dict):
        return None
    v = read.get("score")
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    return None
