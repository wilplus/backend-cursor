"""F4: delete the stored files behind the bundled-era corpus, and record each.

Founder, 2026-09-25 (5a/5b/5e). Files go first, rows after — the account
purge's order — so `apply_bundled_era_erasure_v1` refuses while any reference
in its snapshot has no recorded outcome. This module produces those outcomes.
It is run by hand (scripts/bundled_era_erasure_storage.py), previews by
default, and deletes only with --execute.

Every reference the snapshot lists is one of:

  r2          an ``s3://`` marker, a presigned GET, or a URL on one of our
              public bases — the key and bucket come from the ref itself;
  supabase    a Supabase Storage URL (``/storage/v1/object/…/<bucket>/<path>``)
              or a ``storage://<bucket>/<path>`` export URI;
  bare        a path with no scheme — checked in the Supabase bucket the
              plan names (``audio_recordings``), then the default R2 bucket;
  not_ours    a foreign URL, or a value that is not a storage reference at
              all (a column named ``*key*`` can hold an id).

Outcomes are ``deleted`` (it was there, it is verifiably gone), ``absent``
(verifiably not there in every place it could be) or ``not_ours``. A provider
or network error is never read as absence: it raises, and nothing is
recorded for that reference, so apply stays blocked on it.

The annotation exports (group B) are not in any table row; they are listed
from ``ANNOTATION_EXPORT_BUCKET/<prefix>/`` and handled the same way.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Optional

from services.coach_video_storage import (
    media_key_from_ref,
    media_ref_bucket,
    r2_bucket_name,
)

SUPABASE_AUDIO_BUCKET = "audio_recordings"
_SUPABASE_OBJECT = re.compile(
    r"/storage/v1/object/(?:public/|sign/|authenticated/)?([^/]+)/([^?#]+)"
)


@dataclass(frozen=True)
class Place:
    provider: str          # "r2" | "supabase"
    bucket: str
    key: str


@dataclass(frozen=True)
class Classified:
    kind: str              # "r2" | "supabase" | "bare" | "not_ours"
    places: tuple[Place, ...] = ()
    reason: str = ""


def classify(ref: str) -> Classified:
    raw = (ref or "").strip()
    if not raw:
        return Classified("not_ours", reason="empty")
    if raw.startswith("storage://"):
        bucket, _, key = raw[len("storage://"):].partition("/")
        if bucket and key:
            return Classified("supabase", (Place("supabase", bucket, key),))
        return Classified("not_ours", reason="malformed storage:// URI")
    lower = raw.lower()
    if lower.startswith(("http://", "https://")):
        supa = _SUPABASE_OBJECT.search(raw)
        if supa and ".supabase." in lower:
            return Classified("supabase", (Place("supabase", supa.group(1), supa.group(2)),))
        url_key = media_key_from_ref(raw)
        if not url_key:
            return Classified("not_ours", reason="foreign URL")
        return Classified("r2", (Place("r2", media_ref_bucket(raw) or r2_bucket_name(), url_key),))
    if raw.startswith("s3://"):
        marker_key = media_key_from_ref(raw)
        marker_bucket = raw[len("s3://"):].split("/", 1)[0]
        if marker_key and marker_bucket:
            return Classified("r2", (Place("r2", marker_bucket, marker_key),))
        return Classified("not_ours", reason="malformed s3:// marker")
    path = raw.lstrip("/")
    if "/" not in path and "." not in path:
        return Classified("not_ours", reason="not a storage reference")
    return Classified("bare", (
        Place("supabase", SUPABASE_AUDIO_BUCKET, path),
        Place("r2", r2_bucket_name(), path),
    ))


def _default_absent(place: Place) -> bool:
    from services.lab_audio_storage import verify_lab_audio_object_absent

    return verify_lab_audio_object_absent(
        place.key, bucket=place.bucket, storage_provider=place.provider)


def _default_delete(place: Place) -> None:
    if place.provider == "r2":
        from services.lab_audio_storage import _client

        _client().delete_object(Bucket=place.bucket, Key=place.key)
        return
    from services.db import db

    if db.client.storage.from_(place.bucket).remove([place.key]) is None:
        raise RuntimeError("storage provider did not acknowledge deletion")


def resolve(
    ref: str,
    *,
    execute: bool,
    is_absent: Callable[[Place], bool] = _default_absent,
    delete: Callable[[Place], None] = _default_delete,
) -> tuple[str, str]:
    """(outcome, detail) for one reference. Preview reports what it would do."""
    found = classify(ref)
    if found.kind == "not_ours":
        return "not_ours", found.reason
    present = [place for place in found.places if not is_absent(place)]
    if not present:
        checked = ", ".join(f"{p.provider}:{p.bucket}" for p in found.places)
        return "absent", f"checked {checked}"
    if not execute:
        return "would_delete", ", ".join(f"{p.provider}:{p.bucket}/{p.key}" for p in present)
    for place in present:
        delete(place)
        if not is_absent(place):
            raise RuntimeError(f"still present after delete: {place.provider}:{place.bucket}/{place.key}")
    return "deleted", ", ".join(f"{p.provider}:{p.bucket}" for p in present)


def annotation_export_refs(
    *, bucket: Optional[str], prefix: str, lister: Optional[Callable[[str, str], list]] = None,
) -> list[str]:
    """Every exported annotation file, as ``storage://bucket/prefix/name``."""
    if not bucket:
        return []
    if lister is None:
        from services.db import db

        def lister(b: str, p: str) -> list:
            return db.client.storage.from_(b).list(p, {"limit": 1000}) or []

    clean = prefix.strip().strip("/")
    return sorted(
        f"storage://{bucket}/{clean}/{item['name']}"
        for item in lister(bucket, clean)
        if isinstance(item, dict) and item.get("name")
    )


def run(
    database: Any, snapshot_id: str, *, execute: bool,
    export_refs: list[str],
    resolver: Callable[..., tuple[str, str]] = resolve,
) -> dict:
    """Resolve every reference of one snapshot, and the exports.

    With ``execute`` each outcome is recorded against the snapshot. A raise
    stops the run at that reference; what was recorded before it stays
    recorded, and a rerun picks up where it stopped (recording is idempotent).
    """
    refs = database.client.rpc(
        "bundled_era_erasure_storage_refs_v1", {"p_snapshot": snapshot_id},
    ).execute().data
    if not isinstance(refs, list):
        raise RuntimeError("BUNDLED_ERA_SNAPSHOT_REFS_UNAVAILABLE")
    tally: dict[str, int] = {}
    listed: list[dict] = []
    for ref in [str(r) for r in refs] + list(export_refs):
        outcome, detail = resolver(ref, execute=execute)
        tally[outcome] = tally.get(outcome, 0) + 1
        listed.append({"ref": ref, "outcome": outcome, "detail": detail})
        if execute:
            database.client.rpc("record_bundled_era_object_v1", {
                "p_snapshot": snapshot_id, "p_ref": ref,
                "p_outcome": outcome, "p_detail": detail,
            }).execute()
    return {"mode": "execute" if execute else "preview",
            "snapshot_id": snapshot_id, "tally": tally, "refs": listed}
