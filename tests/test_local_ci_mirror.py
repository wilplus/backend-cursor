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
  · a CI gate with no counterpart step in the script;
  · a fetch of origin/main that changes how deep the clone is — the one
    line that must NOT copy the workflow (CloneDepthTests).

Run: python3 -m unittest tests.test_local_ci_mirror
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


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
        for tool in ("ruff", "mypy", "pytest-cov", "radon"):
            pin = re.search(rf"{re.escape(tool)}==[\d.]+", CHECKS)
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

    def test_the_gate_reads_no_dotenv_like_actions_does(self):
        """The job's checkout has no .env. A local one is found by walking up
        from the calling file, so a worktree under .claude/worktrees/ read the
        main checkout's .env — real R2 credentials — and failed three tests
        CI passes (2026-10-05). The switch must be exported before the first
        step so every step inherits it."""
        export = SCRIPT.find("\nexport PYTHON_DOTENV_DISABLED=1\n")
        self.assertNotEqual(export, -1, "the script does not export PYTHON_DOTENV_DISABLED=1")
        self.assertLess(export, SCRIPT.find('\nstep "'),
                        "PYTHON_DOTENV_DISABLED is exported after a step has run")

    def test_the_pinned_dotenv_honours_the_switch(self):
        """python-dotenv honours PYTHON_DOTENV_DISABLED natively from 1.2.0.
        Below that, the export is a no-op unless the root conftest.py
        backports it — so the backport may only go when the pin moves."""
        pin = re.search(r"^python-dotenv==([\d.]+)$", read("requirements.txt"), re.M)
        self.assertIsNotNone(pin, "python-dotenv pin vanished from requirements.txt")
        if tuple(int(p) for p in pin.group(1).split(".")) >= (1, 2, 0):
            return
        conftest = read("conftest.py")
        self.assertIn('os.environ.get("PYTHON_DOTENV_DISABLED"', conftest)
        self.assertIn("dotenv.load_dotenv = dotenv.main.load_dotenv =", conftest)

    @unittest.skipUnless(
        os.environ.get("PYTHON_DOTENV_DISABLED") == "1",
        "only under scripts/local_ci.sh, which exports PYTHON_DOTENV_DISABLED=1",
    )
    def test_under_the_gate_config_loads_no_dotenv(self):
        import io

        import config

        try:
            loaded = config.load_dotenv(stream=io.StringIO("WILLAB_DOTENV_PROBE=leaked\n"))
            self.assertFalse(loaded, "config.load_dotenv still reads .env under the gate")
            self.assertNotIn("WILLAB_DOTENV_PROBE", os.environ)
        finally:
            os.environ.pop("WILLAB_DOTENV_PROBE", None)

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


class CloneDepthTests(unittest.TestCase):
    """The fetch of origin/main is the one line that must NOT copy the workflow.

    CI's checkout is shallow already, so `git fetch --depth=1` costs it
    nothing. On a full clone the same command writes `shallow` into the git
    dir that the main checkout and every worktree share, and all of them lose
    their history behind origin/main's tip. That is what the ledger step did
    from the day it landed (#911, 2026-10-06): `git rev-list --count
    origin/main` went to 1, merge-bases with older branches stopped
    resolving, and test_legal_citations went red in every worktree. So both
    fetches keep the clone's depth.

    Demonstrated, not grepped: each test clones a real upstream, full or
    shallow, adds a worktree as on the founder's Mac, moves the upstream on,
    and runs the script's own code from the worktree."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        # A sandboxed git: none of the developer's config (signing, hooks),
        # and no GIT_DIR inherited from a calling hook, which would point
        # these commands at the real repository.
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(
            HOME=self.tmp, XDG_CONFIG_HOME=self.tmp, GIT_CONFIG_NOSYSTEM="1",
            GIT_AUTHOR_NAME="gate", GIT_AUTHOR_EMAIL="gate@example.invalid",
            GIT_COMMITTER_NAME="gate", GIT_COMMITTER_EMAIL="gate@example.invalid",
        )
        self.upstream = os.path.join(self.tmp, "upstream")
        self.git(self.tmp, "init", "-q", "-b", "main", self.upstream)
        for n in range(3):
            self.git(self.upstream, "commit", "-q", "--allow-empty", "-m", f"c{n}")

    def git(self, cwd: str, *args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=cwd, env=self.env, check=True,
            capture_output=True, text=True,
        ).stdout.strip()

    def clone(self, *, shallow: bool) -> tuple[str, str]:
        clone = os.path.join(self.tmp, "clone")
        worktree = os.path.join(self.tmp, "worktree")
        # file:// so --depth is honoured; a plain path is a local clone, which
        # ignores it.
        depth = ["--depth=1"] if shallow else []
        self.git(self.tmp, "clone", "-q", *depth, "file://" + self.upstream, clone)
        self.git(clone, "worktree", "add", "-q", "--detach", worktree)
        self.git(self.upstream, "commit", "-q", "--allow-empty", "-m", "c3")
        return clone, worktree

    def assert_depth_kept(self, clone: str, *, shallow: bool) -> None:
        self.assertEqual(self.git(clone, "rev-parse", "origin/main"),
                         self.git(self.upstream, "rev-parse", "main"),
                         "origin/main was not brought up to date")
        self.assertEqual(self.git(clone, "rev-parse", "--is-shallow-repository"),
                         "true" if shallow else "false",
                         "the fetch changed whether the clone is shallow")
        # Full: all four commits. Shallow: still one, as CI fetches it; a
        # plain fetch would pull in history the job does not need.
        self.assertEqual(self.git(clone, "rev-list", "--count", "origin/main"),
                         "1" if shallow else "4")

    def run_ledger_check(self, worktree: str) -> None:
        """local_ci.sh's own ledger_check(), lifted out of the script and run
        with a stand-in interpreter: the fetch is real, the checker is not."""
        fn = re.search(r"^ledger_check\(\) \{\n.*?^\}$", SCRIPT, re.S | re.M)
        if fn is None:
            self.fail("ledger_check() not found in scripts/local_ci.sh")
        os.makedirs(os.path.join(worktree, "docs", "audit"))
        open(os.path.join(worktree, "docs", "audit", "LEDGER.md"), "w").close()
        subprocess.run(["bash", "-c", fn.group(0) + "\nledger_check"], cwd=worktree,
                       env=dict(self.env, PY="true"), check=True, capture_output=True)

    def run_trigger(self, worktree: str) -> None:
        """The real scripts/rehearsal_trigger.sh, copied into the worktree it
        judges (it finds its repository from its own path). 0 and 1 are both
        verdicts; anything else means it never got as far as judging."""
        os.makedirs(os.path.join(worktree, "scripts"))
        script = shutil.copy(os.path.join(ROOT, "scripts", "rehearsal_trigger.sh"),
                             os.path.join(worktree, "scripts"))
        done = subprocess.run(["bash", script, "--quiet"], cwd=worktree, env=self.env,
                              capture_output=True, text=True)
        self.assertIn(done.returncode, (0, 1), done.stderr)

    def test_the_ledger_fetch_leaves_a_full_clone_full(self):
        clone, worktree = self.clone(shallow=False)
        self.run_ledger_check(worktree)
        self.assert_depth_kept(clone, shallow=False)

    def test_the_ledger_fetch_stays_one_commit_deep_in_a_shallow_clone(self):
        clone, worktree = self.clone(shallow=True)
        self.run_ledger_check(worktree)
        self.assert_depth_kept(clone, shallow=True)

    def test_the_rehearsal_trigger_leaves_a_full_clone_full(self):
        clone, worktree = self.clone(shallow=False)
        # The trigger fetches only when origin/main is missing.
        self.git(clone, "update-ref", "-d", "refs/remotes/origin/main")
        self.run_trigger(worktree)
        self.assert_depth_kept(clone, shallow=False)

    def test_the_rehearsal_trigger_stays_one_commit_deep_in_a_shallow_clone(self):
        clone, worktree = self.clone(shallow=True)
        self.git(clone, "update-ref", "-d", "refs/remotes/origin/main")
        self.run_trigger(worktree)
        self.assert_depth_kept(clone, shallow=True)

    def test_the_rehearsal_trigger_does_not_fetch_when_origin_main_is_there(self):
        clone, worktree = self.clone(shallow=False)
        before = self.git(clone, "rev-parse", "origin/main")
        self.run_trigger(worktree)
        self.assertEqual(self.git(clone, "rev-parse", "origin/main"), before)


if __name__ == "__main__":
    unittest.main()
