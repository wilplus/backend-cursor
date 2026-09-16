"""Shared base for the services/db.py table repositories (audit C.1 dedup).

Every ``*_repository.py`` carved out of ``DatabaseService`` (audit Q-A1
step 2 / Q-A2, Phase 4, 2026-09-14) takes the injected database service
(the feedback_repository idiom) and reads the Supabase client THROUGH it
on every call (``self.client`` is a property), so
``DatabaseService.reset_connections()`` — the post-fork rebuild — is seen
here too. Nothing in this module constructs a client; only services/db.py
does.
"""
from __future__ import annotations

from typing import Any


class TableRepository:
    def __init__(self, database: Any) -> None:
        self.database = database

    @property
    def client(self) -> Any:
        return self.database.client
