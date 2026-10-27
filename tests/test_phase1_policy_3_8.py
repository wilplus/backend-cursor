"""
STORY    As a speaker, I want the 3.8 terms I accept to be the legal pack's files
         exactly, with the training wording left alone, so that I can later
         prove what I agreed to.
OUTCOME
  O1  The terms (3.7), privacy (3.8), AI notice and agreement text in the
      publish script equal the legal pack's files byte for byte, and the
      terms' and privacy fingerprints (hashes) are checked by the script.
  O2  It publishes version 3.8 over 3.7, keeps the United States, and does
      not replace the training wording.
PROVES   O1 -> test_the_copy_is_the_legal_pack_byte_for_byte_and_its_hash_is_checked
         O2 -> test_it_publishes_3_8_over_3_7_and_leaves_the_training_wording_alone
WHY      Founder 2026-10-27, N208 (signed "as drafted, question 1 A,
         question 2 A").
"""
from __future__ import annotations

import hashlib
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACK = ROOT / "legal" / "phase1-2026.1"
SCRIPT = (PACK / "PUBLISH-3.8-2026-10-27.sql").read_text(encoding="utf-8")


def _block(tag: str) -> str:
    match = re.search(rf"\${tag}\$(.*?)\${tag}\$", SCRIPT, re.S)
    assert match, f"no ${tag}$ block"
    return match.group(1)


def test_the_copy_is_the_legal_pack_byte_for_byte_and_its_hash_is_checked():
    for tag, name in (("terms", "terms-3.7.txt"), ("privacy", "privacy-3.8.txt"),
                      ("notice", "ai-notice-3.2.txt"), ("agree", "agreement-3.1.txt")):
        assert _block(tag) == (PACK / "copy" / name).read_text(encoding="utf-8"), name
    for name in ("terms-3.7.txt", "privacy-3.8.txt"):
        digest = hashlib.sha256((PACK / "copy" / name).read_bytes()).hexdigest()
        assert SCRIPT.count(digest) >= 2, name  # the last guard and the check


def test_it_publishes_3_8_over_3_7_and_leaves_the_training_wording_alone():
    assert "'version','phase1-2026-10-27-3.8'" in SCRIPT
    assert "'terms_version','terms-3.7-2026-10-27'" in SCRIPT
    assert "'privacy_version','privacy-3.8-2026-10-27'" in SCRIPT
    assert "IS DISTINCT FROM 'phase1-2026-10-15-3.7' THEN" in SCRIPT
    assert "supersede_mlc2_training_consent_policy_v1" not in SCRIPT
    assert "'gr','us')" in SCRIPT
