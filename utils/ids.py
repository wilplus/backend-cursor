"""One rule for ids in requests (audit D1, founder decision 2026-09-26).

Before this, the same UUID check lived in seven places with four behaviours:
some routes rejected an uppercase id, others accepted braces, a ``urn:uuid:``
prefix or 32 bare hex digits. The rule now: the standard 8-4-4-4-12 hex form,
in any letter case, handed back lowercase.
"""
from __future__ import annotations

import re
import uuid
from typing import Any

_UUID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def parse_uuid(value: Any, field: str) -> str:
    """``value`` as a lowercase UUID, or ``ValueError("<field> must be a
    UUID")``. A ``uuid.UUID`` instance is accepted as is."""
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str) and _UUID.match(value.strip()):
        return value.strip().lower()
    raise ValueError(f"{field} must be a UUID")


def is_uuid(value: Any) -> bool:
    """Whether ``parse_uuid`` would accept ``value``."""
    try:
        parse_uuid(value, "value")
    except ValueError:
        return False
    return True
