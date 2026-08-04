# Prompt registry & golden evals

Founder decision 2026-08-03 (the "Eval Harness" plan): prompts are
product surface. Two guardrails now exist, one free and deterministic,
one behavioral and LLM-graded.

## 1. The registry + drift lock (deterministic, always on)

Every LLM prompt is tracked in `services/prompts/`:

- **Extracted tier** — one module per surface holding the verbatim
  prompt text/builders (`say_it_stronger.py`, `best_presentation.py`,
  `slide_alignment.py`, `coach_comment_drafter.py`,
  `moment_suggestions.py`, `delivery_alignment.py`,
  `master_document.py`, `snippet_stickiness.py`). Services import from
  here; the text was moved byte-identically (verified by capturing the
  exact strings sent to the LLM on fixed inputs, pre and post move).
- **Pending tier** (`services/prompts/pending.py`) — every prompt not
  yet physically moved (the legacy `openai_service` hub, `v2_routes`
  interview/coaching, `master_doc_rag`, `life_engine`, …) is pinned by
  a `SourceRef` that hashes its source segment in place, via `ast`,
  with no imports. ~118 prompts across 30 files are covered TODAY;
  physical extraction proceeds surface-by-surface in small verbatim
  PRs (see `say_it_stronger.py` for the pattern).

All hashes live in `services/prompts/prompts.lock.json`. The unit-tier
test `test_prompt_registry.py` fails on any mismatch, so **editing a
prompt without regenerating the lockfile cannot merge**. After an
intentional edit:

```
python -m services.prompts.registry update      # regenerate + commit
python -m services.prompts.registry check       # verify
python -m services.prompts.registry changed --against <old-lock>
```

The lockfile diff is the prompt-change review artifact: reviewers see
exactly WHICH prompts a PR touches.

## 2. Golden evals (behavioral, LLM-graded, keyed to drift)

The `master_doc_probe.py` pattern, generalized: deterministic checks
first (code counts characters; LLMs don't), then a temperature-0
semantic grader only where the rubric declares `semantic_intent`.

- Harness: `tests/evals/harness.py`
- Adapters (golden input → real production function):
  `tests/evals/surfaces.py`
- Datasets: `tests/evals/golden/<surface>.jsonl`
- Runner: `python tests/evals/run_prompt_evals.py --all | --surface X |
  --changed-against <old-lock>`

CI (`prompt-evals` job) diffs the lockfile against the merge base and
runs evals **only for the surfaces whose prompts changed**. Without
`OPENAI_API_KEY` the job skips green (probe precedent — the gate is
armed by the repo secret, never red for a missing credential). Cost is
pennies per run. `master_doc_rag.*` drift is gated by the always-on
master-doc-probe job and is not re-run here. `will_voice.*` drift runs
every surface that has a dataset, because the voice rules ride ~13
system prompts.

The current `golden/*.jsonl` files are **engineering seeds** proving
the pipeline end-to-end — the founder's golden datasets replace and
extend them.

## 3. Golden dataset format (what the founder authors)

**JSONL** — one JSON object per line, one line per case. `//` lines
are comments. File name = surface name (`say_it_stronger.jsonl`).

```json
{"id": "SIS-042",
 "surface": "say_it_stronger",
 "description": "hedged apology keeps the speaker's register",
 "input": {"transcript": "...", "context": {"topic": "...", "audience": "..."}},
 "rubric": {
   "must_not_mention_substrings": ["leverage", "synergy"],
   "no_digits": true,
   "semantic_intent": "One sentence stating the outcome a passing output achieves."
 },
 "notes": "free-form PM commentary; ignored by the harness"}
```

Fields:

| field | required | meaning |
|---|---|---|
| `id` | yes | unique per file; short, stable (used in failure reports) |
| `surface` | yes | must equal the filename stem |
| `description` | no | one line shown in the report |
| `input` | yes | what the production function receives — see each adapter in `tests/evals/surfaces.py` for the accepted keys |
| `rubric` | yes | the grading rules (below) |
| `notes` | no | your commentary; never machine-read |

Rubric keys (compose freely; deterministic ones run first and are
preferred wherever a rule CAN be deterministic):

| key | type | check |
|---|---|---|
| `must_mention_substrings` | list | each must appear (case-insensitive) |
| `must_not_mention_substrings` | list | none may appear (case-insensitive) |
| `must_mention_any` | list | at least one must appear |
| `must_not_substring` | list | none may appear (case-SENSITIVE, verbatim) |
| `max_chars` | int | length ceiling on the flattened output |
| `no_digits` | bool | AC-9: no digits anywhere in the output |
| `must_not_match_construct` | bool | the retired-construct regex (production `_CONSTRUCT_RE`) must not match |
| `must_contain_polish_diacritic` | bool | deterministic "answered in Polish" |
| `expect` | object | `{"dotted.path": exact_value}` pins into structured output (list indexes allowed: `"a.0"`) |
| `expect_contains` | object | `{"dotted.path": substring}` (case-insensitive) |
| `substring_of_input` | list | `[{"path": "quote", "input": "transcript"}]` — output field must be a verbatim substring of an input field (anti-hallucination / L1 pins) |
| `allow_none_output` | bool | a `None` return is a pass (for surfaces where declining is correct) |
| `semantic_intent` | string | ONE sentence; judged by the temperature-0 grader. Keep it a single outcome, not a three-clause aspiration (probe v2 lesson: less surface area, less grader hallucination) |

Authoring guidance (from the probe's hard-won history):

- **Prefer deterministic keys.** Every `semantic_intent` is a coin
  with a small flake rate; every substring/expect check is free and
  never flakes. The probe's v2/v3 changelog is a record of converting
  flaky semantic checks into deterministic ones.
- **Preferred outputs**: express them as `expect` pins where exact
  (e.g. `already_strong` behavior), or fold them into
  `semantic_intent` ("the rewrite keeps X") where fuzzy. A verbatim
  "preferred output" string for a stochastic surface will flake —
  describe the property that makes an output preferred instead.
- Keep inputs **synthetic and PII-free** (probe rule).
- 5–15 cases per surface is plenty to start; each case costs ~a cent.

## 4. What's NOT gated yet (known gaps)

- `routes/v2_routes.py` interview/coaching prompts and the
  `openai_service` legacy hub are drift-TRACKED (pending tier) but
  have no golden datasets yet — function-level hash granularity means
  edits there flag conservatively. Physical extraction shrinks the
  granularity to the prompt text itself.
- Surfaces without datasets skip green with a printed note; coverage
  grows dataset-by-dataset with zero harness changes.
