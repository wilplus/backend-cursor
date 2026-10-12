from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "add_mlc2_foundation.sql"
SQL = MIGRATION.read_text()


def _table(name: str) -> str:
    start = SQL.index(f"CREATE TABLE IF NOT EXISTS public.{name}")
    next_table = SQL.find("CREATE TABLE IF NOT EXISTS public.", start + 1)
    return SQL[start: next_table if next_table >= 0 else len(SQL)]


def test_blind_review_requires_submission_before_reveal():
    assignment = _table("ml_review_assignments")
    assert "blind_packet_sha256" in assignment
    assert "blindness_policy_version" in assignment
    reveal = SQL[
        SQL.index("CREATE OR REPLACE FUNCTION public.reveal_ml_review_assignment_v1"):
        SQL.index("-- ── Immutability, access control")
    ]
    assert "event.event_kind = 'submitted'" in reveal
    assert "blind review may be revealed only after submission" in reveal
