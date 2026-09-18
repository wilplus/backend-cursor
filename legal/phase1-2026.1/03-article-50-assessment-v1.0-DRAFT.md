# Article 50 transparency assessment — WillpowerLab

    artifact_kind:       article_50_assessment
    version:             1.0
    approving_authority: Artur Willoński (founder and controller) — controller's own approval, NOT counsel-reviewed
    approved_at:         2026-09-18T00:00:00Z
    object_key:          phase1-2026.1/legal/article-50-assessment-v1.0.pdf
    sha256:              [[computed from the signed PDF at registration time]]
    metadata:            {"policy_version": "phase1-2026.1", "ai_notice_version": "1.0"}

**STATUS: DRAFT — NOT APPROVED, NOT SIGNED.**

Article 50 of Regulation (EU) 2024/1689 has applied since 2 August 2026. This
assessment is therefore about an obligation that is already in force, not one
being prepared for.

This document records what was checked, what was found, and what is not yet
done. Two obligations are currently **not met**; they are in §4 and §6 rather
than in a footnote.

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

**How we comply.** The AI notice (`copy/ai-notice-1.0.txt`, version 1.0) is
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

**Status: NOT MET.** See §6, gap 1.

### Open item — does the obligation follow the text out of the product?

A user can select the Ideal Text and press Ctrl-C. Whatever marking we apply
inside the product does not survive that paste.

**The framing we would put to counsel.** The Art 50(2) obligation is on the
*provider*, to mark the outputs *the AI system produces*. A user copying text
out of an application is the user's own act, and reading the obligation to
follow the content through an arbitrary third-party paste target would make it
unsatisfiable by any provider of generated text. The better view is that it
does not extend that far. **Counsel should confirm; we do not assume it.**

**The practical consequence, recorded so the answer can be priced.** If the
clipboard *is* in scope, there is no marking that survives an arbitrary paste
target — a plain-text field keeps no metadata, and the destination is outside
our control entirely. The honest options then reduce to two:

1. **Restrict copying** from the generated surfaces. A real product cost on the
   core loop: the Ideal Text exists to be used in a presentation, and a user
   who cannot get it out of the app has a worse product. It would also only
   raise the bar, not close the gap — screenshots and retyping remain.
2. **Accept a documented gap**, on the reasoning above, and record why.

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
| 1 | The Ideal Text and Feedback are not marked as artificially generated, in any format | 50(2) | A persistent, visible label on the Ideal Text and Feedback surfaces, **and** a machine-readable marking on any export or copy leaving the product. The visible label alone does not satisfy 50(2) — it requires machine-readable. Decide the mechanism (embedded metadata on export, or an equivalent) and record it here. |
| 2 | No client surface renders the AI notice or writes `ai_transparency_exposures` | 50(1), 50(5) | The acceptance screen in the frontend. The backend contract exists and is unused. |
| 3 | Terms and Privacy are rendered from hardcoded React pages (`src/app/terms/page.tsx` v1.2, `src/app/privacy/page.tsx` v1.2), not from the policy record | 50(5) "clear", and the integrity of the whole hashing scheme | The pages must render the exact `terms_copy` / `privacy_copy` returned by `get_phase1_processing_authorization_v1`. While they are hardcoded, the text a user reads and the text whose hash they accept can drift apart silently, and the receipt then proves agreement to words the user never saw. |
| 4 | Accessibility conformance not assessed | 50(5) | Assessment against the applicable accessibility requirements. |
| 5 | Article 4 (AI literacy) measures not documented | Art. 4, in force since 2 Feb 2025 | A short record of the measures taken for staff and contractors who operate the system. Outside Article 50 but adjacent and currently absent. |

Gap 3 is the one to fix first. It is not an Article 50 problem so much as the
foundation the whole receipt mechanism rests on: `POLICY_COPY_HASH_MISMATCH` and
`PROCESSING_POLICY_STALE` protect the stored copy against drift, and neither can
see a separately maintained React page.

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

Articles 50(1), 50(3) and 50(5) are met at the design level, with the backend
evidence contract implemented and the client surface still to be built (gaps 2
and 3). Article 50(2) is **not met**: generated text is not marked (gap 1).
Article 50(4) does not apply.

Per `docs/PHASE1-PROCESSING-RUNBOOK.md`: do not describe the application as
"fully compliant". This document reports the controls and evidence actually
verified, and names five that are not.

**This assessment does not support activation until gaps 1, 2 and 3 are closed.**

## 9. Signature

    Name:      ______________________________
    Firm:      ______________________________
    Date:      ______________________________
    Reference: ______________________________
