"""
STORY    As a speaker, I want the 3.9 terms I accept to be the texts the
         founder signed, word for word, with the training wording left alone,
         and the feelings I gave before them deleted, so that I can later prove
         what I agreed to.
OUTCOME
  O1  The terms (3.8), privacy (3.9), AI notice and agreement text in the
      publish script equal the legal pack's files byte for byte; those files
      are the signed record's texts with only the date filled in; and the
      terms' and privacy fingerprints (hashes) are checked by the script.
  O2  It publishes version 3.9 over 3.8, keeps the United States, does not
      replace the training wording, and deletes the feelings given before it.
PROVES   O1 -> test_the_copy_is_the_signed_text_byte_for_byte_and_its_hash_is_checked
         O2 -> test_it_publishes_3_9_over_3_8_and_deletes_the_feelings_before_it
WHY      Founder 2026-10-27, N217 (signed "as drafted, question 1 A,
         question 2 A"; counsel agrees); dated 28 October 2026.
"""
from __future__ import annotations

import hashlib
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACK = ROOT / "legal" / "phase1-2026.1"
SCRIPT = (PACK / "PUBLISH-3.9-2026-10-28.sql").read_text(encoding="utf-8")
SIGNED = (PACK / "30-terms-3.8-privacy-3.9-the-plan-feelings-and-whatsapp-sign-in-SIGNED-2026-10-27.md").read_text(encoding="utf-8")


def _block(tag: str) -> str:
    match = re.search(rf"\${tag}\$(.*?)\${tag}\$", SCRIPT, re.S)
    assert match, f"no ${tag}$ block"
    return match.group(1)


def test_the_copy_is_the_signed_text_byte_for_byte_and_its_hash_is_checked():
    for name, signed in (("terms-3.8.txt", "4. Terms of Service 3.8, as signed"),
                         ("privacy-3.9.txt", "5. Privacy Policy 3.9, as signed")):
        text = re.search(rf"## {re.escape(signed)}\n\n```text\n(.*?)\n```", SIGNED, re.S).group(1)
        dated = text.replace("Effective {publication date}.", "Effective 28 October 2026.")
        assert (PACK / "copy" / name).read_text(encoding="utf-8") == dated, name
    for tag, name in (("terms", "terms-3.8.txt"), ("privacy", "privacy-3.9.txt"),
                      ("notice", "ai-notice-3.2.txt"), ("agree", "agreement-3.1.txt")):
        assert _block(tag) == (PACK / "copy" / name).read_text(encoding="utf-8"), name
    for name in ("terms-3.8.txt", "privacy-3.9.txt"):
        digest = hashlib.sha256((PACK / "copy" / name).read_bytes()).hexdigest()
        assert SCRIPT.count(digest) >= 2, name  # the last guard and the check


def test_it_publishes_3_9_over_3_8_and_deletes_the_feelings_before_it():
    assert "'version','phase1-2026-10-28-3.9'" in SCRIPT
    assert "'terms_version','terms-3.8-2026-10-28'" in SCRIPT
    assert "'privacy_version','privacy-3.9-2026-10-28'" in SCRIPT
    assert "IS DISTINCT FROM 'phase1-2026-10-27-3.8' THEN" in SCRIPT
    body = SCRIPT[SCRIPT.index("BEGIN;"):SCRIPT.index("COMMIT;")]
    assert "DELETE FROM public.recording_feelings;" in body
    assert "- 'named_emotion'" in body
    assert "supersede_mlc2_training_consent_policy_v1" not in SCRIPT
    assert "'gr','us')" in SCRIPT
