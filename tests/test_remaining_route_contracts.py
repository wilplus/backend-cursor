"""Route-level contracts for the last routes over complexity 20 moved into
services (founder 2026-10-12: "move logic out of the backend routes and cut
glue"): the Lounge chat, the transcript edit, the feedback answer, the admin
session read, the journal cover and community generators, the Life Panel day
card and the intake profile.

Characterization tests, written against the unmodified routes first: each
pins a route's main success path (status, body, the writes and their order)
and its main refusal. Decorators are peeled with ``inspect.unwrap``; the move
leaves them untouched. Any database call a test does not stub raises, as it
would in CI.
"""
from __future__ import annotations

import inspect
from unittest.mock import ANY, MagicMock, patch

import pytest

try:
    from flask import Flask, request

    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    _IMPORT_ERROR = e

pytestmark = pytest.mark.skipif(_IMPORT_ERROR is not None,
                                reason=f"needs app deps: {_IMPORT_ERROR}")

USER = "cccccccc-0000-4000-8000-000000000003"
SID = "22222222-2222-4222-8222-222222222222"
SNIP = "33333333-3333-4333-8333-333333333333"
ARC = "44444444-4444-4444-8444-444444444444"
CLIENT = "55555555-5555-4555-8555-555555555555"


class _Unstubbed:
    def __getattr__(self, name):
        def call(*_a, **_k):
            raise RuntimeError(f"unstubbed db.client.{name}")
        return call


def _call(view, *args, user=USER, peel=True, **ctx):
    app = Flask(__name__)
    with app.test_request_context("/", **ctx), \
            patch.object(db, "client", _Unstubbed()):
        request.user_id = user
        fn = inspect.unwrap(view) if peel else view
        out = fn(*args)
    resp, status = out if isinstance(out, tuple) else (out, 200)
    return status, resp.get_json()


# ── POST /v2/chat/query ─────────────────────────────────────────────────────

def _chat_patches(rec, *, intent=None, librarian=None):
    return [
        patch("services.goal_update.handle_goal_update", return_value=None),
        patch("services.presentation_change_intent.handle_presentation_change",
              return_value=None),
        patch("services.chat_intents.detect_chat_intent", return_value=intent),
        patch("services.master_doc_rag.answer_question",
              return_value=librarian or ({}, {})),
        patch("services.token_account.charge", rec.charge),
        patch.object(db, "insert_lounge_messages", rec.insert),
        patch.object(db, "get_user_settings",
                     return_value={"private_admin_notes": "no money talk"}),
    ]


def test_a_chat_turn_answers_persists_and_charges():
    from routes.v2 import coaching
    rec = MagicMock()
    p = _chat_patches(rec, intent={
        "intent": "dad_joke", "answer": "One.\n\nTwo.",
        "show_record_ui": False, "suggested_action": None})
    with p[0], p[1], p[2], p[3], p[4], p[5], p[6]:
        status, body = _call(coaching.v2_chat_query, method="POST", json={
            "question": " tell me a joke ", "persist": True,
            "client_id": CLIENT, "client_created_at": "2026-10-12T10:00:00Z"})
    assert status == 200
    bot_id = body["persisted_client_id"]
    assert body == {"answer": "One.\n\nTwo.", "bubbles": ["One.", "Two."],
                    "show_record_ui": False, "suggested_action": None,
                    "debug": {"intent": "dad_joke"}, "persisted": True,
                    "persisted_client_id": bot_id}
    assert [c[0] for c in rec.mock_calls] == ["insert", "charge"]
    assert rec.insert.call_args.args == (USER, [
        {"client_id": CLIENT, "role": "user", "kind": "text",
         "body": "tell me a joke", "metadata": None,
         "client_created_at": "2026-10-12T10:00:00Z"},
        {"client_id": bot_id, "role": "bot", "kind": "text",
         "body": "One.\n\nTwo.",
         "metadata": {"intent": "dad_joke", "bubbles": ["One.", "Two."]},
         "client_created_at": ANY}])
    rec.charge.assert_called_once_with(USER, "chat")


def test_the_librarian_answers_the_rest_and_a_blank_question_is_refused():
    from routes.v2 import coaching
    rec = MagicMock()
    p = _chat_patches(rec, librarian=(
        {"answer": "Record a take.", "show_record_ui": True,
         "suggested_action": "nonsense"}, {"intent": "faq", "model": "m"}))
    with p[0], p[1], p[2], p[3] as answer, p[4], p[5], p[6]:
        status, body = _call(coaching.v2_chat_query, method="POST",
                             json={"question": "how?", "history": [{"r": 1}]})
        assert (status, body) == (200, {
            "answer": "Record a take.", "bubbles": ["Record a take."],
            "show_record_ui": True, "suggested_action": None,
            "debug": {"intent": "faq", "model": "m"}})
        answer.assert_called_once_with(
            "how?", history=[{"r": 1}], admin_dont_ask_notes="no money talk",
            life_context=None)
        rec.insert.assert_not_called()
        status, body = _call(coaching.v2_chat_query, method="POST",
                             json={"question": "  "})
    assert (status, body["code"]) == (400, "INVALID_INPUT")


# ── PUT /v2/user/sessions/<sid>/transcript-edit ─────────────────────────────

def _owned_session():
    return patch.object(db, "v2_get_session_by_id",
                        return_value={"id": SID, "user_id": USER})


def test_a_transcript_edit_lands_on_its_snippet_or_chunk():
    from routes.v2 import user_sessions as us
    with _owned_session(), \
            patch.object(db, "get_snippet_by_id",
                         return_value={"id": SNIP, "session_id": SID}), \
            patch.object(db.takes, "get_session_slide_transcripts",
                         return_value=[{"slide_index": 0, "transcript": "a b"}]), \
            patch("services.slide_word_split.deckless_chunks_from_stx",
                  return_value=["a", "b"]), \
            patch.object(db, "upsert_user_transcript_edit", return_value=True) as save:
        status, body = _call(us.v2_user_put_transcript_edit, SID, method="PUT",
                             json={"text": " fixed ", "snippet_id": SNIP})
        assert (status, body) == (200, {"saved": True, "session_id": SID,
                                        "snippet_id": SNIP})
        status, body = _call(us.v2_user_put_transcript_edit, SID, method="PUT",
                             json={"text": "fixed", "chunk_index": 1})
        assert (status, body) == (200, {"saved": True, "session_id": SID,
                                        "chunk_index": 1})
    assert save.call_args_list[0].args == (SID,)
    assert save.call_args_list[0].kwargs == {"snippet_id": SNIP,
                                             "chunk_index": None, "text": "fixed"}
    assert save.call_args_list[1].kwargs == {"snippet_id": None,
                                             "chunk_index": 1, "text": "fixed"}


def test_transcript_edit_refusals():
    from routes.v2 import user_sessions as us
    view = us.v2_user_put_transcript_edit
    with _owned_session(), \
            patch.object(db.takes, "get_session_slide_transcripts", return_value=[]), \
            patch("services.slide_word_split.deckless_chunks_from_stx",
                  return_value=["a"]), \
            patch.object(db, "upsert_user_transcript_edit") as save:
        for body, status, code in [
            ({"text": 5, "chunk_index": 0}, 400, "INVALID_INPUT"),
            ({"text": "x"}, 400, "INVALID_INPUT"),
            ({"text": "x", "chunk_index": 0, "snippet_id": SNIP}, 400, "INVALID_INPUT"),
            ({"text": "x", "chunk_index": 3}, 400, "INVALID_INPUT"),
        ]:
            got_status, got = _call(view, SID, method="PUT", json=body)
            assert (got_status, got["code"]) == (status, code), body
    save.assert_not_called()
    with patch.object(db, "v2_get_session_by_id",
                      return_value={"id": SID, "user_id": "someone-else"}):
        assert _call(view, SID, method="PUT", json={"text": "x"})[0] == 404


# ── POST /v2/user/takes/<sid>/feedback-response ─────────────────────────────

def test_a_first_feedback_answer_writes_in_order():
    from routes.v2 import user_sessions as us
    rec = MagicMock()
    rec.insert.return_value = {"outcome": "saved", "row": {"snippet_id": SNIP},
                               "selected_keys": ["k1"]}
    rec.album.return_value = True
    parsed = {"feedback_id": "f-1", "feedback_family": "confident_voice",
              "response": "yes", "snippet_id": None, "candidate_id": "c-1",
              "feedback_membership_id": None, "feedback_exposure_id": None}
    session = {"id": SID, "user_id": USER, "arc_id": ARC}
    with patch.object(db, "v2_get_session_by_id", return_value=session), \
            patch("services.take_feedback_responses.parse_feedback_response",
                  return_value=(dict(parsed), None)), \
            patch.object(db, "insert_take_feedback_self_report", rec.insert), \
            patch("services.ideal_text_feedback_bake.request_rebake_after_answer",
                  rec.rebake), \
            patch("services.take_feedback_responses.canonical_dual_write", rec.canonical), \
            patch.object(db.takes, "get_arc_sessions", return_value=[session]), \
            patch("services.intervention_spend.spend", rec.spend), \
            patch.object(db, "get_snippet_by_id",
                         return_value={"metrics": {"piece": {"slide_index": 2}}}), \
            patch.object(db, "upsert_owner_voice_album_route", rec.album), \
            patch("services.voice_album.refresh_voice_album", rec.refresh), \
            patch("services.judgement_follow_up.follow_up_for_judgement",
                  rec.follow), \
            patch.object(us, "text_update_for_answer", lambda *a, **k: {"t": 1}):
        rec.follow.return_value = "praise"
        status, body = _call(us.v2_post_take_feedback_response, SID,
                             method="POST", json={"any": "thing"})
    assert (status, body) == (200, {"saved": True, "feedback_id": "f-1",
                                    "feedback_family": "confident_voice",
                                    "response": "yes", "follow_up": "praise",
                                    "t": 1})
    assert [c[0] for c in rec.mock_calls] == [
        "insert", "rebake", "canonical", "spend", "album", "refresh", "follow"]
    assert rec.insert.call_args.kwargs == {
        "arc_id": ARC, "take_session_id": SID, "owner_user_id": USER,
        "feedback_id": "f-1", "feedback_family": "confident_voice",
        "response": "yes", "snippet_id": None}
    assert rec.spend.call_args.kwargs == {
        "change_key": "feedback:confident_voice:f-1", "decision": "approved",
        "lane": "feedback:confident_voice", "intervention_type": "NOTICE"}
    assert rec.album.call_args.kwargs == {
        "snippet_id": SNIP, "owner_user_id": USER, "arc_id": ARC,
        "response": ANY, "slide_index": 2}


def test_feedback_answer_refusals():
    from routes.v2 import user_sessions as us
    view = us.v2_post_take_feedback_response
    assert _call(view, "nope", method="POST", json={})[0] == 400
    with patch.object(db, "v2_get_session_by_id",
                      return_value={"id": SID, "user_id": "x", "arc_id": ARC}):
        assert _call(view, SID, method="POST", json={})[:2] == (
            404, {"code": "NOT_FOUND", "error": "Take not found"})
    with patch.object(db, "v2_get_session_by_id",
                      return_value={"id": SID, "user_id": USER, "arc_id": ARC}), \
            patch("services.take_feedback_responses.parse_feedback_response",
                  return_value=({"feedback_id": "f", "feedback_family": "rewrite_clarity",
                                 "response": "keep_wording"}, None)), \
            patch.object(db, "insert_take_feedback_self_report",
                         return_value={"outcome": "conflict"}):
        assert _call(view, SID, method="POST", json={})[:2] == (409, {
            "code": "RESPONSE_ALREADY_FINAL", "error": "This response is already final."})


# ── GET /v2/admin/sessions/<sid> ────────────────────────────────────────────

def test_the_admin_session_read_flattens_turns_and_highlights():
    from routes.v2 import admin
    session = {"id": SID, "user_id": USER, "status": "s", "global_wpm": 120,
               "kpi_score": 3, "needs_admin_review": None,
               "ai_task_alignment_comment": "narr"}
    snippets = [
        {"id": "t2", "turn_number": 2, "transcript": " second ",
         "start_offset_ms": 50, "audio_segment_path": ""},
        {"id": "t1", "turn_number": 1, "question_text": " Why? ",
         "question_tone": "warm", "transcript": "first",
         "audio_segment_path": "p/t1.webm", "duration_ms": 900},
        {"id": "h1", "turn_number": None, "session_id": SID,
         "snippet_type": "star", "source_type": "auto_extracted",
         "transcript": "moment", "start_offset_ms": 1000, "duration_ms": 500,
         "is_skipped": None},
    ]
    with patch.object(db.takes, "get_session_with_global_metrics", return_value=session), \
            patch.object(db, "get_snippets_by_session", return_value=snippets), \
            patch.object(admin, "_resolve_turn_audio_url",
                         side_effect=lambda s: f"turn:{s['id']}"), \
            patch.object(admin, "_resolve_snippet_audio_url",
                         side_effect=lambda s: f"snip:{s['id']}"):
        status, body = _call(admin.v2_admin_get_session, SID)
    assert status == 200
    assert [t["role"] for t in body["turns"]] == ["ai", "user", "user"]
    assert body["turns"][0] == {"role": "ai", "content": "Why?", "tone": "warm",
                                "turn_number": 1}
    assert {k: body["turns"][1][k] for k in (
        "content", "audio_url", "start_offset_ms", "snippet_id")} == {
        "content": "first", "audio_url": "turn:t1", "start_offset_ms": 0,
        "snippet_id": "t1"}
    assert body["turns"][2]["start_offset_ms"] == 50
    assert body["total_turns"] == 3 and body["total_snippets"] == 1
    snip = body["snippets"][0]
    assert {k: snip[k] for k in ("id", "session_id", "user_id", "type",
                                 "audio_url", "is_skipped", "start_time",
                                 "end_time")} == {
        "id": "h1", "session_id": SID, "user_id": None, "type": "star",
        "audio_url": "snip:h1", "is_skipped": False, "start_time": 1.0,
        "end_time": 1.5}
    assert body["global_metrics"]["wpm"] == 120
    assert body["global_metrics"]["needs_admin_review"] is False
    assert body["global_metrics"]["session_kpi_narrative"] == "narr"
    assert {k: body[k] for k in ("id", "user_id", "status")} == {
        "id": SID, "user_id": USER, "status": "s"}


def test_the_admin_session_read_refuses_an_unknown_session():
    from routes.v2 import admin
    with patch.object(db.takes, "get_session_with_global_metrics", return_value=None):
        assert _call(admin.v2_admin_get_session, SID)[:2] == (
            404, {"code": "SESSION_NOT_FOUND", "error": "Session not found."})


# ── POST /v2/internal/journal/community/generate ────────────────────────────

def _journal(pw="pw"):
    from routes import journal
    return patch.object(journal.config, "JOURNAL_ADMIN_PASSWORD", pw)


def test_a_single_format_reroll_inherits_the_siblings_framing():
    from routes import journal
    rec = MagicMock()
    sibling = {"kind": "fear", "pillar": "p"}
    rec.listing.side_effect = [[sibling], [sibling, {"kind": "win"}]]
    rec.upsert.return_value = [{"kind": "win"}]
    with _journal(), \
            patch.object(db, "get_journal_post_by_id",
                         return_value={"id": "p1", "body": "words"}), \
            patch("services.community_content.generate_community_posts",
                  return_value={"posts": 1}) as gen, \
            patch.object(db, "list_journal_community_posts", rec.listing), \
            patch("services.community_content.rows_for_upsert",
                  side_effect=lambda pid, payload, inherit=None: [
                      {"pid": pid, "inherit": inherit}]) as rows, \
            patch.object(db, "upsert_journal_community_posts", rec.upsert), \
            patch("services.community_content.serialize_community_item",
                  side_effect=lambda r: {"k": r["kind"]}):
        status, body = _call(journal.journal_community_generate, peel=False,
                             method="POST", json={"password": "pw", "post_id": " p1 ",
                                                  "formats": ["win", "win"],
                                                  "notes": "n"})
    assert (status, body) == (200, {"items": [{"k": "fear"}, {"k": "win"}]})
    gen.assert_called_once_with({"id": "p1", "body": "words"}, formats=("win",),
                                notes="n")
    rows.assert_called_once_with("p1", {"posts": 1}, inherit=sibling)
    rec.upsert.assert_called_once_with("p1", [{"pid": "p1", "inherit": sibling}])


def test_community_generate_refusals():
    from routes import journal
    view = journal.journal_community_generate
    with _journal():
        assert _call(view, peel=False, method="POST",
                     json={"password": "bad", "post_id": "p"})[0] == 401
        assert _call(view, peel=False, method="POST",
                     json={"password": "pw", "post_id": "p", "formats": ["x"]})[:2] == (
            400, {"code": "INVALID_INPUT",
                  "error": "formats: must be a non-empty subset of myth_bust, fear, win"})
        with patch.object(db, "get_journal_post_by_id", return_value=None):
            assert _call(view, peel=False, method="POST",
                         json={"password": "pw", "post_id": "p"})[:2] == (
                404, {"code": "NOT_FOUND", "error": "post not found"})


def test_cover_generation_refusals():
    """POST /v2/internal/journal/image/generate (its success path is pinned
    by test_journal_image)."""
    from routes import journal
    from services import journal_image as ji
    view = journal.journal_image_generate
    post = {"id": "p1", "title": "T", "body": "B"}
    with _journal(), patch.object(ji, "image_enabled", return_value=True), \
            patch.object(db, "get_journal_post_by_id", return_value=post), \
            patch("services.journal_media.put_bytes") as store:
        with patch.object(db, "get_journal_post_image",
                          return_value={"id": "i9", "journal_post_id": "other"}):
            assert _call(view, peel=False, method="POST", json={
                "password": "pw", "post_id": "p1", "parent_id": "i9"})[:2] == (
                400, {"code": "INVALID_INPUT",
                      "error": "parent_id: belongs to a different post"})
        with patch.object(db, "list_journal_post_images", return_value=[]), \
                patch.object(ji, "generate_cover_image",
                             side_effect=ji.ImageRejected("unsafe")):
            assert _call(view, peel=False, method="POST", json={
                "password": "pw", "post_id": "p1"})[:2] == (
                400, {"code": "IMAGE_REJECTED", "error": "unsafe"})
    store.assert_not_called()


# ── PATCH /v2/life/day/<id> ─────────────────────────────────────────────────

def test_a_one_thing_edit_records_the_accepted_draft():
    from routes import life_routes as life
    import copy
    current = {"id": "d1", "draft_meta": {"one_thing": {"drafted": "x"}}}
    writes = []
    answers = iter([None, {"id": "d1"}])

    def update_day(*args):
        writes.append(copy.deepcopy(args))
        return next(answers)
    with patch.object(life.store, "day_by_id", return_value=current) as read, \
            patch.object(life.store, "update_day", side_effect=update_day), \
            patch.object(life.lp, "serialize_day", side_effect=lambda r: {"day": r["id"]}):
        status, body = _call(life.life_day_update, "d1", method="PATCH", json={
            "one_thing": " Ship it ", "evening_measure": " landed ",
            "ignored": 1})
    assert (status, body) == (200, {"day": {"day": "d1"}})
    read.assert_called_once_with(USER, "d1")
    assert writes[0] == (USER, "d1", {
        "one_thing": " Ship it ", "evening_measure": "landed",
        "draft_meta": {"one_thing": {"drafted": "x", "accepted": "Ship it"}}})
    assert writes[1] == (USER, "d1", {
        "one_thing": " Ship it ",
        "draft_meta": {"one_thing": {"drafted": "x", "accepted": "Ship it"}}})


def test_day_update_refusals():
    from routes import life_routes as life
    view = life.life_day_update
    with patch.object(life.store, "update_day") as update, \
            patch.object(life.store, "day_by_id", return_value=None):
        assert _call(view, "d1", method="PATCH", json={})[:2] == (
            400, {"code": "INVALID_INPUT", "error": "no fields to update"})
        assert _call(view, "d1", method="PATCH", json={"one_thing": " "})[0] == 400
        assert _call(view, "d1", method="PATCH",
                     json={"one_thing_goal_id": "g"})[:2] == (
            404, {"code": "NOT_FOUND", "error": "Not found"})
    update.assert_not_called()


# ── POST /v2/user/profile ───────────────────────────────────────────────────

def test_the_profile_saves_what_was_sent_and_reads_back_the_rest():
    from routes.v2 import user_account as ua
    rec = MagicMock()
    rec.set_profile.return_value = True
    with patch.object(db, "set_user_profile", rec.set_profile), \
            patch.object(db, "get_user_proficient_languages", return_value=["en"]), \
            patch("services.domains.default_domain_vocabulary", return_value={"v": 1}):
        status, body = _call(ua.v2_user_set_profile, method="POST",
                             json={"domain": "sales", "goal": "  win  "})
    assert status == 200
    assert {k: body[k] for k in ("domain", "goal", "proficient_languages")} == {
        "domain": "sales", "goal": "win", "proficient_languages": ["en"]}
    rec.set_profile.assert_called_once_with(USER, domain="sales", goal="win")


def test_profile_refusals():
    from routes.v2 import user_account as ua
    view = ua.v2_user_set_profile
    with patch.object(db, "set_user_profile") as save:
        assert _call(view, method="POST", json={"domain": "x"})[0] == 422
        assert _call(view, method="POST", json={"goal": 5})[:2] == (
            422, {"code": "INVALID_INPUT", "error": "goal: must be a string"})
        assert _call(view, method="POST", json={"goal": "g" * 501})[0] == 422
    save.assert_not_called()
