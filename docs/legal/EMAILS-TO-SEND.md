# Emails to send

Two, both ready. Review, adjust the bracketed fields, send.

---

## EMAIL 1 — to your Polish counsel 🔴 send first

**To:** [your lawyer]
**Attach:** `docs/legal/AI-ACT-SCOPING-MEMO.md` (convert to PDF or paste inline)
**Optionally attach:** `DPIA-2026-09-17.md`, `ROPA-ART30.md`

> **Subject:** AI Act scoping opinion — voice-based confidence feature (WillpowerLab)
>
> Dear [Name],
>
> I need a written scoping opinion on one narrow but urgent question, and I have
> prepared a memo so that you are not paying to discover the facts.
>
> WillpowerLab is my speech-coaching application. One internal component reads
> seven acoustic features from a user's recording — pitch range, loudness range,
> mean pitch, speech rate, pausing, terminal contour and energy contour — and
> produces a single value placing the moment on a spectrum from *doubtful* to
> *confident*. The value is never shown to the user. It is used internally to help
> select which moments become coaching feedback.
>
> **My question is whether that is an "emotion recognition system" under Art 3(39)
> of the AI Act, and what follows if it is.**
>
> I have become concerned because the AI Act's definition of biometric data at
> Art 3(34) omits the "unique identification" limb that GDPR Art 4(14) requires.
> Our privacy policy correctly concludes we are outside the GDPR biometric regime
> because we do not identify anyone — but I do not think that conclusion travels
> to the AI Act, and if it does not, then Art 5(1)(f) and Annex III(1)(c) both come
> into view.
>
> This has become time-sensitive: **we have live inbound B2B interest, and
> Art 5(1)(f) prohibits emotion recognition in the workplace.** I need to know
> whether I can respond to it at all. Our Terms already ban employer and
> educational use, but I assume a contract term alone does not discharge a
> prohibition.
>
> The attached memo sets out the technical facts precisely, gives the arguments I
> can see in both directions, and poses four specific questions (§6). I would also
> value your view on whether either of two design changes — removing the
> speaker-relative normalisation, or redefining the construct so it describes
> delivery rather than the speaker — would be a legitimate scoping change or
> would be seen as formal evasion.
>
> One point I would ask you to confirm rather than assume: the current application
> date for the Annex III high-risk obligations following the Digital Omnibus
> process. My sequencing changes by about a year depending on the answer.
>
> For context on scale: I operate as a sole trader under *działalność
> nieewidencjonowana*, so if the answer is that we fall into the high-risk regime,
> my realistic options are to redesign the feature out of scope or remove it —
> not to build a conformity apparatus. Please factor that into your advice rather
> than treating full compliance as the default recommendation.
>
> Could you let me know your availability and an estimate? I would also like to
> raise, separately and if it is within your scope, a draft Art 35 DPIA and an
> Art 30 record that I would like reviewed before I adopt them.
>
> Best regards,
> Artur Willoński
> WillpowerLab · contact@willpowerlab.com

---

## EMAIL 2 — to OpenAI, on zero data retention 🟠 send this week

**Why it matters.** Privacy §5 and §9 both tell your users that audio and
transcripts go to OpenAI under **zero data retention**, and that inputs are not
used to train foundation models. **ZDR is not a default.** It is granted per
organisation, on application, and it does not apply to every endpoint. If it is
not actually in force on your org, your published policy is false and OpenAI's
standard abuse-monitoring retention applies to every recording and transcript you
have ever sent. That is DPIA RISK-8.

**Where to send it.** I cannot verify current routing from here, so use whichever
of these applies to your account, in order:
1. The **support widget inside platform.openai.com** (fastest; routes to the team that can actually answer).
2. **Your account/sales contact**, if you have one — ZDR is normally granted through that route.
3. `support@openai.com` as a fallback.

Also download the DPA directly from **platform.openai.com → Settings →
Organization → Data processing agreement** while you are in there — that closes
one row of L-6 on its own.

> **Subject:** Confirmation of Zero Data Retention status and DPA — [your org name / org ID]
>
> Hello,
>
> I operate a speech-coaching application in the EU and send both audio and
> transcript content to the OpenAI API. I am completing a GDPR Article 30 record
> and an Article 35 DPIA, and my published privacy policy states that this
> processing occurs under zero data retention terms.
>
> I need to confirm that in writing. Could you please tell me:
>
> 1. Whether **Zero Data Retention is currently active** on my organisation
>    (`[org ID]`), and from what date.
> 2. **Which endpoints and models it covers** — specifically the transcription
>    endpoints and the chat/completions endpoints, since I use both.
> 3. Whether **any content is retained for abuse monitoring** notwithstanding ZDR,
>    and if so for how long and in which region.
> 4. Confirmation that **API inputs and outputs are not used to train OpenAI
>    models** under my current agreement.
> 5. Where I can download the **executed Data Processing Agreement**, and which
>    **Standard Contractual Clauses module** applies to the EU-to-US transfer.
>
> If ZDR is not currently active on my organisation, please treat this as an
> application for it and tell me what you need from me.
>
> I would be grateful for a written response I can retain as a compliance record.
>
> Best regards,
> Artur Willoński
> WillpowerLab · contact@willpowerlab.com

---

## Not an email, but do it the same hour 🟡

Download and file the click-through DPA for each remaining sub-processor. All
publish one; none requires correspondence. ~30 minutes total.

- **Supabase** — dashboard → Organization → Legal/Compliance
- **Railway** — account → Legal, or via support
- **Vercel** — dashboard → Settings → Legal → DPA
- **Cloudflare** — dashboard → Manage Account → Configurations → Compliance
- **Stripe** — dashboard → Settings → Legal/Compliance
- **Sentry** — Organization Settings → Legal & Compliance
- **Resend** — account settings, or via support

File them all in one folder with the date retrieved. That is what closes L-6, and
it is what a regulator asks to see rather than what your policy asserts.
