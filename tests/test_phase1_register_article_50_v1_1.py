"""Document 03 v1.1's registration script (signed 2026-10-05, decisions log
N50 D2 A), written as scripts/phase1_register_power_score_v1_1.sql was.

Pins:
  * it is not a migration: run by hand, once, after the upload;
  * it registers exactly the key and the hash SIGNED-ARTIFACTS.md records
    for 03 v1.1 in its Current table, under (article_50_assessment, 1.1),
    never a placeholder;
  * it never edits a signed artifact: a different 1.1 already there raises
    rather than being changed (04 §5).
"""
from __future__ import annotations

import pathlib
import re

from scripts.migrate import destructive_statements

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = (ROOT / "scripts" / "phase1_register_article_50_v1_1.sql").read_text(
    encoding="utf-8")
SIGNED = (ROOT / "legal" / "phase1-2026.1" / "SIGNED-ARTIFACTS.md").read_text(
    encoding="utf-8")


def _current_row(label: str) -> str:
    current = SIGNED.split("## Current", 1)[1].split("\n## ", 1)[0]
    return next(line for line in current.splitlines()
                if line.startswith(f"| {label} |"))


def test_it_is_not_a_migration():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text(encoding="utf-8")
    assert "phase1_register_article_50_v1_1.sql" not in manifest
    assert not (ROOT / "migrations" / "phase1_register_article_50_v1_1.sql").exists()


def test_it_registers_the_signed_row_signed_artifacts_records():
    row = _current_row("03 v1.1")
    key = re.search(r"`([^`]+\.pdf)`", row).group(1)
    sha = re.search(r"`([0-9a-f]{64})`", row).group(1)
    assert key == "phase1-2026.1/legal/article-50-assessment-v1.1.pdf"
    assert f"v_object_key TEXT := '{key}';" in SCRIPT
    assert f"v_sha256 TEXT := '{sha}';" in SCRIPT
    assert "artifact_kind = 'article_50_assessment' AND version = '1.1'" in SCRIPT
    assert "'article_50_assessment', '1.1'" in SCRIPT
    assert "'signature_reference', 'WILLAB-PHASE1-2026.1-A50-v1.1'" in SCRIPT
    assert "'supersedes', '1.0 (signed 2026-09-22)'" in SCRIPT
    assert "v_approved_at TIMESTAMPTZ := '2026-10-05T00:00:00Z';" in SCRIPT


def test_it_refuses_placeholders_and_never_edits_a_signed_artifact():
    assert "ARTICLE_50_V1_1_UNSIGNED" in SCRIPT
    assert "v_sha256 LIKE '[[%'" in SCRIPT
    assert "ARTICLE_50_VERSION_CONFLICT" in SCRIPT
    assert "UPDATE public.processing_legal_artifacts" not in SCRIPT
    assert destructive_statements(SCRIPT) == []
