"""
STORY    As a person who records in a host's chat, I want the moments I meet
         to reach a coach and the alarm to watch them, so that no moment is
         lost because of where I recorded.
OUTCOME
  O1  A Take made in a host's chat is an ordinary Take of the person: once
      the speaker opens a moment, it is listed for a coach as "judge it".
  O2  Three such Takes whose moments never reached the speaker fire the
      reach alarm; with one reached, it stays quiet.
  O3  When the alarm fires, its message names the host chat of each
      unreached Take; a chat that cannot be read never stops the alarm.
PROVES   O1 -> HostChatTakeTests::test_an_opened_moment_is_listed_for_a_coach
         O2 -> HostChatTakeTests::test_unreached_host_chat_takes_fire_the_alarm
         O3 -> HostChatTakeTests::test_the_alarm_names_the_host_chats
WHY      N648 item 8 (coaches answer the moments of a Take made in a host's
         chat); promise: every moment a speaker meets reaches a coach.
"""
from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest import mock

from services import coach_moments_queue as q

NOW = datetime(2026, 11, 11, 12, 0, tzinfo=timezone.utc)
MOMENT = "aaaaaaaa-0000-0000-0000-00000000000a"


def _take(n: int, sent: str) -> dict:
    # The row a host-chat Take has: the person's own, no chat id on it.
    return {"id": f"1111111{n}-1111-1111-1111-111111111111", "user_id": "speaker",
            "review_requested_at": sent, "intake_context": {}}


def _queue(rows: list[dict], reached: set[str]):
    return q.moments_queue(
        rows, moments_for=lambda _r: [MOMENT], reached_for=lambda _s: reached,
        ratings_for=lambda _s: {}, request_for=lambda _s, _n: None,
        pseudonym_for=lambda _u: "Brave Robin", alarm=False)


class HostChatTakeTests(unittest.TestCase):
    def setUp(self):
        q._alarmed_on = None

    def test_an_opened_moment_is_listed_for_a_coach(self):
        out = _queue([_take(1, "2026-11-10T08:00:00+00:00")], reached={MOMENT})
        moment = out[0]["takes"][0]["moments"][0]
        self.assertEqual((moment["snippet_id"], moment["state"]), (MOMENT, "judge_it"))
        self.assertEqual(out[0]["waiting"], 1)

    def test_unreached_host_chat_takes_fire_the_alarm(self):
        sent = [f"2026-11-10T0{n}:00:00+00:00" for n in (1, 2, 3)]
        rows = [_take(n, s) for n, s in enumerate(sent, 1)]
        with mock.patch("sentry_sdk.capture_message") as warned, \
                mock.patch.object(q, "datetime", wraps=datetime) as clock:
            clock.now.return_value = NOW
            q.moments_queue(
                rows, moments_for=lambda _r: [MOMENT], reached_for=lambda _s: set(),
                ratings_for=lambda _s: {}, request_for=lambda _s, _n: None,
                pseudonym_for=lambda _u: "Brave Robin")
            warned.assert_called_once()
            q._alarmed_on = None
            q.moments_queue(
                rows, moments_for=lambda _r: [MOMENT],
                reached_for=lambda s: {MOMENT} if s == rows[0]["id"] else set(),
                ratings_for=lambda _s: {}, request_for=lambda _s, _n: None,
                pseudonym_for=lambda _u: "Brave Robin")
            warned.assert_called_once()  # reach works: no second warning

    def test_the_alarm_names_the_host_chats(self):
        takes = [(f"2026-11-10T0{n}:00:00+00:00", False, f"take-{n}") for n in (1, 2, 3)]
        chats = {"take-1": "chat-a", "take-2": "chat-a", "take-3": None}
        with mock.patch("sentry_sdk.capture_message") as warned:
            self.assertTrue(q.reach_alarm(takes, now=NOW, chat_of=chats.get))
        self.assertIn("made in host chat: chat-a", warned.call_args.args[0])
        self.assertNotIn("None", warned.call_args.args[0])
        q._alarmed_on = None

        def broken(_sid):
            raise RuntimeError("chats down")
        with mock.patch("sentry_sdk.capture_message") as warned:
            self.assertTrue(q.reach_alarm(takes, now=NOW, chat_of=broken))
        self.assertNotIn("host chat", warned.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
