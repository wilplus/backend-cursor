from contextlib import contextmanager
from unittest.mock import Mock, patch

import pytest

from services.take_lifecycle import (
    TakeLifecycleError,
    confidence_source_manifest,
    confidence_prior_learning_writes_enabled,
    promote_attempt,
)


def test_disabled_flag_builds_nothing_and_uses_existing_promotion():
    database = Mock()
    database.promote_recording_attempt_to_take.return_value = {
        "take_id": "take-1"
    }
    with patch(
        "config.Config.MLC2_CONFIDENCE_CUTOVER_MODE", "dark"
    ):
        assert confidence_source_manifest(
            audio_bytes=b"audio", bucket="bucket", object_key="key",
            filename="take.webm",
        ) is None
        result = promote_attempt(
            database=database, attempt_id="attempt-1", result={"ok": True}
        )
    assert result == {"take_id": "take-1"}
    database.promote_recording_attempt_to_take.assert_called_once()
    database.promote_recording_attempt_with_confidence_outbox.assert_not_called()


OWNER = "11111111-1111-4111-8111-111111111111"
SOURCE = {
    "source_schema_version": "confidence-source-audio-v1",
    "audio": {"object_store": "cloudflare_r2"},
}


@contextmanager
def _canary(ring_on):
    """founder_canary with the ring's answer for the attempt's owner."""
    with patch("config.Config.MLC2_CONFIDENCE_CUTOVER_MODE", "founder_canary"), \
            patch("services.rings.confidence_writer_killed", lambda **_k: False), \
            patch("services.rings.feature_is_on", ring_on):
        yield


def _eligible_database():
    database = Mock()
    database.get_recording_attempt_owner_principal.return_value = OWNER
    return database


def test_rehearsed_enabled_branch_uses_only_atomic_producer_rpc():
    database = _eligible_database()
    database.promote_recording_attempt_with_confidence_outbox.return_value = {
        "take_id": "take-1", "outbox_event_id": "event-1"
    }
    asked = []
    ring_on = lambda feature, owner, **_k: asked.append((feature, owner)) or True  # noqa: E731
    with _canary(ring_on):
        result = promote_attempt(
            database=database, attempt_id="attempt-1", result={"ok": True},
            confidence_producer_manifest=SOURCE,
        )
    assert result["outbox_event_id"] == "event-1"
    assert asked == [("confidence_learning_writes", OWNER)]
    database.promote_recording_attempt_to_take.assert_not_called()
    database.promote_recording_attempt_with_confidence_outbox.assert_called_once()


def test_rehearsed_enabled_branch_fails_before_promotion_without_source():
    database = _eligible_database()
    with _canary(lambda *_a, **_k: True), pytest.raises(TakeLifecycleError, match="source manifest"):
        promote_attempt(
            database=database, attempt_id="attempt-1", result={"ok": True}
        )
    database.promote_recording_attempt_to_take.assert_not_called()
    database.promote_recording_attempt_with_confidence_outbox.assert_not_called()


# THE RING SAYS WHO (production, 2026-10-03: "confidence producer requires a
# resolved speaker" on every Take of a speaker the pipe was never open for).

def test_a_speaker_the_ring_does_not_name_is_promoted_plainly():
    database = _eligible_database()
    database.promote_recording_attempt_to_take.return_value = {"take_id": "take-1"}
    with _canary(lambda *_a, **_k: False):
        result = promote_attempt(
            database=database, attempt_id="attempt-1", result={"ok": True},
            confidence_producer_manifest=SOURCE,
        )
    assert result == {"take_id": "take-1"}
    database.promote_recording_attempt_with_confidence_outbox.assert_not_called()
    database.promote_recording_attempt_to_take.assert_called_once()


def test_a_speaker_the_ring_does_not_name_needs_no_source_manifest():
    database = _eligible_database()
    database.promote_recording_attempt_to_take.return_value = {"take_id": "take-1"}
    with _canary(lambda *_a, **_k: False):
        result = promote_attempt(
            database=database, attempt_id="attempt-1", result={"ok": True},
        )
    assert result == {"take_id": "take-1"}


def test_an_unknown_owner_or_unreadable_ring_is_promoted_plainly():
    database = Mock()
    database.get_recording_attempt_owner_principal.return_value = ""
    database.promote_recording_attempt_to_take.return_value = {"take_id": "take-1"}
    asked = []
    with _canary(lambda *a, **_k: asked.append(a) or True):
        result = promote_attempt(
            database=database, attempt_id="attempt-1", result={"ok": True},
        )
    assert result == {"take_id": "take-1"}
    assert asked == []
    database.promote_recording_attempt_with_confidence_outbox.assert_not_called()


def test_a_refused_canonical_promotion_still_yields_a_take(caplog):
    database = _eligible_database()
    database.promote_recording_attempt_with_confidence_outbox.return_value = None
    database.promote_recording_attempt_to_take.return_value = {"take_id": "take-1"}
    with _canary(lambda *_a, **_k: True):
        result = promote_attempt(
            database=database, attempt_id="attempt-1", result={"ok": True},
            confidence_producer_manifest=SOURCE,
        )
    assert result == {"take_id": "take-1"}
    database.promote_recording_attempt_with_confidence_outbox.assert_called_once()
    database.promote_recording_attempt_to_take.assert_called_once()
    assert "canonical promotion refused attempt=attempt-1" in caplog.text


def test_both_promotions_refusing_is_still_a_hard_failure():
    database = _eligible_database()
    database.promote_recording_attempt_with_confidence_outbox.return_value = None
    database.promote_recording_attempt_to_take.return_value = None
    with _canary(lambda *_a, **_k: True), pytest.raises(TakeLifecycleError, match="not promoted"):
        promote_attempt(
            database=database, attempt_id="attempt-1", result={"ok": True},
            confidence_producer_manifest=SOURCE,
        )


def test_legacy_feedback_shadow_is_disabled_by_the_same_flag():
    # The `changes` block moved out of the route in Phase 5 (audit Q-C1);
    # its orchestrator holds the one writer gate.
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "services" / "ideal_text_changes.py"
    ).read_text()
    condition = "and confidence_prior_learning_writes_enabled()"
    assert condition in source
    assert source.index(condition) < source.index(
        "db.record_canonical_feedback_exposure(",
        source.index(condition),
    )


@pytest.mark.parametrize(
    "mode,canonical_enabled,prior_enabled",
    [
        ("dark", False, True),
        ("founder_canary", True, False),
        ("killed", False, False),
        ("invalid", False, False),
    ],
)
def test_one_mode_atomically_selects_both_writer_boundaries(
    mode, canonical_enabled, prior_enabled,
):
    from services.take_lifecycle import confidence_canonical_writes_enabled

    with patch("config.Config.MLC2_CONFIDENCE_CUTOVER_MODE", mode):
        assert confidence_canonical_writes_enabled() is canonical_enabled
        assert confidence_prior_learning_writes_enabled() is prior_enabled


def test_kill_switch_does_not_reactivate_prior_learning_writes():
    with patch(
        "config.Config.MLC2_CONFIDENCE_CUTOVER_MODE", "founder_canary"
    ):
        assert confidence_prior_learning_writes_enabled() is False
    with patch("config.Config.MLC2_CONFIDENCE_CUTOVER_MODE", "killed"):
        assert confidence_prior_learning_writes_enabled() is False
