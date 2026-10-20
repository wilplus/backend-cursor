-- a_coach_answer_video_is_kept_in_words (0481; founder 2026-10-19, decisions log N79)
--
-- WHY. A coach may answer a speaker's moment with a video (0403): it is kept
-- privately as exercise_coach_requests.answer_video_ref, and a changed
-- answer's old video is kept in exercise_coach_request_answer_versions
-- (0446). What the coach SAID in it was never written down anywhere, so a
-- coach's spoken answer existed only as a video file.
--
-- WHAT. coach_answer_video_transcripts holds the words of an answer video,
-- one row per video ref, so a changed answer's old video keeps its own
-- words and the new video gets its own. exercise_coach_requests, its guard
-- (v2) and its resolver (v3) are not touched: the history already keeps the
-- old ref, and the words are found by that ref. Columns: the ref, the
-- request, its Take and moment, the coach who uploaded it, a status
-- ('done' with the words; 'failed' or 'speaker_authorization_missing'
-- without), the language the transcriber heard, and the number of attempts.
--
-- record_coach_answer_video_transcript_v1 is the only writer (SECURITY
-- DEFINER). It takes words only for a video that is this request's when it
-- writes: the one on the row or one its history keeps. 'done' words are
-- never written over; a 'failed' or 'speaker_authorization_missing' row is
-- retried in place and counts the attempt.
--
-- READERS, MIND THIS. Before the answer is given, a new video overwrites
-- the request row directly and the history keeps nothing (0403; 0446 keeps
-- only a given answer's video). So a video the coach replaced before
-- answering keeps its row here, under the same request_id, when its words
-- were kept before the replacement landed (the usual case: the words take
-- seconds), although it never reached the speaker. Only a replacement that
-- lands first makes the recorder refuse it
-- (COACH_ANSWER_TRANSCRIPT_NOT_THIS_REQUESTS_VIDEO). Nothing in the row
-- tells the two apart, and the row is kept. Every reader (a catch-up, a
-- training export) keeps only rows whose video_ref is the request's
-- answer_video_ref or an exercise_coach_request_answer_versions
-- answer_video_ref of the same request.
--
-- The app writes a row only for a speaker who holds the training yes, and
-- never for a coach answering their own Take (services/coach_answer_video.py);
-- the transcription runs after the coach's upload has returned, under the
-- SPEAKER's provider permit. Capture only: no feedback pair is recorded, and
-- no training, release, golden or promotion reader, and no speaker or coach
-- payload, reads this table. Every row belongs to the speaker's Take and is
-- purged with it (services/data_purge_registry.py,
-- coach_answer_video_transcripts, order 58, before the request, whose
-- cascade is only the backstop). No by-coach entry: a coach's words stay
-- with the speaker's Take (N79).
--
-- A stale comment, for the record: 0428 (the_bake_knows_about_the_coach.sql)
-- says a video can only be added before the answer. Since 0446 the same
-- coach may give a resolved answer a new video (an answer change through the
-- resolver). 0428 is applied and is not edited.
--
-- Additive and idempotent: CREATE TABLE / INDEX IF NOT EXISTS, CREATE OR
-- REPLACE FUNCTION, REVOKE and GRANT, COMMENT. Nothing dropped, no row
-- written, no env var. The foreign key takes a brief SHARE ROW EXCLUSIVE
-- lock on exercise_coach_requests, with no scan (the new table is empty).
-- Deploy with the registry entry in the same PR: an unregistered table with
-- take_session_id stops a purge for review. Merge when no deletion is
-- mid-run. Both rehearsal lanes: it needs only 0385, 0403 and 0446.

BEGIN;

CREATE TABLE IF NOT EXISTS public.coach_answer_video_transcripts (
    id              uuid        PRIMARY KEY DEFAULT gen_random_uuid(),
    video_ref       text        NOT NULL,
    request_id      uuid        NOT NULL
                    REFERENCES public.exercise_coach_requests (id) ON DELETE CASCADE,
    take_session_id text        NOT NULL,
    snippet_id      text        NOT NULL,
    coach_id        text        NULL,
    status          text        NOT NULL,
    transcript      text        NULL,
    language        text        NULL,
    attempts        integer     NOT NULL DEFAULT 1,
    created_at      timestamptz NOT NULL DEFAULT now(),
    updated_at      timestamptz NOT NULL DEFAULT now(),
    transcribed_at  timestamptz NULL,
    CONSTRAINT coach_answer_video_transcripts_one_per_video UNIQUE (video_ref),
    CONSTRAINT coach_answer_video_transcripts_status CHECK (status IN (
        'done', 'failed', 'speaker_authorization_missing')),
    -- Words exactly when done, and done exactly when the words are dated.
    CONSTRAINT coach_answer_video_transcripts_words CHECK (
        (status = 'done') = (transcript IS NOT NULL AND length(btrim(transcript)) > 0)),
    CONSTRAINT coach_answer_video_transcripts_dated CHECK (
        (status = 'done') = (transcribed_at IS NOT NULL)),
    CONSTRAINT coach_answer_video_transcripts_ref CHECK (length(btrim(video_ref)) > 0),
    CONSTRAINT coach_answer_video_transcripts_attempts CHECK (attempts >= 1)
);
CREATE INDEX IF NOT EXISTS coach_answer_video_transcripts_take_idx
    ON public.coach_answer_video_transcripts (take_session_id);
CREATE INDEX IF NOT EXISTS coach_answer_video_transcripts_request_idx
    ON public.coach_answer_video_transcripts (request_id);
ALTER TABLE public.coach_answer_video_transcripts ENABLE ROW LEVEL SECURITY;
COMMENT ON TABLE public.coach_answer_video_transcripts IS
    'The words of a coach''s answer video, one row per video ref (0481; founder '
    '2026-10-19, N79), so a changed answer''s old video keeps its own words. '
    'Written only by record_coach_answer_video_transcript_v1; done words are '
    'never written over. Only for speakers with the training yes, never on the '
    'coach''s own Take. Capture only: read by no training, release, golden or '
    'promotion reader, in no payload. Purged with the Take. A row may name a '
    'video replaced before the answer was given, whose words were kept before '
    'the replacement landed; it never reached the speaker. Readers keep only '
    'rows whose video_ref is the request''s answer_video_ref or an '
    'answer_video_ref of its exercise_coach_request_answer_versions.';

CREATE OR REPLACE FUNCTION public.record_coach_answer_video_transcript_v1(
    p_request_id uuid,
    p_video_ref  text,
    p_coach_id   text,
    p_status     text,
    p_transcript text,
    p_language   text
) RETURNS public.coach_answer_video_transcripts
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_ref   text := NULLIF(btrim(p_video_ref), '');
    v_words text := NULLIF(btrim(p_transcript), '');
    v_req   public.exercise_coach_requests;
    v_kept  public.coach_answer_video_transcripts;
BEGIN
    IF p_request_id IS NULL OR v_ref IS NULL OR p_status IS NULL
       OR p_status NOT IN ('done', 'failed', 'speaker_authorization_missing')
       OR (p_status = 'done') IS DISTINCT FROM (v_words IS NOT NULL) THEN
        RAISE EXCEPTION 'COACH_ANSWER_TRANSCRIPT_INPUT_INVALID';
    END IF;
    SELECT * INTO v_req FROM public.exercise_coach_requests WHERE id = p_request_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'EXERCISE_COACH_REQUEST_NOT_FOUND';
    END IF;
    -- Only this request's own video: the one on the row, or one its history
    -- keeps. One statement, one snapshot: a resolver moving the ref into the
    -- history in between still finds it in one place or the other.
    IF NOT EXISTS (
        SELECT 1 FROM public.exercise_coach_requests r
         WHERE r.id = p_request_id AND r.answer_video_ref = v_ref
        UNION ALL
        SELECT 1 FROM public.exercise_coach_request_answer_versions v
         WHERE v.request_id = p_request_id AND v.answer_video_ref = v_ref) THEN
        RAISE EXCEPTION 'COACH_ANSWER_TRANSCRIPT_NOT_THIS_REQUESTS_VIDEO';
    END IF;
    INSERT INTO public.coach_answer_video_transcripts AS t (
        video_ref, request_id, take_session_id, snippet_id, coach_id,
        status, transcript, language, transcribed_at)
    VALUES (
        v_ref, v_req.id, v_req.take_session_id, v_req.snippet_id,
        NULLIF(btrim(p_coach_id), ''), p_status, v_words,
        NULLIF(btrim(p_language), ''),
        CASE WHEN p_status = 'done' THEN now() END)
    ON CONFLICT (video_ref) DO UPDATE
       SET status = EXCLUDED.status,
           transcript = EXCLUDED.transcript,
           language = EXCLUDED.language,
           transcribed_at = EXCLUDED.transcribed_at,
           coach_id = COALESCE(t.coach_id, EXCLUDED.coach_id),
           attempts = t.attempts + 1,
           updated_at = now()
     -- Done words are never written over.
     WHERE t.status <> 'done' AND t.request_id = EXCLUDED.request_id
    RETURNING * INTO v_kept;
    IF v_kept.id IS NULL THEN
        SELECT * INTO v_kept FROM public.coach_answer_video_transcripts
         WHERE video_ref = v_ref;
    END IF;
    RETURN v_kept;
END;
$$;

COMMENT ON FUNCTION public.record_coach_answer_video_transcript_v1(
    uuid, text, text, text, text, text) IS
    'Keeps the words of a coach''s answer video (0481): only for a video on the '
    'request row or in its answer history; done words are never written over; '
    'a failed or speaker_authorization_missing row is retried in place. '
    'service_role only.';

-- The app reads and the purge deletes; only the recorder writes.
REVOKE ALL ON TABLE public.coach_answer_video_transcripts FROM PUBLIC;
REVOKE ALL ON TABLE public.coach_answer_video_transcripts FROM anon, authenticated, service_role;
GRANT SELECT, DELETE ON TABLE public.coach_answer_video_transcripts TO service_role;

REVOKE ALL ON FUNCTION public.record_coach_answer_video_transcript_v1(
    uuid, text, text, text, text, text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.record_coach_answer_video_transcript_v1(
    uuid, text, text, text, text, text) FROM anon, authenticated;
GRANT EXECUTE ON FUNCTION public.record_coach_answer_video_transcript_v1(
    uuid, text, text, text, text, text) TO service_role;

COMMIT;
