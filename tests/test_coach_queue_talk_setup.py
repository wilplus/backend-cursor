"""
STORY    As a coach, I want to see who a speaker's talk is for and what they
         want the audience to do, in the speaker's own words, next to their
         goal, so that I judge and answer knowing what the talk is trying
         to do.
OUTCOME
  O1  The queue carries, per Take, the setup's audience and its call to
      action as the speaker said them (filled by Will's questions), None
      when they have not said; never a name, never a score.
  O2  The Speakers list passes both through for every Take and still
      carries no moment.
PROVES   O1 -> test_the_queue_carries_who_the_talk_is_for_and_what_they_should_do
         O2 -> test_the_speakers_list_passes_both_through
WHY      Founder 2026-10-20 (N87; flow page coach-panel, C3), on the
         prototype https://claude.ai/artifact/UiZzNZs5623NkforaeR4PM.
"""
from services import coach_moments_queue as q
from services.coach_speakers import speakers_summary


def test_the_queue_carries_who_the_talk_is_for_and_what_they_should_do():
    row = {"intake_context": {
        "audience": " the board ",
        "strategic_context": "Keep it short.\nDesired call to action: Approve two hires",
    }}
    assert q.talk_setup(row) == ("the board", "Approve two hires")
    assert q.talk_setup({"intake_context": {"topic": "research"}}) == (None, None)
    assert q.talk_setup({"intake_context": {"audience": "", "strategic_context": "no ask here"}}) == (None, None)
    assert q.talk_setup({}) == (None, None)


def test_the_speakers_list_passes_both_through():
    queue = [{
        "pseudonym": "Quiet Heron", "goal": "Sound sure", "waiting": 1, "waiting_for_text": 0,
        "takes": [{
            "session_id": "t1", "take_index": 1, "sent_at": "2026-10-20T10:00:00Z",
            "waiting": 1, "waiting_for_text": False, "answered_at": None,
            "moments": [{"snippet_id": "s1", "state": "judge_it"}],
            "audience": "The board", "call_to_action": "Approve two hires",
        }],
    }]
    take = speakers_summary(queue)[0]["takes"][0]
    assert (take["audience"], take["call_to_action"]) == ("The board", "Approve two hires")
    assert "moments" not in take
