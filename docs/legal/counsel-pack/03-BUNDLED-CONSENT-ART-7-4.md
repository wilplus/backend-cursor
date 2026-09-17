# 03 — Bundled consent: Art 7(4) analysis

**Triage item.** Unlike Document 02 this concerns my **published, currently-live**
terms. I believe I have a defect. I want it confirmed or corrected before I ship
a remediation that touches live consent flows.

---

## 1. The consent as it stands

Policy artifact `mlc2-bundled-consent-v1`, active from 28 August 2026, reproduced
in full at Document 07. Its operative configuration:

```
  purposes:             [ personalized_coaching, pooled_model_improvement ]
  bundled_ui:           true
  required_for_service: true
  article_6_basis:      6(1)(a)
  article_9_treatment:  9(2)(a)_when_special_category
```

The onboarding copy the user actually sees:

> *"WillpowerLab uses your practice data for two connected purposes: **1.
> Personalized coaching** ... **2. Improving WillpowerLab's shared models** — We
> may use the same information to evaluate, train and improve models used by
> WillpowerLab for you and other users. Your data may be included in datasets
> together with data from other users.*
>
> ***Using WillpowerLab requires participation in both forms of learning. If you
> do not agree, you cannot use the recording and coaching service.***"

One checkbox, not pre-ticked, covering both purposes. Privacy Policy §5 and §11
both confirm in terms that withdrawing ends access to recording and coaching.

---

## 2. ⚠️ Scale — please read before sizing the urgency

**I do not yet have a verified figure for how many users accepted this consent.**

My working understanding is that the service has **no active user base beyond
myself and a small number of test accounts**, in which case this is a
**pre-launch correction rather than a live exposure**. But I have not verified
it against the database, and my covering email to you may have implied otherwise.

**I am running the query and will confirm the number separately.** Please do not
size your response — or your urgency — from anything other than that figure.

The analysis below is unaffected either way. Only the remediation posture changes:

| If accepted by | Posture |
|---|---|
| Nobody | Fix before launch. No affected subjects, no notification question |
| A handful of test accounts | Fix and re-consent. Trivial |
| Real users at any scale | Fix, re-consent, pause the affected processing, and we should discuss whether anything further is owed |

---

## 3. Why I think it is invalid

### 3.1 Art 7(4) — conditionality

> *"...utmost account shall be taken of whether... the performance of a contract
> ... is conditional on consent to the processing of personal data that is not
> necessary for the performance of that contract."*

Pooled model improvement is **not necessary** to coach an individual user. The
service demonstrably functions for that user without their data ever entering a
training set — nothing in the coaching pipeline depends on it. Yet performance of
the contract is expressly made conditional on it, in the copy quoted above.

### 3.2 Recital 43 — two independent limbs, and I appear to fail both

> *"Consent is presumed not to be freely given if it does not allow separate
> consent to be given to different personal data processing operations despite it
> being appropriate in the individual case, or if the performance of a contract...
> is made dependent on the consent despite such consent not being not necessary
> for such performance."*

**Limb 1 — no separate consent.** One checkbox, two distinct purposes. Separate
consent is plainly appropriate here: one purpose benefits the user, the other
benefits me.

**Limb 2 — conditionality.** As §3.1.

### 3.3 Art 4(11) — freely given

If the only way to use the product is to accept both, the second is not a choice.

### 3.4 Art 9(2)(a) — explicit and specific

The artifact claims 9(2)(a) treatment where special-category data arises. Explicit
consent must be specific to the processing. **A single checkbox spanning two
purposes cannot be specific to either.**

---

## 4. The consequence I most want checked

This is the reason the document exists, and it is not the training purpose.

**If the bundle is invalid, the consent fails as a whole — for both purposes,
including the recording itself.**

And my published Privacy Policy §3 says, in terms:

> *"Performance of a contract (Article 6(1)(b)). We use this basis for account
> administration, purchases and other non-recording contractual operations."*

I **expressly excluded** recording from the Art 6(1)(b) basis, because at the
time consent seemed the more protective choice. The effect is that **if consent
falls, there is no fallback lawful basis for the core operation of the service.**

I would like to know:

1. Whether the bundle does in fact taint the coaching consent as well as the
   training consent, or whether the two can be severed so that coaching survives.
2. Whether my §3 drafting genuinely forecloses reliance on Art 6(1)(b), or
   whether I can rely on it notwithstanding what the policy says — the basis is a
   matter of law, but the statement is a matter of transparency, and I do not know
   how those interact.
3. Whether, on the facts, processing carried out under the defective consent was
   unlawful, or merely inadequately documented.

---

## 5. The remediation I have drafted (do not assume it is right)

`mlc2-split-consent-v2` (Document 07). Two independent grants:

| Grant | Basis | Required? | Refusal costs |
|---|---|---|---|
| **Recording and coaching** | **Art 6(1)(b)** — re-based from consent | Yes — it is the service | Cannot use the product |
| **Pooled model improvement** | **Art 6(1)(a)** | **No** | **Nothing. Full access either way** |

Plus: Art 9(2)(a) explicit consent retained as a cautious overlay for
special-category content a user may incidentally disclose while practising.

**My reasoning for re-basing recording on 6(1)(b):** recording is the contracted
service, not an optional extra. Presenting a mandatory operation as a choice is
itself misleading, and a consent that can be withdrawn while the contract
continues is an unstable basis for the thing the contract is *for*.

**Three things I want tested before I ship this:**

1. **Is 6(1)(b) right for recording?** I find it more honest than consent, but I
   am aware that controllers reach for "necessary for the contract" too readily,
   and that the EDPB has been sceptical of it for anything beyond the core
   service. Recording *is* the core service here — but I would rather you said so.
2. **Does the Art 9(2)(a) overlay survive** being attached to a 6(1)(b) grant,
   given that Art 9 consent must be explicit?
3. **Is "no detriment on refusal" enough** to make the training consent freely
   given, or does anything else need to change?

---

## 6. Related defect — the same processing, described two different ways

Flagged here because it touches the same consent and the same documents.

Privacy §6 and Terms §7 both state:

> *"This inference is opt-in and off by default."*

**That is not what the system does.** The delivery-signal inference (Document 01
§2) is computed for every take by default — `services/voice_confidence.py:177`
defaults the switch to on, and it is a server configuration value, not a per-user
consent flag. No per-user opt-in for it exists.

It also contradicts §3 and §5 of the same policy, which say the consent covering
that inference is **required** to use the service. The inference cannot be both
mandatory and opt-in.

I read this as an Art 5(1)(a) transparency problem and an Art 13 accuracy
problem, and I intend to amend the copy to describe what the system actually
does. **Is amending the copy sufficient, or is anything owed to users who were
told otherwise?**

---

## 7. What I am asking

Consolidated in Document 11, repeated here for convenience:

> **Q3.1** Is the bundled consent invalid under Art 7(4) / Art 4(11) / Recital 43?
>
> **Q3.2** If so, does invalidity extend to the coaching purpose, leaving
> recording without a lawful basis — or can the purposes be severed?
>
> **Q3.3** Does Privacy §3's express exclusion of Art 6(1)(b) for recording
> prevent me relying on it, now or retrospectively?
>
> **Q3.4** Is the split at §5, including the re-basing on 6(1)(b), a sound
> remediation?
>
> **Q3.5** What is owed to users who accepted the defective consent — re-consent,
> notification, anything more? *(Answer may be "nothing, there are none" —
> pending §2.)*
>
> **Q3.6** Is amending the §6 copy sufficient for the defect at §6 above?
