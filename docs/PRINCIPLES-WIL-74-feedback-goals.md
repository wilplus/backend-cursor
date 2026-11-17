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

### Correlated chat delivery (implementation contract)

Every accepted, handler-produced `/v2/chat/query` turn is terminal for one
server-returned `client_id` / `request_id`: `terminal`, `outcome`,
`retryable`, `timeout` and the optional structured `failure` object let the
composer stop its typing state without guessing from a bubble. The usual
reply text and the existing structured intervention fields remain separate.
Middleware/validation refusals can occur before the handler accepts a turn;
they are not a substitute for this terminal contract.

| Failure code | HTTP / fields | Composer treatment |
|---|---|---|
| `CHAT_MODEL_TIMEOUT` | `200`; `retryable: true`, `timeout: true` | Render the language-selected safe fallback when it exists, mark the model attempt timed out, and offer a deliberate retry rather than leaving typing active. |
| `CHAT_MODEL_UNAVAILABLE`, `CHAT_MODEL_EMPTY_RESPONSE`, `CHAT_MODEL_INVALID_RESPONSE`, `CHAT_MODEL_LANGUAGE_REJECTED`, `CHAT_RESPONSE_UNAVAILABLE` | `200`; `retryable: true`, `timeout: false` | Render the useful safe fallback if supplied; never expose provider detail or replace it with a generic acknowledgement. |
| `CHAT_CONTEXT_UNAVAILABLE` | `200`; `retryable: true`, `timeout: false` | Keep the language-selected contextual fallback and its existing settlement metadata; offer a deliberate retry. |
| `CHAT_PERSIST_FAILED` | `200`; `retryable: true`, `timeout: false`, `persisted: false` | Render the explicit recoverable state. `answer` can be empty before work starts, or the safe answer when its later bot write could not be confirmed. |
| `CHAT_TURN_IN_PROGRESS`, `CHAT_TURN_UNAVAILABLE` | `200`; `retryable: true`, `timeout: false`, `retry_after_ms: 1000`, `persisted: false` | Stop typing and show a wait/retry state for the same correlation id; no second intercept, model call, charge or walk release is run. |
| `CHAT_TURN_CONFLICT` | `200` for an accepted reused id; `retryable: false`, `timeout: false`, `persisted: false` | Stop typing and reject changed text for that already-owned id. |
| `CHAT_INTERNAL_ERROR` | `200`; `retryable: true`, `timeout: false`, `persisted: false` for a claimed persisted turn | Stop typing and show the explicit recoverable error; the durable failure receipt prevents duplicate state work on the same id. |
| `INVALID_INPUT`, `INVALID_REQUEST_ID` | `400`; `retryable: false`, `timeout: false` | Validation refusal: keep the input available for correction. Contradictory `client_id` / `request_id` aliases use `INVALID_REQUEST_ID`, not `CHAT_TURN_CONFLICT`. |

`failure` always contains `code`, `retryable` and `timeout`, and may contain
`retry_after_ms`; the top-level `retryable` / `timeout` repeat those values
for existing composer code. Every accepted failure is deliberately `200` with
the terminal fields above, so a generic HTTP client cannot discard the
correlation body before the composer settles its typing state. Validation
refusals remain `400` and use the same renderable fields.

For a signed-in turn with `persist: true`, that UUID is also the durable
retry key. Reposting the same id replays the completed, stored terminal
response without another model call, state transition, release or charge; the
same text with a fresh id is a new turn. Reusing an id for different text is a
conflict, not a reply to the wrong message. A caller that sends no valid UUID
receives a new server id so repeated short text is never deduplicated by its
words. A retry cannot disable this protection by changing a completed
persisted turn to `persist: false`.

Anonymous turns and signed turns explicitly sent with `persist: false` retain
the returned correlation fields but intentionally do not create a durable
receipt: preserving that privacy/storage choice takes precedence over claiming
cross-request idempotency where the backend has no safe arbitration record.

The terminal row after a Take (`metadata.next_take`) belongs to that Take,
not to a later question. It is omitted from both stored and supplied screen
conversation context. A held chain may advance only from explicit settlement
metadata for its own `take_session_id`; an ordinary librarian reply therefore
cannot let an old "Good job. See you next time." appear under an unrelated
message. These delivery fields do not widen what reaches a provider: the
existing Phase-1 authorization, bounded private context, fallback evidence
rules and signed walk copy remain in force.

The shared model-call budget passes its remaining timeout to each started
provider call and discards a response that arrives after the budget. It does
not claim to cancel a browser, proxy or already-blocking SDK call; the
terminal timeout state is the backend result once that call returns. This is a
reliability repair of the existing N652/N654/N656 language, conversation and
after-Take rules, not a new feedback-walk flow or new speaker copy.

**Will learns about each speaker** (founder, 2026-10-20). Their answers and
each Take's outcome feed a private note Will reads before it chats and before
it writes the summary. The speaker never sees their answers played back. See
`docs/SPEAKER-MEMORY.md`.
