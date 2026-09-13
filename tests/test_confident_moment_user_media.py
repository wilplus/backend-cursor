from __future__ import annotations

from hashlib import sha256
from unittest.mock import MagicMock

import pytest
from flask import Flask, request

from services.confident_moment_user_media import (
    BufferedPlaybackAdmission,
    ConfidentMomentSourceMediaPolicyInvalid,
    ConfidentMomentUserReadRetry,
    MAX_SOURCE_BYTES,
    R2ExactPrivateObjectReader,
    load_confident_moment_source_bytes,
    validate_and_consume_emit_authorization,
    validate_exercise_correlation,
)


IDS = {
    name: f"00000000-0000-0000-0000-{number:012d}"
    for number, name in enumerate((
        "principal", "bundle", "attachment", "project", "take", "membership",
        "candidate", "evidence", "presentation", "attempt", "lineage",
        "media", "rollout", "enrollment", "policy", "receipt", "offer",
        "response", "candidate_set", "authorization", "speaker_binding",
    ), 1)
}


def authority(*, digest: str = "a" * 64, size: int = 3) -> dict:
    return {
        "contract_version": "confident-moment-source-playback-authority-v1",
        "authority_sha256": digest,
        "acquisition_principal_id": IDS["principal"],
        "bundle_id": IDS["bundle"],
        "bundle_attachment_id": IDS["attachment"],
        "project_id": IDS["project"],
        "source_take_id": IDS["take"],
        "feedback_membership_id": IDS["membership"],
        "feedback_candidate_id": IDS["candidate"],
        "evidence_span_id": IDS["evidence"],
        "canonical_feedback_presentation_id": IDS["presentation"],
        "recording_attempt_id": IDS["attempt"],
        "audio_lineage_id": IDS["lineage"],
        "media_object_id": IDS["media"],
        "bucket": "private-practice",
        "object_key": "opaque/object.webm",
        "object_version": "version-1",
        "byte_size": size,
        "exact_bytes_sha256": (
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        ),
        "content_type": "audio/webm",
        "rollout_revision_id": IDS["rollout"],
        "enrollment_revision_id": IDS["enrollment"],
        "policy_id": IDS["policy"],
        "authorization_receipt_id": IDS["receipt"],
        "dataset_eligible": False,
    }


def emit_authorization(
    request_id: str, *, authority_digest: str = "a" * 64,
    buffered_digest: str | None = None,
) -> dict:
    return {
        "contract_version": "confident-moment-source-playback-emit-v1",
        "playback_request_id": request_id,
        "acquisition_principal_id": IDS["principal"],
        "bundle_id": IDS["bundle"],
        "bundle_attachment_id": IDS["attachment"],
        "authority_sha256": authority_digest,
        "buffered_bytes_sha256": buffered_digest or authority()[
            "exact_bytes_sha256"
        ],
        "authorized_at": "2026-09-12T12:00:00Z",
        "emit_authorized": True,
        "dataset_eligible": False,
        "emit_authorization_sha256": "d" * 64,
    }


class Reader:
    def __init__(self, body: bytes = b"abc", error: Exception | None = None):
        self.body = body
        self.error = error
        self.calls = 0

    def read_exact(self, **_kwargs) -> bytes:
        self.calls += 1
        if self.error:
            raise self.error
        return self.body


class Stream:
    def __init__(self, body: bytes, *, after_read=None):
        self.body = body
        self.position = 0
        self.read_calls = 0
        self.closed = False
        self.after_read = after_read

    def read(self, amount: int) -> bytes:
        self.read_calls += 1
        result = self.body[self.position:self.position + amount]
        self.position += len(result)
        if self.after_read is not None:
            self.after_read()
        return result

    def close(self) -> None:
        self.closed = True


def exact_r2_reader(content_length, stream):
    client = MagicMock()
    client.get_object.return_value = {
        "ContentLength": content_length, "Body": stream,
    }
    return R2ExactPrivateObjectReader(
        client_provider=lambda: client,
        bucket_provider=lambda: "private-practice",
    ), client


def run(
    *, resolve=None, authorize=None, reader=None, admission=None,
    monotonic=None, sleep=None,
):
    values = iter(resolve or [authority()])
    return load_confident_moment_source_bytes(
        resolve_authority=lambda: next(values),
        authorize_emit=(
            authorize
            or (lambda expected, buffered, request_id: emit_authorization(
                request_id, authority_digest=expected,
                buffered_digest=buffered,
            ))
        ),
        principal_id=IDS["principal"], bundle_id=IDS["bundle"],
        attachment_id=IDS["attachment"], reader=reader or Reader(),
        admission=admission or BufferedPlaybackAdmission(),
        **({"monotonic": monotonic} if monotonic else {}),
        **({"sleep": sleep} if sleep else {}),
        jitter=lambda _a, _b: 0.0,
    )


def test_three_phase_success_reads_once_and_releases_exact_reservation():
    admission = BufferedPlaybackAdmission()
    reader = Reader()
    body, content_type = run(reader=reader, admission=admission)
    assert body == b"abc"
    assert content_type == "audio/webm"
    assert reader.calls == 1
    assert admission.snapshot() == (0, 0)


@pytest.mark.parametrize(
    "reader",
    [
        Reader(body=b"ab"),
        Reader(body=b"abcd"),
        Reader(body=b"abd"),
        Reader(error=RuntimeError("provider failed")),
        Reader(error=KeyboardInterrupt()),
    ],
)
def test_every_phase_two_failure_releases_admission(reader):
    admission = BufferedPlaybackAdmission()
    with pytest.raises(BaseException):
        run(reader=reader, admission=admission)
    assert admission.snapshot() == (0, 0)


def test_provider_failure_is_typed_retry_and_releases_admission():
    admission = BufferedPlaybackAdmission()
    with pytest.raises(ConfidentMomentUserReadRetry):
        run(reader=Reader(error=TimeoutError("R2 timeout")), admission=admission)
    assert admission.snapshot() == (0, 0)


@pytest.mark.parametrize("content_length", [None, "3", True, 2, 4])
def test_r2_content_length_must_be_exact_integer_before_body_read(
    content_length,
):
    stream = Stream(b"abc")
    reader, _client = exact_r2_reader(content_length, stream)
    with pytest.raises(ConfidentMomentSourceMediaPolicyInvalid):
        reader.read_exact(
            bucket="private-practice", object_key="opaque", byte_size=3,
            expected_sha256=authority()["exact_bytes_sha256"],
        )
    assert stream.read_calls == 0


def test_r2_bounded_read_has_no_extra_byte_probe_and_closes_stream():
    stream = Stream(b"abcX")
    reader, client = exact_r2_reader(3, stream)
    assert reader.read_exact(
        bucket="private-practice", object_key="opaque", byte_size=3,
        expected_sha256=authority()["exact_bytes_sha256"],
    ) == b"abc"
    assert stream.read_calls == 1
    assert stream.position == 3
    assert stream.closed
    client.get_object.assert_called_once_with(
        Bucket="private-practice", Key="opaque",
    )


@pytest.mark.parametrize(
    ("body", "digest"),
    [(b"ab", authority()["exact_bytes_sha256"]), (b"abd", "a" * 64)],
)
def test_r2_short_stream_and_hash_mismatch_are_terminal(body, digest):
    stream = Stream(body)
    reader, _client = exact_r2_reader(3, stream)
    with pytest.raises(ConfidentMomentSourceMediaPolicyInvalid):
        reader.read_exact(
            bucket="private-practice", object_key="opaque", byte_size=3,
            expected_sha256=digest,
        )
    assert stream.closed


def test_r2_slow_progress_hits_internal_deadline_and_closes_stream():
    now = [0.0]
    stream = Stream(b"abc", after_read=lambda: now.__setitem__(0, 7.5))
    reader, _client = exact_r2_reader(3, stream)
    with pytest.raises(ConfidentMomentUserReadRetry):
        reader.read_exact(
            bucket="private-practice", object_key="opaque", byte_size=3,
            expected_sha256=authority()["exact_bytes_sha256"],
            monotonic=lambda: now[0],
        )
    assert stream.closed


def test_foreign_emit_authorization_discards_buffer_without_reread():
    reader = Reader()
    admission = BufferedPlaybackAdmission()
    with pytest.raises(ConfidentMomentSourceMediaPolicyInvalid):
        run(reader=reader, admission=admission, authorize=lambda *_args: (
            emit_authorization(str(_args[2]), authority_digest="b" * 64)
        ))
    assert reader.calls == 1
    assert admission.snapshot() == (0, 0)


def test_phase_three_retries_at_most_twice_without_reread():
    reader = Reader()
    admission = BufferedPlaybackAdmission()
    calls = 0

    def authorize(expected, buffered, request_id):
        nonlocal calls
        calls += 1
        raise RuntimeError("CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED")

    with pytest.raises(ConfidentMomentUserReadRetry):
        load_confident_moment_source_bytes(
            resolve_authority=lambda: authority(), authorize_emit=authorize,
            principal_id=IDS["principal"],
            bundle_id=IDS["bundle"], attachment_id=IDS["attachment"],
            reader=reader, admission=admission,
            sleep=lambda _seconds: None, jitter=lambda _a, _b: 0.0,
        )
    assert calls == 2
    assert reader.calls == 1
    assert admission.snapshot() == (0, 0)


def test_phase_three_does_not_start_without_full_budget_inside_ttl():
    clock = iter((0.0, 0.1, 0.1, 1.7))
    calls = 0

    def authorize(_expected, _buffered, request_id):
        nonlocal calls
        calls += 1
        return emit_authorization(request_id)

    with pytest.raises(ConfidentMomentUserReadRetry):
        load_confident_moment_source_bytes(
            resolve_authority=lambda: authority(), authorize_emit=authorize,
            principal_id=IDS["principal"],
            bundle_id=IDS["bundle"], attachment_id=IDS["attachment"],
            reader=Reader(), admission=BufferedPlaybackAdmission(),
            monotonic=lambda: next(clock), sleep=lambda _seconds: None,
            jitter=lambda _a, _b: 0.0,
        )
    assert calls == 0


def test_phase_two_timeout_releases_exact_reservation():
    admission = BufferedPlaybackAdmission()
    clock = iter((0.0, 0.1, 8.01))
    with pytest.raises(ConfidentMomentUserReadRetry):
        run(
            reader=Reader(), admission=admission,
            monotonic=lambda: next(clock),
        )
    assert admission.snapshot() == (0, 0)


def test_phase_three_result_after_buffer_ttl_is_retryable_without_reread():
    now = [0.0]
    reader = Reader()
    calls = 0

    def clock():
        return now[0]

    def authorize(expected, buffered, request_id):
        nonlocal calls
        calls += 1
        if calls == 1:
            now[0] = 2.2
        return emit_authorization(
            request_id, authority_digest=expected, buffered_digest=buffered,
        )

    with pytest.raises(ConfidentMomentUserReadRetry):
        load_confident_moment_source_bytes(
            resolve_authority=lambda: authority(), authorize_emit=authorize,
            principal_id=IDS["principal"],
            bundle_id=IDS["bundle"], attachment_id=IDS["attachment"],
            reader=reader, admission=BufferedPlaybackAdmission(), monotonic=clock,
            sleep=lambda _seconds: None,
        )
    assert calls == 1
    assert reader.calls == 1


def test_emit_authorization_is_request_local_and_one_use():
    request_id = IDS["authorization"]
    authorization = emit_authorization(request_id)
    assert validate_and_consume_emit_authorization(
        authorization, playback_request_id=request_id,
        principal_id=IDS["principal"], bundle_id=IDS["bundle"],
        attachment_id=IDS["attachment"], authority_sha256="a" * 64,
        buffered_body=b"abc", window_started_at=0.0,
        buffer_completed_at=0.0, monotonic=lambda: 0.1,
        already_consumed=False,
    ) is True
    with pytest.raises(ConfidentMomentSourceMediaPolicyInvalid):
        validate_and_consume_emit_authorization(
            authorization, playback_request_id=request_id,
            principal_id=IDS["principal"], bundle_id=IDS["bundle"],
            attachment_id=IDS["attachment"], authority_sha256="a" * 64,
            buffered_body=b"abc", window_started_at=0.0,
            buffer_completed_at=0.0, monotonic=lambda: 0.1,
            already_consumed=True,
        )


@pytest.mark.parametrize(
    ("elapsed", "expected_error"),
    [
        (0.499999, None),
        (0.500001, ConfidentMomentUserReadRetry),
    ],
)
def test_maximum_source_buffer_rehash_obeys_local_emit_window(
    elapsed, expected_error,
):
    """D46's exact 25 MiB boundary remains inside the injected 500 ms clock."""
    body = b"x" * MAX_SOURCE_BYTES
    request_id = IDS["authorization"]
    authorization = emit_authorization(
        request_id,
        buffered_digest=sha256(body).hexdigest(),
    )

    def validate():
        return validate_and_consume_emit_authorization(
            authorization,
            playback_request_id=request_id,
            principal_id=IDS["principal"],
            bundle_id=IDS["bundle"],
            attachment_id=IDS["attachment"],
            authority_sha256="a" * 64,
            buffered_body=body,
            window_started_at=0.0,
            buffer_completed_at=0.0,
            monotonic=lambda: elapsed,
            already_consumed=False,
        )

    if expected_error is None:
        assert validate() is True
    else:
        with pytest.raises(expected_error):
            validate()


@pytest.mark.parametrize(
    "change",
    [
        {"playback_request_id": IDS["offer"]},
        {"authority_sha256": "b" * 64},
        {"buffered_bytes_sha256": "b" * 64},
        {"emit_authorized": False},
        {"leaked": "field"},
    ],
)
def test_foreign_or_open_emit_authorization_never_authorizes(change):
    request_id = IDS["authorization"]
    candidate = {**emit_authorization(request_id), **change}
    with pytest.raises(ConfidentMomentSourceMediaPolicyInvalid):
        validate_and_consume_emit_authorization(
            candidate, playback_request_id=request_id,
            principal_id=IDS["principal"], bundle_id=IDS["bundle"],
            attachment_id=IDS["attachment"], authority_sha256="a" * 64,
            buffered_body=b"abc", window_started_at=0.0,
            buffer_completed_at=0.0, monotonic=lambda: 0.1,
            already_consumed=False,
        )


def test_expired_local_authorization_consumes_attempt_then_retries_once():
    clock = iter((0.0, 0.0, 0.0, 0.0, 0.0, 0.6, 0.6, 0.6, 0.7))
    calls = 0

    def authorize(expected, buffered, request_id):
        nonlocal calls
        calls += 1
        return emit_authorization(
            request_id, authority_digest=expected, buffered_digest=buffered,
        )

    body, _ = load_confident_moment_source_bytes(
        resolve_authority=lambda: authority(), authorize_emit=authorize,
        principal_id=IDS["principal"], bundle_id=IDS["bundle"],
        attachment_id=IDS["attachment"], reader=Reader(),
        admission=BufferedPlaybackAdmission(), monotonic=lambda: next(clock),
        sleep=lambda _seconds: None, jitter=lambda _a, _b: 0.0,
    )
    assert body == b"abc"
    assert calls == 2


def test_admission_enforces_count_bytes_and_policy_then_recovers():
    admission = BufferedPlaybackAdmission()
    first = admission.reserve(MAX_SOURCE_BYTES)
    second = admission.reserve(MAX_SOURCE_BYTES)
    with pytest.raises(ConfidentMomentUserReadRetry):
        admission.reserve(1)
    admission.release(first)
    third = admission.reserve(1)
    admission.release(third)
    admission.release(second)
    assert admission.snapshot() == (0, 0)
    with pytest.raises(ConfidentMomentSourceMediaPolicyInvalid):
        admission.reserve(MAX_SOURCE_BYTES + 1)


def test_admission_rejection_happens_before_object_reader():
    admission = BufferedPlaybackAdmission()
    first = admission.reserve(MAX_SOURCE_BYTES)
    second = admission.reserve(MAX_SOURCE_BYTES)
    reader = Reader()
    try:
        with pytest.raises(ConfidentMomentUserReadRetry):
            run(reader=reader, admission=admission)
        assert reader.calls == 0
    finally:
        admission.release(first)
        admission.release(second)
    assert admission.snapshot() == (0, 0)


def test_many_small_reservations_have_no_count_ceiling():
    admission = BufferedPlaybackAdmission()
    reservations = [admission.reserve(1) for _ in range(100)]
    assert admission.snapshot() == (100, 100)
    for reservation in reservations:
        admission.release(reservation)
    assert admission.snapshot() == (0, 0)


def test_exercise_correlation_closed_shapes():
    empty = {
        "contract_version": "confident-moment-exercise-correlation-v2",
        "status": "not_supplied", "bundle_id": IDS["bundle"],
        "bundle_attachment_id": IDS["attachment"], "offer_id": None,
        "correlation_sha256": "c" * 64, "dataset_eligible": False,
    }
    assert validate_exercise_correlation(
        empty, bundle_id=IDS["bundle"], attachment_id=IDS["attachment"]
    ) == empty
    available = {
        **empty, "status": "available", "offer_id": IDS["offer"],
        "feedback_response_binding_id": IDS["response"],
        "n1_candidate_set_id": IDS["candidate_set"],
        "authorization_check_id": IDS["authorization"],
        "source_acquisition_receipt_id": IDS["receipt"],
        "source_target_speaker_binding_id": IDS["speaker_binding"],
    }
    assert validate_exercise_correlation(
        available, bundle_id=IDS["bundle"], attachment_id=IDS["attachment"]
    ) == available
    with pytest.raises(RuntimeError):
        validate_exercise_correlation(
            {**empty, "object_key": "leak"}, bundle_id=IDS["bundle"],
            attachment_id=IDS["attachment"],
        )
    with pytest.raises(RuntimeError):
        validate_exercise_correlation(
            {**empty, "contract_version": "confident-moment-exercise-correlation-v1"},
            bundle_id=IDS["bundle"], attachment_id=IDS["attachment"],
        )


def _app() -> Flask:
    app = Flask(__name__)
    app.testing = True
    return app


def _raw(handler):
    return handler.__wrapped__.__wrapped__.__wrapped__


@pytest.mark.parametrize(
    "handler_name",
    [
        "get_confident_moment_source_playback",
        "get_confident_moment_exercise_correlation",
    ],
)
def test_new_read_routes_fail_before_auth_or_repository_when_gate_off(
    monkeypatch, handler_name,
):
    import routes.v2.confident_moment_bundles as route

    repository = MagicMock()
    monkeypatch.setattr(route, "runtime_is_enabled", lambda: False)
    monkeypatch.setattr(route, "_repo", repository)
    with _app().test_request_context("/v2/x"):
        response, status = getattr(route, handler_name)(
            IDS["bundle"], IDS["attachment"],
        )
    assert status == 404
    assert response.get_json() == {"code": "CONFIDENT_MOMENT_BUNDLE_DISABLED"}
    repository.assert_not_called()


def test_source_playback_route_is_private_and_never_returns_authority(monkeypatch):
    import routes.v2.confident_moment_bundles as route

    repo = MagicMock()
    monkeypatch.setattr(route, "_repo", lambda: repo)
    monkeypatch.setattr(
        route, "load_confident_moment_source_bytes",
        lambda **_kwargs: (b"abc", "audio/webm"),
    )
    with _app().test_request_context("/v2/x"):
        request.mlc3_principal_id = IDS["principal"]
        response = _raw(route.get_confident_moment_source_playback)(
            IDS["bundle"], IDS["attachment"],
        )
    assert response.data == b"abc"
    assert response.headers["Cache-Control"] == "private, no-store, max-age=0"
    assert response.headers["X-Content-Type-Options"] == "nosniff"


def test_source_playback_retry_is_409_with_no_bytes(monkeypatch):
    import routes.v2.confident_moment_bundles as route

    monkeypatch.setattr(route, "_repo", MagicMock)
    monkeypatch.setattr(
        route, "load_confident_moment_source_bytes",
        MagicMock(side_effect=ConfidentMomentUserReadRetry(
            "CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED"
        )),
    )
    with _app().test_request_context("/v2/x"):
        request.mlc3_principal_id = IDS["principal"]
        response, status = _raw(route.get_confident_moment_source_playback)(
            IDS["bundle"], IDS["attachment"],
        )
    assert status == 409
    assert response.get_json() == {
        "code": "CONFIDENT_MOMENT_USER_READ_RETRY_REQUIRED"
    }
    assert b"abc" not in response.data


def test_source_playback_terminal_failure_has_no_media_bytes(monkeypatch):
    import routes.v2.confident_moment_bundles as route

    monkeypatch.setattr(route, "_repo", MagicMock)
    monkeypatch.setattr(
        route, "load_confident_moment_source_bytes",
        MagicMock(side_effect=ConfidentMomentSourceMediaPolicyInvalid(
            "CONFIDENT_MOMENT_SOURCE_MEDIA_POLICY_INVALID"
        )),
    )
    with _app().test_request_context("/v2/x"):
        request.mlc3_principal_id = IDS["principal"]
        response, status = _raw(route.get_confident_moment_source_playback)(
            IDS["bundle"], IDS["attachment"],
        )
    assert status == 422
    assert response.get_json() == {
        "code": "CONFIDENT_MOMENT_SOURCE_MEDIA_POLICY_INVALID"
    }
    assert b"abc" not in response.data


def test_exercise_route_passes_only_exact_closed_database_result(monkeypatch):
    import routes.v2.confident_moment_bundles as route

    result = {
        "contract_version": "confident-moment-exercise-correlation-v2",
        "status": "not_supplied", "bundle_id": IDS["bundle"],
        "bundle_attachment_id": IDS["attachment"], "offer_id": None,
        "correlation_sha256": "c" * 64, "dataset_eligible": False,
    }
    repo = MagicMock()
    repo.resolve_exercise_offer.return_value = result
    monkeypatch.setattr(route, "_repo", lambda: repo)
    with _app().test_request_context("/v2/x"):
        request.mlc3_principal_id = IDS["principal"]
        response = _raw(route.get_confident_moment_exercise_correlation)(
            IDS["bundle"], IDS["attachment"],
        )
    assert response.get_json() == result
    assert response.headers["Cache-Control"] == "private, no-store, max-age=0"


def test_repository_uses_only_exact_read_rpc_shapes(monkeypatch):
    from services import confident_moment_bundle as bundle_contract
    from services.confident_moment_bundle_repository import (
        ConfidentMomentBundleRepository,
    )

    client = MagicMock()
    transport = MagicMock()
    transport.call.return_value = authority()
    # Patch the class reference owned by the runtime module.  Other tests reload
    # ``config`` and can replace ``config.Config`` without replacing this
    # already-imported reference.
    monkeypatch.setattr(
        bundle_contract.Config, "CONFIDENT_MOMENT_BUNDLE_V1_ENABLED", True,
    )
    repository = ConfidentMomentBundleRepository(
        lambda: client, read_transport_provider=lambda: transport,
    )
    assert repository.resolve_source_playback_authority(
        acquisition_principal_id=IDS["principal"], bundle_id=IDS["bundle"],
        bundle_attachment_id=IDS["attachment"],
    ) == authority()
    transport.call.assert_called_once_with(
        "resolve_confident_moment_source_playback_authority_v1",
        {"p_acquisition_principal_id": IDS["principal"],
         "p_bundle_id": IDS["bundle"],
         "p_bundle_attachment_id": IDS["attachment"]},
    )
    client.rpc.assert_not_called()

    transport.reset_mock()
    transport.call.return_value = emit_authorization(IDS["authorization"])
    repository.authorize_source_playback_emit(
        acquisition_principal_id=IDS["principal"], bundle_id=IDS["bundle"],
        bundle_attachment_id=IDS["attachment"],
        expected_authority_sha256="a" * 64,
        buffered_bytes_sha256=authority()["exact_bytes_sha256"],
        playback_request_id=IDS["authorization"],
    )
    transport.call.assert_called_once_with(
        "authorize_confident_moment_source_playback_emit_v1",
        {
            "p_acquisition_principal_id": IDS["principal"],
            "p_bundle_id": IDS["bundle"],
            "p_bundle_attachment_id": IDS["attachment"],
            "p_expected_authority_sha256": "a" * 64,
            "p_buffered_bytes_sha256": authority()["exact_bytes_sha256"],
            "p_playback_request_id": IDS["authorization"],
        },
    )


def test_dedicated_read_transport_is_one_no_retry_total_deadline_call(
    monkeypatch,
):
    import urllib3
    from services.confident_moment_bundle_repository import (
        ServiceRoleReadRpcTransport,
    )

    response = SimpleResponse(200, authority())
    pool = MagicMock()
    pool.request.return_value = response
    pool_factory = MagicMock(return_value=pool)
    monkeypatch.setattr(urllib3, "PoolManager", pool_factory)

    assert ServiceRoleReadRpcTransport().call("exact_rpc", {"p": "v"}) == authority()
    pool_factory.assert_called_once()
    assert pool_factory.call_args.kwargs["retries"] is False
    assert pool_factory.call_args.kwargs["timeout"].total == 0.5
    pool.request.assert_called_once()
    assert pool.request.call_args.kwargs["retries"] is False
    assert pool.request.call_args.kwargs["timeout"].total == 0.5


def test_dedicated_read_transport_rejects_late_success_without_retry(
    monkeypatch,
):
    import urllib3
    from services.confident_moment_bundle_repository import (
        ServiceRoleReadRpcTransport,
    )

    pool = MagicMock()
    pool.request.return_value = SimpleResponse(200, authority())
    monkeypatch.setattr(urllib3, "PoolManager", MagicMock(return_value=pool))
    clock = iter((0.0, 0.5))
    transport = ServiceRoleReadRpcTransport(monotonic=lambda: next(clock))
    with pytest.raises(ConfidentMomentUserReadRetry):
        transport.call("exact_rpc", {"p": "v"})
    pool.request.assert_called_once()


class SimpleResponse:
    def __init__(self, status: int, value: dict):
        import json

        self.status = status
        self.data = json.dumps(value).encode()
