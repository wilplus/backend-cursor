"""0454, read as text (the released lane runs it for real:
test_practice_is_part_of_the_service_postgres.py)."""
from __future__ import annotations

import pathlib
import re

from services.data_purge_registry import DEPENDENCIES

ROOT = pathlib.Path(__file__).resolve().parents[1]
SQL = (ROOT / "migrations" / "practice_is_part_of_the_service.sql").read_text()


def _code(sql: str) -> str:
    return re.sub(r"--[^\n]*", "", sql)


def test_it_is_additive_and_reads_no_environment():
    code = _code(SQL).upper()
    assert "DROP TABLE" not in code and "DROP COLUMN" not in code
    assert "CREATE TABLE IF NOT EXISTS PUBLIC.BLIND_CHECK_OBJECTIONS" in code
    assert "CURRENT_SETTING" not in code


def test_practice_reads_as_on_only_where_the_active_policy_requires_it():
    code = _code(SQL)
    assert "pp.purpose_id = 'personalized_exercise_recommendation'" in code
    assert "AND pp.required_for_core_service);" in code
    on = code.index("IF in_service THEN")
    tick = code.index("practice_on := cardinality(optional_ids) > 0")
    events = code.index("e.choice = 'personalised_practice'")
    assert on < tick < events
    assert code.count("'practice_in_service', in_service") == 2


def test_browser_roles_reach_none_of_it():
    code = _code(SQL)
    for name in ("get_phase1_consent_choices_v1(UUID)",
                 "record_blind_check_objection_v1(UUID, TEXT)",
                 "has_blind_check_objection_v1(UUID)"):
        assert f"REVOKE ALL ON FUNCTION public.{name}\n    FROM PUBLIC, anon, authenticated;" in code
        assert f"GRANT EXECUTE ON FUNCTION public.{name}\n    TO service_role;" in code
    assert "REVOKE ALL ON public.blind_check_objections\n    FROM PUBLIC, anon, authenticated;" in code


def test_an_objection_goes_with_the_person():
    row = {d.code: d for d in DEPENDENCIES}["blind_check_objections"]
    assert (row.relation, row.selector_column, row.locator_kind,
            row.disposition) == ("blind_check_objections",
                                 "acquisition_principal_id", "principal",
                                 "delete")
