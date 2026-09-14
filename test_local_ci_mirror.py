"""THE LOCAL GATE MUST STAY A MIRROR (founder 2026-08-11).

This repo is private, its Actions minutes ran out mid-month, and the founder's
ruling was DO NOT UPGRADE — merge on local evidence instead, documented in the
squash commit. `scripts/local_ci.sh` is that local evidence.

A hand-maintained copy of a CI job is a copy that drifts, and this one drifts
in the one direction nobody notices: CI grows a gate, the script doesn't, and
the local run goes on printing GREEN while covering less than it claims. The
outage makes that failure silent for weeks rather than minutes, because there
is no red X to contradict it.

So the mirror is asserted, not maintained by memory. These tests read both
files and fail on:

  · a pin that moved on one side (python, ruff, mypy) — a local mypy 1.x
    calling itself a stand-in for CI's 2.x is exactly the false green this
    whole arrangement cannot afford;
  · a quarantine list that no longer matches — an --ignore the script lacks
    turns green into red for environmental reasons, and one the script has
    but CI doesn't means the local run skips a module CI would have caught;
  · a CI gate with no counterpart step in the script.

Run: python3 -m unittest test_local_ci_mirror
"""
from __future__ import annotations

import os
import re
import unittest

ROOT = os.path.dirname(os.path.abspath(__file__))


def read(rel: str) -> str:
    with open(os.path.join(ROOT, rel), encoding="utf-8") as fh:
        return fh.read()


WORKFLOW = read(".github/workflows/tests.yml")
SCRIPT = read("scripts/local_ci.sh")

# The workflow's two jobs, split so `checks` assertions can't be satisfied by
# something that only appears in `evals`.
CHECKS, _, EVALS = WORKFLOW.partition("\n  evals:")

# Steps that build the ENVIRONMENT rather than gate the code. The script
# implements them in its setup block instead of as a `step`, so they are
# named here — which also means a NEW workflow step lands in neither list and
# fails the test until someone classifies it.
SETUP_STEPS = {"Set up Python 3.12", "Install dependencies"}


def step_names(job: str) -> list[str]:
    return re.findall(r"^\s+- name: (.+)$", job, re.M)


class PinTests(unittest.TestCase):
    def test_the_interpreter_minor_is_the_same_on_both_sides(self):
        # Patch level may differ (a local 3.12.9 is a fair stand-in for CI's
        # 3.12.1); the minor may not, because that is where syntax and stdlib
        # behaviour actually move. The script enforces this at runtime too.
        ci = re.search(r'python-version: "([\d.]+)"', CHECKS)
        mine = re.search(r'CI_PYTHON="([\d.]+)"', SCRIPT)
        self.assertIsNotNone(ci)
        self.assertIsNotNone(mine)
        self.assertEqual(ci.group(1), mine.group(1))

    def test_ruff_and_mypy_are_pinned_to_the_same_versions(self):
        for tool in ("ruff", "mypy"):
            pin = re.search(rf"{tool}==[\d.]+", CHECKS)
            self.assertIsNotNone(pin, f"{tool} pin vanished from the workflow")
            self.assertIn(
                pin.group(0), SCRIPT,
                f"the workflow pins {pin.group(0)}; scripts/local_ci.sh does not",
            )


class QuarantineTests(unittest.TestCase):
    def test_every_quarantined_file_exists(self):
        """A phantom entry is a list that has rotted (audit Q-T3, 2026-09-14).

        Four of the six entries named files deleted months earlier; the list
        looked maintained and covered nothing. An --ignore for a file that
        is not there is silently accepted by pytest, so only this test can
        notice. Removing a module means removing its entry in the same PR.
        """
        ci = re.findall(r"--ignore=(\S+\.py)", CHECKS)
        missing = [m for m in ci if not os.path.exists(os.path.join(ROOT, m))]
        self.assertEqual(
            missing, [],
            f"quarantined files that do not exist: {missing} — delete the "
            f"entry from BOTH tests.yml and scripts/local_ci.sh",
        )

    def test_no_test_modules_hide_in_scripts(self):
        """scripts/ is hand-run tooling, not a test tree. pytest collects
        test_*.py recursively from the repo root, so a test_ file parked
        under scripts/ would be collected as a test again — which is how
        two print scripts (now scripts/sentry_smoke.py and
        scripts/jwt_secret_check.py) sat in the quarantine list for months."""
        stray = sorted(
            n for n in os.listdir(os.path.join(ROOT, "scripts"))
            if n.startswith("test_") and n.endswith(".py")
        )
        self.assertEqual(stray, [], f"test modules under scripts/: {stray}")

    def test_the_ignore_list_matches_exactly(self):
        ci = set(re.findall(r"--ignore=(\S+\.py)", CHECKS))
        block = re.search(r"QUARANTINE=\(\n(.*?)\n\)", SCRIPT, re.S)
        self.assertIsNotNone(block)
        mine = set(block.group(1).split())
        self.assertTrue(ci, "the workflow's quarantine list disappeared")
        # Reported as a symmetric difference on purpose: BOTH directions are
        # defects, and they are different defects (see the module docstring).
        self.assertEqual(ci, mine, f"quarantine drift: {ci ^ mine}")


class CoverageTests(unittest.TestCase):
    def test_the_gate_exports_CI_like_actions_does(self):
        """GitHub Actions exports CI=true on every job. Tests marked CI-only
        (test_audio_metrics_features: the librosa/numba cold start, ~25 s
        per process — audit Q-T11) skip without it. The local mirror must
        export it in the unit-tier step or it covers less than CI does
        while printing GREEN."""
        step = re.search(r'step "Run unit-tier tests" env \\\n(.*?)\n\s*"\$PY"', SCRIPT, re.S)
        self.assertIsNotNone(step, "unit-tier step not found in the script")
        self.assertRegex(step.group(1), r"(?m)^\s*CI=1 \\$",
                         "the unit-tier step does not export CI=1")

    def test_every_gate_in_checks_has_a_step_in_the_script(self):
        for name in step_names(CHECKS):
            if name in SETUP_STEPS:
                continue
            self.assertIn(
                f'step "{name}"', SCRIPT,
                f"CI runs '{name}'; the local mirror does not — a local GREEN "
                f"would be claiming coverage it doesn't have",
            )

    def test_the_rehearsal_tier_is_bound_to_the_change_on_both_sides(self):
        """Both sides consult scripts/rehearsal_trigger.sh before deciding
        whether the PostgreSQL tier runs, and both run the same runner. A
        side that only ran it on --with-rehearsal would be back to
        discipline (audit Q-T2, founder 2026-09-14)."""
        for text, side in ((CHECKS, "workflow"), (SCRIPT, "script")):
            self.assertIn("scripts/rehearsal_trigger.sh", text,
                          f"the {side} does not consult the trigger")
            self.assertIn("scripts/rehearsal_tier.sh", text,
                          f"the {side} does not run the tier")
        self.assertIn('step "Rehearsal tier (PostgreSQL)"', SCRIPT)
        for helper in ("scripts/rehearsal_trigger.sh", "scripts/rehearsal_tier.sh"):
            self.assertTrue(os.access(os.path.join(ROOT, helper), os.X_OK),
                            f"{helper} is not executable")

    def test_the_blocking_evals_are_reachable_locally(self):
        # Both are merge-blocking in CI. They cost live model calls, so the
        # script keeps them behind --with-evals rather than running them on
        # every invocation — but they must be RUNNABLE, and the summary has
        # to say when they were skipped.
        for name in ("Master-doc probe", "Golden evals for changed prompts"):
            self.assertIn(f'step "{name}"', SCRIPT)
        self.assertIn("--with-evals", SCRIPT)
        self.assertIn("EVALS=", SCRIPT)

    def test_the_non_blocking_probe_is_not_treated_as_a_gate(self):
        # Router parity is a parked flag-OFF path: continue-on-error in CI,
        # and it must not be able to fail a local run either.
        self.assertIn("continue-on-error: true", EVALS)
        self.assertNotIn('step "Router parity probe', SCRIPT)


class UsabilityTests(unittest.TestCase):
    def test_the_script_is_executable(self):
        self.assertTrue(os.access(os.path.join(ROOT, "scripts/local_ci.sh"), os.X_OK))

    def test_a_failing_gate_cannot_exit_zero(self):
        # The one property that makes the whole thing worth having.
        self.assertRegex(SCRIPT, r'if \[ "\$FAILED" != 0 \]')
        self.assertIn("RED — do not merge.", SCRIPT)
        self.assertIn("exit 1", SCRIPT)

    def test_the_venv_is_not_committed(self):
        self.assertIn(".venv-ci/", read(".gitignore"))


if __name__ == "__main__":
    unittest.main()
