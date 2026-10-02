# The coach's blind check of the detector — privacy line, balancing test, retention row (DRAFT)

    record:              coach-blind-check-basis-2026-10-02
    author:              Artur Willoński, founder and controller; not reviewed by outside counsel
    rests on:            14-founder-determinations-2026-10-02/q1.md (C) and q2.md (C)
    gate it serves:      6a · ERROR_PRESENCE_AUDIT_ENABLED (off until the version below is published and re-accepted)
    status:              DRAFT for the founder's review; user-facing lines below need his sign-off before they ship (LIVE LOOP)

**What the gate does, in one paragraph, so the lines below describe it and
nothing else.** A coach hears a short clip of a recording and answers one
question about one speaking pattern ("Do you hear rushing here?"), Yes, No or
Can't tell, without seeing whether the detector fired, without the speaker's
name, words or any read about them (`services/error_presence_audit.py`;
contract 35g-9). The clip is chosen by the machine, fired and not fired alike,
at most twenty blind answers per coach per week and at most three clips per
speaker per sampling. The answer grades the detector; it is never shown to the
speaker and never becomes feedback. Practice attempts are checked the same
way. Nothing is trained on it (gate 6d is separate).

**Why Privacy 3.2 cannot carry it as written.** Section 5 "Human coaches"
promises that a coach listens "in order to review the feedback you were
given, and, if you turned practice on, to prepare practice for you". A clip
heard purely to check the detector is neither, so the promise must change
before the first blind check (Q1, "change the promise first"). The Terms say
the same in §1 and §11 and change with it.

## 1. The lines — draft copy for Privacy 3.3 and Terms 3.3

Section numbers are Privacy 3.2's and Terms 3.2's (`legal/phase1-2026.1/copy/privacy-3.2.txt`,
`legal/phase1-2026.1/copy/terms-3.2.txt`). Everything not quoted here stays as it is.

### Privacy §4 — a new purpose under legitimate interest

After the "To keep the service secure and working" paragraph:

> To check that our automated listening is right: from time to time a
> WillpowerLab coach — a person — hears a short clip of a recording and answers
> one question about one speaking pattern, for example whether the words sound
> rushed, without being told what our software found. The answer is used only
> to check and correct the software that chooses your feedback. The coach does
> not see your name, your words or anything about you, and the answer is never
> shown to you or used as feedback.
> Legal basis: our legitimate interest in keeping the tool accurate (Article
> 6(1)(f) GDPR). You can turn this off at any time by turning off Personalised
> practice in your settings: from then on no clip of yours is chosen for a
> check. Turning it off costs you nothing else.

### Privacy §5 — "Human coaches", one sentence added

After "Coaches are bound to confidentiality and see only what a review
requires.":

> A coach may also hear a short clip of a recording to check our automated
> listening, as section 4 describes, unless you have turned Personalised
> practice off.

### Privacy §7 — "How long we keep it", one sentence added

After "Voice measurements are deleted together with the recording they came
from and are never kept after it.":

> A coach's answer in a blind check is deleted together with the recording it
> was about, and never kept after it.

### Terms §11 — "Human coaches", one paragraph added

After the paragraph ending "A coach does not see the voice measurements
described in section 3 of the Privacy Policy.":

> A coach may also hear a short clip of a recording in order to check our
> automated listening, without being told what it found and without seeing
> who you are. That check is described in section 4 of the Privacy Policy, and
> you can turn it off there at any time.

Terms §1 needs no change: "a WillpowerLab coach — a person — may listen to your
recordings" already covers hearing, and the purpose is stated in §11.

## 2. The legitimate-interest assessment (the balancing test)

**Purpose.** To know whether the speaking-pattern detectors are right, in both
directions: how often they miss a pattern a coach hears (the caught rate the
shadow comparison already measures from coach-named moments,
`services/verbal_cue_validation.py`) and how often they fire on a clip where
no coach hears it (the false-alarm rate, which nothing else can measure
because coaches record only what is present). A detector that cries wolf
sends speakers the wrong exercise; one that misses sends none.

**Necessity.** The check needs a human ear on clips the detector fired on AND
on clips it did not, sampled by the machine so the coach's choice of what to
hear cannot bias the measure. Asking each speaker first (Q1 option B) would
leave too few clips to measure and would tell the coach which speakers said
yes; the measure needs the pool as it is. A coach already hears recordings
under §4(1)(b); the new element is the purpose, not the hearing.

**Balancing, the speaker's side.**
- Expectation: a person who accepted hybrid coaching expects a coach to hear
  their recordings; hearing one clip to check the tool is close to that
  expectation, and the new line makes it explicit.
- Intrusion: one clip, one question, no name, no transcript, no read, no
  consequence for the speaker; the answer never reaches them and never
  changes their feedback.
- Special-category risk: a clip may happen to reveal something sensitive, as
  §4 already says of recordings; the check adds no inference and no new
  reader beyond the coach who may already review the recording.
- Scale: at most twenty answers per coach per week, three clips per speaker
  per sampling, one clip in ten heard by two coaches for agreement.

**Balancing, the controller's side.** The interest is real and specific
(accuracy of the thing that chooses exercises), the processing is minimal
(one clip, one question), and the safeguards below are in code.

**Safeguards.**
1. Blind: the coach is never shown whether the detector fired, and the
   exposure record makes a later non-blind rating by that coach on that clip
   count for nothing (contract 35g-11).
2. Minimal: no name, no words, no read; the clip only.
3. Capped: twenty per coach per week shared with the blind block pick; three
   per speaker per sampling.
4. Opt-out, easy: the speaker's existing Personalised practice choice, read
   at sampling time; off takes their clips out of the pool from the next
   sampling (`services/error_presence_audit.py`, `_still_permitted`).
5. Retention: the answer dies with the recording (§3 below).
6. No training: gate 6d is separate and off.

**Conclusion.** Legitimate interest holds for the blind check with the opt-out
and the new wording in place; it does not hold for the current wording, which
is why the gate waits for Privacy 3.3 and Terms 3.3 to be published and
re-accepted (`16-share-switch-wording-DRAFT.md` carries the share lines into
the same version so there is one re-acceptance, not two).

## 3. The retention row

Addition to the schedule (`06-retention-schedule-v1.0-DRAFT.md` §1, as extended
by `11-retention-schedule-v1.1-training-DRAFT.md`):

| Category | Period | Trigger |
|---|---|---|
| A coach's blind-check answer (Yes, No, Can't tell) about one clip and one speaking pattern | with the recording — deleted with the source recording's Take, never after it | deletion of the recording, or of the coach's account |

Addition to the rules to seed (§2):

| `rule_code` | `evidence_category` | `retention_until_rule` | What it covers |
|---|---|---|---|
| `coach-audit-answers-v1` | `coach_audit_answers` | `deleted_with_source_recording` | `error_presence_audit` rows; keyed to the Take and to the coach in `services/data_purge_registry.py` |

No number is invented: the rule is the one §1 of the signed schedule already
states, "Voice measurements are never outlived by their source."

## 4. What has to be true before `ERROR_PRESENCE_AUDIT_ENABLED` flips

1. The founder signs the lines in §1 (this document's status moves to SIGNED).
2. Privacy 3.3 and Terms 3.3 are written as copy/privacy-3.3.txt and
   copy/terms-3.3.txt (exact bytes), registered as the next `phase1-…`
   policy version, and re-accepted through the six screens.
3. The retention row is seeded.
4. The flip is one reviewed PR, after the founder's review.
