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

ROOT = pathlib.Path(__file__).resolve().parents[1]
SIGNED = (ROOT / "legal" / "phase1-2026.1" / "SIGNED-ARTIFACTS.md").read_text(
    encoding="utf-8")


def test_it_is_not_a_migration():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text(encoding="utf-8")
    assert "phase1_register_article_50_v1_1.sql" not in manifest
    assert not (ROOT / "migrations" / "phase1_register_article_50_v1_1.sql").exists()
