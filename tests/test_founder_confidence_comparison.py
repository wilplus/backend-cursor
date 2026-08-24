from services.founder_confidence_comparison import (
    build_founder_comparison,
    is_founder_comparison_email,
)
from flask import Flask, request
from routes.v2 import coach as coach_routes


def test_founder_email_is_exact_and_case_insensitive():
    assert is_founder_comparison_email("ARTUR@WILLONSKI.COM")
    assert not is_founder_comparison_email("coach@example.com")
    assert not is_founder_comparison_email(None)


def test_comparison_emits_only_the_callers_already_labelled_rows():
    snippets = [
        {"id": "one", "transcript": "first"},
        {"id": "two", "transcript": "second"},
    ]
    labels = {
        "one": [{
            "rater_id": "artur",
            "value": "yes",
            "machine_value": "yes",
            "updated_at": "2026-01-01",
        }],
        "two": [{
            "rater_id": "somebody-else",
            "value": "no",
            "machine_value": "yes",
        }],
    }
    result = build_founder_comparison(
        snippets, labels, rater_id="artur",
    )
    assert [row["snippet_id"] for row in result["rows"]] == ["one"]
    assert result["summary"] == {
        "labelled": 1,
        "comparable": 1,
        "same": 1,
        "different": 0,
        "both_confident": 1,
    }


def test_unrateable_and_missing_machine_state_are_not_fake_disagreements():
    result = build_founder_comparison(
        [{"id": "one"}, {"id": "two"}],
        {
            "one": [{
                "rater_id": "artur",
                "unrateable": True,
                "machine_value": "yes",
            }],
            "two": [{
                "rater_id": "artur",
                "value": "no",
                "machine_value": None,
            }],
        },
        rater_id="artur",
    )
    assert result["summary"]["comparable"] == 0
    assert all(row["agreement"] is None for row in result["rows"])


def test_comparison_route_denies_every_other_coach_before_data_access():
    app = Flask(__name__)
    with app.test_request_context():
        request.user_id = "coach"
        request.token_payload = {"email": "coach@example.com"}
        response, status = (
            coach_routes.v2_coach_confidence_comparison.__wrapped__("sid")
        )
    assert status == 403
    assert response.get_json()["code"] == "FORBIDDEN"


def test_founder_route_emits_only_own_committed_rows(monkeypatch):
    monkeypatch.setattr(
        coach_routes.db,
        "v2_get_session_by_id",
        lambda _sid: {"id": "sid", "source": "training_import"},
    )
    monkeypatch.setattr(
        coach_routes.db,
        "get_snippets_by_session",
        lambda _sid: [
            {"id": "one", "transcript": "first"},
            {"id": "two", "transcript": "second"},
        ],
    )
    monkeypatch.setattr(
        coach_routes,
        "_confidence_queue_selection",
        lambda _sid, _session, snippets: snippets,
    )
    monkeypatch.setattr(
        coach_routes.db,
        "get_confidence_labels_by_snippet_ids",
        lambda _ids: {
            "one": [{
                "rater_id": "founder-id",
                "value": "yes",
                "machine_value": "no",
            }],
            "two": [{
                "rater_id": "another-coach",
                "value": "yes",
                "machine_value": "yes",
            }],
        },
    )
    app = Flask(__name__)
    with app.test_request_context():
        request.user_id = "founder-id"
        request.token_payload = {"email": "artur@willonski.com"}
        response, status = (
            coach_routes.v2_coach_confidence_comparison.__wrapped__("sid")
        )
    body = response.get_json()
    assert status == 200
    assert [row["snippet_id"] for row in body["rows"]] == ["one"]
    assert body["summary"]["different"] == 1
