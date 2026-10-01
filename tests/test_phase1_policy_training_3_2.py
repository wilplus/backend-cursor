"""The Privacy 3.2 / Terms 3.2 publish script (door 1; founder 2026-10-01,
N15). Pins what made the 3.1 publish safe, for this one:

  * the four copy blocks mirror the legal pack byte for byte (terms-3.2,
    privacy-3.2; the 3.1 notice and agreement unchanged);
  * the five purposes are exactly the 3.1 script's — the training yes is
    not a Phase-1 purpose; no consent purpose is required, no required
    purpose is on consent;
  * the copy carries section 4a and the licence; the effective-date
    placeholder is still there, and STEP 1 refuses to register while it is;
  * it is not a migration, and its version id is the one the training
    registration SQL names.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "phase1_policy_publish_training_3_2.sql"
OLD = ROOT / "scripts" / "phase1_policy_publish_unbundled.sql"
COPY = ROOT / "legal" / "phase1-2026.1" / "copy"
MIRRORED = {"terms": "terms-3.2.txt", "privacy": "privacy-3.2.txt",
            "notice": "ai-notice-3.1.txt", "agree": "agreement-3.1.txt"}


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


def test_the_purposes_are_the_three_one_publish_s_purposes_unchanged():
    assert _purposes(SCRIPT) == _purposes(OLD)
    objects = _purposes(SCRIPT).split("jsonb_build_object(")[1:]
    assert len(objects) == 5
    for chunk in objects:
        consent = "'lawful_basis_code','consent'" in chunk
        required = "'required_for_core_service',true" in chunk
        assert consent != required, chunk[:80]
    assert "pooled_model_improvement" not in _purposes(SCRIPT)


def test_the_copy_carries_the_training_choice_and_nothing_about_audio_training():
    privacy, terms = _quoted("privacy"), _quoted("terms")
    assert "4a. HELPING TO IMPROVE WILLPOWERLAB — OPTIONAL" in privacy
    assert "Use\nmy practice text and my coach's notes on it" in privacy
    assert "Text only. Your voice never leaves for\ntraining" in privacy
    assert "six years" in privacy
    assert "do\nnot reproduce your text" in privacy
    assert "hold no personal information" not in privacy
    assert "you give us a licence to reproduce" in terms
    assert "Version 3.2." in privacy and "Version 3.2." in terms


def test_the_effective_date_is_set_and_step_one_refuses_a_placeholder():
    assert "Version 3.2. Effective 1 October 2026." in _quoted("privacy")
    assert "Version 3.2. Effective 1 October 2026." in _quoted("terms")
    assert "[[EFFECTIVE DATE]]" not in _quoted("privacy")
    body = _script()
    assert "WHERE position('[[EFFECTIVE DATE]]' in c.terms) = 0" in body
    assert "AND position('[[EFFECTIVE DATE]]' in c.privacy) = 0" in body


def test_it_is_not_a_migration_and_names_the_version_the_registration_uses():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text(encoding="utf-8")
    assert "phase1_policy_publish_training_3_2.sql" not in manifest
    assert "'version','phase1-2026-10-01'" in _script()
    assert "activate_phase1_policy_v1(\n  'phase1-2026-10-01'" in _script()
    doors = (ROOT / "docs" / "LEARNING-DOORS.md").read_text(encoding="utf-8")
    assert "'phase1-2026-10-01'" in doors
