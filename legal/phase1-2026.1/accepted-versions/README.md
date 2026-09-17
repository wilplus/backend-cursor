# The published Terms and Privacy sequence, recovered from git

**The `.txt` files are the record. This file is the provenance for them, kept
separate so nothing in a text file is anything but the text.**

---

## ⚠️ The document 26 people accepted is NOT v1.0

The task that produced this folder asked for v1.0 (`01026bf0`, 2026-07-24) as
"the only document anyone has actually accepted". **It is not.** Checking the
dates before extracting:

| | |
|---|---|
| First acceptance in `user_consents` | **2026-05-08** |
| Last acceptance | **2026-07-16** |
| `01026bf0` "publish … v1.0" committed | **2026-07-24** |

**Every one of the 26 acceptances predates that commit** — the last by eight
days. Nobody has ever accepted the text in `01026bf0`.

The legal pages first shipped in **`3202b5a1`, 2026-05-07** — the day before the
first acceptance — and that text stood unchanged until 24 July. The 6 June
rebrand (`9815b7a2`) touched both files but changed styling only; the extracted
text is byte-identical across it. **So `3202b5a1` is the text in force for the
entire acceptance window, and it is what those 26 people agreed to.**

### And it was marked as placeholder copy

`3202b5a1`'s own source docstring, above the component:

> `TODO(content): swap the placeholder copy below for the legally-reviewed`
> `Terms of Use text once it's finalised.`

It is ~1 KB. Titled **"Terms of Use"**, branded **"Willab"**. For comparison:

| | Terms | Privacy |
|---|---|---|
| **As published 2026-05-07 (accepted by 26 users)** | **1,052 chars** | **865 chars** |
| v1.0 (2026-07-24, accepted by nobody) | 7,026 | 9,560 |
| v1.1 (2026-08-13, accepted by nobody) | 12,423 | 15,273 |
| v1.2 (2026-08-28, accepted by nobody) | 12,445 | 15,555 |

Engineering states the facts and stops there. What it means for the basis of
processing is counsel's, and it is question Q-E in
`09-counsel-cover-note.md`.

---

## Provenance

| File | Commit | Commit date | Accepted by | sha256 |
|---|---|---|---|---|
| `terms-as-published-2026-05-07.txt` | `3202b5a1` | 2026-05-07 | **26 users, 8 May – 16 Jul 2026** | `d228641e737e97f0a521cad3bb06319b2ab7c01af0e9483654ad5b44d8719ae2` |
| `privacy-as-published-2026-05-07.txt` | `3202b5a1` | 2026-05-07 | **26 users, same window** | `f6ea2f6ac7cb8ed312cee930584b7aed138157642dfa595f042c7488e6ed4030` |
| `terms-v1.0.txt` | `01026bf0` | 2026-07-24 | nobody | `75e0bf3db04f5986bcdf26bf6b0b6bc4b2794c1d1aff430c8ea0dce246b4ff6d` |
| `privacy-v1.0.txt` | `01026bf0` | 2026-07-24 | nobody | `f37cd58cdde8d15740949f41e79eea1ab3babd86390dd65965562c1ecb9098e9` |
| `terms-v1.1.txt` | `f97ad632` | 2026-08-13 | nobody | `bae6dc001a95a1c223d10ac08fb0845077af7373eb9c87ba103cd8079ae4f9c1` |
| `privacy-v1.1.txt` | `f97ad632` | 2026-08-13 | nobody | `3f5a0ab40b7b7c147e94bd947f5c92b4cd89504246b616c8dc1db9934fc51406` |
| `terms-v1.2.txt` | `7a46c279` | 2026-08-28 | nobody | `d2e2a7bd38e40937679f595bb75c562c8beb9b990c7d85ad439d4cafe5cf2fa4` |
| `privacy-v1.2.txt` | `7a46c279` | 2026-08-28 | nobody | `3f1e1709ef19069244df2d6564faf4b59623d58f74cec84da3713c624d28223a` |

Source in every case: `src/app/terms/page.tsx` and `src/app/privacy/page.tsx`
in `wilplus/frontend-cursor`, at the commit named.

**A note on v1.0's own dates.** It was committed 2026-07-24 and its copy states
an effective date of 23 July 2026 — after the last acceptance either way.

**A note on v1.2.** `page.tsx` has changed twice since `7a46c279`: the
policy-record render wrapper (#384, #385) and the correction of six false
statements (`8f3e51d7`). `7a46c279` is the text as published on 28 August and
is the right snapshot for this record; the corrected text is a different
document with a different date.

---

## How the text was recovered, exactly

The pages are React components, so the text had to be extracted from JSX rather
than copied. The extraction was one-off and is described here so it can be
repeated or challenged.

**Removed:** JSX tags; attributes; `{/* … */}` authoring comments; the
`import`/`metadata` preamble and the authoring docstring, none of which a user
saw.

**Preserved:** every text node, in document order. Block tags (`h1`–`h6`, `p`,
`li`, `tr`, `div`, `section`, `header`) became line breaks; table cells became
` | `; `{" "}` became a space; entities were decoded.

**Three normalisations, each restoring fidelity rather than editing content:**

1. **Space before punctuation removed.** `<Link>Privacy Policy</Link>` followed
   by `.` on the next source line renders as "Privacy Policy." — JSX strips the
   newline. Leaving " ." would misreport what users saw.
2. **Leading "Back home" dropped.** Site navigation, not part of the agreement.
3. **`{lastUpdated}` resolved to its literal value**, `"May 7, 2026"`, in the
   2026-05-07 files only. It is a `const` two lines above the JSX; leaving the
   token unresolved would have left a placeholder in an evidence file.

**What was checked:** the extractor reports any `{expression}` it cannot
evaluate, so interpolated content cannot vanish silently. It flagged
`{lastUpdated}` on the May files — which is how normalisation 3 came to be
applied deliberately rather than missed — and reported **none** on the other
six. It also refused outright on the May files' component shape rather than
writing an empty file, which is how the whole dating error surfaced.

**These files must not be edited.** They are evidence of what was published. A
correction is a new file at a new version, never a change here.
