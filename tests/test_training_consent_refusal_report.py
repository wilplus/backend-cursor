"""
STORY    As the founder, I want a refused training switch to show up in the
         logs and Sentry without the person's id, so that problems are
         visible and private.
OUTCOME
  O1  When the training status cannot be read, the speaker gets "service
      unavailable" (503) with the refusal code.
  O2  One warning is logged and one Sentry message sent, naming the code
      and never the user or owner id.
PROVES   O1 -> test_status_unavailable_is_reported_and_answered_503
         O2 -> test_status_unavailable_is_reported_and_answered_503
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from flask import Flask, request

import routes.v2.training_consent as route
from services.training_consent import TrainingSwitchError


def test_status_unavailable_is_reported_and_answered_503() -> None:
    code = "TRAINING_STATUS_UNAVAILABLE"
    app = Flask(__name__)
    with patch.object(route, "_repository") as repo, \
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
