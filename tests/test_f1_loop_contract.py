"""THE F1 LOOP CONTRACT — what the pipeline work may not break.

FOUNDER, 2026-09-22, before releasing five parallel agent sessions onto the
provenance audit: "how can we do it so that the two things collaborate and
step by step sort of talk to each other and check if nothing got broken?"

This file is that mechanism, and it is deliberately a TEST and not a
document. Five parallel sessions will not read a document. They will run
the gate, because the gate is what stops their pull request merging. So the
protection lives inside the gate.

WHAT EACH LINE IS. One assertion, named in the words the founder used, over
the behaviour this week established. Every line is either

  GREEN  — true today, and a pipeline change that breaks it turns this file
           red and cannot merge; or
  XFAIL  — false today because the audit found a real defect, marked strict
           and tagged with its finding id.

STRICT IS THE WHOLE TRICK. `xfail(strict=True)` fails the suite when the
test starts PASSING. So the workstream that closes a finding is mechanically
forced to come here and flip its line, and cannot quietly close a finding
the contract still believes is open. Neither side has to remember the other
exists: one writes the fix, the gate notices.

WHAT THIS FILE IS NOT. It is not the audit, and it does not restate it. It
holds only the handful of behaviours a speaker would FEEL — bookmarks that
arrive and stay answered, a document that is never rebuilt, a wait that
never lies, no number on a user's screen. The audit's ninety-eight findings
have their own regression tests, named per finding, in their own files.

Unit tier on purpose: no database, no network, so it runs on every pull
request in this repository rather than only on the ones that touch
migrations. The database-bound half of the same contract lives in
`test_ideal_text_feedback_bake_postgres.py` (the stored bookmark set and
its freshness rule) and runs in the rehearsal tier.

Its ledger — which workstream flipped which line, and when — is
`docs/PIPELINE_WORK_LEDGER.md`.
"""
from __future__ import annotations

import sys
import types
import unittest
import unittest.mock

for _module in ("supabase", "sentry_sdk"):
    if _module not in sys.modules:
        sys.modules[_module] = types.ModuleType(_module)
if not hasattr(sys.modules["supabase"], "create_client"):
    sys.modules["supabase"].create_client = lambda *a, **k: None
    sys.modules["supabase"].Client = object
if not hasattr(sys.modules["sentry_sdk"], "capture_exception"):
    sys.modules["sentry_sdk"].capture_exception = lambda *a, **k: None


# ══════════════════════════════════════════════════════════════════════════
#  1. THE BOOKMARKS ARRIVE, AND THEY ARE THE ONES THAT WERE FROZEN
# ══════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════
#  2. AN ANSWERED BOOKMARK STAYS ANSWERED
# ══════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════
#  3. THE DOCUMENT IS CREATED ONCE AND NEVER REBUILT
# ══════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════
#  4. THE STORED BOOKMARK SET NEVER OUTLIVES AN ANSWER
# ══════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════
#  5. THE FIVE OWNER STATES SURVIVE THE WRITE
# ══════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════
#  6. NOTHING CHANGES THE SPEAKER'S WORDS WITHOUT A DECISION
# ══════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════
#  7. NO NUMBER REACHES A SPEAKER (AC-9)
# ══════════════════════════════════════════════════════════════════════════


class NoScoreReachesTheSpeaker(unittest.TestCase):
    """The fence that cannot be traded for anything. The read is
    qualitative; a score, ratio, verdict or classifier output never is."""

    BANNED = ("score", "ratio", "percentile", "confidence_value",
              "classifier", "probability", "z_score")

    def test_the_words_a_speaker_waits_on_name_work_not_judgement(self):
        """Every stage label the wait screen renders comes from here. They
        say what the machine is doing, never what it has concluded."""
        import inspect
        import re

        import services.analysis_worker as worker

        source = inspect.getsource(worker.run_full_analysis)
        emitted = re.findall(r'_emit\(progress,\s*"[a-z_]+",\s*\d+,\s*\n?\s*"([^"]+)"', source)
        self.assertTrue(emitted, "no stage labels found to check")
        for label in emitted:
            for banned in self.BANNED:
                with self.subTest(label=label, banned=banned):
                    self.assertNotIn(banned, label.lower())

    def test_the_stage_labels_a_speaker_reads_carry_no_verdict(self):
        """The wait screen's own words, checked here because the backend
        emits the stage names the screen renders."""
        import inspect

        import services.analysis_worker as worker

        source = inspect.getsource(worker.run_full_analysis)
        for banned in ("charisma", "stress score", "power_score ="):
            with self.subTest(banned=banned):
                self.assertNotIn(f'"{banned}"', source)


# ══════════════════════════════════════════════════════════════════════════
#  8. EVERY SERVICE THAT CAN DROP A WRITE SAYS WHAT IT READ
# ══════════════════════════════════════════════════════════════════════════


                                                        # and the unreadable
                                                        # one, once each
