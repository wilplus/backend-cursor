"""
STORY    As a speaker, I want every chat turn saved with its buttons, so that
         my chat bubbles never disappear when I reload.
OUTCOME
  O1  POST /v2/chat/query with persist writes my row and the bot's row,
      with the bot's choices in its metadata; posting the same turn again
      writes the same two ids, so the table keeps it once.
  O2  A reload (GET /v2/user/lounge/messages) brings the bot's choices back.
  O3  If the durable turn claim cannot be saved, the composer receives an
      explicit terminal retry state and no model or stateful handler runs.
  O4  The bot's reply is saved under my turn even when my browser's clock
      runs ahead of the server's, so a reload keeps the order I saw.
  O5  A typed answer to Will's open practice question is stored in the talk
      and memory, answered by contextual Will from that question and screen,
      and persisted with the settling metadata before the chain advances once.
  O6  A retry with the same turn id replays its completed terminal result
      without another model/state/charge path; the same words with a fresh id
      are a new turn. A changed payload with the same id is rejected instead
      of being attached to the earlier answer.
  O7  A concurrent retry sees the durable pending claim and settles with an
      explicit retry state without running a second model/state/charge path.
      A bot-write failure is retained as a terminal receipt so the same id
      cannot run those side effects again; a committed answer whose write
      acknowledgement is lost, or whose later best-effort follow-on fails,
      remains the successful answer. An optimistic bubble's surrounding
      whitespace does not stop it from being claimed.
  O8  A completed walk closing is neither model context nor a response to a
      later unrelated chat message; structured reply metadata survives retry.
PROVES   O1, O2 -> test_a_turn_is_saved_once_and_its_choices_come_back
         O3     -> test_a_claim_failure_is_terminal_without_running_the_turn
         O4     -> test_the_reply_is_saved_under_the_turn_it_answers
         O5     -> test_a_typed_practice_answer_is_contextual_and_settles_once
         O6     -> test_a_correlated_retry_replays_once_and_a_new_id_is_a_new_turn,
                   test_an_optimistic_row_keeps_its_words_and_metadata_until_its_owner_claims_it,
                   test_a_reused_bot_row_cannot_become_a_user_turn_claim
         O7     -> test_a_pending_claim_and_a_failed_receipt_never_reexecute_a_turn,
                   test_a_committed_bot_write_with_a_lost_acknowledgement_replays_successfully,
                   test_a_post_persist_follow_on_failure_replays_the_same_success,
                   test_an_optimistic_whitespace_bubble_can_be_claimed_once,
                   test_an_unexpected_accepted_turn_error_is_still_a_renderable_terminal
         O8     -> test_a_turn_is_saved_once_and_its_choices_come_back,
                   test_a_completed_walk_closing_cannot_answer_a_later_question
WHY      Founder #2: bubbles must never disappear; founder 2026-10-20: the
         chat keeps the order it shows. The harness is
         tests/chat_route_fakes.py; what the chat answers is pinned in
         test_chat_answers.py.
"""
from __future__ import annotations

import uuid
from unittest.mock import patch

from tests.chat_route_fakes import CHOICE, USER, ChatRouteHarness


class ChatTurnPersistsTests(ChatRouteHarness):
    __test__ = True

    def test_project_follow_up_stays_scoped_and_retries_without_another_answer(self):
        metadata = {"project_chat": True, "arc_id": "arc-a", "take_session_id": "take-a"}
        reply = {"answer": "Your closing already names the decision.",
                 "row_metadata": metadata}
        turn = {"question": "How can I close this?", "arc_id": "arc-a",
                "session_id": "take-a", "place": "speaking", "persist": True,
                "client_id": str(uuid.uuid4())}
        with patch("services.project_chat.answer", return_value=(reply, "project_chat")) as answer:
            first = self.post(turn).get_json()
            replay = self.post(turn).get_json()
        self.assertEqual(answer.call_count, 1)
        self.assertTrue(first["persisted"])
        self.assertEqual(replay["answer"], first["answer"])
        self.assertTrue(replay["replayed"])
        for row in self.rows[-1][1]:
            self.assertEqual(row["metadata"]["arc_id"], "arc-a")
        self.assertEqual(len(self.charges), 1)

    def test_speaking_coach_never_consumes_a_project_question(self):
        from routes.v2 import coaching
        with (
            patch.object(coaching.config, "SPEAKING_COACH_ENABLED", True),
            patch("services.will_question.chat_turn",
                  side_effect=AssertionError("Project question consumed in Coach")),
            patch("services.feedback_check.chat_turn",
                  side_effect=AssertionError("Project feedback answer consumed in Coach")),
            patch("services.speaking_coach.answer",
                  return_value=({"answer": "Your examples make the idea concrete."}, {"route": "longitudinal"})),
        ):
            body = self.post({"question": "What is my strongest point?",
                              "place": "speaking", "persist": True,
                              "client_id": str(uuid.uuid4())}).get_json()
        self.assertEqual(body["answer"], "Your examples make the idea concrete.")
        self.assertTrue(body["persisted"])

    def test_a_turn_is_saved_once_and_its_choices_come_back(self):
        turn = {
            "question": "replace my deck", "persist": True,
            "client_id": str(uuid.uuid4()),
        }
        body = self.post(turn).get_json()
        self.assertEqual(body["suggested_actions"], CHOICE["suggested_actions"])
        user_id, (mine, bot) = self.rows[0]
        self.assertEqual(user_id, USER)
        self.assertEqual((mine["role"], mine["body"]), ("user", "replace my deck"))
        self.assertEqual((bot["role"], bot["body"]), ("bot", CHOICE["answer"]))
        self.assertEqual(bot["metadata"]["suggested_actions"], CHOICE["suggested_actions"])
        retry = self.post(turn).get_json()
        self.assertTrue(retry["replayed"])
        self.assertEqual(retry["answer"], CHOICE["answer"])
        self.assertEqual(retry["suggested_actions"], CHOICE["suggested_actions"])
        self.assertEqual(retry["outcome"], "structured")
        self.assertEqual(len(self.rows), 1)
        self.assertEqual([r["client_id"] for r in self.rows[0][1]],
                         [mine["client_id"], bot["client_id"]])

        # The table hands back what was written, newest first.
        self.thread = list(reversed(self.rows[0][1]))
        # An older-page read: the newest page's live flags are not the subject.
        page = self.client.get("/v2/user/lounge/messages?before=2100-01-01T00:00:00Z",
                               headers={"Authorization": "Bearer t"}).get_json()
        reloaded = [m for m in page["messages"] if m["client_id"] == bot["client_id"]]
        self.assertTrue(reloaded)
        self.assertEqual(reloaded[0]["metadata"]["suggested_actions"],
                         CHOICE["suggested_actions"])

    def test_a_correlated_retry_replays_once_and_a_new_id_is_a_new_turn(self):
        first_id, second_id = str(uuid.uuid4()), str(uuid.uuid4())
        first = self.post({
            "question": "nice", "persist": True, "client_id": first_id,
        }).get_json()
        retry = self.post({
            "question": "nice", "persist": True,
            "client_id": first_id.upper(), "request_id": first_id,
        }).get_json()

        self.assertEqual(first["request_id"], first_id)
        self.assertTrue(first["terminal"])
        self.assertEqual(first["outcome"], "reply")
        self.assertFalse(first["retryable"])
        self.assertIsNone(first["failure"])
        self.assertEqual(retry["answer"], first["answer"])
        self.assertEqual(retry["request_id"], first_id)
        self.assertTrue(retry["replayed"])
        self.assertEqual(len(self.rows), 1)
        self.assertEqual(len(self.histories), 1)
        self.assertEqual(len(self.charges), 1)

        # A retry can lose its persistence flag in a client reconnect; a
        # completed durable receipt still owns the logical turn.
        downgraded = self.post({
            "question": "nice", "persist": False, "request_id": first_id,
        }).get_json()
        self.assertTrue(downgraded["replayed"])
        self.assertEqual(len(self.histories), 1)
        self.assertEqual(len(self.charges), 1)

        conflict = self.post({
            "question": "What should I change instead?", "persist": True,
            "request_id": first_id,
        })
        self.assertEqual(conflict.status_code, 200)
        self.assertEqual(conflict.get_json()["failure"]["code"],
                         "CHAT_TURN_CONFLICT")
        self.assertFalse(conflict.get_json()["persisted"])
        self.assertEqual(len(self.rows), 1)
        self.assertEqual(len(self.histories), 1)
        self.assertEqual(len(self.charges), 1)

        second = self.post({
            "question": "nice", "persist": True, "client_id": second_id,
        }).get_json()
        self.assertEqual(second["request_id"], second_id)
        self.assertEqual(len(self.rows), 2)
        self.assertEqual(len(self.histories), 2)
        self.assertEqual(len(self.charges), 2)
        self.assertNotEqual(self.rows[0][1][0]["client_id"],
                            self.rows[1][1][0]["client_id"])
        receipt = self.rows[0][1][1]["metadata"]["chat_response"]["response"]
        self.assertEqual(receipt["answer"], first["answer"])
        self.assertEqual(receipt["request_id"], first_id)
        self.assertNotIn("debug", receipt)

    def test_a_pending_claim_and_a_failed_receipt_never_reexecute_a_turn(self):
        pending_id = str(uuid.uuid4())
        self.stored[(USER, pending_id)] = {
            "client_id": pending_id, "role": "user", "kind": "text",
            "body": "nice", "metadata": {
                "chat_turn": {
                    "version": 1, "state": "pending", "claim_id": "other",
                },
            },
        }
        pending = self.post({
            "question": "nice", "persist": True, "client_id": pending_id,
        }).get_json()
        self.assertTrue(pending["terminal"])
        self.assertEqual(pending["failure"], {
            "code": "CHAT_TURN_IN_PROGRESS", "retryable": True,
            "timeout": False, "retry_after_ms": 1000,
        })
        self.assertFalse(pending["persisted"])
        self.assertEqual(self.histories, [])
        self.assertEqual(self.rows, [])
        self.assertEqual(self.charges, [])

        failed_id = str(uuid.uuid4())
        self.fail_final_db = True
        first = self.post({
            "question": "What is this?", "persist": True,
            "client_id": failed_id,
        }).get_json()
        self.assertEqual(first["answer"], self.model_answer)
        self.assertEqual(first["failure"]["code"], "CHAT_PERSIST_FAILED")
        self.assertEqual(len(self.histories), 1)
        self.assertEqual(self.charges, [])

        self.fail_final_db = False
        retry = self.post({
            "question": "What is this?", "persist": True,
            "request_id": failed_id,
        }).get_json()
        self.assertTrue(retry["replayed"])
        self.assertEqual(retry["failure"], first["failure"])
        self.assertEqual(len(self.histories), 1)
        self.assertEqual(self.charges, [])

    def test_a_committed_bot_write_with_a_lost_acknowledgement_replays_successfully(self):
        turn_id = str(uuid.uuid4())
        self.ambiguous_final_db = True
        first = self.post({
            "question": "What is this?", "persist": True,
            "client_id": turn_id,
        }).get_json()

        self.assertTrue(first["terminal"])
        self.assertTrue(first["persisted"])
        self.assertIsNone(first["failure"])
        self.assertEqual(len(self.histories), 1)
        self.assertEqual(len(self.charges), 1)

        self.ambiguous_final_db = False
        retry = self.post({
            "question": "What is this?", "persist": True,
            "request_id": turn_id,
        }).get_json()
        self.assertTrue(retry["replayed"])
        self.assertEqual(retry["answer"], self.model_answer)
        self.assertIsNone(retry["failure"])
        self.assertEqual(len(self.histories), 1)
        self.assertEqual(len(self.charges), 1)

    def test_a_post_persist_follow_on_failure_replays_the_same_success(self):
        turn_id = str(uuid.uuid4())

        def finalizing_sunday_note(*_args, finalize=None, **_kwargs):
            return finalize({
                "answer": self.model_answer,
                "bubbles": [self.model_answer],
                "show_record_ui": False,
                "suggested_action": None,
                "suggested_actions": None,
                "app_action": None,
                "sunday_case": {"id": "case-1"},
            }, "sunday_note")

        with (
            patch("routes.v2.coaching.answer_chat", finalizing_sunday_note),
            patch("services.sunday_note.after_head",
                  side_effect=RuntimeError("post-save action failed")) as after_head,
        ):
            first = self.post({
                "question": "What should I change?", "persist": True,
                "client_id": turn_id,
            }).get_json()

        retry = self.post({
            "question": "What should I change?", "persist": True,
            "request_id": turn_id,
        }).get_json()

        self.assertTrue(first["persisted"])
        self.assertIsNone(first["failure"])
        self.assertEqual(first["answer"], self.model_answer)
        self.assertTrue(retry["replayed"])
        self.assertEqual(retry["answer"], first["answer"])
        self.assertEqual(retry["failure"], first["failure"])
        self.assertEqual(len(self.rows), 1)
        self.assertEqual(len(self.charges), 1)
        after_head.assert_called_once()

    def test_an_optimistic_row_keeps_its_words_and_metadata_until_its_owner_claims_it(self):
        turn_id = str(uuid.uuid4())
        self.stored[(USER, turn_id)] = {
            "client_id": turn_id, "role": "user", "kind": "text",
            "body": "Question one", "metadata": {
                "place": "will", "optimistic_marker": "kept",
            },
        }

        wrong = self.post({
            "question": "Question two", "persist": True,
            "client_id": turn_id,
        }).get_json()
        self.assertEqual(wrong["failure"]["code"], "CHAT_TURN_CONFLICT")
        self.assertEqual(self.histories, [])
        self.assertEqual(
            self.stored[(USER, turn_id)]["metadata"],
            {"place": "will", "optimistic_marker": "kept"},
        )

        right = self.post({
            "question": "Question one", "persist": True,
            "client_id": turn_id,
        }).get_json()
        self.assertEqual(right["answer"], self.model_answer)
        stored = self.stored[(USER, turn_id)]
        self.assertEqual(stored["metadata"]["optimistic_marker"], "kept")
        self.assertEqual(stored["metadata"]["chat_turn"]["state"], "completed")
        self.assertEqual(len(self.histories), 1)

    def test_an_optimistic_whitespace_bubble_can_be_claimed_once(self):
        turn_id = str(uuid.uuid4())
        self.stored[(USER, turn_id)] = {
            "client_id": turn_id, "role": "user", "kind": "text",
            "body": "  Question one  ", "metadata": {
                "place": "will", "optimistic_marker": "kept",
            },
        }

        body = self.post({
            "question": "  Question one  ", "persist": True,
            "client_id": turn_id,
        }).get_json()

        stored = self.stored[(USER, turn_id)]
        self.assertEqual(body["answer"], self.model_answer)
        self.assertEqual(stored["body"], "  Question one  ")
        self.assertEqual(stored["metadata"]["optimistic_marker"], "kept")
        self.assertEqual(stored["metadata"]["chat_turn"]["state"], "completed")
        self.assertEqual(len(self.histories), 1)

    def test_a_reused_bot_row_cannot_become_a_user_turn_claim(self):
        turn_id = str(uuid.uuid4())
        self.stored[(USER, turn_id)] = {
            "client_id": turn_id, "role": "bot", "kind": "text",
            "body": "A pre-existing bot bubble", "metadata": {},
        }

        body = self.post({
            "question": "A pre-existing bot bubble", "persist": True,
            "client_id": turn_id,
        }).get_json()
        self.assertEqual(body["failure"]["code"], "CHAT_TURN_CONFLICT")
        self.assertEqual(self.stored[(USER, turn_id)]["role"], "bot")
        self.assertNotIn("chat_turn", self.stored[(USER, turn_id)]["metadata"])
        self.assertEqual(self.histories, [])

    def test_an_unexpected_accepted_turn_error_is_still_a_renderable_terminal(self):
        turn_id = str(uuid.uuid4())
        with patch("services.chat_query._librarian", side_effect=RuntimeError("boom")):
            response = self.post({
                "question": "What is this?", "persist": True,
                "client_id": turn_id,
            })

        body = response.get_json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(body["request_id"], turn_id)
        self.assertTrue(body["terminal"])
        self.assertEqual(body["failure"], {
            "code": "CHAT_INTERNAL_ERROR", "retryable": True, "timeout": False,
        })
        self.assertFalse(body["persisted"])
        self.assertEqual(self.charges, [])

        retry = self.post({
            "question": "What is this?", "persist": True,
            "request_id": turn_id,
        }).get_json()
        self.assertTrue(retry["replayed"])
        self.assertEqual(retry["failure"], body["failure"])
        self.assertEqual(self.charges, [])

    def test_a_completed_walk_closing_cannot_answer_a_later_question(self):
        from services.after_take import SEE_YOU

        closing = {
            "client_id": "walk-is-complete", "role": "bot", "kind": "text",
            "body": SEE_YOU,
            "metadata": {"next_take": True, "take_session_id": "take-1"},
        }
        prior = {
            "client_id": "prior", "role": "bot", "kind": "text",
            "body": "Your opening had one clear point.", "metadata": {},
        }
        self.thread = [closing, prior]  # newest first, as the DB returns it
        with patch("services.after_take.release") as release:
            body = self.post({
                "question": "How can I make the opening clearer?",
                "persist": True, "client_id": str(uuid.uuid4()),
            }).get_json()

        self.assertEqual(body["answer"], self.model_answer)
        self.assertTrue(body["terminal"])
        self.assertNotIn("after_take", body)
        self.assertEqual(self.histories[-1], [{
            "role": "assistant", "content": prior["body"],
        }])
        release.assert_not_called()

        screen = self.post({
            "question": "What is the next useful change?", "persist": True,
            "client_id": str(uuid.uuid4()), "history_source": "screen",
            "history": [
                {"role": "assistant", "content": "Earlier useful context."},
                {"role": "assistant", "content": SEE_YOU},
            ],
        }).get_json()
        self.assertEqual(screen["answer"], self.model_answer)
        self.assertEqual(self.histories[-1], [{
            "role": "assistant", "content": "Earlier useful context.",
        }])

    def test_model_timeout_is_a_correlated_recoverable_terminal_outcome(self):
        turn_id = str(uuid.uuid4())
        self.debug = {"error": "llm_timeout"}
        first = self.post({
            "question": "What should I change in the opening?",
            "persist": True, "client_id": turn_id,
        }).get_json()
        retry = self.post({
            "question": "What should I change in the opening?",
            "persist": True, "client_id": turn_id,
        }).get_json()

        self.assertTrue(first["terminal"])
        self.assertEqual(first["outcome"], "recoverable_error")
        self.assertTrue(first["retryable"])
        self.assertTrue(first["timeout"])
        self.assertEqual(first["failure"], {
            "code": "CHAT_MODEL_TIMEOUT", "retryable": True, "timeout": True,
        })
        self.assertTrue(retry["replayed"])
        self.assertEqual(retry["failure"], first["failure"])
        self.assertEqual(len(self.histories), 1)

    def test_a_claim_failure_is_terminal_without_running_the_turn(self):
        self.fail_db = True
        resp = self.post({"question": "what is this?", "persist": True})
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["answer"], "")
        self.assertTrue(body["terminal"])
        self.assertEqual(body["outcome"], "recoverable_error")
        self.assertEqual(body["failure"]["code"], "CHAT_PERSIST_FAILED")
        self.assertTrue(body["failure"]["retryable"])
        self.assertFalse(body["persisted"])
        self.assertEqual(self.rows, [])
        self.assertEqual(self.histories, [])
        self.assertEqual(self.charges, [])

    def test_conflicting_request_aliases_are_a_validation_terminal(self):
        response = self.post({
            "question": "What is this?", "persist": True,
            "client_id": str(uuid.uuid4()), "request_id": str(uuid.uuid4()),
        })

        body = response.get_json()
        self.assertEqual(response.status_code, 400)
        self.assertEqual(body["code"], "INVALID_REQUEST_ID")
        self.assertEqual(body["failure"]["code"], "INVALID_REQUEST_ID")
        self.assertTrue(body["terminal"])
        self.assertEqual(self.histories, [])
        self.assertEqual(self.rows, [])

    def test_the_reply_is_saved_under_the_turn_it_answers(self):
        from datetime import datetime, timedelta, timezone
        ahead = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        self.post({"question": "what is this?", "persist": True,
                   "client_created_at": ahead})
        mine, bot = self.rows[-1][1]
        self.assertEqual(mine["client_created_at"], ahead)
        self.assertGreater(datetime.fromisoformat(bot["client_created_at"]),
                           datetime.fromisoformat(ahead))

    def test_a_typed_practice_answer_is_contextual_and_settles_once(self):
        from services import after_take
        from services.db import db

        asked = "When you finish, what do you want the audience to do?"
        answer = "Approve two hires by March"
        self.model_answer = "That gives this talk a concrete outcome."
        self.thread = [{
            "client_id": "will-question-ask", "role": "bot", "kind": "text",
            "body": asked,
            "metadata": {
                "offer": "will_question", "will_question": "goal",
                "will_question_step": "ask", "arc_id": "arc-1",
                "take_session_id": "take-1", "chips": [],
            },
            "client_created_at": "2026-11-16T19:00:00+00:00",
        }]
        setup = {"strategic_context": "Existing context."}
        memory, releases = [], []

        def stored_row(_user_id, client_id):
            stored = self.stored.get((str(_user_id), str(client_id)))
            if stored:
                return stored
            rows = self.thread + [row for _, batch in self.rows for row in batch]
            return next((row for row in rows if row["client_id"] == client_id), None)

        def remember(_database, user_id, kind, payload, take):
            memory.append((user_id, kind, payload, take))

        def release(_database, user_id, take=None):
            releases.append((user_id, take))
            return [{"kind": "text"}]

        client_id = "11111111-1111-4111-8111-111111111111"
        with (
            patch.object(db, "get_lounge_message_by_client_id", stored_row),
            patch.object(db.takes, "get_session_intake_context",
                         lambda _take: dict(setup)),
            patch.object(db.takes, "set_session_intake_context",
                         lambda _take, context: setup.update(context) or True),
            patch("services.speaker_memory.record", remember),
            patch.object(after_take, "release", release),
        ):
            body = self.post({
                "question": answer, "persist": True, "client_id": client_id,
                "place": "will", "history_source": "screen",
                # The optimistic bubble is already on screen; Will must read it
                # once, with the server-owned open question immediately before it.
                "history": [
                    {"role": "assistant", "content": "Earlier context."},
                    {"role": "user", "content": answer},
                ],
            }).get_json()

        self.assertEqual(body["answer"], self.model_answer)
        self.assertTrue(body["persisted"])
        self.assertTrue(body["after_take"])
        self.assertEqual(self.histories[-1], [
            {"role": "assistant", "content": "Earlier context."},
            {"role": "assistant", "content": asked},
        ])
        self.assertEqual(memory, [(USER, "answer", {
            "question": "goal", "said": answer, "typed": True,
            "goal": answer,
        }, "take-1")])
        self.assertEqual(
            setup["strategic_context"],
            "Desired call to action: Approve two hires by March\nExisting context.",
        )
        self.assertEqual(releases, [(USER, "take-1")])
        mine, will = self.rows[-1][1]
        self.assertEqual((mine["role"], mine["body"]), ("user", answer))
        self.assertEqual((will["role"], will["body"]),
                         ("bot", self.model_answer))
        self.assertNotEqual(mine["client_id"], will["client_id"])
        self.assertEqual(will["metadata"]["will_question_step"], "thanks")
        self.assertEqual(will["metadata"]["will_question"], "goal")
        self.assertEqual(will["metadata"]["take_session_id"], "take-1")
        self.assertEqual(will["metadata"]["place"], "will")
