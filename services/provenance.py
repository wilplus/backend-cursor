"""PROVENANCE — what produced a number, and whether it can still be trusted.

SPEC-immutable-provenance §3.1, Phase A. Pure: no DB, no clock, no I/O.

THE PROBLEM THIS SOLVES, stated concretely rather than abstractly. The entire
filler detector is a bare module-level list in ``utils/metrics.py``::

    DEFAULT_FILLERS = ["um", "uh", "like", "you know", "er", "ah", "so"]

No version anywhere. Add one word and every ``fillers`` figure ever computed
becomes incomparable with every figure computed afterwards — and nothing in
the schema can separate the two eras, so the drift layer reads the step change
as the SPEAKER's behaviour rather than ours. The founder's own framing: "I have
a system that compares across databases, so if fillers are corrupted all my
data goes nuts."

``so`` sits in that list as both a filler and a conjunction, so the day someone
tightens this detector is a live prospect, not a hypothetical.

THE HASH IS THE LOAD-BEARING PART. A version string is a promise a human can
forget to keep; a hash is a fact about what the code actually is. Boot compares
the live definition's hash against the recorded one for the current version, so
"someone edited the lexicon and forgot to bump" stops being an invisible
corruption and becomes a loud, dated log line — and every row written after it
is MARKED rather than silently mixed in.

WHY MARK RATHER THAN REFUSE (founder decision 2026-08-10). Refusing to boot
trades a certain outage for an uncertain corruption, and the LIVE LOOP fence
says never break the running record→transcribe→coach→read loop. A mismatch is
recoverable as long as it is visible AND the affected rows are separable —
which is exactly what the marker buys.

CANONICAL FORM, and the one subtlety in it. Lists are SORTED before hashing,
because for every definition here the list is a SET: `count_fillers` iterates
its lexicon and counts each pattern independently, so reordering the words
cannot change a single output. Hashing the literal order instead would fire a
false mismatch on a cosmetic edit, and a checker that cries wolf gets muted —
which is worse than not having one. A detector whose behaviour genuinely
depends on order must NOT express that order as a bare list here.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Optional

# ── fit_stage — how much a definition should be trusted ─────────────────────
#
# A DIFFERENT QUESTION from `version`, which only says "which one". Analysis
# can filter on this; today it cannot filter on anything at all.
BOOTSTRAP = "bootstrap"        # first pass, small n, expected to move
PROVISIONAL = "provisional"    # stable but not defended
FROZEN = "frozen"              # never changes again; a change mints a version
FIT_STAGES = (BOOTSTRAP, PROVISIONAL, FROZEN)

# ── the provenance marker written onto measurement rows ─────────────────────
#
# `ok`      the live definition hashes to its recorded version
# `suspect` it does NOT — the row was produced by code that disagrees with its
#           own version stamp, and must be separable from clean rows forever
OK = "ok"
SUSPECT = "suspect"

# ── the detectors this module knows how to describe ─────────────────────────
#
# ONLY definitions that actually change a number belong here. A detector added
# to this table without its definition being genuinely hashable is worse than
# absent: it reports `ok` forever and looks like coverage.
FILLERS = "fillers"
DETECTORS = (FILLERS,)

# Which dimension_evaluations rows a detector's version stamps. A dimension
# absent here is stamped with NOTHING (honest NULL), never with a neighbour's
# version.
#
# There WAS a second filler lexicon (utils/filler_words.py, per-language) that
# fed clip selection rather than these rows; it was deliberately excluded here
# and then deleted outright on 2026-08-10 with the snippet generators that
# were its only reader. The rule it illustrated still stands: a lexicon that
# never produces a dimension_evaluations row must not be mapped to one, or the
# stamp claims a definition that did not produce the measurement.
DETECTOR_FOR_DIMENSION = {"fillers": FILLERS}


def canonical(definition: Any) -> str:
    """The definition as ONE stable string, ready to hash.

    Sorted keys, sorted lists, no incidental whitespace. Deterministic across
    processes and Python versions — unlike `repr()` or `hash()`, either of
    which would make the recorded hash depend on how the process happened to
    start (the same defect `_stable_fraction` avoids in manager_engine).
    """
    def _norm(v: Any) -> Any:
        if isinstance(v, dict):
            return {str(k): _norm(v[k]) for k in sorted(v, key=str)}
        if isinstance(v, (list, tuple, set)):
            # SORTED — see the module header. Every definition here is a set;
            # a cosmetic reorder must not read as a behaviour change.
            return sorted((_norm(x) for x in v), key=lambda x: json.dumps(
                x, sort_keys=True, ensure_ascii=False))
        return v

    return json.dumps(_norm(definition), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def definition_hash(definition: Any) -> str:
    """sha256 of the canonical form. The fact a version string only promises."""
    return hashlib.sha256(canonical(definition).encode("utf-8")).hexdigest()


def live_definition(detector_id: str) -> Optional[dict]:
    """The definition THIS PROCESS is actually running, or None if unknown.

    Read from the live module rather than restated here — a copy would be one
    more thing that can silently disagree with the code, which is the whole
    class of bug this file exists to catch.
    """
    if detector_id == FILLERS:
        try:
            from utils.metrics import DEFAULT_FILLERS
        except Exception:
            return None
        return {"lexicon": list(DEFAULT_FILLERS), "match": "whole_word_ci"}
    return None


def check(detector_id: str, recorded_hash: Any) -> tuple[str, Optional[str]]:
    """Compare the live definition against its recorded hash.

    Returns ``(marker, live_hash)`` where marker is OK or SUSPECT.

    UNKNOWN IS SUSPECT, deliberately. No recorded hash, or a detector this
    module cannot describe, means nobody can say what produced the number —
    which is the state the marker exists to make visible. Reporting OK there
    would be a clean bill of health issued without an examination.
    """
    live = live_definition(detector_id)
    if live is None:
        return (SUSPECT, None)
    live_hash = definition_hash(live)
    if not isinstance(recorded_hash, str) or not recorded_hash:
        return (SUSPECT, live_hash)
    return (OK if live_hash == recorded_hash.strip().lower() else SUSPECT,
            live_hash)
