#!/usr/bin/env python3
"""Upload and register one immutable MLC-2 Product/legal approval artifact.

The script is intentionally separate from migrations: schema deployment must
not fabricate legal approval or user consent. It verifies the exact copy hash,
uses an immutable R2 key, reads the object back, then calls the service-only
configuration RPC. It never calls a consent grant RPC.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from config import Config  # noqa: E402
from services.db import db  # noqa: E402


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_artifact(path: Path) -> tuple[dict, bytes]:
    raw = path.read_bytes()
    artifact = json.loads(raw.decode("utf-8"))
    if not isinstance(artifact, dict):
        raise ValueError("approval artifact must be a JSON object")
    copy = str(artifact.get("onboarding_copy") or "")
    expected_copy_hash = str(artifact.get("approved_copy_sha256") or "")
    if _sha256(copy.encode("utf-8")) != expected_copy_hash:
        raise ValueError("approved_copy_sha256 does not match onboarding_copy")
    if artifact.get("article_6_basis") != "6(1)(a)":
        raise ValueError("MLC-2 pooled training requires Article 6(1)(a)")
    if artifact.get("required_for_service") is not True \
       or artifact.get("bundled_ui") is not True \
       or artifact.get("checkbox_preselected") is not False:
        raise ValueError("bundled explicit-consent contract is invalid")
    return artifact, raw


def _r2_client():
    if not (
        Config.R2_ACCOUNT_ID
        and Config.R2_ACCESS_KEY_ID
        and Config.R2_SECRET_ACCESS_KEY
    ):
        raise RuntimeError("Cloudflare R2 credentials are not configured")
    import boto3

    return boto3.client(
        "s3",
        endpoint_url=(
            f"https://{Config.R2_ACCOUNT_ID}.r2.cloudflarestorage.com"
        ),
        aws_access_key_id=Config.R2_ACCESS_KEY_ID,
        aws_secret_access_key=Config.R2_SECRET_ACCESS_KEY,
        region_name="auto",
    )


def _upload_and_verify(*, bucket: str, key: str, raw: bytes) -> str:
    client = _r2_client()
    expected = _sha256(raw)
    try:
        response = client.get_object(Bucket=bucket, Key=key)
        existing = response["Body"].read()
        if _sha256(existing) != expected:
            raise RuntimeError(
                "immutable R2 approval key already contains different bytes"
            )
    except Exception as error:
        from botocore.exceptions import ClientError

        if not isinstance(error, ClientError) or str(
            error.response.get("Error", {}).get("Code", "")
        ) not in ("NoSuchKey", "404", "NotFound"):
            raise
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=raw,
            ContentType="application/json",
            Metadata={"sha256": expected},
        )
    verified = client.get_object(Bucket=bucket, Key=key)["Body"].read()
    if _sha256(verified) != expected:
        raise RuntimeError("R2 approval evidence failed read-back verification")
    return expected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--artifact",
        default=str(ROOT / "legal" / "mlc2-bundled-consent-v1.json"),
    )
    parser.add_argument(
        "--bucket",
        default=(Config.R2_BUCKET_NAME or Config.COACH_FEEDBACK_VIDEO_BUCKET),
    )
    args = parser.parse_args(argv)
    if not str(args.bucket or "").strip():
        raise RuntimeError("R2_BUCKET_NAME (or --bucket) is required")

    artifact, raw = _read_artifact(Path(args.artifact))
    evidence_sha = _upload_and_verify(
        bucket=str(args.bucket).strip(),
        key=str(artifact["r2_object_key"]),
        raw=raw,
    )
    response = db.client.rpc("configure_mlc2_consent_policy_v1", {
        "p_approval_reference": artifact["approval_reference"],
        "p_approved_copy_sha256": artifact["approved_copy_sha256"],
        "p_onboarding_copy": artifact["onboarding_copy"],
        "p_consent_policy_version": artifact["consent_policy_version"],
        "p_terms_version": artifact["terms_version"],
        "p_privacy_policy_version": artifact["privacy_policy_version"],
        "p_approving_authority": artifact["approving_authority"],
        "p_approved_at": artifact["approved_at"],
        "p_jurisdictions": artifact["jurisdictions"],
        "p_article_9_treatment": artifact["article_9_treatment"],
        "p_evidence_object_key": artifact["r2_object_key"],
        "p_evidence_sha256": evidence_sha,
        "p_active_from": artifact["active_from"],
    }).execute()
    result = response.data
    if isinstance(result, list) and result:
        result = result[0]
    print(json.dumps({
        "configured": True,
        "policy": result,
        "evidence_object_key": artifact["r2_object_key"],
        "evidence_sha256": evidence_sha,
    }, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
