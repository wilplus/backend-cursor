# WIL-74 principles: feedback, goals and notifications (founder, 2026-10-20)

> **Label: Reference** · how something works today; where it differs from the In force docs, they win. Every doc and its label: [`README.md`](../README.md) (N106).

Answered by the founder one question at a time
(<https://claude.ai/artifact/FCoVEXE71vKya61NXrbbVg>). The rule behind all
of them: the simplest thing that works, nothing to set up or test by hand.

1. **The next Take answers whether the feedback helped.** Every summary
   stores whether the voice rose, held or dipped against the last Take
   (`moved` in its metadata). The one-tap question is the backup.
2. **"Did this help?" is asked only when something looks off:**
   the practice did not land (not yet, or none tried) or the voice dipped
   (`feedback_check.looks_off`). It is never asked when another offer comes
   in the same step, and it never stands in front of the next Take.
3. ~~The founder reads the answers in a short note in their own chat, once a
   week.~~ Retired (founder, 2026-11-05, N516): no weekly note is written in
   the chat, and the ones already there are hidden. The answers are still
   kept and feed the speaker's private note. Only the founder reads the
   answers; coaches do not.
4. **A goal is tracked in words in every summary.** One goal, in the
   speaker's own words, changed by telling the chat, never graded. The
   summary hears it (`take_summary.goal_facts`). No goals screen.
5. **Notifications only when the other person must know.** The coach hears
   a goal changed (a card in their chat); the speaker hears the coach's word
   is in. Nothing else, and only in the app's chat.
6. **Everyone gets it.** No test group: it is optional and quiet.
7. **We change something when the same thing is missing three times** in
   the answers (no longer read in a weekly note, N516).

The chat knows these as facts (`feedback_check.CHAT_FACTS`, passed to the
librarian with the feature list and the speaker's status card), so it can
answer "who reads my answer?" or "how do I change my goal?".

## Chat behavior (2026-11-16)

Will mirrors the language of the speaker's typed message; the browser or
navigation locale does not choose the language of a reply. A substantive
question gets a substantive answer: Will may use one short, natural framing
clause, but does not replace the answer with a generic acknowledgement. The
recent visible conversation and the current project's bounded context are
passed together so a follow-up such as "what about the opening?" stays tied to
the talk the speaker is viewing. Missing context remains missing; Will does
not invent evidence or metrics.

When a speaker asks for a pattern, the first reply names the pattern found in
their recent notes in the typed language and the following structured case row
remains the source for the existing Not now | Investigate intervention. The
answer is concise; the case row's metadata and follow-on lens are unchanged.

**Will learns about each speaker** (founder, 2026-10-20). Their answers and
each Take's outcome feed a private note Will reads before it chats and before
it writes the summary. The speaker never sees their answers played back. See
`docs/SPEAKER-MEMORY.md`.
