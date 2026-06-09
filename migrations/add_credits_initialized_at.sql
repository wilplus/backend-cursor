-- UX Wave v2 (C1) — willab credit grant: lazy first-touch seed marker.
--
-- v2_student_details.credits already exists (the ledger). This adds the
-- DEDICATED idempotency flag so the 15-credit grant fires exactly once per
-- user and is never re-granted when a user legitimately spends down to 0
-- (we guard on this flag, never on credits == 0/NULL).
--
-- Safe to run repeatedly. The application degrades to the legacy implicit
-- "credits is NULL -> treat as 15" default until this is applied, so there
-- is no hard dependency on deploy ordering.

ALTER TABLE v2_student_details
    ADD COLUMN IF NOT EXISTS credits_initialized_at timestamptz;
