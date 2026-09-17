# Vendor actions — who to contact, for what, with the text

Five vendors, six actions. None of them cost money. The OpenAI ZDR request is
the one with a lead time, so start it first.

---

## 1. OpenAI — TWO separate things

These are different routes and people conflate them. **If the dashboard route
below cannot be found, skip the hunt and email `support@openai.com` cc
`privacy@openai.com` asking for both the DPA link and the retention answer in
one message.** That is faster than navigating their settings and it creates a
written record, which is what document 06 actually needs.

### 1a. The DPA — self-serve, five minutes

Platform dashboard → Settings → Organization → there is a self-serve Data
Processing Addendum you complete and e-sign. It incorporates Standard
Contractual Clauses and their sub-processor list. Save the executed PDF.

### 1b. Zero Data Retention — an application, not a setting

**What the public documentation says**, as of 2026-09-17:

- API inputs and outputs are retained up to **30 days** for abuse monitoring by
  default, then deleted.
- **ZDR is available for `/v1/audio/transcriptions`** — it is on the supported
  endpoint list — but it is **subject to prior approval** and additional terms.
- Sources conflict on whether the transcription endpoint already has reduced or
  zero default retention. **Do not assume.** That conflict is exactly why this
  has to be confirmed in writing rather than read off a blog.
- Once approved, an org admin enables it under Settings → Organization → Data
  controls, at organisation or project level.

**Route:** the contact-sales flow at `openai.com/contact-sales`, or your account
team if you have one. Not a support ticket.

**Text to send:**

> We operate a voice-based presentation coaching product for consumers in the EU
> and the US. User audio is sent to `/v1/audio/transcriptions`, and bounded
> transcript text to a chat model for generation. We are finalising our GDPR
> record of processing and a published retention schedule, and we serve Illinois,
> so our retention statements have to be exact rather than approximate.
>
> Three things, in writing please:
>
> 1. What is the current default retention for audio submitted to
>    `/v1/audio/transcriptions`, and for the transcript text subsequently sent to
>    a chat completion? Please confirm each separately — we have seen conflicting
>    public descriptions of the audio endpoint.
> 2. We would like to apply for Zero Data Retention on both endpoints. What are
>    the eligibility criteria and the additional terms, and what is the typical
>    lead time to approval?
> 3. If ZDR is not available to us, what is the exact wording you would consider
>    accurate for us to publish about how long you hold end-user audio?
>
> We have executed your standard DPA. This is about what we can truthfully tell
> our users.

**Why it blocks:** document 06 cannot be signed without the answer, and document
06 gates the retention rules, which gate policy registration. It is the top of
the critical path.

---

## 2. Railway — self-serve, three minutes

**`railway.com/legal/dpa`** — execute it there directly. (An earlier draft of
this document said Railway was not self-serve and would be the slowest of the
five. That was wrong.)

Then take two documents from **`trust.railway.com`**: the current sub-processor
list — Railway runs on Google Cloud, with Cloudflare and Stripe underneath, and
counsel will want to see who sits behind the name in Privacy §5 — and whatever
they publish on EU-to-US transfers. Railway's primary processing is in the
United States, so that is the transfer mechanism for the hosting layer.

## 2b. Where a vendor has no self-serve DPA

Text that works for any of them:

> We are a customer processing personal data of EU and US individuals on your
> platform. Please provide your Data Processing Agreement for signature,
> together with your current sub-processor list and the transfer mechanism you
> rely on for EU-to-US transfers (Data Privacy Framework certification or
> Standard Contractual Clauses). If you are DPF-certified, please confirm the
> certification name we should reference.

## 3. Cloudflare

Their DPA is usually incorporated by reference into the standard self-serve
subscription terms, so there may be nothing to sign. Confirm which applies to
your account, download the current version, and file it. A DPA you cannot
produce is one you do not have.

## 4. Supabase — one extra question

Ask the DPA question above, and also: **which region is our project in?** If it
is an EU region, the transfer analysis for our database gets materially simpler
and the Privacy Policy §6 wording shrinks.

## 5. Merchant of record — NOT a DPA

Do not send them the DPA text above. A merchant of record contracts with the
user as seller, which makes them an independent controller for the purchase, not
our processor. Article 28 is the wrong instrument.

What to ask for instead: their standard reseller/MoR agreement, confirmation of
how they characterise the data relationship, and the URL of the privacy policy
we should point our users at. Counsel confirms the characterisation and says
what, if anything, we need to sign — see document 01 §2.

---

## Checklist

| Vendor | Action | Route | Status |
|---|---|---|---|
| OpenAI | DPA | self-serve dashboard | ☐ |
| OpenAI | ZDR + retention answer in writing | contact-sales | ☐ ← blocks doc 06 |
| Railway | DPA + sub-processors + transfers | railway.com/legal/dpa (self-serve) | ☐ |
| Supabase | DPA + project region | dashboard/legal | ☐ |
| Cloudflare | Confirm DPA applies, file a copy | account terms | ☐ |
| Email provider | DPA | provider | ☐ |
| Merchant of record | MoR agreement, NOT a DPA | provider | ☐ |

Every executed document gets filed with its date and version. Document 01 §2
lists them, and counsel will ask to see them before signing.
