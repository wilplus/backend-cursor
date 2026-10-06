"""F-1: the MLC-2 kill is the confidence writer state, and the docs say so.

docs/MLC2-FOUNDATION.md named ``MLC2_FOUNDATION_ENABLED=false`` as the
application kill switch. No code ever read it, and it left config.py with
the other dead settings (#495). The kill that exists is the code constant
``MLC2_CONFIDENCE_CUTOVER_MODE`` plus the one-way ring kill of the
``confidence_learning_writes`` row. These cases keep the documentation and
the code saying the same thing, and every foundation writer behind it.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def test_no_environment_kill_switch_is_promised():
    assert "MLC2_FOUNDATION_ENABLED" not in _read("config.py")
    assert not re.search(r"^MLC2_FOUNDATION_ENABLED=", _read(".env.example"), re.M)
    assert "is the application kill switch" not in _read("docs/MLC2-FOUNDATION.md")


def test_the_docs_name_the_kill_that_exists():
    doc = _read("docs/MLC2-FOUNDATION.md")
    for named in ("MLC2_CONFIDENCE_CUTOVER_MODE", "`killed`",
                  "confidence_learning_writes", "rings.confidence_writer_killed()"):
        assert named in doc, named


def test_the_writer_state_reads_the_ring_kill_and_cannot_be_opened_by_it():
    cutover = _read("services/mlc2_confidence_cutover.py")
    assert "rings.confidence_writer_killed()" in cutover
    assert "resolve_confidence_cutover(KILLED)" in cutover
    assert 'os.getenv("MLC2_CONFIDENCE_CUTOVER_MODE")' not in _read("config.py")


def test_every_foundation_writer_reads_the_writer_state():
    readers = {
        "services/take_lifecycle.py": "configured_confidence_cutover().canonical_writes_enabled",
        "services/confidence_chain_consumer.py": "configured_confidence_cutover().canonical_writes_enabled",
        "services/mlc2_confidence_frame_factory.py": "configured_confidence_cutover()",
        "services/object_verification.py": "confidence_canonical_writes_enabled()",
    }
    for path, call in readers.items():
        assert call in _read(path), path


def test_the_killed_state_closes_both_writer_boundaries():
    from services.mlc2_confidence_cutover import resolve_confidence_cutover
    killed = resolve_confidence_cutover("killed")
    assert (killed.canonical_writes_enabled, killed.prior_learning_writes_enabled) == (False, False)
    garbage = resolve_confidence_cutover("on")
    assert garbage.mode == "killed" and not garbage.valid_configuration
