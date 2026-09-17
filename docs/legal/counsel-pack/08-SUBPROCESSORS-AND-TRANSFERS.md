# 08 — Sub-processors and international transfers

**Status: my published policy asserts more than I have verified.** That is the
finding, and it is why this document exists.

---

## 1. What Privacy §9 tells users

> *"We use carefully selected third-party service providers ('sub-processors')
> who process personal data on our behalf **under written Data Processing
> Agreements (DPAs)**. Where a sub-processor transfers data outside the European
> Economic Area (EEA), the transfer is governed by appropriate safeguards,
> **primarily the European Commission's Standard Contractual Clauses (SCCs)** and,
> where relevant, supplementary measures."*

And Privacy §5 tells users:

> *"Your Voice Data and transcripts are sent to OpenAI's developer API for
> analysis **under a commercial API agreement providing for zero data
> retention**, under which API inputs and outputs are not used to train OpenAI's
> foundation models."*

---

## 2. What I have actually verified

**Nothing.** Every row below is an assertion in the published policy that I have
not confirmed against an executed document.

| Sub-processor | Purpose | Location | Asserted safeguard | Verified |
|---|---|---|---|---|
| Supabase | Database, auth, file storage | EU region | DPA | ⛔ |
| Railway | Backend hosting | — | DPA + SCCs | ⛔ |
| Vercel | Web hosting | — | DPA + SCCs | ⛔ |
| Cloudflare R2 | **Audio object storage** | — | DPA + SCCs | ⛔ |
| **OpenAI** | **Transcription and text analysis** | **United States** | **DPA + SCCs + zero data retention** | ⛔ |
| Stripe | Payments | — | DPA + SCCs | ⛔ |
| Sentry | Error monitoring | — | DPA + SCCs | ⛔ |
| Resend | Transactional email | — | DPA + SCCs | ⛔ |
| Coaches (non-operator) | Human review | EU presumed | Written DPA | ⛔ |

I am remediating this by obtaining and filing each DPA. Most are click-through
documents available from the provider's dashboard. **I raise it with you because
an unverified assertion in a published privacy policy is itself a statement to
data subjects, and I would like to know what follows if one of them turns out to
be wrong.**

---

## 3. The one I am most concerned about

**OpenAI zero data retention.**

ZDR is **not a default**. My understanding is that it is granted per
organisation, on application, and does not necessarily cover every endpoint.
I have asserted it in a published policy without confirming it is active on my
account.

**If it is not in force**, then:

- Privacy §5 is false as to a material matter.
- Standard abuse-monitoring retention would apply to **every recording and every
  transcript I have ever sent** — which is all of the voice data in the product.
- The transfer picture changes, because content is then retained in the US rather
  than transiting.

I have written to OpenAI to confirm status, endpoint coverage, abuse-monitoring
retention, and the SCC module. **I will tell you the answer.** I flag it now
because if the answer is bad it is likely the most consequential factual
correction in this pack.

---

## 4. A methodological caution I would pass on

My sub-processor list was originally assembled by auditing the repository.
**Vercel was missing** — because a codebase never names its own host. It
surfaced only when Vercel ran the CI checks on an unrelated pull request.

I mention it because it means **this list may still be incomplete**, and I do not
want you to treat it as exhaustive. The next pass reads the Vercel and Supabase
dashboards, DNS records, and the per-service environment variables rather than
the source tree.

---

## 5. Questions

> **Q8.1** If a DPA asserted in a published privacy policy turns out not to be in
> place, what is the exposure — and is anything owed to users beyond correcting
> the policy?
>
> **Q8.2** Specifically on OpenAI: if ZDR is not active, what follows for
> (a) the accuracy of Privacy §5, (b) the lawfulness of the transfers already
> made, and (c) anything I need to do now?
>
> **Q8.3** Do I need a transfer impact assessment for each non-EEA recipient at
> this scale, or is reliance on the provider's SCCs and published TIA sufficient?
>
> **Q8.4** The coach relationship: where a coach is not me, are they a processor
> under Art 28 or a separate controller? The published policy says processor and
> promises a written DPA. Is that right, and what must the DPA contain?
