# 02 — AI Act Art 3(39) determination

**Instruction:** whether `voice_confidence` is an "emotion recognition system",
and what follows.
**Technical facts:** Document 01. **Your worklist:** Document 11.
**§7 sets out both sides. §9 is left blank for your determination.**

---

## 1. The question

> Is a component that infers a position on a *doubtful↔confident* spectrum from
> seven acoustic features of a speaker's voice an **"emotion recognition system"**
> within the meaning of AI Act Art 3(39)?

Everything else in this pack is downstream of the answer.

---

## 2. The system in one paragraph

Seven acoustic features (pitch range, loudness range, mean pitch, speech rate,
pausing, terminal contour, energy contour), each z-scored **against the
individual speaker's own baseline**, signed, weighted by fixed
literature-derived coefficients, summed, and squashed to a single value in
[-1.0, +1.0]. Not machine-learned. Computed for every recording. Never shown to
the user or to the reviewing coach. Currently not acted on, pending validation.
Full detail: Document 01 §2.

---

## 3. The definitional asymmetry that prompts this instruction

| | GDPR Art 4(14) | AI Act Art 3(34) |
|---|---|---|
| Personal data from specific technical processing | ✓ | ✓ |
| Relating to physical, physiological or behavioural characteristics | ✓ | ✓ |
| **"which allow or confirm the unique identification"** | **✓ required** | **✗ absent** |

My published privacy policy §3 concludes that voice processed to analyse
delivery rather than to identify a speaker is **not** Art 4(14) biometric data,
so Art 9 GDPR is not triggered by the processing itself. I believe that is right
and I am not asking you to revisit it.

**What I am asking is whether the conclusion travels.** If Art 3(34) genuinely
omits the identification limb, then pitch, loudness dynamics, speech rate and
pause structure are biometric data *for AI Act purposes* — and the only
remaining question is whether what we infer from them is an *emotion*.

---

## 4. Art 3(39)

> *"'emotion recognition system' means an AI system for the purpose of
> identifying or inferring emotions or intentions of natural persons on the basis
> of their biometric data."*

Four elements. On my reading three are plainly met and one is contested:

| Element | Met? |
|---|---|
| An AI system | Assumed yes (Art 3(1) — though the composite is fixed arithmetic; see §7.2(f)) |
| For the purpose of identifying or inferring | **Yes** — inference is exactly what it does |
| Of natural persons | Yes |
| **Emotions or intentions** | **⚠️ Contested — this is the question** |
| On the basis of biometric data | Yes **if** §3 is right |

---

## 5. Recital 18

> *"...emotions or intentions such as happiness, sadness, anger, surprise,
> disgust, embarrassment, excitement, shame, contempt, satisfaction and
> amusement. It does not include physical states, such as pain or fatigue...
> nor does it cover the mere detection of readily apparent expressions, gestures
> or movements, unless they are used for identifying or inferring emotions."*

"Confidence" and "doubt" appear in neither the inclusion list nor the exclusions.
Whether the list is indicative or limiting is, I think, load-bearing here.

---

## 6. Why the answer determines the product

I am a sole trader operating unregistered business activity. The branches are
not equivalent inconveniences — they are different businesses:

| Branch | Consequence |
|---|---|
| **Not in scope** | Ordinary GDPR housekeeping. Documents 03-10 proceed as normal remediation |
| **In scope, Art 5(1)(f) engaged** | Prohibited in workplace and education since 2 Feb 2025. I must decline the B2B interest and enforce the consumer fence technically |
| **In scope, Annex III(1)(c)** | High-risk. Arts 9-17, QMS, conformity assessment, CE marking, registration, post-market monitoring. **Not sustainable at my scale — the feature would be removed** |

---

## 7. The arguments, both ways

I have tried to state the case against myself at least as strongly as the case
for. Where I think I am weak I have said so.

### 7.1 For inclusion — the system IS an emotion recognition system

**(a) The construct is named in affective terms in our own source.** The module
documents its output as a spectrum from *doubtful* to *confident*. Not "vocal
projection" or "delivery energy" — doubt and confidence. A reader of the code
would not hesitate to call these states of a person.

**(b) The within-speaker baseline points at the person, not the audio.**
Normalising against *this speaker's own history* makes the output a claim about
how this person sounds relative to their own norm. **This is the strongest point
against me**, and it is in tension with my published explanation that "the
measurements describe a recording, not a person" (Privacy §6). The design does
not fully support the explanation.

**(c) Recital 18's list may be indicative, not exhaustive.** "such as" ordinarily
introduces examples. If so, the absence of "confidence" proves little, and a
purposive reading — the Recital is concerned with inferring inner states from
bodily signals — captures what we do.

**(d) The shadow model is harder to defend than the composite.** A model trained
to reproduce human judgements of whether a speaker sounds assured is, on any
reading, a classifier of a person's apparent state (Document 01 §2.4).

**(e) The Commission's February 2025 guidelines on prohibited practices appear to
read Art 5(1)(f) broadly.** I have not analysed them closely and would value your
view on whether they narrow or widen the position for a case like this.

**(f) "We never show it" is a product control, not a legal one.** Art 3(39) turns
on the system's purpose, not on whether the inference reaches a screen. I do not
think our AC-9 rule helps on scope at all, though it may help on severity.

### 7.2 Against inclusion — the system is NOT an emotion recognition system

**(a) Confidence is an attribute of a performance, not an emotion.** The feature
reads *how a passage was delivered*. A speech coach makes the same judgement by
ear without claiming to know anything about the speaker's inner life. The system
automates an observation about a **speech act**, not a psychological diagnosis.

**(b) Recital 18's list is notably specific and confidence is absent.** Eleven
emotions are named. Assurance, confidence and doubt are not among them, and they
are not obvious omissions — they are exactly the category a drafter concerned
with workplace surveillance might have included had they meant to.

**(c) The exclusions point our way.** Recital 18 excludes physical states and the
mere detection of readily apparent expressions. Speech rate and pause structure
are closer to readily apparent properties of speech than to concealed inner
states.

**(d) No emotion vocabulary is applied to the output.** The system never labels a
recording "nervous" or "anxious". The only named emotions in the product are the
user's own self-report (Document 01 §3).

**(e) Self-directed use with no adverse consequence.** The subject is the sole
user, analysing their own voluntarily-created recording, to improve their own
speech, with no decision taken about them by anyone. The mischief Art 5(1)(f) and
Annex III address — surveillance of the subject by a party with power over them —
is absent.

**(f) The composite may not be an "AI system" at all.** It is a fixed weighted
sum with literature-derived coefficients and no learned parameters. Whether that
meets Art 3(1)'s "infers, from the input it receives, how to generate outputs" is
a real question. **I note it but do not rely on it** — the shadow model at
Document 01 §2.4 plainly is an AI system, so this argument at best splits the two
components rather than clearing the product.

### 7.3 My own working assessment

**More likely in scope than not, but genuinely arguable — I would put it near
60/40 against me.** I would not build on the assumption that we are outside it.
I record this so you know my prior, not to anchor you: **if you think I am wrong
in either direction, that is more useful to me than agreement.**

---

## 8. If in scope — the two sub-questions

### 8.1 Art 5(1)(f) — workplace and education

> *prohibits "the placing on the market, the putting into service for this
> specific purpose, or the use of AI systems to infer emotions of a natural
> person in the areas of workplace and education institutions, except where...
> intended to be put in place or into the market for medical or safety reasons."*

Applicable since 2 February 2025. Art 99(3) ceiling: €35m or 7% of worldwide
turnover.

My position is that I am B2C and that Terms §7 bans employer and institutional
use. **I do not know whether that is enough**, and I have three specific doubts:

1. A contract term is not a technical control. Nothing in the code prevents a
   company buying seats — the restriction exists only in prose.
2. "Placing on the market **for this specific purpose**" may be satisfied by my
   consumer positioning, or the "**use**" limb may bite independently on a
   customer's use regardless of my terms.
3. The coach-assigns-practice flow (Document 01 §4) may engage the *education*
   limb. I genuinely do not know.

**And it is live.** I have inbound B2B interest and cannot answer it until I hear
from you.

### 8.2 Annex III(1)(c) — high-risk otherwise

An emotion recognition system not caught by Art 5 is high-risk under Annex III
point 1(c).

I assume the **Art 6(3) derogation is unavailable** to me, because its final
subparagraph makes any Annex III system always high-risk where it performs
**profiling**, and evaluating delivery across repeated takes appears to be
profiling within Art 4(4) GDPR. **Please confirm or correct that assumption** —
it is the only route out of the high-risk regime that I can see, and I may be
closing it too readily.

⚠️ **Application date.** Annex III obligations were scheduled for 2 August 2026.
I am aware of a Commission "Digital Omnibus" proposal that would have altered the
high-risk timeline. **Please confirm the position as at the date of your opinion
rather than as at the original text** — my sequencing changes by roughly a year
either way, and I have deliberately not assumed an answer anywhere in this pack.

---

## 9. DETERMINATION

*To be completed by counsel.*

### 9.1 Is `voice_confidence` an emotion recognition system within Art 3(39)?

> ☐ **Yes** ☐ **No** ☐ **Arguable — reasoning below**
>
>
> _______________________________________________________________________
>
> _______________________________________________________________________
>
> _______________________________________________________________________

### 9.2 Does Art 3(34) omit the unique-identification limb, such that our acoustic features are biometric data for AI Act purposes?

> ☐ **Yes** ☐ **No** ☐ **Qualified**
>
> _______________________________________________________________________
>
> _______________________________________________________________________

### 9.3 Is the within-speaker baseline (Document 01 §2.2) material to 9.1?

> ☐ **Material** ☐ **Not material** ☐ **Material only in combination**
>
> _______________________________________________________________________

### 9.4 If yes to 9.1 — is Art 5(1)(f) engaged on our facts?

> ☐ **Engaged** ☐ **Not engaged** ☐ **Not engaged, subject to measures below**
>
> Measures required before responding to B2B interest:
>
> _______________________________________________________________________
>
> _______________________________________________________________________

### 9.5 If not prohibited — Annex III(1)(c) high-risk, and from what date?

> ☐ **High-risk** ☐ **Not high-risk** — Art 6(3) derogation ☐ available ☐ foreclosed by profiling
>
> Current application date following the Digital Omnibus process: ______________
>
> _______________________________________________________________________

### 9.6 Would either redesign move us out of scope — and is it legitimate scoping or formal evasion likely to be seen through?

**(a)** Remove the within-speaker baseline, so the read is a property of the
audio segment rather than of the person.
*Cost to me: measurable accuracy loss — the source literature normalises
within-speaker, so this degrades the feature rather than merely renaming it.*

> ☐ **Moves out of scope** ☐ **Does not** ☐ **Helps but insufficient alone**
>
> _______________________________________________________________________

**(b)** Redefine the construct — in its written operational definition and in its
use — to describe delivery properties only, making no claim about the speaker's
state.

> ☐ **Legitimate scoping** ☐ **Formal evasion — would not survive scrutiny**
>
> _______________________________________________________________________

### 9.7 Recommended course

> ☐ **Proceed as is** ☐ **Redesign per 9.6** ☐ **Remove the feature**
> ☐ **Other:** ______________________________________________________
>
> _______________________________________________________________________
>
> _______________________________________________________________________

**Counsel:** _____________________ **Date:** _____________

---

## 10. Follow-on, only if in scope

Not part of the determination — please do not spend time on these until §9 is
settled.

- **Art 50(3)** requires deployers of emotion recognition systems to inform
  persons exposed. Privacy §6 substantially describes the processing already, and
  we have a notice-receipt mechanism that records delivery. Would §6 as written
  discharge it, or is an in-product notice required?
- **Provider vs deployer.** I build and operate it, so I assume I am both. Any
  consequence I am missing?
- **AI literacy (Art 4).** Applicable since Feb 2025 to providers and deployers.
  What does it require of a sole operator with no staff?
