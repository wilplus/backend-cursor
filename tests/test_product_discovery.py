"""Tests for the copy-independent product discovery contract."""
from __future__ import annotations

import unittest

from services.product_discovery import (
    build_open_product_action,
    parse_product_action,
    shape_product_discoveries,
)


class ProductActionTests(unittest.TestCase):
    def test_builds_versioned_no_context_action(self):
        action = build_open_product_action(
            "life_panel",
            intent="start_setup",
            source="voice_album_completion",
        )
        self.assertEqual(action, {
            "action": "open_product",
            "product": "life_panel",
            "intent": "start_setup",
            "source": "voice_album_completion",
            "context_transfer": "none",
            "schema_version": 1,
        })

    def test_parser_requires_structured_metadata(self):
        self.assertIsNone(parse_product_action({
            "body": "Open your Voice Album",
            "voice_album_ready": True,
        }))

    def test_parser_accepts_supported_action(self):
        action = build_open_product_action(
            "voice_album",
            intent="open_album",
            source="voice_album_introduction",
        )
        self.assertEqual(
            parse_product_action({"product_action": action}), action,
        )

    def test_parser_rejects_context_transfer_and_unknown_products(self):
        base = build_open_product_action(
            "life_panel", intent="start_setup", source="test",
        )
        self.assertIsNone(parse_product_action({
            "product_action": {**base, "context_transfer": "chat"},
        }))
        self.assertIsNone(parse_product_action({
            "product_action": {**base, "product": "principles"},
        }))


class ProductDiscoveryResponseTests(unittest.TestCase):
    def test_deduplicates_filters_and_sorts(self):
        self.assertEqual(shape_product_discoveries([
            {"product": "voice_album"},
            {"product": "life_panel"},
            {"product": "voice_album"},
            {"product": "unknown"},
        ]), {"products": ["life_panel", "voice_album"]})


if __name__ == "__main__":
    unittest.main()
