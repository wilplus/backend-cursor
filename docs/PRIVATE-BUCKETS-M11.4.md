# Private buckets (DPIA RISK-11, mitigation M11.4)

Founder decision 4, 2026-09-25: switch both recording buckets to private.

A public development URL (`pub-….r2.dev`) is permanent, unauthenticated and
cannot be revoked: every link to a recording that ever left our systems still
plays for anyone who has it. Since 2026-09-17/18 nothing mints a new one for
user content. This finishes the job: nothing mints one for anything, every
stored link is re-signed from its key when it is read, and the buckets stop
answering public requests at all.

## What the code does after this PR

- `coach_media_public_url` returns `None` for every key. Each caller already
  falls back to a presigned GET or an `s3://bucket/key` marker.
- `refreshed_media_url` signs every ref that is ours: a presigned URL, a URL
  on one of our public bases, an `s3://` marker, or a bare user-content key.
  Foreign refs and Supabase signed URLs pass through untouched.
- Six reads that served a stored ref raw now sign it. They cover:
  - the coach feedback video: the coach's review, a de-duplicated re-upload,
    and the speaker's readout;
  - the readout's deck (two keys);
  - the Trainings-page cover.
- The coach video upload stores `s3://bucket/key`, not a URL.
- Audit PDFs (`willab_audits/`) are classified as user content.

**Keep every `*_PUBLIC_BASE_URL` variable set.** They no longer mint anything.
The code uses them to recognise old stored URLs (`media_key_from_ref`,
`audio_ref_resolver`) so it can re-sign them. Unset one, and rows written on
that base are sent to the browser unchanged and fail.

## Steps, in order

Do step 1 before step 2. Each switch is instant and can be undone the same
way.

1. **Merge and deploy this PR.** Confirm the web and worker services booted on
   the new commit.
2. **Check that `R2_JOURNAL_BUCKET` is set** on the web and worker services, in
   Railway → each service → Variables. If it is not, journal and exercise-demo
   media fall back into the coach bucket (`services/journal_media.py:93-109`),
   and blog images would break when that bucket goes private. Stop here and
   say so if it is missing.
3. **`user-interview-audio`.** Cloudflare dashboard → R2 → `user-interview-audio`
   → Settings → Public access:
   - **R2.dev subdomain → Disallow.**
   - **Custom domains:** remove any listed. There should be none.
4. **`coach-feedback-videos`.** The same two settings.
5. **Check, within 10 minutes of each switch:**
   - Open an old public link, for example one from before 2026-09-17 in a
     support thread. It should now answer 401 or 404.
   - Open a take with a recording, a coach review with a feedback video, a
     project with a slide deck, and the Trainings page. All should play and
     show normally.

## If something stops showing

Turn the R2.dev subdomain back on for that bucket; it takes effect at once.
Then send the page and the time, and the read path gets fixed before trying
again.

## Not in scope

- **`willab-journal`** (blog and demo media) is published on purpose and stays
  public.
- **The MLC-3 buckets** have their own readiness proof
  (`MLC3-FOUNDER-CANARY-ACTIVATION-READINESS.md`).
- **Deleting old objects** is the F4 plan, not this switch.
