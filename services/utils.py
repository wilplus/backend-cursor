"""Shared utilities for the backend."""
from datetime import datetime, timezone


def utc_now_iso() -> str:
    """Return the current UTC time as a Z-suffixed ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
