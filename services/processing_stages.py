"""Durable, idempotent provenance for one processing-stage attempt.

The existing ``processing_jobs`` row remains the live polling contract during
the parity window. This recorder dual-writes a stricter owner/project/take
ledger without changing pipeline control flow: database failures are logged,
while the real stage exception always propagates unchanged.
"""
from __future__ import annotations

from contextlib import contextmanager
import logging
from typing import Any, Iterator, Optional

from services.feedback_data_contract import content_hash


logger = logging.getLogger(__name__)

CANONICAL_STAGES = frozenset({
    "upload",
    "transcription",
    "alignment",
    "feature_extraction",
    "candidate_generation",
    "manager_selection",
    "exposure",
    "human_decisions",
    "derived_state",
})


class ProcessingStageRecorder:
    """Bind all stage writes to one verified Take attempt."""

    def __init__(
        self, *, database: Any, owner_principal_id: str, project_id: str,
        take_id: str, attempt_count: int = 1,
        processing_job_id: Optional[str] = None, input_provenance: Any = None,
    ) -> None:
        self._db = database
        self.owner_principal_id = str(owner_principal_id or "")
        self.project_id = str(project_id or "")
        self.take_id = str(take_id or "")
        self.processing_job_id = (
            str(processing_job_id) if processing_job_id else None
        )
        self.attempt_count = (
            int(attempt_count)
            if isinstance(attempt_count, int)
            and not isinstance(attempt_count, bool) and attempt_count > 0
            else 1
        )
        self.input_hash = content_hash(input_provenance or {
            "take_id": self.take_id,
            "attempt_count": self.attempt_count,
        })

    @property
    def enabled(self) -> bool:
        return bool(
            self._db and self.owner_principal_id
            and self.project_id and self.take_id
        )

    def _key(self, stage: str) -> str:
        job_coordinate = self.processing_job_id or self.take_id
        return (
            f"processing-stage:{job_coordinate}:"
            f"{self.attempt_count}:{stage}"
        )

    def record(
        self, stage: str, status: str, *, output: Any = None,
        error: Optional[BaseException] = None,
    ) -> Optional[dict]:
        if not self.enabled or stage not in CANONICAL_STAGES:
            return None
        output_hash = (
            content_hash(output) if output is not None else None
        )
        error_payload = None
        if error is not None:
            error_payload = {
                "type": type(error).__name__,
                "message": str(error)[:500],
            }
        return self._db.record_canonical_processing_stage(
            processing_job_id=self.processing_job_id,
            owner_principal_id=self.owner_principal_id,
            project_id=self.project_id,
            take_id=self.take_id,
            stage=stage,
            status=status,
            attempt_count=self.attempt_count,
            input_hash=self.input_hash,
            output_hash=output_hash,
            idempotency_key=self._key(stage),
            error=error_payload,
        )

    @contextmanager
    def stage(self, stage: str) -> Iterator[None]:
        """Record running/terminal states while preserving the real error."""
        self.record(stage, "running")
        try:
            yield
        except BaseException as stage_error:
            self.record(stage, "failed", error=stage_error)
            raise
        else:
            self.record(stage, "succeeded")


def recorder_for_take(
    *, database: Any, session: dict, attempt_count: int = 1,
    processing_job_id: Optional[str] = None, input_provenance: Any = None,
) -> Optional[ProcessingStageRecorder]:
    """Return a recorder only after all canonical ownership IDs are known."""
    if not isinstance(session, dict):
        return None
    owner = session.get("owner_principal_id")
    project = session.get("project_id")
    take = session.get("id")
    if not all((owner, project, take)):
        return None
    return ProcessingStageRecorder(
        database=database,
        owner_principal_id=str(owner),
        project_id=str(project),
        take_id=str(take),
        attempt_count=attempt_count,
        processing_job_id=processing_job_id,
        input_provenance=input_provenance,
    )
