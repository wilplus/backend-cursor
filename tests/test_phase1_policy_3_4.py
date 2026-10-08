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
  * it is not a migration, and it is meant to run only after 0451.
"""
from __future__ import annotations

import difflib
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "phase1_policy_publish_3_4.sql"
OLD = ROOT / "scripts" / "phase1_policy_publish_3_3.sql"
COPY = ROOT / "legal" / "phase1-2026.1" / "copy"
MIRRORED = {"terms": "terms-3.4.txt", "privacy": "privacy-3.4.txt",
            "notice": "ai-notice-3.1.txt", "agree": "agreement-3.1.txt"}
PRACTICE = ("personalized_exercise_recommendation",
            "individual_learning_profile")

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


def _purpose_objects(path) -> dict[str, str]:
    body = _script(path)
    end = body.index("'founder:artur@willonski.com'\n) FROM c")
    start = body.rindex("jsonb_build_array(", 0, end)
    chunks = re.sub(r"--[^\n]*", "", body[start:end]).split(
        "jsonb_build_object(")[1:]
    out = {}
    for chunk in chunks:
        purpose = re.search(r"WHERE r\.id = '([a-z_]+)'", chunk).group(1)
        out[purpose] = re.sub(r"\s+", " ", chunk)
    return out


def test_every_block_is_mirrored_byte_for_byte():
    bad = [name for tag, name in MIRRORED.items()
           if (COPY / name).read_text(encoding="utf-8") != _quoted(tag)]
    assert bad == []


def test_practice_moves_to_contract_and_nothing_else_changes():
    new, old = _purpose_objects(SCRIPT), _purpose_objects(OLD)
    assert set(new) == set(old) and len(new) == 5
    for purpose, chunk in new.items():
        assert "'lawful_basis_code','contract'" in chunk, purpose
        assert "'required_for_core_service',true" in chunk, purpose
        if purpose not in PRACTICE:
            assert chunk == old[purpose], purpose
    for purpose in PRACTICE:
        assert "'lawful_basis_code','consent'" in old[purpose]
    assert "pooled_model_improvement" not in "".join(new.values())


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


def test_three_four_changes_only_the_practice_passages():
    """3.3 and 3.4 differ in exactly the places the founder read: Privacy in
    seven (version line, version note, the blind check's off switch, the
    practice purpose, "Do you have to provide", and two lines of "Human
    coaches"), Terms in four (version line, version note, the blind check's
    off switch, practice in section 11)."""
    for kind, places in (("privacy", 7), ("terms", 4)):
        old = (COPY / f"{kind}-3.3.txt").read_text(encoding="utf-8").splitlines()
        new = (COPY / f"{kind}-3.4.txt").read_text(encoding="utf-8").splitlines()
        changed = [op for op in difflib.SequenceMatcher(
            None, old, new, autojunk=False).get_opcodes() if op[0] != "equal"]
        assert len(changed) == places, (kind, changed)


def test_counsel_review_is_recorded_as_not_obtained():
    body = _script()
    assert ("'practice_counsel_review',"
            "'not_obtained_founder_signed_in_place_2026-10-08'") in body
    assert "COUNSEL'S REVIEW WAS NOT OBTAINED" in body


def test_the_date_is_the_day_the_founder_named_and_step_one_refuses_a_placeholder():
    body = _script()
    assert "WHERE position('[[EFFECTIVE DATE]]' in c.terms) = 0" in body
    assert "AND position('[[EFFECTIVE DATE]]' in c.privacy) = 0" in body
    for tag in ("privacy", "terms"):
        assert "Version 3.4. Effective 8 October 2026." in _quoted(tag)
        assert "[[EFFECTIVE DATE]]" not in _quoted(tag)


def test_it_is_not_a_migration_and_follows_0451():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text(encoding="utf-8")
    assert "phase1_policy_publish_3_4.sql" not in manifest
    assert "0451\tpractice_is_part_of_the_service.sql" in manifest
    body = _script()
    assert "'version','phase1-2026-10-08'" in body
    assert "activate_phase1_policy_v1(\n  'phase1-2026-10-08'" in body
    assert "RUN IT ONLY AFTER migration 0451" in body
