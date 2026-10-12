"""The D20 snapshot gate and the row binding of the V3 orchestrator, pinned.

Each refusal is asserted by its exact reason, through
`prepare_first_client_feedback` itself, so these pins hold whatever shape the
function takes inside. A refused snapshot must also stop the Take BEFORE the
exposure bundle is built and recorded: that ordering is the D20 contract.
"""
from __future__ import annotations

from services import mlc3_first_client_feedback as module
from services.mlc3_first_client_feedback import (
    V3Unavailable,
    prepare_first_client_feedback,
)
from tests.test_mlc3_first_client_feedback import (
    USER,
    _Database,
    _source,
)


def _run(database):
    session, document, snippets = _source()
    return prepare_first_client_feedback(
        database=database, session=session, take_document=document,
        served_text=document["text"], snippets=snippets, suggestions={},
        feedback_candidates=[], owner_user_id=USER,
    )


def test_a_visible_row_outside_the_bundle_declines(monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "MLC3_SERVICE_ENABLED", True)
    monkeypatch.setattr(module, "_canonical_index", lambda bundle: {})

    result = _run(_Database())

    assert result == V3Unavailable("visible_row_candidate_not_in_bundle")


# ── THE BUNDLE COMES BACK WITH THE ROWS (founder 2026-09-29) ──────────────
#
# The V3 learning packets are frozen from the bundle V3 served from. It is
# handed back through the `learning` out-parameter on the success exit only,
# so a declined Take hands back nothing and no packet can describe a card
# that was not served.
