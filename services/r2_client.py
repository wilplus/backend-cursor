"""Shared Cloudflare R2 (S3 API) client construction (audit C.7 dedup).

``services.coach_video_storage`` and ``services.user_media_storage`` both
read the same ``R2_ACCOUNT_ID`` / ``R2_ACCESS_KEY_ID`` / ``R2_SECRET_ACCESS_KEY``
credentials and built an identical boto3 client from them. Each module keeps
its own lazy-cached client instance (unchanged) and only the construction
call is shared here.
"""
from __future__ import annotations

from typing import Any


def build_r2_client(config: Any) -> Any:
    import boto3
    from botocore.config import Config as BotoConfig

    account = (config.R2_ACCOUNT_ID or "").strip()
    return boto3.client(
        "s3",
        endpoint_url=f"https://{account}.r2.cloudflarestorage.com",
        aws_access_key_id=(config.R2_ACCESS_KEY_ID or "").strip(),
        aws_secret_access_key=(config.R2_SECRET_ACCESS_KEY or "").strip(),
        config=BotoConfig(signature_version="s3v4"),
        region_name="auto",
    )


def clamp_ttl(expires_in: int) -> int:
    return max(60, min(int(expires_in), 604800))
