from __future__ import annotations

import mimetypes
from pathlib import Path
from typing import Any

from services.db import DatabaseService
from services.first_client_repository import FirstClientRepository
from services.practice_attempt_orchestrator import PracticeAttemptOrchestrator


ROOT = Path(__file__).resolve().parents[1]
ROUTE = (ROOT / "routes/v2/mlc3_first_client_service.py").read_text()


def _service_with_client(client: Any) -> DatabaseService:
    service = DatabaseService.__new__(DatabaseService)
    service.client = client
    return service


def test_repository_follows_explicit_database_client_reset(monkeypatch):
    original = object()
    replacement = object()
    service = _service_with_client(original)
    repository = FirstClientRepository(lambda: service.client)
    monkeypatch.setattr(service, "_build_supabase_client", lambda: replacement)

    service.reset_connections()

    assert repository.client is replacement


def test_repository_follows_transient_reconnect(monkeypatch):
    original = object()
    replacement = object()
    service = _service_with_client(original)
    repository = FirstClientRepository(lambda: service.client)
    monkeypatch.setattr(service, "_build_supabase_client", lambda: replacement)
    monkeypatch.setattr("services.db.time.sleep", lambda _seconds: None)
    calls = 0

    class Query:
        def execute(self):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("server disconnected")
            return "ok"

    result = service._execute_with_retry(
        lambda: Query(), label="first-client-refactor"
    )

    assert result == "ok"
    assert repository.client is replacement


def test_unnamed_upload_preserves_mime_derived_object_extension():
    expected = mimetypes.guess_extension("audio/webm") or ".audio"

    assert PracticeAttemptOrchestrator._extension("", "audio/webm") == expected
    assert 'filename=upload.filename or "",' in ROUTE
    assert 'command.filename or "practice.audio"' in (
        ROOT / "services/practice_attempt_orchestrator.py"
    ).read_text()
