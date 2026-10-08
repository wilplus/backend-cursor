"""The release-time eligibility decision for a pair (PLF-1.1 "Dataset
eligibility"; audit PLF-P5; founder 2026-10-05, wave 4).

The weekly refresh (``refresh_feedback_pair_consent_v1``, 0405, 0422) keeps
a ``releasable`` flag on every pair, and the export lists pairs by it. PLF
asks for more at the boundary itself: "Dataset eligibility is never
inherited from a policy flag or an old snapshot. Every prospective release
item must receive a fresh, immutable eligibility decision." So the export
decides every candidate pair AGAIN, at the moment of release, from the
sources themselves, not from the flag:

  1. the texts are still a pair: both present and the final differs from
     the draft (the C5 rule), on a surface door 2 may release;
  2. CURRENT pooled-improvement authorization: the owner's training-only
     yes in force now (``training_consent_active_grants``, the view the
     refresh itself reads), for every surface counsel says needs it;
  3. the owner's service is not ending: no account deletion that was not
     cancelled, no termination, deletion or retention-expiry block
     (``phase1_learning_stopped_v1``, 0422);
  4. the pair's project is not being deleted and was not erased (an open
     or finished ``project_deletion_requests`` row, a tombstoned project;
     0364, 0422), and its Take still exists;
  5. the exact texts that leave are fingerprinted now (``item_sha256``),
     the text counterpart of PLF's recomputed audio hash: a pair carries no
     audio, only the two texts.

A pair that fails a check stays out of this release (the next refresh
settles its flag) and is counted under its reason. The decision's record
is the signed manifest: its ``eligibility`` block (version, time, counts by
reason) is inside the hash the release key signs, beside the file and in
``pair_releases.manifest``; each line carries its fingerprint and the time
it was decided. A source that cannot be read raises, and the export of that
surface fails for the week: nothing leaves on a guess.

What this does not do, and the report says so: it writes no per-item row
for a pair that did NOT leave (the manifest counts them by reason), and it
does not re-check a Take's acquisition snapshot (a pair is a coach's text
about a passage; the Take's processing authority was checked when it was
processed, and a deletion or termination since is check 3).
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime
from typing import Any, Iterable

DECISION_VERSION = "pair-release-eligibility-v1"

#: Why a candidate stayed out, in the order the checks run.
REASONS = (
    "texts_not_a_pair",      # 1
    "no_owner",              # 2: a surface that needs the yes, no principal
    "no_current_yes",        # 2: no training yes in force now
    "service_ending",        # 3
    "take_gone",             # 4: the pair names a Take that no longer exists
    "project_leaving",       # 4: the project is being deleted or was erased
)


def _norm(text: Any) -> str:
    return " ".join(text.split()) if isinstance(text, str) else ""


def item_sha256(pair: dict) -> str:
    """The fingerprint of exactly what leaves for this pair: its surface,
    the two texts and the final's kind, canonical JSON, sha256."""
    body = json.dumps({"surface": str(pair.get("surface") or ""),
                       "draft": str(pair.get("draft_text") or ""),
                       "final": str(pair.get("final_text") or ""),
                       "final_kind": str(pair.get("final_kind") or "final")},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(str(value))
    except (TypeError, ValueError):
        return False
    return True


def _projects_leaving(database: Any, project_ids: Iterable[str]) -> set[str]:
    """Projects with an open deletion request, or erased (a finished request
    or a tombstone). Raises on a read failure (project_deletion.py raises on
    anything but a missing table)."""
    from services.project_deletion import ProjectDeletionService
    ids = sorted({p for p in project_ids if p})
    if not ids:
        return set()
    service = ProjectDeletionService(database)
    return set(service.open_for_projects(ids)) | service.erased_projects(ids)


def _owners(pairs: list[dict]) -> list[str]:
    return sorted({str(p.get("owner_principal_id")) for p in pairs
                   if p.get("owner_principal_id")})


def _sources(database: Any, pairs: list[dict], needs_yes: bool) -> dict:
    """Every read the decision makes, made once for the whole batch. Any
    failure raises: the export of the surface then fails, nothing leaves."""
    owners = _owners(pairs)
    grants: dict[str, dict] = {}
    if needs_yes and owners:
        for row in database.list_active_training_grants(owners) or []:
            if isinstance(row, dict) and row.get("acquisition_principal_id"):
                grants[str(row["acquisition_principal_id"])] = row
    # One question per person still in the running: an owner without a yes
    # is out already, whatever their service says.
    asked = [o for o in owners if o in grants] if needs_yes else owners
    stopped = {owner for owner in asked if database.phase1_learning_stopped(owner) is True}
    takes = sorted({str(p.get("take_session_id")) for p in pairs
                    if p.get("take_session_id")})
    projects = database.list_take_projects([t for t in takes if _is_uuid(t)]) if takes else {}
    leaving = _projects_leaving(database, projects.values())
    return {"grants": grants, "stopped": stopped, "projects": projects, "leaving": leaving}


def _why_not(pair: dict, sources: dict, needs_yes: bool) -> str | None:
    draft, final = _norm(pair.get("draft_text")), _norm(pair.get("final_text"))
    if not draft or not final or draft == final:
        return "texts_not_a_pair"
    owner = str(pair.get("owner_principal_id") or "")
    if needs_yes:
        if not owner:
            return "no_owner"
        if owner not in sources["grants"]:
            return "no_current_yes"
    if owner and owner in sources["stopped"]:
        return "service_ending"
    take = str(pair.get("take_session_id") or "")
    if take:
        if take not in sources["projects"]:
            return "take_gone"
        if sources["projects"][take] in sources["leaving"]:
            return "project_leaving"
    return None


def decide(database: Any, pairs: list[dict], *, surface: str,
           required_surfaces: Iterable[str], now: datetime) -> dict:
    """The fresh decision for every candidate pair of one surface.

    Returns ``{"eligible": [...], "summary": {...}}``: the pairs that may
    leave, each carrying the consent it rests on NOW (``consent_state``,
    ``consent_policy_version``, ``consent_grant_event_id`` from the grant
    in force, not the weekly stamp), its ``item_sha256`` and
    ``eligibility_decided_at``; and the summary the manifest signs. Raises
    when a source cannot be read."""
    candidates = [p for p in pairs if isinstance(p, dict)]
    needs_yes = surface in set(required_surfaces)
    sources = _sources(database, candidates, needs_yes)
    decided_at = now.isoformat()
    eligible: list[dict] = []
    excluded: dict[str, int] = {}
    for pair in candidates:
        reason = _why_not(pair, sources, needs_yes)
        if reason:
            excluded[reason] = excluded.get(reason, 0) + 1
            continue
        grant = sources["grants"].get(str(pair.get("owner_principal_id") or ""))
        fresh = dict(pair)
        if needs_yes and grant:
            fresh.update(consent_state="yes", consent_grant_event_id=str(grant.get("id") or ""),
                         consent_policy_version=grant.get("consent_policy_version"))
        elif not needs_yes:
            fresh.update(consent_state="not_needed")
        fresh.update(item_sha256=item_sha256(pair), eligibility_decided_at=decided_at)
        eligible.append(fresh)
    return {
        "eligible": eligible,
        "summary": {
            "decision_version": DECISION_VERSION,
            "decided_at": decided_at,
            "consent_required": needs_yes,
            "checked": len(candidates),
            "eligible": len(eligible),
            "excluded": {reason: excluded[reason] for reason in REASONS if reason in excluded},
        },
    }


def summary_words(summary: dict) -> str:
    """The week's row when nothing left: why, in words, by reason."""
    excluded = summary.get("excluded") or {}
    parts = [f"{count} {reason.replace('_', ' ')}" for reason, count in excluded.items()]
    return "nothing eligible at release time (" + (", ".join(parts) or "no candidate") + ")"
