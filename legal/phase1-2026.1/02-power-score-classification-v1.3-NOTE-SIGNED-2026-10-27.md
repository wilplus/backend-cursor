# Document 02, version 1.3 — note for the Willfidence reading a coach and the founder see — SIGNED by the founder 2026-10-27

**SIGNED by the founder, 27 October 2026** (the sign-off page for Terms 3.7 and
Privacy 3.8, question 1, answer A: "Keep it, and say so … I add a one-page
note to document 02 (v1.3) that records the change, for counsel's next look";
in chat: "I sign as drafted, question 1 A, question 2 A"; decisions log N208).
Counsel had not seen this change when the founder signed; since then
**counsel has seen it and accepts it** (the founder, in chat, 27 October
2026: "they ve seen ti and they accept it!!!"; N208).

    artifact_kind:       power_score_classification
    version:             1.3 — supersedes 1.2 (signed 2026-10-08) by version bump, never in place (04 §5)
    form:                this note lists the changes; on signature v1.3 is rendered as v1.2's full text
                         with these changes applied, then signed and hashed
    approving_authority: Artur Willoński (founder and controller) — controller's own determination; counsel has since seen it and accepts it
    approved_at:         2026-10-27 (decisions log N208; counsel's acceptance relayed by the founder the same day)
    object_key:          phase1-2026.1/legal/power-score-classification-v1.3.pdf
    sha256:              [[computed from the signed PDF at registration time]]
    metadata:            unchanged from 1.2 (biometric_identification false, sex_gender_inference false,
                         emotion_intention_inference false, pipeline_version voice-confidence-universal-v3)

## Why a v1.3

v1.2 §3 items 3 and 4 say no number from the composite is shown to anyone,
and never to the coach; §7.2 point 5 leans on that ("The output never reaches
a user, a coach, or any third party"); §8 makes it a deployment condition
("the composite stays off the coach packet"). Since 21 October two founder
decisions show a reading derived from the composite:

- **N104:** after a coach's own blind answer about a moment, the coach panel's
  "What happened" shows a last line, **Willfidence**, the moment's reading as
  a whole percent (`services/coach_moment_read.py:23`). The coach never sees
  it before answering (CLAUDE.md, Never 2).
- **N105:** the founder's person page shows each Take's Willfidence, the mean
  of its moments' readings, in its Takes table and that table's CSV
  (`services/admin_takes.py:57`).

The reading is S × W: S is the composite of §3, stretched to a 0 to 1 scale,
against the speaker's own baseline; W is read from the words (fillers,
hedging, how the passage fits its slide). No speaker ever sees it (CLAUDE.md,
Never 1; AC-9). Privacy 3.8 §3 and Terms 3.7 §10 and §11 now say all of this
to speakers (29-…).

## The changes

1. **§3 item 3, "Never surfaced"**, becomes:

   > 3. **Never surfaced to the speaker.** AC-9. The score, the band and the
   > cue z-scores never reach a user payload, and this is fence-tested in
   > `tests/test_voice_confidence.py`. One derived reading, Willfidence (the
   > composite stretched, times a reading of the words), is shown as a whole
   > percent to a coach about a moment only after that coach's own blind
   > answer (N104), and to the founder per Take on the person's admin page and
   > its CSV (N105). No number, ratio, badge or classifier output is shown to
   > the speaker or to anyone outside WillpowerLab.

2. **§3 item 4, "Never shown to the coach"**, becomes:

   > 4. **Never shown to the coach before their answer.** The composite itself
   > is "NOT learned and NOT on the coach packet". The derived reading appears
   > only behind the blind gate, after the coach has answered about that
   > moment, so it cannot anchor that answer.

3. **§7.2, the case for `false`, point 5**, becomes:

   > 5. The output never reaches the speaker or any third party. A coach sees
   > the derived reading of a moment only after answering about it, and the
   > founder sees it per Take; both use it to check the software. It selects
   > which of the user's own sentences to replay to them.

4. **§8, the deployment conditions**: "the coach surface stays
   user-initiated and asynchronous, and the composite stays off the coach
   packet;" becomes "the coach surface stays user-initiated and asynchronous,
   the composite stays off the coach packet, and the derived reading reaches a
   coach only after their own blind answer;".

## Why the determination does not change

§9 stands: `biometric_identification: false`, `sex_gender_inference: false`,
`emotion_intention_inference: false`. The reading characterises how assured a
delivery sounds, as §7.2 argues, whoever sees it. Showing it to the coach after
answering and to the controller adds no inference about the person, no
comparison against other people, and no consequence for the speaker: no
eligibility, price, access or report follows from it (§7.2 point 6). Point 5
was one support of the case among six; it now holds in its narrower form.

## For counsel's next look

Does showing the derived reading to a coach after their blind answer, and to
the controller per Take, change the §7 analysis or the §8 profiling question
(Article 6(3), final subparagraph)? The founder's position is that it does
not, for the reasons above.

**Counsel's answer** (relayed by the founder, 27 October 2026: "they ve seen ti and they accept it!!!"): counsel
has seen this note and accepts it.
