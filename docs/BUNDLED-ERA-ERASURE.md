# Bundled-era erasure (F4)

Founder, 2026-09-25. Delete what was gathered for training under the
bundled-era consent, which the DPIA calls defective (§2.4). The decisions this
follows are:

- **5a** delete every row of group A;
- **5b** delete group B too;
- **5c** keep the consent records;
- **5d** handle group D separately;
- **5e** counsel reviews the prepared list before anything is deleted.

The plan and its reasoning are in the founder-facing F4 page.

**Nothing here runs by itself.** `migrations/pending/erase_bundled_era_corpus.sql`
is not in `manifest.txt`, so merging it runs nothing. It is applied by hand,
once, when the steps below reach it.

## What is deleted, what is kept

| | Tables | Here |
|---|---|---|
| **A** (5a) | `training_labels`, `shadow_predictions`, `reflection_clips`, `stress_snippets`, `snippet_labels`, `acoustic_labels`, `recording_reviews`, `recording_review_annotations`, `strong_sides_library`, `admin_annotations_log` | every row, and every stored file they point to |
| **B** (5b) | `model_versions`; annotation exports in `ANNOTATION_EXPORT_BUCKET`; OpenAI fine-tuning files and models | rows and exports by the tools below; OpenAI **by hand** in the OpenAI dashboard, each deletion recorded |
| **C** | `ml_object_artifacts`, `ml_evidence_spans`, `ml_canonical_events`, `ml_candidate_sets` | **counted only**; not decided |
| kept (5c) | `user_consents`, `ml_consent_events` | evidence; needs a written end date (DPIA RISK-9, M9.1) |
| **D** (5d) | live tables | a separate decision |

## Steps

1. **Install the tools.** Paste `migrations/pending/erase_bundled_era_corpus.sql`
   into the Supabase SQL editor, as the database owner. It creates two log
   tables and the functions, and deletes nothing.
2. **Count, and answer OPEN-1.** Run
   `SELECT public.preview_bundled_era_erasure_v1();`. It returns:
   - the rows per table;
   - group C's counts;
   - how many people accepted each terms version.
3. **Freeze what could still copy it.** Confirm `MLC2_TRAINING_ENABLED` is off.
   In the OpenAI dashboard, list the fine-tuning files and models, and note
   each one.
4. **Prepare.** Run `SELECT public.prepare_bundled_era_erasure_v1();`. It
   returns a `snapshot_id`, a `sha256` and the counts. The snapshot is the
   exact list: every row by primary key, and every stored reference.
5. **Preview the files.** Run
   `python3 scripts/bundled_era_erasure_storage.py --snapshot-id <id>`
   (`railway run`, web service). It classifies every reference as one of:
   - `would_delete`
   - `absent`
   - `not_ours`

   It also lists the annotation exports.
6. **Counsel reviews** the prepare output, the file preview and the OpenAI
   list (5e). Record their reference, for example the memo's date or id.
7. **Delete the files.** Run the same script with `--execute`. Each file is
   deleted, checked gone and recorded against the snapshot. A provider error
   stops the run. Rerun it: finished references stay recorded.
8. **Delete the OpenAI copies by hand.** Write down what was deleted, as a
   JSON list such as
   `[{"provider":"openai","ref":"ft:…","action":"deleted","at":"…"}]`, or
   `[{"provider":"openai","action":"none found"}]`.
9. **Apply.** As the owner, run:

   ```sql
   SELECT public.apply_bundled_era_erasure_v1(
     '<snapshot_id>', '<sha256>', '<founder authorisation ref>',
     '<counsel review ref>', '<external copies JSON>'::jsonb);
   ```

   It refuses in each of these cases:
   - a wrong hash;
   - a missing reference or record;
   - any file with no recorded outcome;
   - any row missing since step 4.

   It deletes exactly the snapshot, past the retired-write guard. That guard
   is off only inside this one transaction.
10. **Record it.** Update the DPIA status note (§2.4) and the Article 30
    record (A9, A13) with what was deleted and when, and close OPEN-1.

## If a step refuses

Nothing has been deleted from the database: apply is one transaction. Files
already deleted stay recorded. Prepare a new snapshot only if the rows really
changed, and take it back through counsel, because the list is what they
approved.
