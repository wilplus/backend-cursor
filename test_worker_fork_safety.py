"""Fork safety and the singleton sweep chain — the two worker defects.

Both are invisible at runtime, which is why they are pinned statically.

1 · FORK-INHERITED TLS. `db = DatabaseService()` runs at import, and worker.py
    touches Supabase in the PARENT (warm-up, boot sweep) before forking slots
    with a `fork` context. Two processes writing into one TLS session produce
    SSLV3_ALERT_BAD_RECORD_MAC / "EOF occurred in violation of protocol", which
    services.db catches and logs as a warning — so the slot looks alive and
    silently does no work. job_queue already resets Redis for exactly this
    reason; the httpx half was missed.

2 · THE SWEEP CHAIN MULTIPLIED. run_sweep_loop re-enqueues itself in a
    `finally`, so a chain never ends, and every worker boot started a new one.
    Ten restarts left ten immortal chains sweeping in parallel — observed as
    eleven sweeps in four seconds, which reads like a hot loop and is actually
    an accumulation that never recovers.

Run: python3 -m unittest test_worker_fork_safety
"""
from __future__ import annotations

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).parent


def _calls_in(source: str, function: str) -> set[str]:
    """Every attribute/name called inside one top-level function."""
    tree = ast.parse(source)
    node = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == function), None)
    if node is None:
        return set()
    out = set()
    for call in ast.walk(node):
        if not isinstance(call, ast.Call):
            continue
        f = call.func
        if isinstance(f, ast.Name):
            out.add(f.id)
        elif isinstance(f, ast.Attribute):
            out.add(f.attr)
    return out


class TestForkSafety(unittest.TestCase):

    def test_the_db_client_can_be_rebuilt(self):
        """Without this there is nothing for a forked child to call."""
        source = (ROOT / "services" / "db.py").read_text()
        self.assertIn("def reset_connections(self)", source)

    def test_the_forked_slot_resets_both_connections(self):
        """Redis AND the DB. Resetting only Redis is the state that produced
        the SSL corruption — and it looked fine, because every failed read is
        swallowed and returns nothing."""
        calls = _calls_in((ROOT / "worker.py").read_text(), "_worker_child")
        self.assertIn("reset_connections", calls,
                      "the forked slot does not reset its inherited "
                      "connections")
        source = (ROOT / "worker.py").read_text()
        child = source[source.index("def _worker_child"):
                       source.index("def _run_worker_pool")]
        self.assertIn("services.db", child,
                      "the slot resets Redis but not the DB client — it will "
                      "share the parent's TLS socket")

    def test_the_pool_forks_which_is_why_this_matters(self):
        """If the pool ever moves to spawn, children get a fresh interpreter
        and the resets become harmless no-ops rather than load-bearing. This
        failing is a prompt to re-read, not necessarily to fix."""
        source = (ROOT / "worker.py").read_text()
        self.assertIn('get_context("fork")', source)


class TestSweepChainIsSingleton(unittest.TestCase):

    def test_boot_acquires_a_lease_before_starting_a_chain(self):
        """The whole fix. Without the gate, every boot adds an immortal
        chain."""
        calls = _calls_in((ROOT / "worker.py").read_text(), "main")
        self.assertIn("acquire_sweep_lease", calls,
                      "worker boot starts a sweep chain unconditionally — "
                      "one per restart, and they never die")

    def test_the_running_chain_renews_the_lease(self):
        """Without renewal the lease expires under a live chain and the next
        boot starts a second one alongside it."""
        calls = _calls_in((ROOT / "services" / "pipeline_jobs.py").read_text(),
                          "run_sweep_loop")
        self.assertIn("renew_sweep_lease", calls)
        self.assertIn("enqueue", calls)

    def test_the_lease_outlives_a_single_interval(self):
        """>1 interval so one slow or failed sweep cannot drop the lease;
        bounded so a genuinely dead chain is taken over, not stranded."""
        # Read rather than import: services.pipeline_jobs pulls in the
        # supabase client, which this pure-unit suite must not require.
        source = (ROOT / "services" / "pipeline_jobs.py").read_text()
        tree = ast.parse(source)
        value = next(n.value.value for n in tree.body
                     if isinstance(n, ast.Assign)
                     and getattr(n.targets[0], "id", "") == "SWEEP_LEASE_INTERVALS")
        self.assertGreater(value, 1)
        self.assertLessEqual(value, 6)

    def test_the_lease_fails_closed_without_a_broker(self):
        """No broker means no lease means no chain — the web-boot sweep and
        POST /v2/internal/jobs/sweep remain the backstops. Failing OPEN would
        start a chain on every boot again, which is the bug."""
        source = (ROOT / "services" / "job_queue.py").read_text()
        fn = source[source.index("def acquire_sweep_lease"):
                    source.index("def renew_sweep_lease")]
        self.assertIn("return False", fn)
        self.assertIn("SWEEP_LEASE_KEY", source)


if __name__ == "__main__":
    unittest.main()
