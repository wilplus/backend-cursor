"""Reviewed provider-deletion adapters for Phase-1 purge orchestration.

The adapter never guesses what a provider retains.  It executes only an
immutable contract whose latest append-only event is ``activated``.  An
unknown provider, object shape, contract mode, or verification response fails
closed and leaves the purge in review.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProviderDeletionResult:
    state: str
    remaining_match_count: int
    error_code: str | None = None
    retention_rule_id: str | None = None


def _is_not_found(error: BaseException) -> bool:
    status = getattr(error, "status_code", None)
    response = getattr(error, "response", None)
    if status is None and response is not None:
        status = getattr(response, "status_code", None)
    return status == 404 or type(error).__name__ in {
        "NotFoundError", "NotFound", "FileNotFoundError",
    }


def _openai_delete_and_verify(object_ref: str) -> bool:
    from services.openai_service import OpenAIService

    client = OpenAIService().client
    if client is None:
        raise RuntimeError("OPENAI_CLIENT_UNAVAILABLE")
    deleted = client.files.delete(object_ref)
    if not bool(getattr(deleted, "deleted", False)):
        return False
    try:
        client.files.retrieve(object_ref)
    except Exception as error:
        if _is_not_found(error):
            return True
        raise
    return False


_DELETE_AND_VERIFY: Mapping[str, Callable[[str], bool]] = {
    "openai": _openai_delete_and_verify,
}


def resolve_provider_operation(
    *,
    contract: Mapping[str, Any],
    provider: str,
    provider_operation_ref: str | None,
    delete_and_verify: Mapping[str, Callable[[str], bool]] | None = None,
) -> ProviderDeletionResult:
    """Resolve one provider operation under one exact reviewed contract."""
    if str(contract.get("provider") or "") != provider:
        return ProviderDeletionResult("failed", 1, "PROVIDER_CONTRACT_MISMATCH")
    mode = str(contract.get("resolution_mode") or "")
    if mode == "no_durable_provider_object":
        return ProviderDeletionResult("not_found", 0)
    if mode == "contractual_retention":
        rule_id = str(contract.get("retention_rule_id") or "")
        if not rule_id:
            return ProviderDeletionResult("failed", 1, "RETENTION_RULE_REQUIRED")
        return ProviderDeletionResult(
            "retained", 1, retention_rule_id=rule_id,
        )
    if mode != "api_delete":
        return ProviderDeletionResult("failed", 1, "UNKNOWN_PROVIDER_MODE")

    object_ref = str(provider_operation_ref or "")
    prefix = str(contract.get("provider_object_prefix") or "")
    if not object_ref or not prefix or not object_ref.startswith(prefix):
        return ProviderDeletionResult(
            "failed", 1, "PROVIDER_OBJECT_REF_INCOMPATIBLE",
        )
    adapter = (delete_and_verify or _DELETE_AND_VERIFY).get(provider)
    if adapter is None:
        return ProviderDeletionResult("failed", 1, "PROVIDER_ADAPTER_MISSING")
    try:
        verified = adapter(object_ref)
    except Exception as error:  # noqa: BLE001 - provider SDK boundary
        return ProviderDeletionResult(
            "failed", 1, f"PROVIDER_DELETE_{type(error).__name__.upper()}",
        )
    return ProviderDeletionResult(
        "deleted" if verified else "failed",
        0 if verified else 1,
        None if verified else "PROVIDER_DELETION_NOT_VERIFIED",
    )
