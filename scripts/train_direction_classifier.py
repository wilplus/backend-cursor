#!/usr/bin/env python3
"""Reproducible local train of the SHADOW direction classifier.

willab Phase 4 / Prompt 1, B2. Exports the labels⋈features corpus, fits the
logistic model, and prints eval metrics + warnings. The same core
(train_direction_classifier) is what POST /v2/admin/learning/train runs. This
script does NOT register/store — pass --register to do the full train_and_
register (export → fit → store artifact → model_versions row).

Usage:  python scripts/train_direction_classifier.py [--register]
"""
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def main() -> int:
    if "--register" in sys.argv[1:]:
        from services.learning_train import train_and_register
        print(json.dumps(train_and_register(), indent=2, default=str))
        return 0
    from services.learning_export import export_snippet_labels_dataset
    from services.learning_train import train_direction_classifier
    rows, summary = export_snippet_labels_dataset()
    _artifact, metrics, warnings = train_direction_classifier(rows)
    print(json.dumps({
        "export_summary": summary, "metrics": metrics, "warnings": warnings,
    }, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
