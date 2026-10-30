"""
STORY    As a speaker, I want the Ideal Text routes (read, extras, earlier-Take
         decision, paragraph lock, helper words and my own edits) to answer
         exactly as they did before the code was moved into services, so that
         the loop never breaks.
OUTCOME
  O1  Reading my Ideal Text returns the same full answer and records, in
      order, what I was shown; someone else's project is "not found".
  O2  The extras (notes, history, entitlement) are served for the current
      version only, with no caching; a missing, unknown, outdated or wrong
      request gets its exact refusal.
  O3  Accepting an earlier Take's text, locking a paragraph and picking or
      skipping helper words each write their records in the same order; every
      refusal returns its exact code and writes nothing.
  O4  My own edit is saved through the one safe writer and published; a bad,
      outdated or failed edit returns its exact code (a database refusal is a
      409) and publishes nothing.
PROVES   O1 -> test_the_notebook_read_composes_locks_and_prepares_the_exposure,
               test_the_notebook_read_refuses_a_project_not_owned
         O2 -> test_enrichment_serves_the_asked_sections_for_the_current_snapshot,
               test_enrichment_refusals
         O3 -> test_an_accepted_prior_take_writes_in_order, test_prior_take_refusals,
               test_a_lock_writes_the_lock_its_record_and_the_canonical_decision,
               test_lock_refusals, test_a_root_pick_and_a_skip_write_their_records,
               test_root_refusals
         O4 -> test_a_current_edit_is_saved_through_the_one_cas_writer,
               test_user_edit_refusals,
               test_a_typed_ideal_text_refusal_from_the_database_is_a_409
WHY      Founder 2026-10-12: move logic out of the routes; Never-rule 3.
"""
from __future__ import annotations

import inspect
import itertools
import uuid
from unittest.mock import MagicMock, patch

import pytest

try:
    from flask import Flask, request

    from config import Config
    from routes.v2 import explore_ideal_text as route
    from services.db import db
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    _IMPORT_ERROR = e

pytestmark = pytest.mark.skipif(_IMPORT_ERROR is not None,
                                reason=f"needs app deps: {_IMPORT_ERROR}")

ARC = "aaaaaaaa-0000-4000-8000-000000000001"
TAKE = "bbbbbbbb-0000-4000-8000-000000000002"
USER = "cccccccc-0000-4000-8000-000000000003"
PA, PB, PC = (f"11111111-1111-4111-8111-11111111111{i}" for i in (1, 2, 3))
SESSIONS = [{"id": TAKE, "arc_id": ARC, "take_index": 1,
             "recording_kind": "spoken", "analysis_state": "ready",
             "owner_principal_id": "pp-1", "project_id": ARC,
             "intake_context": {"topic": "Board pitch"},
             "created_at": "2026-10-01T00:00:00Z"}]


class _Unstubbed:
    """``db.client`` for these tests: every raw call fails, as in CI."""

    def __getattr__(self, name):
        def call(*_a, **_k):
            raise RuntimeError(f"unstubbed db.client.{name}")
        return call


def _call(view, *args, owned=True, query="", **ctx):
    app = Flask(__name__)
    with app.test_request_context("/" + query, **ctx), \
            patch.object(db, "client", _Unstubbed()), \
            patch.object(route, "_arc_owned_by_caller",
                         return_value=(owned, SESSIONS if owned else [])):
        request.user_id = USER
        out = inspect.unwrap(view)(*args)
    resp, status = out if isinstance(out, tuple) else (out, 200)
    return status, resp.get_json(), resp


# ── GET /explore/arc/<arc>/ideal-text ───────────────────────────────────────

MACHINE = "Para one new.\n\nPara two.\n\nPara three new."


def test_the_notebook_read_composes_locks_and_prepares_the_exposure():
    row = {"arc_id": ARC, "text": MACHINE, "auto_text": MACHINE,
           "updated_by": None, "approved_at": None, "version": 2,
           "updated_at": "2026-10-02T00:00:00Z"}
    stored = [{"id": PA, "ord": 0, "text": "Para one old.", "locked_at": None},
              {"id": PB, "ord": 1, "text": "My typed two.",
               "locked_at": "2026-10-01T10:00:00Z"},
              {"id": PC, "ord": 2, "text": "Para three old.", "locked_at": None}]
    counter = itertools.count(1)
    rec = MagicMock()
    rec.replace.return_value = True
    rec.expose.return_value = {"handle": "h-1"}
    with patch.object(route, "_moments_entitled", return_value=True), \
            patch.object(route, "_moment_explanations_map", return_value={}), \
            patch.object(route, "_moment_playback_map", return_value={}), \
            patch.object(db.ideal_text, "get_coach_arc_ideal_text", return_value=row), \
            patch.object(db, "get_user_ideal_edit", return_value=None), \
            patch.object(db, "get_ideal_text_parts", return_value=stored), \
            patch.object(db, "replace_ideal_text_parts", rec.replace), \
            patch.object(db, "get_user_arc_ideal_notes", return_value="my notes"), \
            patch.object(db, "list_intervention_decision_history",
                         return_value=[{"d": 1}]), \
            patch("services.learning_exposures.prepare_ideal_text_presentation",
                  rec.expose), \
            patch("uuid.uuid4", side_effect=lambda: uuid.UUID(int=next(counter))):
        status, body, _ = _call(route.v2_explore_get_ideal_text, ARC)
    new1, new3 = str(uuid.UUID(int=1)), str(uuid.UUID(int=2))
    parts = [{"id": new1, "locked": False, "ord": 0, "text": "Para one new."},
             {"id": PB, "iteration": 0, "locked": True, "ord": 1,
              "text": "My typed two."},
             {"id": new3, "locked": False, "ord": 2, "text": "Para three new."}]
    text = "Para one new.\n\nMy typed two.\n\nPara three new."

    def piece(key, words):
        return {"block_key": None, "challenger": None, "piece_key": key,
                "root_phrase": None, "root_type": None, "slide_index": None,
                "snippet_id": None, "status": "settled", "take_index": None,
                "take_session_id": None, "text": words}
    assert status == 200
    assert body == {
        "arc_id": ARC, "can_record_take": True, "decision_history": [{"d": 1}],
        "explanations_available": False, "journey_next_steps_seen": False,
        "key_moments": [], "latest_take_session_id": TAKE,
        "learning_exposure": {"handle": "h-1"}, "moments_unlocked": True,
        "has_deck": False, "project_archived": False,
        "notes": "my notes", "notes_text": "my notes", "user_notes": "my notes",
        "parts": parts,
        "pieces": [piece(0, "Para one new."), piece(1, "My typed two."),
                   piece(2, "Para three new.")],
        "presentation_ref": None, "price_tokens": 2500, "slide_titles": [],
        "status": "unverified", "take_count": 1, "text": text,
        "title": "Board pitch", "updated_at": "2026-10-02T00:00:00Z",
        "user_edited": False, "version": 2,
    }
    assert [c[0] for c in rec.mock_calls] == ["replace", "expose"]
    rec.replace.assert_called_once_with(ARC, USER, [
        {"id": new1, "text": "Para one new.", "locked": False, "ord": 0,
         "locked_at": None},
        {"id": PB, "ord": 1, "text": "My typed two.", "locked": True,
         "iteration": 0, "locked_at": "2026-10-01T10:00:00Z"},
        {"id": new3, "text": "Para three new.", "locked": False, "ord": 2,
         "locked_at": None}])
    rec.expose.assert_called_once_with(
        database=db, owner_principal_id="pp-1", project_id=ARC, take_id=TAKE,
        actor_id=USER, text=text, version=2, take_count=1, title="Board pitch",
        parts=parts, delivery_mode="canary")


def test_the_notebook_read_refuses_a_project_not_owned():
    status, body, _ = _call(route.v2_explore_get_ideal_text, ARC, owned=False)
    assert (status, body) == (404, {"code": "NOT_FOUND", "error": "arc not found"})


# ── GET /explore/arc/<arc>/ideal-text/enrichment ────────────────────────────

SNAP = {"id": "snap-1", "payload": {"latest_take_session_id": TAKE,
                                    "take_count": 1, "text": "T"},
        "enrichment_seed": {"moments": []}}


def test_enrichment_serves_the_asked_sections_for_the_current_snapshot():
    with patch.object(db, "get_ideal_text_document_core", return_value=SNAP), \
            patch.object(db, "get_ideal_text_document_snapshot", return_value=SNAP), \
            patch.object(db, "get_user_arc_ideal_notes", return_value="n"), \
            patch.object(db, "list_intervention_decision_history",
                         return_value=[{"d": 1}]), \
            patch.object(route, "_moments_entitled", return_value=False):
        status, body, resp = _call(
            route.v2_explore_get_ideal_text_enrichment, ARC,
            query="?document_snapshot_id=snap-1&sections=notes,history,entitlement")
    assert status == 200
    assert body == {"document_snapshot_id": "snap-1", "sections": {
        "notes": {"status": "ready", "data": {"notes_text": "n"}},
        "history": {"status": "ready",
                    "data": {"decision_history": [{"d": 1}]}},
        "entitlement": {"status": "ready", "data": {
            "moments_unlocked": False, "price_tokens": 2500}}}}
    assert resp.headers["Cache-Control"] == "private, no-store"
    assert resp.headers["Server-Timing"].startswith("ideal_enrichment;dur=")
    assert "section_notes;dur=" in resp.headers["Server-Timing"]


def test_enrichment_refusals():
    view = route.v2_explore_get_ideal_text_enrichment
    assert _call(view, ARC, owned=False)[:2] == (
        404, {"code": "NOT_FOUND", "error": "arc not found"})
    assert _call(view, ARC)[:2] == (400, {
        "code": "SNAPSHOT_REQUIRED", "error": "document_snapshot_id is required"})
    with patch.object(db, "get_ideal_text_document_core", return_value=SNAP), \
            patch.object(db, "get_ideal_text_document_snapshot", return_value=None):
        assert _call(view, ARC, query="?document_snapshot_id=snap-0")[:2] == (
            404, {"code": "SNAPSHOT_NOT_FOUND"})
    with patch.object(db, "get_ideal_text_document_core",
                      return_value={**SNAP, "id": "snap-2"}), \
            patch.object(db, "get_ideal_text_document_snapshot", return_value=SNAP):
        assert _call(view, ARC, query="?document_snapshot_id=snap-1")[:2] == (
            409, {"code": "SNAPSHOT_STALE", "current_document_snapshot_id": "snap-2"})
    with patch.object(db, "get_ideal_text_document_core", return_value=SNAP), \
            patch.object(db, "get_ideal_text_document_snapshot", return_value=SNAP):
        assert _call(view, ARC, query="?document_snapshot_id=snap-1&sections=x,notes")[:2] == (
            400, {"code": "INVALID_ENRICHMENT_SECTION", "sections": ["x"]})


# ── POST /explore/arc/<arc>/prior-take/decide ───────────────────────────────

def test_an_accepted_prior_take_writes_in_order():
    rec = MagicMock()
    rec.ledger.return_value = True
    with patch.object(Config, "LIVING_TRANSCRIPT_ENABLED", True), \
            patch.object(db.ideal_text, "get_coach_arc_ideal_text",
                         return_value={"version": 3}), \
            patch.object(db, "upsert_ideal_decision", rec.ledger), \
            patch("services.intervention_spend.spend", rec.spend), \
            patch("services.ideal_text_feedback_bake._bake_enabled",
                  return_value=False), \
            patch.object(route, "_reassemble_after_decision", rec.reassemble):
        status, body, _ = _call(
            route.v2_explore_decide_prior_take, ARC, method="POST",
            json={"action": "accept", "snippet_id": "s1", "quote": " Old Words ",
                  "proposed_text": " new words ", "why_key": "w"})
    assert (status, body) == (200, {"saved": True})
    assert [c[0] for c in rec.mock_calls] == ["ledger", "spend", "reassemble"]
    rec.ledger.assert_called_once_with(
        arc_id=ARC, kind="replace", target_phrase="old words",
        display_phrase="Old Words", replacement_text="new words",
        decision="approved", source="prior_take", snippet_id="s1", version=3)
    rec.spend.assert_called_once_with(
        db, ARC, SESSIONS, change_key="prior_take:old words",
        decision="approved", lane="lane:prior_take", intervention_type="REWRITE",
        quote="Old Words", proposed_text="new words", why_key="w")
    rec.reassemble.assert_called_once_with(ARC)


def test_prior_take_refusals():
    view = route.v2_explore_decide_prior_take
    with patch.object(Config, "LIVING_TRANSCRIPT_ENABLED", False):
        assert _call(view, ARC, method="POST", json={})[:2] == (
            404, {"code": "NOT_FOUND", "error": "not found"})
    with patch.object(Config, "LIVING_TRANSCRIPT_ENABLED", True), \
            patch.object(db, "upsert_ideal_decision") as ledger:
        assert _call(view, ARC, method="POST", json={"action": "x"})[:2] == (
            400, {"code": "INVALID_INPUT", "error": "action must be accept or keep"})
        assert _call(view, ARC, method="POST",
                     json={"action": "accept", "quote": "q", "snippet_id": "s"})[:2] == (
            400, {"code": "INVALID_INPUT", "error": "proposed_text is required"})
    ledger.assert_not_called()


# ── PUT /explore/arc/<arc>/parts/<part>/lock and /root ──────────────────────

DOC = "First words here.\n\nSecond words here."
STORED = [{"id": PA, "ord": 0, "text": "First words here.", "locked_at": None,
           "iteration": 2},
          {"id": PB, "ord": 1, "text": "Second words here.", "locked_at": None}]


def _part_writes(rec):
    return [
        patch.object(db, "get_ideal_text_parts", return_value=STORED),
        patch.object(db, "v2_get_session_by_id",
                     return_value={"id": TAKE, "project_id": "proj-1"}),
        patch.object(db, "get_latest_ideal_text_part_revision",
                     return_value={"id": 7, "action": "owner_part_created"}),
        patch("services.slide_helper_words._apply", rec.helper_words),
        patch("services.ideal_text_core_snapshot.publish_for_arc", rec.publish),
    ]


def test_a_lock_writes_the_lock_its_record_and_the_canonical_decision():
    rec = MagicMock()
    rec.lock.return_value = True
    w = _part_writes(rec)
    with w[0], w[1], w[2], w[3], w[4], \
            patch.object(db, "set_ideal_text_part_lock", rec.lock), \
            patch.object(db, "record_canonical_paragraph_decision", rec.canonical), \
            patch("services.rooting_phrase.propose_rooting_phrase",
                  return_value={"text": "words"}):
        status, body, _ = _call(route.v2_explore_set_part_lock, ARC, PA.upper(),
                                method="PUT",
                                json={"locked": True, "text_echo": f" {DOC} "})
    assert (status, body) == (200, {"locked": True, "part_id": PA.upper(),
                                    "root_phrase_proposal": {"text": "words"}})
    assert [c[0] for c in rec.mock_calls] == [
        "lock", "helper_words", "canonical", "publish"]
    rec.lock.assert_called_once_with(ARC, USER, PA.upper(), True,
                                     revision_action=None)
    assert rec.helper_words.call_args.args[:4] == (db, ARC, USER, PA.upper())
    decision = rec.canonical.call_args.args[0]
    assert decision is not None
    rec.publish.assert_called_once_with(db, ARC, USER)


def test_lock_refusals():
    view = route.v2_explore_set_part_lock
    with patch.object(db, "get_ideal_text_parts", return_value=STORED), \
            patch.object(db, "set_ideal_text_part_lock") as lock:
        assert _call(view, ARC, PA, method="PUT", json={"locked": "y"})[:2] == (
            400, {"code": "INVALID_INPUT", "error": "locked must be a boolean"})
        assert _call(view, ARC, PA, method="PUT",
                     json={"locked": True, "text_echo": "Another document."})[:2] == (
            409, {"code": "STALE_DOCUMENT", "error": "document moved"})
        assert _call(view, ARC, PC, method="PUT",
                     json={"locked": True, "text_echo": DOC})[:2] == (
            404, {"code": "NOT_FOUND", "error": "part not found"})
        assert _call(view, ARC, PA, method="PUT",
                     json={"locked": True, "text_echo": DOC,
                           "reason": "keep_evolving"})[:2] == (
            400, {"code": "INVALID_INPUT", "error": "keep_evolving requires unlocked"})
    lock.assert_not_called()


def test_a_root_pick_and_a_skip_write_their_records():
    rec = MagicMock()
    rec.root.return_value = True
    w = _part_writes(rec)
    with w[0], w[1], w[2], w[3], w[4], \
            patch.object(db, "set_ideal_text_part_root", rec.root), \
            patch.object(db, "record_canonical_root_phrase", rec.canonical), \
            patch.object(db, "record_canonical_root_phrase_skip", rec.skip):
        status, body, _ = _call(route.v2_explore_set_part_root, ARC, PA,
                                method="PUT",
                                json={"text_echo": DOC, "phrase": "words",
                                      "start": 6, "end": 11})
        assert (status, body) == (200, {"saved": True, "part_id": PA,
                                        "root_phrase": "words", "root_start": 6,
                                        "root_end": 11})
        status, body, _ = _call(route.v2_explore_set_part_root, ARC, PA,
                                method="PUT", json={"text_echo": DOC})
        assert (status, body) == (200, {"saved": True, "part_id": PA,
                                        "root_phrase": None, "root_start": None,
                                        "root_end": None})
    assert [c[0] for c in rec.mock_calls] == [
        "root", "helper_words", "canonical", "publish",
        "root", "helper_words", "skip", "publish"]
    assert rec.root.call_args_list[0].kwargs == {
        "arc_id": ARC, "user_id": USER, "part_id": PA, "phrase": "words",
        "start": 6, "end": 11}
    assert rec.helper_words.call_args.args[:4] == (db, ARC, USER, PA)


def test_root_refusals():
    view = route.v2_explore_set_part_root
    with patch.object(db, "get_ideal_text_parts", return_value=STORED), \
            patch.object(db, "set_ideal_text_part_root") as root:
        assert _call(view, ARC, PA, method="PUT", json={})[:2] == (
            400, {"code": "INVALID_INPUT", "error": "text_echo is required"})
        assert _call(view, ARC, PA, method="PUT",
                     json={"text_echo": "Moved."})[:2] == (
            409, {"code": "STALE_DOCUMENT", "error": "document moved"})
        assert _call(view, ARC, PA, method="PUT",
                     json={"text_echo": DOC, "start": 1})[:2] == (
            400, {"code": "INVALID_INPUT", "error": "skip must not include a span"})
        assert _call(view, ARC, PA, method="PUT",
                     json={"text_echo": DOC, "phrase": "absent", "start": 0,
                           "end": 6})[:2] == (
            400, {"code": "INVALID_ROOT_PHRASE",
                  "error": "Choose exact words from this paragraph."})
    root.assert_not_called()


# ── PUT /explore/arc/<arc>/ideal-text/user-edit (the current CAS shape) ─────

HASH = "a" * 64


def _cas_body(**over):
    body = {"text": "<b>One</b>\n\nTwo", "version": 3,
            "expected_user_text_revision": "4", "expected_user_text_sha256": HASH,
            "idempotency_key": "op-1",
            "parts": {"expected_parts": [
                {"position": 0, "part_id": PA, "text_sha256": HASH,
                 "locked": False, "current_part_revision_id": "9"}],
                "desired_parts": [{"position": 0, "part_id": PA, "text": "One"},
                                  {"position": 1, "part_id": PB, "text": "Two"}]}}
    body.update(over)
    return body


def _cas_result():
    return {"ideal_text_user_edit_contract_version": "ideal-text-user-edit-cas-v2",
            "saved": True, "arc_id": ARC, "source_document_version": 3,
            "previous_user_text_revision": "4", "result_user_text_revision": "5",
            "result_user_text_sha256": HASH, "desired_parts_lineage_sha256": HASH,
            "part_revisions": [
                {"part_id": PA, "revision_id": "10",
                 "action": "owner_part_text_updated", "previous_position": 0,
                 "result_position": 0},
                {"part_id": PB, "revision_id": "11", "action": "owner_part_created",
                 "previous_position": None, "result_position": 1}],
            "dataset_eligible": False}


def test_a_current_edit_is_saved_through_the_one_cas_writer():
    rec = MagicMock()
    rec.cas.return_value = _cas_result()
    with patch.object(db, "compare_and_set_user_ideal_edit", rec.cas), \
            patch("services.ideal_text_core_snapshot.publish_for_arc", rec.publish):
        status, body, _ = _call(route.v2_explore_put_ideal_user_edit, ARC,
                                method="PUT", json=_cas_body())
    assert (status, body) == (200, _cas_result())
    assert [c[0] for c in rec.mock_calls] == ["cas", "publish"]
    rec.cas.assert_called_once_with(
        owner_user_id=USER, arc_id=ARC, source_document_version=3,
        expected_user_text_revision=4, expected_user_text_sha256=HASH,
        desired_user_text="One\n\nTwo",
        desired_parts_lineage=_cas_body()["parts"], idempotency_key="op-1")


def test_user_edit_refusals():
    view = route.v2_explore_put_ideal_user_edit
    rec = MagicMock()
    with patch.object(db, "compare_and_set_user_ideal_edit", rec.cas), \
            patch("services.ideal_text_core_snapshot.publish_for_arc", rec.publish):
        cases = [
            (_cas_body(extra=1), 400, {"code": "INVALID_INPUT",
                                       "error": "request keys invalid"}),
            (_cas_body(text="<i></i>"), 400, {"code": "IDEAL_TEXT_EMPTY_EDIT_REJECTED"}),
            (_cas_body(expected_user_text_revision="04"), 400,
             {"code": "INVALID_INPUT", "error": "revision must be a bigint string"}),
            (_cas_body(parts={"expected_parts": [], "desired_parts": [
                {"position": 0, "part_id": "not-a-uuid", "text": "x"}]}), 400,
             {"code": "INVALID_INPUT", "error": "part_id invalid"}),
        ]
        for body, status, payload in cases:
            assert _call(view, ARC, method="PUT", json=body)[:2] == (status, payload)
        rec.cas.assert_not_called()
        rec.cas.return_value = {**_cas_result(), "saved": False}
        assert _call(view, ARC, method="PUT", json=_cas_body())[:2] == (
            500, {"code": "V2_ERROR", "error": "Failed to save"})
        with patch.object(db.ideal_text, "get_coach_arc_ideal_text",
                          return_value={"auto_text": "m", "version": 4}):
            assert _call(view, ARC, method="PUT",
                         json={"text": "One", "version": 3})[:2] == (
                409, {"code": "VERSION_SUPERSEDED", "current_version": 4})
    rec.publish.assert_not_called()


def test_a_typed_ideal_text_refusal_from_the_database_is_a_409():
    """Founder 2026-10-12, option 1: the edit database's IDEAL_TEXT_*
    refusals answer 409 with their code (the app reads the "document moved"
    ones as a supersede and the rest as a failed save)."""
    with patch.object(db, "compare_and_set_user_ideal_edit",
                      side_effect=RuntimeError("IDEAL_TEXT_PART_REQUIRES_UNLOCK")), \
            patch("services.ideal_text_core_snapshot.publish_for_arc") as publish:
        assert _call(route.v2_explore_put_ideal_user_edit, ARC, method="PUT",
                     json=_cas_body())[:2] == (
            409, {"code": "IDEAL_TEXT_PART_REQUIRES_UNLOCK"})
    publish.assert_not_called()
