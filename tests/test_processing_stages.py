from services.processing_stages import ProcessingStageRecorder, recorder_for_take


class _DB:
    def __init__(self):
        self.calls = []

    def record_canonical_processing_stage(self, **kwargs):
        self.calls.append(kwargs)
        return {"status": kwargs["status"]}


def test_stage_attempt_uses_one_idempotency_key_and_monotonic_statuses():
    database = _DB()
    recorder = ProcessingStageRecorder(
        database=database,
        owner_principal_id="owner",
        project_id="project",
        take_id="take",
        attempt_count=2,
        processing_job_id="job",
        input_provenance={"audio": "hash-only-input"},
    )
    with recorder.stage("transcription"):
        pass
    assert [call["status"] for call in database.calls] == [
        "running", "succeeded"]
    assert len({call["idempotency_key"] for call in database.calls}) == 1
    assert database.calls[0]["idempotency_key"].endswith(
        ":2:transcription")


def test_stage_failure_is_recorded_and_original_exception_propagates():
    database = _DB()
    recorder = ProcessingStageRecorder(
        database=database,
        owner_principal_id="owner",
        project_id="project",
        take_id="take",
    )
    try:
        with recorder.stage("alignment"):
            raise RuntimeError("alignment failed")
    except RuntimeError as error:
        assert str(error) == "alignment failed"
    else:
        raise AssertionError("the pipeline exception was swallowed")
    assert database.calls[-1]["status"] == "failed"
    assert database.calls[-1]["error"] == {
        "type": "RuntimeError", "message": "alignment failed"}


def test_recorder_refuses_partially_bound_ownership():
    assert recorder_for_take(
        database=_DB(),
        session={"id": "take", "project_id": "project"},
    ) is None
