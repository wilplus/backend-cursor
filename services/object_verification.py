"""Every download or release check appends a verification (MLC-2 F-8).

The foundation (0302) keeps each chain object's R2 coordinates and the
hash and size the bytes had when the Take was promoted
(``ml_object_artifacts``), and promises that every later download or
release check appends an ``ml_object_verifications`` row, never touching
the artifact. Until 2026-10-05 nothing wrote one. Migration 0431 adds the
writers; this module is their one caller:

  * ``note_download``: a job that downloaded a recording for its own use
    (today the dark training-corpus copy) hands over the bytes it read; if
    the key is a chain object, one row is appended. A key that is not a
    chain object writes nothing;
  * ``check_chain_objects``: the weekly job downloads a capped list of
    chain objects (never checked first, then the longest unchecked), only
    to hash them, and appends one row each;
  * ``read_back_exports`` / ``check_pair_releases``: door 2's file and its
    signed manifest are read back from the release bucket by the weekly
    job right after its export wrote them (read-after-write), and every
    week while the release stands; each read appends one
    ``pair_release_verifications`` row. A release spans many speakers, so
    it cannot be one chain object. The export path itself
    (``services/pair_release.py``) is unchanged: the checks run beside it.

The caller states only what it observed (the sha256 and byte count of the
bytes it read); the database compares them with the immutable record, so
no caller can declare an object verified. A chain-object row is a
canonical write, so it is written only while the confidence chain writes
(``MLC2_CONFIDENCE_CUTOVER_MODE`` and its one-way ring kill; F-1).

Nothing here keeps the bytes, and nothing reaches a speaker or a coach:
counts for the weekly row, ids of releases, never a key or a recording
(AC-9 is not in play).
"""
from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)

VERIFIER_VERSION = "mlc2-object-verifier-v1"
#: A job downloaded the object for its own use and hashed what it read.
DOWNLOAD = "download_sha256"
#: The weekly check downloaded the object only to hash it.
SCHEDULED = "scheduled_check_sha256"
#: Door 2 read its file and manifest back right after writing them.
READ_AFTER_WRITE = "read_after_write_sha256"
#: Chain objects downloaded per weekly run (the SQL caps the list at 100).
WEEKLY_OBJECT_LIMIT = 20
#: The fields of a release manifest object that are not the signed manifest.
_SIGNATURE_FIELDS = ("manifest_sha256", "signature", "signing_key_id")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def chain_writes_enabled() -> bool:
    """Whether a chain-object verification may be written: only while the
    chain itself writes. A failing read counts as no."""
    try:
        from services.take_lifecycle import confidence_canonical_writes_enabled
        return bool(confidence_canonical_writes_enabled())
    except Exception as error:  # noqa: BLE001 - fail closed, named
        _log.warning("confidence cutover read failed: %s", error, exc_info=True)
        return False


def note_download(database: Any, *, bucket: str, object_key: str,
                  data: Any, method: str = DOWNLOAD) -> Optional[dict]:
    """Append one verification for a chain object a job just downloaded.
    ``None`` when the key is no chain object, the chain is not writing, or
    the write failed. Never raises: a verification never fails the job
    that downloaded."""
    recorder = getattr(database, "record_mlc2_object_verification", None)
    if recorder is None or not isinstance(data, (bytes, bytearray)):
        return None
    if not chain_writes_enabled():
        return None
    try:
        return recorder(
            bucket=str(bucket or ""), object_key=str(object_key or ""),
            observed_sha256=_sha256(bytes(data)),
            observed_byte_size=len(data), verification_method=method,
            verifier_version=VERIFIER_VERSION)
    except Exception as error:  # noqa: BLE001 - named, never fails the download
        _log.warning("object verification not recorded: %s", error, exc_info=True)
        return None


def _r2_bytes(bucket: str, key: str) -> bytes:
    from services.lab_audio_storage import get_exact_storage_object_bytes
    return get_exact_storage_object_bytes(key, bucket=bucket, storage_provider="r2")


def check_chain_objects(database: Any, *,
                        fetch: Optional[Callable[[str, str], bytes]] = None,
                        limit: int = WEEKLY_OBJECT_LIMIT) -> dict:
    """The weekly check of chain objects. Counts only."""
    lister = getattr(database, "list_mlc2_objects_due_verification", None)
    if lister is None:
        return {"checked": 0, "unavailable": "no object list on this database"}
    if not chain_writes_enabled():
        return {"checked": 0,
                "why": "the confidence chain is not writing "
                       "(MLC2_CONFIDENCE_CUTOVER_MODE or its ring kill)"}
    try:
        due = lister(int(limit)) or []
    except Exception as error:  # noqa: BLE001 - named, never a silent zero
        _log.warning("object work list read failed: %s", error, exc_info=True)
        return {"checked": 0, "unavailable": str(error)[:200]}
    fetch = fetch or _r2_bytes
    out = {"checked": 0, "verified": 0, "mismatched": 0, "failed": 0}
    for row in due:
        if not isinstance(row, dict):
            continue
        bucket, key = str(row.get("bucket") or ""), str(row.get("object_key") or "")
        try:
            data = fetch(bucket, key)
        except Exception as error:  # noqa: BLE001 - counted; the next week retries
            _log.warning("chain object download failed: %s", error)
            out["failed"] += 1
            continue
        result = note_download(database, bucket=bucket, object_key=key,
                               data=data, method=SCHEDULED)
        if not isinstance(result, dict):
            out["failed"] += 1
            continue
        out["checked"] += 1
        out["verified" if result.get("verified") else "mismatched"] += 1
    return out


def manifest_reading(body: bytes, signing_key: str) -> tuple[str, bool]:
    """``(observed manifest sha256, signature valid)`` for a manifest object
    as door 2 writes it: the signed manifest plus its sha256, signature and
    key id. The sha256 is recomputed the way the export computed it."""
    from services.pair_release import _json, sha256_text, verify
    try:
        document = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return _sha256(body), False
    if not isinstance(document, dict):
        return _sha256(body), False
    stated = str(document.get("manifest_sha256") or "")
    signature = str(document.get("signature") or "")
    manifest = {k: v for k, v in document.items() if k not in _SIGNATURE_FIELDS}
    observed = sha256_text(_json(manifest))
    valid = bool(signing_key) and stated == observed and verify(
        observed, signature, signing_key)
    return observed, valid


def manifest_key(storage_key: str) -> str:
    return str(storage_key).replace("pairs.jsonl", "manifest.json")


def _read(storage: Any, bucket: str, key: str) -> bytes:
    """One object's bytes from the release bucket: the storage's own ``get``
    when it has one, else its R2 client (``R2ReleaseStorage.client()``)."""
    getter = getattr(storage, "get", None)
    if callable(getter):
        return getter(bucket, key)
    return storage.client().get_object(Bucket=bucket, Key=key)["Body"].read()


def check_release(database: Any, storage: Any, release: dict, *,
                  signing_key: str, method: str) -> dict:
    """Read one release's file and manifest back, hash both, check the
    manifest's signature, and append one row for each. Raises on a failed
    read or write; the callers name it."""
    release_id = str(release.get("id") or "")
    bucket = str(release.get("storage_bucket") or "")
    key = str(release.get("storage_key") or "")
    body = _read(storage, bucket, key)
    file_row = database.record_pair_release_verification(
        release_id=release_id, object_role="file", observed_sha256=_sha256(body),
        observed_byte_size=len(body), signature_valid=None,
        verification_method=method, verifier_version=VERIFIER_VERSION) or {}
    manifest = _read(storage, bucket, manifest_key(key))
    observed, signature_valid = manifest_reading(manifest, signing_key)
    manifest_row = database.record_pair_release_verification(
        release_id=release_id, object_role="manifest", observed_sha256=observed,
        observed_byte_size=len(manifest), signature_valid=signature_valid,
        verification_method=method, verifier_version=VERIFIER_VERSION) or {}
    return {"release_id": release_id,
            "file_verified": bool(file_row.get("verified")),
            "manifest_verified": bool(manifest_row.get("verified"))}


def read_back_exports(database: Any, storage: Any, config: Any,
                      exported: list) -> set[str]:
    """The read-after-write check of the releases the weekly export just
    wrote: each row of ``exported`` that names a release gains ``verified``
    (True or False as the database judged both objects, None when the check
    could not run). Returns the ids checked. Never raises: the releases
    already stand, and the weekly check reads them again next week."""
    key = str(getattr(config, "PAIR_RELEASE_SIGNING_KEY", "") or "")
    checked: set[str] = set()
    rows = [row for row in (exported or [])
            if isinstance(row, dict) and row.get("release_id")]
    if not rows:
        return checked
    try:
        # Where each release lives, from the ledger the weekly check reads.
        standing = {str(r.get("id")): r for r in (database.list_live_pair_releases() or [])
                    if isinstance(r, dict)}
    except Exception as error:  # noqa: BLE001 - named; next week reads them again
        _log.warning("release ledger read failed: %s", error, exc_info=True)
        standing = {}
    for row in rows:
        release_id = str(row["release_id"])
        try:
            result = check_release(database, storage, standing[release_id],
                                   signing_key=key, method=READ_AFTER_WRITE)
        except Exception as error:  # noqa: BLE001 - named; next week reads it again
            _log.warning("release %s read-back failed: %s", release_id, error,
                         exc_info=True)
            row["verified"] = None
            continue
        checked.add(release_id)
        row["verified"] = bool(result["file_verified"] and result["manifest_verified"])
    return checked


def check_pair_releases(database: Any, storage: Any, config: Any, *,
                        skip: frozenset[str] | set[str] = frozenset()) -> dict:
    """The weekly check of every standing door 2 release, whatever the door
    says now: a release that left is checked for as long as it stands.
    ``skip`` names releases this run already read back."""
    lister = getattr(database, "list_live_pair_releases", None)
    if lister is None:
        return {"checked": 0, "unavailable": "no release ledger on this database"}
    try:
        releases = lister() or []
    except Exception as error:  # noqa: BLE001 - named, never a silent zero
        _log.warning("release list read failed: %s", error, exc_info=True)
        return {"checked": 0, "unavailable": str(error)[:200]}
    key = str(getattr(config, "PAIR_RELEASE_SIGNING_KEY", "") or "")
    out: dict = {"checked": 0, "verified": 0, "mismatched": [], "failed": []}
    for release in releases:
        if not isinstance(release, dict):
            continue
        release_id = str(release.get("id") or "")
        if release_id in skip:
            continue
        try:
            result = check_release(database, storage, release, signing_key=key,
                                   method=SCHEDULED)
        except Exception as error:  # noqa: BLE001 - named; the next week retries
            _log.warning("release %s not checked: %s", release_id, error, exc_info=True)
            out["failed"].append(release_id)
            continue
        out["checked"] += 1
        if result["file_verified"] and result["manifest_verified"]:
            out["verified"] += 1
        else:
            out["mismatched"].append(release_id)
    return out
