# Privacy Policy 3.6, Terms of Service 3.6, AI notice 3.2: what shipped since 3.5 — SIGNED by the founder 2026-10-15

**SIGNED by the founder, 15 October 2026, in chat** ("I sign the 3.6 pack of 15 October 2026 as drafted"; decisions log N72). **Counsel has not seen it**; the founder signed knowing that.

    documents:           copy/privacy-3.6.txt, copy/terms-3.6.txt, copy/ai-notice-3.2.txt (the exact bytes to publish)
    replaces:            copy/privacy-3.5.txt, copy/terms-3.5.txt, copy/ai-notice-3.1.txt
    unchanged:           copy/agreement-3.1.txt (the agreement screen's words)
    asked by:            Artur Willoński, founder and controller, 2026-10-14 ("update all the consents and
                         privacy policy so that when users accept it they are free to use it and I can
                         train on their data; just make the updates necessary after recent developments")
    training:            stays opt-in and is widened (founder's answer in chat, 2026-10-14: "Keep opt-in, widen it")
    scope:               AI voice, WhatsApp, Lounge chat, booking and lessons, community sharing, coach videos,
                         admin export, Google/LinkedIn sign-in (founder's answer in chat, 2026-10-14: all four groups)
    countries:           the 27 EU/EEA codes of 3.5, plus 'us' (founder, chat, 2026-10-15: "allow users from
                         California United States use the app so add to the list of countries United States
                         and add it below Poland"); the United States only for residents of California (D8)
    the switch wording:  26-training-consent-wording-v3-SIGNED-2026-10-15.md (training-only-v3)
    drafted by:          engineering, from the code; not a lawyer

As with 3.5, the `copy/*.txt` files carry no draft mark: their exact bytes are
what is hashed and what a user later proves they agreed to. Their effective
date line says 15 October 2026; on another day, change it in both files
before the publish script is written.

## 1. Why 3.6

Privacy 3.5 is now wrong about the product in one place and silent in
several. The worst: it says "OpenAI is the only AI provider that receives
your audio or your transcript", while the AI version of the voice sends up
to 150 s of Take-1 audio to ElevenLabs for everyone
(`services/ai_voice_clone.py:56-131`, on by default, `config.py:868-881`).
A speaker who accepts 3.5 has not been told about ElevenLabs, WhatsApp,
the Lounge chat, bookings or community sharing. 3.6 describes each.

"Free to use it" (the founder's words) is what acceptance already gives: the
agreement, the age tick, the country and the sensitive-information tick, as
today. 3.6 adds no new tick. Training stays its own optional switch, for the
reason in 26-…: a training yes bundled into accepting the Terms is not freely
given (GDPR Art 7(4)) and the bundled consent was retired for that reason.

## 2. Changelog, 3.5 → 3.6

**Privacy Policy**

| § | Change | Code it describes |
|---|---|---|
| version note | rewritten: the new features, the widened §4a, an earlier yes counts as off | — |
| §2 | sign-in name and email from Google/LinkedIn; what you write to Will; phone number; lesson details; your listener answers; the AI voice and its examples; the IP-suggested time zone on the booking page, not stored | frontend `bfd45f1` `frontend-cursor/src/lib/auth/startOAuth.ts:59-65`; `services/chat_query.py`; `services/whatsapp_notify.py:81-92`; `services/booking.py:374-461`; frontend `bfd45f1` `frontend-cursor/src/app/book/[slug]/page.tsx:18` |
| §3 | new paragraph: the AI version of your voice (up to 2.5 min of the first take, ElevenLabs, only you hear it, labelled, re-transcribed, next try measured, not for identification or training, delete and turn on again); other users also hear a take you share (§4d) | `services/ai_voice_clone.py`, `services/ai_voice_clip.py:283-442`; lock L1, L6–L11 |
| §4 | service basis now names the AI voice and Will; new purposes: talking to Will (contract), reading messages marked as about the app (legitimate interest, objection by email), WhatsApp (consent, by adding the number), lessons (contract, plus legal obligation for paid ones), admin access and export of measurements (legitimate interest); Stripe also for lessons; "making the AI voice is not training"; the optional items named | `services/chat_app_context.py:193-272`; `services/speaker_feedback.py`; `routes/v2/admin.py:1714`; frontend `bfd45f1` `frontend-cursor/src/app/admin/users/[id]/TakesExplorer.tsx:43-89` |
| §4a | the switch sentence v3; new bullet "What you write to Will"; "an AI voice example helped" joins the measurements; the AI voice and its examples are excluded with coach videos; the Lounge conversation before the yes may be used; **Art 9(2)(a) removed from the basis** (counsel, N69: the training data is not special-category, the mention was "surplus, tidied at the next version"); "before version 3.6" | 26-…; `docs/SPEC-DECISIONS-LOG.md` N69 |
| §4d | new: sharing a take with a community, per take, explicit consent, what listeners hear, their answers, stopping | `services/communities.py:48-60,273-316,385-481` |
| §5 | OpenAI also answers Will and checks AI examples; ElevenLabs named; "OpenAI is the only AI provider…" replaced by lock line L13, extended; "we do not authorise … ElevenLabs to use your content to train" (needs E1); R2 holds examples and coach videos; Supabase does sign-in; Resend sends lesson confirmations; Meta (WhatsApp), Google, LinkedIn named; coaches' video answers and lesson details; other users for §4d | `services/elevenlabs_client.py`; `services/whatsapp_notify.py:39`; `services/coach_answer_video.py` |
| §6 | ElevenLabs and Meta added under SCCs (needs E1, E2) | — |
| §7 | rows for coach videos, the AI voice and examples, the Lounge conversation, the phone number, a lesson (paid-lesson record kept for accounting), a shared take; training copies include what you wrote to Will | — (E6, E7 make two of them true) |
| §9 | the paid-lesson record survives as an accounting record; the AI voice is deleted at ElevenLabs first | `routes/v2/processing_authorization.py:479-483` |

Plus one fix: §5 "how many reviews you receive each month depends on your
plan" becomes "a written review that comes back to you is paid for in
tokens" (plans no longer carry reviews, `services/token_prices.py:51-59,154`).

**Terms of Service**

| § | Change |
|---|---|
| version note | rewritten: new features, plans as sold, training widened; three choices, all off unless chosen (training, lending, community sharing) |
| §1 | the AI voice (lock line L12, as signed for counsel 2026-10-12), Will is an AI assistant, WhatsApp, lessons; "a third-party AI provider" becomes "third-party AI providers" |
| §2 | the plan table as sold: Free 12,000 / Starter 150,000 USD 12 / Plus 550,000 USD 39 / Pro 1,400,000 USD 89 (`token_prices.py`, frontend `bfd45f1` `frontend-cursor/src/components/tokens/copy.ts:44-48`); reviews are paid in tokens; lessons: price on the booking page, cancel or move by replying, the 14-day withdrawal (see D7) |
| §8 | the AI voice is for you alone; the licence covers what you write to Will; a per-take permission for community sharing; a coach's video answer is not to be published |
| §11 | reviews paid in tokens rather than counted per plan; other users hear a take you share |

**California (founder, 2026-10-15)**

| Where | Change |
|---|---|
| Privacy version note, new §14 | what California residents should know (CCPA/CPRA style): categories, sources, purposes, sensitive personal information, no sale or sharing, the rights to know, delete, correct and limit, non-discrimination, authorised agents, 45 days |
| Terms version note, §4 | in the United States, residents of California only; choosing the United States confirms it |
| Terms §16 | a California consumer keeps the protection of California law that cannot be waived, and may sue in California |
| the publish script | `allowed_countries` gains `'us'` |
| the acceptance screen | the United States is listed right below Poland (frontend, `acceptanceSteps.ts`, `SECOND_CHOICE`; the country list and its order are not locked, consent-screen lock "Not locked") |

**AI notice 3.2:** two paragraphs added: Will is an AI assistant, not a
person; the AI version of your voice is AI-made, labelled, only you hear it
(AI Act Art 50(1) and (2): people are told they talk to an AI, and synthetic
audio is marked; document 03 is updated with this at counsel's review).

## 3. Decisions the signature takes (each drafted one way; say so if not)

**D1. A training-only-v2 yes does not carry over. Drafted: it counts as off.**
v3 names more than v2 (what you write to Will), so the v2 yes did not cover
it, exactly as D3 of 3.5 ruled for v1. Every speaker is asked again by
"Turn on the learning?" before their next take. *If 3.5 was never
published* (N68 recorded publication blocked on migration 0458; this branch
cannot see production), no v2 yes exists: then publish 3.6 in place of 3.5
and register v3 directly, retiring v1 — the outcome for speakers is the same.

**D2. The Lounge messages you read by hand. Drafted: legitimate interest, with
objection by email.** The founder reads messages Will marked as about the app
(`GET /v2/admin/speaker-feedback`). That is product feedback, not training,
so it is drafted under Art 6(1)(f) like the blind check. The other way, only
with the training yes, would mean the endpoint filters by the yes.

**D3. The AI voice stays part of the service, on from the start.** Kept as
the founder decided on 2026-10-12 (lock §4, D3a, D3b: "agreed by using the
app"), basis contract. Engineering's note for counsel: a voice clone is
built from biometric-like voice features; it is not used to identify anyone,
so Art 9 is not drafted for it, but a separate opt-in would be the safer
reading if counsel disagrees. Counsel was to review L12 and L13 before launch
and has not.

**D4. WhatsApp rests on consent, given by adding the number.** Removing it
withdraws it. Needs E4 to be true on screen.

**D5. Community sharing rests on explicit consent, per take (Art 9(2)(a)),
like lending.** Needs E5: the share screen pre-ticks a community today, and
a pre-ticked box is not consent.

**D6. The training yes covers Will's answers too.** They are written for the
speaker from the speaker's own words and project, so they are drafted as
part of "what you write to Will".

**D7. Lesson cancellation.** Drafted as the consumer-law default (14 days to
withdraw, lost once a lesson you asked to be held within the 14 days has
taken place) plus "reply to your confirmation email", because the code has
no refund rule (`services/booking.py:16,586`). If you want a different rule
(for example a free cancellation up to 24 hours before), say so and §2
changes before signature.

**D8. The United States, California only. Drafted: the Terms limit US
residents to California.** A country code cannot tell states apart, so the
receipt records `us`, and the Terms make choosing it a statement of
California residence. Why not every state: Illinois's BIPA gives
per-person statutory damages for voiceprints without a written release, and
the AI version of the voice is on for everyone (D3); Texas and Washington
have similar laws. `05-us-counsel-brief-DRAFT.md` was parked on 2026-09-17
because there were no US users; it is live again (E12). Also for US
counsel: California is an all-party-consent state for recording
conversations (Penal Code 632), which Terms §6 already covers; the CCPA's
thresholds may not reach WillpowerLab today, and §14 is written as if they
did.

## 4. What must be true before 3.6 is published (E-items)

Publishing a sentence the code does not make true is worse than not
publishing it. Each item is its own reviewed PR or a founder action.

| # | What | Why | Who |
|---|---|---|---|
| E1 | ElevenLabs. **DPA in place** (founder supplied it 2026-10-15: "ElevenLabs Data Processing Addendum", last updated 8 April 2026, elevenlabs.io/dpa; it forms part of the self-serve Terms, so no separate signature): ElevenLabs is our processor, acting only on our documented instructions (§3.1); transfers rest on the EU-US Data Privacy Framework or the EEA SCCs, module 2, Irish law, deemed executed (§11); no selling or sharing under the CCPA (§12); 30-day notice of new subprocessors (§6.3). **Still open:** (a) the DPA's instructions are "set forth in the Agreement", so whether ElevenLabs may use our audio to improve its own models turns on the ElevenLabs Terms and our account's data-use setting, not the DPA: confirm the opt-out (or zero-retention mode) before §5's "we do not authorise … ElevenLabs" is published, or that sentence goes; (b) on self-serve plans ElevenLabs need not delete content until 180 days of inactivity and keeps backups on its own schedule (§9.2.2, §9.3), so our deletion call (`DELETE /v1/voices/{id}`) is what makes Privacy §7 true; the backup tail is for counsel | Privacy §5, §6, §7 | founder |
| E2 | Meta (WhatsApp). **DPA in place, two things open.** The founder supplied the **WhatsApp Business Data Processing Terms** on 2026-10-15 (last updated 22 August 2025, whatsapp.com/legal/business-data-processing-terms). They are part of the WhatsApp Business terms accepted in WhatsApp Manager, with no separate signature. WhatsApp is our processor (§1, §2.a: only on our instructions in the Business Terms). Confidentiality, security, breach notice "without undue delay" and help with data-subject requests are in §2.c–h. Subprocessors in the EEA or US are by written agreement, and Meta companies are pre-authorised with advance notice (§2.i–j). For WhatsApp Ireland Limited as contracting entity, the **WhatsApp Business Data Transfer Addendum** is incorporated (§2.i). Data is deleted on termination "within the time period set forth in the Business Terms", except where WhatsApp has its own right to use it (§2.k); that matches Privacy 3.6 §5, where Meta is also a controller for its own service. **Account (founder, 2026-10-15):** Business portfolio ID `1096268846348586`, WhatsApp Business Account ID `1109192322091002`. WhatsApp Manager shows no pending-terms banner, so the Business terms are accepted. Both data-sharing switches (Cloud API message events, marketing message events) are off and stay off (Privacy 3.6 §5: no sharing for advertising). **Data Transfer Addendum filed** (last updated 16 February 2024): WhatsApp Ireland relies on the **EU-US Data Privacy Framework** for transfers to WhatsApp LLC and Meta Platforms, Inc., and may use processor-to-processor SCCs instead (§2). Privacy 3.6 §6 said SCCs for Meta, so it is corrected: see §8 below. **Open:** the portfolio's official name and full address to be completed in Business settings | Privacy §5, §6 | founder |
| E3 | Lounge chat's OpenAI calls run inside `protected_provider_scope` with a permit (today `/v2/chat/query` carries none) | Privacy §5 "each transfer is made under a short-lived internal permit"; CLAUDE.md: every provider call goes through the processing-authorization path | engineering |
| E4 | A "Remove" for the WhatsApp number on Data & consent (the frontend proxy exists at `bfd45f1`, `frontend-cursor/src/app/api/v2/user/whatsapp/route.ts:8`, nothing calls it); and one handler for `/v2/user/whatsapp` (`routes/v2/people.py:65-81` stores the number in auth metadata with no opt-in time, shadowed by the `user_settings` one) | Privacy §4 "remove it at any time in Data & consent"; D4 | engineering; the card is a locked screen → founder |
| E5 | The share screen starts with nothing ticked (frontend `bfd45f1` `frontend-cursor/src/components/willab/NextTakeShareScreen.tsx:68`), and a shared take can be stopped later | Privacy §4d; D5 | engineering; locked screen (moment-feedback-chat lock) → founder |
| E6 | Coach answer videos: stored behind signed URLs, not a public bucket URL (`services/coach_answer_video.py:43-46`), and the file deleted with the take (only the row is, `data_purge_registry.py:342-350`) | Privacy §7 "deleted with it" | engineering |
| E7 | Bookings into the purge registry: deleted with the account, a paid lesson's accounting record kept and the rest cleared (`bookings` is in no registry and has no FK) | Privacy §7, §9 | engineering |
| E8 | No lane trains on Lounge messages yet; the one that does reads the v3 yes per speaker. Also gate or delete `services/ml_finetuning_export.py` / `services/annotation_export.py` (`scripts/export_annotation_events.py`), which build fine-tuning JSONL with no consent check | Privacy §4a "only with your yes" | engineering |
| E9 | An objection flag for D2: `/v2/admin/speaker-feedback` leaves out speakers who objected | Privacy §4 "from then on none of your messages is marked" | engineering (small) |
| E10 | The ninth line above the switch (26-…) on the consent screens | 26-… | engineering; locked screen → founder |
| E11 | DPIA and ROPA addenda for the four new operations (voice clone at ElevenLabs, Lounge chat, WhatsApp, bookings) and document 03 for AI notice 3.2 | accountability (Art 30, 35) | engineering drafts, founder signs |
| E12 | US counsel reads brief 05 for California (CCPA/CPRA, Penal Code 632, the AI voice under California law), §14 and Terms §4 and §16; a US resident's request handled within 45 days | D8 | founder |

## 5. After signing, in order

1. Engineering records the signature here, renames 25 and 26 from `-DRAFT`
   to `-SIGNED-<date>`, and recomputes the three copy hashes into the
   signing record.
2. The E-items above land, each in its own PR.
3. Render 26 as a PDF (`scripts/render_doc_pdf.py`), sign it (PAdES), upload
   to its `object_key`, record the signed hash in `SIGNED-ARTIFACTS.md`.
4. Engineering writes `PUBLISH-3.6-<date>.sql` from `PUBLISH-3.5-2026-10-08.sql`
   (policy `phase1-<date>-3.6`, the three copy files' exact bytes, `allowed_countries` with `'us'` added, v2 → v3 by
   `supersede_mlc2_training_consent_policy_v1`), and you run it by hand in
   the Supabase SQL editor (`docs/PHASE1-PROCESSING-RUNBOOK.md`). From then
   every speaker is asked to accept 3.6.

## 6. The sentence signed

> I sign the 3.6 pack of 15 October 2026 as drafted: Privacy 3.6, Terms 3.6, AI notice 3.2 and the training switch wording v3 with its nine lines, with D1 to D8 as drafted, and the United States (California only) added to the countries, knowing counsel has not seen them.

## 7. The signature (founder, chat, 15 October 2026)

> I sign the 3.6 pack of 15 October 2026 as drafted: Privacy 3.6, Terms 3.6, AI notice 3.2 and the training switch wording v3 with its nine lines, with D1 to D8 as drafted, and the United States (California only) added to the countries, knowing counsel has not seen them.

Word for word as offered (signing page <https://claude.ai/artifact/G5jMEWdiZtJ6ECCMvUWDv9>).
What it covers, by file:
`copy/privacy-3.6.txt` (sha256 `5aa2ffc447bf4543ec74412fe455b60bf439ca708c024d4fdfb0b41797d3ddd3`),
`copy/terms-3.6.txt` (sha256 `6ce5f7d0e7f9e52764b0bdc7e4a5ca6bc257c75ff148c4254e907220212e6bfb`),
`copy/ai-notice-3.2.txt` (sha256 `8b85806ceddc3cb07e69a8dbd5d49970be95208a410bdbbb33b6cba8bc5bde4e`),
`26-training-consent-wording-v3-SIGNED-2026-10-15.md` (switch sentence sha256 `6a8ab6eeefb59c0ef481bbdd8e05f90fb3b1f07330a949586221d45fe4828bd9`),
and D1 to D8 as drafted in section 3. Both files were renamed from `-DRAFT`
and their draft line replaced by the signature line; nothing else changed.

**Signing published nothing.** Section 5 continues from step 2: the E-items,
then the PAdES signature of 26's PDF, then the publish script.

## 8. Corrections after signature, confirmed by the founder (15 October 2026)

The WhatsApp Business Data Transfer Addendum (16 February 2024), filed after
the signature, says Meta's US transfers rest on the EU-US Data Privacy
Framework, not on SCCs. Privacy 3.6 §6 said SCCs for every US transfer, and
SCCs for Meta. Two sentences change in `copy/privacy-3.6.txt`, nothing else:

- §6, first paragraph: "… made under the European Commission's Standard
  Contractual Clauses or the EU-US Data Privacy Framework, as each
  provider's data processing agreement sets out."
- §6, Meta line: "Meta (WhatsApp): the EU-US Data Privacy Framework, under
  WhatsApp's Data Transfer Addendum, which allows Standard Contractual
  Clauses instead."

sha256 of `copy/privacy-3.6.txt`: was `5aa2ffc447bf4543ec74412fe455b60bf439ca708c024d4fdfb0b41797d3ddd3` (as
signed in §7), after this change `b69bf6434e5a939e8f64f80912e6e2fbee2300456b77ce4a0875f996a809c92b`, and after the second change below `2518d96703dfd632d409d6fc84f9729a86958278054992215972ad2417818864`. Confirmed by the founder (below).

**Second change, same day (founder, chat: keep the coach videos).** The
founder wants coach video answers kept: "keep the coach videos permanent …
now I need them". Privacy 3.6 §7 said they are deleted with the Take. It
now says they are kept while the account is open, including after the Take
is deleted, and deleted on request or when the account is closed. They stay
outside training (§4a, "Your coach's videos are not part of it either"):
using them to train a model later needs a new policy version and the
speaker's yes. Fix 7 keeps the private links and drops "deleted with the
Take". sha256 of `copy/privacy-3.6.txt` after both changes: `2518d96703dfd632d409d6fc84f9729a86958278054992215972ad2417818864`.

**Confirmed by the founder, chat, 15 October 2026:** "I confirm both Privacy
3.6 corrections: the transfer lines in section 6 and the coach videos in
section 7." The bytes to publish are `copy/privacy-3.6.txt` with sha256
`2518d96703dfd632d409d6fc84f9729a86958278054992215972ad2417818864`.

