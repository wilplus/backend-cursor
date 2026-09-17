# Emails to send

Two, both ready. Review, adjust the bracketed fields, send.

---

## EMAIL 1 — to your Polish counsel 🔴 send first

**Attach:** the twelve files in `docs/legal/counsel-pack/` (00 through 11).
**⚠️ Before sending:** run the user-count query (engineering brief WP0) — one
sentence below depends on the answer.

> **Subject:** WillpowerLab — AI Act + GDPR instruction pack. One determination needed.
>
> Hi [name],
>
> Attached is an instruction pack for a consumer speech-coaching app I operate as
> a sole trader in Poland. Eleven documents plus a cover note — please read
> 00-READ-THIS-FIRST first, it's one page and it orients the rest.
>
> The core question is whether one component of the product is an "emotion
> recognition system" under AI Act Art 3(39). Document 02 sets out both sides at
> §7 and leaves §9 blank for your determination. Everything else waits on it.
>
> The short version of my concern: **AI Act Art 3(34) defines "biometric data"
> without the unique-identification limb that GDPR Art 4(14) requires.** My
> published policy concludes we are outside the GDPR biometric regime because we
> do not identify anyone, and I think that is right — but I do not think the
> conclusion carries across to the AI Act, and if it does not then Art 5(1)(f)
> and Annex III(1)(c) both come into view. I have live inbound B2B interest I
> cannot answer until I know.
>
> One thing I'd like triaged ahead of the rest: my published v1.2 terms rely on a
> bundled consent that I believe is invalid under Art 7(4). Document 03 sets it
> out. The consequence I most want checked is not the training purpose but the
> collateral one — if the bundle falls, consent fails for *both* purposes
> including the recording itself, and my policy §3 expressly declines Art 6(1)(b)
> for recording.
>
> ⚠️ PICK ONE — delete the other:
>
> **[If the query returns ~0 real users]**
> > On scale: I should be straight with you, because it affects how much of your
> > time this deserves. I have now verified that **no real users have accepted
> > that consent** — the service is pre-launch beyond my own test accounts. So
> > this is a defect to fix before anyone is affected, not a live exposure. I'd
> > still like it confirmed, because the remediation is half-built and I don't
> > want to ship a change to live consent flows on my own reading.
>
> **[If the query returns real users]**
> > On scale: **[N] users** accepted that consent between [date] and today. That
> > makes it a current exposure rather than a future one, and Document 03 §7 asks
> > what is owed to them.
>
> The documents were drafted by my engineering side with AI assistance, working
> from the source code. Nothing in them is legal advice and nothing has been
> reviewed by a lawyer — that's what I'm asking you for. The technical statements
> in Document 01 are verified against source and carry file references; the legal
> characterisations throughout are my working assumptions, stated confidently to
> save your time rather than because they're settled. I can give you repository
> access if the technical sections need checking.
>
> Two things I'd rather hear early than late. If the answer to Document 02 is
> that we fall into the high-risk regime, please tell me the feature has to go
> rather than setting out what compliance would require — at my scale that isn't
> something I can sustain. And if my Art 7(4) analysis is simply wrong, say so;
> I'd rather stop than ship an unnecessary change.
>
> Document 11 is the consolidated question schedule, tiered. If you answer only
> Tier 1, the instruction has served its purpose.
>
> Could you let me know your availability and an estimate?
>
> Artur

### What I changed from your draft, and why

| Your line | Change | Why |
|---|---|---|
| "affecting users who already accepted" | **Split into two variants, pick after the query** | It contradicts what you told me — *"there are no new users."* Asserting live affected users to a lawyer sets their urgency and their bill. If it's wrong you pay for triage you don't need; if it's right and you'd said otherwise, worse |
| — | **Added the Art 3(34) sentence** | Your draft says "the core question is whether X" without saying *why it's a question*. One sentence lets them start thinking before they open an attachment |
| — | **Added the Art 6(1)(b) collateral point** | Without it, "bundled consent invalid" reads as a training-data problem. The real point is that it takes the recording basis down with it |
| "Nothing in them is legal advice" | **Kept, and sharpened the provenance split** | Good instinct. Made explicit which parts are verified fact vs. your assumptions — it tells them where to spend attention |
| — | **Added the commercial constraint** | Otherwise you risk a thorough, expensive compliance roadmap for a regime you've already decided you can't sustain |
| — | **Added the Tier 1 pointer** | Caps the engagement without capping the advice |

Your structure was better than mine and the pack now matches it.

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
