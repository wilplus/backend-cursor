from unittest.mock import patch

from flask import Flask, request

from routes.v2.learning_exposures import v2_ack_learning_exposure


PRESENTATION = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
TOKEN = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
RENDER = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"


def _call(body, *, user_id="dddddddd-dddd-4ddd-8ddd-dddddddddddd"):
    app = Flask(__name__)
    with app.test_request_context(method="POST", json=body):
        request.user_id = user_id
        return v2_ack_learning_exposure.__wrapped__()


def test_owner_ack_actor_is_taken_from_auth_not_the_request_body():
    body = {
        "presentation_id": PRESENTATION,
        "acknowledgement_token": TOKEN,
        "actor_role": "owner",
        "render_instance_id": RENDER,
    }
    with patch(
        "routes.v2.learning_exposures.acknowledge_visible_render",
        return_value={
            "exposure_receipt_id": "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
            "learning_surface": "confidence_classification",
            "replayed": False,
        },
    ) as acknowledge:
        response, status = _call(body)

    assert status == 200
    assert response.get_json()["acknowledged"] is True
    assert acknowledge.call_args.kwargs["actor_id"] == (
        "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    )


def test_client_cannot_supply_or_override_actor_identity():
    response, status = _call({
        "presentation_id": PRESENTATION,
        "acknowledgement_token": TOKEN,
        "actor_role": "owner",
        "actor_id": "ffffffff-ffff-4fff-8fff-ffffffffffff",
        "render_instance_id": RENDER,
    })
    assert status == 400
    assert response.get_json()["code"] == "INVALID_INPUT"


def test_non_coach_cannot_ack_a_coach_packet_even_with_payload_coordinates():
    with patch("routes.v2.learning_exposures.is_coach", return_value=False), \
            patch(
                "routes.v2.learning_exposures.acknowledge_visible_render"
            ) as acknowledge:
        response, status = _call({
            "presentation_id": PRESENTATION,
            "acknowledgement_token": TOKEN,
            "actor_role": "coach",
            "render_instance_id": RENDER,
        })
    assert status == 404
    acknowledge.assert_not_called()
