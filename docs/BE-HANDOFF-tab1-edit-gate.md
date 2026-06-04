# BE handoff — Tab 1: >5-word-change save gate (anti-lazy-admin)

Status: **NOT STARTED — needs FE confirmation on 4 questions below.**
Implementation is small (~50 LOC across two endpoints + one shared helper). Want to confirm shape with FE before shipping so we don't double-trip on the contract.

---

## What the gate protects

Two RLHF-logged fields fed by AI drafts. Each existing write endpoint emits a row to `admin_annotations_log` (the training corpus). If the admin saves the AI draft unchanged or with a one-word tweak, the model "learns" that its own draft was perfect — feedback loop garbage. The gate stops sub-threshold edits from reaching the corpus.

| Field | Write endpoint | DB column | AI-draft baseline |
|---|---|---|---|
| Per-snippet comment | `POST /v2/admin/snippets/<snippet_id>/comment` ([routes/v2_routes.py:13293](routes/v2_routes.py:13293)) | `charisma_snippets.admin_comment` | `charisma_snippets.ai_draft_admin_comment` |
| Session-level AI commentary | `POST /v2/admin/sessions/<session_id>/publish` ([routes/v2_routes.py:14262](routes/v2_routes.py:14262)) | written into `admin_annotations_log` via `final_human_comment` body field | the model's pre-publish suggestion (lives upstream in the session payload; FE has it) |

**Third surface that could need the same gate** — open question for FE:

| Field | Same publish endpoint | AI-draft baseline |
|---|---|---|
| `final_human_next_questions` (array of up to 5 question strings) | Same `POST .../publish` | The pre-baked AI script per snippet — already lives on the row the FE renders |

The brief only says "two editable text fields." If the 5 questions count as one bucket each, that's seven total surfaces. **FE confirm: gate the script questions or only the prose comments?**

---

## Proposed algorithm — word-level diff

`difflib.SequenceMatcher` on whitespace-split tokens of both strings, count operations:

```python
import difflib, re

def _normalise(s: str) -> list[str]:
    """lowercase + strip punctuation + split on whitespace."""
    s = (s or "").lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return s.split()

def word_diff_count(draft: str | None, final: str | None) -> int:
    """How many word-level tokens changed between draft and final.
    Symmetric: insertions + deletions + replacements (each counted once).
    Empty/None draft → returns len(final tokens) so admin's typed-from-scratch
    content always passes the gate.
    """
    d = _normalise(draft)
    f = _normalise(final)
    if not d:
        return len(f)  # all new content = full credit
    sm = difflib.SequenceMatcher(a=d, b=f, autojunk=False)
    changed = 0
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            continue
        # 'replace' / 'delete' / 'insert' — count the larger side so
        # a 3-word swap counts as 3, not 6
        changed += max(i2 - i1, j2 - j1)
    return changed
```

Threshold: `> 5` (i.e. 6+ tokens different). Edge cases:
- Empty draft (no AI starting point) → admin's content counts fully against threshold. Means short typed-from-scratch comments still get gated. Acceptable IMO since the field is meant to be substantive; FE override if you prefer "no AI draft = no gate."
- Whitespace-only on either side → treated as empty.
- Case-insensitive + punctuation-insensitive — `"Hello, world!"` vs `"hello world"` is 0 diff. Stops admins from fake-editing by changing capitalization.

**FE confirm**: this algorithm acceptable, or do you want a different metric (raw char distance? Levenshtein? something else)?

---

## Proposed server-side contract

Both endpoints grow the same two-flag pattern in their request body:

```jsonc
// POST /v2/admin/snippets/<snippet_id>/comment
// POST /v2/admin/sessions/<session_id>/publish
{
  /* existing fields stay unchanged */
  "admin_comment": "the edited text",
  "ai_draft_baseline": "the AI text the admin started from",  // NEW: FE sends so BE can diff
  "is_trivial_edit": false                                     // NEW: override flag
}
```

**Behaviour:**
- `is_trivial_edit: false` (default) + word-diff > 5 → write to user-facing column AND emit RLHF row. Today's behavior.
- `is_trivial_edit: false` + word-diff ≤ 5 → reject with **422 EDIT_TOO_SMALL** + helpful error body. Nothing written.
- `is_trivial_edit: true` → write to user-facing column, **skip RLHF emission entirely**. User sees the edit; the corpus doesn't.
- `ai_draft_baseline` absent (legacy callers) → BE looks up `ai_draft_admin_comment` from the row itself for the snippet endpoint; for publish, BE doesn't have a single "draft" field, so legacy callers without the baseline get the legacy behavior (no gate). Document this as the migration window.

422 response shape:
```jsonc
{
  "code": "EDIT_TOO_SMALL",
  "error": "Edit too minor to feed the training pipeline (need >5 word-level changes). Use is_trivial_edit=true to save as user-facing only.",
  "diff_count": 2,
  "threshold": 5
}
```

**FE confirm**: this contract, or do you want a different field name / status code / error shape?

---

## FE deliverables

- **Tab 1 — per-snippet comment editor:**
  - Compute `word_diff_count(ai_draft_admin_comment, current_textarea_value)` client-side as the admin types (debounced)
  - Disable Save button when count ≤ 5 AND the trivial-edit override checkbox is unchecked
  - Show a small inline hint: `"3 / 6 words changed — add 3 more or tick 'minor edit'"`
  - Trivial-edit override: small checkbox below the Save button, label `"Save as minor edit (won't feed training)"`
  - On 422 EDIT_TOO_SMALL from the server (defensive — client should never let this through), surface a toast with the server's `error` text

- **Tab 1 — session-level AI commentary:** same pattern at the publish step. The publish modal/panel needs the same gate + checkbox before the `POST .../publish` call goes out.

- **Trivial-edit override semantics:** the checkbox state must be sent in the request body so the server can skip the RLHF emission. FE doesn't need to know about the corpus internals — just send the flag truthfully.

---

## Four questions for FE before I ship

1. **Scope** — gate just the prose comments (per-snippet + session-level), or also gate the `final_human_next_questions` array (5 questions × per-question word-diff)?
2. **Algorithm** — the `difflib`-based word-diff above acceptable, or do you want something else (Levenshtein, raw char-distance, ratio-based)?
3. **Empty-draft behavior** — admin typing from scratch (no AI draft to diff against). Gate applies to absolute word count (current proposal), or skip the gate entirely when there's no baseline?
4. **Trivial-edit override** — checkbox per the above, or a different UI (separate "Quick fix" button)? Either works for me; FE knows the design system.

---

## Acceptance criteria

- Admin types the AI draft verbatim → Save disabled (FE) + 422 EDIT_TOO_SMALL (BE) if the FE check is bypassed.
- Admin changes 3 words → Save still disabled (3 ≤ 5) + 422 if bypassed.
- Admin changes 6 words → Save enabled + 200, RLHF row written to `admin_annotations_log`.
- Admin changes 1 word + ticks "minor edit" → Save enabled + 200, **no** RLHF row written. Column is updated for the user.
- No FE deploy + old admin clicks Save → legacy behavior (no gate, RLHF row written). Migration window safe.

---

## Out of scope

- The 5 director-script questions, if FE picks "only prose" for Q1. Easy to add later via the same helper.
- Backfilling a "trivial edit" flag onto historical `admin_annotations_log` rows. The gate prevents future garbage; existing data is what it is. Out-of-scope cleanup if anyone cares.
- Char-level diff display in the UI (showing WHICH words changed). Pure UX nicety; the threshold check is binary.

Reply with the four answers and I'll ship in one commit.
