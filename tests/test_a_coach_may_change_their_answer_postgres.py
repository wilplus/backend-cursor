"""A coach may change their answer, on a disposable database (0446; coach
panel lock flows 7 and 12; Q-B12 A, N62; build plan D-CP-7).

Pins:
  * the history table exists with RLS on; browser roles and PUBLIC hold
    nothing on it or on the v3 resolver; service_role reads and deletes the
    history, calls the resolver, and cannot write the history by hand;
  * the file applied again changes nothing; the guard trigger is v2;
  * the first answer is written as before; the same answer again is a no-op
    that may add the share; a DIFFERENT answer by the same coach replaces the
    row's answer, resets the share to this call's, and moves the old answer
    (words, exercise, video, share) into the history as version 1, 2, ...;
  * another coach's call on a resolved request is ALREADY_RESOLVED, the
    same answer included (it cannot add the share);
  * the answer's video goes with the answer: a new video (p_video_ref) is a
    change that keeps the old video in the history and puts the new one on
    the row in the same UPDATE; '' clears it; NULL keeps it; a hand UPDATE
    of a resolved answer's video is refused by the guard;
  * the guard still refuses a hand UPDATE of a set resolution, a hand unset
    of a share, and any change to what was requested; the door is only the
    resolver's, in its own transaction;
  * a changed answer that goes from shared to unshared leaves shared_at NULL
    (a withdrawn share), and from words to an exercise respects the row's
    shape checks;
  * a coach's Take word keeps every earlier version too (0478, N79): a new
    word, a re-draft or a new video moves the one before into
    coach_take_word_versions; a NULL being filled in, or the same text
    again, keeps none; a new video clears the old video's words on the row;
    only the trigger writes the history;
  * a coach's answer video keeps its own words, by its ref (0480, N79): the
    recorder takes words for the video on the row or one the history keeps,
    and for no other; a failed try is retried in place and counted; done
    words are never written over; after a new video, the old one keeps its
    words and the new one gets its own; only the recorder writes the table;
  * each answer keeps what the coach saw (0481, N79): one situation per
    answer (the same answer written again is ignored), a replaced answer
    finds its own on (request_id, resolved_at) with the error type copied,
    one per Take-word save; nobody may update a situation; the request's and
    the word's cascades remove theirs.
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
    """As upsert_coach_take_word writes it: only the payload columns."""
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
    _save_word(db, take, text="Pause at the number.", video="s3://b/coach-feedback/t/b.webm")
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


SITUATIONS = "public.coach_answer_situations"


def _keep_situation(db, *, take, answered_at, request_id=None, snippet_id=None,
                    take_word_id=None, diagnoses=()):
    """As insert_coach_answer_situation writes it: an answer already kept is
    ignored by its key. Returns the rows written."""
    key = "take_word_id" if take_word_id else "request_id"
    with db.cursor() as cur:
        cur.execute(
            f"INSERT INTO {SITUATIONS} (take_session_id, snippet_id, request_id, take_word_id, "
            "answered_at, passage_text, diagnosis_ids, diagnoses) "
            "VALUES (%s, %s, %s, %s, %s, 'and that is why', %s::uuid[], %s::jsonb) "
            f"ON CONFLICT ({key}, answered_at) DO NOTHING",
            (take, snippet_id, request_id, take_word_id, answered_at,
             [d["diagnosis_id"] for d in diagnoses], psycopg2.extras.Json(list(diagnoses))))
        return cur.rowcount


def _count(db, column, value):
    return _row(db, f"SELECT count(*) AS n FROM {SITUATIONS} WHERE {column} = %s",
                (value,))["n"]


def test_each_answer_keeps_what_the_coach_saw_and_it_never_changes(db):
    request = _request(db)
    moment = {"take": request["take_session_id"], "snippet_id": request["snippet_id"],
              "request_id": request["id"]}
    first = _resolve(db, request["id"], "coach-1", "line_written", text="Well said.")
    picked = [{"diagnosis_id": str(uuid.uuid4()), "snippet_id": request["snippet_id"],
               "kind": "error", "error_id": "rushing", "named_error_id": None,
               "label": "Rushing"}]
    assert _keep_situation(db, answered_at=first["resolved_at"], diagnoses=picked,
                           **moment) == 1
    # The same answer written again is ignored: one row per answer.
    assert _keep_situation(db, answered_at=first["resolved_at"], **moment) == 0
    # A changed answer keeps its own; the first finds its history row by the
    # resolver's time, with the error type the coach had picked, copied.
    second = _resolve(db, request["id"], "coach-1", "line_written",
                      text="Pause, then the number.")
    assert _keep_situation(db, answered_at=second["resolved_at"], **moment) == 1
    with db.cursor() as cur:
        cur.execute(f"SELECT h.answer_text, s.diagnoses, s.diagnosis_ids::text[] AS ids "
                    f"FROM {HISTORY} h JOIN {SITUATIONS} s ON s.request_id = h.request_id "
                    "AND s.answered_at = h.resolved_at WHERE h.request_id = %s",
                    (request["id"],))
        assert cur.fetchall() == [("Well said.", picked, [picked[0]["diagnosis_id"]])]
    # Frozen: nobody rewrites what the coach saw, the owner included.
    with pytest.raises(psycopg2.Error, match="COACH_ANSWER_SITUATION_FROZEN"):
        with db.cursor() as cur:
            cur.execute(f"UPDATE {SITUATIONS} SET passage_text = 'other words' "
                        "WHERE request_id = %s", (request["id"],))
    # A Take word: one row per save, by the word and its updated_at.
    take = str(uuid.uuid4())
    _save_word(db, take, text="Slow down.")
    word = _row(db, "SELECT id, updated_at FROM public.coach_take_words "
                    "WHERE take_session_id = %s", (take,))
    for written in (1, 0):
        assert _keep_situation(db, take=take, take_word_id=word["id"],
                               answered_at=word["updated_at"]) == written
    # The parents' cascades are the purge's backstop (the registry deletes
    # by Take first).
    with db.cursor() as cur:
        cur.execute("DELETE FROM public.exercise_coach_requests WHERE id = %s", (request["id"],))
        cur.execute("DELETE FROM public.coach_take_words WHERE id = %s", (word["id"],))
    assert (_count(db, "request_id", request["id"]), _count(db, "take_word_id", word["id"])) == (0, 0)
