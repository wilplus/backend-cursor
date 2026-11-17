"""STORY    As a speaker retrying a saved message, I want exactly one worker
         to own its durable turn, so that an optimistic bubble cannot be
         overwritten or answered twice.
OUTCOME
  O1  An optimistic user/text row is claimed once only when its logical words
      match, while its existing metadata and visible whitespace are retained.
  O2  A different payload or an existing bot row is returned untouched; it
      cannot be converted into a pending user turn.
  O3  Only the pending claim that owns the user row can mark it terminal.
PROVES   O1 -> test_claim_adapter_stamps_only_the_matching_optimistic_user_row_once
         O2 -> test_claim_adapter_refuses_mismatched_or_bot_rows_without_writing
         O3 -> test_completion_adapter_compares_claim_and_pending_state
WHY      The database's unique client id and conditional update are the
         cross-worker arbitration point for a persisted chat retry.
"""
from __future__ import annotations

import copy

from services.db import DatabaseService


class _Result:
    def __init__(self, data):
        self.data = data


class _ClaimQuery:
    def __init__(self, records, calls):
        self.records = records
        self.calls = calls
        self.payload = None
        self.filters = []

    def update(self, payload):
        self.payload = copy.deepcopy(payload)
        self.calls.append(("update", self.payload))
        return self

    def eq(self, key, value):
        self.filters.append(("eq", key, value))
        self.calls.append(("eq", key, value))
        return self

    def is_(self, key, value):
        self.filters.append(("is", key, value))
        self.calls.append(("is", key, value))
        return self

    def execute(self):
        filter_map = {key: value for kind, key, value in self.filters
                      if kind == "eq"}
        client_id = filter_map.get("client_id")
        row = self.records.get(client_id)
        if not row:
            return _Result([])
        if "metadata->chat_turn->>claim_id" in filter_map:
            turn = (row.get("metadata") or {}).get("chat_turn") or {}
            matches = (
                turn.get("claim_id") == filter_map["metadata->chat_turn->>claim_id"]
                and turn.get("state") == filter_map["metadata->chat_turn->>state"]
            )
        else:
            matches = (
                row.get("role") == filter_map.get("role")
                and row.get("kind") == filter_map.get("kind")
                and row.get("body") == filter_map.get("body")
                and not (row.get("metadata") or {}).get("chat_turn")
            )
        if not matches:
            return _Result([])
        row["metadata"] = copy.deepcopy(self.payload["metadata"])
        return _Result([copy.deepcopy(row)])


class _ClaimClient:
    def __init__(self, records):
        self.records = records
        self.calls = []

    def table(self, name):
        assert name == "lounge_messages"
        return _ClaimQuery(self.records, self.calls)


def _adapter(records):
    adapter = DatabaseService.__new__(DatabaseService)
    adapter.client = _ClaimClient(records)
    adapter.insert_lounge_messages = lambda _user, messages: [
        copy.deepcopy(records.get(message["client_id"]))
        for message in messages if message["client_id"] in records
    ]
    adapter.get_lounge_message_by_client_id = lambda _user, client_id: copy.deepcopy(
        records.get(client_id)
    )
    return adapter


def _pending(client_id, claim_id, body="Question one"):
    return {
        "client_id": client_id, "role": "user", "kind": "text", "body": body,
        "metadata": {
            "place": "will",
            "chat_turn": {"version": 1, "state": "pending", "claim_id": claim_id},
        },
        "client_created_at": "2026-11-17T00:00:00+00:00",
    }


def test_claim_adapter_stamps_only_the_matching_optimistic_user_row_once():
    client_id = "turn-1"
    records = {
        client_id: {
            "client_id": client_id, "role": "user", "kind": "text",
            "body": "Question one", "metadata": {"optimistic_marker": "kept"},
        },
    }
    adapter = _adapter(records)

    first = adapter.claim_lounge_chat_turn("u", _pending(client_id, "claim-a"))
    second = adapter.claim_lounge_chat_turn("u", _pending(client_id, "claim-b"))

    assert first["metadata"]["chat_turn"]["claim_id"] == "claim-a"
    assert second["metadata"]["chat_turn"]["claim_id"] == "claim-a"
    assert records[client_id]["metadata"] == {
        "optimistic_marker": "kept", "place": "will",
        "chat_turn": {"version": 1, "state": "pending", "claim_id": "claim-a"},
    }
    assert ("eq", "body", "Question one") in adapter.client.calls
    assert ("is", "metadata->>chat_turn", "null") in adapter.client.calls


def test_claim_adapter_keeps_optimistic_whitespace_for_the_same_message():
    client_id = "turn-whitespace"
    records = {
        client_id: {
            "client_id": client_id, "role": "user", "kind": "text",
            "body": "  Question one  ",
            "metadata": {"optimistic_marker": "kept"},
        },
    }
    adapter = _adapter(records)

    claimed = adapter.claim_lounge_chat_turn(
        "u", _pending(client_id, "claim-a", body="Question one"),
    )

    assert claimed["metadata"]["chat_turn"]["claim_id"] == "claim-a"
    assert records[client_id]["body"] == "  Question one  "
    assert ("eq", "body", "  Question one  ") in adapter.client.calls


def test_claim_adapter_refuses_mismatched_or_bot_rows_without_writing():
    for client_id, row in {
        "wrong-words": {
            "client_id": "wrong-words", "role": "user", "kind": "text",
            "body": "Question one", "metadata": {"optimistic_marker": "kept"},
        },
        "bot-row": {
            "client_id": "bot-row", "role": "bot", "kind": "text",
            "body": "Question two", "metadata": {},
        },
    }.items():
        records = {client_id: copy.deepcopy(row)}
        adapter = _adapter(records)
        result = adapter.claim_lounge_chat_turn("u", _pending(
            client_id, "claim-a", body="Question two",
        ))

        assert result == row
        assert records[client_id] == row
        assert adapter.client.calls == []


def test_completion_adapter_compares_claim_and_pending_state():
    records = {
        "turn-1": {
            "client_id": "turn-1", "role": "user", "kind": "text",
            "body": "Question one", "metadata": {
                "optimistic_marker": "kept",
                "chat_turn": {"version": 1, "state": "pending", "claim_id": "claim-a"},
            },
        },
    }
    adapter = _adapter(records)
    completed = {
        "optimistic_marker": "kept",
        "chat_turn": {"version": 1, "state": "completed", "claim_id": "claim-a"},
    }

    won = adapter.complete_lounge_chat_turn("u", "turn-1", "claim-a", completed)
    lost = adapter.complete_lounge_chat_turn("u", "turn-1", "claim-b", completed)

    assert won["metadata"] == completed
    assert lost is None
    assert records["turn-1"]["metadata"] == completed
    assert ("eq", "metadata->chat_turn->>claim_id", "claim-a") in adapter.client.calls
    assert ("eq", "metadata->chat_turn->>state", "pending") in adapter.client.calls
