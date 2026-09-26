-- A project can be archived (founder 2026-09-26, decisions log N14).
--
-- "In place of a real delete that for now we can hide": the ⋯ on each row of
-- the project list offers Archive, so a person can tidy the list without any
-- load-bearing action. Archiving only hides the project from the list; its
-- takes, words, Ideal Text and feedback are untouched, and it can be brought
-- back. Deletion stays a separate, governed request (Data & consent).
--
-- ADDITIVE AND IDEMPOTENT: one nullable column. No row is written by running
-- this file.

BEGIN;

ALTER TABLE public.projects
    ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ NULL;

COMMENT ON COLUMN public.projects.archived_at IS
    'Set when the owner archives the project (N14): hidden from the project '
    'list only; nothing is deleted. NULL = shown.';

COMMIT;
