"""Ideal Text repository — the F1 ideal-text and evidence-span table access carved out of services/db.py
(audit Q-A1 step 2 / Q-A2, Phase 4, 2026-09-14).

Every method here is the verbatim body it had on DatabaseService; db.py keeps
a one-line delegate under the same name, so the ~360 test sites that patch
``db.<method>`` and every caller keep working unchanged. The repository takes
the injected database service (the feedback_repository idiom) and reads the
Supabase client THROUGH it on every call (``self.client`` is a property), so
``DatabaseService.reset_connections()`` — the post-fork rebuild — is seen here
too. Nothing in this module constructs a client; only services/db.py does.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone  # noqa: F401 — used by the moved bodies
from typing import Any, Dict, List, Optional  # noqa: F401

import sentry_sdk  # noqa: F401

logger = logging.getLogger(__name__)


class IdealTextRepository:
    def __init__(self, database: Any) -> None:
        self.database = database

    @property
    def client(self) -> Any:
        return self.database.client

    def get_coach_arc_ideal_text(self, arc_id: Optional[str]) -> Optional[dict]:
        """The coach's one-block ideal text row for an arc, or None (no row /
        missing table / error → the caller falls back to the auto draft)."""
        if not arc_id:
            return None
        try:
            res = (
                self.client.table("coach_arc_ideal_text")
                .select("*")
                .eq("arc_id", str(arc_id))
                .limit(1)
                .execute()
            )
            rows = res.data or []
            return rows[0] if rows else None
        except Exception as e:
            _e = str(e).lower()
            if "coach_arc_ideal_text" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                return None
            logger.warning("get_coach_arc_ideal_text failed arc=%s: %s",
                           arc_id, e)
            return None

    def upsert_coach_arc_ideal_text(
        self, arc_id: str, text: str, updated_by: Optional[str],
        *, approve: bool = False,
    ) -> bool:
        """Save (and optionally approve) the coach's one-block ideal text.
        approve=True stamps approved_at — the gate the student GET requires.
        Re-saving after approval keeps approved_at (edits post-approval stay
        approved; the coach explicitly owns the content either way)."""
        if not arc_id or not isinstance(text, str) or not text.strip():
            return False
        payload: dict = {
            "arc_id": str(arc_id),
            "text": text,
            "updated_by": str(updated_by) if updated_by else None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if approve:
            payload["approved_at"] = datetime.now(timezone.utc).isoformat()
        try:
            self.client.table("coach_arc_ideal_text").upsert(
                payload, on_conflict="arc_id").execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "coach_arc_ideal_text" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "upsert_coach_arc_ideal_text: table missing (run "
                    "migrations/add_coach_arc_ideal_text.sql) arc=%s", arc_id,
                )
                return False
            logger.warning("upsert_coach_arc_ideal_text failed arc=%s: %s",
                           arc_id, e)
            return False

    def get_canonical_confidence_evidence(
        self, *, take_id: str, snippet_id: str,
    ) -> Optional[dict]:
        """Resolve the exact canonical clip without reading any judgment."""
        if not take_id or not snippet_id:
            return None
        try:
            rows = (self.client.table("evidence_spans")
                    .select("id,audio_ref,start_ms,end_ms,technical_metadata")
                    .eq("take_id", str(take_id))
                    .eq("legacy_piece_id", str(snippet_id))
                    .eq("task_type", "confidence_classification")
                    .order("created_at", desc=True)
                    .limit(1).execute().data) or []
            if not rows:
                return None
            row = rows[0]
            return {
                "evidence_span_id": row.get("id"),
                "audio_ref": row.get("audio_ref"),
                "start_ms": row.get("start_ms"),
                "end_ms": row.get("end_ms"),
                "technical_metadata": row.get("technical_metadata") or {},
            }
        except Exception as error:
            logger.warning(
                "canonical confidence evidence read failed take=%s "
                "snippet=%s: %s", take_id, snippet_id, error,
            )
            return None

    def list_ideal_text_blocks(self,
                               arc_id: Optional[str]) -> Optional[list]:
        if not arc_id:
            return None
        try:
            res = (
                self.client.table("ideal_text_blocks")
                .select("*")
                .eq("arc_id", str(arc_id))
                .order("block_key", desc=False)
                .execute()
            )
            return res.data or []
        except Exception as e:
            _e = str(e).lower()
            if not ("ideal_text_blocks" in _e and (
                    "does not exist" in _e or "pgrst" in _e)):
                logger.warning("list_ideal_text_blocks failed arc=%s: %s",
                               arc_id, e)
            return None

    def get_ideal_text_block(self, arc_id: Optional[str],
                             block_key: Any) -> Optional[dict]:
        if not arc_id or not isinstance(block_key, int):
            return None
        try:
            res = (
                self.client.table("ideal_text_blocks")
                .select("*")
                .eq("arc_id", str(arc_id))
                .eq("block_key", block_key)
                .limit(1)
                .execute()
            )
            return (res.data or [None])[0]
        except Exception as e:
            logger.warning("get_ideal_text_block failed arc=%s: %s",
                           arc_id, e)
            return None

    def upsert_ideal_text_block(self, arc_id: str, block_key: int,
                                fields: dict) -> bool:
        """Partial upsert of one block row. Every column in the table has
        a default or is nullable except the key pair (enforced here), so
        partial writes are INSERT-safe — no #221-class NOT NULL trap."""
        if not arc_id or not isinstance(block_key, int) \
                or not isinstance(fields, dict):
            return False
        try:
            payload = dict(fields)
            payload["arc_id"] = str(arc_id)
            payload["block_key"] = block_key
            payload["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.client.table("ideal_text_blocks").upsert(
                payload, on_conflict="arc_id,block_key").execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "ideal_text_blocks" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "upsert_ideal_text_block: table missing (run "
                    "migrations/add_ideal_text_blocks.sql)")
                return False
            logger.warning("upsert_ideal_text_block failed arc=%s: %s",
                           arc_id, e)
            return False

    def delete_ideal_text_block(self, arc_id: str,
                                block_key: int) -> bool:
        """Remove one block row — a kept candidate is deleted outright
        (a parked settled-inactive row became an invisible ghost that
        swallowed later takes' material; review 2026-07-22)."""
        if not arc_id or not isinstance(block_key, int):
            return False
        try:
            (self.client.table("ideal_text_blocks")
             .delete()
             .eq("arc_id", str(arc_id))
             .eq("block_key", block_key)
             .execute())
            return True
        except Exception as e:
            logger.warning("delete_ideal_text_block failed arc=%s: %s",
                           arc_id, e)
            return False

    def insert_ideal_text_save(self, arc_id: str, version: int) -> bool:
        """One save row per (arc, version) — idempotent (a double-tap on
        Save re-stamps the same version harmlessly)."""
        if not arc_id or not isinstance(version, int) or version < 1:
            return False
        try:
            self.client.table("ideal_text_saves").upsert({
                "arc_id": str(arc_id),
                "version": version,
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="arc_id,version").execute()
            return True
        except Exception as e:
            _e = str(e).lower()
            if "ideal_text_saves" in _e and (
                "does not exist" in _e or "pgrst" in _e
            ):
                logger.warning(
                    "insert_ideal_text_save: table missing (run "
                    "migrations/add_ideal_text_blocks.sql)")
                return False
            logger.warning("insert_ideal_text_save failed arc=%s: %s",
                           arc_id, e)
            return False

    def get_latest_ideal_text_save(self,
                                   arc_id: Optional[str]) -> Optional[dict]:
        if not arc_id:
            return None
        try:
            res = (
                self.client.table("ideal_text_saves")
                .select("*")
                .eq("arc_id", str(arc_id))
                .order("version", desc=True)
                .limit(1)
                .execute()
            )
            return (res.data or [None])[0]
        except Exception:
            return None
