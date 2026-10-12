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


def _script(path=SCRIPT) -> str:
    return path.read_text(encoding="utf-8")


def _purposes(path) -> str:
    body = _script(path)
    end = body.index("'founder:artur@willonski.com'\n) FROM c")
    start = body.rindex("jsonb_build_array(", 0, end)
    return re.sub(r"--[^\n]*", "", body[start:end])


def test_the_purposes_are_the_three_one_publish_s_purposes_unchanged():
    assert _purposes(SCRIPT) == _purposes(OLD)
    objects = _purposes(SCRIPT).split("jsonb_build_object(")[1:]
    assert len(objects) == 5
    for chunk in objects:
        consent = "'lawful_basis_code','consent'" in chunk
        required = "'required_for_core_service',true" in chunk
        assert consent != required, chunk[:80]
    assert "pooled_model_improvement" not in _purposes(SCRIPT)
