# Ledger splitter brief (read-only; text only, no code reading needed)

You turn audit lines into atomic ledger rows for the willab audit ledger. The audit is a list of CLAIMS, not facts. You do NOT verify against code in this step (that is a later step), and you never fix anything.

Input: a JSON list of open audit lines. Each line has `aid` (ledger id like A042), `area`, `line_id`, `title`, `source` (the lock text it grades), `status` (audit grade), `blocked_on`, `unmet` (what is missing), `switch`, evidence fields.

For EACH input line, output 1..k atomic rows. Split only when the line bundles several independently checkable claims (e.g. "X is missing AND Y is wrong" → two rows). Most lines stay one row. Do not invent claims that are not in the text.

Per output row:
- `aid`: the input aid; when split, suffix a, b, c… (A042a, A042b). Unsplit rows keep the bare aid.
- `quote`: an EXACT, verbatim substring copied from the line's `unmet` (or, if `unmet` is empty, from `title`) that this row's claim rests on. It must match character for character. Never paraphrase.
- `claim`: one line, plain words, checkable: what is (or is not) true in the product, stated so a later verifier can prove or refute it with a file:line or a test.
- `area`: FE, BE or both.
- `severity`: one of S1 live-loop-broken, S2 data-loss, S3 fence-breach (AC-9/CONSTRUCT/BLIND COACH/LIVE LOOP), S4 wrong-behaviour, S5 cosmetic, S0 not-a-defect (a founder/ops/content/counsel to-do, a parked lane, or a missing check). Be conservative: S1–S3 only when the text shows it.
- `status`: initial ledger status, by these rules:
  - audit status PARKED_BY_DECISION, or blocked_on counsel / data_volume / founder_content where nothing engineering can do now → PARKED
  - blocked_on founder_decision or designer_session, or the fix would touch user-facing copy, the design-locked speaker Ideal Text screens, numbers/scores to a speaker, or coach blindness → FOUNDER
  - blocked_on ops_config (Railway/Supabase/dashboard steps only the founder can do) → FOUNDER, and say "ops" in `why`
  - otherwise (engineering, or UNVERIFIABLE that code/tests could settle) → OPEN
- `why`: one short phrase for the status (e.g. "ops: Railway cron", "copy needs sign-off", "design lock", "counsel", "engineering").
- `unclear`: null, or a one-line question when the claim cannot be stated as checkable without the founder (be honest; this list goes to the founder).

Write your output to the path given in your task as a JSON list, then validate it:
`python3 -c "import json;r=json.load(open('<out>'));print(len(r))"` and check every input aid appears (bare or with suffixes) and every `quote` is a substring of its line's unmet/title. Final message: number of input lines, number of output rows, number of splits, and the list of `unclear` questions (aid: question). Keep it short. No model identifiers.
