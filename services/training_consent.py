"""The training switch (SPEC-training-corpus §3, P5 packet §4 item 6). OPEN.

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

OPEN since 2026-10-01 (door 1, the founder's sentence "open door 1";
docs/LEARNING-DOORS.md). `Config.MLC2_TRAINING_SWITCH_ENABLED` is a code
constant, True since then; only a reviewed change setting it back to False
makes the route answer 410 again. The training policy row the yes rests on
(`training-only-v1`) was registered by the founder the same day, per that
document; whenever no training policy is active, `_read` answers
`available: false` and there is nothing to turn on.

THE ONE CONSENT AUTHORITY (founder 2026-10-05, N48.5 Q27 A; migration 0430).
This yes is also what admits a person's Takes into the confidence chain; the
bundled grant no longer does. So turning it on binds the person's speaker
(their verified account identity, ``services.speaker_identity``) in the same
transaction (``accept_mlc2_training_consent_v1``; F-3): the chain and the
speaker-disjoint split both need a speaker. A person who said yes before
0430 is bound the next time their card reads the switch (``_bind_speaker``,
best effort, never a reason for the card to fail). Turning it off is
unchanged.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

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
           client_version: str,
           identity: Optional[tuple[str, str]] = None) -> dict:
    """GET reads, POST turns on, DELETE turns off. Returns the new state.

    ``identity`` is ``(identity_hash, binding_proof_hash)`` from the verified
    token (``services.speaker_identity``). With it, a yes binds the speaker
    in the same transaction, and a yes given before that existed is bound
    when the card next reads the switch."""
    policy, state = _read(database, owner_id)
    if method == "GET":
        if state.get("active"):
            _bind_speaker(database, owner_id, identity)
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
            _turn_on(database, owner_id, policy, key, now, client_version,
                     identity)
        else:
            _bind_speaker(database, owner_id, identity)
    elif method == "DELETE":
        _turn_off(database, owner_id, key, now, client_version)
    return _read(database, owner_id)[1]


def _turn_on(database: Any, owner_id: str, policy: dict, key: str, now: str,
             client_version: str,
             identity: Optional[tuple[str, str]] = None) -> None:
    grant = {
        "acquisition_principal_id": owner_id,
        "consent_policy_version": policy["version"],
        "terms_version": policy["terms_version"],
        "privacy_policy_version": policy["privacy_policy_version"],
        "source_route": SOURCE_ROUTE, "client_version": client_version,
        "affirmative_action": {
            "accepted": True, "control": CONTROL,
            "copy_sha256": policy["approved_copy_sha256"],
            "preselected": False,
        },
        "occurred_at": now, "idempotency_key": key,
    }
    try:
        if identity:
            from services.speaker_identity import BOUND_BY, IDENTITY_VERSION
            recorded = database.accept_mlc2_training_consent(
                **grant, identity_hash=identity[0],
                identity_version=IDENTITY_VERSION,
                binding_proof_hash=identity[1], bound_by=BOUND_BY)
        else:
            recorded = database.record_mlc2_training_consent_grant(**grant)
    except Exception as error:  # noqa: BLE001 — mapped to a stable code
        raise _refused(error) from error
    if not recorded:
        raise TrainingSwitchError("TRAINING_SWITCH_FAILED", 500)


def _bind_speaker(database: Any, owner_id: str,
                  identity: Optional[tuple[str, str]]) -> None:
    """Best effort: bind the speaker of someone who already holds a yes.
    The database writes nothing without an active yes and never rebinds a
    principal; a failure is logged by the seam and never reaches the card."""
    binder = getattr(database, "bind_mlc2_training_speaker", None)
    if not identity or binder is None:
        return
    from services.speaker_identity import BOUND_BY, IDENTITY_VERSION
    try:
        binder(acquisition_principal_id=owner_id, identity_hash=identity[0],
               identity_version=IDENTITY_VERSION,
               binding_proof_hash=identity[1], bound_by=BOUND_BY)
    except Exception:  # noqa: BLE001 — the switch's own answer stands
        return


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
