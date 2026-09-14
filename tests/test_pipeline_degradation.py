"""The pipeline and the assembler name their fallbacks (audit Q-C1, Phase 5).

Three writers used to swallow their best-effort stages into log lines:
the full-analysis worker, the eager assembler and the job runner that
serves the job row. Each now runs those stages through one
``DegradationLog``; a healthy run is byte-identical to before, and a run
that fell back says which stage did, by name and exception class only.
"""
from __future__ import annotations

import sys
import types
from unittest.mock import patch

import pytest

from services.degradation import DegradationLog

SID = "77777777-7777-4777-8777-777777777777"
REC = "88888888-8888-4888-8888-888888888888"
ARC = "arc-1"


def _module(name, **attrs):
    mod = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(mod, key, value)
    return mod


def _raise(exc):
    def _fn(*a, **k):
        raise exc
    return _fn


# ── the worker ────────────────────────────────────────────────────────────

class _WorkerDb:
    def get_user_profile(self, user_id):
        return {"goal": "clarity"}


def _run_worker(modules, *, degradation=None):
    import services.analysis_worker as aw
    lab = _module("services.lab_recording",
                  process_lab_recording=lambda **k: {"snippets": [1]})
    with patch.dict(sys.modules, {"services.lab_recording": lab, **modules}), \
            patch.object(aw, "db", _WorkerDb()):
        return aw.run_full_analysis(
            session_id=SID, user_id="u1", recording_id=REC,
            audio_bytes=b"x", filename="lab.webm", session_context=None,
            parent_audio_url="https://a", recording_kind="read",
            arc_id=ARC, take_index=1, degradation=degradation)


def _healthy_modules(calls):
    return {
        "services.session_metrics": _module(
            "services.session_metrics",
            compute_session_global_metrics=lambda sid: calls.append("globals")),
        "services.session_cadence": _module(
            "services.session_cadence",
            fire_arc_start=lambda *a, **k: calls.append("cadence")),
        "services.lab_send": _module(
            "services.lab_send",
            send_lab_recording_to_coach=lambda *a, **k: {"ok": True}),
        "services.arc_notifications": _module(
            "services.arc_notifications",
            fire_human_check_note=lambda *a, **k: calls.append("cards")),
    }


def test_a_healthy_authed_run_leaves_the_log_empty():
    calls: list[str] = []
    log = DegradationLog("take_analysis")
    readout, sent = _run_worker(_healthy_modules(calls), degradation=log)
    assert readout == {"snippets": [1]}
    assert sent is True
    assert calls == ["globals", "cadence", "cards"]
    assert log.payload() == {}


def test_every_best_effort_stage_names_itself_in_order():
    modules = {
        "services.session_metrics": _module(
            "services.session_metrics",
            compute_session_global_metrics=_raise(RuntimeError("agg"))),
        "services.session_cadence": _module(
            "services.session_cadence",
            fire_arc_start=_raise(KeyError("goal"))),
        "services.lab_send": _module(
            "services.lab_send",
            send_lab_recording_to_coach=_raise(TimeoutError("queue"))),
        "services.arc_notifications": _module(
            "services.arc_notifications",
            fire_human_check_note=_raise(ValueError("card"))),
    }
    log = DegradationLog("take_analysis")
    readout, sent = _run_worker(modules, degradation=log)
    # The same fallbacks as before: the take is served, the coach send is
    # reported false, nothing raised (LIVE LOOP).
    assert readout == {"snippets": [1]}
    assert sent is False
    assert [d.as_payload() for d in log.items] == [
        {"stage": "take_analysis.session_globals", "kind": "RuntimeError"},
        {"stage": "take_analysis.cadence", "kind": "KeyError"},
        {"stage": "take_analysis.auto_send", "kind": "TimeoutError"},
        {"stage": "take_analysis.arc_cards", "kind": "ValueError"},
    ]
    assert "goal" not in str(log.payload())


def test_a_worker_without_a_shared_log_still_serves():
    modules = _healthy_modules([])
    modules["services.session_cadence"] = _module(
        "services.session_cadence", fire_arc_start=_raise(RuntimeError("x")))
    readout, sent = _run_worker(modules)
    assert readout == {"snippets": [1]}
    assert sent is True


def test_the_take_one_builder_receives_the_runs_log():
    import services.analysis_worker as aw
    log = DegradationLog("take_analysis")
    lab = _module("services.lab_recording",
                  process_lab_recording=lambda **k: {"snippets": [1]})
    with patch.dict(sys.modules, {"services.lab_recording": lab}), \
            patch("services.ideal_text_confirmation."
                  "build_initial_ideal_text_from_stored_artifacts",
                  return_value={"text": "doc", "version": 1}) as build, \
            patch("services.moment_suggestions.generate_for_session",
                  create=True):
        aw.run_full_analysis(
            session_id=SID, user_id=None, recording_id=REC,
            audio_bytes=b"x", filename="lab.webm", session_context=None,
            parent_audio_url="https://a", recording_kind="spoken",
            arc_id=ARC, take_index=1, degradation=log)
    assert build.call_args.kwargs["degradation"] is log


# ── the confirmation builder ──────────────────────────────────────────────

def test_the_builder_forwards_a_log_only_when_it_has_one():
    from unittest.mock import Mock
    from services import ideal_text_confirmation as confirmation
    database = Mock()
    database.get_coach_arc_ideal_text.return_value = {"auto_text": "doc"}
    log = DegradationLog("take_analysis")
    with patch("services.ideal_text_block.maybe_assemble_ideal_text",
               return_value=True) as assemble:
        confirmation.build_initial_ideal_text_from_stored_artifacts(
            database, ARC, timeout_seconds=1, degradation=log)
    assert assemble.call_args.kwargs["degradation"] is log


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

    def get_coach_arc_ideal_text(self, arc_id):
        return None

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


def _assemble(db, *, auto=None, degradation=None, polish=False):
    import services.ideal_text_block as mod
    auto = auto or {"text": "assembled block", "key_moments": [],
                    "ready": True}
    with patch.object(mod, "assemble_ideal_text_block", return_value=auto), \
            patch.object(mod, "_polish_as_suggestions_enabled",
                         lambda: polish):
        return mod.maybe_assemble_ideal_text(
            ARC, database=db, require_target=False,
            include_suggestion_anchors=True, degradation=degradation)


def test_a_healthy_assembly_records_nothing():
    log = DegradationLog("ideal_text")
    db = _AssemblerDb()
    with patch("services.ideal_text_core_snapshot.publish_for_arc"):
        assert _assemble(db, degradation=log) is True
    assert db.persisted == "assembled block"
    assert log.payload() == {}


def test_each_post_persist_stage_names_itself_and_the_assembly_still_succeeds():
    log = DegradationLog("ideal_text")
    db = _AssemblerDb(boom={"upsert_ideal_text_version",
                            "upsert_moment_suggestion"})
    auto = {"text": "assembled block", "key_moments": [], "ready": True,
            "polish": [{"snippet_id": "s1", "verbatim": "we did it",
                        "edited": "we did it well"}]}
    with patch("services.ideal_text_core_snapshot.publish_for_arc",
               _raise(KeyError("core"))):
        assert _assemble(db, auto=auto, degradation=log, polish=True) is True
    assert db.persisted == "assembled block"
    assert [d.as_payload() for d in log.items] == [
        {"stage": "ideal_text.assembly.polish_persist",
         "kind": "RuntimeError"},
        {"stage": "ideal_text.assembly.version_snapshot",
         "kind": "RuntimeError"},
        {"stage": "ideal_text.assembly.core_snapshot_publish",
         "kind": "KeyError"},
    ]


def test_the_anchor_read_failing_is_named_and_the_text_still_persists():
    log = DegradationLog("ideal_text")
    db = _AssemblerDb(boom={"get_moment_suggestions_by_arc"})
    with patch("services.ideal_text_core_snapshot.publish_for_arc"):
        assert _assemble(db, degradation=log) is True
    stages = [d.stage for d in log.items]
    assert stages[0] == "ideal_text.assembly.suggestion_anchor_ids"
    # The version snapshot reads the same table and falls back too.
    assert "ideal_text.assembly.version_snapshot" in stages


def test_the_whole_assembly_failing_is_false_and_named():
    log = DegradationLog("ideal_text")
    db = _AssemblerDb(boom={"get_arc_sessions"})
    assert _assemble(db, degradation=log) is False
    assert db.persisted is None
    assert [d.as_payload() for d in log.items] == [
        {"stage": "ideal_text.assembly", "kind": "RuntimeError"}]


def test_the_assembler_makes_its_own_log_when_given_none():
    db = _AssemblerDb(boom={"upsert_ideal_text_version"})
    with patch("services.ideal_text_core_snapshot.publish_for_arc"):
        assert _assemble(db) is True


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


def test_a_degraded_run_reaches_the_job_row_by_stage_name():
    def fake_run(**kwargs):
        log = kwargs["degradation"]
        log.run("cadence", _raise(RuntimeError("lounge down")))
        log.note("review_version_card", "card_not_persisted")
        return {"snippets": [1]}, False

    result = _run_job(fake_run)
    assert result == {
        "snippet_count": 1, "sent_to_coach": False,
        "degraded": [
            {"stage": "take_analysis.cadence", "kind": "RuntimeError"},
            {"stage": "take_analysis.review_version_card",
             "kind": "card_not_persisted"},
        ],
    }
    # Names only: no message, nothing numeric (AC-9 holds on the job row).
    assert "lounge down" not in str(result)


@pytest.mark.parametrize("stage", [
    "session_globals", "cadence", "auto_send", "arc_cards",
    "moment_suggestions", "spoken_take_count", "user_edit_signal",
    "part_acoustics", "swap_offer", "review_version_card",
])
def test_every_former_swallow_all_in_the_worker_runs_through_the_log(stage):
    import inspect
    import services.analysis_worker as aw
    src = inspect.getsource(aw._run_full_analysis_impl)
    assert f'_deg.run("{stage}"' in src, stage
