"""
STORY    As a speaker, I want every policy I may have accepted to carry
         exactly the signed copy and never make an optional purpose a
         condition of the service, so that refusing an optional purpose never
         blocks me and I can later prove what I agreed to.
OUTCOME
  O1  In every publish since the unbundling (3.1 to the live 3.7), every
      required purpose is on contract ...
  O2  ... and every consent purpose is optional; neither check passes alone.
  O3  Training (pooled_model_improvement) is never a processing purpose:
      the training yes stays its own act.
  O4  Each publish's four copy blocks equal the legal pack's files byte for
      byte (3.6 and 3.7 are checked in their own files).
  O5  No publish is a migration (MIGRATE_ON_BOOT would publish it at boot).
PROVES   O1, O2, O3 -> test_no_purpose_is_both_required_and_by_consent
         O4 -> test_the_copy_is_the_signed_legal_pack
         O5 -> test_no_publish_is_in_the_migration_manifest
WHY      P11: the 2026-09-20 publish put all five purposes on consent AND
         required (Art 7(4)). Reads the publish SQL as text.
"""
from __future__ import annotations

import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
COPY = ROOT / "legal" / "phase1-2026.1" / "copy"

# (publish script, privacy, terms, notice, agreement), oldest first; the last
# is the policy in force (3.7, published 2026-10-15). 3.1's script is the
# unbundled republish; the 2026-09-20 bundled one is the defect and is left out.
PUBLISHES = (
    ("scripts/phase1_policy_publish_unbundled.sql", "privacy-3.1", "terms-3.1",
     "ai-notice-3.1", "agreement-3.1"),
    ("scripts/phase1_policy_publish_training_3_2.sql", "privacy-3.2", "terms-3.2",
     "ai-notice-3.1", "agreement-3.1"),
    ("scripts/phase1_policy_publish_3_3.sql", "privacy-3.3", "terms-3.3",
     "ai-notice-3.1", "agreement-3.1"),
    ("scripts/phase1_policy_publish_3_4.sql", "privacy-3.4", "terms-3.4",
     "ai-notice-3.1", "agreement-3.1"),
    ("legal/phase1-2026.1/PUBLISH-3.5-2026-10-08.sql", "privacy-3.5", "terms-3.5",
     "ai-notice-3.1", "agreement-3.1"),
    ("legal/phase1-2026.1/PUBLISH-3.6-2026-10-15.sql", "privacy-3.6", "terms-3.6",
     "ai-notice-3.2", "agreement-3.1"),
    ("legal/phase1-2026.1/PUBLISH-3.7-2026-10-15.sql", "privacy-3.7", "terms-3.6",
     "ai-notice-3.2", "agreement-3.1"),
)
#: 3.6 and 3.7 have their own copy checks (test_phase1_policy_3_6/3_7.py).
OWN_COPY_CHECK = ("privacy-3.6", "privacy-3.7")


def _script(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _purpose_objects(path: str) -> list[str]:
    """Each purpose's jsonb_build_object from the purposes array (the last
    array before the actor argument), comments stripped, so basis and
    requiredness are read together: the defect is a pairing, not a tally."""
    body = _script(path)
    end = body.index("'founder:artur@willonski.com'\n) FROM c")
    start = body.rindex("jsonb_build_array(", 0, end)
    block = re.sub(r"--[^\n]*", "", body[start:end])
    return block.split("jsonb_build_object(")[1:]


@pytest.mark.parametrize("publish", PUBLISHES, ids=lambda p: p[1])
def test_no_purpose_is_both_required_and_by_consent(publish):
    objects = _purpose_objects(publish[0])
    assert len(objects) == 5
    for chunk in objects:
        name = re.search(r"r\.id = '([a-z_]+)'", chunk).group(1)
        required = "'required_for_core_service',true" in chunk
        if required:
            assert "'lawful_basis_code','contract'" in chunk, name
        if "'lawful_basis_code','consent'" in chunk:
            assert not required, name
        assert name != "pooled_model_improvement"


@pytest.mark.parametrize(
    "publish", [p for p in PUBLISHES if p[1] not in OWN_COPY_CHECK],
    ids=lambda p: p[1])
def test_the_copy_is_the_signed_legal_pack(publish):
    script = _script(publish[0])
    for tag, name in zip(("privacy", "terms", "notice", "agree"), publish[1:]):
        block = re.search(rf"\${tag}\$(.*?)\${tag}\$", script, re.S)
        assert block, f"no ${tag}$ block"
        assert block.group(1) == (COPY / f"{name}.txt").read_text(
            encoding="utf-8"), f"{tag} differs from {name}.txt"


def test_no_publish_is_in_the_migration_manifest():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text(encoding="utf-8")
    assert "0412\ta_training_yes_counts_any_later_policy.sql" in manifest
    for publish in (*PUBLISHES, ("scripts/phase1_policy_publish.sql",)):
        assert pathlib.Path(publish[0]).name not in manifest
