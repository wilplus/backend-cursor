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

import os

# The old name remains the DEFAULT on purpose: with the variable unset,
# every environment behaves exactly as it did before this module existed.
# Nothing changes until someone deliberately renames the table AND sets the
# variable, in that order.
LEGACY_SNIPPETS_TABLE = "charisma_snippets"

SNIPPETS_TABLE = (os.getenv("SNIPPETS_TABLE") or LEGACY_SNIPPETS_TABLE).strip()
