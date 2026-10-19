"""
STORY    As a speaker, I want my Take to open as soon as it is ready, and any
         skipped step to be named, so that I am never stuck and problems are
         visible. (Record -> process -> Ideal Text.)
OUTCOME
  O1  The job flips the session to 'ready' before the job itself finishes.
  O2  A healthy job keeps its result shape (no 'degraded' key); a job whose
      run fell back carries the stage names, never messages.
  O3  The Ideal Text assembler saves the text even when a trailing stage
      fails, and names that stage; a healthy assembly names nothing.
  O4  When the whole assembly fails it returns False, saves nothing, and
      says so by name.
PROVES   O1 -> test_the_job_tells_the_speaker_ready_before_it_finishes
         O2 -> test_a_healthy_job_result_is_the_old_shape
               test_a_job_that_fell_back_names_the_stage
         O3 -> test_a_failed_trailing_stage_still_saves_the_ideal_text
         O4 -> test_the_whole_assembly_failing_is_false_and_named
WHY      Audit Q-C1: best-effort stages were swallowed into log lines. The
         analysis worker's own stages are pinned in tests/test_analysis_worker.py.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from services.degradation import DegradationLog

SID = "77777777-7777-4777-8777-777777777777"
REC = "88888888-8888-4888-8888-888888888888"
ARC = "arc-1"


# ── the assembler ─────────────────────────────────────────────────────────

class _AssemblerDb:
    def __init__(self, *, boom=()):
        self.boom = set(boom)
        self.persisted = None

    def _maybe(self, name):
        if name in self.boom:
            raise RuntimeError(f"{name} is down")

    def get_arc_sessions(self, arc_id):
        self._maybe("get_arc_sessions")
        return [{"id": SID, "take_index": 1, "recording_kind": "spoken"}]

    @property
    def takes(self):
        # audit Q-A2: production now calls db.takes.<method>();
        # this fake implements those methods directly on itself.
        return self

    def get_coach_arc_ideal_text(self, arc_id):
        return None

    @property
    def ideal_text(self):
        # audit Q-A2: production now calls database.ideal_text.<method>();
        # this fake implements those methods directly on itself.
        return self

    def persist_auto_ideal_text(self, arc_id, text, *, take_count=None,
                                document=None):
        self.persisted = text
        return True

    def get_moment_suggestions_by_arc(self, arc_id):
        self._maybe("get_moment_suggestions_by_arc")
        return {}

    def get_snippets_by_session(self, sid):
        return []

    def upsert_moment_suggestion(self, *a, **k):
        self._maybe("upsert_moment_suggestion")

    def upsert_ideal_text_version(self, *a, **k):
        self._maybe("upsert_ideal_text_version")


def _assemble(db, *, auto=None, degradation=None):
    import services.ideal_text_block as mod
    auto = auto or {"text": "assembled block", "key_moments": [],
                    "ready": True}
    with patch.object(mod, "assemble_transcript_document",
                      return_value=auto):
        return mod.maybe_assemble_ideal_text(
            ARC, database=db, require_target=False, degradation=degradation)


@pytest.mark.parametrize("boom, named", [
    ((), []),
    (("upsert_ideal_text_version",),
     [{"stage": "ideal_text.assembly.version_snapshot", "kind": "RuntimeError"}]),
])
def test_a_failed_trailing_stage_still_saves_the_ideal_text(boom, named):
    log = DegradationLog("ideal_text")
    db = _AssemblerDb(boom=boom)
    assert _assemble(db, degradation=log) is True
    assert db.persisted == "assembled block"
    assert [d.as_payload() for d in log.items] == named


def test_the_whole_assembly_failing_is_false_and_named():
    log = DegradationLog("ideal_text")
    db = _AssemblerDb(boom={"get_arc_sessions"})
    assert _assemble(db, degradation=log) is False
    assert db.persisted is None
    assert [d.as_payload() for d in log.items] == [
        {"stage": "ideal_text.assembly", "kind": "RuntimeError"}]


# ── the job runner ────────────────────────────────────────────────────────

class _JobDb:
    client = object()

    def __init__(self):
        self.updates = []
        self.states = []

    def update_processing_job(self, job_id, patch_):
        self.updates.append(patch_)
        return True

    def v2_get_session_by_id(self, sid):
        return {}

    @property
    def takes(self):
        return self

    def set_session_analysis_state(self, sid, state, error=None):
        self.states.append((sid, state))
        return True


class _Adapter:
    def __init__(self, *a, **k):
        pass

    def download_audio(self, **k):
        return b"audio"


class _Authorization:
    def __init__(self, *a, **k):
        pass

    def resolve_acquisition_principal(self, *a, **k):
        return "principal-1"


def _run_job(fake_run, job_db=None):
    import services.pipeline_jobs as pj
    job = {"id": "job-1", "attempts": 1, "kind": "session_recording",
           "session_id": SID,
           "payload": {"storage_provider": "r2", "storage_key": "k",
                       "bucket": "b", "session_id": SID,
                       "recording_id": REC, "user_id": "u1",
                       "recording_kind": "spoken", "take_index": 2}}
    with patch.object(pj, "db", job_db or _JobDb()), \
            patch.object(pj, "_storage_provider", lambda: "r2"), \
            patch.object(pj, "confidence_source_manifest",
                         lambda **k: None), \
            patch("services.authorized_provider.AuthorizedProviderAdapter",
                  _Adapter), \
            patch("services.processing_authorization."
                  "ProcessingAuthorizationService", _Authorization), \
            patch("services.analysis_worker.run_full_analysis", fake_run):
        return pj._run_session_recording(job)


def test_a_healthy_job_result_is_the_old_shape():
    seen = {}

    def fake_run(**kwargs):
        seen["degradation"] = kwargs.get("degradation")
        return {"snippets": [1, 2]}, True

    assert _run_job(fake_run) == {"snippet_count": 2, "sent_to_coach": True}
    assert isinstance(seen["degradation"], DegradationLog)


def test_a_job_that_fell_back_names_the_stage():
    def fake_run(**kwargs):
        kwargs["degradation"].record("cadence", ValueError("secret provider text"))
        return {"snippets": [1]}, True

    result = _run_job(fake_run)
    assert result["snippet_count"] == 1
    assert result["degraded"] == [{"stage": "take_analysis.cadence", "kind": "ValueError"}]
    assert "secret provider text" not in str(result)


def test_the_job_tells_the_speaker_ready_before_it_finishes():
    """Founder 2026-10-14: the pipeline's early flip writes the SESSION's
    `ready` while the job row is still processing — the readout serves on
    the session row, so the speaker is in before the trailing work runs."""
    job_db = _JobDb()

    def fake_run(**kwargs):
        kwargs["on_ready"]()
        return {"snippets": [1]}, True

    assert _run_job(fake_run, job_db)["snippet_count"] == 1
    assert job_db.states == [(SID, "ready")]
