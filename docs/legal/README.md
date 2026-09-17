# Legal compliance artefacts

Opened 2026-09-17. Everything here is **draft pending founder adoption**; two
items additionally need Polish counsel. None of it is legal advice.

| Document | Discharges | Status |
|---|---|---|
| [`DPIA-2026-09-17.md`](DPIA-2026-09-17.md) | GDPR Art 35 · backlog **L-9** | 🟡 Draft — 6 open questions block adoption |
| [`ROPA-ART30.md`](ROPA-ART30.md) | GDPR Art 30 · backlog **L-10** | 🟡 Draft — awaiting founder adoption |
| [`AI-ACT-SCOPING-MEMO.md`](AI-ACT-SCOPING-MEMO.md) | AI Act scope · backlog **L-11** | 🟡 Ready to send to counsel |
| [`COPY-AMENDMENT-PROPOSAL-v1.3.md`](COPY-AMENDMENT-PROPOSAL-v1.3.md) | Privacy/Terms v1.3 · **L-1** | ⛔ Held — LIVE LOOP fence, needs sign-off |
| [`ENGINEERING-BRIEF-GDPR-REMEDIATION.md`](ENGINEERING-BRIEF-GDPR-REMEDIATION.md) | **L-1, L-3, L-4, L-5** | 🟢 Ready to hand to engineering |
| [`EMAILS-TO-SEND.md`](EMAILS-TO-SEND.md) | **L-6**, counsel instruction | 🟢 Ready to send |
| [`../../legal/mlc2-split-consent-v2.json`](../../legal/mlc2-split-consent-v2.json) | Fixes DPIA RISK-1 | ⛔ DRAFT — do not activate |

## Read in this order

1. **DPIA** — the keystone. Every other document is downstream of its risk register.
2. **Engineering brief** — what to build, in order. WP0 first: three queries that rescale the whole assessment.
3. **Emails** — counsel and OpenAI. Both blocking on someone outside the repo.
4. **Copy proposal** — needs a yes/no per amendment.

## The three findings that matter

- 🔴 **RISK-1** — the bundled consent is likely invalid under Art 4(11)/7(4) +
  Recital 43. If invalid it fails for *both* purposes, **including the recording
  itself**, for which Privacy §3 expressly declined Art 6(1)(b). No fallback basis.
- 🔴 **RISK-2** — Privacy §6 and Terms §7 say the voice inference is "opt-in and
  off by default". `services/voice_confidence.py:177` defaults it **on**, and no
  per-user flag exists.
- 🔴 **RISK-3** — `voice_confidence` may be an AI Act emotion recognition system,
  because **Art 3(34) drops the unique-identification limb that GDPR Art 4(14)
  requires**. With live B2B interest, Art 5(1)(f) is in play. Counsel question.

## The one thing not to get wrong

"We do not do voice identification, therefore we are outside the biometric
regime" is **correct under GDPR and wrong under the AI Act.** The two regimes
define biometric data differently. Do not carry the conclusion across.
