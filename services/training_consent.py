"""The training switch (SPEC-training-corpus §3, P5 packet §4 item 6). DARK.

One person, one switch, its own screen: **Help improve WillpowerLab**. Turning
it on records the training-only yes (`record_mlc2_training_consent_grant_v2`,
0373) with control `training_toggle`; turning it off records the withdrawal
(`record_mlc2_consent_withdrawal_v2`), which makes every copy due in the same
transaction (0376), and then queues their erasure.

The wording shown is the wording the database holds for the policy, and the
yes carries its fingerprint. The database refuses a yes on any other text and
a yes from anyone who has not accepted the processing policy that introduced
training (C1). This module adds no rule of its own; it maps the database's
answers to stable codes. User-facing words for those codes live in the
frontend and are the founder's (N10).

DARK. `Config.MLC2_TRAINING_SWITCH_ENABLED` is a code constant, False until P5,
and the route answers 410 while it is. Behind it the database holds no
training policy, so there is nothing to turn on.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

SOURCE_ROUTE = "/v2/user/training-consent"
CONTROL = "training_toggle"

#: Database refusals the person can act on, and what the route answers.
_REFUSALS = {
    "TRAINING_CONSENT_NEEDS_POLICY_RECEIPT": ("REACCEPT_REQUIRED", 409),
    "TRAINING_CONSENT_DOES_NOT_MATCH_APPROVAL": ("TRAINING_COPY_CHANGED", 409),
    "TRAINING_POLICY_NOT_ACTIVE": ("TRAINING_NOT_AVAILABLE", 409),
}


class TrainingSwitchError(Exception):
    def __init__(self, code: str, status: int) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


def switch_enabled() -> bool:
    from config import Config

    return getattr(Config, "MLC2_TRAINING_SWITCH_ENABLED", False) is True


def _read(database: Any, owner_id: str) -> tuple[dict | None, dict]:
    policy = database.get_active_training_consent_policy()
    if not policy:
        return None, {"available": False, "active": False}
    status = database.get_mlc2_training_consent_status(owner_id)
    if status is None:
        raise TrainingSwitchError("TRAINING_STATUS_UNAVAILABLE", 503)
    return policy, {
        "available": True,
        "active": status.get("active") is True,
        "policy_version": policy["version"],
        "copy": policy["onboarding_copy"],
        "copy_sha256": policy["approved_copy_sha256"],
    }


def _key(body: Any) -> str:
    key = str((body or {}).get("idempotency_key") or "").strip() \
        if isinstance(body, dict) else ""
    if not key or len(key) > 200:
        raise TrainingSwitchError("INVALID_INPUT", 400)
    return key


def _refused(error: Exception) -> TrainingSwitchError:
    text = str(error)
    for marker, (code, status) in _REFUSALS.items():
        if marker in text:
            return TrainingSwitchError(code, status)
    return TrainingSwitchError("TRAINING_SWITCH_FAILED", 500)


def handle(database: Any, owner_id: str, method: str, body: Any,
           client_version: str) -> dict:
    """GET reads, POST turns on, DELETE turns off. Returns the new state."""
    policy, state = _read(database, owner_id)
    if method == "GET":
        return state
    key = _key(body)
    now = datetime.now(timezone.utc).isoformat()
    if method == "POST":
        if policy is None:
            raise TrainingSwitchError("TRAINING_NOT_AVAILABLE", 409)
        if body.get("accepted") is not True:
            raise TrainingSwitchError("EXPLICIT_CONSENT_REQUIRED", 400)
        if (body.get("policy_version") != policy["version"]
                or body.get("copy_sha256") != policy["approved_copy_sha256"]):
            raise TrainingSwitchError("TRAINING_COPY_CHANGED", 409)
        if not state["active"]:
            _turn_on(database, owner_id, policy, key, now, client_version)
    elif method == "DELETE":
        _turn_off(database, owner_id, key, now, client_version)
    return _read(database, owner_id)[1]


def _turn_on(database: Any, owner_id: str, policy: dict, key: str, now: str,
             client_version: str) -> None:
    try:
        recorded = database.record_mlc2_training_consent_grant(
            acquisition_principal_id=owner_id,
            consent_policy_version=policy["version"],
            terms_version=policy["terms_version"],
            privacy_policy_version=policy["privacy_policy_version"],
            source_route=SOURCE_ROUTE, client_version=client_version,
            affirmative_action={
                "accepted": True, "control": CONTROL,
                "copy_sha256": policy["approved_copy_sha256"],
                "preselected": False,
            },
            occurred_at=now, idempotency_key=key)
    except Exception as error:  # noqa: BLE001 — mapped to a stable code
        raise _refused(error) from error
    if not recorded:
        raise TrainingSwitchError("TRAINING_SWITCH_FAILED", 500)


def _turn_off(database: Any, owner_id: str, key: str, now: str,
              client_version: str) -> None:
    status = database.get_mlc2_training_consent_status(owner_id) or {}
    grant_event_id = str(status.get("grant_event_id") or "")
    if status.get("active") is True and grant_event_id:
        try:
            recorded = database.record_mlc2_training_consent_withdrawal(
                acquisition_principal_id=owner_id,
                grant_event_id=grant_event_id, source_route=SOURCE_ROUTE,
                client_version=client_version,
                affirmative_action={"accepted": False, "control": CONTROL},
                occurred_at=now, idempotency_key=key)
        except Exception as error:  # noqa: BLE001
            raise _refused(error) from error
        if not recorded:
            raise TrainingSwitchError("TRAINING_SWITCH_FAILED", 500)
    # Always, even when already off: a retry must still reach any copy a
    # lost message left due. The worker's sweep is the backstop.
    from services.training_corpus import enqueue_corpus_purge

    enqueue_corpus_purge(owner_id)
