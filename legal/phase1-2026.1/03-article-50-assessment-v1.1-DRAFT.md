# Article 50 transparency assessment — WillpowerLab

    artifact_kind:       article_50_assessment
    version:             1.1 — supersedes 1.0 (signed 2026-09-22); never edited in place, see 04 §5
    approving_authority: Artur Willoński (founder and controller) — controller's own approval, NOT counsel-signed
    approved_at:         2026-10-05 (the day the controller decided the correction; the document records a date, not a time)
    object_key:          phase1-2026.1/legal/article-50-assessment-v1.1.pdf
    sha256:              [[computed from the signed PDF at registration time]]
    metadata:            {"policy_version": "phase1-2026.1", "ai_notice_version": "ai-notice-3.1-2026-09-23"}

## What changed in 1.1 (5 October 2026)

The founder's answer Q22 A (decisions log N48.4): document 03 is corrected
to say what the screens label, and counsel is asked whether the Feedback
sheets need a label of their own. Corrections of fact only; no conclusion
moves:

- **§6 says what the screens label today** (frontend `main` at `9a928fd6`,
  5 October 2026; the new subsection after the gaps table). The Ideal Text's
  caption now reads "AI-generated text · Take N". The Feedback sheets carry
  no label of their own and sit inside the page's machine-readable mark. A
  rewrite a sheet offers is made by a fixed rule and a praise line is a
  signed sentence. The `text/plain` clipboard flavour is unmarked. Gap 3 is
  closed (the standalone `/terms` and `/privacy` pages read the stored copy
  since 25 September), and gap 2's notice is live (a policy has been active
  since 24 September).
- **§3 follows it.** The visible sentence it quoted is no longer on any
  screen; the clipboard item it left open was decided by the founder on 22
  September (no marker line); counsel still confirms whether the html-only
  marking satisfies 50(2) for the clipboard.
- **§2 names the notice that is live**, `ai-notice-3.1-2026-09-23`, and says
  what it states.
- **Four statements v1.0 still carried, and that were no longer true, are
  corrected:** §1 and §3 said a language model writes the Feedback; §2's
  status said the client render of the notice did not yet exist (gap 2
  closed that on 19 September); §4 said the AI notice discloses the voice
  measurements, which Privacy 3.3 §3 now does.
- **Counsel is asked** both open questions (`21-counsel-questions-2026-10.md`,
  question 2).

§8's conclusion and the signature follow these changes; everything else is
v1.0's text, unchanged. The v1.0 signature stands for v1.0; v1.1 needs its own
render, signature, upload and hash (`SIGNED-ARTIFACTS.md`).

**STATUS: DRAFT, for the controller's signature (v1.0 signed 22 September
2026) — NOT COUNSEL-SIGNED.** Signing closes no gaps; the work does. Of the
five gaps in §6, the three this document treated as blocking activation are
closed — gap 1 (Article 50(2) marking) on 2026-09-19, with two questions put to
counsel; gap 2 on 2026-09-19; gap 3 on 2026-09-25. Gaps 4 and 5 are open and do
not block. The founder decided the plain-text clipboard on 22 September 2026
(no marker line). §3, §6 and §8 record what is still put to counsel rather than
settled here. Each policy publish since 23 September registers this artifact provisionally
with counsel's correspondence of 23 September 2026 and no signed counsel
letter (`scripts/phase1_policy_publish_unbundled.sql` and each publish
since); nothing here rests on it.

Article 50 of Regulation (EU) 2024/1689 has applied since 2 August 2026. This
assessment is therefore about an obligation that is already in force, not one
being prepared for.

This document records what was checked, what was found, and what is not yet
done. Everything it once listed as an unmet obligation was closed by
2026-09-25; the two items still open are in §6, named rather than footnoted,
and neither is an Article 50 obligation that binds today.

---

## 1. Role and scope

WillpowerLab is the **provider** of the AI system (it develops it and places it
on the market under its own name, Article 3(3)) and is also its **deployer** for
the purposes of the Article 50(3) duties. Both sets of obligations apply.

The system: a presentation-practice service for individual adults. A user
records themselves presenting against their slides; a speech model transcribes
the audio; a language model generates the Ideal Text document; the Manager
chooses the Feedback from the user's own words, by rule (§3; corrected in
1.1); and an internal acoustic composite helps select which of the user's own
sentences to surface back to them.

Article 50 applies regardless of risk tier. Nothing in this assessment depends
on the outcome of document 02, except where §5 says so explicitly.

## 2. Article 50(1) — users must know they are interacting with AI

> Providers shall ensure that AI systems intended to interact directly with
> natural persons are designed and developed in such a way that the natural
> persons concerned are informed that they are interacting with an AI system,
> unless this is obvious from the point of view of a reasonably well-informed,
> observant and circumspect natural person.

**Applies.** The product interacts directly with the user throughout. The
"obvious" carve-out is not relied on: a user recording a presentation and
receiving a written document back is not, without being told, in a position to
know that a third-party speech model received their audio.

**How we comply.** The AI notice is presented on the acceptance screen, before
any recording is possible. The notice every published policy carries, from the first
(activated on 24 September 2026), is `copy/ai-notice-3.1.txt`
(`ai-notice-3.1-2026-09-23`;
v1.0 of this document described its predecessor, `copy/ai-notice-1.0.txt`).
It states in plain language that the transcript, the written version of the
talk and the feedback are produced by automated systems, including AI models;
that the feedback is a reading, not a measurement, and scores and decides
nothing about the person; and that a person may review it. The provider that
receives the audio is named in the Privacy Policy (§5), and the Terms (§10)
say that the output can be wrong.

**Evidence, by design rather than by assertion.** The database records the
render: `ai_transparency_exposures` stores `(acquisition_principal_id,
ai_notice_version, surface, client_render_id, rendered_at, client_version)` with
a uniqueness constraint over that tuple, and
`get_phase1_processing_authorization_v1` returns an `ai_notice_rendered` boolean
computed from it. The rendered exposure requires authenticated client
confirmation; the staging rehearsal asserts this
(`docs/PHASE1-PROCESSING-RUNBOOK.md`, "rendered AI exposure requires
authenticated client confirmation").

**Status: met.** The client-side render that writes the exposure row has
existed since 19 September 2026 (§6, gap 2). *Corrected in 1.1:* v1.0 still
carried the earlier sentence here, that the render did not yet exist.

## 3. Article 50(2) — marking of synthetic content

> Providers of AI systems […] generating synthetic audio, image, video or text
> content, shall ensure the outputs of the AI system are marked in a
> machine-readable format and detectable as artificially generated or
> manipulated.

**Applies to the Ideal Text and to Manager Feedback.** The Ideal Text is text
generated by a language model. The Article 50(2) exemption for systems
performing "an assistive function for standard editing" or not substantially
altering the input does not cover the Ideal Text: it is not a cleaned-up
transcript, it is a project-specific presentation document generated from one,
and L1 makes it the sole canonical presentation document the user then works
from.

*Corrected in 1.1.* v1.0 said that Manager Feedback, too, is text a language
model generates. On 5 October 2026 a Feedback sheet shows the speaker's own
words, a rewrite made by a fixed rule from them, a praise line a person signed,
and a coach's own words (§6); the model-written suggestions that could add a
rewrite are switched off. The Feedback is still the system's output, since the
system chooses what to show, so this assessment keeps it inside 50(2): the
sheets sit inside the Ideal Text page's machine-readable mark. Whether they
also need a visible label of their own is put to counsel (§6, gap 1).

**Transcripts** are a closer question. A transcript is a representation of what
the user actually said rather than synthesised content, and the better view is
that Article 50(2) does not attach to it. Counsel should confirm.

**Status: MET as of 2026-09-19**, by the marking described below. See §6,
gap 1, for exactly what is and is not marked.

### How the marking works

**In the product.** The element wrapping the generated text carries
`data-ai-generated="true"` together with `data-ai-generated-source-type`, whose
value is the ratified IPTC NewsCode
`…/digitalsourcetype/trainedAlgorithmicMedia` — the same term C2PA carries for
the identical claim. A JSON-LD block beside it states the claim again in a
format a parser that is not looking for our attribute names will find. Using a
published vocabulary rather than a string we invented is the point: it is what
makes the mark mean something to a reader who is not us. Alongside it, a
visible caption under the project's name tells the person reading that the
text is AI-generated: *"AI-generated text · Take N"* since 5 October 2026
(founder, N48.3 Q8 A), the design's words, N naming the Take whose text is
shown; it rates nothing (AC-9). The sentence v1.0 quoted here ("Written by AI
from what you said — it can be wrong, so check it before you present") was
shortened on 22 September and replaced on the Ideal Text on 5 October; §6
lists what each screen carries now.

**On the way out.** `docs/AI-CONTENT-MARKING-PROPOSAL.md` §1 enumerated every
path by which generated text leaves the product. There are four, and all four
are now accounted for:

| # | Path | Marking |
|---|---|---|
| 1 | Copy buttons → clipboard | the `text/html` flavour carries the attributes and the JSON-LD. The `text/plain` flavour does not — see the decided item below |
| 2 | Download as PDF | an XMP packet (`/Type /Metadata`) referenced from the catalogue, carrying `Iptc4xmpExt:DigitalSourceType` as an `rdf:resource`, plus the DocInfo dictionary for readers that ignore XMP |
| 3 | Download as `.docx` | OOXML core properties (`docProps/core.xml`), where any office suite shows provenance under File → Properties |
| 4 | GDPR data export (JSON) | **nothing to mark.** `export_authorization_evidence` returns receipt ids, timestamps, country, locale, client version and request states — no Ideal Text, no Feedback, no transcript. Checked rather than assumed, as the proposal asked. There is no other export or download route in the backend |

All three markings are generated from one shared assertion, so the exporters
cannot drift into three wordings of one claim — which is also what allows C2PA
to be added beside them later rather than replacing them (proposal §4).

**What is NOT marked, deliberately.** Transcripts — a transcript represents
what the user actually said, and marking it as artificially generated would be
a false claim. A coach's own writing — `origin: "coach"` is a human author, and
the mark is gated on that field rather than applied to the Feedback surface
wholesale, which is the same provenance wall L3 keeps everywhere else. And the
**plain-text clipboard flavour**, which stays byte-identical to what the user
reads: see the next subsection. The Feedback sheets carry no visible label of
their own (§6).

### Decided item — the paths that cannot carry a mark

**The earlier draft of this section was wrong about the shape of the problem.**
It described the risk as "a user can select the Ideal Text and press Ctrl-C"
and reasoned about whether a provider's obligation follows a user's own act.
That understated it, because the product **ships a Copy button and a `.docx`
export**. Those are our acts, in our product, and the "it was the user's own
doing" argument was never available for them. They are now marked.

What genuinely remains outside any marking: the **`text/plain` clipboard
flavour**, a screenshot, and retyping.

**The framing we would put to counsel.** The Art 50(2) obligation is on the
*provider*, to mark the outputs *the AI system produces*. A user copying text
out of an application is the user's own act, and reading the obligation to
follow the content through an arbitrary third-party paste target would make it
unsatisfiable by any provider of generated text. The better view is that it
does not extend that far. **Counsel should confirm; we do not assume it.**

**The plain-text flavour was decided by the founder on 22 September 2026: it
carries no marker line** (decisions log, "Article 50(2) and the plain-text
clipboard — SETTLED"). v1.0 recorded it as open because the two written
positions disagreed and the implementation had taken one side; the record of
that disagreement stays below.

`docs/AI-CONTENT-MARKING-PROPOSAL.md` §3 recommends **option 1: a visible
trailing marker line** on the `text/plain` flavour, on the reasoning that it is
"the only one that is true for every paste", and notes the line is user-facing
copy needing founder sign-off. The proposal explicitly describes the
html-only answer as meeting the obligation "for some pastes and not others".

**What shipped is the html-only answer**, on this reasoning: a trailing
sentence is not *a machine-readable format*, which is what Art 50(2) asks for,
so it would not convert a non-compliant paste into a compliant one; it would
appear in the user's own pasted text every time; and the Ideal Text exists to
be pasted into a presentation, so the cost lands squarely on the core loop.
Zero-width encoding is rejected by both documents and stays rejected.

**The founder's half is answered; counsel's is not.** The founder decided that
the trailing line does not ship. Counsel confirms whether html-only satisfies
50(2) for the clipboard at all (`21-counsel-questions-2026-10.md`, question
2). If counsel rejects the boundary argument, the trailing line is where this
lands, and a later version of this document says so.

Restricting copying altogether was considered and rejected: a real product cost
on the core loop, and it would raise the bar rather than close the gap, since
screenshots and retyping remain.

**Zero-width characters are rejected by name and stay rejected.** Invisible
watermarking of user-facing text is a covert mark on content the user believes
is theirs; it survives paste precisely because nobody can see it, corrupts the
text for any downstream tool, and is the kind of measure that reads badly in
exactly the forum where it would be examined. It is not on the list above and
should not be re-proposed as a clever solution to option 1's cost.

## 4. Article 50(3) — emotion recognition and biometric categorisation

> Deployers of an emotion recognition system or a biometric categorisation
> system shall inform the natural persons exposed thereto of the operation of
> the system […]

**Whether this applies is the open question in document 02 §7.** If the
determination is that the voice-confidence composite is not an emotion
recognition system, 50(3) does not attach.

**We comply either way, and deliberately.** The acoustic delivery analysis is
disclosed regardless of the determination: that measurements are taken from
how the user's voice sounds, what they are used for (choosing which of the
user's own sentences to show back), and that no score or rating is produced for
or about the user. This costs two sentences and removes the dependency between
this assessment and an unresolved determination. *Corrected in 1.1:* the
disclosure is in the Privacy Policy, §3 "The sound of your voice", which the
acceptance screen shows before any recording, beside the AI notice. Notice 1.0
carried it too; notice 3.1 does not repeat it.

**Note for the record:** the disclosure is drafted to satisfy 50(3) without
breaching AC-9. It describes the operation of the analysis qualitatively and
surfaces no number, band, ratio or classifier output. A 50(3)-compliant
disclosure does not require surfacing the output, and must not be allowed to
become a route to surfacing it.

**Status: met, and independent of document 02.**

## 5. Article 50(4) — deep fakes and public-interest text

**Not applicable.** The system generates no synthetic image, audio or video
resembling any person, and the generated text is a private document for its own
author, not text "published with the purpose of informing the public on matters
of public interest".

## 6. Article 50(5) — form and timing

> The information […] shall be provided to the natural persons concerned in a
> clear and distinguishable manner at the latest at the time of the first
> interaction or exposure. The information shall conform to the applicable
> accessibility requirements.

**Timing.** The acceptance screen precedes any recording. A user who has not
accepted cannot produce a receipt, and without a receipt
`get_phase1_processing_authorization_v1` returns
`PROCESSING_AUTHORIZATION_REQUIRED` and `finalize_phase1_recording_intake_v1`
raises rather than accepting the upload. The timing requirement is enforced by
the database, not by a UI convention.

**Clear and distinguishable.** The AI notice is its own document with its own
version and its own hash. It is not a clause inside the Terms.

**Accessibility.** Not yet assessed against the Accessibility Act / EN 301 549.
Open item.

### Gaps — the honest part

| # | Gap | Obligation | What is needed |
|---|---|---|---|
| 1 | The Ideal Text and Feedback were not marked in any format — **closed 2026-09-19; what each screen carries today is set out below; two questions put to counsel** | 50(2) | The mechanism is in §3: a visible caption on both Ideal Text screens, and a machine-readable IPTC `trainedAlgorithmicMedia` marking on the Ideal Text page, which holds the Feedback sheets, and on all three export paths that carry generated text (the fourth carries none). One module (`frontend-cursor/src/lib/willab/aiGeneratedMark.ts`, frontend `ae212ee9`, #406) is the single source of the vocabulary; a source-reading test fails if a surface drops the mark or a transcript gains one, and the PDF test walks the produced file's xref to prove the added metadata objects did not corrupt it. **Put to counsel:** whether the Feedback sheets need a visible label of their own, and whether the html-only clipboard satisfies 50(2) (§3). |
| 2 | ~~No client surface renders the AI notice or writes `ai_transparency_exposures`~~ **CLOSED 2026-09-19** | 50(1), 50(5) | Done. `Phase1AcceptanceFlow.tsx` shows the notice as its own step and writes the exposure **on render, not on submit** (`recordAiNoticeRendered` → `/api/v2/processing-authorization/ai-rendered`, keyed on `ai_notice_version`), so a user who reads it and closes the screen still counts as informed. Shipped to production in frontend #389 (`f4607888`). Live since the first policy was activated on 24 September 2026 (version `phase1-2026-09-23`); every policy published since carries the same notice. |
| 3 | ~~The standalone `/terms` and `/privacy` pages are hardcoded React~~ **CLOSED 2026-09-25** (narrowed 2026-09-19) | 50(5) "clear", and the integrity of the whole hashing scheme | The receipt-integrity half was fixed on 2026-09-19: `Phase1AcceptanceFlow.tsx` renders the exact `terms_copy` / `privacy_copy` / `ai_notice_copy` bytes returned by `get_phase1_processing_authorization_v1`, so the text read at the moment of acceptance **is** the text whose hash the receipt names. The residual closed on 2026-09-25 (founder decisions 2 and 3 of that day): both standalone pages read the stored copy of the published policy on the server (`src/app/terms/page.tsx`, `src/app/privacy/page.tsx`, `loadPublishedPolicyText`), so they cannot drift from it. |
| 4 | Accessibility conformance not assessed | 50(5) | Assessment against the applicable accessibility requirements. |
| 5 | Article 4 (AI literacy) measures not documented | Art. 4, in force since 2 Feb 2025 | A short record of the measures taken for staff and contractors who operate the system. Outside Article 50 but adjacent and currently absent. |

Gap 3 was the one to fix first, and it is fixed. It was never really an
Article 50 problem: it was the foundation the whole receipt mechanism rests on.
`POLICY_COPY_HASH_MISMATCH` and `PROCESSING_POLICY_STALE` protect the stored
copy against drift, and neither can see a separately maintained React page —
which is exactly why acceptance had to stop happening on one, and why the
standalone pages now read the stored copy too. Gap 1's machine-readable
obligation was the last thing this document treated as blocking activation;
the mechanism landed on 2026-09-19, the founder decided the clipboard on
2026-09-22, and two questions inside it are put to counsel. **Gaps 4 and 5
remain open and neither blocks activation**; they are named here so that
"open" never quietly becomes "forgotten".

### What the screens label today (frontend `main` at `9a928fd6`, 5 October 2026)

- **The Ideal Text.** On both screens that show it (`IdealTextOverlay.tsx`,
  `IdealTextReadout.tsx`), the header caption under the project's name reads
  **"AI-generated text · Take N"**, N being the Take whose text is shown
  (`AiGeneratedNote`, `aiGeneratedLabel`; before a Take number is known it
  reads "AI-generated text"). The element that wraps the whole page carries the
  machine-readable mark (`aiGeneratedAttrs("ideal-text")`: `data-ai-generated`,
  the IPTC `trainedAlgorithmicMedia` source type, the producer), and a JSON-LD
  block sits beside the caption.
- **The Feedback sheets** (the moment sheet `DeckChunkModal.tsx` and the
  paragraph sheet `ParagraphSheet.tsx`) **carry no label of their own.** They
  open inside the Ideal Text page's element, so the page's machine-readable
  mark covers them; no line on a sheet says what is AI-generated. What a sheet
  shows: the speaker's own words; a rewrite made by a fixed rule from the
  speaker's own words (the model-written suggestions that could also supply
  one, `MOMENT_SUGGESTIONS_ENABLED`, are off); a praise line that is a sentence
  signed by the founder or a coach (`feedback_catalogue`), or the sheet's own
  fixed wording where no signed line matches; a coach's own words
  (a person's writing, never marked: L3); and exercise videos made by people.
- **Presentation Mode** shows the text full screen with no visible label; it
  opens inside the same page element and its mark.
- **The coaching-bundle sheet** (`ConfidentMomentCoachingBundle.tsx`) would show
  "Written by AI — it can be wrong." under machine-written text, with its own
  mark. It is switched off (`CONFIDENT_MOMENT_BUNDLE_V1_ENABLED`, off by
  default), so no screen shows that line today.
- **Leaving the product.** The Copy button puts both flavours on the
  clipboard: `text/html` carries the attributes and the JSON-LD; **`text/plain`
  carries nothing** (founder decision, 22 September 2026). The PDF export
  carries the XMP packet and the DocInfo dictionary, the `.docx` export its
  core properties. The review deck has a plain-text Copy button of its own,
  but it is drawn only in a layout no screen uses (both Ideal Text screens open
  the deck in its "stage" layout), so the only copy a speaker can press is the
  marked one.

## 7. Change management

A change to any of the four copy documents changes its SHA-256. The stored
hashes then no longer match what a client submits, and
`accept_phase1_processing_authorization_v1` raises `PROCESSING_POLICY_STALE`
until the user re-accepts the new version. Transparency is therefore versioned
by construction: a user's receipt names exactly which words they were shown.

A new `ai_notice_version` also resets `ai_notice_rendered`, because the
`ai_transparency_exposures` lookup is keyed on the version — so a changed notice
must be re-rendered and re-acknowledged before it counts as delivered.

**Trigger conditions for re-assessing this document:** a new provider receiving
audio or transcript; a new generated artifact surfaced to users; a change to the
document 02 determination; any deployment into a workplace or education context;
or an export/sharing feature that lets generated text leave the product.

## 8. Conclusion

Articles 50(1), 50(3) and 50(5) are met. The backend evidence contract is
implemented and, since frontend #389, the client surface that renders the
notice and writes the exposure exists (gap 2 closed; gap 3 closed on
2026-09-25). **Article 50(2) is met as of 2026-09-19** (gap 1): the Ideal Text
carries a visible caption ("AI-generated text · Take N") and a machine-readable
IPTC `trainedAlgorithmicMedia` marking, the Feedback sheets sit inside that
marking with no visible label of their own, and all three export paths that
carry generated text are marked; the fourth was checked and carries none. The
`text/plain` clipboard flavour is unmarked by the founder's decision of 22
September (§3). Two questions are put to counsel: whether the sheets need their
own label, and whether html-only satisfies 50(2) for the clipboard.
Screenshots and retyping remain outside any marking, argued in §3 rather than
assumed away. Article 50(4) does not apply.

Per `docs/PHASE1-PROCESSING-RUNBOOK.md`: do not describe the application as
"fully compliant". This document reports the controls and evidence actually
verified, and names five that are not.

**This assessment no longer withholds support for activation.** Every gap it
treated as blocking — 1, 2 and 3 — is closed. The two questions put to counsel
do not hold activation: they ask how much further to go on one paste target
and on one surface, not whether the obligation is addressed. Gaps 4 (accessibility conformance) and 5 (the Article 4 AI-literacy
record) are open and are not blocking; they are tracked, not waived.

Two things this document does **not** say, and should not be read as saying.
It does not say the application is "fully compliant" — `docs/PHASE1-PROCESSING-RUNBOOK.md`
forbids that phrasing, and this is a report of controls actually verified. And
it is the controller's own assessment, not counsel's: §3's position on manual
paste, §3's reading that Article 50(2) does not attach to transcripts, and
whether the Feedback sheets need a visible label of their own (§6) are put to
counsel rather than settled here.

## 9. Signature

By signing, the approving authority adopts v1.0 as corrected by v1.1 (the
changes listed at the top), in place of v1.0 for every use from today.

    Name:      Artur Willoński
    Firm:      None — natural person, no company (działalność nieewidencjonowana)
    Date:      5 October 2026 (the day of the decision; the signature's own timestamp records when it was signed)
    Reference: WILLAB-PHASE1-2026.1-A50-v1.1
