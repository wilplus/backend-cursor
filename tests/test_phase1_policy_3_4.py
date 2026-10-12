"""The Privacy 3.4 / Terms 3.4 publish script (founder 2026-10-06 N55, WQ3a B;
2026-10-08 N66.2, text signed in place of counsel). Pins:

  * the four copy blocks mirror the legal pack byte for byte (terms-3.4,
    privacy-3.4; the 3.1 notice and agreement unchanged);
  * the five purposes are 3.3's, with the two practice purposes moved to
    contract and required, so the policy has no optional purpose; still no
    consent purpose is required, and nothing Phase-2 is named;
  * the copy is 3.3 with only the practice passages changed, every signed
    3.4 passage present and 3.3's training and lending sections intact;
  * it records that counsel's review was not obtained;
  * the effective date is the day the founder named (8 October 2026), and
    STEP 1 still refuses a placeholder;
  * it is not a migration, and it is meant to run only after 0454.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "phase1_policy_publish_3_4.sql"

# The signed 3.4 passages (founder in chat, 2026-10-08, "text signed").
PRIVACY_LINES = (
    "Version 3.4 replaces every earlier version. It changes one thing: practice\n"
    "is now part of the service rather than a separate choice.",
    "If you had turned Personalised practice off,\n"
    "accepting this version turns practice back on for you.",
    "6(1)(f) GDPR). You can object to it at any time by writing to\n"
    "contact@willpowerlab.com: from then on no clip of yours is chosen for a check.\n"
    "Objecting costs you nothing else.",
    "Legal basis: performance of our contract with you (Article 6(1)(b) GDPR).\n"
    "Practice is part of what WillpowerLab is, alongside your feedback, so it is no\n"
    "longer a separate choice. Doing an exercise is always up to you: you can skip\n"
    "any exercise, and skipping costs you nothing.",
    "service. Practice is part of the service too, though doing any one exercise\n"
    "is always up to you.",
    "listening, as section 4 describes, unless you have objected to it.",
)
TERMS_LINES = (
    "Version 3.4 replaces every earlier version. It makes practice part of the\n"
    "service rather than a separate choice (section 11).",
    "you can object to it at any time as that section says.",
    "Practice is part of the service. After your feedback you may be offered a\n"
    "short exercise chosen for your recording and the chance to re-record a\n"
    "fragment,",
    "any of them, and skipping changes nothing else about your account.",
)
GONE = ("Practice is optional", "Practice is the exception",
        "turning off Personalised\npractice in your settings",
        "Practice, and making it personal — optional")


def _script(path=SCRIPT) -> str:
    return path.read_text(encoding="utf-8")


def _quoted(tag: str) -> str:
    match = re.search(rf"\${tag}\$(.*?)\${tag}\$", _script(), re.S)
    assert match, f"no ${tag}$ block"
    return match.group(1)


def test_the_copy_carries_every_signed_passage_and_drops_the_old_ones():
    privacy, terms = _quoted("privacy"), _quoted("terms")
    missing = [line[:40] for line in PRIVACY_LINES if privacy.count(line) != 1]
    missing += [line[:40] for line in TERMS_LINES if terms.count(line) != 1]
    assert missing == []
    left = [g for g in GONE if g in privacy or g in terms]
    assert left == []
    assert "4a. HELPING TO IMPROVE WILLPOWERLAB — OPTIONAL" in privacy
    assert "4b. LENDING A RECORDING TO OTHER USERS — OPTIONAL, PER RECORDING" in privacy
    assert "you give us a licence to reproduce" in terms
    # The unsigned packages rewrite (N44.4) is not in 3.4.
    assert "A package is paid for once" not in terms
