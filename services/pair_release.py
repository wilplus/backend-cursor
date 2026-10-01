"""The weekly pair release (founder 2026-09-30, L2, L5; build plan ML-9).

Door 2. One file per surface per week, written to the private release
bucket with a manifest the job signs:

  * only RELEASABLE pairs leave (services/pair_consent.py: the owner's
    training yes, or a surface counsel said needs none), and a pair leaves
    once, marked under its release atomically (mark_feedback_pairs_released_v1);
  * a surface leaves only when the door is open in code AND the founder
    named the surface (Config.PAIR_RELEASE_SURFACES) by a reviewed change
    carrying his sentence; every other surface reports why it stayed;
  * the manifest carries the file's sha256, the split counts (speaker-
    disjoint 80/10/10 by owner principal, services/dataset_releases), the
    policy versions the pairs rest on, and a hash of the owner set; the
    manifest's own sha256 is signed with the release key (HMAC-SHA256),
    so a file and its manifest can be checked against each other and
    against the key later;
  * a release whose owner withdraws is voided by the weekly refresh and
    its object deleted by the sweep here (revocation purges the copies).

Counts about the system; a pair's texts leave only inside the file. AC-9:
nothing here reaches a speaker or a coach.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from services.feedback_pairs import ANSWER_SURFACES as SURFACES

_log = logging.getLogger(__name__)

RELEASE_VERSION = "pair-release-v1"
KEY_PREFIX = "pair-releases/"


class ReleaseRefusal(Exception):
    """Why a surface did not leave. Never a fault: the job reports it."""


def door_open(config: Any) -> bool:
    """Door 2 is MLC2_PAIR_RELEASES_ENABLED (its own constant since
    2026-10-01: the DPO dataset-release lane keeps MLC2_DATASET_RELEASES_ENABLED
    and stays dark)."""
    return bool(getattr(config, "MLC2_PAIR_RELEASES_ENABLED", False))


def authorised_surfaces(config: Any) -> frozenset:
    """The surfaces the founder authorised, or nothing while door 2 is
    closed in code (both flips are reviewed changes)."""
    if not door_open(config):
        return frozenset()
    named: Any = getattr(config, "PAIR_RELEASE_SURFACES", frozenset()) or frozenset()
    return frozenset(s for s in named if s in SURFACES)


def why_not(config: Any, surface: str) -> Optional[str]:
    """None when the surface may leave; else the reason, in words."""
    if not door_open(config):
        return "door 2 closed (MLC2_PAIR_RELEASES_ENABLED)"
    if surface not in authorised_surfaces(config):
        return "door 2 open, but no founder sentence for this surface yet (PAIR_RELEASE_SURFACES)"
    if not (getattr(config, "R2_PAIR_RELEASE_BUCKET", "") or "").strip():
        return "no release bucket (R2_PAIR_RELEASE_BUCKET)"
    if not (getattr(config, "PAIR_RELEASE_SIGNING_KEY", "") or "").strip():
        return "no signing key (PAIR_RELEASE_SIGNING_KEY)"
    return None


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sign(manifest_sha256: str, key: str) -> str:
    """HMAC-SHA256 over the manifest's sha256 with the release key."""
    return hmac.new(key.encode("utf-8"), manifest_sha256.encode("utf-8"),
                    hashlib.sha256).hexdigest()


def verify(manifest_sha256: str, signature: str, key: str) -> bool:
    return hmac.compare_digest(sign(manifest_sha256, key), str(signature or ""))


def lines_for(pairs: list) -> list[dict]:
    """One JSONL record per pair: the two texts, the pattern, the model
    version, the split by owner and the consent the pair rests on. No
    user id, no coach id, no take: the owner is a stable split key only."""
    from services.dataset_releases import speaker_split
    out = []
    for pair in pairs:
        if not isinstance(pair, dict):
            continue
        owner = str(pair.get("owner_principal_id") or "")
        split, _digest = speaker_split(owner) if owner else ("train", "")
        out.append({
            "pair_id": str(pair.get("id")),
            "surface": str(pair.get("surface")),
            "pattern_key": pair.get("pattern_key"),
            "draft": str(pair.get("draft_text") or ""),
            "final": str(pair.get("final_text") or ""),
            "final_kind": str(pair.get("final_kind") or "final"),
            "draft_model_version": pair.get("draft_model_version"),
            "split": split,
            "owner_split_key": hashlib.sha256(owner.encode("utf-8")).hexdigest()[:16] if owner else None,
            "consent_state": pair.get("consent_state"),
            "consent_policy_version": pair.get("consent_policy_version"),
            "recorded_at": str(pair.get("created_at") or ""),
        })
    return out


def manifest_for(*, surface: str, week_start: date, records: list[dict],
                 file_sha256: str, owners: list[str], now: datetime,
                 storage_key: str) -> dict:
    splits: dict[str, int] = {"train": 0, "validation": 0, "test": 0}
    policies: set[str] = set()
    for record in records:
        splits[record["split"]] = splits.get(record["split"], 0) + 1
        if record.get("consent_policy_version"):
            policies.add(str(record["consent_policy_version"]))
    return {
        "release_version": RELEASE_VERSION,
        "surface": surface,
        "week_start": week_start.isoformat(),
        "exported_at": now.isoformat(),
        "item_count": len(records),
        "file_sha256": file_sha256,
        "storage_key": storage_key,
        "split_counts": splits,
        "split_strategy": "speaker-sha256-80-10-10-v1",
        "consent_policy_versions": sorted(policies),
        "owners_sha256": sha256_text("\n".join(sorted(set(owners)))),
        "owner_count": len(set(owners)),
    }


def storage_key_for(surface: str, week_start: date) -> str:
    return f"{KEY_PREFIX}{surface}/{week_start.isoformat()}/pairs.jsonl"


def export_surface(database: Any, storage: Any, *, surface: str,
                   week_start: date, config: Any,
                   now: Optional[datetime] = None) -> dict:
    """Export one surface for one week. Returns the job's row for it:
    {surface, exported, waiting, why|release_id, manifest_sha256}."""
    now = now or datetime.now(timezone.utc)
    reason = why_not(config, surface)
    pairs = database.list_releasable_pairs(surface)
    waiting = len(pairs)
    if reason:
        return {"surface": surface, "exported": 0, "waiting": waiting, "why": reason}
    if not pairs:
        return {"surface": surface, "exported": 0, "waiting": 0, "why": "nothing releasable waiting"}
    records = lines_for(pairs)
    body = "\n".join(_json(r) for r in records) + "\n"
    file_sha = sha256_text(body)
    owners = [str(p.get("owner_principal_id")) for p in pairs if p.get("owner_principal_id")]
    key = storage_key_for(surface, week_start)
    bucket = str(getattr(config, "R2_PAIR_RELEASE_BUCKET")).strip()
    manifest = manifest_for(surface=surface, week_start=week_start, records=records,
                            file_sha256=file_sha, owners=owners, now=now, storage_key=key)
    manifest_sha = sha256_text(_json(manifest))
    signature = sign(manifest_sha, str(getattr(config, "PAIR_RELEASE_SIGNING_KEY")))
    key_id = str(getattr(config, "PAIR_RELEASE_SIGNING_KEY_ID", "pair-release-key-1"))
    manifest_body = _json({**manifest, "manifest_sha256": manifest_sha,
                           "signature": signature, "signing_key_id": key_id})
    # The file first, then its manifest beside it, then the ledger: a crash
    # between leaves an object with no row, which the next week overwrites
    # (same key), never a row with no object.
    storage.put(bucket, key, body.encode("utf-8"), "application/x-ndjson")
    storage.put(bucket, key.replace("pairs.jsonl", "manifest.json"),
                manifest_body.encode("utf-8"), "application/json")
    release = database.insert_pair_release(
        release_version=RELEASE_VERSION, surface=surface,
        week_start=week_start.isoformat(), item_count=len(records),
        storage_bucket=bucket, storage_key=key, manifest=manifest,
        manifest_sha256=manifest_sha, file_sha256=file_sha,
        signature=signature, signing_key_id=key_id)
    release_id = str((release or {}).get("id") or "")
    database.insert_pair_release_owners(release_id, owners)
    marked = database.mark_feedback_pairs_released(release_id, [str(p["id"]) for p in pairs])
    return {"surface": surface, "exported": int(marked), "waiting": 0,
            "release_id": release_id, "manifest_sha256": manifest_sha}


def sweep_voided(database: Any, storage: Any) -> dict:
    """Delete the objects of voided releases (an owner withdrew) and mark
    them purged. Runs every week whatever the door says: revocation is
    honoured even where nothing new leaves."""
    lister = getattr(database, "list_voided_unpurged_pair_releases", None)
    if lister is None:
        return {"purged": 0, "unavailable": "no release ledger on this database"}
    try:
        due = lister() or []
    except Exception as e:  # noqa: BLE001 -- named, never a silent zero
        _log.warning("voided release read failed: %s", e, exc_info=True)
        return {"purged": 0, "unavailable": str(e)[:200]}
    purged = 0
    failed: list[str] = []
    for release in due:
        if not isinstance(release, dict):
            continue
        rid = str(release.get("id") or "")
        bucket = str(release.get("storage_bucket") or "")
        key = str(release.get("storage_key") or "")
        try:
            storage.delete(bucket, key)
            storage.delete(bucket, key.replace("pairs.jsonl", "manifest.json"))
            database.mark_pair_release_purged(rid)
            purged += 1
        except Exception as e:  # noqa: BLE001 -- the next sweep retries; the row stays voided
            _log.warning("voided release %s not purged: %s", rid, e, exc_info=True)
            failed.append(rid)
    return {"purged": purged, "failed": failed}


class R2ReleaseStorage:
    """The release bucket's two verbs, on the shared R2 client."""

    def __init__(self, config: Any):
        self._config = config
        self._client = None

    def client(self) -> Any:
        if self._client is None:
            from services.r2_client import build_r2_client
            self._client = build_r2_client(self._config)
        return self._client

    def put(self, bucket: str, key: str, body: bytes, content_type: str) -> None:
        self.client().put_object(Bucket=bucket, Key=key, Body=body, ContentType=content_type)

    def delete(self, bucket: str, key: str) -> None:
        self.client().delete_object(Bucket=bucket, Key=key)
