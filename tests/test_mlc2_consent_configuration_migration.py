from pathlib import Path
import hashlib
import json
import re


ROOT = Path(__file__).resolve().parents[1]
MIGRATION = ROOT / "migrations" / "add_mlc2_consent_configuration.sql"
SQL = MIGRATION.read_text()


def _function(name: str) -> str:
    match = re.search(
        rf"CREATE OR REPLACE FUNCTION public\.{name}\b(.*?)\n\$\$;",
        SQL,
        flags=re.S,
    )
    assert match, name
    return match.group(1)


def test_manifest_contains_slice6a_as_0306():
    manifest = (ROOT / "migrations" / "manifest.txt").read_text().splitlines()
    assert "0306\tadd_mlc2_consent_configuration.sql" in manifest


def test_configuration_rpc_verifies_copy_and_is_service_only():
    function = _function("configure_mlc2_consent_policy_v1")
    for required in (
        "digest(convert_to(p_onboarding_copy, 'UTF8'), 'sha256')",
        "Product/legal approval idempotency collision",
        "consent policy idempotency collision",
        "another bundled MLC-2 consent policy is active",
        "'6(1)(a)'",
        "'9(2)(a)_when_special_category'",
    ):
        assert required in function
    assert "TO service_role" in SQL
    assert "FROM PUBLIC, anon, authenticated" in SQL


def test_migration_never_seeds_approval_policy_or_consent():
    outside_function_bodies = re.sub(r"AS \$\$.*?\$\$;", "", SQL, flags=re.S)
    assert "INSERT INTO public.ml_product_legal_approvals" not in outside_function_bodies
    assert "INSERT INTO public.ml_consent_policies" not in outside_function_bodies
    assert "INSERT INTO public.ml_consent_events" not in outside_function_bodies


def test_status_rpc_is_exact_principal_and_withdrawal_aware():
    function = _function("get_mlc2_principal_consent_status_v1")
    for required in (
        "p_acquisition_principal_id",
        "ml_speaker_principals",
        "ml_consent_event_purposes",
        "personalized_coaching",
        "pooled_model_improvement",
        "supersedes_event_id",
        "onboarding_copy",
        "approved_copy_sha256",
    ):
        assert required in function
    assert "STABLE" in function


def test_identity_binding_and_grant_are_one_atomic_service_only_rpc():
    function = _function("accept_mlc2_founder_consent_v1")
    assert "register_ml_speaker_principal_v1" in function
    assert "record_mlc2_consent_grant_v1" in function
    assert "If either operation fails, neither persists" in function
    assert "GRANT EXECUTE ON FUNCTION public.accept_mlc2_founder_consent_v1" in SQL


def test_checked_in_approval_artifact_binds_exact_copy():
    artifact_path = ROOT / "legal" / "mlc2-bundled-consent-v1.json"
    artifact = json.loads(artifact_path.read_text())
    observed = hashlib.sha256(
        artifact["onboarding_copy"].encode("utf-8")
    ).hexdigest()
    assert observed == artifact["approved_copy_sha256"]
    assert artifact["article_6_basis"] == "6(1)(a)"
    assert artifact["article_9_treatment"] == "9(2)(a)_when_special_category"
    assert artifact["required_for_service"] is True
    assert artifact["bundled_ui"] is True
    assert artifact["checkbox_preselected"] is False
