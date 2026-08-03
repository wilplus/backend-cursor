"""willab prompt registry — every LLM prompt lives here, versioned.

Founder decision 2026-08-03 ("Eval Harness" plan): prompts are product
surface, not incidental strings. This package is the single home for
every prompt the backend sends to an LLM, so that:

  1. **Drift is visible.** ``registry.py`` hashes every prompt into
     ``prompts.lock.json`` (checked in). Editing a prompt without
     updating the lockfile fails the unit tier — every prompt change
     is an explicit, reviewable diff.
  2. **Edits are eval-gated.** CI diffs the lockfile against the merge
     base to find WHICH prompts changed, and runs the matching golden
     evals (tests/evals/) before the change can merge — the
     master_doc_probe pattern, extended to the F1 surfaces.

Layout
------
One module per surface (``say_it_stronger.py``, ``best_presentation.py``,
…). Each module declares ``REGISTER: dict[str, str | callable]`` mapping
prompt ids (``"<surface>.<part>"``) to either a static string or a pure
builder function. Builders that interpolate context stay FUNCTIONS
(moved verbatim from their service) — converting f-strings to ``.format``
templates risks silent behavior change on literal braces, which the
refactor guard forbids.

Rules for modules in this package:
  * stdlib-only imports (the registry must import in CI with no
    OpenAI / Supabase credentials);
  * builders are pure text functions — no I/O, no LLM calls, no db;
  * the SERVICE keeps the LLM call, the schema, and the output guards;
    only the prompt text/builders live here.

Fences: extraction is verbatim-only (L1/L2/L3 untouched, live loop
untouched). Prompt copy that surfaces to users still needs founder
sign-off before EDITS — this package changes where prompts live, never
what they say.
"""
