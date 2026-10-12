"""Best Presentation composes nothing and sends nothing (founder 2026-10-05,
N48.3 Q13 A; N48.1 step 6).

Its builder sent every pick's verbatim transcript to the model with no
permit, from the student GET, the coach GET and the training import's
legacy assembly. L1 had already retired the artifact. Both GETs were 410
tombstones, deleted 2026-10-11; the training import pins its own recording (the
deterministic transcript document), and the builder itself is removed
(N48.3 Q13 A).
"""
from __future__ import annotations

import pathlib
from unittest import mock



ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_the_training_import_pins_its_own_recording():
    """Pinned → maybe_assemble_ideal_text takes the deterministic transcript
    document (the legacy best-of compose is removed, N48.3 Q13 A)."""
    source = (ROOT / "services/training_import.py").read_text()
    stage = source[source.index("if STAGE_IDEAL_TEXT in picked_stages:"):]
    stage = stage[:stage.index("except Exception")]
    assert "source_session_id=session_id" in stage


def test_a_pinned_assembly_takes_the_transcript_document(monkeypatch):
    from services import ideal_text_block as itb

    class _Takes:
        @staticmethod
        def get_arc_sessions(arc_id):
            return [{"id": "s1", "take_index": 1, "arc_id": "arc-1"}]

    class _DB:
        takes = _Takes()
        ideal_text = None

        @staticmethod
        def v2_get_session_by_id(sid):
            return {"id": sid, "take_index": 1, "arc_id": "arc-1"}

        @staticmethod
        def persist_auto_ideal_text(*_a, **_k):
            return False

    seen: list = []
    monkeypatch.setattr(itb, "_living_transcript_enabled", lambda: False)
    monkeypatch.setattr(itb, "assemble_transcript_document",
                        lambda arc_id, **k: seen.append(k) or {"text": "words"})
    itb.maybe_assemble_ideal_text("arc-1", database=_DB(), require_target=False,
                                  source_session_id="s1")
    assert seen == [{"database": mock.ANY, "session_id": "s1"}]

