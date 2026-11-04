"""
STORY    As a speaker, I want the 3.12 privacy policy I accept to be the text
         the founder signed, word for word, with the terms and the training
         wording left alone, so that I can later prove what I agreed to.
OUTCOME
  O1  The privacy (3.12), terms (3.10), AI notice and agreement text in the
      publish script equal the legal pack's files byte for byte; the privacy
      file is the signed record's text with only the date filled in; and the
      terms' and privacy fingerprints (hashes) are checked by the script.
  O2  It publishes version 3.12 over 3.11 with Terms 3.10 unchanged, keeps
      the United States, does not replace the training wording, and deletes
      nothing.
PROVES   O1 -> test_the_copy_is_the_signed_text_byte_for_byte_and_its_hash_is_checked
         O2 -> test_it_publishes_3_12_over_3_11_and_deletes_nothing
WHY      Founder 2026-11-04, N482 (signed: sending a Take is the speaker's
         own message, not special category; Terms 3.10 stays; no untick for
         future Takes); for N479 item 1.
"""
from __future__ import annotations

import hashlib
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACK = ROOT / "legal" / "phase1-2026.1"
SCRIPT = (PACK / "PUBLISH-3.12-2026-11-04.sql").read_text(encoding="utf-8")
SIGNED = (PACK / "33-privacy-3.12-sending-a-take-to-the-people-you-chat-with-SIGNED-2026-11-04.md").read_text(encoding="utf-8")


def _block(tag: str) -> str:
    match = re.search(rf"\${tag}\$(.*?)\${tag}\$", SCRIPT, re.S)
    assert match, f"no ${tag}$ block"
    return match.group(1)


def test_the_copy_is_the_signed_text_byte_for_byte_and_its_hash_is_checked():
    text = re.search(r"## 6\. Privacy Policy 3\.12, as signed\n\n```text\n(.*?)\n```", SIGNED, re.S).group(1)
    dated = text.replace("Effective {publication date}.", "Effective 4 November 2026.")
    assert (PACK / "copy" / "privacy-3.12.txt").read_text(encoding="utf-8") == dated
    for tag, name in (("terms", "terms-3.10.txt"), ("privacy", "privacy-3.12.txt"),
                      ("notice", "ai-notice-3.2.txt"), ("agree", "agreement-3.1.txt")):
        assert _block(tag) == (PACK / "copy" / name).read_text(encoding="utf-8"), name
    for name in ("terms-3.10.txt", "privacy-3.12.txt"):
        digest = hashlib.sha256((PACK / "copy" / name).read_bytes()).hexdigest()
        assert SCRIPT.count(digest) >= 2, name  # the last guard and the check


def test_it_publishes_3_12_over_3_11_and_deletes_nothing():
    assert "'version','phase1-2026-11-04-3.12'" in SCRIPT
    assert "'terms_version','terms-3.10-2026-11-04'" in SCRIPT
    assert "'privacy_version','privacy-3.12-2026-11-04'" in SCRIPT
    assert "IS DISTINCT FROM 'phase1-2026-11-04-3.11' THEN" in SCRIPT
    body = SCRIPT[SCRIPT.index("BEGIN;"):SCRIPT.index("COMMIT;")]
    assert "DELETE FROM" not in body and "UPDATE public." not in body
    assert "supersede_mlc2_training_consent_policy_v1" not in SCRIPT
    assert "'gr','us')" in SCRIPT
