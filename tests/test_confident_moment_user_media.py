from __future__ import annotations

from services.confident_moment_user_media import (
    BufferedPlaybackAdmission,
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
