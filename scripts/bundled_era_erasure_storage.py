#!/usr/bin/env python3
"""F4 step "objects": delete the stored files one bundled-era snapshot lists.

Founder, 2026-09-25. Preview is the default and changes nothing. With
--execute each file is deleted, verified gone and recorded against the
snapshot, which apply_bundled_era_erasure_v1 requires before it deletes a row.
The full procedure is docs/BUNDLED-ERA-ERASURE.md.

  python3 scripts/bundled_era_erasure_storage.py --snapshot-id <uuid>
  python3 scripts/bundled_era_erasure_storage.py --snapshot-id <uuid> --execute
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import Config
from services.bundled_era_storage import annotation_export_refs, run
from services.db import db


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args(argv)
    config = Config()
    exports = annotation_export_refs(
        bucket=config.ANNOTATION_EXPORT_BUCKET,
        prefix=config.ANNOTATION_EXPORT_PREFIX,
    )
    print(json.dumps(run(db, args.snapshot_id, execute=args.execute,
                         export_refs=exports), sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
