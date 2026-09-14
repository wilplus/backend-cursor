"""Audit Q-T4 (Phase 6, commit 1): the per-slide selection engine lives under
its own name. L1 retired the Best Presentation ARTIFACT, not the mechanism —
selecting the best take of each slide is F1 piece (b) — so the module is
``services/slide_selection.py`` and nothing imports the retired name."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RETIRED = re.compile(r"services[./]best_presentation\b")


def _production_sources():
    for folder in ("routes", "services", "utils"):
        yield from (ROOT / folder).rglob("*.py")
    for name in ("app.py", "worker.py", "config.py"):
        yield ROOT / name


def test_the_retired_module_is_gone():
    assert not (ROOT / "services" / "best_presentation.py").exists()
    assert (ROOT / "services" / "slide_selection.py").exists()


def test_nothing_imports_the_retired_name():
    offenders = [
        str(p.relative_to(ROOT))
        for p in _production_sources()
        # The module's own header records what it was renamed from.
        if p.name != "slide_selection.py"
        and RETIRED.search(p.read_text(encoding="utf-8"))
    ]
    assert offenders == [], offenders


def test_the_live_readers_are_where_the_pipeline_looks():
    from services import slide_selection

    for name in ("spoken_arc_sessions", "select_best_per_slide", "TAKES_TARGET"):
        assert hasattr(slide_selection, name), name
