"""The golden set: manifest schema, loader, and coverage checks.

A take in the corpus is one audio file plus whatever ground truth we have
for it. The schema is deliberately tolerant about what is MISSING and strict
about what is WRONG — a half-labeled corpus should still produce the numbers
it can support and say plainly which ones it cannot, because that is the
state a real corpus is in for most of its life.

WHAT EACH FIELD UNLOCKS
-----------------------
    audio                 (required)  nothing works without it
    reference_text                    → WER (tier 1)
    slide_advances + slides           → slide-bucket agreement (THE metric)
    reference_words                   → timestamp ACCURACY (tier 2) instead
                                        of agreement-with-whisper-1 (tier 3)
    language                          → correct prompt rule + filler list
    accent / speaker_id / condition   → per-stratum breakdown, which is the
                                        whole point of an accent bake-off:
                                        a corpus average hides the exact
                                        subgroup the migration is meant to
                                        fix

STRATIFICATION IS NOT OPTIONAL
------------------------------
Six clean American-English takes and one heavily-accented one produce an
average that says the migration is fine. ``strata_report`` exists so the
per-stratum numbers are always in front of the reader, and so a stratum with
too few takes to mean anything is labeled as such instead of being quoted.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Below this, a stratum's mean is noise. Reported, but flagged — quoting a
# WER off two takes is how a migration gets approved on a coin flip.
MIN_TAKES_PER_STRATUM = 5

_REQUIRED = ("take_id", "audio")


class CorpusError(RuntimeError):
    """Manifest is malformed in a way that cannot be degraded around."""


# Extensions that mark a reference_text value as a PATH, not inline prose.
_TEXT_SUFFIXES = (".txt", ".md", ".json", ".vtt", ".srt", ".text")


def _looks_like_path(v: str) -> bool:
    """Is this value meant to be a file path rather than inline text?

    Needed because the two are otherwise indistinguishable, and guessing
    wrong is silently catastrophic: a typo'd ``refs/take-01.txt`` that falls
    back to "inline text" makes the literal string ``refs/take-01.txt`` the
    reference transcript, and the take then scores ~100% WER against every
    provider. The harness would report a confident, entirely fictional
    number. A path-shaped value that does not resolve must be an ERROR.
    """
    return ("/" in v or "\\" in v or v.lower().endswith(_TEXT_SUFFIXES))


def _read_maybe_file(value: Any, root: str, *, field: str,
                     take_id: str) -> Optional[str]:
    """A field that may be inline text or a path relative to the manifest.

    Reference transcripts get long; inline is convenient for a 30-word
    snippet and miserable for a 10-minute take, so both are accepted — but a
    path-shaped value that does not resolve raises instead of degrading to
    itself (see ``_looks_like_path``).
    """
    if not isinstance(value, str) or not value.strip():
        return None
    v = value.strip()
    cand = v if os.path.isabs(v) else os.path.join(root, v)
    if os.path.isfile(cand):
        with open(cand, "r", encoding="utf-8") as fh:
            return fh.read().strip()
    if _looks_like_path(v):
        raise CorpusError(
            f"take {take_id!r}: {field} looks like a path but no file exists "
            f"at {cand!r}. Refusing to treat it as inline text — that would "
            f"silently make the path string the reference transcript.")
    return v


def _coerce_advances(raw: Any) -> list:
    """Normalize slide taps to ``[{index:int, t_ms:int}]``.

    ``slide_index_for_offset`` requires BOTH to be real ints — it silently
    skips entries where either is a float, so a manifest written with
    ``"t_ms": 18400.0`` would produce a timeline that looks present and
    buckets every word to slide 0. Coercing here turns that into a correct
    timeline instead of a silent wrong answer.
    """
    out = []
    for a in (raw or []):
        if not isinstance(a, dict):
            continue
        idx, t = a.get("index"), a.get("t_ms")
        if isinstance(idx, bool) or isinstance(t, bool):
            continue
        if not isinstance(idx, (int, float)) or not isinstance(t, (int, float)):
            continue
        out.append({"index": int(idx), "t_ms": int(t)})
    out.sort(key=lambda a: a["t_ms"])
    return out


def load_take(entry: Any, root: str) -> dict:
    """One manifest entry → a validated take dict."""
    if not isinstance(entry, dict):
        raise CorpusError(f"take entry is not an object: {entry!r}")
    for k in _REQUIRED:
        if not str(entry.get(k) or "").strip():
            raise CorpusError(f"take is missing required field {k!r}: {entry!r}")

    audio = entry["audio"]
    audio_path = audio if os.path.isabs(audio) else os.path.join(root, audio)

    ref_words = entry.get("reference_words")
    if isinstance(ref_words, str) and ref_words.strip():
        p = (ref_words if os.path.isabs(ref_words)
             else os.path.join(root, ref_words))
        try:
            with open(p, "r", encoding="utf-8") as fh:
                ref_words = json.load(fh)
        except Exception as e:
            # Tier 3 is a legitimate fallback (unlike a bogus reference
            # transcript, which is fabricated ground truth), so this warns
            # rather than raising — but it must be visible, since it
            # silently downgrades every timing number in the run.
            logger.warning("take %s: reference_words unreadable (%s) — timing "
                           "drops to tier 3", entry["take_id"], e)
            ref_words = None
    if not isinstance(ref_words, list):
        ref_words = None

    slides = entry.get("slides")
    if isinstance(slides, int):          # "5 slides, contents irrelevant"
        slides = [{} for _ in range(max(0, slides))]
    if not isinstance(slides, list):
        slides = None

    return {
        "take_id": str(entry["take_id"]).strip(),
        "audio_path": audio_path,
        "audio_exists": os.path.isfile(audio_path),
        "reference_text": _read_maybe_file(
            entry.get("reference_text"), root,
            field="reference_text", take_id=str(entry["take_id"])),
        "reference_words": ref_words,
        "language": (str(entry.get("language") or "").strip().lower() or None),
        "vocabulary": [str(t) for t in (entry.get("vocabulary") or [])],
        "slide_advances": _coerce_advances(entry.get("slide_advances")),
        "slides": slides,
        "slide_clock_offset_ms": entry.get("slide_clock_offset_ms"),
        # Stratum keys — free-form, whatever the corpus wants to slice by.
        "accent": (str(entry.get("accent") or "").strip() or "unspecified"),
        "condition": (str(entry.get("condition") or "").strip() or "unspecified"),
        "speaker_id": (str(entry.get("speaker_id") or "").strip() or None),
        "duration_s": entry.get("duration_s"),
        "notes": entry.get("notes") or "",
    }


def load_manifest(path: str) -> dict:
    """Load a corpus manifest (JSON object, or JSONL of take entries)."""
    if not os.path.isfile(path):
        raise CorpusError(f"manifest not found: {path}")
    root = os.path.dirname(os.path.abspath(path))
    with open(path, "r", encoding="utf-8") as fh:
        raw = fh.read().strip()
    if not raw:
        raise CorpusError(f"manifest is empty: {path}")

    meta: dict = {}
    if raw.lstrip().startswith("{") and '"takes"' in raw:
        doc = json.loads(raw)
        entries = doc.get("takes") or []
        meta = {k: v for k, v in doc.items() if k != "takes"}
    elif raw.lstrip().startswith("["):
        entries = json.loads(raw)
    else:                                   # JSONL
        entries = [json.loads(ln) for ln in raw.splitlines()
                   if ln.strip() and not ln.lstrip().startswith("#")]

    takes = [load_take(e, root) for e in entries]
    ids = [t["take_id"] for t in takes]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise CorpusError(f"duplicate take_id(s): {sorted(dupes)}")
    return {"root": root, "meta": meta, "takes": takes}


def readiness(corpus: Any) -> dict:
    """What this corpus can and cannot measure, before spending a cent.

    Run before any sweep. Its job is to answer "is the golden set good
    enough yet?" concretely enough to hand back as a data request, rather
    than discovering mid-run that the headline metric is unmeasurable.
    """
    takes = (corpus or {}).get("takes") or []
    n = len(takes)
    missing_audio = [t["take_id"] for t in takes if not t["audio_exists"]]
    with_ref = [t for t in takes if t["reference_text"]]
    with_deck = [t for t in takes
                 if t["slide_advances"] and t["slides"]]
    with_times = [t for t in takes if t["reference_words"]]

    strata: dict = {}
    for t in takes:
        strata.setdefault(t["accent"], []).append(t["take_id"])

    blockers = []
    if not n:
        blockers.append("corpus is empty")
    if missing_audio:
        blockers.append(f"{len(missing_audio)} take(s) have no audio file on "
                        f"disk: {missing_audio[:5]}")
    if not with_deck:
        blockers.append(
            "no take has BOTH slide_advances and slides — slide-bucket "
            "agreement, the metric that decides this migration, cannot be "
            "computed for any take")
    if not with_ref:
        blockers.append("no take has reference_text — no WER is computable")

    warnings = []
    if not with_times:
        warnings.append(
            "no take has reference_words — all timing numbers will be TIER 3 "
            "(agreement with whisper-1), which cannot show a candidate is "
            "BETTER, only that it differs. Run the forced-align-reference "
            "provider to produce them.")
    thin = {k: len(v) for k, v in strata.items()
            if len(v) < MIN_TAKES_PER_STRATUM}
    if thin:
        warnings.append(
            f"strata below {MIN_TAKES_PER_STRATUM} takes — means are not "
            f"trustworthy: {thin}")

    return {
        "takes": n,
        "with_audio": n - len(missing_audio),
        "with_reference_text": len(with_ref),
        "with_deck_timeline": len(with_deck),
        "with_reference_word_times": len(with_times),
        "strata": {k: len(v) for k, v in sorted(strata.items())},
        "can_compute_wer": bool(with_ref),
        "can_compute_slide_bucket": bool(with_deck),
        "can_compute_timestamp_accuracy": bool(with_times),
        "blockers": blockers,
        "warnings": warnings,
        "ready": not blockers,
    }


def strata_report(rows: Any, key: str = "accent") -> dict:
    """Group per-take results by stratum, flagging thin ones.

    ``rows`` are ``{take, result}`` dicts from the runner.
    """
    groups: dict = {}
    for r in (rows or []):
        groups.setdefault((r.get("take") or {}).get(key, "unspecified"),
                          []).append(r)
    return {
        k: {"takes": len(v),
            "trustworthy": len(v) >= MIN_TAKES_PER_STRATUM,
            "rows": v}
        for k, v in sorted(groups.items())
    }
