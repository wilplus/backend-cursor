"""The D20 snapshot gate and the row binding of the V3 orchestrator, pinned.

Each refusal is asserted by its exact reason, through
`prepare_first_client_feedback` itself, so these pins hold whatever shape the
function takes inside. A refused snapshot must also stop the Take BEFORE the
exposure bundle is built and recorded: that ordering is the D20 contract.
"""
from __future__ import annotations

import logging

import pytest

from services import mlc3_first_client_feedback as module
from services.mlc3_first_client_feedback import (
    V3Unavailable,
    prepare_first_client_feedback,
)
from tests.test_mlc3_first_client_feedback import (
    MEMBERSHIP,
    TAKE,
    USER,
    _Database,
    _source,
)


class _SnapshotDatabase(_Database):
    """The shared fake, with the snapshot RPC's answer bent by `bend`."""

    def __init__(self, bend):
        super().__init__()
        self._bend = bend

    def execute(self):
        data = self._bend(dict(self._rpc_data))

        class Result:
            pass

        result = Result()
        result.data = data  # type: ignore[attr-defined]
        return result


def _run(database):
    session, document, snippets = _source()
    return prepare_first_client_feedback(
        database=database, session=session, take_document=document,
        served_text=document["text"], snippets=snippets, suggestions={},
        feedback_candidates=[], owner_user_id=USER,
    )


def _set(key, value):
    def bend(data):
        data[key] = value
        return data
    return bend


def _extra_key(data):
    data["extra"] = 1
    return data


_BENDS = [
    (lambda data: None, "source_snapshot_shape_unexpected"),
    (_extra_key, "source_snapshot_shape_unexpected"),
    (_set("document_snapshot_id", "not-a-uuid"),
     "source_snapshot_id_not_a_uuid"),
    (_set("document_snapshot_id", None), "source_snapshot_id_not_a_uuid"),
    # A UUID that parses but is not written canonically.
    (lambda data: _set("document_snapshot_id",
                       "{" + data["document_snapshot_id"] + "}")(data),
     "source_snapshot_does_not_match_served_text"),
    (_set("snapshot_contract_version", "feedback-v3-source-snapshot-v0"),
     "source_snapshot_does_not_match_served_text"),
    (_set("source_generation", True),
     "source_snapshot_does_not_match_served_text"),
    (_set("source_generation", 0),
     "source_snapshot_does_not_match_served_text"),
    (_set("source_generation", "1"),
     "source_snapshot_does_not_match_served_text"),
    (lambda data: _set("surface", data["surface"] + " ")(data),
     "source_snapshot_does_not_match_served_text"),
    (_set("surface_sha256", "0" * 64),
     "source_snapshot_does_not_match_served_text"),
]


@pytest.mark.parametrize("bend,reason", _BENDS)
def test_a_refused_snapshot_declines_before_the_bundle_exists(
    monkeypatch, bend, reason,
):
    from config import Config

    monkeypatch.setattr(Config, "MLC3_SERVICE_ENABLED", True)
    database = _SnapshotDatabase(bend)

    result = _run(database)

    assert result == V3Unavailable(reason)
    assert database.bundle is None
    assert database.membership_payload is None


def test_the_unbent_snapshot_serves(monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "MLC3_SERVICE_ENABLED", True)

    rows = _run(_SnapshotDatabase(lambda data: data))

    assert isinstance(rows, list) and len(rows) == 1


def test_a_visible_row_outside_the_bundle_declines(monkeypatch):
    from config import Config

    monkeypatch.setattr(Config, "MLC3_SERVICE_ENABLED", True)
    monkeypatch.setattr(module, "_canonical_index", lambda bundle: {})

    result = _run(_Database())

    assert result == V3Unavailable("visible_row_candidate_not_in_bundle")


def test_a_served_take_logs_its_families_and_lineage(monkeypatch, caplog):
    from config import Config

    monkeypatch.setattr(Config, "MLC3_SERVICE_ENABLED", True)
    caplog.set_level(logging.INFO, logger=module.logger.name)

    rows = _run(_Database())

    assert isinstance(rows, list)
    assert rows[0]["feedback_membership_id"] == MEMBERSHIP
    served = [record.getMessage() for record in caplog.records
              if "v3 served" in record.getMessage()]
    assert served == [
        "first_client: v3 served items=1 families=confident_voice:1 "
        f"lineage=yes take={TAKE}"
    ]
