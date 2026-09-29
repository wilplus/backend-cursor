"""The three canary variables are retired (rings, 0394; follow-up 2026-09-29).

DATA_FOUNDATION_CANARY_ENABLED, MLC2_CONFIDENCE_CANARY_FOUNDER_EMAIL and
MLC2_CONFIDENCE_CANARY_PRINCIPAL_ID decided who a canary reached. Since 0394
the `canonical_take_rows` and `confidence_learning_writes` ring rows do, and
the variables were kept readable and unread for one release. This pins that
no production module names them again: a new reader would be a second "who"
beside the ring, which is the drift the rings exist to end.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RETIRED = (
    "DATA_FOUNDATION_CANARY_ENABLED",
    "MLC2_CONFIDENCE_CANARY_FOUNDER_EMAIL",
    "MLC2_CONFIDENCE_CANARY_PRINCIPAL_ID",
)
PRODUCTION = ("app.py", "worker.py", "config.py", "routes", "services", "scripts", "bin")


def _production_files():
    for name in PRODUCTION:
        path = ROOT / name
        if path.is_file():
            yield path
        else:
            yield from (p for p in path.rglob("*") if p.suffix in (".py", ".sh"))


def test_config_no_longer_defines_them():
    from config import Config

    for name in RETIRED:
        assert not hasattr(Config, name), name


def test_no_production_module_reads_them():
    """A mention in prose (a comment or docstring recording the retirement)
    is allowed; a read is not: `Config.X`, `config.X`, `os.getenv("X")`,
    or the name as a shell variable."""
    offenders = []
    for path in _production_files():
        text = path.read_text(errors="ignore")
        for name in RETIRED:
            if re.search(rf"(Config\.|config\.|getenv\(\"|environ\[\"|\$\{{?){name}", text):
                offenders.append(f"{path.relative_to(ROOT)}: {name}")
            if path.suffix == ".sh" and re.search(rf"^\s*(export\s+)?{name}=", text, re.M):
                offenders.append(f"{path.relative_to(ROOT)}: {name}")
    assert offenders == []


def test_the_boot_line_neither_names_nor_prints_them():
    from services.gate_flags import GATE_FLAGS, IDENTIFYING_FLAGS

    for name in RETIRED:
        assert name not in GATE_FLAGS
        assert name not in IDENTIFYING_FLAGS
