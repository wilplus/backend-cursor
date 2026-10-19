"""Every draft keeps its prompt (0479; founder 2026-10-19, decisions log N79).

A model draft shown to a coach used to live only on the row it was shown
from, and a re-draft replaced it; the answer surfaces kept nothing of what
their prompt was sent. Pins, on the public services the routes call:

  * every answer draft (services.coach_request_drafts.draft_for_request) is
    kept, a re-draft beside the first, with the sha256 of exactly the
    system and user text the model was sent, what the prompt was given
    (the passage as sent, the kind, the spotted labels and tag ids, the
    coach's notes) and the surface's prompt lock; the request row's
    ``draft_prompt`` is written and names the latest draft;
  * the coach's save settles the draft the row carries: kept as written or
    not; an earlier, replaced draft stays unsettled;
  * a Take-word draft is kept on its Take and word the same way, and the
    word's save settles it.
"""
from __future__ import annotations

import hashlib
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from services import coach_request_drafts as crd
from services import coach_take_word as ctw
from services import coach_word_pairs as cwp
from services import exercise_coach_requests as ecr
from services.ml_surface_contracts import locked_prompt_hash

REQUEST_ID = "6f1d2c3b-4a5e-4f60-8a7b-9c0d1e2f3a4b"


class _Db:
    """The request, the coach's word, the kept drafts and the pairs, in
    memory: just enough of services.db for a draft and its save."""

    def __init__(self):
        self.request = {"id": REQUEST_ID, "take_session_id": "take-1",
                        "snippet_id": "snip-1", "owner_user_id": "speaker-1",
                        "kind": "praise", "reason": "nothing_spotted",
                        "observed_tags": ["rushing"], "resolution": None}
        self.word: dict = {}
        self.drafts: list = []
        self.pairs: list = []

    # what the drafters read
    def get_snippets_by_session(self, take):
        return [{"id": "snip-1", "transcript": "and that   is why the number matters"}]

    def list_speaking_errors(self, active_only=True):
        return [{"error_id": "rushing", "label": "Rushing"}]

    def list_bookmarked_snippet_ids(self, take):
        return ["snip-1"]

    def get_own_state_ratings_for_session(self, take, coach):
        return {"snip-1": {"value": "yes"}}

    def v2_get_session_by_id(self, sid):
        return {"id": sid, "user_id": "speaker-1"}

    # the rows a draft is shown from
    def set_exercise_coach_request_draft(self, *, request_id, surface, text,
                                         model_version, prompt=None):
        self.request.update(draft_surface=surface, draft_text=text,
                            draft_model_version=model_version, draft_prompt=prompt)
        return dict(self.request)

    def set_coach_take_word_draft(self, *, take_session_id, coach_id, text,
                                  model_version, prompt=None):
        self.word.update(id="word-1", take_session_id=take_session_id, coach_id=coach_id,
                         draft_text=text, draft_model_version=model_version,
                         draft_prompt=prompt)
        return dict(self.word)

    # the history
    def insert_coach_draft(self, **fields):
        self.drafts.append({**fields, "settled_at": None, "final_unchanged": None})
        return self.drafts[-1]

    def settle_coach_draft(self, *, draft_id, final_unchanged, settled_at):
        for row in self.drafts:
            if row["id"] == draft_id:
                row.update(settled_at=settled_at, final_unchanged=final_unchanged)
                return row
        return None

    # the saves
    def resolve_exercise_coach_request(self, **kwargs):
        return {**self.request, "resolution": kwargs["resolution"],
                "answer_text": kwargs.get("answer_text"), "resolved_by": kwargs["coach_id"],
                "shared_at": None}

    def upsert_coach_take_word(self, *, take_session_id, coach_id, text, video_ref, share,
                               keep_video=False):
        self.word.update(take_session_id=take_session_id, coach_id=coach_id, text=text,
                         updated_at="now")
        if not keep_video:  # a save that names no video keeps the saved one
            self.word["video_ref"] = video_ref
        return dict(self.word)

    def list_diagnostic_exercises(self):
        return []

    # the pairs and the consent ledger
    def insert_feedback_pair(self, **fields):
        self.pairs.append(fields)
        return {"id": f"pair-{len(self.pairs)}", **fields}

    def record_take_word_pair(self, **fields):
        self.pairs.append(fields)
        return {"id": f"pair-{len(self.pairs)}", **fields}

    def get_owner_principal_for_user(self, user_id):
        return None


def _sha(system, user):
    """The documented formula (migration 0479): sha256 of the UTF-8 JSON
    array [system, user], no spaces, no ASCII escaping."""
    sent = json.dumps([system, user], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(sent.encode("utf-8")).hexdigest()


def _model(replies, sent):
    replies = iter(replies)

    def chat_complete(**kwargs):
        sent.append((kwargs["system"], kwargs["user"]))
        return SimpleNamespace(text=next(replies), model="model-a")
    return chat_complete


class EveryDraftKeepsItsPromptTests(unittest.TestCase):

    def test_every_answer_draft_is_kept_with_what_it_was_sent_and_the_save_settles_it(self):
        db, sent = _Db(), []
        with patch("services.llm.chat_complete",
                   side_effect=_model(["You let the number land.",
                                       "The pause before the number worked."], sent)):
            for _ in range(2):
                status, _payload = crd.draft_for_request(
                    db, dict(db.request), {"notes": "Name the pause."}, coach_id="coach-1")
                self.assertEqual(status, 200)
        self.assertEqual([d["draft_text"] for d in db.drafts],
                         ["You let the number land.", "The pause before the number worked."])
        for (system, user), kept in zip(sent, db.drafts):
            self.assertEqual(kept["prompt_sha256"], _sha(system, user))
            self.assertEqual(kept["prompt_inputs"], {
                "passage_text": "and that is why the number matters", "kind": "praise",
                "spotted": ["Rushing"], "spotted_tags": ["rushing"],
                "notes": "Name the pause."})
            self.assertEqual(
                {k: kept[k] for k in ("surface", "prompt_family", "coach_id", "owner_user_id",
                                      "take_session_id", "snippet_id", "request_id",
                                      "take_word_id", "model_version", "prompt_lock_sha256")},
                {"surface": "praise_line", "prompt_family": "coach_answer_drafts",
                 "coach_id": "coach-1", "owner_user_id": "speaker-1",
                 "take_session_id": "take-1", "snippet_id": "snip-1",
                 "request_id": REQUEST_ID, "take_word_id": None, "model_version": "model-a",
                 "prompt_lock_sha256": locked_prompt_hash("praise_line")})
        # The row's snapshot is written for an answer draft too, and names
        # the draft it carries.
        self.assertEqual(db.request["draft_prompt"]["draft_id"], db.drafts[1]["id"])
        self.assertEqual(db.request["draft_prompt"]["prompt_context"]["prompt"],
                         "coach_answer_drafts")

        status, _payload = ecr.resolve_request(
            db, dict(db.request), {"resolution": "line_written",
                                   "answer_text": "The pause before the number worked.",
                                   "file_in_catalogue": False}, "coach-1")
        self.assertEqual(status, 200)
        self.assertEqual([(d["settled_at"] is not None, d["final_unchanged"]) for d in db.drafts],
                         [(False, None), (True, True)])

    def test_a_take_word_draft_is_kept_on_its_take_and_the_word_s_save_settles_it(self):
        db, sent = _Db(), []
        with patch("services.llm.chat_complete",
                   side_effect=_model(["Slow down at the number."], sent)):
            status, _payload = cwp.draft_take_word(db, take_session_id="take-1",
                                                   coach_id="coach-1", body={"notes": "pace"})
        self.assertEqual(status, 200)
        [kept] = db.drafts
        self.assertEqual(kept["prompt_sha256"], _sha(*sent[0]))
        self.assertEqual(kept["prompt_inputs"], {
            "passage_text": "and that is why the number matters", "coach_text": "pace"})
        self.assertEqual(
            {k: kept[k] for k in ("surface", "prompt_family", "owner_user_id",
                                  "take_session_id", "take_word_id", "request_id")},
            {"surface": "coach_take_word", "prompt_family": "coach_word_drafts",
             "owner_user_id": "speaker-1", "take_session_id": "take-1",
             "take_word_id": "word-1", "request_id": None})

        ctw.save_take_word(db, take_session_id="take-1", coach_id="coach-1",
                           body={"text": "Pause before the number."})
        self.assertIsNotNone(kept["settled_at"])
        self.assertIs(kept["final_unchanged"], False)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
