"""WHAT THE VOICE DID in one moment — named, ordered, and safe to say.

Founder 2026-08-15: *"for the underlining use the verbal and vocal cues of
what the user said to determine that it was confident or highly engaging,
not just random"*, and *"in the justification of the positive feedback …
explain using the vocal and verbal cues."*

────────────────────────────────────────────────────────────────────────────
WHY THIS MODULE EXISTS. services/voice_confidence.py already reads seven
acoustic cues per moment and folds them into ONE number. That number decides
which moments are confident, and it is exactly the wrong shape for the two
things asked for here:

  * an ACCENT needs to know WHERE INSIDE the moment the delivery landed, and
    a scalar cannot say;
  * a PRAISE line needs to know WHICH CUES carried it, and a scalar has
    thrown that away by the time anyone reads it.

So this module re-reads the same cues through the same weight tables — the
same tables, imported, never a second copy that could drift — and hands back
the two things the composite discards: the ORDER of the cues, and the part of
the moment they point at.

────────────────────────────────────────────────────────────────────────────
IT NEVER SURFACES A NUMBER (AC-9). Everything leaving here is a KEY from a
closed vocabulary, and the FE holds the copy for it — the same contract as
`why_key`. No z-score, no ratio, no "cues: 5 of 7". A key says which true
thing may be said; it does not say it.

IT IS NOT A NEW CONSTRUCT (CONSTRUCT fence). These are the OBSERVED CUES
behind the `confidence` read (conf-q-v1, SPEC §17) — descriptions of what the
voice measurably did, not a second measured state sitting beside it. Nothing
here is rated, aggregated or entered into quorum. "Engaging" in particular is
NOT introduced as a state: there is no written operational definition for it,
and inventing one is precisely how the retired charisma construct got in.

WITHIN-SPEAKER, ALWAYS. Every cue is z-scored against the speaker's own
baseline upstream, so "wider range" means wider *than they usually are*, never
wider than some other speaker. A cue with no baseline is not measurable and
simply does not appear.

────────────────────────────────────────────────────────────────────────────
PROVISIONAL, AND SAYING SO. The cue→key mapping and the region rule below are
ours, tilted from the same Jiang & Pell (2017) reading as the weights, and
they carry the same status the weights carry in voice_confidence.py: constants
chosen deliberately, not fitted. There is no machinery here to tune them.

Pure and deterministic throughout. Every unmeasurable case returns an HONEST
ABSENCE — an empty list, or None — never a filled-in guess.
"""
from __future__ import annotations

from typing import Any, Optional

from services.voice_confidence import (
    confidence_cues,
    normalize_features,
)

# ── THE CUE VOCABULARY ────────────────────────────────────────────────────
#
# Keyed by (cue, direction the speaker actually went). The direction matters
# because a cue may describe positive or negative movement relative to the
# same speaker's baseline. The sign is taken from the one universal contract,
# so qualitative evidence and the composite cannot disagree.
#
# Only the CONFIDENT direction has keys. This vocabulary exists to say what
# went right; the to-work-on lane is services/delivery_stars.py and it has its
# own device names.
_CUE_KEYS: dict[tuple[str, float], str] = {
    ("pitch_range", +1.0): "wide_range",       # their pitch moved, not flat
    ("loudness_range", +1.0): "full_volume",   # they let the volume move
    ("pausing", -1.0): "no_hesitation",        # fewer/shorter pauses than usual
    ("mean_pitch", -1.0): "settled_pitch",     # sat lower than their norm
    ("speech_rate", +1.0): "kept_moving",      # didn't slow into uncertainty
    ("terminal_contour", +1.0): "landed_ending",   # brought the end DOWN
    ("energy_frontload", -1.0): "opened_strong",   # led with the energy
}

#: Every key this module can ever emit. The FE's copy map is checked against
#: it, so a new cue cannot reach a student without copy for it.
CUE_KEYS: tuple = tuple(sorted(set(_CUE_KEYS.values())))

# A cue has to be at least this far from the speaker's own norm before it is
# worth NAMING. The composite happily sums small contributions — that is what
# a composite is for — but "your pitch moved a little more than usual" is not
# a thing to tell somebody, and a praise line built from noise reads as
# flattery. Deliberately stricter than the composite's own dead zone.
_MIN_CUE_Z = 0.5

# How many cues a single line may name. Three observations is a read; seven is
# a printout, and a printout is how AC-9 gets breached in spirit while
# obeying the letter.
_MAX_CUES = 3

#: Where inside a moment the delivery landed.
OPENING = "opening"
CLOSING = "closing"


def _contributions(piece_metrics: Any, baseline: Any) -> list:
    """[(cue_name, signed_z, feature_sign), …] for the measurable cues, in the
    weight table's own order.

    `signed_z` is POSITIVE when the cue pushed toward confident, which is the
    only direction this module speaks about. Computed the same way
    voice_confidence.confidence_z computes it — same table, same aliases, same
    within-speaker z — but kept UNSUMMED, which is the whole point. Pure."""
    if not baseline:
        return []
    feats = normalize_features(piece_metrics)
    if not feats:
        return []
    out: list = []
    for name, members, _weight in confidence_cues():
        zs, sign_used = [], None
        for feature, sign in members:
            v = feats.get(feature)
            base = baseline.get(feature)
            if v is None or not base:
                continue
            mean, sd = base
            if not sd:
                continue
            zs.append(sign * (v - mean) / sd)
            sign_used = sign
        if zs and sign_used is not None:
            out.append((name, sum(zs) / len(zs), sign_used))
    return out


def cue_keys_for_piece(piece_metrics: Any, baseline: Any) -> list:
    """The cues that carried THIS moment, strongest first — at most three,
    as keys.

    Only cues pointing toward confident and clearing `_MIN_CUE_Z` appear: this
    is the evidence behind a praise line, and a praise line that cites a cue
    the speaker did not actually produce is worse than one that cites nothing.
    Empty is a legitimate and common answer (no baseline yet, a middling
    delivery, a cue set that is simply unremarkable). Pure."""
    scored = [
        (z, _CUE_KEYS[(name, sign)])
        for (name, z, sign) in _contributions(piece_metrics, baseline)
        if z >= _MIN_CUE_Z and (name, sign) in _CUE_KEYS
    ]
    scored.sort(key=lambda t: -t[0])
    return [key for _z, key in scored[:_MAX_CUES]]


def accent_region(piece_metrics: Any, baseline: Any) -> Optional[str]:
    """WHERE in the moment the delivery landed — "opening", "closing", or None.

    THE ONE WITHIN-MOMENT SIGNAL WE ACTUALLY HAVE. Six of the seven cues are
    whole-moment scalars and say nothing about position. Two do:

      * energy_frontload reads `intensity_envelope`, the SLOPE of the
        loudness contour. Confident delivery front-loads it — the energy is
        spent at the start and fades — so a positive contribution here means
        the OPENING carried the moment.
      * terminal_contour reads `f0_mid_end_delta`, mid-third pitch minus
        last-third. Confident delivery brings the ending DOWN rather than
        letting it drift up, so a positive contribution means the speaker
        landed the CLOSING deliberately.

    They can point in opposite directions on the same moment — a strong open
    AND a landed close is a real shape, not a contradiction — so the stronger
    contribution wins and a near-tie yields None. None means "no position
    evidence": the caller must then treat the whole moment as the search
    space rather than pick a half at random, which is the entire complaint
    this answers.

    Provisional, as the header says: this is a reading of the two positional
    cues, not a measurement of where the peak is. Real within-moment
    localisation needs windowed analysis of the clip, which we do not compute.
    Pure."""
    by_name = {name: (z, sign)
               for (name, z, sign) in _contributions(piece_metrics, baseline)}
    front = by_name.get("energy_frontload")
    term = by_name.get("terminal_contour")
    z_front = front[0] if front and front[0] >= _MIN_CUE_Z else 0.0
    z_term = term[0] if term and term[0] >= _MIN_CUE_Z else 0.0
    if z_front <= 0.0 and z_term <= 0.0:
        return None
    # A near-tie is two true things, not a winner. Say nothing rather than
    # break the tie on a rounding difference.
    if abs(z_front - z_term) < 0.25:
        return None
    return OPENING if z_front > z_term else CLOSING


def is_impeccable(piece_metrics: Any, baseline: Any, *,
                  confidence_score: Any = None) -> bool:
    """Was this moment delivered so well that the honest note is PRAISE?

    Founder 2026-08-15: *"if the delivery was impeccable, just give them the
    feedback in the praise lane."*

    Two conditions, and both have to hold, because each alone is a way to be
    wrong:

      * the composite has to be genuinely confident, not merely out of the
        neutral band — a moment that squeaked past the dead zone is not
        "impeccable" and saying so devalues every time we say it;
      * at least TWO named cues have to be behind it. One cue clearing the bar
        is a single measurement; the praise line quotes its evidence, and
        evidence of one is a coincidence.

    `confidence_score` is the stamped voice-confidence value when the caller
    has it (they usually do — it rides in the metrics blob). Absent, the
    cue count alone decides, which is stricter, not looser. Pure."""
    keys = cue_keys_for_piece(piece_metrics, baseline)
    if len(keys) < 2:
        return False
    if confidence_score is None:
        return True
    try:
        return float(confidence_score) >= _IMPECCABLE_SCORE
    except (TypeError, ValueError):
        return False


# The composite value at which a delivery stops being "confident enough to
# rank higher" and becomes "worth telling them about". Well clear of the
# neutral dead zone (0.25): praise that fires on a borderline read is the
# fastest way to make every later praise line worthless.
_IMPECCABLE_SCORE = 0.6
