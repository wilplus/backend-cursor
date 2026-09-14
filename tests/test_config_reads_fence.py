"""Fence: environment variables are read in ``config.py`` and
``services/secrets.py``, nowhere else (audit Q-A5, Phase 4).

The CONFIG-FIRST rule (CLAUDE.md, 2026-08-10) says a variable is set on
every Railway service before the code that reads it merges. That is only
checkable when there is one place the code reads from. The audit found 86
``os.environ`` / ``os.getenv`` reads in 42 production files outside
``config.py``; the F1 modules (transcription, Ideal Text, Manager) among them
now read through ``Config``, and this test keeps it that way:

1. Every module in the F1 coverage floor (``scripts/coverage_floor.json``)
   reads no environment variable directly.
2. Every other production file is frozen at its current count below. Down
   only: a new read anywhere fails the unit tier, and a file that moves its
   reads into ``Config`` lowers its number here in the same change.

Read from the AST (``os.environ`` / ``os.getenv`` attribute access on the
``os`` module), so a comment or a docstring neither trips nor dodges it.

Run: python3 -m pytest tests/test_config_reads_fence.py
"""
from __future__ import annotations

import ast
import json
import pathlib

import pytest

from tests.repo_scan import ROOT, python_files, try_parse

ALLOWED = {"config.py", "services/secrets.py"}

# path → direct environment reads, frozen 2026-09-14. Down only.
GRANDFATHERED_ENV_READS = {
    "get_token.py": 3,
    "routes/drift_webhook.py": 1,
    "routes/jobs.py": 2,
    "routes/life_reminders_webhook.py": 1,
    "routes/v2/canonical_publish.py": 5,
    "routes/v2/common.py": 1,
    "run_migration.py": 1,
    "services/audio_metrics.py": 1,
    "services/casual_voice_analytics.py": 1,
    "services/delivery_alignment.py": 1,
    "services/ideal_text_variants.py": 1,
    "services/job_queue.py": 6,
    "services/journal_image.py": 1,
    "services/journal_media.py": 1,
    "services/life_reminders.py": 4,
    "services/llm_usage.py": 1,
    "services/logging_setup.py": 1,
    "services/master_doc_rag.py": 1,
    "services/moment_suggestions.py": 2,
    "services/orphan_audio_cleanup.py": 1,
    "services/pipeline_health.py": 1,
    "services/processing_authorization.py": 1,
    "services/rate_limits.py": 5,
    "services/recording_piece_analysis.py": 1,
    "services/snippet_tables.py": 2,
    "services/stripe_subscription_tiers.py": 1,
    "services/token_account.py": 1,
    "services/tutor_video_url.py": 6,
    "services/voice_confidence.py": 2,
    "utils/errors.py": 2,
    "worker.py": 2,
}


def _production_files() -> list[pathlib.Path]:
    out = []
    for path in python_files(""):
        rel = path.relative_to(ROOT)
        top = rel.parts[0]
        if top in ("tests", "scripts") or rel.name.startswith("test_") or rel.name == "conftest.py":
            continue
        out.append(path)
    return out


def _env_reads(tree: ast.Module) -> int:
    return sum(
        1 for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name) and node.value.id == "os"
        and node.attr in ("environ", "getenv")
    )


@pytest.fixture(scope="module")
def reads_by_file() -> dict[str, int]:
    found: dict[str, int] = {}
    for path in _production_files():
        tree = try_parse(path)
        if tree is None:
            continue
        n = _env_reads(tree)
        if n:
            found[path.relative_to(ROOT).as_posix()] = n
    return found


def test_the_f1_modules_read_no_environment_variable_directly(reads_by_file):
    floor = json.loads((ROOT / "scripts" / "coverage_floor.json").read_text())
    offenders = {p: reads_by_file[p] for p in floor if p in reads_by_file}
    assert not offenders, (
        "F1 modules read configuration through Config (config.py), never "
        f"os.environ / os.getenv directly: {offenders}"
    )


def test_environment_reads_outside_config_only_ever_shrink(reads_by_file):
    found = {p: n for p, n in reads_by_file.items() if p not in ALLOWED}
    new = {p: n for p, n in found.items() if p not in GRANDFATHERED_ENV_READS}
    assert not new, (
        "new direct environment read(s) — add the value to Config in config.py "
        f"and read it from there: {new}"
    )
    grown = {p: (GRANDFATHERED_ENV_READS[p], n) for p, n in found.items()
             if n > GRANDFATHERED_ENV_READS[p]}
    assert not grown, f"direct environment reads grew (frozen, found): {grown}"
    stale = {p: (n, found.get(p, 0)) for p, n in GRANDFATHERED_ENV_READS.items()
             if found.get(p, 0) < n}
    assert not stale, (
        "environment reads moved into Config (good) — lower the number in "
        f"GRANDFATHERED_ENV_READS so the ratchet holds: {stale}"
    )
