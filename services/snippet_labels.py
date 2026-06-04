"""Snippet labels: admin-supplied structured {charisma, stress} tags for stress_snippets.

Decoupled from stress_snippets.coach_label so:
- One clip can hold both charisma and stress labels.
- Multiple labelers each get their own row (unique on snippet_id, labeler_admin_id).
- Re-labeling by the same admin is a cheap UPSERT.

This module is the writer for the labeling UI and the read source for a future
training-export script (see scripts/export_snippet_labels_dataset.py — not yet written).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import sentry_sdk

from config import Config
from services.db import db

logger = logging.getLogger(__name__)
config = Config()


def admin_id_for_email(email: str) -> Optional[str]:
    """Resolve an active admin's UUID from their email (matches routes/admin.is_admin pattern)."""
    if not email:
        return None
    res = (
        db.client.table("admin_users")
        .select("id")
        .eq("email", email)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    rows = res.data or []
    return rows[0]["id"] if rows else None


def list_unlabeled_for_admin(admin_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """Return up to `limit` stress_snippets that this admin has not yet labeled.

    Each row includes a fresh signed audio URL. Oldest snippets first so we work
    through the backlog deterministically.
    """
    if limit <= 0:
        return []
    # Pull a small superset of candidates, then anti-join in memory against this admin's labels.
    # PostgREST has no clean NOT EXISTS subquery; this is cheap at v0 scale.
    fetch = max(limit * 3, limit + 20)
    snippets_res = (
        db.client.table("stress_snippets")
        .select(
            "id, source_type, scenario, duration_ms, "
            "classifier_stress_probability, transcript_excerpt, storage_path, created_at, "
            "transcript, language, words"
        )
        .order("created_at", desc=False)
        .limit(fetch)
        .execute()
    )
    snippets = snippets_res.data or []
    if not snippets:
        return []

    ids = [s["id"] for s in snippets]
    labeled_res = (
        db.client.table("snippet_labels")
        .select("snippet_id")
        .eq("labeler_admin_id", admin_id)
        .in_("snippet_id", ids)
        .execute()
    )
    already = {row["snippet_id"] for row in (labeled_res.data or [])}

    out: list[dict[str, Any]] = []
    for s in snippets:
        if s["id"] in already:
            continue
        url: Optional[str] = None
        try:
            url = db.create_signed_url(
                config.AUDIO_BUCKET_NAME, s["storage_path"], expires_in=3600
            )
        except Exception as e:
            logger.warning(
                "snippet_labels: signed URL failed snippet_id=%s err=%s",
                s["id"], type(e).__name__,
            )
            sentry_sdk.capture_exception(e)
            continue
        out.append({
            "snippet_id": s["id"],
            "source_type": s.get("source_type"),
            "scenario": s.get("scenario"),
            "duration_ms": s.get("duration_ms"),
            "classifier_stress_probability": s.get("classifier_stress_probability"),
            "transcript_excerpt": s.get("transcript_excerpt"),
            "transcript": s.get("transcript"),
            "language": s.get("language"),
            "words": s.get("words"),
            "audio_url": url,
        })
        if len(out) >= limit:
            break
    return out


def upsert_label(
    *,
    snippet_id: str,
    admin_id: str,
    charisma: Optional[int],
    stress: Optional[int],
    notes: Optional[str],
    confidence: Optional[str] = "high",
) -> dict[str, Any]:
    """Insert or update this admin's label for a snippet.

    Raises ValueError on invalid input. UPSERT on (snippet_id, labeler_admin_id).
    `confidence` is 'low' | 'high' (default 'high'); used to filter training data later.
    """
    if not snippet_id:
        raise ValueError("snippet_id is required")
    if not admin_id:
        raise ValueError("admin_id is required")
    if charisma is None and stress is None:
        raise ValueError("at least one of charisma or stress must be provided")
    for name, val in (("charisma", charisma), ("stress", stress)):
        if val is not None and val not in (0, 1):
            raise ValueError(f"{name} must be 0, 1, or null")
    if confidence is None:
        confidence = "high"
    if confidence not in ("low", "high"):
        raise ValueError("confidence must be 'low' or 'high'")
    if notes is not None:
        notes = str(notes)
        if len(notes) > 2000:
            notes = notes[:2000]

    payload: dict[str, Any] = {
        "snippet_id": snippet_id,
        "labeler_admin_id": admin_id,
        "charisma": charisma,
        "stress": stress,
        "confidence": confidence,
        "notes": notes,
        # Explicit timestamp so UPSERTs refresh labeled_at on re-label.
        "labeled_at": datetime.now(timezone.utc).isoformat(),
    }
    res = (
        db.client.table("snippet_labels")
        .upsert(payload, on_conflict="snippet_id,labeler_admin_id")
        .execute()
    )
    rows = res.data or []
    return rows[0] if rows else {}


def label_stats(admin_id: str) -> dict[str, int]:
    """Throughput counters for the labeler UI."""
    by_me = (
        db.client.table("snippet_labels")
        .select("id", count="exact")
        .eq("labeler_admin_id", admin_id)
        .execute()
    )
    by_me_high = (
        db.client.table("snippet_labels")
        .select("id", count="exact")
        .eq("labeler_admin_id", admin_id)
        .eq("confidence", "high")
        .execute()
    )
    by_me_low = (
        db.client.table("snippet_labels")
        .select("id", count="exact")
        .eq("labeler_admin_id", admin_id)
        .eq("confidence", "low")
        .execute()
    )
    total = (
        db.client.table("snippet_labels")
        .select("id", count="exact")
        .execute()
    )
    snippets_total = (
        db.client.table("stress_snippets")
        .select("id", count="exact")
        .execute()
    )
    return {
        "labels_by_me": int(getattr(by_me, "count", 0) or 0),
        "labels_by_me_high": int(getattr(by_me_high, "count", 0) or 0),
        "labels_by_me_low": int(getattr(by_me_low, "count", 0) or 0),
        "labels_total": int(getattr(total, "count", 0) or 0),
        "snippets_total": int(getattr(snippets_total, "count", 0) or 0),
    }
