"""The Privacy 3.3 / Terms 3.3 publish script (gate 6a and Phases 4 and 5;
founder 2026-10-02, N24). Pins what made the 3.2 publish safe, for this one:

  * the four copy blocks mirror the legal pack byte for byte (terms-3.3,
    privacy-3.3; the 3.1 notice and agreement unchanged);
  * the five purposes are exactly the 3.2 script's — neither the blind check
    nor the lending yes is a Phase-1 purpose; no consent purpose is required,
    no required purpose is on consent;
  * the copy is the 3.2 copy plus the signed lines of 15 §1 and 16 §1, every
    one of them present, and 3.2's training section intact;
  * the effective-date placeholder is still there, STEP 1 refuses to register
    while it is, and the day is set in the copy files and the script together;
  * it is not a migration, and its version id is the one the share switch
    will be gated on.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "phase1_policy_publish_3_3.sql"
OLD = ROOT / "scripts" / "phase1_policy_publish_training_3_2.sql"
COPY = ROOT / "legal" / "phase1-2026.1" / "copy"
MIRRORED = {"terms": "terms-3.3.txt", "privacy": "privacy-3.3.txt",
            "notice": "ai-notice-3.1.txt", "agree": "agreement-3.1.txt"}

# The signed lines (15 §1, 16 §1), one anchor each, as they sit in the bytes.
PRIVACY_LINES = (
    "Other users never hear your voice unless you lend a particular recording to\n"
    "them yourself, as section 4b describes.",
    "To check that our automated listening is right: from time to time a\n"
    "WillpowerLab coach — a person — hears a short clip of a recording",
    "Legal basis: our legitimate interest in keeping the tool accurate (Article\n"
    "6(1)(f) GDPR). You can turn this off at any time by turning off Personalised\n"
    "practice in your settings",
    "4b. LENDING A RECORDING TO OTHER USERS — OPTIONAL, PER RECORDING",
    "Legal basis: your explicit consent (Article 9(2)(a) GDPR), given per\n"
    "recording by the switch itself.",
    "Your own answers as a listener: when you answer a question about someone\n"
    "else's clip, that answer is about their voice and it is also your own data.",
    "A coach may also hear a short clip of a recording to check our automated\n"
    "listening, as section 4 describes, unless you have turned Personalised\n"
    "practice off.",
    "Other users\nIf you lend a recording (section 4b), other WillpowerLab users hear that\n"
    "clip, without your name or your words. Nobody else does.",
    "A coach's answer in a blind check is deleted together with the recording it\n"
    "was about, and never kept after it.",
    "A recording you lent stops being heard by others the moment you turn the\n"
    "switch off, and is deleted with the recording like everything else.\n"
    "Your answers about other users' clips are kept while your account is open\n"
    "and deleted when you delete it.",
)
TERMS_LINES = (
    "If you turn on lending for a recording (Privacy Policy, section 4b), you\n"
    "give us permission to play a short clip of that recording to other users,",
    "A coach may also hear a short clip of a recording in order to check our\n"
    "automated listening, without being told what it found and without seeing\n"
    "who you are.",
    "Other users hear a recording of yours only if you lend it (Privacy Policy,\n"
    "section 4b); nothing in this section lends anything for you.",
)


def _script(path=SCRIPT) -> str:
    return path.read_text(encoding="utf-8")


def _quoted(tag: str) -> str:
    match = re.search(rf"\${tag}\$(.*?)\${tag}\$", _script(), re.S)
    assert match, f"no ${tag}$ block"
    return match.group(1)


def _purposes(path) -> str:
    body = _script(path)
    end = body.index("'founder:artur@willonski.com'\n) FROM c")
    start = body.rindex("jsonb_build_array(", 0, end)
    return re.sub(r"--[^\n]*", "", body[start:end])


def test_every_block_is_mirrored_byte_for_byte():
    bad = [name for tag, name in MIRRORED.items()
           if (COPY / name).read_text(encoding="utf-8") != _quoted(tag)]
    assert bad == []


def test_the_purposes_are_the_three_two_publish_s_purposes_unchanged():
    assert _purposes(SCRIPT) == _purposes(OLD)
    objects = _purposes(SCRIPT).split("jsonb_build_object(")[1:]
    assert len(objects) == 5
    for chunk in objects:
        consent = "'lawful_basis_code','consent'" in chunk
        required = "'required_for_core_service',true" in chunk
        assert consent != required, chunk[:80]
    assert "pooled_model_improvement" not in _purposes(SCRIPT)


def test_the_copy_carries_every_signed_line_and_keeps_three_two():
    privacy, terms = _quoted("privacy"), _quoted("terms")
    missing = [line[:40] for line in PRIVACY_LINES if privacy.count(line) != 1]
    missing += [line[:40] for line in TERMS_LINES if terms.count(line) != 1]
    assert missing == []
    # 3.2's training section and licence are untouched.
    assert "4a. HELPING TO IMPROVE WILLPOWERLAB — OPTIONAL" in privacy
    assert "you give us a licence to reproduce" in terms
    assert "Version 3.3." in privacy and "Version 3.3." in terms
    assert "Version 3.2" not in privacy and "Version 3.2" not in terms


def test_three_three_is_three_two_plus_additions_only():
    """Every line of 3.2 survives, in order: nothing was deleted or reworded
    except the version line and the version note under it."""
    for new, old in (("privacy-3.3.txt", "privacy-3.2.txt"),
                     ("terms-3.3.txt", "terms-3.2.txt")):
        old_lines = (COPY / old).read_text(encoding="utf-8").splitlines()
        new_lines = (COPY / new).read_text(encoding="utf-8").splitlines()
        # the version line and the version note are the only rewrites: keep
        # everything after the note's paragraph
        note = next(i for i, line in enumerate(old_lines)
                    if line.startswith("Version 3.2 replaces"))
        note_end = old_lines.index("", note)
        kept = old_lines[note_end:]
        it = iter(new_lines)
        dropped = [line for line in kept if not any(line == got for got in it)]
        assert dropped == [], (new, dropped[:3])


def test_the_effective_date_placeholder_is_there_and_step_one_refuses_it():
    for tag in ("privacy", "terms"):
        assert "Version 3.3. Effective [[EFFECTIVE DATE]]." in _quoted(tag)
    body = _script()
    assert "WHERE position('[[EFFECTIVE DATE]]' in c.terms) = 0" in body
    assert "AND position('[[EFFECTIVE DATE]]' in c.privacy) = 0" in body


def test_it_is_not_a_migration_and_names_the_version_the_share_switch_uses():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text(encoding="utf-8")
    assert "phase1_policy_publish_3_3.sql" not in manifest
    assert "phase1_retention_rules_v1_2.sql" not in manifest
    assert "'version','phase1-2026-10-02'" in _script()
    assert "activate_phase1_policy_v1(\n  'phase1-2026-10-02'" in _script()
    assert "PEER_SHARE_POLICY_VERSION = 'phase1-2026-10-02'" in _script()
