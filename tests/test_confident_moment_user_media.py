"""
STORY    As a speaker, I want my confident-moment playback to load even if its
         short authorisation expires mid-load, so that I can always hear my
         own moment.
OUTCOME
  O1  An authorisation that expires locally is retried once and the exact
      bytes are returned.
  O2  If the retry expires too, the load fails cleanly with a retry error:
      no bytes, no third attempt, and the buffer reservation is released.
PROVES   O1 -> test_expired_authorization_is_retried_once_and_returns_the_exact_bytes
         O2 -> test_second_expiry_fails_cleanly_without_a_third_attempt
"""
from __future__ import annotations

import pytest

from services.confident_moment_user_media import (
    BufferedPlaybackAdmission,
    ConfidentMomentUserReadRetry,
    load_confident_moment_source_bytes,
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


class Clock:
    """Monotonic clock that stands still unless the database was slow.

    ``slow_answer()`` makes the read right after an authorisation returns jump
    past the local emit window, so that authorisation expires before use.
    """

    def __init__(self) -> None:
        self.now = 0.0
        self._jump = 0.0

    def slow_answer(self) -> None:
        self._jump = 0.6

    def __call__(self) -> float:
        value = self.now
        self.now += self._jump
        self._jump = 0.0
        return value


def _load(*, slow_attempts: set[int]):
    clock = Clock()
    attempts: list[int] = []
    admission = BufferedPlaybackAdmission()

    def authorize(expected, buffered, request_id):
        attempts.append(len(attempts) + 1)
        if len(attempts) in slow_attempts:
            clock.slow_answer()
        return emit_authorization(
            request_id, authority_digest=expected, buffered_digest=buffered,
        )

    def run():
        return load_confident_moment_source_bytes(
            resolve_authority=lambda: authority(), authorize_emit=authorize,
            principal_id=IDS["principal"], bundle_id=IDS["bundle"],
            attachment_id=IDS["attachment"], reader=Reader(),
            admission=admission, monotonic=clock,
            sleep=lambda _seconds: None, jitter=lambda _a, _b: 0.0,
        )

    return run, attempts, admission


def test_expired_authorization_is_retried_once_and_returns_the_exact_bytes():
    run, attempts, admission = _load(slow_attempts={1})
    body, content_type = run()
    assert body == b"abc"
    assert content_type == "audio/webm"
    assert attempts == [1, 2]
    assert admission.snapshot() == (0, 0)


def test_second_expiry_fails_cleanly_without_a_third_attempt():
    run, attempts, admission = _load(slow_attempts={1, 2})
    with pytest.raises(ConfidentMomentUserReadRetry):
        run()
    assert attempts == [1, 2]
    assert admission.snapshot() == (0, 0)
