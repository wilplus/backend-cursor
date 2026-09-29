"""0393: the legacy coach card's three confidence-chain wrappers (Q2).

Text pins on the migration file; the released rehearsal lane proves them
against PostgreSQL in tests/test_mlc2_confidence_end_to_end_postgres.py.
"""
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
SQL = (ROOT / "migrations" / "the_coach_card_consumes_the_confidence_chain.sql").read_text()
WRAPPERS = (
    "prepare_mlc2_confidence_coach_packet_v1",
    "ack_mlc2_confidence_coach_render_v1",
    "submit_mlc2_confidence_coach_judgment_v1",
)


def _body(name: str) -> str:
    match = re.search(
        rf"CREATE OR REPLACE FUNCTION public\.{name}\b(.*?)\n\$\$;", SQL, flags=re.S,
    )
    assert match, name
    return match.group(1)


def test_manifest_appends_0393_after_q1s_0392():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text().splitlines()
    this = "0393\tthe_coach_card_consumes_the_confidence_chain.sql"
    before = "0392\tthe_promotion_freezes_the_consent_snapshot.sql"
    assert this in manifest
    assert manifest.index(before) < manifest.index(this)


def test_exactly_the_three_wrappers_are_defined_as_definers_with_0307s_search_path():
    assert SQL.count("CREATE OR REPLACE FUNCTION") == 3
    for name in WRAPPERS:
        body = _body(name)
        assert "SECURITY DEFINER" in body
        assert "SET search_path = extensions, public" in body
        assert f"REVOKE ALL ON FUNCTION public.{name}(" in SQL
        assert f"GRANT EXECUTE ON FUNCTION public.{name}(" in SQL


def test_the_packet_comes_from_the_selected_eligible_candidate_of_the_takes_snippet():
    body = _body("prepare_mlc2_confidence_coach_packet_v1")
    assert "candidate_row.clip_id = p_snippet_id" in body
    assert "candidate_set.take_id = p_take_id" in body
    assert "candidate_row.selected" in body and "candidate_row.eligible" in body
    assert "create_mlc2_confidence_blind_packet_v1(" in body
    assert "'coach', 'conf-q-v2'" in body


def test_the_owner_is_not_a_peer_and_no_candidate_is_no_packet():
    body = _body("prepare_mlc2_confidence_coach_packet_v1")
    assert "speaker_principal = p_reviewer_principal_id" in body
    assert body.count("RETURN NULL;") == 2


def test_the_render_receipt_is_bound_to_this_packet_and_reviewer():
    body = _body("ack_mlc2_confidence_coach_render_v1")
    assert "ml_confidence_blind_packets packet" in body
    assert "packet.reviewer_principal_id = p_reviewer_principal_id" in body
    assert "packet.visible_packet_sha256 = p_visible_payload_sha256" in body
    assert "ack_mlc2_rendered_exposure_v1(" in body


def test_the_judgment_reaches_the_owner_only_writer_and_reveals_in_the_same_transaction():
    body = _body("submit_mlc2_confidence_coach_judgment_v1")
    judgment = body.index("submit_mlc2_confidence_blind_judgment_v1(")
    reveal = body.index("reveal_mlc2_confidence_review_v1(")
    assert body.index("COACH_CARD_BLIND_JUDGMENT_IDENTITY_INVALID") < judgment < reveal
    assert "p_idempotency_key || ':reveal'" in body
    assert "'revealed', true" in body


def test_the_migration_is_additive_and_activates_nothing():
    lowered = SQL.lower()
    for forbidden in ("drop table", "drop column", "truncate", "delete from",
                      "alter table", "create table"):
        assert forbidden not in lowered, forbidden
    assert "founder_canary" not in _body("prepare_mlc2_confidence_coach_packet_v1")


def test_the_released_lane_applies_0393_twice():
    recipe = (ROOT / "tests" / "integration" / "confident_moment_rehearsal.sh").read_text()
    assert recipe.count("hard migrations/the_coach_card_consumes_the_confidence_chain.sql") == 2
