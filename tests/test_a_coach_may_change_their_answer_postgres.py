"""
STORY    As a coach, I want to change my answer to a speaker's request, or
         my word on a Take, and have every earlier one kept, so that I can
         correct myself without losing the record.
OUTCOME
  O1  Giving the same answer again changes nothing.
  O2  A different answer replaces what the speaker sees; the old one, with
      its words, video and share, is kept as version 1, 2, 3.
  O3  A new answer that is not shared withdraws the earlier share.
  O4  Changing from words to an exercise keeps the answer well-formed.
  O5  A coach's word on a Take keeps every earlier version: a new word, a
      new draft or a new video keeps the one before; filling in what was
      empty, or the same word again, keeps nothing; a new video clears the
      old video's words; only the database writes the history, and the
      purge can read and delete it.
  O6  A coach's answer video keeps its own words, by its ref: a failed try
      is retried in place and counted; done words are never written over;
      after a new video the old one, now in the history, keeps its words
      and the new one gets its own; a video that is not this request's
      takes no words; only the database writes them.
PROVES   O1, O2, O3, O4 ->
             test_the_same_coach_changes_the_answer_and_every_earlier_one_stays
         O5 -> test_a_take_word_keeps_every_earlier_version
         O6 -> test_an_answer_video_keeps_its_own_words
WHY      Coach panel lock flows 7 and 12; Q-B12 A (migration 0446); a Take
         word keeps every version, N79 (migration 0480); a coach's answer
         video is kept in words, N79 (migration 0482).
"""
from __future__ import annotations

import os
import uuid

import psycopg2
import psycopg2.extras
import pytest

DSN = os.environ.get("CONFIDENT_MOMENT_REHEARSAL_DSN", "")
pytestmark = pytest.mark.skipif(
    not DSN, reason="disposable confident-moment rehearsal only"
)

HISTORY = "public.exercise_coach_request_answer_versions"
RESOLVER = ("public.resolve_exercise_coach_request_v3"
            "(uuid, text, text, text, integer, boolean, text, text)")


@pytest.fixture(scope="module")
def db():
    parsed = psycopg2.extensions.parse_dsn(DSN)
    if not parsed.get("dbname", "").startswith("willab_confident_moment_"):
        raise RuntimeError("Refusing a non-disposable database")
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    try:
        yield conn
    finally:
        conn.close()


def _row(db, sql, args):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(sql, args)
        return dict(cur.fetchone())


def _request(db):
    return _row(db,
                "SELECT * FROM public.request_exercise_from_coach_v1("
                "%s, %s, %s, 'nothing_targets_it', 'near_confident', %s::text[], %s::jsonb)",
                (str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4()), ["rushing"],
                 psycopg2.extras.Json({"signals": {"insufficient_pauses": True}})))


def _resolve(db, request_id, coach, resolution, *, exercise_id=None, version=None,
             share=False, text=None, video=None):
    return _row(db, f"SELECT * FROM {RESOLVER.split('(')[0]}(%s, %s, %s, %s, %s, %s, %s, %s)",
                (request_id, coach, resolution, exercise_id, version, share, text, video))


def _history(db, request_id):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM {HISTORY} WHERE request_id = %s ORDER BY version",
                    (request_id,))
        return [dict(r) for r in cur.fetchall()]


def test_the_same_coach_changes_the_answer_and_every_earlier_one_stays(db):
    request = _request(db)
    # The coach uploads a video before answering (the app's seam: a direct
    # write while the request is unresolved, as 0403).
    with db.cursor() as cur:
        cur.execute("UPDATE public.exercise_coach_requests SET answer_video_ref = 'v/1.mp4' "
                    "WHERE id = %s", (request["id"],))
    first = _resolve(db, request["id"], "coach-1", "line_written", text="Well said.", share=True)
    assert (first["resolution"], first["answer_text"]) == ("line_written", "Well said.")
    assert first["answer_video_ref"] == "v/1.mp4"
    assert first["shared_at"] is not None
    # The same answer again: nothing changes.
    again = _resolve(db, request["id"], "coach-1", "line_written", text="Well said.", share=True)
    assert (again["resolved_at"], again["shared_at"]) == (first["resolved_at"], first["shared_at"])
    assert _history(db, request["id"]) == []
    # Q-B12 A: new words replace the card; the old answer, whole, is version 1.
    second = _resolve(db, request["id"], "coach-1", "version_written",
                      text="We think timing matters.", share=True)
    assert (second["resolution"], second["answer_text"]) == ("version_written",
                                                             "We think timing matters.")
    assert second["resolved_at"] > first["resolved_at"]
    assert second["shared_at"] is not None and second["shared_at"] > first["shared_at"]
    history = _history(db, request["id"])
    assert len(history) == 1
    old = history[0]
    assert (old["version"], old["resolution"], old["answer_text"], old["answer_video_ref"],
            old["resolved_by"], old["superseded_by"]) == (
        1, "line_written", "Well said.", "v/1.mp4", "coach-1", "coach-1")
    assert old["resolved_at"] == first["resolved_at"] and old["shared_at"] == first["shared_at"]
    assert (old["take_session_id"], old["snippet_id"]) == (request["take_session_id"],
                                                             request["snippet_id"])
    # Changed again, this time not shared: the share is withdrawn with the
    # answer it belonged to, and the card goes.
    third = _resolve(db, request["id"], "coach-1", "no_safe_match")
    assert third["resolution"] == "no_safe_match" and third["shared_at"] is None
    assert third["answer_text"] is None and third["resolved_exercise_id"] is None
    history = _history(db, request["id"])
    assert [h["version"] for h in history] == [1, 2]
    assert (history[1]["resolution"], history[1]["shared_at"] is not None) == ("version_written", True)
    # And to an exercise, shared: the row's shape checks hold through it.
    fourth = _resolve(db, request["id"], "coach-1", "exercise_chosen",
                      exercise_id="ex-1", version=2, share=True)
    assert (fourth["resolved_exercise_id"], fourth["resolved_exercise_version"]) == ("ex-1", 2)
    assert fourth["shared_at"] is not None and fourth["answer_text"] is None
    assert [h["version"] for h in _history(db, request["id"])] == [1, 2, 3]


WORDS = "public.coach_take_word_versions"


def _save_word(db, take, *, text, video=None):
    """As upsert_coach_take_word writes a save that names its video: only the
    payload columns. (A word-only edit leaves video_ref out of the write.)"""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO public.coach_take_words (take_session_id, coach_id, text, video_ref, "
            "updated_at) VALUES (%s, 'coach-1', %s, %s, now()) "
            "ON CONFLICT (take_session_id, coach_id) DO UPDATE SET text = EXCLUDED.text, "
            "video_ref = EXCLUDED.video_ref, updated_at = EXCLUDED.updated_at",
            (take, text, video))


def _set(db, take, **columns):
    with db.cursor() as cur:
        assignments = ", ".join(f"{name} = %s" for name in columns)
        cur.execute(f"UPDATE public.coach_take_words SET {assignments} "
                    "WHERE take_session_id = %s AND coach_id = 'coach-1'",
                    (*columns.values(), take))


def _versions(db, take):
    with db.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT version, replaced, text, video_ref, draft_text, transcript "
                    f"FROM {WORDS} WHERE take_session_id = %s ORDER BY version", (take,))
        return [dict(r) for r in cur.fetchall()]


def test_a_take_word_keeps_every_earlier_version(db):
    take = str(uuid.uuid4())
    _save_word(db, take, text="Slow down.", video="s3://b/coach-feedback/t/a.webm")
    _set(db, take, draft_text="Pause.", draft_prompt=psycopg2.extras.Json({"passage_text": "p"}),
         drafted_at="now")
    _set(db, take, transcript="Slow down there.", transcribed_at="now")
    _save_word(db, take, text="Slow down.", video="s3://b/coach-feedback/t/a.webm")
    assert _versions(db, take) == []  # filled in, or the same again: nothing lost
    _save_word(db, take, text="Pause at the number.", video="s3://b/coach-feedback/t/a.webm")
    _set(db, take, draft_text="Breathe first.")
    # The app's own role writes the word; only the trigger can write the history.
    with db.cursor() as cur:  # as Supabase has it: the app's role bypasses RLS
        cur.execute("ALTER ROLE service_role BYPASSRLS")
        cur.execute("GRANT SELECT, INSERT, UPDATE ON public.coach_take_words TO service_role")
    db.autocommit = False
    try:
        with db.cursor() as cur:
            cur.execute("SET LOCAL ROLE service_role")
        _save_word(db, take, text="Pause at the number.", video="s3://b/coach-feedback/t/b.webm")
        db.commit()
    finally:
        db.rollback()
        db.autocommit = True
    kept = _versions(db, take)
    assert [(v["version"], v["replaced"]) for v in kept] == [
        (1, "word"), (2, "draft"), (3, "word")]
    assert (kept[0]["text"], kept[0]["transcript"]) == ("Slow down.", "Slow down there.")
    assert kept[1]["draft_text"] == "Pause."
    assert kept[2]["video_ref"].endswith("/a.webm")
    live = _row(db, "SELECT transcript, video_ref FROM public.coach_take_words "
                    "WHERE take_session_id = %s", (take,))
    assert live == {"transcript": None, "video_ref": "s3://b/coach-feedback/t/b.webm"}
    # Only the trigger writes the history.
    assert _row(db, "SELECT relrowsecurity AS rls FROM pg_class WHERE oid = %s::regclass",
                (WORDS,))["rls"] is True
    assert _row(db, "SELECT has_table_privilege('service_role', %s, 'INSERT') AS can",
                (WORDS,))["can"] is False
    # The purge reads and deletes it with the Take.
    for right in ("SELECT", "DELETE"):
        assert _row(db, "SELECT has_table_privilege('service_role', %s, %s) AS can",
                    (WORDS, right))["can"] is True
    for role in ("anon", "authenticated"):
        if _row(db, "SELECT count(*) AS n FROM pg_roles WHERE rolname = %s", (role,))["n"]:
            assert _row(db, "SELECT has_table_privilege(%s, %s, 'SELECT') AS can",
                        (role, WORDS))["can"] is False


TRANSCRIPTS = "public.coach_answer_video_transcripts"
RECORDER = "public.record_coach_answer_video_transcript_v1(uuid, text, text, text, text, text)"


def _keep_words(db, request_id, ref, status, words=None):
    return _row(db, f"SELECT * FROM {RECORDER.split('(')[0]}(%s, %s, 'coach-1', %s, %s, 'en')",
                (request_id, ref, status, words))


def test_an_answer_video_keeps_its_own_words(db):
    request = _request(db)
    old, new = "s3://b/coach-answers/u/r/1.mp4", "s3://b/coach-answers/u/r/2.mp4"
    with db.cursor() as cur:
        cur.execute("UPDATE public.exercise_coach_requests SET answer_video_ref = %s "
                    "WHERE id = %s", (old, request["id"]))
    failed = _keep_words(db, request["id"], old, "failed")
    assert (failed["status"], failed["transcript"], failed["attempts"]) == ("failed", None, 1)
    # The answer, then a new video: the old video goes into the history.
    _resolve(db, request["id"], "coach-1", "line_written", text="Well said.")
    _resolve(db, request["id"], "coach-1", "line_written", text="Well said.", video=new)
    assert [h["answer_video_ref"] for h in _history(db, request["id"])] == [old]
    # The old video, now only in the history, is retried in place.
    done = _keep_words(db, request["id"], old, "done", "  Pause before the number.  ")
    assert (done["id"], done["status"], done["transcript"], done["attempts"]) == (
        failed["id"], "done", "Pause before the number.", 2)
    assert done["transcribed_at"] is not None and done["language"] == "en"
    assert (done["take_session_id"], done["snippet_id"]) == (request["take_session_id"],
                                                             request["snippet_id"])
    # Done words are never written over.
    for status, words in (("done", "Something else."), ("failed", None)):
        kept = _keep_words(db, request["id"], old, status, words)
        assert (kept["status"], kept["transcript"], kept["attempts"]) == (
            "done", "Pause before the number.", 2)
    _keep_words(db, request["id"], new, "done", "Breathe, then the number.")
    with db.cursor() as cur:
        cur.execute(f"SELECT video_ref, transcript FROM {TRANSCRIPTS} WHERE request_id = %s",
                    (request["id"],))
        assert dict(cur.fetchall()) == {old: "Pause before the number.",
                                        new: "Breathe, then the number."}
    # A video that is not this request's takes no words: a stray ref, or
    # another request's video.
    other = _request(db)
    for request_id, ref in ((request["id"], "s3://b/coach-answers/u/r/3.mp4"),
                            (other["id"], old)):
        with pytest.raises(psycopg2.Error, match="COACH_ANSWER_TRANSCRIPT_NOT_THIS_REQUESTS_VIDEO"):
            _keep_words(db, request_id, ref, "done", "Words.")
    # Only the recorder writes.
    assert _row(db, "SELECT has_table_privilege('service_role', %s, 'INSERT') AS can",
                (TRANSCRIPTS,))["can"] is False
    assert _row(db, "SELECT has_function_privilege('service_role', %s, 'EXECUTE') AS can",
                (RECORDER,))["can"] is True
