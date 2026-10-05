# Questions for counsel — October 2026

    to:       our counsel
    from:     Artur Willoński, founder and controller, WillpowerLab (natural person, działalność nieewidencjonowana)
    date:     5 October 2026, to be sent this week
    subject:  WillpowerLab — eleven questions; the first is overdue
    record:   decisions log N48.4 (Q15 A, Q18 B, Q21 A, Q22 A, Q23 A), N50 (the Wave 3 sign-off), and counsel items still open (N15 item 3, M4 and others)

Dear Counsel,

Below are eleven questions, numbered, in the order we need the answers. The
first is overdue: a determination of ours is conditional on your confirmation,
and the condition has been engaged since 2 October. The other ten follow my
decisions of 5 October.

**How to read this.** Each question says what to read, what we did and why,
and what exactly we ask. Every reference names a file attached to this email
and its line numbers, counted from line 1 of the file. A signed document is
attached as its source text, which carries the same words as the signed PDF.
Where a question turns on a few lines of our code, they are quoted here, so
you need not open the code.

**What we need back.** For question 1, a dated letter, signed, that we can
hash and register: an email cannot be registered as a legal artifact, which is
why your answers of 23 September still stand in our records as
"confirmed by correspondence", with the signed letter "pending". For questions
2 to 11, an email answer is enough unless you say a question needs a letter.
Nothing here is published to users before you answer and I sign off the
words.

**Attached.**

- `02-power-score-classification-v1.1-DRAFT.md` (signed 2 October 2026 as a PDF)
- `03-article-50-assessment-v1.1-DRAFT.md` (signed 5 October 2026 as a PDF)
- `20-retention-schedule-v1.4-product-records-and-job-evidence-DRAFT.md` (signed 5 October 2026 as a PDF) and `19-retention-schedule-v1.3-financial-records-DRAFT.md` (signed 5 October 2026)
- `11-retention-schedule-v1.1-training-DRAFT.md`, `13-training-consent-wording-SIGNED-2026-10-01.md`, `15-coach-blind-check-privacy-line-and-balancing-test-SIGNED-2026-10-02.md`, `17-door-2-coach-word-surfaces-shut-2026-10-02.md`, `14-founder-determinations-2026-10-02/q1.md`
- `copy/privacy-3.3.txt` and `copy/terms-3.3.txt` (the Privacy Policy and Terms as published, version 3.3)
- `docs/PRODUCT-LEGAL-FLOW-PLF-1.1.md` (our product-legal flow) and `docs/SPEC-DECISIONS-LOG.md` (my decisions log)
- `scripts/phase1_policy_publish_unbundled.sql` (only the comment at lines 292–313, our record of your answers of 23 September)

---

## 1. Document 02: please confirm the determination, or tell us what fails

**Read.** `02-power-score-classification-v1.1-DRAFT.md`: the status paragraph
(lines 40–51); §3b, the speaking-error detectors, new in v1.1
(lines 166–196); §9, Determination (lines 445–518), above all the Q7 note
(lines 459–465), "The fact, stated by the founder on 2026-10-02"
(lines 467–477) and the box "The condition this determination is made under"
(lines 502–505). Our record of your answers of 23 September:
`scripts/phase1_policy_publish_unbundled.sql` lines 292–313.

**What we did.** I determined, as controller and not as a lawyer, that the
voice analysis is not biometric identification, does not infer sex or
gender, and does not infer emotion or intention; that it is not high-risk under
Annex III; and that it is not prohibited under Article 5. I made that
determination on one condition: "It must be confirmed by counsel before the
first third-party user records on the service." On 2 October 2026 I stated in
writing that one other person has recorded. The condition is therefore
engaged, and your confirmation is overdue.

On 23 September you told us by email that the voice-confidence component is
not an emotion recognition system under Article 3(39). We recorded that as
correspondence, not as a signed opinion. Version 1.1 adds three
speaking-error detectors (rushing, compressed words, compressed sentence
endings; §3b), and my answer (Q7) that they describe how a delivery sounds,
not how the speaker feels. You have not seen §3b.

For completeness: one switch that rests on this document, training a learned
detector on coaches' blind answers, was on from 2 to 3 October and trained
nothing, because the code that trains does not exist yet. It is off, and it stays off until you confirm
(`docs/SPEC-DECISIONS-LOG.md` N26 and N29).

**The question.** Do you confirm the §9 determination, for (a) the
voice-confidence composite and (b) the three detectors of §3b? Please answer
in a dated, signed letter. If you cannot confirm a line, please say which, and
what would change your answer. Until you answer, our own document says the
service should not be open to anyone but me (lines 514–518).

---

## 2. Article 50(2): a label on the Feedback sheets, and the plain-text clipboard

**Read.** `03-article-50-assessment-v1.1-DRAFT.md`: §6, "What the screens label
today" (lines 328–361); §3, the paragraph "Corrected in 1.1" (lines 138–145);
§3, "Decided item — the paths that cannot carry a mark" (lines 196–238); and
the correction to §4 (lines 261–269). Privacy 3.3 §3, "The sound of your voice"
(`copy/privacy-3.3.txt` lines 57–66).

**What we did.** The Ideal Text, the speaker's working document, shows the
caption "AI-generated text · Take N" and carries a machine-readable mark (the
IPTC term `trainedAlgorithmicMedia`) on the page that holds it. The Feedback
sheets open inside that page, under its mark, and carry no visible label of
their own. Nothing on a sheet is written by a language model today: it shows
the speaker's own words, a rewrite made by a fixed rule from those words, a
praise line a person wrote and signed (or the sheet's own fixed wording), a
coach's own words, and exercise videos made by people. Model-written suggestions exist in the code and are
switched off.

The Copy button puts two versions of the text on the clipboard: the formatted
one carries the mark; the plain-text one carries nothing (my decision of
22 September, because a visible line would land in every paste of
the speaker's own presentation). The PDF and Word downloads are marked.

**The questions.**

- (a) Do the Feedback sheets need a visible AI label of their own? Would your
  answer change if model-written rewrites were switched on later?
- (b) Is marking only the formatted clipboard version enough under Article
  50(2), or must the plain-text version carry a visible line?
- (c) A correction you should know of: version 1.0 said the AI notice
  describes the voice measurements. The live notice (3.1) does not; Privacy
  3.3 §3 does, and the acceptance screen shows it before any recording, beside
  the notice. If Article 50(3) applied, would that be enough?

---

## 3. Retention schedule v1.4: please review it

**Read.** `20-retention-schedule-v1.4-product-records-and-job-evidence-DRAFT.md`
in full, especially §1 (lines 44–62), Table B (lines 100–109), §5.1
(lines 134–152), §5.7 (lines 281–292) and §6 (lines 294–313).
`copy/privacy-3.3.txt`: §7 (lines 287–291 and lines 316–320) and §9
(lines 354–357 and lines 365–376). v1.3's two open points:
`19-retention-schedule-v1.3-financial-records-DRAFT.md` lines 43–49. What I
decided on §5 afterwards: `docs/SPEC-DECISIONS-LOG.md` N50, item 5
(lines 1658–1670).

**What we did.** On 5 October I decided one rule for every table our deletion
process could not yet resolve on its own. **Product records** (what the
service showed, the speaker's own answers, every version of a paragraph, any
other record of the speaker's own use) are deleted with the account or with
the project. **Job evidence** (records of how each recording was processed:
identifiers, times, states, technical error codes; never words or voice) is
kept for 12 months from the day of the recording, including after an account
is deleted, and then deleted. Whatever fits neither rule was set out as a
proposal (§5), not adopted by the signature; I adopted those proposals the
same evening, and a version 1.5 will carry them. One change goes the other
way: the processing-job row itself, which our deletion process listed for
deletion with the account, is kept with its job evidence, because the database
refuses to delete a job while its records point at it.

**The questions.**

- (a) Privacy 3.3 §9 says a deletion removes "queued processing jobs" with
  everything else, and names three things that survive. Job evidence kept 12
  months would be a fourth. Is it covered by the first ("records that prove
  your recordings were processed with your agreement"), or must the Privacy
  Policy say so in a new version, accepted again by every user, before this
  rule is switched on?
- (b) Can you support 12 months from the recording for this evidence? On
  what ground can it survive an erasure request (Article 17(3))?
- (c) §5.7: I have decided (P7) that each purchase and token-use record is
  deleted when its five years end, for open accounts as well, counted first.
  Any objection? And v1.3's two open points: does the five-year period of the
  Accounting Act (art. 74) apply to a seller operating as działalność
  nieewidencjonowana; and should the AI-usage record, a cost record rather
  than a sale, be detached from the person rather than kept?
- (d) §5.1: I have decided (P1) that the nine live tables only database
  functions may write are deleted with the account or the project, through a
  governed database function, rather than kept as "empty receipts" (the row
  kept, with the words erased and only identifiers and times left). Any
  objection?

---

## 4. Where a user lives: ask once, or check again?

**Read.** `docs/PRODUCT-LEGAL-FLOW-PLF-1.1.md`, user flow items 5 and 6
(PLF-U6 is item 6), with my amendments of 5 October (lines 59–69). Terms 3.3 §4, "Where the
service is available" (`copy/terms-3.3.txt` lines 75–79).

**What we did.** A user gives their country of residence once, at setup.
When a new policy version asks them to accept again, the country from their
latest acceptance is shown already chosen; they can change it, and the
acceptance is refused for a country the policy does not list. Item 6 of our
flow said location would be reassessed after a risk signal or a material
change in the account's circumstances. On 5 October I dropped that, unless
you want it. Nothing reassesses location today; no IP address is
checked.

**The question.** Is asking once, with the country shown again at each
re-acceptance, enough? Or do you want location reassessed on a risk signal,
and if so, on which signal?

---

## 5. Recording other people: are the Terms enough without a report button?

**Read.** Terms 3.3 §6, "Recording other people" (`copy/terms-3.3.txt`
lines 91–104), and §7 (line 111), quoted below.
`docs/PRODUCT-LEGAL-FLOW-PLF-1.1.md` item 3 as amended on 5 October
(lines 52–56). My answers Q18 B and Q20 A
(`docs/SPEC-DECISIONS-LOG.md` lines 1574–1577).

Terms 3.3 §6:

    6. RECORDING OTHER PEOPLE

    You may record your own voice. You may not use WillpowerLab to record anyone
    else without their knowledge and their agreement.

    This matters more here than in most products, because a recording of a person's
    voice is their personal data and we process it on your say-so. If you record
    someone else, you are the one who must have their permission, and you are
    responsible for having it.

    If you believe your voice has been recorded and uploaded to WillpowerLab by
    somebody else, contact us at contact@willpowerlab.com. We will act on that
    report, which includes blocking further processing of the recording and
    deleting the audio.

Terms 3.3 §7, the first item:

    - record a person who has not agreed to it;

**What we did.** I decided (Q18 B) that there is no "report a recording"
control in the app: the Terms carry the rule, and a person who
believes their voice was uploaded by someone else writes to us. I also
decided (Q20 A) that the Terms stand as written: others may be recorded with
their knowledge and agreement.

**The question.** Do these Terms carry the rule adequately, both for the user
who records and for the person recorded, without an in-app control for
reporting a recording?

---

## 6. The coach's own words and the training yes

**Read.** `17-door-2-coach-word-surfaces-shut-2026-10-02.md`, "What would open
it" (lines 29–41). The switch sentence I signed:
`13-training-consent-wording-SIGNED-2026-10-01.md` line 18.

**What we did.** You advised on 1 October that a coach's sentences about a
speaker's passage are the speaker's personal data. A speaker may turn on
training with this sentence:

    Use my practice text and my coach's notes on it to train the models that write WillpowerLab's feedback.

Two kinds of coach writing are kept out of all training until you answer: the
coach's personal line on one moment of a Take, and the coach's word for a
whole Take.

**The question.** Does a yes to that sentence cover those two, as the speaker
reads "my coach's notes on it"? If it does not, we need new wording and a
fresh yes from every speaker.

---

## 7. Six years for the record of the training choice

**Read.** `copy/privacy-3.3.txt` §4a (lines 179–182), §7
(lines 312–314) and §9 (lines 372–375).
`11-retention-schedule-v1.1-training-DRAFT.md`: the row (line 36) and
"What counsel is asked to check", item 1 (lines 71–76).
`docs/SPEC-DECISIONS-LOG.md` N15, item 3 (lines 787–788).

**What we did.** On 1 October you told us that "as long as it is useful" is
not a period. I named six years after the person turns training off
or deletes the account, taking the general limitation period for claims
(art. 118 of the Civil Code) as the reasoning. The record holds identifiers,
times, the policy version and a fingerprint of the switch wording; no words
and no voice. The Privacy Policy already publishes the six years.

**The question.** Do you confirm six years, or replace it? A different
number means a new Privacy version that every user accepts again.

---

## 8. A coach listening when the user receives no written review

**Read.** Terms 3.3 §11, "Human coaches" (lines 195–207). `copy/privacy-3.3.txt`
§4, the contract basis (lines 75–86), and §5, "Human coaches"
(lines 245–255). `docs/SPEC-DECISIONS-LOG.md` M4 (lines 532–538). Your answer of
23 September as we recorded it: `scripts/phase1_policy_publish_unbundled.sql`
lines 294–299.

**What we did.** Coach review is part of the service for every user: a coach
may listen to a user's recordings to review the feedback the user was given
and to prepare practice. What a plan or package sets is how many written
reviews come back. A user may therefore receive none (the free start, and the
Practice package), and a coach may still listen. The Terms say so plainly: "A
plan with no coach reviews does not mean nobody listens; it means no written
review is returned to you that month." You told us on 23 September that the
contract basis holds for coach review, covering the delivery of the coaching
only.

**The question.** Where a user receives no written review, is a coach's
listening still necessary for the contract (Article 6(1)(b))? If not, is
legitimate interest with an off switch the right basis, or should a coach not
listen at all where no review is delivered?

---

## 9. Article 9 and the training yes: two of our records disagree

**Read.** `copy/privacy-3.3.txt` §4a, the legal basis (lines 162–167).
Our code, quoted below: `services/pair_consent.py` lines 17–20;
`migrations/a_training_yes_is_its_own_act.sql` lines 111–122 and
lines 242–246; `migrations/a_training_yes_counts_any_later_policy.sql`
lines 115–119.

What the published Privacy Policy says:

    Legal basis: your consent (Article 6(1)(a) GDPR), given as explicit consent
    (Article 9(2)(a) GDPR) because what you say in a practice passage may reveal
    sensitive information about you. You give it on its own screen, by turning the
    switch on. It is never on when you sign up, never pre-ticked, and never a
    condition of using WillpowerLab. Saying no costs you nothing. You can turn it
    off at any time.

What our code note says, citing your answer of 1 October:

    WHICH SURFACES NEED THE YES: all three, counsel 2026-10-01 (a coach's note
    about a speaker's passage is the speaker's personal data even without the
    passage attached; basis Art 6(1)(a) with Art 9(2)(a), never legitimate
    interest).

What the database records with every training yes (the comment is ours, the
values are what is stored):

    -- Exactly one purpose row. Voice is not biometric here: no Article 9.
    INSERT INTO public.ml_consent_event_purposes (
        consent_event_id, purpose, article_6_basis, article_9_basis
    ) VALUES (consent_event.id, 'pooled_model_improvement', '6(1)(a)', NULL)
    ON CONFLICT (consent_event_id, purpose) DO NOTHING;

and with the approval behind it:

    -- Voice is not biometric data here (counsel, 2026-09-25): no Article 9.
    ...
    p_approving_authority, p_approved_at, p_jurisdictions, '6(1)(a)',
    'not_applicable', p_evidence_object_key, lower(p_evidence_sha256)

**The disagreement.** The Privacy Policy and the code note say the training
yes is explicit consent under Article 9(2)(a), because what a person says in a
practice passage may reveal sensitive information. The database records each
yes with no Article 9 basis, on the reasoning that voice is not biometric data
here (your advice of 25 September). Both reasons can be true at once: no voice
is used for training, but the words can be sensitive.

**The question.** For the record kept of each yes, which is right: (a)
Article 9(2)(a) explicit consent, as the Privacy Policy says, or (b) no
Article 9 basis? If (a), the database's record of each new yes is corrected;
please also tell us whether the yes records already made need anything.

---

## 10. Objecting to the blind check alone

**Read.** `copy/privacy-3.3.txt` §4, the blind check (lines 92–102) and
practice (lines 104–110); §8, the right to object (lines 334–335).
`15-coach-blind-check-privacy-line-and-balancing-test-SIGNED-2026-10-02.md`,
safeguard 4 (lines 133–135) and the conclusion (lines 139–143).
`14-founder-determinations-2026-10-02/q1.md`, the answer (lines 21–33).

Privacy 3.3, lines 99–102:

    Legal basis: our legitimate interest in keeping the tool accurate (Article
    6(1)(f) GDPR). You can turn this off at any time by turning off Personalised
    practice in your settings: from then on no clip of yours is chosen for a
    check. Turning it off costs you nothing else.

**What we did.** From time to time a coach hears a short clip, without
knowing who the speaker is or what our software found, to check our automated
listening. The basis is legitimate interest. The one off switch is
"Personalised practice", which is also the consent for practice itself. Today
a user cannot stop the blind check and keep practice: there is no separate
switch, and an objection by email under §8 would have nothing to act on but
turning practice off for them.

**The questions.** Under Article 21, must a user be able to object to the
blind check alone, keeping practice? And is "Turning it off costs you nothing
else" accurate, when turning it off also ends practice?

---

## 11. Terms 3.4 §2: packages bought once, instead of monthly plans

**Read.** Terms 3.3 §2, "What it costs" (lines 40–64), and §11 (lines 201–207).
`copy/privacy-3.3.txt`, "Payments" and "Human coaches" (lines 240–243 and
lines 249–250). `docs/SPEC-DECISIONS-LOG.md` N44 (lines 1446–1466) and N49
(lines 1611–1632).

**What we did.** Since 5 October, purchases are packages bought once: nothing
renews, and the subscription paths are removed (no subscription was live).
Terms 3.3 §2 still describes monthly plans and monthly allowances. The
proposed §2 follows, word for word. It is not published, and I have not yet
signed it off.

    2. WHAT IT COSTS

    You start with 12,000 free tokens, once. After that you can buy packages. A
    package is paid for once: it never renews, and there is nothing to cancel.

    Work in the app is measured in tokens. The tokens in a package stay until you
    use them; they do not expire at the end of a month.

      Practice    150,000 tokens     no coach reviews     USD 12, once
      Coaching    150,000 tokens     3 coach reviews      USD 39, once
      Intensive   400,000 tokens     8 coach reviews      USD 89, once

    Reviews by a human coach are a separate limit from tokens, and the tighter of
    the two applies: you can have tokens left and no reviews left. The coach
    reviews in a package also stay until you use them.

    The price and what it includes are shown before you pay. We will tell you
    before any price changes. Payments are taken by our payment provider; we do not
    see or store your card details.

    If you are a consumer in the EU or EEA, you have 14 days to withdraw from a
    purchase. We give you that full 14 days with no questions asked, even once you
    have started using it.

And one line of the Privacy Policy, replacing "how many reviews you receive
each month depends on your plan" (lines 249–250):

    The number of coach reviews you receive depends on the packages you buy.

**The questions.**

- (a) Is this §2 adequate for one-time packages of digital service,
  including the sentence that gives the full 14 days to withdraw even once
  the user has started using a package?
- (b) Terms §11 and the Privacy Policy's "Payments" line also speak of plans
  and months, and would change with it; that wording is not drafted yet. Is
  there anything else in 3.3 that must change with it?
- (c) Under Terms §15 (lines 266–274) the change is a new version that every
  user accepts again. Until then the live Terms describe monthly plans while
  the purchase screen sells one-time packages, showing the price and "one-time
  purchase" before payment (N44). Is the purchase screen's own wording enough
  meanwhile, or should sales pause until 3.4 is accepted?

---

**What happens with your answers.** An answer that changes a signed document
becomes a new version of it, never an edit. An answer that changes words a
user reads comes to me for sign-off, then goes into a new policy version that
every user accepts again.

With thanks,

Artur Willoński
WillpowerLab · contact@willpowerlab.com
