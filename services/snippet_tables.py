"""The physical name of the snippet table, in ONE place.

WHY THIS MODULE EXISTS. `charisma_snippets` is not a charisma table. It is the
shared snippet substrate, and it has FIVE producers:

    Path A  interview turns (/v2/public/interview/upload-answer)  source_type NULL
    Path B  extract_recording_snippets — the funnel cold-start    source_type NULL
    Path C  the ML generator                     'student' / 'internet'  DELETED
    Path D  willab Lab auto-cut (create_charisma_snippet)         source_type NULL
    Path E  snippet_truncation's session re-cut          source_type 'auto_extracted'

Path C is the only one the name ever described, and it was deleted on
2026-08-10 (PR #368). The other four are live and carry real user recordings.
So the name is a fossil that makes every reader of `user_chat.py` or
`coaching.py` believe in a feature that does not exist — while the table under
it is load-bearing. Production on 2026-08-10: 1216 NULL, 39 'student', 21
'auto_extracted'.

THE source_type FILTERS ARE OWNERSHIP CLAIMS, and they are disjoint on
purpose. `v2_delete_lab_snippets_for_recording` deletes `source_type IS NULL`;
`snippet_truncation` deletes only `source_type = 'auto_extracted'` and says
plainly that rows outside that "we don't own". Widening either filter to
"all rows for this session/recording" is the single most destructive edit
available in this file's neighbourhood — it would make one producer's cleanup
delete another's live rows, and the symptom would be users' recordings
quietly disappearing.

THE RENAME IS A TWO-STEP CUTOVER, AND THE ENV VAR IS WHY IT IS SAFE.

The obvious approach — rename the table, then deploy code that uses the new
name — has a window where the running code queries a name that no longer
exists. PostgREST answers 404, and this codebase swallows those exceptions by
design, so the failure is SILENT: interview answers and Lab cuts would vanish
for the length of a deploy with nothing going red.

The other obvious approach — rename, then leave a compatibility VIEW behind
under the old name — is worse, and specifically dangerous here.
`add_rls_all_public_tables.sql` names this table as one that `anon` can reach
directly through PostgREST, where "RLS is the only control on it". A view runs
with its OWNER's rights unless it is declared `security_invoker = true`, so a
naive compat view silently REOPENS that hole — and the backend, which connects
with the service-role key and bypasses RLS anyway, would show no symptom at
all.

Reading the name from the environment avoids both. The cutover becomes:

    1. deploy this code                      (no behaviour change)
    2. ALTER TABLE public.charisma_snippets RENAME TO snippets;
    3. set SNIPPETS_TABLE=snippets in Railway

Step 3 is a config change, not a deploy — seconds, not minutes — and step 2
carries RLS policies, indexes, foreign keys and grants along with the table
automatically. Rollback is the same two steps backwards, equally fast. No view
is ever created, so the RLS hazard never exists.

Runbook and cutover checklist: docs/OPS-FLAGS-AND-RELEASES.md.

ONCE THE CUTOVER IS DONE AND SETTLED, this module collapses to a plain
constant and the environment variable is deleted. It is a migration
affordance with an expiry date, not a configuration knob — a table name that
stays configurable forever is a table name nobody can grep for.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

# The old name remains the DEFAULT on purpose: with the variable unset,
# every environment behaves exactly as it did before this module existed.
# Nothing changes until someone deliberately renames the table AND sets the
# variable, in that order.
LEGACY_SNIPPETS_TABLE = "charisma_snippets"

SNIPPETS_TABLE = (os.getenv("SNIPPETS_TABLE") or LEGACY_SNIPPETS_TABLE).strip()


def check_at_boot() -> None:
    """Say which table this process resolved, and whether it can read it.

    WHY THIS EXISTS — the 2026-08-10 incident. The cutover was UNOBSERVABLE:
    you set a variable and had no way to see what the process did with it.
    Every symptom of "variable did not take effect", "restart never
    completed", "the running commit predates the code that reads the
    variable", and "PostgREST is serving a stale schema" is IDENTICAL from
    the outside — writes stop, nothing goes red, and the only evidence is a
    row count that fails to move. Twenty minutes went into distinguishing
    causes that one log line separates instantly.

    So this logs the resolved name unconditionally (that alone settles
    "did the variable take effect?"), then reads one row to prove the name is
    actually reachable. A failure is CRITICAL, not a warning: it means every
    snippet write in this process will be swallowed, which is the single
    worst failure this table has.

    NEVER RAISES. The LIVE LOOP fence: a table this process cannot see is a
    reason to shout, never a reason to refuse to boot — refusing would turn a
    recoverable misconfiguration into an outage.
    """
    source = "SNIPPETS_TABLE env" if os.getenv("SNIPPETS_TABLE") else "default"
    logger.info("snippets: table resolved to '%s' (%s)", SNIPPETS_TABLE, source)
    try:
        from services.db import db
        db.client.table(SNIPPETS_TABLE).select("id").limit(1).execute()
        logger.info("snippets: '%s' is readable", SNIPPETS_TABLE)
    except Exception as e:
        logger.critical(
            "SNIPPET TABLE UNREACHABLE — resolved '%s' (%s) but the read "
            "failed: %s. EVERY snippet write in this process will fail "
            "SILENTLY (the writers swallow exceptions by design). Fix: check "
            "the table name actually exists, then run "
            "NOTIFY pgrst, 'reload schema'; and restart. Mid-rename? unset "
            "SNIPPETS_TABLE and rename the table back — see "
            "docs/OPS-FLAGS-AND-RELEASES.md.",
            SNIPPETS_TABLE, source, e)
