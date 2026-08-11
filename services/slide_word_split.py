"""Per-slide transcript sync via the slide-click timeline (founder #6).

The Lab take viewer shows the FULL verbatim transcript per slide. Until now a
snippet was assigned WHOLE to the slide that was on screen when it STARTED, so
words spoken AFTER a mid-snippet slide click stayed under the OLD slide. With
word-level Whisper timestamps we can do it precisely: every WORD is bucketed to
the slide that was on screen when that word was spoken, so a snippet spanning a
click is split — the post-click words move to the new slide.

Pure + dependency-light (only slide_alignment). When there is no usable click
timeline (no slide_advances) or no words, ``split_words_by_slides`` returns [] so
the caller falls back to the legacy whole-snippet assignment.

Whisper word timestamps are SECONDS, absolute to the whole recording — the same
reference frame as a snippet's start_offset_ms — so a word's slide is just
``slide_index_for_offset(word.start * 1000, slide_advances)``.
"""
from __future__ import annotations

import math
import os
import re
from typing import Any


# ── Pause-snap — RETIRED FROM THE PIPELINE (founder 2026-08-11) ───────────
# The recorder warm-up makes Whisper word-times run slightly EARLIER than the
# UI tap-times, so the first word(s) after a slide tap can land on the PREVIOUS
# slide. Pause-snap GUESSED that offset: when the speaker pauses as they tap
# (the common case) the offset sits inside the silence, so snapping each
# boundary into the nearest pause recovers the true boundary without knowing
# the number.
#
# The FE now MEASURES the number instead (`slide_clock_offset_ms`, applied by
# apply_clock_offset below), and an exact correction does not want a heuristic
# arguing with it. SLIDE_PAUSE_SNAP_ENABLED is deleted rather than left at 0:
# a dark flag that would FIGHT the correct answer if anyone flipped it is a
# trap, not an option, and it never ran in production a single time.
#
# `_snap_boundaries_to_pauses` SURVIVES as a pure analysis helper — it is the
# instrument services/slide_boundary_metrics.py uses to ask "was a pause even
# available near this tap", which is how we learn whether the measured offset
# is doing its job. Analysis, never assignment.


# ── Measured audio-vs-UI clock offset (F1, 2026-07-26) ───────────────────
# Pause-snap GUESSES the recorder warm-up offset by looking for a silence near
# each tap. The FE can MEASURE it instead: the delta between the UI clock that
# timestamps slide taps and the moment MediaRecorder actually produced its first
# audio. Given that number, the correction is exact and needs no heuristic.
#
# Bounds: a warm-up is tens to low hundreds of ms; 30s is an absurd upper bound
# that still catches a unit mix-up (seconds sent as ms). A small NEGATIVE value
# is allowed because the UI clock can start marginally after the audio.
_MAX_CLOCK_OFFSET_MS = 30000
_MIN_CLOCK_OFFSET_MS = -5000


def apply_clock_offset(slide_advances: Any, offset_ms: Any) -> Any:
    """Shift every tap time onto the AUDIO clock by subtracting the measured
    offset. Pure; returns ``slide_advances`` UNCHANGED (same object) when the
    offset is missing, malformed or out of bounds — an unusable measurement
    must degrade to today's behaviour, never to a corrupted timeline.

    The first entry is clamped at 0 rather than going negative: a tap cannot
    precede the recording. Order and the ``{index, t_ms}`` shape are preserved,
    so every downstream consumer is unaffected apart from the times.
    """
    if not isinstance(slide_advances, list) or not slide_advances:
        return slide_advances
    if isinstance(offset_ms, bool) or not isinstance(offset_ms, (int, float)):
        return slide_advances
    # NaN/inf are floats and would survive the type check, then blow up in
    # int() — and a JS client can genuinely produce NaN from a bad subtraction.
    if isinstance(offset_ms, float) and not math.isfinite(offset_ms):
        return slide_advances
    off = int(offset_ms)
    if off == 0 or not (_MIN_CLOCK_OFFSET_MS <= off <= _MAX_CLOCK_OFFSET_MS):
        return slide_advances
    out = []
    for a in slide_advances:
        if not isinstance(a, dict) or not isinstance(a.get("t_ms"), (int, float)) \
                or isinstance(a.get("t_ms"), bool):
            out.append(a)
            continue
        out.append({**a, "t_ms": max(0, int(a["t_ms"]) - off)})
    return out


def context_with_clock_offset(session_context: Any) -> Any:
    """Return ``session_context`` with its slide_advances moved onto the audio
    clock, using its own ``slide_clock_offset_ms``. Applied ONCE at the top of
    the pipeline so every downstream reader inherits the correction without
    threading a parameter through half a dozen signatures.

    Pause-snap still runs afterwards, deliberately: the offset removes the
    SYSTEMATIC start bias, snap cleans up whatever per-boundary residue is
    left. They are complementary, not alternatives. (Whether snap earns its
    keep once offsets are flowing is a question for the boundary metrics, not
    an assumption to bake in here.)

    Returns the input unchanged when there is nothing to correct.
    """
    if not isinstance(session_context, dict):
        return session_context
    off = session_context.get("slide_clock_offset_ms")
    adv = session_context.get("slide_advances")
    if not adv or off in (None, 0):
        return session_context
    shifted = apply_clock_offset(adv, off)
    if shifted is adv:
        return session_context
    return {**session_context, "slide_advances": shifted}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _snap_boundaries_to_pauses(slide_advances: Any, words: Any, *,
                               window_ms: int, min_gap_ms: int) -> list:
    """Move each slide-change boundary to the NEAREST real speech pause within
    ``window_ms``, so a small audio-vs-UI clock offset lands in the silence the
    speaker leaves when they tap NEXT/BACK. Pure. Returns slide_advances
    unchanged (same ``{index, t_ms}`` shape) when there's no qualifying pause
    near a tap (speaker talked straight through) or when inputs are empty. Never
    reorders or collapses adjacent boundaries (clamps each snap strictly between
    the previous SNAPPED boundary and the next RAW boundary); the index of every
    entry is preserved; the first entry at t_ms<=0 (recording start) is never
    moved."""
    if not slide_advances or not words:
        return slide_advances

    # 1) Real pauses → snap-points (gap midpoints, ms). Only gaps bigger than
    #    normal speech rhythm count (a deliberate pause, not a breath).
    ws = sorted(
        (w for w in words if isinstance(w, dict)
         and isinstance(w.get("start"), (int, float))),
        key=lambda w: w.get("start") or 0.0,
    )
    gaps: list = []
    for i in range(len(ws) - 1):
        pe = ws[i].get("end")
        pe = float(pe) if isinstance(pe, (int, float)) else float(ws[i].get("start") or 0.0)
        ns = float(ws[i + 1].get("start") or 0.0)
        if (ns - pe) * 1000.0 >= min_gap_ms:
            gaps.append((pe + ns) / 2.0 * 1000.0)
    if not gaps:
        return slide_advances

    # 2) Boundaries in time order (t_ms is monotonic even with BACK nav).
    idxs = [i for i, a in enumerate(slide_advances)
            if isinstance(a, dict) and isinstance(a.get("t_ms"), (int, float))]
    idxs.sort(key=lambda i: slide_advances[i]["t_ms"])

    snapped: dict = {i: slide_advances[i]["t_ms"] for i in idxs}
    prev_snapped = None
    for pos, i in enumerate(idxs):
        t = slide_advances[i]["t_ms"]
        if t <= 0:                       # recording start — never snap
            prev_snapped = snapped[i]
            continue
        lo = prev_snapped if prev_snapped is not None else float("-inf")
        nxt = idxs[pos + 1] if pos + 1 < len(idxs) else None
        hi = slide_advances[nxt]["t_ms"] if nxt is not None else float("inf")
        best = None
        best_d = None
        for g in gaps:
            if g <= lo or g >= hi or abs(g - t) > window_ms:
                continue
            d = abs(g - t)
            if best_d is None or d < best_d:
                best, best_d = g, d
        snapped[i] = int(round(best)) if best is not None else t
        prev_snapped = snapped[i]

    # 3) Rebuild preserving original order + index; only t_ms changes.
    return [
        ({**a, "t_ms": snapped[i]} if (i in snapped and isinstance(a, dict)) else a)
        for i, a in enumerate(slide_advances)
    ]


def slice_words_for_window(words: Any, start_ms: int, end_ms: int) -> list:
    """The word-level analogue of slice_transcript_for_window: the words whose
    time span overlaps [start_ms, end_ms]. ``words`` = [{word, start, end}] in
    SECONDS (Whisper verbose_json). Pure; None-safe. Used to park each selected
    snippet's words at process time so the take viewer can split later."""
    if not words:
        return []
    s = start_ms / 1000.0
    e = end_ms / 1000.0
    out: list = []
    for w in words:
        if not isinstance(w, dict):
            continue
        ws = w.get("start")
        if not isinstance(ws, (int, float)):
            continue
        we = w.get("end")
        we = we if isinstance(we, (int, float)) else ws
        # Overlap test (same as the segment slicer): end after window start AND
        # start before window end.
        if we > s and ws < e:
            out.append({"word": w.get("word") or "", "start": ws, "end": we})
    return out


def split_words_by_slides(words: Any, slide_advances: Any, slides: Any) -> list:
    """Group a snippet's words into per-slide fragments by the click timeline.

    Returns an ordered list of
    ``{slide_index, transcript, start_offset_ms, duration_ms}`` — one entry per
    run of consecutive words that share a slide. A snippet whose words straddle a
    slide click yields TWO+ fragments (the split #6 is about).

    Returns ``[]`` when there is no usable timeline (no slide_advances) or no
    words/slides — the signal for the caller to fall back to the legacy
    whole-snippet assignment (which can't split, so it keeps everything on the
    start slide). A word before the first advance is clamped to the first slide;
    indices are clamped into range.
    """
    n = len(slides) if isinstance(slides, list) else 0
    if not words or n == 0 or not slide_advances:
        return []

    from services.slide_alignment import slide_index_for_offset

    ordered = sorted(
        (w for w in words if isinstance(w, dict)
         and isinstance(w.get("start"), (int, float))),
        key=lambda w: w.get("start") or 0.0,
    )

    groups: list = []
    cur: dict | None = None
    for w in ordered:
        token = (w.get("word") or "").strip()
        if not token:
            continue
        st = float(w.get("start") or 0.0)
        en = w.get("end")
        en = float(en) if isinstance(en, (int, float)) else st
        start_ms = int(st * 1000)
        end_ms = int(en * 1000)
        si = slide_index_for_offset(start_ms, slide_advances)
        si = 0 if not isinstance(si, int) else max(0, min(si, n - 1))
        if cur is None or cur["slide_index"] != si:
            if cur is not None:
                groups.append(cur)
            cur = {
                "slide_index": si, "tokens": [token],
                "start_offset_ms": start_ms, "end_ms": end_ms,
            }
        else:
            cur["tokens"].append(token)
            cur["end_ms"] = max(cur["end_ms"], end_ms)
    if cur is not None:
        groups.append(cur)

    return [
        {
            "slide_index": g["slide_index"],
            "transcript": " ".join(g["tokens"]).strip(),
            "start_offset_ms": g["start_offset_ms"],
            "duration_ms": max(0, g["end_ms"] - g["start_offset_ms"]),
        }
        for g in groups
    ]


def _bucket_words_by_slide(words_all: Any, slide_advances: Any,
                           slides: Any) -> dict:
    """Bucket the WHOLE-recording word list to the slide on screen at each
    word's timestamp — the ONE shared bucketing for both the per-slide
    transcript view AND the ≤200-char piece cutter, so the two views can never
    disagree about which slide a word belongs to.

    Returns {slide_index: [original word dicts, time-sorted]} for every slide
    0..n-1 (empty list when the slide had no speech), or {} when there are no
    slides. Words keep their original {word, start, end}-in-seconds shape so
    downstream chunkers can derive exact audio spans. A word before the first
    advance clamps to slide 0; no advances at all → every word clamps to
    slide 0 truthfully (the deck never advanced past it). Pause-snap
    (flag-gated, default OFF) is applied here so every consumer inherits the
    boundary robustness. Pure.
    """
    n = len(slides) if isinstance(slides, list) else 0
    if n == 0:
        return {}

    buckets: dict = {i: [] for i in range(n)}
    if words_all and slide_advances:
        from services.slide_alignment import slide_index_for_offset
        for w in words_all:
            if not isinstance(w, dict):
                continue
            st = w.get("start")
            if not isinstance(st, (int, float)):
                continue
            token = (w.get("word") or "").strip()
            if not token:
                continue
            start_ms = int(float(st) * 1000)
            si = slide_index_for_offset(start_ms, slide_advances)
            si = 0 if not isinstance(si, int) else max(0, min(si, n - 1))
            buckets[si].append(w)
    for i in range(n):
        buckets[i].sort(key=lambda w: w.get("start") or 0.0)
    return buckets


def build_slide_transcripts(words_all: Any, slide_advances: Any,
                            slides: Any) -> list:
    """The COMPLETE per-slide transcript for the take viewer (founder Part A —
    "text under the slide = exactly 1:1 of what was said while that slide was on
    screen"). Unlike the per-snippet split, this buckets the WHOLE-recording word
    list so a slide whose speech wasn't in a salient snippet (typically the quiet
    first slide) still gets its words — fixing "the app doesn't catch the first
    slide / everything is shifted".

    Returns one entry PER DECK SLIDE (index 0..n-1, in order) —
    ``{index, transcript, start_offset_ms, duration_ms}`` — even when a slide had
    no speech (empty transcript is the truthful 1:1). Every word is bucketed to
    the slide on screen at its timestamp; a word before the first advance clamps
    to slide 0; a revisited slide collects all its words in time order. The span
    is [min word start, max word end] for that slide. Returns [] when there are
    no slides. Pure. (Bucketing shared with chunk_slide_words_by_chars via
    _bucket_words_by_slide — the two views cannot drift.)
    """
    n = len(slides) if isinstance(slides, list) else 0
    if n == 0:
        return []
    buckets = _bucket_words_by_slide(words_all, slide_advances, slides)
    # No advances at all → the legacy behavior was empty buckets (all-empty
    # transcripts). _bucket_words_by_slide clamps everything to slide 0 only
    # when advances EXIST; without advances it also produces empty buckets
    # (the words loop is gated on slide_advances) — preserved.

    out: list = []
    for i in range(n):
        ws = buckets.get(i) or []
        tokens = [(int(float(w.get("start") or 0.0) * 1000),
                   int(float(w.get("end") if isinstance(w.get("end"), (int, float))
                             else (w.get("start") or 0.0)) * 1000),
                   (w.get("word") or "").strip()) for w in ws]
        transcript = " ".join(t[2] for t in tokens).strip()
        if tokens:
            start_ms = tokens[0][0]
            end_ms = max(t[1] for t in tokens)
            duration_ms = max(0, end_ms - start_ms)
        else:
            start_ms = None
            duration_ms = None
        out.append({
            "index": i,
            "transcript": transcript,
            "start_offset_ms": start_ms,
            "duration_ms": duration_ms,
        })
    return out


# ── Deckless chunking (founder 2026-07-11, supersedes the 50-word cut) ──────
# No deck → no click timeline to bucket by, so the whole-recording transcript
# is split into ~200-CHARACTER pieces broken at word boundaries, each with
# its audio span derived from the Whisper word timestamps — so every chunk's
# playback control plays exactly its own segment of the single take audio,
# and text/audio boundaries can never drift (both come from the same words).
#
# SENTENCE-AWARE since 2026-07-15 (founder BE-1): a piece never ends
# mid-sentence when a sentence end exists — 200 is the TARGET; a sentence may
# extend a piece up to the 300-char hard cap (founder-locked) before the
# run-on escape hatch cuts at a word boundary.

_DECKLESS_CHUNK_CHARS = 200

# The sentence-extension window: a piece may run past the target up to
# target+100 (=300 for default pieces) to reach a sentence end. Founder-locked
# 2026-07-15 ("300").
_SENTENCE_EXTENSION_CHARS = 100

# A token that ENDS a sentence: terminal . ! ? … optionally followed by
# closing quotes/brackets ("word." / "word!”" / "word?')").
_SENTENCE_END_RE = re.compile(r'[.!?…]["\'’”)\]]*$')

# Trailing punctuation worth carrying from a skipped (ghost) segment token
# onto the previous aligned word.
_TRAILING_PUNCT_RE = re.compile(r'[.,!?;:…"\'’”)\]]+$')

# Normalization key for alignment: letters/digits only, lowercased —
# "Store," ≡ store; "don't" ≡ dont.
_NORM_RE = re.compile(r"[\W_]+", re.UNICODE)

# Bounded skip window for the two-pointer alignment (the "ghost word"
# problem): a mismatch may skip at most this many tokens on the segment
# side before we declare the word unalignable — never the whole segment.
_ALIGN_SKIP_WINDOW = 3


def _norm_token(token: Any) -> str:
    return _NORM_RE.sub("", str(token or "")).lower()


def _ends_sentence(token: str) -> bool:
    return bool(_SENTENCE_END_RE.search(token))


def _align_segment(seg_words: list, seg_tokens: list, out: list) -> None:
    """Align ONE segment's words against its punctuated tokens (appends the
    decorated word dicts to ``out``). Two-pointer + bounded look-ahead +
    MUTUAL SKIP: when no match lands within _ALIGN_SKIP_WINDOW, the text
    pointer consumes one token (donating its trailing punctuation to the
    previous aligned word) and retries — the pointer can NEVER freeze, so a
    long ghost run (filler chains, spelled-out numbers) costs at most its
    own tokens, never the rest of the take (review fix 2026-07-15)."""
    j = 0
    n = len(seg_tokens)

    def _donate_tail(upto):
        nonlocal j
        while j < upto:
            m = _TRAILING_PUNCT_RE.search(seg_tokens[j])
            if m:
                for k in range(len(out) - 1, -1, -1):
                    if isinstance(out[k], dict) and out[k].get("word"):
                        out[k] = dict(out[k])
                        out[k]["word"] = out[k]["word"] + m.group(0)
                        break
            j += 1

    for w in seg_words:
        if not isinstance(w, dict) or not (w.get("word") or "").strip():
            out.append(w)
            continue
        wkey = _norm_token(w.get("word"))
        matched = None
        if wkey:
            probe = j
            while probe < n:
                # bounded look-ahead from the current probe position
                hit = None
                for dj in range(0, _ALIGN_SKIP_WINDOW + 1):
                    if probe + dj < n and \
                            _norm_token(seg_tokens[probe + dj]) == wkey:
                        hit = probe + dj
                        break
                if hit is not None:
                    matched = hit
                    break
                # MUTUAL SKIP — consume one text token and retry (never
                # freeze); its punctuation lands on the previous word.
                probe += 1
        if matched is None:
            out.append(dict(w))   # array-side ghost — raw, text untouched
            continue
        _donate_tail(matched)     # text-side ghosts donate punctuation
        nw = dict(w)
        nw["word"] = seg_tokens[matched]  # punctuated + properly cased
        out.append(nw)
        j = matched + 1


def restore_punctuation(words: Any, segments: Any) -> list:
    """Re-attach punctuation (and casing) to the timestamped word stream from
    the Whisper SEGMENT text (founder BE-1a, 2026-07-15). Deterministic — no
    LLM anywhere.

    Whisper's word-level timestamps arrive punctuation-less; the segments
    carry the punctuated text. Alignment is ANCHORED PER SEGMENT by the
    timestamps both sides already carry (a word belongs to the segment whose
    time range it starts in), then aligned within the segment via a
    two-pointer walk with bounded look-ahead + mutual skip (the "ghost word"
    problem: the streams are NOT a reliable 1:1 — fillers dropped from one
    side, contractions merged, numbers spelled out). Any residual mismatch is
    therefore contained to ONE segment — it can never derail the rest of the
    take (review fix 2026-07-15):

      * aligned word → takes the SEGMENT token verbatim (punctuation + case);
      * skipped segment tokens (text-side ghosts) → their trailing
        punctuation carries onto the PREVIOUS aligned word;
      * unalignable word (array-side ghost) → passes through unchanged;
      * no segments at all → the input passes through unchanged.

    Returns NEW word dicts; ``start``/``end`` spans are STRICTLY untouched
    (this decorates the ``word`` strings only). Pure.
    """
    src = list(words or [])
    segs = [s for s in (segments or []) if isinstance(s, dict)
            and (s.get("text") or "").strip()]
    if not src or not segs:
        return src

    out: list = []
    wi = 0
    n_words = len(src)
    for si, seg in enumerate(segs):
        seg_end = seg.get("end")
        seg_end = float(seg_end) if isinstance(seg_end, (int, float)) else None
        # This segment's words: consume while the word STARTS before the
        # segment ends (the last segment takes everything left).
        seg_words: list = []
        while wi < n_words:
            w = src[wi]
            if si < len(segs) - 1 and seg_end is not None \
                    and isinstance(w, dict) \
                    and isinstance(w.get("start"), (int, float)) \
                    and float(w["start"]) >= seg_end:
                break
            seg_words.append(w)
            wi += 1
        if not seg_words:
            continue
        _align_segment(seg_words, (seg.get("text") or "").split(), out)
    # words past the last segment (shouldn't happen, but never drop text)
    out.extend(dict(w) if isinstance(w, dict) else w for w in src[wi:])
    return out


# ── Run-on sentence boundaries (founder BE-1c, 2026-07-16) ─────────────────
# Whisper under-punctuates long spoken run-ons — several clauses arrive
# comma-spliced or with no punctuation at all, and the reader gets a wall of
# text. The missing boundary is in the DELIVERY: a sentence end is a pause
# you can hear, and the word timestamps already carry it. Where a real pause
# follows an already-long sentence, the boundary is promoted to a full stop.
# Punctuation + casing ONLY — words are never added, removed, or reordered
# (the L1 verbatim fence) and spans are strictly untouched.

# A trailing comma/semicolon/colon (kept inside closing quotes) that a
# promotion upgrades to a period.
_UPGRADEABLE_TAIL_RE = re.compile(r'[,;:](["\'’”)\]]*)$')

# Trailing closing quotes/brackets — an appended period lands BEFORE them
# ("word\"" → "word.\""). Always matches (possibly empty).
_CLOSERS_TAIL_RE = re.compile(r'(["\'’”)\]]*)$')

# Words an English sentence essentially never ends on — a pause after one of
# these is hesitation ("the... [pause] biggest thing"), never a period.
# Deliberately excludes particles/pronouns that legitimately end sentences
# ("give up.", "come in.", "I like that.", "thank you.").
_NON_FINAL_WORDS = frozenset("""
    a an the and but or nor so yet because although though while whereas if
    unless until than which whose whom of to into onto upon from with without
    toward towards versus via per at for as my your his her its our their
    am is are was were be been being do does will would can could shall
    should may might must have has had very really quite such i
""".split())


def runon_split_enabled() -> bool:
    """Run-on sentence-boundary kill-switch. Default ON; set
    SENTENCE_BOUNDARY_SPLIT_ENABLED=0 to fall back to Whisper's own
    punctuation only (live-loop safety valve, no redeploy)."""
    return (os.getenv("SENTENCE_BOUNDARY_SPLIT_ENABLED") or "1") \
        .strip().lower() not in ("0", "false", "no", "off")


def _promote_token(token: str) -> str:
    """End ``token`` with a period: upgrade a trailing , ; : — or append —
    keeping any closing quotes/brackets outside it. Whitespace preserved."""
    lead = token[:len(token) - len(token.lstrip())]
    trail = token[len(token.rstrip()):]
    core = token.strip()
    m = _UPGRADEABLE_TAIL_RE.search(core)
    if m is None:
        m = _CLOSERS_TAIL_RE.search(core)
    return lead + core[:m.start()] + "." + m.group(1) + trail


def _capitalize_token(token: str) -> str:
    """Uppercase the first letter (skipping any opening quote/bracket)."""
    for i, ch in enumerate(token):
        if ch.isalpha():
            return token[:i] + ch.upper() + token[i + 1:]
    return token


def split_runon_sentences(words: Any, *, min_gap_ms: int | None = None,
                          min_chars: int | None = None) -> list:
    """Promote real speech pauses to sentence boundaries in the (ideally
    punctuation-restored) word stream — the run-on fix (founder BE-1c,
    2026-07-16). Deterministic; no LLM.

    A boundary between adjacent speech words is promoted to a full stop when
    ALL of these hold:

      * the pause between them is >= ``min_gap_ms`` (default 600, env
        SENTENCE_SPLIT_MIN_GAP_MS) — sentence-end pauses run long,
        hesitations short;
      * the running sentence is already >= ``min_chars`` (default 60, env
        SENTENCE_SPLIT_MIN_CHARS) since the last sentence end — short
        sentences are left alone;
      * the previous word doesn't already end a sentence;
      * the previous word isn't a dangling connective (_NON_FINAL_WORDS).

    Promotion: the previous word's trailing comma/semicolon/colon upgrades
    to ``.`` (an appended ``.`` stays inside closing quotes) and the next
    word is capitalized. Words are NEVER added, removed, or reordered —
    punctuation and casing only; ``start``/``end`` spans are STRICTLY
    untouched. Returns NEW word dicts (malformed entries pass through).
    Pure given env.
    """
    gap_need = min_gap_ms if isinstance(min_gap_ms, int) \
        else _env_int("SENTENCE_SPLIT_MIN_GAP_MS", 600)
    chars_need = min_chars if isinstance(min_chars, int) \
        else _env_int("SENTENCE_SPLIT_MIN_CHARS", 60)
    src = list(words or [])
    if not src:
        return src
    out = [dict(w) if isinstance(w, dict) else w for w in src]
    idxs = [i for i, w in enumerate(out)
            if isinstance(w, dict) and (w.get("word") or "").strip()
            and isinstance(w.get("start"), (int, float))]

    run_chars = 0  # chars since the last sentence end
    for pos, i in enumerate(idxs):
        tok = out[i]["word"].strip()
        run_chars += len(tok) + (1 if run_chars else 0)
        if _ends_sentence(tok):
            run_chars = 0
            continue
        if pos + 1 >= len(idxs):
            break
        nxt = out[idxs[pos + 1]]
        pe = out[i].get("end")
        pe = float(pe) if isinstance(pe, (int, float)) \
            else float(out[i]["start"])
        if (float(nxt["start"]) - pe) * 1000.0 < gap_need:
            continue
        if run_chars < chars_need or _norm_token(tok) in _NON_FINAL_WORDS:
            continue
        out[i]["word"] = _promote_token(out[i]["word"])
        nxt["word"] = _capitalize_token(nxt["word"])
        run_chars = 0
    return out


def chunk_words_by_chars(words: Any, max_chars: int = _DECKLESS_CHUNK_CHARS) -> list:
    """Chunk the word list into ~max_chars text pieces with per-chunk audio
    spans — SENTENCE-AWARE (founder BE-1b, 2026-07-15).

    ``words`` = [{word, start, end}] in SECONDS (Whisper verbose_json),
    ideally punctuation-restored first (restore_punctuation). Rules:

      * ``max_chars`` (200) is the TARGET. When the buffer would exceed it:
        close at the LAST sentence end in the buffer when one exists (the
        remainder opens the next piece);
      * no sentence end yet → keep extending; close at the FIRST sentence
        end within the hard cap (target+100 = 300, founder-locked);
      * still none at the hard cap → close at the word boundary before it
        (the run-on-sentence escape hatch);
      * a word is never split; a single over-long word gets its own piece.

    Unpunctuated input (no sentence ends anywhere) degrades to plain
    word-boundary cuts at the HARD cap. Returns ``[{index, transcript,
    start_offset_ms, duration_ms}, ...]`` in time order, exact word-derived
    spans; ``[]`` when there are no usable words. Pure.
    """
    cap = max_chars if isinstance(max_chars, int) and max_chars > 0 \
        else _DECKLESS_CHUNK_CHARS
    # Extension is PROPORTIONAL (half the target, capped at +100) so the
    # founder-locked default holds exactly (200 → 300) while small custom
    # caps keep sane windows instead of being swallowed by a flat +100.
    hard_cap = cap + min(_SENTENCE_EXTENSION_CHARS, cap // 2)
    ordered = sorted(
        (w for w in (words or []) if isinstance(w, dict)
         and isinstance(w.get("start"), (int, float))
         and (w.get("word") or "").strip()),
        key=lambda w: w.get("start") or 0.0,
    )
    out: list = []
    buf: list = []          # [(token, start_ms, end_ms)]
    cur_len = 0
    last_sent = None        # index in buf of the last sentence-ending token

    def _emit(entries):
        if entries:
            start_ms = entries[0][1]
            end_ms = max(e[2] for e in entries)
            out.append({
                "index": len(out),
                "transcript": " ".join(e[0] for e in entries),
                "start_offset_ms": start_ms,
                "duration_ms": max(0, end_ms - start_ms),
            })

    def _close_upto(idx):
        # Emit buf[:idx+1]; the remainder stays as the next piece's start.
        nonlocal buf, cur_len, last_sent
        _emit(buf[:idx + 1])
        buf = buf[idx + 1:]
        cur_len = sum(len(e[0]) for e in buf) + max(0, len(buf) - 1)
        last_sent = None
        for i, e in enumerate(buf):
            if _ends_sentence(e[0]):
                last_sent = i

    for w in ordered:
        token = (w.get("word") or "").strip()
        st = float(w.get("start") or 0.0)
        en = w.get("end")
        en = float(en) if isinstance(en, (int, float)) else st
        entry = (token, int(st * 1000), int(en * 1000))
        cost = len(token) + (1 if buf else 0)
        if buf and cur_len + cost > cap:
            if last_sent is not None:
                # never end mid-sentence when a sentence end exists
                _close_upto(last_sent)
                cost = len(token) + (1 if buf else 0)
            if buf and cur_len + cost > hard_cap:
                # run-on escape hatch — word boundary before the hard cap
                _close_upto(len(buf) - 1)
                cost = len(token)
        buf.append(entry)
        cur_len += cost
        if _ends_sentence(token):
            if cur_len >= cap:
                _close_upto(len(buf) - 1)   # first sentence end ≤ hard cap
            else:
                last_sent = len(buf) - 1
    if buf:
        _close_upto(len(buf) - 1)
    return out


def _contiguous_slide_runs(words_all: Any, slide_advances: Any,
                           slides: Any) -> list:
    """Split the WHOLE-recording word list into CONTIGUOUS per-slide runs in
    time order — a new run starts whenever the slide on screen changes. A
    slide revisited later (back-navigation A→B→A) yields TWO separate runs,
    never one merged bucket, so a piece cut from a run can never span a slide
    boundary or swallow another slide's audio.

    Returns ``[(slide_index, [word dicts]), ...]`` time-ordered. Pure.
    """
    n = len(slides) if isinstance(slides, list) else 0
    if n == 0 or not words_all or not slide_advances:
        return []
    adv = slide_advances
    from services.slide_alignment import slide_index_for_offset
    ordered = sorted(
        (w for w in words_all if isinstance(w, dict)
         and isinstance(w.get("start"), (int, float))
         and (w.get("word") or "").strip()),
        key=lambda w: w.get("start") or 0.0,
    )
    runs: list = []
    cur_si = None
    cur: list = []
    for w in ordered:
        start_ms = int(float(w.get("start")) * 1000)
        si = slide_index_for_offset(start_ms, adv)
        si = 0 if not isinstance(si, int) else max(0, min(si, n - 1))
        if si != cur_si:
            if cur:
                runs.append((cur_si, cur))
            cur_si, cur = si, [w]
        else:
            cur.append(w)
    if cur:
        runs.append((cur_si, cur))
    return runs


def chunk_slide_words_by_chars(words_all: Any, slide_advances: Any,
                               slides: Any,
                               max_chars: int = _DECKLESS_CHUNK_CHARS) -> list:
    """The DECKED piece cutter (founder 2026-07-14 — the core unit): slide
    boundaries FIRST (the tap timeline), then ≤max_chars word-boundary pieces
    WITHIN each contiguous slide visit. By construction a piece can never
    cross a slide boundary — a REVISITED slide is a separate run, so a piece's
    audio span is always exact and contiguous (never swallows another slide's
    speech). Same span math as the deckless cutter, so text/audio can't drift.

    Returns ``[{index, slide_index, transcript, start_offset_ms,
    duration_ms}, ...]`` — ``index`` is the GLOBAL running ordinal in time
    order across the take; ``slide_index`` is the deck slide the piece was
    spoken on (a revisited slide appears under its index again, later in the
    list). Silent slides contribute no pieces. Returns [] when there are no
    slides or no usable words. Pure.
    """
    n = len(slides) if isinstance(slides, list) else 0
    if n == 0:
        return []
    out: list = []
    for slide_index, run_words in _contiguous_slide_runs(
            words_all, slide_advances, slides):
        for piece in chunk_words_by_chars(run_words, max_chars):
            piece["index"] = len(out)      # global time-ordered ordinal
            piece["slide_index"] = slide_index
            out.append(piece)
    return out


def chunk_transcript_by_chars(text: Any, max_chars: int = _DECKLESS_CHUNK_CHARS) -> list:
    """Text-only fallback for LEGACY deckless recordings persisted as one
    blob with no word list: same ≤max_chars word-boundary split, but no
    audio spans (the FE hides the per-chunk play control).

    Returns ``[{index, transcript}, ...]``; ``[]`` for blank input. Pure.
    """
    cap = max_chars if isinstance(max_chars, int) and max_chars > 0 \
        else _DECKLESS_CHUNK_CHARS
    words = (text or "").split()
    if not words:
        return []
    out: list = []
    tokens: list = []
    cur_len = 0
    for token in words:
        cost = len(token) + (1 if tokens else 0)
        if tokens and cur_len + cost > cap:
            out.append({"index": len(out), "transcript": " ".join(tokens)})
            tokens = []
            cur_len = 0
        tokens.append(token)
        cur_len += len(token) + (1 if cur_len else 0)
    if tokens:
        out.append({"index": len(out), "transcript": " ".join(tokens)})
    return out


def deckless_chunks_from_stx(stx: Any) -> list:
    """The ONE canonical deckless chunk list for a session, from its persisted
    ``slide_transcripts`` entries — shared by the readout fold AND the
    transcript-edit route's chunk-bound check so their counts can never drift.

    New-style persists (2026-07-11+) store the chunks THEMSELVES as multiple
    entries with audio spans → returned as-is (re-indexed, span-preserving).
    A single entry whose text still fits one chunk is also span-preserving.
    A legacy single-blob entry (text longer than one chunk, no per-chunk
    spans) falls back to the text-only split. Returns [] for no entries. Pure.
    """
    entries = [t for t in (stx or []) if isinstance(t, dict)
               and (t.get("transcript") or "").strip()]
    if not entries:
        return []
    if len(entries) == 1:
        text = entries[0]["transcript"].strip()
        # Legacy-blob probe at the HARD cap (review fix 2026-07-15): the
        # sentence-aware persist cutter legitimately emits a single piece up
        # to target+extension (300) — probing at the 200 target re-split
        # such a piece into span-less phantom chunks (play control lost,
        # cards unattachable, edit indexes drifting from the canonical
        # piece). Only text LONGER than the hard cap can be a legacy blob.
        _hard = _DECKLESS_CHUNK_CHARS + min(
            _SENTENCE_EXTENSION_CHARS, _DECKLESS_CHUNK_CHARS // 2)
        if len(text) > _hard:
            pieces = chunk_transcript_by_chars(text)
            if len(pieces) > 1:
                return pieces  # legacy blob → text-only chunks, no spans
            # a single unsplittable over-long token → keep the span below
        # fits one (possibly sentence-extended) piece → keep the entry's span
        e = entries[0]
        return [{
            "index": 0, "transcript": text,
            "start_offset_ms": e.get("start_offset_ms"),
            "duration_ms": e.get("duration_ms"),
        }]
    return [{
        "index": i,
        "transcript": e["transcript"].strip(),
        "start_offset_ms": e.get("start_offset_ms"),
        "duration_ms": e.get("duration_ms"),
    } for i, e in enumerate(entries)]
