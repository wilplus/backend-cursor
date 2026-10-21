# Concept — per-user exercise effectiveness (Linear WIL-29)

> **Label: History** · kept as written, because the rules still cite it. Every doc and its label: [`README.md`](../README.md) (N106).

> **2026-10-21 (N102):** what the app learns from and how a label settles are now one page, [`docs/LEARNING-AND-QUORUM.md`](LEARNING-AND-QUORUM.md). This concept stays as it was written. Whether what it proposes is in force is §3 A15 there.

Date: 2026-10-18. Status: **CONCEPT FOR THE FOUNDER'S DECISION. Nothing here
is built, and nothing here authorises a migration, a screen or a number on
a speaker's screen.** The founder's note on the issue: "probably in the user
profile, to have it available from the CEO panel; needs to be conceptualised
and its necessity assessed."

## 0. The one question first

*Does this make the transcript, the Ideal Text or the feedback better, or does
a task in progress need it?*

Not directly. It is a founder-side lens on data the loop already produces.
One part of it (§3, M3 "held in the next Take") would improve the feedback
later, through the exercise ranker, and nothing measures it today. The rest
is a convenience for the founder's admin work. The verdict is in §6.

## 1. What already exists

The product already measures whether an exercise helped. All of it is about
the **system** or about one **practice**; none of it is read per person.

| Measure | Where | Unit | What it says |
|---|---|---|---|
| Live practice check (`practice-check-v4`) | `services/practice_check.py` | one try | `praise` / `again` / `moved_on`: the try is measurably better than the original clip (targeted problem cleared, a delivery cue moved by `CUE_GAIN_MIN` within-speaker z, or the machine leg reads higher) |
| Practice sounds more confident (`exercise-more-confident-v1`) | `practice_more_confident_outcomes` | one practice | `helped` / `not_helped` / `pending`: the machine leg **and** the coach's blind "more confident?" answer, both yes |
| Exercise adequacy label (`exercise-adequacy-label-v2`) | `services/exercise_learning_readiness.py`, `exercise_adequacy_labels` | first valid attempt of a first exposure | the targeted problem stopped firing on the endpoint attempt; feeds the jar (300 counted / 30 per exercise) and the fair test |
| Delayed blind human measure (`exercise-human-delayed-v1`) | `delayed_measure_pairs` | one pair, seven days later | peers and coaches, blind, hear before and after; off until the peer lane returns |
| Willfidence (`willfidence-v1`) | `services/willfidence.py`, dark | one moment; "Take or person" is defined as the average over random moments | S·W; machine-only read built dark (B1.3), never on a screen |
| Person page practice line | `services/admin_person.py::practice` | one person | `offered` and `done` counts (founder 2026-10-18) |

Fences that bind anything per person:

- **AC-9**: numbers are about the machine, never shown to a speaker; the
  founder's own pages are the exception. A coach never sees a per-person
  read either (blind coach).
- **L3**: every input keeps its own provenance; a derived read is never
  written back as a speaker's answer, a coach's answer or a label.
- **Never #1**: no score, number or verdict reaches the speaker. Nothing in
  this concept touches a speaker screen.
- **Never #4**: new words on an admin screen still need the founder's OK.

## 2. What "effective for this person" means

Three different questions hide in the phrase. They need different data and
have different value.

1. **Did it help this moment right away?** Within-speaker, the same clip,
   minutes later. Already answered per practice (row 1 and 2 above). Only
   needs reading per person.
2. **Did it hold into the next Take?** The targeted problem on that passage:
   did it come back when the speaker recorded the whole talk again? **Nobody
   measures this today**, for anyone. It is the only honest meaning of
   "effective" for a speaker, and it is also the measure the system-level
   ranker is missing.
3. **Which exercises work for this person rather than for people in
   general?** Personalisation. Needs tens of practices per person per
   exercise. With today's volumes that is years away, and the fair test
   already does the population version.

## 3. Metrics, per person

All derived; nothing new is asked of the speaker. Each one is a **count in
words**, never a rate, because n per person will be one to three for a long
time. Below five practices the page says "too few to read" and shows the
raw facts only.

| | Metric | Source | Values |
|---|---|---|---|
| M1 | **Sounded better right away** | the live check's read on the first valid attempt (`exercise-adequacy-label-v2`'s endpoint rule, scoped to the person) | yes / not yet / no valid try |
| M2 | **Coach agreed it sounded more confident** | `practice_more_confident_outcomes.outcome` | helped / not helped / pending |
| M3 | **Held in the next Take** (new) | the targeted problem's firing on the lineage-matched paragraph of the speaker's next Take of the same project, read from the V3 frame | held / came back / unknown (no next Take yet, paragraph rewritten away, rules changed between Takes) |
| M4 | **Went through with it** | `confident_voice_practice.status`, attempt count, skips | offered, opened, tried once, tried three times, completed, skipped |
| M5 | **Willfidence over Takes** | `willfidence-v1`'s "person" average, once B1.3 leaves the dark | not redefined here; listed so this concept does not invent a second progress read |

Grouping: by exercise, and inside it by targeted problem (the match trace
names both). Never by score. The column that would tempt a rate ("2 of 3")
stays two separate counts.

M3's rule, so it can be frozen before any data is read:

- one practice → at most one M3 result, decided when the speaker's **next**
  Take of the same project finishes processing; a later Take never revises it;
- the passage is followed through the versioning lineage (`VERSIONING_SPEC`);
  a paragraph that was rewritten, split or deleted is `unknown`, never `held`;
- "fires" is the same detector and the same rule version as the practice's
  match trace; a rule change in between is `unknown` (same stance as the
  jar's `rules_changed` exclusion);
- rule name `exercise-held-next-take-v1`; `serves_user` and `is_label`
  CHECK-forced false, like `practice_more_confident_outcomes`.

## 4. Data collection

**v1 collects nothing and migrates nothing.** M1, M2 and M4 are a read over
`confident_voice_practice`, `confident_voice_practice_attempt`,
`confident_voice_exercise_exposures`, `confident_voice_exercise_match_traces`
and `practice_more_confident_outcomes`, joined in one service
(`services/admin_person.py`, next to today's `practice()`), scoped to one
`owner_user_id`. Admin traffic is tiny; computing on read is fine and avoids
a migration and its outside review.

**M3 needs one derived table** (`speaker_exercise_effects`, one row per
practice, written when the next Take's frame lands). Additive, idempotent,
`IF NOT EXISTS`, no drop; listed in `services/data_purge_registry.py` so an
account or project deletion takes it too; outside review before merging as
every migration. It is also the row the **system** measure reads
("did any exercise hold into the next Take?"), which is why it is worth a
table and the per-person list is not.

Consent: all inputs already exist under the processing authorisation;
nothing new is recorded about a person. Deletion: v1 has no new rows;
M3's table goes in the purge registry.

## 5. UI concept

**Where:** `/admin/users/<id>`, the person page (founder 2026-10-13,
step 1), growing its existing practice line into a section. **From the CEO
panel:** the admin menu already links CEO → People → Users; no new CEO
surface. If the founder wants it one tap closer, the CEO Overview gets a
short "People practising" list (name, last practice, link), nothing more.

Draft (words need the founder's OK before they appear):

```
Practice                                        offered 6 · done 4

Pausing before the point                      · 3 practices
  sounded better right away      2    not yet 1
  coach agreed                   1    pending 2
  held in the next Take          1    came back 0   unknown 2
  tries: once 1 · three times 2 · skipped 0

Landing the last word                         · 1 practice
  too few to read — tried once, not yet; no next Take
```

Rules on the screen: counts and words only; no bars, no percentages, no
colour that ranks; "too few to read" below five practices for an exercise;
the speaker's own answers (`final_user_answer`) and the coach's are shown
as their own lines, never merged into a verdict (L3). Founder role only,
as `/admin/pace` is; a coach never reaches the page.

## 6. Is it necessary?

**For the loop: no.** It does not change a transcript, an Ideal Text or a
feedback card. CLAUDE.md's filter says: say so and ask. This document is the
asking.

**For the founder's work: partly.** Two real needs sit behind the issue:

- *"Is it working for this person?"* before a lesson, a booking or a
  conversation. Today the person page shows offered and done; everything
  else is per exercise across everyone. A per-person **list of facts** (v1)
  answers this in about two days of work, with no migration.
- *"Does any of it hold?"* Nobody can answer this for anyone today. M3 is the
  gap, and it is a **system** measure that happens to be readable per
  person. It is the one piece here that later makes the feedback better,
  through the ranker.

**What is not worth building now:** per-person effectiveness *rates* or a
per-person exercise ranking (§2, question 3). With one to three practices per
person per exercise the number would be noise presented as insight, and the
fair test already ranks at population level, blind to the person.

**Recommendation.**

1. **v1, if the founder wants the admin convenience:** the per-person facts
   list on the person page (M1, M2, M4). Compute on read, no migration, no
   speaker or coach exposure. Around two days.
2. **M3 as a system measure, on its own merits:** define
   `exercise-held-next-take-v1`, one table, a row on the pace panel beside
   the jar, and the per-person line falls out of it. Three to five days;
   needs the paragraph lineage read and an outside review of the migration.
3. **Not now:** per-person ranking, willfidence per person on any screen,
   anything a speaker could see.

## 7. Questions for the founder

1. Is v1 wanted at all, or is "offered / done" enough until M3 exists?
2. M3: is "the next Take of the same project" the right horizon, or any Take
   within N days?
3. Does a rewritten paragraph count as `unknown` (proposed) or as its own
   outcome ("the words changed instead")?
4. Founder only, or admins too? Today's person page is admin; the pace
   panel is founder only.
