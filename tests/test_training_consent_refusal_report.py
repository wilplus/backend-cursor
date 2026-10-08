"""A refused training switch is visible: logged and sent to Sentry by code.

The HTTP answer stays the code and the status the switch already chose.
The report never carries a person's id (the frontend has no Sentry).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from flask import Flask, request

import routes.v2.training_consent as route
from services.training_consent import TrainingSwitchError


@pytest.mark.parametrize(
    "code",
    ["REACCEPT_REQUIRED", "TRAINING_COPY_CHANGED", "TRAINING_NOT_AVAILABLE"],
)
def test_a_refusal_is_reported_by_code(code: str) -> None:
    app = Flask(__name__)
    with patch.object(route, "switch_enabled", return_value=True), \
            patch.object(route, "_repository") as repo, \
            patch.object(route, "identity_coordinates", return_value={}), \
            patch.object(route, "handle",
                         side_effect=TrainingSwitchError(code, 409)), \
            patch.object(route.logger, "warning") as warned, \
            patch.object(route.sentry_sdk, "capture_message") as capture:
        repo.owner_for_user.return_value = MagicMock(id="owner-1")
        with app.test_request_context(
                "/v2/user/training-consent", method="POST", json={}):
            request.user_id = "u-1"
            response, status = route.v2_user_training_consent.__wrapped__()
    assert status == 409
    assert response.get_json() == {"code": code}
    warned.assert_called_once_with("training switch refused: %s", code)
    capture.assert_called_once_with(
        f"training switch refused: {code}", level="warning")
    message = capture.call_args.args[0]
    assert "u-1" not in message
    assert "owner-1" not in message


def test_disabled_switch_answers_410_and_does_not_report() -> None:
    app = Flask(__name__)
    with patch.object(route, "switch_enabled", return_value=False), \
            patch.object(route.sentry_sdk, "capture_message") as capture:
        with app.test_request_context(
                "/v2/user/training-consent", method="POST", json={}):
            response, status = route.v2_user_training_consent.__wrapped__()
    assert status == 410
    assert response.get_json() == {"code": "TRAINING_SWITCH_DISABLED"}
    capture.assert_not_called()


def test_status_unavailable_is_reported_and_answered_503() -> None:
    code = "TRAINING_STATUS_UNAVAILABLE"
    app = Flask(__name__)
    with patch.object(route, "switch_enabled", return_value=True), \
            patch.object(route, "_repository") as repo, \
            patch.object(route, "identity_coordinates", return_value={}), \
            patch.object(route, "handle",
                         side_effect=TrainingSwitchError(code, 503)), \
            patch.object(route.logger, "warning") as warned, \
            patch.object(route.sentry_sdk, "capture_message") as capture:
        repo.owner_for_user.return_value = MagicMock(id="owner-1")
        with app.test_request_context(
                "/v2/user/training-consent", method="GET"):
            request.user_id = "u-1"
            response, status = route.v2_user_training_consent.__wrapped__()
    assert status == 503
    assert response.get_json() == {"code": code}
    warned.assert_called_once_with("training switch refused: %s", code)
    capture.assert_called_once_with(
        f"training switch refused: {code}", level="warning")
    message = capture.call_args.args[0]
    assert "u-1" not in message
    assert "owner-1" not in message
