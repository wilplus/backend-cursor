"""Run the prompt golden evals — the behavioral half of the drift gate.

Usage:
    python tests/evals/run_prompt_evals.py --all
    python tests/evals/run_prompt_evals.py --surface say_it_stronger
    python tests/evals/run_prompt_evals.py --changed-against old-lock.json

``--changed-against`` is what CI uses: it diffs the current prompt
registry against the merge-base's prompts.lock.json and runs evals ONLY
for the surfaces whose prompts changed. A prompt id's surface is the
part before the first dot ("say_it_stronger.system" → say_it_stronger).

Special mappings:
  * will_voice.* changed → the voice rules ride ~13 system prompts, so
    every surface that HAS a golden dataset runs.
  * master_doc_rag* changed → covered by the always-on master-doc-probe
    CI job; noted, not re-run here.
  * a changed surface with no dataset/adapter yet → noted, skipped
    green. Coverage grows as the founder's golden datasets land.

Exit codes: 0 = pass / skipped-green, 1 = at least one case failed.
No API key → skip green (probe precedent: the gate arms itself when
the repo secret exists).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from tests.evals import harness  # noqa: E402
from tests.evals.surfaces import ADAPTERS  # noqa: E402

# Surfaces whose prompt drift is already gated by a dedicated CI job.
_COVERED_ELSEWHERE = ("master_doc_rag",)


def _surfaces_from_changed_ids(changed_ids: list[str]) -> list[str]:
    available = set(harness.available_surfaces())
    surfaces: set[str] = set()
    for pid in changed_ids:
        surface = pid.split(".", 1)[0]
        if surface == "will_voice":
            surfaces |= available
            continue
        if surface.startswith(_COVERED_ELSEWHERE):
            print(f"note: {pid} changed — gated by the master-doc-probe job.")
            continue
        surfaces.add(surface)
    return sorted(surfaces)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true",
                       help="run every surface with a golden dataset")
    group.add_argument("--surface", action="append",
                       help="run one surface (repeatable)")
    group.add_argument("--changed-against", metavar="OLD_LOCK",
                       help="run surfaces whose prompts changed vs an "
                            "older prompts.lock.json")
    args = parser.parse_args()

    if args.all:
        surfaces = harness.available_surfaces()
    elif args.surface:
        surfaces = args.surface
    else:
        from services.prompts import registry
        old_path = Path(args.changed_against)
        old = registry.read_lockfile(old_path) if old_path.exists() else {}
        delta = registry.diff_against(old)
        changed = delta["added"] + delta["changed"]
        if not changed:
            print("no prompt changes vs the base lockfile — nothing to eval.")
            return 0
        print(f"changed prompt ids vs base: {', '.join(changed)}")
        surfaces = _surfaces_from_changed_ids(changed)
        if not surfaces:
            print("no changed surface has a golden dataset yet — "
                  "skipping green.")
            return 0

    return harness.run(surfaces, ADAPTERS)


if __name__ == "__main__":
    sys.exit(main())
