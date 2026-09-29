"""0392: the canonical promotion takes its own consent snapshot (Q1).

Text pins on the migration file; the released rehearsal lane proves the
behaviour in tests/test_mlc2_confidence_end_to_end_postgres.py.
"""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "the_promotion_freezes_the_consent_snapshot.sql"
SQL = MIGRATION.read_text()
FUNCTION = "promote_recording_attempt_with_mlc2_confidence_v1"


def _body() -> str:
    match = re.search(
        rf"CREATE OR REPLACE FUNCTION public\.{FUNCTION}\b(.*?)\n\$\$;",
        SQL, flags=re.S,
    )
    assert match
    return match.group(1)


def test_manifest_appends_0392_after_0391():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text().splitlines()
    this = "0392\tthe_promotion_freezes_the_consent_snapshot.sql"
    before = "0391\tsounds_more_confident_reads_the_coachs_two_answers.sql"
    assert this in manifest
    assert manifest.index(before) < manifest.index(this)


def test_the_snapshot_is_taken_before_it_is_looked_up_and_after_the_take_promotion():
    body = _body()
    promotion = body.index("promote_recording_attempt_to_take_v1")
    snapshot = body.index("PERFORM public.create_mlc2_consent_snapshot_v1(")
    lookup = body.index("SELECT snapshot.id INTO consent_id")
    outbox = body.index("enqueue_mlc2_outbox_event_v1")
    assert promotion < snapshot < lookup < outbox


def test_the_snapshot_is_taken_only_when_this_attempt_has_none():
    body = _body()
    guard = body.index("IF NOT EXISTS (")
    assert guard < body.index("PERFORM public.create_mlc2_consent_snapshot_v1(")
    window = body[guard:body.index("PERFORM public.create_mlc2_consent_snapshot_v1(")]
    assert "snapshot.recording_attempt_id = attempt.id" in window
    assert "snapshot.acquisition_principal_id = attempt.owner_principal_id" in window


def test_the_snapshot_binds_the_attempts_own_owner_and_project():
    body = _body()
    assert (
        "create_mlc2_consent_snapshot_v1(\n"
        "            attempt.owner_principal_id, attempt.id, NULL, attempt.project_id"
    ) in body


def test_everything_else_the_function_required_is_still_required():
    body = _body()
    for requirement in (
        "cloudflare_r2", "pooled_model_improvement", "resolved speaker",
        "pre-cutover Take", "source_manifest_sha256",
        "lacks current model-improvement consent",
    ):
        assert requirement in body


def test_the_search_path_and_grants_match_0307_and_0304():
    assert "SET search_path = extensions, public" in _body()
    assert f"REVOKE ALL ON FUNCTION public.{FUNCTION}(" in SQL
    assert f"GRANT EXECUTE ON FUNCTION public.{FUNCTION}(" in SQL
    assert "TO service_role" in SQL


def test_the_migration_is_additive_and_activates_nothing():
    lowered = SQL.lower()
    for forbidden in ("drop table", "drop column", "truncate", "delete from",
                      "alter table", "founder_canary"):
        assert forbidden not in lowered, forbidden
    assert SQL.count("CREATE OR REPLACE FUNCTION") == 1


def test_the_released_lane_applies_0392_twice():
    recipe = (ROOT / "tests" / "integration" / "confident_moment_rehearsal.sh").read_text()
    assert recipe.count("hard migrations/the_promotion_freezes_the_consent_snapshot.sql") == 2
