-- Context-document upload (X-1, founder 2026-07-24).
--
-- One supplementary document per arc (a report / case metrics / Q&A, ≤~20
-- pages), extracted to plain text and stored so the assembly/feedback can
-- draw on the background. L1: this is BACKGROUND for the qualitative layer
-- only — it never becomes part of the verbatim ideal text.
--
-- Idempotent; degrades gracefully — every read/write in services/db is
-- best-effort, so shipping the code before running this is safe.

CREATE TABLE IF NOT EXISTS arc_context_documents (
    arc_id     text PRIMARY KEY,
    text       text        NOT NULL DEFAULT '',
    pages      integer     NOT NULL DEFAULT 0,
    chars      integer     NOT NULL DEFAULT 0,
    filename   text,
    truncated  boolean     NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now()
);
