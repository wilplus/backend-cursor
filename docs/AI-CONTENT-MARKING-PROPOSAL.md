# Marking AI-generated output — mechanism proposal (Article 50(2))

**Status: BUILT 2026-09-19, except one decision — see the box below.** This
was written as a proposal, and it is kept as written rather than rewritten into
a description, because what it got right and wrong is the useful part of the
record.

> **What shipped, against this proposal:**
> - §2 Layer A — **done** for DOCX (core properties) and PDF (XMP packet
>   referenced from the catalogue + DocInfo). §1 path 4, the JSON data export,
>   was read through as §5 asked and carries **no** Article 50 content:
>   `export_authorization_evidence` returns receipt ids, timestamps and request
>   states, nothing generated.
> - §2 Layer B — **half done.** The `text/html` flavour ships. The
>   `text/plain` trailing marker line that §3 recommends as option 1 **did
>   not**, and that disagreement is live: see
>   `legal/phase1-2026.1/03-article-50-assessment` §3, which records both
>   positions rather than picking one. **Founder call.**
> - §6 visible label — **done**, wording closest to candidate B, taken from
>   `copy/ai-notice-1.0.txt` so the surface and the notice share one vocabulary.
> - §4 C2PA — still not proposed, and the shared-assertion module exists so it
>   can be added beside this rather than replacing it.
> - §1 got the export inventory right and it was worth having: an
>   implementation that had only looked at the code would have marked two paths
>   and missed the hand-assembled PDF exporter entirely.

Task 5 of the Phase-1 compliance brief asks for the mechanism to be proposed
before it is implemented, because the wrong choice here is expensive to
reverse: a marking scheme that ships into users' exported files cannot be
quietly changed afterwards without invalidating every file already in the
world.

Source: `legal/phase1-2026.1/03-article-50-assessment-v1.0-DRAFT.md` §3 and §6
gap 1.

> Providers of AI systems […] generating synthetic audio, image, video or text
> content, shall ensure the outputs of the AI system are marked in a
> machine-readable format and detectable as artificially generated or
> manipulated.

Two obligations, and the assessment is explicit that they are not
interchangeable: a **visible label** on the surface, **and** a
**machine-readable marking** on anything leaving the product. Satisfying one
does not satisfy the other.

---

## 1. What actually leaves the product

This is the part that had to be established before proposing anything. Grepping
for every path by which Ideal Text or Manager Feedback reaches a file or another
application gives exactly four, and they have nothing in common technically:

| # | Path | Code | Format | Marking difficulty |
|---|---|---|---|---|
| 1 | Copy to clipboard | `src/components/willab/IdealTextOverlay.tsx:924` — `navigator.clipboard.writeText(stripRichMarkers(displayText))` | `text/plain` | **Hard** — see §3 |
| 2 | Download as PDF | `src/lib/willab/presentationPdf.ts` → `pdfFromCanvases` | hand-written PDF, pages are rasterised canvases | Medium |
| 3 | Download as DOCX | `src/lib/willab/presentationDocx.ts` → `docx@9.7.1` `Packer.toBlob` | OOXML | **Easy** |
| 4 | GDPR data export | `/v2/processing-authorization/data-export` → `export_authorization_evidence` | JSON | Easy, and see §5 |

Path 2 is worth reading twice. The PDF is **not** produced by a PDF library —
`pdfFromCanvases` assembles the file itself from rendered canvases. There is no
`setMetadata()` to call; the XMP packet has to be written into the object
structure by hand. That is the single largest piece of work in this proposal,
and it exists only because the exporter was hand-rolled.

## 2. Recommended mechanism

**Two layers, deliberately.** A standards-track marking that survives into the
wider ecosystem, and a plain one that survives naive copy-paste. Neither alone
covers both, and the regulation asks for detectability, not for elegance.

### Layer A — per-format embedded metadata (the machine-readable obligation)

One shared assertion, expressed in whatever each format supports natively:

```
generator      : WillpowerLab Ideal Text
ai_generated   : true
generated_by   : machine
policy_version : <the active processing policy version>
generated_at   : <ISO-8601 UTC>
```

- **DOCX** — `docx` already accepts core properties (`creator` and `title` are
  set today at `presentationDocx.ts:130`). Add `description` carrying the
  assertion, and a `docProps/custom.xml` custom-properties part for the fields.
  Half a day.
- **PDF** — an XMP metadata stream (`/Type /Metadata /Subtype /XML`) referenced
  from the catalogue, plus the DocInfo dictionary as a fallback for readers that
  ignore XMP. Writing XMP into a hand-assembled PDF is the real cost here:
  budget several days, and it needs its own tests because a malformed metadata
  object can make the whole file unreadable in strict viewers.
- **JSON export** — a top-level `ai_generated` block. Trivial.

### Layer B — clipboard (`text/html` + `text/plain`)

Replace the `writeText` call with `navigator.clipboard.write()` offering two
flavours of the same content:

- `text/html` — the text wrapped so it carries an HTML comment and a
  `<meta name="ai-generated" content="true">`. Any target that accepts rich text
  (Word, Google Docs, Notion, most mail clients) preserves it.
- `text/plain` — the text plus one trailing marker line, for targets that take
  plain text only.

**The `text/plain` marker line is user-facing copy and needs founder sign-off**
(LIVE LOOP fence). It is also the only part of this proposal a user will
routinely see in their own pasted text, so it should be as short as it can be
while still being detectable.

## 3. The clipboard problem, stated honestly

There is no way to put invisible machine-readable metadata into a plain-text
clipboard payload that survives arbitrary targets. The options are:

1. **A visible trailing line.** Detectable, robust, and the user sees it every
   time they paste. Some will find it intrusive.
2. **`text/html` only, no plain-text marker.** Invisible in rich targets, absent
   entirely in plain-text ones — so the obligation is met for some pastes and
   not others.
3. **Zero-width character encoding.** Technically invisible and technically
   machine-readable. **Not recommended.** It is steganography, it breaks
   diffing and search in unpredictable ways, several editors strip it silently,
   and defending "we marked it, you just could not see it" is a worse position
   than either honest option.

**Recommendation: option 1 for `text/plain`, plus the HTML flavour.** It is the
only one that is true for every paste.

## 4. C2PA — the strategic answer, and why not yet

C2PA (Content Credentials) is where the AI Act ecosystem is converging, and the
Commission's Article 50 guidance is likely to name it. It is a cryptographically
signed manifest rather than a metadata field, so it is tamper-evident, which
loose XMP is not.

It is not proposed for now because it needs a signing identity and certificate
handling, the tooling for text-bearing PDFs is much less mature than for images,
and none of that is proportionate before the policy is even registered.

**Layer A should be designed so C2PA can be added beside it later**, not so it
has to be replaced. Keeping the assertion in one shared module rather than
inlining it in three exporters is what makes that possible.

## 5. Scope questions this proposal does NOT decide

- **Transcripts.** §3 of the assessment says a transcript represents what the
  user actually said rather than synthesised content, and that the better view
  is that 50(2) does not attach. **Flagged, not decided — counsel confirms.**
  If it does attach, path 1 and the recording exports come into scope too.
- **The GDPR data export.** `export_authorization_evidence` returns receipts and
  authorization records rather than generated documents. It probably carries no
  Article 50 content at all. Worth one read-through before assuming either way.
- **Manager Feedback has no export path today.** It is rendered in the bookmark
  sheet and never leaves the product as a file. It therefore needs the visible
  label now, and needs Layer A only if an export is ever added — which is a
  reason to put the marking in a shared module at the point content is
  serialised, rather than in each export surface.

## 6. Visible label — wording for sign-off

Not shippable until signed (LIVE LOOP). Three candidates, on both the Ideal Text
and the Feedback surfaces, persistent rather than dismissible:

| | Wording | Note |
|---|---|---|
| A | `AI-generated` | Shortest. Detectable, neutral, no claim about quality. |
| B | `Written by AI from your recording` | Explains the provenance, which is the thing a user actually wants to know. |
| C | `AI-generated from your take` | Product vocabulary, shortest of the explanatory two. |

**AC-9 applies to all three:** this is a provenance label and never a quality
signal. No confidence wording, no score, no badge that could read as a verdict
on the text.

## 7. Suggested order

1. Visible label on both surfaces — small, and the gap a regulator would notice
   first. Blocked only on copy sign-off.
2. The shared assertion module + DOCX + JSON. Cheap, and it establishes the
   shape.
3. Clipboard, once the `text/plain` marker line is signed off.
4. PDF XMP. The most work, and the easiest to defer because it is one export
   format rather than a surface.
