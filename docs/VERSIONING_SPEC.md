# VERSIONING_SPEC.md — how the ideal text evolves

**Status:** confirmed against shipped code, 2026-07-23 (Stage 4 / T1).
**Scope:** the versioning engine — how a project's ideal text is built from
takes, how changes are surfaced and approved, and what carries forward.
Every engine card (T2 approval-memory, T3 sub-chunk emphasis) builds from
this; if the code and this doc disagree, that is a bug in one of them.

**Out of scope (do NOT build from this):** progressive shortening (E-1) is
a later stage. This spec never asks the text to get shorter.

---

## 1. The document model

* One **project = one arc** (`arc_id`). One persistent **master document**
  per project — a new take never replaces it wholesale; it only offers
  block-level upgrades where it beats the current text.
  (`services/master_document.py`, flag `MASTER_DOCUMENT_ENABLED`.)
* **Per-project numbering.** The badge is `take_count.0` — the count of
  official (spoken) takes of *this* arc, reads excluded. Never a global
  tally. `version` (a separate field) bumps only when the text actually
  changes; the badge uses `take_count`, which climbs on every take.
* **Not a raw dump, not an AI rewrite.** The served text is the speaker's
  **verbatim words**, minimally smoothed (§2). Everything beyond the
  fenced smoothing is a **visible, approvable change** — never silent.

## 2. Silent smoothing — the ONLY things that change without asking

`services/transcript_smoothing.py`. Exhaustive; anything not on this list
is a suggestion, never a silent edit:

1. **Hesitations** — a closed, *language-aware* token list (um/uh/…);
   real words are never removed (German/Portuguese "um" is kept).
2. **Immediate word repeats** — "the the" → "the". An expressive repeat
   separated by punctuation ("no, no, no") is kept.
3. **Punctuation + casing** — sentence-initial capitals and one terminal
   mark, applied once to the finished document (never per fragment, so no
   fabricated sentence breaks at a cut).

That is the whole silent surface. False starts, rephrasings, the compose
LLM's smoothing, a coach's wording change — all approvable, never silent.

## 3. Inputs that can trigger a fragment change

* **The new take** — its verbatim transcript, §2-smoothed.
* **The prior approved text** — the default; carried forward untouched
  unless a change is approved against it (§5).
* **Per-fragment signals**, judged by the shipped blended ranking
  (`power_score`; L2): delivery/acoustic quality, fluency/coherence,
  slide stickiness (coverage). Coach direction feeds ranking where a
  label exists.
* **Repeated user phrasing** — wording the speaker uses in ≥ 2 takes is
  **kept as their voice** and locked out of change suggestions
  (`services/protected_phrases.py`), except the harmful carve-out
  (profanity / threat still surface).

## 4. Allowed outputs per fragment

Exactly four, all span-anchored (`services/tracked_changes.py`):

| kind      | renders as                                   | on approve |
|-----------|----------------------------------------------|------------|
| `keep`    | nothing — the fragment stands                | n/a |
| `replace` | old struck through + new inline              | words swap, baked forward |
| `emphasize` (bold) | the sub-span accented               | stays bold |
| `advise`  | no text change; points at the span           | n/a (delivery/structural coaching) |

Cross-take: where a *previous* take said the same thing better it returns
as a `replace` (`source: prior_take` / `new_take`) carrying its origin
take badge and a deterministic why-key
(`energy | steadiness | coverage | overall`).

## 5. The no-revert invariant (T2's contract)

* An **approved** change on version N is **baked into N+1 and every later
  assembly** wherever its phrase still occurs — plain text, no star, never
  auto-reverted (`ideal_decision_ledger.bake_piece`, run at every
  assembly).
* A **dismissed** change is remembered and never re-offered for that
  phrase.
* **Reasoning shows only for the current step.** Generation filters every
  already-decided phrase, so a version's suggestions are that version's
  *delta* — an already-approved fragment renders as plain baked text with
  no underline or reasoning. A later take that would touch it appears as a
  **new** suggestion with its own fresh reasoning, never a silent revert.

## 6. Chunking rule

* **Structure** stays at the section/piece grain: pieces are cut on slide
  boundaries (decked) or a ~200–300-char sentence cap (deckless); this
  division is fixed and not what suggestions operate on.
* **Suggestions** operate at the **sub-chunk** grain — a ~20–50-char span
  *within* a section. A half-sentence fix underlines only that half; the
  rest of the section stays clean.
  * Shipped: `replace` (polish diff / profanity sentence) already narrows
    to the sub-span (`services/suggestion_quotes.py`).
  * **Gap (T3 / limitation A):** `emphasize` currently spans its whole
    fragment — no sub-sentence emphasis signal yet. T3 closes this.

## 7. Known v1 limitations (C-3 gate)

* **A — emphasis spans the whole fragment.** No sub-sentence signal yet.
  Closed by T3.
* **B — cross-take ranking is delivery + coverage only.** The coach's
  label lives in a different table (`training_labels`), not on the snippet
  row, so the block comparison does not read it; the field that pretended
  to was removed rather than left as a silent no-op. Adding it is a later
  enhancement, not a correctness bug.

## 8. Fences (non-negotiable, enforced in code + tests)

* **L1** — served text is verbatim actual speech; only §2 changes
  silently. An LLM may output boundaries/mappings, never words that get
  served.
* **L2** — `power_score` judges, deterministically.
* **AC-9 / construct** — no scores/numbers/verdicts on a user payload;
  badges are take numbers, why-keys are the four-word set.
* **Live loop** — every lane is flag-gated and best-effort; flag-off is
  byte-for-byte the prior behavior.
