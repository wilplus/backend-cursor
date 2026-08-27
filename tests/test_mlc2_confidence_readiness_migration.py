from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT / "migrations" / "add_mlc2_confidence_canary_readiness.sql"
)
SQL = MIGRATION.read_text()


def _function(name: str) -> str:
    match = re.search(
        rf"CREATE OR REPLACE FUNCTION public\.{name}\b(.*?)\n\$\$;",
        SQL,
        flags=re.S,
    )
    assert match, name
    return match.group(1)


def test_manifest_appends_slice6_readiness_as_0305():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text().splitlines()
    assert manifest[-1] == "0305\tadd_mlc2_confidence_canary_readiness.sql"


def test_readiness_rpc_checks_consent_founder_scope_and_lineage():
    function = _function("get_mlc2_confidence_canary_readiness_v1")
    for contract in (
        "ml_product_legal_approvals",
        "required_for_service",
        "bundled_ui",
        "6(1)(a)",
        "founder_active_bundled_consent_grant_count",
        "nonfounder_producer_receipt_count",
        "nonfounder_canonical_event_count",
        "failed_confidence_outbox_count",
        "receipt_without_outbox_count",
        "processed_without_frame_count",
        "blind_assignment_without_packet_count",
        "revealed_without_judgment_count",
    ):
        assert contract in function


def test_readiness_rpc_is_aggregate_only_service_role_only_and_non_mutating():
    function = _function("get_mlc2_confidence_canary_readiness_v1")
    assert "count(*)" in function
    assert "SECURITY DEFINER" in function
    assert "STABLE" in function
    assert (
        "REVOKE ALL ON FUNCTION "
        "public.get_mlc2_confidence_canary_readiness_v1(UUID)"
    ) in SQL
    assert (
        "GRANT EXECUTE ON FUNCTION "
        "public.get_mlc2_confidence_canary_readiness_v1(UUID)\n"
        "    TO service_role"
    ) in SQL
    assert not re.search(
        r"\b(INSERT|UPDATE|DELETE|TRUNCATE|DROP\s+TABLE)\b",
        function,
        flags=re.I,
    )


def test_readiness_rpc_keeps_downstream_capabilities_disabled():
    function = _function("get_mlc2_confidence_canary_readiness_v1")
    assert "'dataset_creation_enabled', false" in function
    assert "'training_enabled', false" in function
    assert "'promotion_enabled', false" in function
