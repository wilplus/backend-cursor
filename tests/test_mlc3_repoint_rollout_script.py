"""The by-hand rollout re-point (founder 2026-09-28): activating a policy
does not move the coaching rollout, so this script does, and only by hand."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "mlc3_repoint_rollout_to_active_policy.sql"


def test_it_never_runs_on_deploy():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text()
    assert "mlc3_repoint_rollout_to_active_policy" not in manifest


def test_it_halts_then_registers_inside_one_transaction():
    sql = SCRIPT.read_text()
    begin, commit = sql.index("\nBEGIN;"), sql.index("\nCOMMIT;")
    halt = sql.index("halt_mlc3_service_rollout_v1(")
    register = sql.index("register_mlc3_general_rollout_v2(")
    assert begin < halt < register < commit


def test_it_reuses_the_approved_settings_and_requires_the_active_policy():
    sql = SCRIPT.read_text()
    for field in ("prev.activation_risk_decision_id", "prev.capacity_policy",
                  "prev.policy_versions"):
        assert field in sql
    assert "WHERE status = 'active'" in sql


def test_the_publish_script_points_to_it():
    publish = (ROOT / "scripts" / "phase1_policy_publish_unbundled.sql").read_text()
    assert "mlc3_repoint_rollout_to_active_policy.sql" in publish
