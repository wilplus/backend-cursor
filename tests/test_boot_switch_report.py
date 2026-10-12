"""The boot-switch report reads pasted logs, not the Railway panel.

Ledger row A165: REASONABLE_CONFIDENCE_ENABLED must read the same on web,
worker and every cron service. These tests feed the script text, never the
app.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "scripts" / "boot_switch_report.py"


def _load():
    spec = importlib.util.spec_from_file_location("boot_switch_report", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _line(**overrides: str) -> str:
    values = {
        "REASONABLE_CONFIDENCE_ENABLED": "0",
        "TAKE_FEEDBACK_POLICY_V3_MODE": "off",
        "MLC3_SERVICE_ENABLED": "1",
        "MIGRATE_ON_BOOT": "(unset)",
    }
    values.update(overrides)
    body = " ".join(f"{name}={value}" for name, value in values.items())
    return f"2026-10-07 09:12:44,101 INFO app [-]: gate flags {body}"


def test_all_services_agree(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    module = _load()
    web = tmp_path / "web.txt"
    worker = tmp_path / "worker.txt"
    web.write_text(_line(), encoding="utf-8")
    worker.write_text(_line(), encoding="utf-8")
    code = module.main([f"web={web}", f"worker={worker}"])
    out = capsys.readouterr().out
    assert code == 0
    assert "boot_switch_report: ok (2 services agree on" in out
    assert "REASONABLE_CONFIDENCE_ENABLED" in out


def test_watched_flag_mismatch(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    module = _load()
    web = tmp_path / "web.txt"
    worker = tmp_path / "worker.txt"
    web.write_text(_line(MLC3_SERVICE_ENABLED="1"), encoding="utf-8")
    worker.write_text(_line(MLC3_SERVICE_ENABLED="0"), encoding="utf-8")
    code = module.main([f"web={web}", f"worker={worker}"])
    out = capsys.readouterr().out
    assert code == 1
    assert "MISMATCH MLC3_SERVICE_ENABLED: web=1 worker=0" in out
