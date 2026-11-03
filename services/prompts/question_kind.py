"""Prompt for Will's mark on a question in a chat (founder 2026-11-03, N361
item 1: "Will decides from the words").

A question that waits for the speaker's answer, in the asker's words (a
customer's request, or a voice note's words after a photo or a file), is
read once: does it ask about a product or a treatment? A yes turns the bar
into "Record an answer" (N321 item 4). The service keeps the call and the
output guard (services/chats.py). Editing the text below is a prompt change:
regenerate prompts.lock.json.
"""
from __future__ import annotations

SYSTEM = (
    "Someone asks a business a question, in the words below. Does the "
    "question ask about a product or a treatment the business offers or "
    "could offer (what it is, whether it would help, how to use it, what it "
    "costs, which one to choose)? Questions about opening hours, bookings, "
    "directions, payments already made or small talk are not.\n"
    "Answer with one word: yes or no."
)

REGISTER = {
    "question_kind.system": SYSTEM,
}
