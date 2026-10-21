"""Judging the training corpus mixed (founder 2026-10-21, N101).

"Make sure that for the display of the recordings for the judgement, they do
not come from the same speaker; the fragments are really mixed, with
different willfidence scores like really neutral, high, and low."

A round is drawn across every open import the coach may hear, only from each
import's frozen cohort, so every clip plays (``queued_corpus_clip``) and its
rating is stamped with the cohort's own record (K9):

- THE MACHINE'S READS IN EQUAL MEASURE. Up to ``PER_BAND`` clips from each
  delivery-signal band (high, neutral, low; unscored as a group of its own),
  so a round holds all three. The band decides which clips come in, never
  where they stand.
- A BLIND ORDER (BLIND COACH, N2). The order is a seeded uniform shuffle of
  the clip ids, then one pass that brings a clip of another speaker forward
  whenever the next one shares the last one's speaker. It is a function of
  the seed, the ids and the speakers only, so no position tells a band; and
  there is no strict one-of-each-band rotation, which would let a coach rule
  a band out by elimination.
- NEVER ONE SPEAKER TWICE IN A ROW while another is left in the round.

A round carries the import queue's own allowlist (``corpus_presented_rows``)
and the import's topic, the label the judging screen already shows: no
import id, speaker, band, score or selection record. Only clips this coach
has not answered and may still answer come in; the next round is read when
this one is done.
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable, Optional

#: Clips a round takes from each band of the machine's read.
PER_BAND = 10
#: Imports read together while a round is gathered.
_IMPORT_BATCH = 50
#: The bands a round is balanced over (services.confidence_labels.band_of).
_NAMED_BANDS = ("delivery_signal_high", "delivery_signal_neutral",
                "delivery_signal_low")
_LABEL_CHUNK = 150


def _key(seed: str, purpose: str, value: Any) -> str:
    return hashlib.sha1(f"{seed}:{purpose}:{value}".encode("utf-8")).hexdigest()


def _alternate(ordered: list[dict]) -> list[dict]:
    """The same clips, the first kept first, each next one of another
    speaker than the last whenever one is left. Pure."""
    if not ordered:
        return []
    out, rest = [ordered[0]], list(ordered[1:])
    while rest:
        last = out[-1]["speaker"]
        at = next((i for i, c in enumerate(rest) if c["speaker"] != last), 0)
        out.append(rest.pop(at))
    return out


def mixed_round(candidates: list[dict], *, seed: str,
                start_session: Optional[str] = None,
                per_band: int = PER_BAND) -> list[dict]:
    """One round from the clips a coach may answer, in its order. Each
    candidate is ``{snippet_id, session_id, speaker, band, ...}``.

    Up to ``per_band`` clips from each band come in, drawn by a seeded hash;
    a clip of ``start_session`` (the import the coach opened) comes first
    when it has one. The rest are ordered by another seeded hash of their
    ids alone, then never one speaker twice in a row when it can be helped.
    Pure."""
    pool = sorted(candidates, key=lambda c: _key(seed, "draw", c["snippet_id"]))
    first = next((c for c in pool if start_session
                  and c["session_id"] == str(start_session)), None)
    taken: dict[str, int] = {}
    chosen: list[dict] = []
    for c in ([first] if first else []) + [c for c in pool if c is not first]:
        if taken.get(c["band"], 0) < per_band:
            taken[c["band"]] = taken.get(c["band"], 0) + 1
            chosen.append(c)
    rest = sorted((c for c in chosen if c is not first),
                  key=lambda c: _key(seed, "order", c["snippet_id"]))
    return _alternate(([first] if first else []) + rest)


def _answerable(rows: list, rater_id: str) -> bool:
    """A clip this coach has not answered and may answer now."""
    from services.label_quorum import rater_submission_access

    if any(str(r.get("rater_id") or "") == rater_id for r in rows or []):
        return False
    return bool(rater_submission_access(rows or [], rater_id)["allowed"])


def _candidates(database: Any, imports: list[dict], rater_id: str) -> list[dict]:
    """The clips of these imports' cohorts this coach may answer, each with
    its import, speaker, band and topic: three batched reads."""
    from services.confidence_labels import band_of, stored_selection_records
    from services.corpus_split import import_speaker_key

    cohort: dict[str, dict] = {}
    for im in imports:
        ctx = im.get("intake_context") or {}
        for record in stored_selection_records(ctx):
            cohort[record["snippet_id"]] = im
    ids = sorted(cohort)
    scores = database.get_snippet_scores_by_ids(ids) or {}
    labels: dict = {}
    for i in range(0, len(ids), _LABEL_CHUNK):
        labels.update(database.get_confidence_labels_by_snippet_ids(
            ids[i:i + _LABEL_CHUNK], strict=True) or {})
    out = []
    for snippet_id in ids:
        im, found = cohort[snippet_id], scores.get(snippet_id)
        # A cohort clip whose piece is gone, or that moved Takes, is not served.
        if not found or str(found.get("session_id")) != str(im.get("id")):
            continue
        if not _answerable(labels.get(snippet_id) or [], rater_id):
            continue
        out.append({
            "snippet_id": snippet_id,
            "session_id": str(im.get("id")),
            "speaker": import_speaker_key(im) or f"import:{im.get('id')}",
            "band": band_of(found.get("score")),
            "topic": str((im.get("intake_context") or {}).get("topic") or ""),
        })
    return out


def _enough(candidates: list[dict], per_band: int) -> bool:
    return all(sum(1 for c in candidates if c["band"] == band) >= per_band
               for band in _NAMED_BANDS)


def mixed_queue(database: Any, *, rater_id: str, seed: str,
                matched: Callable[[list], list],
                start: Optional[str] = None,
                per_band: int = PER_BAND) -> list[dict]:
    """The next round for this coach, as the judging screen receives it.

    ``matched`` is the route's language gate over import rows. Imports are
    read in a seeded order (the one the coach opened first), a batch at a
    time, until every band has a round's worth or none is left."""
    from services.corpus_coach_queue import corpus_presented_rows, corpus_queue_open

    imports = [im for im in database.takes.list_training_import_cohorts() or []
               if corpus_queue_open(im)
               and not (im.get("intake_context") or {}).get("archived_at")]
    imports = matched(imports)
    imports.sort(key=lambda im: (str(im.get("id")) != str(start or ""),
                                 _key(seed, "import", im.get("id"))))
    candidates: list[dict] = []
    for i in range(0, len(imports), _IMPORT_BATCH):
        candidates += _candidates(database, imports[i:i + _IMPORT_BATCH], rater_id)
        if _enough(candidates, per_band):
            break
    picked = mixed_round(candidates, seed=seed, start_session=start, per_band=per_band)
    rows = corpus_presented_rows([{"snippet_id": c["snippet_id"]} for c in picked])
    for row, c in zip(rows, picked):
        row["topic"] = c["topic"]
    return rows
