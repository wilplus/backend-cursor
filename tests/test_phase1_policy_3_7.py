"""The 3.7 publish script (founder 2026-10-15, N74). Pins what a speaker later
proves they agreed to: the four copy blocks are the legal pack's files byte
for byte (Privacy 3.7, the rest unchanged from 3.6), the guards check those
files' own hashes, and the training wording is left alone."""
from __future__ import annotations

import hashlib
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACK = ROOT / "legal" / "phase1-2026.1"
SCRIPT = (PACK / "PUBLISH-3.7-2026-10-15.sql").read_text(encoding="utf-8")


def _block(tag: str) -> str:
    match = re.search(rf"\${tag}\$(.*?)\${tag}\$", SCRIPT, re.S)
    assert match, f"no ${tag}$ block"
    return match.group(1)


def test_the_copy_is_the_legal_pack_byte_for_byte_and_its_hash_is_checked():
    for tag, name in (("terms", "terms-3.6.txt"), ("privacy", "privacy-3.7.txt"),
                      ("notice", "ai-notice-3.2.txt"), ("agree", "agreement-3.1.txt")):
        assert _block(tag) == (PACK / "copy" / name).read_text(encoding="utf-8"), name
    for name in ("terms-3.6.txt", "privacy-3.7.txt"):
        digest = hashlib.sha256((PACK / "copy" / name).read_bytes()).hexdigest()
        assert SCRIPT.count(digest) >= 2, name  # the last guard and the check


def test_it_publishes_3_7_and_leaves_the_training_wording_alone():
    assert "'version','phase1-2026-10-15-3.7'" in SCRIPT
    assert "'privacy_version','privacy-3.7-2026-10-15'" in SCRIPT
    assert "supersede_mlc2_training_consent_policy_v1" not in SCRIPT
    assert "'gr','us')" in SCRIPT
