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


def test_rehearsed_enabled_branch_uses_only_atomic_producer_rpc():
    database = Mock()
    database.promote_recording_attempt_with_confidence_outbox.return_value = {
        "take_id": "take-1", "outbox_event_id": "event-1"
    }
    source = {
        "source_schema_version": "confidence-source-audio-v1",
        "audio": {"object_store": "cloudflare_r2"},
    }
    with patch(
        "config.Config.MLC2_CONFIDENCE_CUTOVER_MODE", "founder_canary"
    ):
        result = promote_attempt(
            database=database, attempt_id="attempt-1", result={"ok": True},
            confidence_producer_manifest=source,
        )
    assert result["outbox_event_id"] == "event-1"
    database.promote_recording_attempt_to_take.assert_not_called()
    database.promote_recording_attempt_with_confidence_outbox.assert_called_once()


def test_rehearsed_enabled_branch_fails_before_promotion_without_source():
    database = Mock()
    with patch(
        "config.Config.MLC2_CONFIDENCE_CUTOVER_MODE", "founder_canary"
    ), pytest.raises(TakeLifecycleError, match="source manifest"):
        promote_attempt(
            database=database, attempt_id="attempt-1", result={"ok": True}
        )
    database.promote_recording_attempt_to_take.assert_not_called()
    database.promote_recording_attempt_with_confidence_outbox.assert_not_called()


def test_legacy_feedback_shadow_is_disabled_by_the_same_flag():
    source = (
        __import__("pathlib").Path(__file__).resolve().parents[1]
        / "routes" / "v2" / "explore_ideal_text.py"
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
