#!/usr/bin/env python3
"""Write/read/delete synthetic bytes in both exact MLC-3 production buckets.

This command never reads user content. It uses unique keys under the fixed
``mlc3-founder-readiness/`` prefix and attempts cleanup for both keys on every
exit path. It prints a checksum-bound JSON manifest only after both deletions
are independently confirmed.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import secrets
import sys
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Config  # noqa: E402
from services.mlc3_founder_canary_readiness import (  # noqa: E402
    R2_EVIDENCE_VERSION,
    TRUSTED_ATTESTATION_ISSUER,
    TRUSTED_ATTESTATION_KEY_ID,
    evidence_manifest_sha256,
    validate_cloudflare_r2_privacy_export,
)

_CONFIRMATION = "write-read-delete-synthetic-r2-objects"
_TRUSTED_PUBLIC_KEY = (
    ROOT / "config" / "mlc3_founder_attestation_public_key.pem"
)


def _canonical_sha256(value: object) -> str:
    return sha256(json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")).hexdigest()


def _load_private_bucket_export(
    path: str, *, account: str, practice: str, coach: str,
) -> dict:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict) or not validate_cloudflare_r2_privacy_export(
        value, account_id=account, practice_bucket=practice,
        coach_video_bucket=coach,
        trusted_public_key_pem=_TRUSTED_PUBLIC_KEY.read_bytes(),
        trusted_issuer=TRUSTED_ATTESTATION_ISSUER,
        trusted_key_id=TRUSTED_ATTESTATION_KEY_ID,
    ):
        raise SystemExit("R2_CONTROL_PLANE_SIGNATURE_OR_PRIVACY_INVALID")
    return value


def _client():
    import boto3
    from botocore.config import Config as BotoConfig

    return boto3.client(
        "s3",
        endpoint_url=(
            f"https://{Config.R2_ACCOUNT_ID.strip()}"
            ".r2.cloudflarestorage.com"
        ),
        aws_access_key_id=Config.R2_ACCESS_KEY_ID.strip(),
        aws_secret_access_key=Config.R2_SECRET_ACCESS_KEY.strip(),
        config=BotoConfig(signature_version="s3v4"),
        region_name="auto",
    )


def _confirm_absent(client, bucket: str, key: str) -> bool:
    from botocore.exceptions import ClientError

    try:
        client.head_object(Bucket=bucket, Key=key)
    except ClientError as error:
        code = str(error.response.get("Error", {}).get("Code", ""))
        return code in {"404", "NoSuchKey", "NotFound"}
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm", required=True)
    parser.add_argument("--cloudflare-control-plane-export", required=True)
    args = parser.parse_args(argv)
    if args.confirm != _CONFIRMATION:
        raise SystemExit("R2_REHEARSAL_EXPLICIT_CONFIRMATION_REQUIRED")

    account = (Config.R2_ACCOUNT_ID or "").strip()
    practice = (Config.R2_USER_MEDIA_BUCKET or "").strip()
    coach = (Config.R2_BUCKET_NAME or "").strip()
    if not all((account, Config.R2_ACCESS_KEY_ID, Config.R2_SECRET_ACCESS_KEY,
                practice, coach)):
        raise SystemExit("R2_REHEARSAL_CONFIGURATION_INCOMPLETE")
    if practice == coach:
        raise SystemExit("R2_REHEARSAL_BUCKETS_MUST_BE_DISTINCT")
    control_plane = _load_private_bucket_export(
        args.cloudflare_control_plane_export,
        account=account, practice=practice, coach=coach,
    )

    client = _client()
    run_id = str(uuid4())
    body = secrets.token_bytes(64)
    body_sha = sha256(body).hexdigest()
    targets = (
        ("practice_audio", practice),
        ("coach_video", coach),
    )
    keys = {
        role: f"mlc3-founder-readiness/{run_id}/{role}.bin"
        for role, _ in targets
    }
    results: list[dict] = []
    cleanup: dict[str, bool] = {}
    try:
        for role, bucket in targets:
            key = keys[role]
            client.put_object(
                Bucket=bucket, Key=key, Body=body,
                ContentType="application/octet-stream",
            )
            response = client.get_object(Bucket=bucket, Key=key)
            read_body = response["Body"].read()
            read_sha = sha256(read_body).hexdigest()
            if read_body != body:
                raise RuntimeError("R2_REHEARSAL_READ_MISMATCH")
            results.append({
                "role": role,
                "bucket": bucket,
                "byte_size": len(body),
                "object_key_sha256": sha256(key.encode()).hexdigest(),
                "object_key_prefix": "mlc3-founder-readiness/",
                "write_sha256": body_sha,
                "read_sha256": read_sha,
                "write_verified": True,
                "read_verified": True,
                "deletion_verified": False,
            })
    finally:
        for role, bucket in targets:
            key = keys[role]
            try:
                client.delete_object(Bucket=bucket, Key=key)
                cleanup[role] = _confirm_absent(client, bucket, key)
            except Exception:
                cleanup[role] = False

    if len(results) != 2 or not all(cleanup.values()):
        unresolved = [
            {"role": role, "bucket": bucket, "object_key": keys[role]}
            for role, bucket in targets if not cleanup.get(role, False)
        ]
        print(json.dumps({
            "error": "R2_REHEARSAL_CLEANUP_NOT_VERIFIED",
            "unresolved_synthetic_objects": unresolved,
        }, sort_keys=True), file=sys.stderr)
        raise SystemExit("R2_REHEARSAL_CLEANUP_NOT_VERIFIED")
    for result in results:
        result["deletion_verified"] = cleanup[result["role"]]
    manifest = {
        "contract_version": R2_EVIDENCE_VERSION,
        "environment": "production",
        "endpoint": f"https://{account}.r2.cloudflarestorage.com",
        "account_id_sha256": sha256(account.encode()).hexdigest(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "cloudflare_authenticated_provider_export": control_plane,
        "cloudflare_provider_export_sha256": _canonical_sha256(control_plane),
        "results": results,
    }
    manifest["evidence_sha256"] = evidence_manifest_sha256(manifest)
    print(json.dumps(manifest, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
