"""Canonical cross-product discovery contract.

A product becomes discoverable only through a persisted bot bubble carrying a
versioned ``metadata.product_action`` object.  Copy, bubble kind, and legacy
flags are deliberately irrelevant.  The database records that introduction
durably; this module owns the application-side shape used by producers and
the authenticated read endpoint.
"""
from __future__ import annotations

from typing import Any, Optional


PRODUCT_ACTION_METADATA_KEY = "product_action"
PRODUCT_ACTION_SCHEMA_VERSION = 1
SUPPORTED_PRODUCT_IDS = frozenset(("voice_album", "life_panel"))


def build_open_product_action(
    product: str,
    *,
    intent: str,
    source: str,
) -> dict[str, Any]:
    """Build the only product-introduction action accepted by Willab."""
    if product not in SUPPORTED_PRODUCT_IDS:
        raise ValueError(f"Unsupported product: {product}")
    if not intent or not source:
        raise ValueError("intent and source are required")
    return {
        "action": "open_product",
        "product": product,
        "intent": intent,
        "source": source,
        "context_transfer": "none",
        "schema_version": PRODUCT_ACTION_SCHEMA_VERSION,
    }


def parse_product_action(metadata: Any) -> Optional[dict[str, Any]]:
    """Return a validated action or ``None``; never infer one from copy."""
    if not isinstance(metadata, dict):
        return None
    action = metadata.get(PRODUCT_ACTION_METADATA_KEY)
    if not isinstance(action, dict):
        return None
    if action.get("action") != "open_product":
        return None
    if action.get("product") not in SUPPORTED_PRODUCT_IDS:
        return None
    if action.get("context_transfer") != "none":
        return None
    if action.get("schema_version") != PRODUCT_ACTION_SCHEMA_VERSION:
        return None
    if not isinstance(action.get("intent"), str) or not action["intent"]:
        return None
    if not isinstance(action.get("source"), str) or not action["source"]:
        return None
    return dict(action)


def shape_product_discoveries(rows: Any) -> dict[str, list[str]]:
    """Shape owner-scoped database rows into the stable API response."""
    products = {
        row.get("product")
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, dict) and row.get("product") in SUPPORTED_PRODUCT_IDS
    }
    return {"products": sorted(products)}
