# Article 50 transparency assessment — WillpowerLab

    artifact_kind:       article_50_assessment
    version:             1.0
    approving_authority: Artur Willoński (founder and controller) — controller's own approval, NOT counsel-reviewed
    approved_at:         2026-09-19T00:00:00Z
    object_key:          phase1-2026.1/legal/article-50-assessment-v1.0.pdf
    sha256:              [[computed from the signed PDF at registration time]]
    metadata:            {"policy_version": "phase1-2026.1", "ai_notice_version": "1.0"}

**STATUS: APPROVED AND SIGNED BY THE CONTROLLER, 19 September 2026 — NOT
COUNSEL-REVIEWED.** Signing closes no gaps; the work does. Of the five gaps in
§6, the three this document treated as blocking activation are closed — gap 1
(Article 50(2) marking) and gap 2 on 2026-09-19, gap 3 narrowed to a residual
that no receipt depends on. Gaps 4 and 5 are open and do not block. **One
decision inside gap 1 is open and is a founder call: whether the plain-text
clipboard flavour carries a visible marker line (§3).** §3 and §8 record what
is still put to counsel rather than settled here.

Article 50 of Regulation (EU) 2024/1689 has applied since 2 August 2026. This
assessment is therefore about an obligation that is already in force, not one
being prepared for.

This document records what was checked, what was found, and what is not yet
done. Everything it once listed as an unmet obligation was closed on
2026-09-19; the two items still open are in §6, named rather than footnoted,
and neither is an Article 50 obligation that binds today.

---

## 1. Role and scope

WillpowerLab is the **provider** of the AI system (it develops it and places it
on the market under its own name, Article 3(3)) and is also its **deployer** for
the purposes of the Article 50(3) duties. Both sets of obligations apply.

The system: a presentation-practice service for individual adults. A user
records themselves presenting against their slides; a speech model transcribes
the audio; a language model generates the Ideal Text document and Manager
Feedback; and an internal acoustic composite helps select which of the user's
own sentences to surface back to them.

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

**How we comply.** The AI notice (`copy/ai-notice-1.0-DRAFT.txt`, version 1.0,
which loses the `-DRAFT` suffix at signature) is
presented on the acceptance screen, before any recording is possible, and states
in plain language that recordings are processed by AI, which provider receives
the audio, that the Ideal Text and the Feedback are AI-generated, and that they
can be wrong.

**Evidence, by design rather than by assertion.** The database records the
render: `ai_transparency_exposures` stores `(acquisition_principal_id,
ai_notice_version, surface, client_render_id, rendered_at, client_version)` with
a uniqueness constraint over that tuple, and
`get_phase1_processing_authorization_v1` returns an `ai_notice_rendered` boolean
computed from it. The rendered exposure requires authenticated client
confirmation; the staging rehearsal asserts this
(`docs/PHASE1-PROCESSING-RUNBOOK.md`, "rendered AI exposure requires
authenticated client confirmation").

**Status: met at the design level; the client-side render that writes the
exposure row does not yet exist (§6).**

## 3. Article 50(2) — marking of synthetic content

> Providers of AI systems […] generating synthetic audio, image, video or text
> content, shall ensure the outputs of the AI system are marked in a
> machine-readable format and detectable as artificially generated or
> manipulated.

**Applies to the Ideal Text and to Manager Feedback.** Both are text generated
by a language model. The Article 50(2) exemption for systems performing "an
assistive function for standard editing" or not substantially altering the input
does not cover the Ideal Text: it is not a cleaned-up transcript, it is a
project-specific presentation document generated from one, and L1 makes it the
sole canonical presentation document the user then works from. Manager Feedback
is generated text in the same sense.

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
makes the mark mean something to a reader who is not us. Alongside it, a plain
sentence — *"Written by AI from what you said — it can be wrong, so check it
before you present"* — satisfies "detectable as artificially generated" for the
person reading. The wording is the AI notice's own, so the surface and the
notice do not develop two vocabularies for one fact.

**On the way out.** `docs/AI-CONTENT-MARKING-PROPOSAL.md` §1 enumerated every
path by which generated text leaves the product. There are four, and all four
are now accounted for:

| # | Path | Marking |
|---|---|---|
| 1 | Copy buttons → clipboard | the `text/html` flavour carries the attributes and the JSON-LD. The `text/plain` flavour does not — see the open item below |
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
reads: see the next subsection.

### Open item — the paths that cannot carry a mark

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

**⚠️ The plain-text flavour is an OPEN FOUNDER DECISION, and the two written
positions disagree.** It is recorded here rather than quietly settled, because
the implementation took one side of it.

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

**Neither document can settle this and neither should pretend to.** The
founder decides whether the trailing line ships; counsel confirms whether
html-only satisfies 50(2) for the clipboard at all. Until both answer, this is
a known, named, argued gap — not a closed one.

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

**We comply either way, and deliberately.** The AI notice discloses the acoustic
delivery analysis regardless of the determination: that measurements are taken
from how the user's voice sounds, what they are used for (choosing which of the
user's own sentences to show back), and that no score or rating is produced for
or about the user. This costs two sentences and removes the dependency between
this assessment and an unresolved determination.

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
| 1 | The Ideal Text and Feedback were not marked in any format — **substantially closed 2026-09-19, one decision open** | 50(2) | Both halves are implemented and the mechanism is in §3: a persistent visible label on both Ideal Text mounts and on machine-origin Feedback, and a machine-readable IPTC `trainedAlgorithmicMedia` marking on the surfaces and on all three export paths that carry generated text (the fourth carries none). One module (`frontend-cursor/src/lib/willab/aiGeneratedMark.ts`, frontend `cf0e5380` and `e6f41b3c`) is the single source of the vocabulary; a source-reading test fails if a surface drops the mark or a transcript gains one, and the PDF test walks the produced file's xref to prove the added metadata objects did not corrupt it. **Open:** the `text/plain` clipboard flavour, where the written proposal and the implementation disagree — §3. |
| 2 | ~~No client surface renders the AI notice or writes `ai_transparency_exposures`~~ **CLOSED 2026-09-19** | 50(1), 50(5) | Done. `Phase1AcceptanceFlow.tsx` shows the notice as its own step and writes the exposure **on render, not on submit** (`recordAiNoticeRendered` → `/api/v2/processing-authorization/ai-rendered`, keyed on `ai_notice_version`), so a user who reads it and closes the screen still counts as informed. Shipped to production in frontend #389 (`f4607888`). It is inert until a policy is registered and active. |
| 3 | **NARROWED 2026-09-19.** The *acceptance* surface now renders the stored copy; the standalone `/terms` and `/privacy` pages (`src/app/terms/page.tsx` v1.2, `src/app/privacy/page.tsx` v1.2) are still hardcoded React | 50(5) "clear", and the integrity of the whole hashing scheme | The receipt-integrity half is fixed: `Phase1AcceptanceFlow.tsx` renders the exact `terms_copy` / `privacy_copy` / `ai_notice_copy` bytes returned by `get_phase1_processing_authorization_v1`, so the text read at the moment of acceptance **is** the text whose hash the receipt names. **Residual:** the two standalone pages can still drift from the registered copy. They are no longer what any receipt is taken against, so this is now a consistency defect rather than a receipt-integrity one — but they must either render the stored copy or be plainly marked as an informational mirror. |
| 4 | Accessibility conformance not assessed | 50(5) | Assessment against the applicable accessibility requirements. |
| 5 | Article 4 (AI literacy) measures not documented | Art. 4, in force since 2 Feb 2025 | A short record of the measures taken for staff and contractors who operate the system. Outside Article 50 but adjacent and currently absent. |

Gap 3 was the one to fix first, and its load-bearing half is fixed. It was
never really an Article 50 problem: it was the foundation the whole receipt
mechanism rests on. `POLICY_COPY_HASH_MISMATCH` and `PROCESSING_POLICY_STALE`
protect the stored copy against drift, and neither can see a separately
maintained React page — which is exactly why acceptance had to stop happening
on one. Gap 1's machine-readable obligation was the last thing this document
treated as blocking activation, and the mechanism landed on 2026-09-19 with one
decision left inside it (§3, the `text/plain` flavour). **Gaps 4 and 5 remain
open and neither blocks activation**; they are named here so that "open" never
quietly becomes "forgotten".

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
notice and writes the exposure exists (gap 2 closed, gap 3 narrowed to the two
standalone pages). **Article 50(2) is met as of 2026-09-19** (gap 1): generated
text carries a visible label and a machine-readable IPTC `trainedAlgorithmicMedia`
marking, on the surfaces and on all three export paths that carry generated
text; the fourth was checked and carries none. One decision inside it is open
and named: the `text/plain` clipboard flavour, where the written proposal
recommends a visible trailing line and the implementation did not ship one
(§3). Screenshots and retyping remain outside any marking, argued in §3 rather
than assumed away. Article 50(4) does not apply.

Per `docs/PHASE1-PROCESSING-RUNBOOK.md`: do not describe the application as
"fully compliant". This document reports the controls and evidence actually
verified, and names five that are not.

**This assessment no longer withholds support for activation.** Every gap it
treated as blocking — 1, 2 and 3 — is closed or reduced to a residual argued on
the record. The open `text/plain` decision in §3 does not hold activation: it
is a question about how much further to go on one paste target, not about
whether the obligation is addressed. Gaps 4 (accessibility conformance) and 5 (the Article 4 AI-literacy
record) are open and are not blocking; they are tracked, not waived.

Two things this document does **not** say, and should not be read as saying.
It does not say the application is "fully compliant" — `docs/PHASE1-PROCESSING-RUNBOOK.md`
forbids that phrasing, and this is a report of controls actually verified. And
it is the controller's own assessment, not counsel's: §3's position on manual
paste, and §3's reading that Article 50(2) does not attach to transcripts, are
both put to counsel rather than settled here.

## 9. Signature

    Name:      Artur Willoński
    Firm:      None — natural person, no company (działalność nieewidencjonowana)
    Date:      19 September 2026
    Reference: WILLAB-PHASE1-2026.1-A50-2026-09-19
