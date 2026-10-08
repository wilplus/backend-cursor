"""The boot-switch report reads pasted logs, not the Railway panel.

Ledger row A165: REASONABLE_CONFIDENCE_ENABLED must read the same on web,
worker and every cron service. These tests feed the script text, never the
app.
"""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
MODULE_PATH = REPO_ROOT / "scripts" / "boot_switch_report.py"

REAL_LINE = (
    "2026-10-07 09:12:44,101 INFO app [-]: gate flags "
    "PLF1_PROCESSING_AUTHORIZATION_MODE=enforce "
    "TAKE_FEEDBACK_POLICY_V3_MODE=off MLC3_SERVICE_ENABLED=1 "
    "MLC3_COACH_INLINE_AUTHORING_ENABLED=(unset) "
    "CONFIDENT_MOMENT_BUNDLE_V1_ENABLED=1 "
    "MLC2_CONFIDENCE_MONITORING_ENABLED=1 "
    "REASONABLE_CONFIDENCE_ENABLED=0 LIVING_TRANSCRIPT_ENABLED=1 "
    "IDEAL_TEXT_FEEDBACK_BAKE_ENABLED=1 PIPELINE_QUEUE_ENABLED=1"
)


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
        "JUDGEMENT_AFTER_FEEDBACK_ENABLED": "on",
        "PRAISE_AFTER_PRACTICE_ENABLED": "off",
        "MACHINE_PRACTICE_CHECK_ENABLED": "off",
        "COMMUNITIES_ENABLED": "off",
    }
    values.update(overrides)
    body = " ".join(f"{name}={value}" for name, value in values.items())
    return f"2026-10-07 09:12:44,101 INFO app [-]: gate flags {body}"


def test_parse_real_line_with_railway_prefix():
    module = _load()
    text = "2026-10-07T09:12:44.200Z " + REAL_LINE
    parsed = module.parse_gate_line(text)
    assert parsed is not None
    assert parsed["PLF1_PROCESSING_AUTHORIZATION_MODE"] == "enforce"
    assert parsed["TAKE_FEEDBACK_POLICY_V3_MODE"] == "off"
    assert parsed["MLC3_SERVICE_ENABLED"] == "1"
    assert parsed["MLC3_COACH_INLINE_AUTHORING_ENABLED"] == "(unset)"
    assert parsed["REASONABLE_CONFIDENCE_ENABLED"] == "0"
    assert parsed["PIPELINE_QUEUE_ENABLED"] == "1"


def test_last_of_two_gate_lines_wins():
    module = _load()
    older = REAL_LINE
    newer = REAL_LINE.replace(
        "REASONABLE_CONFIDENCE_ENABLED=0",
        "REASONABLE_CONFIDENCE_ENABLED=1",
    )
    parsed = module.parse_gate_line(older + "\nnoise\n" + newer)
    assert parsed is not None
    assert parsed["REASONABLE_CONFIDENCE_ENABLED"] == "1"


def test_text_with_no_gate_line_is_none():
    module = _load()
    assert module.parse_gate_line("boot complete\nno switches here\n") is None


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


def test_reasonable_confidence_mismatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    module = _load()
    web = tmp_path / "web.txt"
    worker = tmp_path / "worker.txt"
    web.write_text(_line(REASONABLE_CONFIDENCE_ENABLED="1"), encoding="utf-8")
    worker.write_text(_line(REASONABLE_CONFIDENCE_ENABLED="0"), encoding="utf-8")
    code = module.main([f"web={web}", f"worker={worker}"])
    out = capsys.readouterr().out
    assert code == 1
    assert "MISMATCH REASONABLE_CONFIDENCE_ENABLED: web=1 worker=0" in out
    assert "boot_switch_report: 1 problem(s)" in out


def test_name_present_on_one_service_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    module = _load()
    web = tmp_path / "web.txt"
    worker = tmp_path / "worker.txt"
    web.write_text(
        _line() + " EXTRA_SWITCH_ENABLED=1\n",
        encoding="utf-8",
    )
    worker.write_text(_line(), encoding="utf-8")
    code = module.main([f"web={web}", f"worker={worker}"])
    out = capsys.readouterr().out
    assert code == 1
    assert "MISMATCH EXTRA_SWITCH_ENABLED: web=1 worker=(missing)" in out


def test_service_with_no_gate_line(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    module = _load()
    web = tmp_path / "web.txt"
    worker = tmp_path / "worker.txt"
    web.write_text(_line(), encoding="utf-8")
    worker.write_text("worker booted, no gate line\n", encoding="utf-8")
    code = module.main([f"web={web}", f"worker={worker}"])
    out = capsys.readouterr().out
    assert code == 1
    assert "NO GATE LINE: worker" in out


def test_migrate_on_boot_is_printed_not_compared(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
):
    module = _load()
    web = tmp_path / "web.txt"
    worker = tmp_path / "worker.txt"
    web.write_text(_line(MIGRATE_ON_BOOT="1"), encoding="utf-8")
    worker.write_text(_line(MIGRATE_ON_BOOT="(unset)"), encoding="utf-8")
    code = module.main([f"web={web}", f"worker={worker}"])
    out = capsys.readouterr().out
    assert code == 0
    assert "MIGRATE_ON_BOOT" in out
    assert "(web only, not compared)" in out
    assert "MISMATCH" not in out


def test_code_switch_mismatch(tmp_path: Path, capsys: pytest.CaptureFixture[str]):
    module = _load()
    web = tmp_path / "web.txt"
    worker = tmp_path / "worker.txt"
    web.write_text(_line(COMMUNITIES_ENABLED="on"), encoding="utf-8")
    worker.write_text(_line(COMMUNITIES_ENABLED="off"), encoding="utf-8")
    code = module.main([f"web={web}", f"worker={worker}"])
    out = capsys.readouterr().out
    assert code == 1
    assert "MISMATCH COMMUNITIES_ENABLED: web=on worker=off" in out


def test_malformed_argument(capsys: pytest.CaptureFixture[str]):
    module = _load()
    code = module.main(["web", "worker=logs/worker.txt"])
    err = capsys.readouterr().err
    assert code == 2
    assert "malformed argument" in err


def test_stdin_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    module = _load()
    web = tmp_path / "web.txt"
    web.write_text(_line(), encoding="utf-8")
    monkeypatch.setattr("sys.stdin", io.StringIO(_line()))
    code = module.main([f"web={web}", "worker=-"])
    out = capsys.readouterr().out
    assert code == 0
    assert "boot_switch_report: ok" in out
