# The check-in learning contract

**Founder-agreed, 2026-08-02.** Every PR that touches the day card argues with
this document, not around it.

The morning card is a stack of four decisions. They do **not** all learn the
same way, and the split is the contract:

| Layer | The founder's correction | What the system does with it |
|---|---|---|
| **Bet order** | — none exists — | **Immutable** (L-2a). No UI offers the edit; nothing to learn. |
| **Priority within a bet** (which goal takes the one-thing slot) | Swapping the one thing | **Gated, never learned.** Swaps are recorded but the ranking model never sees them. The same goal displaced **3 mornings running** becomes a Sunday review proposal — retire / re-date / keep — decided consciously. Avoidance cannot teach the machine. |
| **Extraction** (which concrete step is drawn from the goal) | Replacing the step, same goal | **Learned silently.** (goal → drafted → final) pairs ride the next drafts as worked examples of how the founder decomposes. |
| **Formulation** (phrasing, size, language) | Rewording the draft | **Learned silently.** Same pairs, same window. |
| **Habits** | Editing the list | Data, not learning. |

## Memory mechanics

- Rolling window of ~20 (drafted → accepted) pairs; older material ages out
  naturally.
- **An unedited accept enters as a positive anchor** ("this was right") —
  silence teaches, and anchors keep corrections from overcorrecting.
  Corrections are weighted first.
- Per user, owner-scoped rows; they ride the export and die with the hard
  delete.

## Fences

- **Internal only.** No surfaced "the model learned…", no accuracy read-back,
  nothing score-shaped (AC-9 / N4).
- **The two data streams never cross.** The swap/displacement counter feeds
  only the review proposal; the (drafted → accepted) pairs feed only the
  drafting prompt. Code that reaches across is a contract breach.
- **Drafts propose, never commit** (N5): a drafted action counts for nothing
  until the founder engages with the card, and the deterministic
  goal-title card is the fallback for every drafting failure.
- Any new sentence a user reads ships with founder sign-off (LIVE LOOP).

## Storage

`life_days.draft_meta` (nullable jsonb, `add_life_days_draft_meta.sql`):

```json
{
  "one_thing": {"goal_id": "…", "goal": "…", "drafted": "…", "accepted": "…"},
  "focus": [{"goal_id": "…", "goal": "…", "drafted": "…"}],
  "displaced_goal_id": "…"
}
```

`drafted`, `accepted` and `displaced_goal_id` never reach the wire;
`serialize_day` lifts only the goal name and id.
