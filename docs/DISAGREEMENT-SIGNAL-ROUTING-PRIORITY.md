# Disagreement signal → `routing_priority` (WIL-32)

Status: **design only, not built.** Written 2026-10-18 for Linear WIL-32
("Define disagreement-signal integration"). Nothing in this file changes code
or a screen. The founder's answers to the open questions at the end decide
what gets built.

The issue says `ranking_priority`. The function in
`services/label_quorum.py` is `routing_priority`, and this file uses that name.

## 1. What exists today

`routing_priority(resolution, machine_value)` decides **order only**. It
cannot change a label, a count or a status (rule 1: the machine is a router,
not a rater). It reads two things:

| status (from `resolve`) | priority |
|---|---|
| `singleton`, and the lone human answer contradicts the machine (`machine_disagrees`) | 100 |
| `needs_third` (two humans, no quorum) | 80 |
| `audio_retry` | 60 |
| `singleton`, machine agrees or has no opinion | 40 |
| `unrated` | 20 |
| `quorum`, `unresolved`, `audio_quarantined` | 0 |

It has one consumer: the coach confidence queue
(`routes/v2/coach.py`, `_confidence_queue_row` and the sort after it). That
queue puts contract-34 `re_review` rows first, then sorts by
`-_queue_priority`, then **strips the priority before the response** so the
order logic is never an answer hint on the blind screen. The SQL view
`snippet_label_quorum` has no priority column. Lend your ear and the coach
moments queue do not read it.

The **speaker's own answer** on a clip is already stored, but **outside the
ledger**:

- `take_feedback_self_report` (`feedback_family = 'confident_voice'`), read per
  clip by `db.list_take_feedback_self_reports_by_snippet`. The latest row is
  the current answer (`services/coach_moment_read.py::_speaker_answer`).
- An owner row inside `confidence_labels` is marked `self_report` (or lane
  `game_owner`). `resolve()` excludes it from quorum and counts it in
  `n_self_report` only (rule 2).

The one built "they disagree" path is **speaker vs machine** (QG12a A, migration
0444): `services/coach_listen_again.py` gives the moment back to the coach who
already judged it. It writes a revision and never touches the ledger or
`routing_priority`. **Speaker vs coach is not used for ordering anywhere.**
Contract 34's speaker-vs-coach outcomes (User Yes / Coach No → re-review; User
No / Coach Yes → a later Album exercise, not built: QB19 B, A151b, A169c) are
product follow-ups, not routing.

## 2. Rules any design must keep

1. **The speaker never votes.** Their answer is a router input, exactly like
   the machine's proposal. It may change *which clip a human hears next*. It
   may never change `status`, `value`, `settled`, `gold_eligible`, a count, or
   break a tie. `resolve()` keeps its signature: no owner parameter.
2. **Blind coach and blind peer** (contract 34, K2, P28 B). The owner's
   answer, the machine's read and the reason a clip moved up are never
   serialized to a rater. The priority stays stripped before the response, and
   no badge, label or word appears for it. (No new words on screen.)
3. **Only a definite contradiction counts.** Same rule as
   `machine_disagrees`: `yes` vs `no` only. `in_between`, `not_sure`,
   `audio_unclear` or no answer is not a disagreement.
4. **Only a real owner has an answer.** The owner is the person whose voice is
   on the clip and who judged it on their own Take. An import has no owner
   answer (see §4.3).
5. **No speaker-facing effect.** Nothing here reaches the speaker (AC-9, rule
   1 of CLAUDE.md). It only changes how soon a clip gets its next human.

## 3. Proposed rule

Add one router input, `owner_value` (the speaker's current answer on that
clip, or `None`), next to `machine_value`. Define two helpers in the style of
`machine_disagrees`:

- `owner_disagrees_with_raters(resolution, owner_value)`: the owner gave a
  definite answer, and every definite counted human answer is the other one.
- `owner_disagrees_with_machine(owner_value, machine_value)`: both definite,
  and different.

New table (new rows marked ★):

| status | condition | priority |
|---|---|---|
| `singleton` | lone human contradicts the machine | **100** (unchanged) |
| `singleton` ★ | lone human contradicts the **owner**, machine does not | **90** |
| `needs_third` | — | **80** (unchanged; the owner does not break the tie) |
| `audio_retry` | — | 60 (unchanged) |
| `singleton` | otherwise | 40 (unchanged) |
| `unrated` ★ | owner contradicts the machine | **30** |
| `unrated` | otherwise | 20 (unchanged) |
| `quorum`, `unresolved`, `audio_quarantined` | any owner answer | **0** (unchanged) |

Why this order:

- **100 stays on top.** A human against the machine is the model's
  active-learning signal (rule 3). When the coach says No and both the
  machine and the speaker say Yes, the clip is already at 100; the owner adds
  nothing.
- **90 for coach vs speaker.** A single coach against the speaker is either a
  coach miss or a speaker whose self-perception is off. One more independent
  human answers which. It also unblocks the speaker: contract 34's follow-ups
  (the re-review's "calm explanation after confirmed No", the future Album
  disagreement exercise) are only safe on a label that stands. It ranks below
  100 because the owner is not independent (Phase 2: the speaker judges
  *after* the machine's read chose their feedback, so their answer is anchored
  to it).
- **`needs_third` is not raised.** Two humans already disagree. A speaker
  siding with one of them is exactly the vote rule 2 forbids, even as a nudge
  to "settle faster on the speaker's side".
- **30 for unrated owner-vs-machine.** No human has heard the clip yet. The
  speaker contradicting the machine against their own anchor makes it a better
  first listen than a random unrated clip. It stays below every clip that
  already has a human answer, because those are closer to settling.
- **Settled stays settled.** An owner disagreeing with a quorum does not reopen
  it. Reopening on the owner's word would be a veto, which is a vote. The case
  is kept for calibration (`n_self_report`), not routing.

## 4. The four kinds of recording

### 4.1 Star (the machine's confident read)

"Star" here is the **confident-moment star**: the machine read the clip as
confident (`machine_proposal` → `yes`), the speaker got praise, and Voice
Album counts it as the "machine's confident star" leg. A starred clip has
`machine_value = 'yes'`.

- Owner **No** on a starred clip: a definite contradiction made against the
  anchor. That is the strongest owner signal there is. Unrated → 30. One coach
  Yes → 90 (coach vs owner). One coach No → 100 (coach vs machine).
- Owner **Yes** on a starred clip: agrees with the machine, and is anchored to
  it. It adds nothing to routing. One coach No → 100 as today.
- **`star_verdicts` are not an input.** They are non-blind (the coach saw the
  machine's star), retired (contract 63), and must never feed the ledger.
  Delivery and suggestion stars are text prompts, not confidence reads, and
  are not inputs either.

### 4.2 Disagreement (speaker vs coach)

This is the 90 row. Rules for reading it:

- Use the speaker's **latest** `take_feedback_self_report` on that exact clip
  (`confident_voice` family). An answer on a different Take or practice
  attempt is a different recording and never transfers (contract 32).
- A coach **revision** (contract 34 re-review, listen-again) is still that
  coach's one answer in the ledger. It is never counted as a second human.
- The contract-34 `re_review` flag keeps sorting first and is independent of
  this rule. A re-review is the **same** coach looking again. The 90 row asks
  for a **different** human.
- QG12a's listen-again (speaker vs machine, same coach) stays as built. It
  does not raise priority by itself.

### 4.3 Licensed recordings

- **Licensed corpus clips (`corpus_clips`)** are not snippets. They have no
  quorum, no label and no Take (`services/communities.py`), and
  `routing_priority` never sees them. **No change.**
- **Training-corpus imports** (`session.source = 'training_import'`, N58) are
  snippets and do go through the ledger. The importing coach is **not** the
  owner (CO3 A: "A coach's blind judgement on a clip they imported counts like
  any other coach's"). The speaker on the clip is not a user and has no answer.
  So `owner_value` is always `None` for an import, and only the machine rows
  apply. The caller must not read the importer's self-reports as the owner's.

### 4.4 Peer recordings

- A peer answer (`game_peer`, written from a community clip under the
  quorum's access rule) is a full human vote (K6: coach and peer form one
  panel). So "lone human contradicts the owner" covers a lone **peer** exactly
  as it covers a lone coach. The 90 row is lane-blind.
- The owner's answer is never served to peers either. Lend your ear's
  payload stays audio only.
- **Lend your ear does not read `routing_priority` today** (community first,
  then corpus, random within strata). This design does not change that. If
  the founder wants the peer queue ordered by the ledger, that is a separate
  decision (open question 5).
- A peer's answer on their own shared clip never reaches a peer queue (the
  queue never serves a listener their own clip). If one exists, it is a
  self-report and is excluded as today.

## 5. Where it would be built (later)

Not built now. When it is:

- `services/label_quorum.py`: `P_SINGLETON_OWNER_DISAGREES = 90`,
  `P_UNRATED_OWNER_DISAGREES = 30`, the two helpers, and
  `routing_priority(resolution, machine_value=None, owner_value=None)`.
  The module docstring gains this as rule 3's owner half. `resolve()` is not
  touched.
- `routes/v2/coach.py::_confidence_queue_row`: pass the speaker's current
  answer. Read the take's self-reports **once per queue** (a batched reader),
  not one query per clip. Skip it when the Take is a `training_import`. Keep
  stripping `_queue_priority`.
- No migration. The SQL view has no priority column and needs none.
- Tests (founder's test rules): extend the existing `routing_priority` contract
  test with the ★ rows and with "the owner can never change `resolve()`'s
  output", plus one check that the coach queue response carries no owner
  answer or priority. No new test file.

## 6. Open questions for the founder

1. **Coach vs speaker at 90** (above two-human disagreement at 80), or below
   it? Proposal: 90.
2. **A speaker disagreeing with a settled label**: never reopen (proposal), or
   send it to a third human?
3. **In-between**: should speaker In-between vs coach Yes/No count as
   disagreement? Proposal: no, only Yes vs No, as for the machine.
4. **Unrated speaker-vs-machine at 30**: worth having, or leave unrated clips
   in plain order?
5. **Peer queue**: should Lend your ear's community clips also be ordered by
   `routing_priority`? Proposal: not now.
