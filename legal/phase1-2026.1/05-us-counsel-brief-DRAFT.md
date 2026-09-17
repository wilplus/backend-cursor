# Brief to US counsel — WillpowerLab

> **⏸ PARKED, 2026-09-17.** The founder has scoped the launch to Poland, free,
> operating as a natural person with no entity. No US users means no BIPA, no
> CCPA and no US terms, so nothing in this brief is live work.
>
> It is kept, not deleted, because the analysis does not go stale — §§1-3 are
> code facts and §§4-9 are the questions that will still be the right questions
> whenever the US comes back. **Send it only once a company exists.** Serving
> Illinois as a natural person means BIPA's per-person statutory damages land on
> the founder personally, which is exactly what a *sp. z o.o.* is for.

**Purpose:** to instruct US counsel on serving US consumers. This is a brief,
not a determination. §§1-3 are facts about the product, written by engineering
and verifiable against the source code. §§4-9 are the questions we need
answered. §10 lists the deliverables.

**Companion material:** `02-power-score-classification-v1.0-DRAFT.md` in this
directory is the equivalent analysis under the EU AI Act. Its §§2-5 describe the
same code in more depth and much of it transfers. Please read at least its §§3
and 5 before answering §4 below — it will save time.

---

## 1. The product, in one paragraph

An adult records themselves rehearsing a presentation against their slides.
The audio is transcribed by a third-party AI provider, a language model
generates a presentation document and written feedback, and the user practises
again. It is a self-serve consumer tool. There is no employer dashboard, no
institutional deployment, and no third party receives a user's material unless
that user asks for optional human coach review.

Established entity: [[FOUNDER: Polish entity]]. No US entity at present.
Minimum age 18, enforced by a database constraint that accepts no other value.

## 2. What happens to a recording

| Step | Detail |
|---|---|
| Capture | Audio recorded in browser, uploaded |
| Storage | Cloudflare R2 (primary), Supabase (fallback). Each object verified against a SHA-256 of its exact bytes |
| Transcription | Audio bytes sent to **OpenAI** |
| Generation | Bounded transcript text sent to **OpenAI** for the presentation document and the feedback |
| Acoustic measurement | Local only. No provider involved. See §3 |
| Retention | [[FOUNDER: periods — see the Privacy Policy draft §7]] |
| Deletion | Orchestrated purge across database, storage and provider records |

OpenAI is the only AI provider that receives audio or transcript. Every provider
call takes a short-lived internal permit naming the operation and the minimum
data it may carry, and records a terminal outcome. We do not authorise OpenAI to
train on user content.

## 3. The acoustic analysis — the facts that matter for §4

This is the part that raises the biometric question. Precisely what it does:

**Inputs.** Eight numbers already produced by the audio pipeline: pitch standard
deviation, loudness range, mean pitch, words per minute, pause ratio, mean pause
length, a mid-to-end pitch delta, and an intensity envelope value.

**Normalisation.** Each is converted to a z-score against **that same speaker's
own prior recordings** — never against other speakers. A stored per-speaker
statistical baseline (mean and standard deviation per feature) makes this
possible. That baseline is retrieved **by an already-known account id**.

**Output.** Seven weighted cues combine to a single number between -1 and +1,
plus an internal five-point label. Fixed hand-set weights; nothing is learned or
tuned on data.

**Six properties, each enforced in code and testable:**

1. **No identification.** No voiceprint, no enrolment, no template store, no
   1:1 or 1:N matching. The system cannot answer "who is speaking" and is never
   asked to. Account identity is an *input* to the baseline lookup, never an
   output of it.
2. **Never surfaced.** The number and the label never reach the user, a coach,
   or any third party. No score, rating, grade or verdict is displayed to
   anyone. This is an architectural rule with automated tests behind it.
3. **Never used for a decision about the person.** Its only function is ranking
   which of the user's own sentences to replay to that same user. No
   eligibility, pricing, access or reporting consequence follows.
4. **No demographic inference.** Sex/gender routing was removed in August 2026.
   An automated test parses the module and fails if identifiers such as `sex`,
   `gender` or `speaker_sex` appear at all. We neither collect speaker sex nor
   infer it from pitch.
5. **Not sent anywhere.** Computed locally; never transmitted to OpenAI or any
   other processor.
6. **Honest absence.** Where the measurement cannot be taken reliably, the
   system records that it could not be taken rather than substituting a value.

**The one fact that cuts the other way, stated plainly:** we persist a
per-speaker statistical profile of an individual's voice. It is coarse, it
cannot identify anyone, and it is not used to — but it exists, it is derived
from voice, and it is stored.

## 4. Illinois BIPA — the primary question

We have decided to serve Illinois. We are not asking whether to; we are asking
how to do it correctly.

1. On the facts in §3, is the stored per-speaker acoustic baseline a
   **"voiceprint"** or a "biometric identifier" under 740 ILCS 14/10? Is the
   per-recording composite "biometric information"?
2. If the answer is yes, or is close enough to be litigable: what must our
   **§15(b) written notice and written release** say, and does a pre-recording
   acceptance screen with an unticked checkbox satisfy it? We control this
   screen and will build whatever wording you specify. Draft it.
3. **§15(a)** — what must our published retention schedule and destruction
   guidelines contain? Does the "purpose satisfied, or three years after last
   interaction, whichever occurs first" outer limit bind us, and how does it
   interact with the retention periods we are setting for GDPR?
4. **§15(d)** — sending audio to OpenAI is a disclosure to a third party. Does
   that require its own consent, distinct from the collection consent? This is
   the point we are least sure about and it is structural: if a separate consent
   is needed, it must be built into the acceptance screen, not bolted on.
5. **§15(e)** — reasonable standard of care. Is our storage and transmission
   posture (§2) adequate, and what would you add?
6. Given the 2024 amendment limiting damages accrual, how would you size the
   realistic exposure for a consumer product with our volumes?
7. **Would you recommend complying with §15 regardless of whether you conclude
   we hold biometric identifiers?** Our engineering view is that the marginal
   cost is roughly one paragraph and one checkbox, because we are building the
   notice-and-consent machinery anyway for GDPR. If that is right, procedural
   compliance looks cheaper than relying on winning the definitional argument.
   Tell us if that reasoning is wrong.

**Texas CUBI and Washington RCW 19.375:** the same definitional question, no
private right of action. Does anything in our facts change the answer, and does
Texas' destruction-within-one-year-of-purpose rule bite?

**Other states with biometric or sensitive-data consent rules** (Colorado,
Connecticut, Virginia, Oregon, Montana, Texas' comprehensive law, and others):
can a single consent flow satisfy all of them, or do we need per-state branches?
We would strongly prefer one flow.

## 5. California — CCPA/CPRA

8. Is the audio recording, or the derived acoustic data, **"sensitive personal
   information"**? The statutory category covers biometric information
   processed *for the purpose of uniquely identifying* a consumer, and §3.1 says
   we do not — but we want your view rather than ours.
9. If it is SPI, do we need a "Limit the Use of My Sensitive Personal
   Information" mechanism, and what does it mean for a product where the
   processing *is* the service?
10. Our notice at collection: what must it say and where must it appear?
11. Is our OpenAI relationship a **service provider** relationship rather than a
    sale or share? Does the standard OpenAI DPA carry the contract terms CCPA
    requires of a service provider, or do we need an addendum?
12. Rights requests: we have access, export, correction, restriction and
    objection workflows, plus an orchestrated deletion. What else does
    California require, and what are the response-time differences from GDPR?

## 6. Recording other people

Our Terms place the obligation on the user: record only yourself, and never
another person without their agreement. We have an abuse-report route and can
block processing and delete the audio on report.

13. Given all-party consent statutes in roughly a dozen states and federal
    ECPA, is a contractual obligation on the user sufficient to protect us as
    the platform, or do we need technical measures — for example a
    pre-recording notice on every session rather than once at signup?
14. What is our exposure if a user records a third party unlawfully and that
    person sues us rather than them?

## 7. Terms of service

15. Please draft **arbitration and class-action waiver** provisions suitable for
    a US consumer product, and advise on mass-arbitration risk. We understand
    this is the main structural defence available to us.
16. Our current Terms specify Polish law and Polish courts (§16 of the draft).
    That plainly will not serve a US consumer. Do we need a **separate US Terms**
    or a **US addendum** to the existing one? We would prefer one document with
    a US section, if that is defensible.
17. Anything in the draft Terms that is unenforceable or counterproductive in a
    US consumer contract.

## 8. AI-specific US law

18. Do any US state AI statutes reach us — Colorado's AI Act, Illinois HB 3773,
    Utah's disclosure law, or anything newer? Our read is that these target
    consequential decisions and employment, and we make neither, but please
    confirm rather than assume.
19. **FTC Act §5.** Our AI notice tells users plainly that generated output can
    be wrong, and we make no claim about improving anyone's performance. Is our
    marketing and in-product copy substantiated? The FTC has been active on AI
    claims and we would rather hear it from you first.
20. Is there any US requirement to disclose that a user is interacting with AI,
    equivalent to EU AI Act Art. 50? We disclose anyway.

## 9. Structural

21. Does a Polish entity serving US consumers need a US entity, a registered
    agent, or state registrations? What is the minimum?
22. **Insurance.** We understand BIPA claims are commonly excluded from cyber
    and tech E&O policies. What cover should we be asking for, and what
    exclusions should we refuse? Please flag this early — it may take longer to
    arrange than the legal work.
23. Anything in §§1-3 that changes your analysis and that we have not asked
    about.

## 10. What we need back

1. **A written BIPA determination** — the parallel of document 02 in this
   directory. It will be stored as an immutable, fingerprinted record, so please
   draft it as a document that stands on its own and is superseded by a new
   version rather than edited.
2. **The §15(b) notice and release wording**, ready to put on the acceptance
   screen.
3. **The published retention and destruction schedule wording**, consistent with
   the GDPR periods we are setting.
4. **US Terms provisions** — arbitration, class waiver, governing law, venue.
5. **The CCPA notice at collection** and any California-specific privacy
   sections.
6. **Confirmation that §§1-3 of this brief are the right factual basis.** If
   anything there is wrong or incomplete, that matters more than any of the
   answers.

## 11. What is already decided, so it is not re-opened

- We serve Illinois. Not a question.
- Minimum age is 18, enforced in the database.
- We do not pool user data or train models on it, and the database refuses to
  register any policy that would permit it.
- The acoustic output is never shown to anyone. This is an architectural rule
  and we will not trade it.
- Poland/EU is handled by separate EU counsel. We need the US layer to sit
  alongside that work, not replace it.

**Timing.** Our EU work and our engineering are running in parallel. The two
items on your list that gate our build are §4 question 2 (the notice and release
wording) and §4 question 4 (whether disclosure to OpenAI needs separate
consent), because both change the acceptance screen. If you can answer those two
ahead of the rest, we can keep building.
