"""BE-4 (founder 2026-07-27, backlog story #11): the life-panel strategy
downloads as a real PDF or .docx, and a missing renderer degrades to markdown
rather than 500ing the download button.

Run: python3 -m unittest test_strategy_export
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from services.strategy_export import (DOCX, MD, PDF, export, horizon_label,
                                      sections, to_markdown)

HORIZONS = ("daily", "weekly", "five_year")
LATEST = {
    "daily": {"body": "Ship one thing.\n\nThen stop.", "version": 3},
    "weekly": {"body": "  Review the takes.  ", "version": 1},
    "five_year": {"body": "   ", "version": 1},          # empty → skipped
}


class SectionsTests(unittest.TestCase):
    def test_horizon_label_is_human(self):
        self.assertEqual(horizon_label("five_year"), "Five year")
        self.assertEqual(horizon_label(None), "")

    def test_sections_follow_horizon_order_and_skip_empties(self):
        self.assertEqual([h for h, _ in sections(LATEST, HORIZONS)],
                         ["Daily", "Weekly"])

    def test_sections_are_stripped_but_never_reworded(self):
        body = dict(sections(LATEST, HORIZONS))["Weekly"]
        self.assertEqual(body, "Review the takes.")

    def test_sections_safe_on_empty_input(self):
        self.assertEqual(sections({}, HORIZONS), [])
        self.assertEqual(sections(None, None), [])

    def test_markdown_has_a_heading_per_horizon(self):
        md = to_markdown(sections(LATEST, HORIZONS))
        self.assertIn("# Daily", md)
        self.assertIn("# Weekly", md)
        self.assertNotIn("Five year", md)


class ExportTests(unittest.TestCase):
    def test_markdown_export(self):
        payload, mime, name = export(LATEST, HORIZONS, "md")
        self.assertEqual((mime, name), (MD[0], "strategy.md"))
        self.assertIn("Ship one thing.", payload.decode("utf-8"))

    def test_pdf_export_is_a_real_pdf(self):
        payload, mime, name = export(LATEST, HORIZONS, "pdf")
        self.assertEqual((mime, name), (PDF[0], "strategy.pdf"))
        self.assertTrue(payload.startswith(b"%PDF"))

    def test_docx_export_is_a_real_docx(self):
        payload, mime, name = export(LATEST, HORIZONS, "docx")
        self.assertEqual((mime, name), (DOCX[0], "strategy.docx"))
        self.assertTrue(payload.startswith(b"PK"))       # a zip container

    def test_pdf_degrades_to_markdown_when_reportlab_is_missing(self):
        with patch("services.strategy_export._render_pdf",
                   side_effect=ImportError("no reportlab")):
            payload, mime, name = export(LATEST, HORIZONS, "pdf")
        self.assertEqual((mime, name), (MD[0], "strategy.md"))
        self.assertIn("Ship one thing.", payload.decode("utf-8"))

    def test_docx_degrades_to_markdown_when_python_docx_is_missing(self):
        with patch("services.strategy_export._render_docx",
                   side_effect=ImportError("no docx")):
            payload, mime, name = export(LATEST, HORIZONS, "docx")
        self.assertEqual((mime, name), (MD[0], "strategy.md"))

    def test_a_renderer_blowing_up_never_raises(self):
        with patch("services.strategy_export._render_pdf",
                   side_effect=RuntimeError("boom")):
            payload, mime, _ = export(LATEST, HORIZONS, "pdf")
        self.assertEqual(mime, MD[0])

    def test_unknown_format_and_empty_strategy_land_on_markdown(self):
        self.assertEqual(export(LATEST, HORIZONS, "xls")[1], MD[0])
        self.assertEqual(export({}, HORIZONS, "pdf"), (b"", MD[0],
                                                       "strategy.md"))


if __name__ == "__main__":
    unittest.main()
