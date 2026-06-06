-- willab coach per-snippet DRAFT store — USER lane (note / tag / surfaced).
--
-- E1 (immediate-persist + resume): each coach edit upserts one row here, so
-- closing the overlay mid-review never loses work. At publish the SURFACED
-- rows are ASSEMBLED into the session's insights_payload (the published
-- artifact on v2_sessions.insights_payload).
--
-- WHY A SEPARATE TABLE (split-sink §2 / S.1): the PRIVATE direction-label
-- lane lives in training_labels; the USER note/tag lane lives here. Separate
-- fields -> separate validators -> separate tables, no cross-derivation. And
-- because insights_payload is written ONLY at publish, draft note/tag never
-- leak to the user re-read pre-publish (the user readout folds insights_payload
-- only when it is set).
--
-- `surfaced` = does this snippet reach the user? (F: skip removes from the
-- user lane only). A row with surfaced=false is a draft the coach kept but did
-- not send; a row may be labeled-but-unsurfaced (label lives in training_labels).
-- `when_context` avoids the SQL reserved word `when`; it maps to the
-- insights_payload note field `when` at assembly time.

CREATE TABLE IF NOT EXISTS coach_snippet_drafts (
    session_id    uuid        NOT NULL,
    snippet_id    uuid        NOT NULL,
    note          text,
    tag           text,                              -- 'strong' | 'to_work_on' (validated app-side)
    surfaced      boolean     NOT NULL DEFAULT true,
    when_context  text,
    examples      jsonb       NOT NULL DEFAULT '[]'::jsonb,
    updated_by    uuid,
    updated_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (session_id, snippet_id)
);

CREATE INDEX IF NOT EXISTS idx_coach_snippet_drafts_session
    ON coach_snippet_drafts (session_id);

-- Service-role only (the BE assembles + publishes; never client-read).
ALTER TABLE coach_snippet_drafts ENABLE ROW LEVEL SECURITY;
