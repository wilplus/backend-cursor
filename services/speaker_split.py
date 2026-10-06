"""The speaker-disjoint split both data doors read (MLC-2 F-3).

Until 2026-10-05 door 2 (the weekly pair release) and door 3 (the fine-tune
run) each hashed the pair's OWNER PRINCIPAL into 80/10/10. A principal is an
account or a guest, not a person: the foundation keeps the person as a
speaker (``ml_speakers``), bound to each principal they acted through, and
gives the speaker ONE deterministic assignment per split policy
(``ml_speaker_split_assignments``, written once by
``assign_ml_speaker_split_v1`` when the speaker is bound, never changed).

Since the training yes binds the speaker (founder 2026-10-05, N48.5 Q27 A;
migration 0430; ``services/speaker_identity.py``), every person whose pairs
can leave has, or gets at their next visit to the switch, a speaker. So:

  * door 2 releases a pair only when its owner's speaker has an assignment,
    and writes that assignment as the pair's split. A pair whose owner is not
    bound yet waits, and the job says so: a split that changed between
    weeks would put one person on both sides of a frozen test set;
  * door 3 trains each pair under the split its release used, read from
    the release's manifest (``split_source``): the same speaker assignment
    for a release made since F-3, the owner-principal hash for one made
    before. A pair whose split cannot be known now is left out, never
    guessed, so a pair released as "test" is never trained on.

Counts and splits only; nothing here reaches a speaker or a coach (AC-9).
"""
from __future__ import annotations

import logging
from typing import Any, Iterable, Optional

_log = logging.getLogger(__name__)

SPLIT_POLICY_VERSION = "speaker-sha256-80-10-10-v1"
SPLITS = ("train", "validation", "test")
SPEAKER_SOURCE = "speaker_assignment"
FALLBACK_SOURCE = "owner_principal_fallback"
WAITING_REASON = "waiting for the owner's speaker binding (training yes, F-3)"


def speaker_splits(database: Any, owner_ids: Iterable[Any]) -> dict[str, str]:
    """``{owner_principal_id: split}`` from each owner's bound speaker's
    assignment. An owner with no bound speaker, or no assignment, is absent;
    an unreadable table reads as nobody bound (the doors then wait)."""
    owners = sorted({str(o) for o in owner_ids if o})
    reader = getattr(database, "get_speaker_splits_for_principals", None)
    if not owners or reader is None:
        return {}
    try:
        rows = reader(owners, SPLIT_POLICY_VERSION) or {}
    except Exception as error:  # noqa: BLE001 - named, never a silent split
        _log.warning("speaker split read failed: %s", error, exc_info=True)
        return {}
    return {str(owner): str(split) for owner, split in rows.items()
            if str(split) in SPLITS}


def release_split_sources(database: Any, release_ids: Iterable[Any]) -> dict[str, str]:
    """``{release_id: split_source}`` from each release's manifest: a release
    made since F-3 says ``speaker_assignment``; one made before has no
    ``split_source`` and split by the owner-principal hash. A release that
    cannot be read is absent (its pairs then wait at door 3)."""
    ids = sorted({str(r) for r in release_ids if r})
    reader = getattr(database, "get_pair_release_manifests", None)
    if not ids or reader is None:
        return {}
    try:
        manifests = reader(ids) or {}
    except Exception as error:  # noqa: BLE001 - named; the pairs wait
        _log.warning("release manifest read failed: %s", error, exc_info=True)
        return {}
    return {str(rid): (SPEAKER_SOURCE
                       if (manifest or {}).get("split_source") == SPEAKER_SOURCE
                       else FALLBACK_SOURCE)
            for rid, manifest in manifests.items()}


def released_split(pair: dict, splits: dict[str, str],
                   sources: dict[str, str]) -> Optional[str]:
    """The split a released pair left under, or ``None`` when that cannot be
    known now (door 3 then leaves the pair out rather than guess): the
    owner's speaker assignment for a release that used it, the
    owner-principal hash for a release made before F-3."""
    owner = str(pair.get("owner_principal_id") or "")
    source = sources.get(str(pair.get("release_id") or ""))
    if not owner or source is None:
        return None
    if source == SPEAKER_SOURCE:
        return splits.get(owner)
    from services.dataset_releases import speaker_split
    return speaker_split(owner)[0]


def split_for(owner_principal_id: str, splits: dict[str, str]) -> tuple[str, str]:
    """``(split, source)`` for one owner: the speaker's assignment, or the
    owner-principal hash the doors used before (door 3's fallback only)."""
    owner = str(owner_principal_id or "")
    if owner in splits:
        return splits[owner], SPEAKER_SOURCE
    from services.dataset_releases import speaker_split
    split, _digest = speaker_split(owner) if owner else ("train", "")
    return split, FALLBACK_SOURCE
