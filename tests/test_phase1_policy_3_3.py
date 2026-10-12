"""The Privacy 3.3 / Terms 3.3 publish script (gate 6a and Phases 4 and 5;
founder 2026-10-02, N24). Pins what made the 3.2 publish safe, for this one:

  * the four copy blocks mirror the legal pack byte for byte (terms-3.3,
    privacy-3.3; the 3.1 notice and agreement unchanged);
  * the five purposes are exactly the 3.2 script's — neither the blind check
    nor the lending yes is a Phase-1 purpose; no consent purpose is required,
    no required purpose is on consent;
  * the copy is the 3.2 copy plus the signed lines of 15 §1 and 16 §1, every
    one of them present, and 3.2's training section intact;
  * the effective date is the day the founder named (2 October 2026), set in
    the copy files and the script together, and STEP 1 still refuses a
    placeholder;
  * it is not a migration, and its version id is the one the share switch
    will be gated on.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "phase1_policy_publish_3_3.sql"
OLD = ROOT / "scripts" / "phase1_policy_publish_training_3_2.sql"


def _script(path=SCRIPT) -> str:
    return path.read_text(encoding="utf-8")


def _purposes(path) -> str:
    body = _script(path)
    end = body.index("'founder:artur@willonski.com'\n) FROM c")
    start = body.rindex("jsonb_build_array(", 0, end)
    return re.sub(r"--[^\n]*", "", body[start:end])


def test_the_purposes_are_the_three_two_publish_s_purposes_unchanged():
    assert _purposes(SCRIPT) == _purposes(OLD)
    objects = _purposes(SCRIPT).split("jsonb_build_object(")[1:]
    assert len(objects) == 5
    for chunk in objects:
        consent = "'lawful_basis_code','consent'" in chunk
        required = "'required_for_core_service',true" in chunk
        assert consent != required, chunk[:80]
    assert "pooled_model_improvement" not in _purposes(SCRIPT)
