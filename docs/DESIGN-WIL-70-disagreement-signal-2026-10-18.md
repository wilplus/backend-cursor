# WIL-70 · Speaker/coach disagreement as a learning signal (design note, 2026-10-18)

No code in this note. It says what to build, where, and what stays as it is.

## 1. The two answers, and when they disagree

| Side | Where it is read | Which row |
|---|---|---|
| **Speaker** | `take_feedback_self_report` (family `confident_voice`) via `db.list_confident_voice_self_reports(arc_id)`; else a `confidence_labels` row with `self_report = true` | The latest answer, revisions included (`db._latest_self_reports`, 0440) |
| **Coach** (or any lone counted human) | `confidence_labels`, through `label_quorum.resolve()` | The counted `responses` |

- **Agree:** both answers are perceptual (`yes`, `in_between`, `no`) and the same.
- **Disagree:** both are perceptual and different. `yes` vs `in_between` counts.
- **No signal:** either side is `not_sure`, `audio_unclear` or missing.

A person's `in_between` is a real answer (label_quorum, rule 4). So this rule
counts it, which `machine_disagrees` does not do for the machine's own
ambiguous read.

**It is never stored as a category.** There is no new column, status, enum
value, table or view row called "disagreement". It is worked out on read
from the two answers, every time. If the speaker changes their answer, the
signal changes with it, the same way the Voice Album mirrors answers.

## 2. The ranking rule

The ticket calls it `ranking_priority`; in the code it is
`routing_priority()` in `services/label_quorum.py`. Keep the name.

| Ledger status | Today | After WIL-70 |
|---|---|---|
| `singleton`, **at least one** disagreement: machine vs the lone human (`machine_disagrees`) **or** speaker vs the lone human (new) | 100 if the machine disagrees, else 40 | **100** |
| `singleton`, everyone who answered agrees, or nobody else has a definite opinion | 40 | **40** |
| `needs_third` | 80 | 80, unchanged |
| `audio_retry` | 60 | 60, unchanged |
| `unrated` | 20 | 20, unchanged (with no coach answer there is nothing to disagree with) |
| `quorum`, `unresolved`, `audio_quarantined` | 0 | 0, unchanged. **A speaker's disagreement never reopens a closed clip.** |

- Disagreements don't stack. One is enough, and two still give 100.
- Why 100: a lone coach answer that the speaker contradicts is either the
  coach's miss or the speaker's miss. One more independent human settles
  which. This is the same reason rule 3 gives for the machine.
- **Rules 1 and 2 stay structural.** The speaker's answer goes only into
  `routing_priority`, never into `resolve()`. `resolve()` still has no
  machine parameter and no owner parameter, `machine_votes` stays 0, and a
  self-report still never counts toward quorum, gold or evaluation.

## 3. The recording mix in each judgement round

**Round one is the speaker's own voice: the walk's own judgements.** The
current Take's moments are served as they are today. Up to **2** earlier
clips from the same project are mixed in with them:

- **1 star recording:** the speaker's latest answer and the coach's latest
  professional answer (`professional_confidence.latest_professional_value`)
  are both `yes`.
- **1 disagreement recording:** the speaker and the coach disagree, as
  defined in section 1.
- How to pick each one: start with the newest Take, and skip any clip the
  speaker has already answered since their previous Take. If one kind has
  no clip, leave its place empty and don't fill it with the other kind.
- Shuffle them in among the current moments. The screen is the existing
  judgement screen. It never says why a clip is there, never says that
  anyone agreed or disagreed, and never shows the coach's answer (Never 1,
  AC-9).
- The answer is a judgement revision through
  `revise_take_feedback_response_v1` (0440). The latest answer wins and the
  first one stays.

**Round two is other voices: the walk's `others` step (`WalkOthers`).** It is
a mix of **3 clips** every walk (founder 2026-10-19):

- **Peer** (community) clips come first, **at most 2**. A clip in
  disagreement is served first. This is how a disagreement reaches a second
  blind human.
- **Licensed** corpus clips, picked by stratum, fill the places left, so
  there is **always at least 1**.
- If there aren't enough clips, serve fewer and never top up from anywhere
  else. With no peer clips, serve 3 licensed clips. With no licensed clips,
  serve at most 2 peers. With none at all, the walk goes on (lock 2026-10-12,
  section 2.6).

Neither round adds a screen, a step, a word or a number.

### A speaker's judgement of their own voice never trains a model (founder 2026-10-19)

The speaker may judge their own clips, but that answer **never trains the
confidence model**, or any other model. It is not training data, gold data,
evaluation data or a feature.

Its only uses are:
- ordering the routing queue (section 2);
- the Voice Album's user leg;
- rater calibration (label_quorum, rule 2).

This is already true structurally:
- The answer lives in `take_feedback_self_report` (L3,
  `provenance = 'user_self_report'`), which no training reader reads.
- In `confidence_labels` it is `self_report = true`, which `resolve()`
  excludes, so it can never make a clip `gold_eligible` or
  `eval_eligible`.
- The detector fit (`detector_candidates.training_rows`) reads only the
  coaches' blind answers.

WIL-70 adds no path from the speaker's answer into a model. Any future
trainer must read labels only through `label_quorum.resolve()`.

## 4. Code touchpoints

1. **`services/label_quorum.py`**
   - Add `owner_disagrees(resolution, owner_value)` next to
     `machine_disagrees`. It applies the perceptual-vs-perceptual rule from
     section 1 to `resolution["responses"]`.
   - `routing_priority(resolution, machine_value=None, owner_value=None)`:
     the `SINGLETON` branch returns `P_SINGLETON_DISAGREES` when
     `machine_disagrees(...) or owner_disagrees(...)`.
   - In the rule 2 docstring, add one sentence: the owner's answer may order
     the queue and never counts.
   - `resolve()` and the `snippet_label_quorum` view stay as they are. The
     view gives status, not priority, so **there is no migration.**
2. **`routes/v2/coach.py` `_confidence_queue_row`** (around line 2214)
   - Pass `owner_value` to `routing_priority`.
   - Read the speaker's answers once per batch with
     `list_confident_voice_self_reports(arc_id)`, keyed by `snippet_id`.
     Don't read them once per row (#1122).
   - `_queue_priority` is already removed before the row is sent (line 2511),
     so the coach never sees the speaker's answer. Blind coach holds.
3. **`services/communities.py` `order_community_clips`**
   - Change the sort key from `(rank, index)` to `(rank, -priority, index)`, where
     `priority` = `routing_priority(resolve(rows_for), machine_value,
     owner_value)`.
   - `owner_value` is the clip owner's latest answer
     (`list_confident_voice_self_reports` on the clip's project). Read it
     once per project, not once per clip.
4. **`services/lend_your_ear.py` `other_voices`**
   - Add `PEERS_MAX = 2` next to `OTHER_VOICES_MAX = 3`.
   - Call `community_clips(..., limit=min(limit, PEERS_MAX))`. Training
     clips fill `limit - len(clips)` as they do now. Peers stay first in the
     list.
   - Update the docstring and the Q-B11 A comment to "at most 2 peers, at
     least 1 training clip".
5. **Round one picker:** add `own_replays(database, owner_id, arc_id)` in
   `services/lend_your_ear.py`. It returns at most 1 star and 1
   disagreement, as in section 3. The route that serves the own judgements
   adds them to the current Take's moments. Audio only.
6. **Tests**
   - Add rows to `tests/test_label_quorum.py`: singleton coach `yes` +
     speaker `no` → 100; + speaker `yes` → 40; + speaker `not_sure` → 40;
     quorum + speaker disagrees → 0.
   - One contract check that `own_replays` never returns two clips of the
     same kind.
   - One contract check on `other_voices`: with 5 peer clips and 5 training
     clips, it returns 2 peers then 1 training clip.
   - No new test file.
