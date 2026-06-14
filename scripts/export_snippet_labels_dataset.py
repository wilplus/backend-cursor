#!/usr/bin/env python3
"""Export the snippet-labels dataset (training_labels ⋈ 11 features) to JSONL.

willab Phase 4 / Prompt 1, B1. Read-only. Prints a class-balance summary so
you can see corpus size + balance + how many labels were dropped for missing
features (the §7 integrity check) before training.

Usage:  python scripts/export_snippet_labels_dataset.py [out.jsonl]
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from services.learning_export import export_snippet_labels_dataset, write_jsonl


def main() -> int:
    out = sys.argv[1] if len(sys.argv) > 1 else "snippet_labels_dataset.jsonl"
    rows, summary = export_snippet_labels_dataset()
    n = write_jsonl(rows, out)
    print(f"wrote {n} rows → {out}")
    print(json.dumps(summary, indent=2))
    if summary["total"] == 0:
        print("WARNING: empty corpus (no labels with a complete feature vector).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
