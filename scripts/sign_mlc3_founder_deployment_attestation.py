#!/usr/bin/env python3
"""Sign a canary-readiness evidence manifest with the operator key.

The unsigned input may be the deployment/monitor/rollback attestation or the
R2 rehearsal output containing its already signed Cloudflare control-plane
export. This command does not query or mutate any provider. It produces
provenance only; the readiness checker still validates every field and keeps
all gates disabled.
"""
from __future__ import annotations

import argparse
import base64
import json
from hashlib import sha256
from pathlib import Path
import sys

from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.mlc3_founder_canary_readiness import (  # noqa: E402
    TRUSTED_ATTESTATION_ISSUER,
    TRUSTED_ATTESTATION_KEY_ID,
)


def _canonical(value: dict) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def sign_manifest(unsigned: dict, private_key_pem: bytes) -> dict:
    if "signature_ed25519_base64" in unsigned:
        raise ValueError("input manifest is already signed")
    payload = {
        **unsigned,
        "issuer": TRUSTED_ATTESTATION_ISSUER,
        "key_id": TRUSTED_ATTESTATION_KEY_ID,
    }
    payload.pop("evidence_sha256", None)
    payload["evidence_sha256"] = sha256(_canonical(payload)).hexdigest()
    private_key = load_pem_private_key(private_key_pem, password=None)
    if not isinstance(private_key, Ed25519PrivateKey):
        raise ValueError("operator key must be Ed25519")
    signature = private_key.sign(_canonical(payload))
    return {
        **payload,
        "signature_ed25519_base64": base64.b64encode(signature).decode(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--private-key-file", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    unsigned = json.loads(Path(args.input).read_text())
    if not isinstance(unsigned, dict):
        raise ValueError("input manifest must be a JSON object")
    signed = sign_manifest(unsigned, Path(args.private_key_file).read_bytes())
    Path(args.output).write_text(
        json.dumps(signed, indent=2, sort_keys=True) + "\n",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
