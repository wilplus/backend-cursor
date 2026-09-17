# Vendor processor paperwork

Executed or in-force Art. 28 documents for the processors the code actually
reaches. Adding one should need no thought — follow the convention below and
add the matching row.

## Convention

**Filename:** `<Vendor>_<DocType>_<YYYY-MM-DD>.pdf`

```
Cloudflare_DPA_2026-09-17.pdf
Sentry_SOC2_2026-09-17.pdf
Supabase_TIA_2026-09-17.pdf
```

**The date is the day WE captured or accepted it**, not the vendor's own
revision date. A vendor that republishes its DPA does not change the date on a
file we captured before the change — that is the point. Where the document
carries its own version or "last updated" line, record *that* in the register
row instead, so the two dates stay distinguishable.

**Every file must have a matching row** in
[`../../VENDOR_DPA_REGISTER.md`](../../VENDOR_DPA_REGISTER.md), with the
relative path in the Evidence file column. A file here with no row is not
evidence of anything — nobody knows what it was meant to prove.

## What does not go in here

These are **public vendor documents, not secrets**. They can be read by anyone
with the repo.

So: nothing containing credentials, API keys, account identifiers beyond the
organisation name, bucket names, internal hostnames, or any invoice, usage
report or support thread that carries them. If a capture includes an account
number in a header, re-capture it rather than committing and redacting —
a redaction in git history is not a redaction.

## Capture quality

A `Cmd+P` capture of a web page can silently produce a blank page, a cookie
banner, or a consent wall instead of the agreement. **Open every file before
committing it.** The check that catches this is page count plus the first line
of real text: a genuine DPA opens with its own title and, usually, the source
URL in the print header.

## Signed vs in force by reference

Both are valid Art. 28 positions and the register distinguishes them:

- **`SIGNED`** — an executed, countersigned document exists.
- **`BY-REF`** — the vendor's DPA is incorporated into terms we have already
  accepted, and no signature is available or needed. The evidence is the DPA
  text itself, containing the incorporation clause.

Read the execution clause before assuming which one applies. Two examples from
this folder that look alike and are not:

- **Resend** — *"the signature blocks set forth below are provided for
  reference purposes only; this DPA becomes legally binding upon Customer's
  acceptance"* → `BY-REF`.
- **Railway** — *"Customer must complete the information requested and submit
  the DocuSign form available here. This DPA will become legally binding upon
  Company's execution in the signature block below"* → **not** by reference,
  despite the same document also saying it "supplements the Terms of Service".
  That phrase describes the DPA's relationship to the TOS, not its execution.

## Not a build input

Docs only. Nothing here is read by the application, and this folder must not be
added to any build, bundle or deploy path.
