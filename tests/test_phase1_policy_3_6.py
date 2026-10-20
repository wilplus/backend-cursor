"""
STORY    As a speaker, I want the 3.6 terms I accept to be the legal pack's files
         exactly, checked by their fingerprints, so that I can later prove what
         I agreed to.
OUTCOME
  O1  The terms, privacy, AI notice and agreement text in the publish script
      equal the legal pack's files byte for byte, and the terms' and privacy
      fingerprints (hashes) are checked by the script.
  O2  The United States is added to the countries, and the registered
      training sentence is the v4 one.
PROVES   O1 -> test_the_copy_is_the_legal_pack_byte_for_byte_and_its_hash_is_checked
         O2 -> test_the_united_states_and_the_v4_sentence
WHY      Founder 2026-10-15, N72 and N73.
"""
from __future__ import annotations

import hashlib
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACK = ROOT / "legal" / "phase1-2026.1"
SCRIPT = (PACK / "PUBLISH-3.6-2026-10-15.sql").read_text(encoding="utf-8")


def _block(tag: str) -> str:
    match = re.search(rf"\${tag}\$(.*?)\${tag}\$", SCRIPT, re.S)
    assert match, f"no ${tag}$ block"
    return match.group(1)


def test_the_copy_is_the_legal_pack_byte_for_byte_and_its_hash_is_checked():
    for tag, name in (("terms", "terms-3.6.txt"), ("privacy", "privacy-3.6.txt"),
                      ("notice", "ai-notice-3.2.txt"), ("agree", "agreement-3.1.txt")):
        text = (PACK / "copy" / name).read_text(encoding="utf-8")
        assert _block(tag) == text, name
    for name in ("terms-3.6.txt", "privacy-3.6.txt"):
        digest = hashlib.sha256((PACK / "copy" / name).read_bytes()).hexdigest()
        assert SCRIPT.count(digest) >= 2, name  # the last guard and the check


def test_the_united_states_and_the_v4_sentence():
    assert "'gr','us')" in SCRIPT
    sentence = "We'd train our feedback on your practice."
    assert hashlib.sha256(sentence.encode()).hexdigest() in SCRIPT
    assert "'We''d train our feedback on your practice.'" in SCRIPT
    assert "<SIGNED_PDF_SHA256_OF_27>" in SCRIPT or "training-consent-wording-v4.pdf" in SCRIPT
