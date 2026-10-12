"""The pipeline and the assembler name their fallbacks (audit Q-C1, Phase 5).

Three writers used to swallow their best-effort stages into log lines:
the full-analysis worker, the eager assembler and the job runner that
serves the job row. Each now runs those stages through one
``DegradationLog``; a healthy run is byte-identical to before, and a run
that fell back says which stage did, by name and exception class only.
"""
from __future__ import annotations

from unittest.mock import patch

from services.degradation import DegradationLog

SID = "77777777-7777-4777-8777-777777777777"
REC = "88888888-8888-4888-8888-888888888888"
ARC = "arc-1"


# ── the worker ────────────────────────────────────────────────────────────


# ── the confirmation builder ──────────────────────────────────────────────


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

    def update_processing_job(self, job_id, patch_):
        self.updates.append(patch_)
        return True

    def v2_get_session_by_id(self, sid):
        return {}


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


def _run_job(fake_run):
    import services.pipeline_jobs as pj
    job = {"id": "job-1", "attempts": 1, "kind": "session_recording",
           "payload": {"storage_provider": "r2", "storage_key": "k",
                       "bucket": "b", "session_id": SID,
                       "recording_id": REC, "user_id": "u1",
                       "recording_kind": "spoken", "take_index": 2}}
    with patch.object(pj, "db", _JobDb()), \
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
    assert seen["degradation"].path == "take_analysis"
