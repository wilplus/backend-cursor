# PARKED — Lounge intent-router + persona polish

Status: **parked, ready to execute when `services/master_doc_rag.py`
stops churning** (excision stages + §3.12 library work were landing on
that file as of 2026-06-06; don't start the router until that settles —
refactoring a hot, actively-edited file against a moving baseline is how
you manufacture the regressions the router exists to prevent).

Why this exists: the master-doc system prompt has hit its **attention
ceiling**. Two independent signals proved it:
1. A well-specified persona polish (varied off-topic refusals + dad-joke
   escape valve + anti-screen framing) consistently dropped the eval
   probe to 10/12 — the added RULE B text stole attention from RULE H
   (capability decline), so the bot started saying "I can't access your
   camera" but dropping "video". Reverted; never shipped.
2. Clean `main` (no persona change) had *already* drifted 12→11 from
   parallel master-doc work — MDR-05 (off-topic redirect) now fails on a
   clean run. Silent degradation the eval caught.

Conclusion: every future capability note or persona tweak will keep
hitting this wall. The fix is structural (the deferred "Rule 3" intent
router), not another prompt cram.

---

## Part 1 — The intent-router refactor (the real fix)

### Current architecture (the problem)
`services/master_doc_rag.py::answer_question` makes ONE LLM call whose
single system prompt must simultaneously nail:
- the verbatim Master Document (brand voice + product facts)
- RULE A verbatim grounding
- RULE B off-topic pivot
- RULE C voice/tone + short-question discipline
- RULE G upload-intent detection (`show_upload_ui`)
- RULE H capability boundaries (`camera`/`video` declines)
- RULE I record-intent detection (`show_record_ui`)
- RULE J correction acknowledgement
- the §3.12 LIBRARIAN GUARDRAIL + strong-sides library block
- the admin "don't-ask" private-notes block

That's ~10 concerns in one prompt. Adding an 11th degrades an existing
one (proven). This is the textbook case for splitting.

### Proposed architecture
Two-stage, cheap-model both stages:

1. **Intent classifier** (tiny, ~50-token system prompt, gpt-4o-mini,
   temp 0): classify the user turn into one of:
   `product_faq | upload_intent | record_intent | off_topic |
   capability_request | library_recall | correction`.
   Returns strict JSON `{intent, confidence}`.

2. **Dedicated handler per intent**, each a SHORT focused prompt:
   - `product_faq` → master-doc-grounded answer (the current RAG path,
     minus all the branching rules it no longer needs)
   - `off_topic` → the persona polish below (varied refusal + dad joke +
     anti-screen), in ISOLATION — can't degrade capability decline
     because that's a different handler
   - `capability_request` → the RULE H decline, focused
   - `upload_intent` / `record_intent` → set the flag + short confirm
   - `library_recall` → the §3.12 librarian path
   - `correction` → RULE J acknowledgement

### Critical guards (from the original Rule 3 risk analysis)
- **Latency**: 2 LLM calls/turn = +400–700ms. Mitigate: classifier is
  tiny + temp 0; cache the classification when only the latest message
  changed mid-turn.
- **Cost**: doubles per turn. Negligible at MVP volume; real at scale.
- **Misclassification compounds**: a wrong route is worse than the
  mega-prompt's "all rules at once". Mitigate: on low classifier
  confidence, fall back to the current single-prompt path (keep it as
  the safety net, don't delete it).
- **Build the router as a PARALLEL path behind a feature flag**, A/B vs
  the current prompt, promote only when the probe shows ≥ parity. Do NOT
  rip out the mega-prompt until the router beats it on the eval.

### Acceptance
- Probe v2 (`tests/evals/master_doc_probe.py`) scores ≥ baseline (12/12
  once the drift in Part 3 is fixed) with the router on.
- Off-topic handler can carry the full persona polish WITHOUT moving
  MDR-04 (capability decline) — that's the whole point.
- Latency p50 < current + 600ms.

---

## Part 2 — The persona polish (parked spec + few-shot pool)

Lands in the `off_topic` handler once the router exists. Verbatim from
the FE handoff note so it isn't lost.

### Three behaviors
1. **Scope statement, every off-topic refusal, varied language.** Name
   what the bot is for (public speaking, voice, conversation skill),
   name what it's not for, invite back. NEVER the same refusal string
   twice in a conversation (read history). An identical canned line is
   the worst failure mode — reads as a broken IVR.
2. **Optional dad-joke escape valve.** Only when the off-topic input is
   playful/trivial/pop-culture. ONE short warm joke before redirecting,
   never the same twice, never on a serious question. Joke = warmth,
   redirect = substance.
3. **Anti-screen framing, sparingly (once per conversation max).**
   willab's point is to get the user good fast so they close the app and
   go be with their people. Remind them only when it lands naturally.

### Few-shot pool (high signal for the handler prompt)
| User | Bot |
|---|---|
| `What is the Rip from Yellowstone real name?` | "Couldn't tell you Rip's real name, but I do know what makes a voice land like his does on screen — gravel, pacing, comfort with silence. Want to work on any of those?" |
| `Lol` | "Easy laugh! Got a question buried in there, or shall I throw one back — what's the speaking situation that's been on your mind?" |
| `What's 17 × 24?` | "I'm rubbish at arithmetic — I do voice, presence, and how words land. Anything in that lane I can dig into for you?" |
| `Tell me a joke` | "I'd rather hear yours and tell you how to land it. What's your go-to opener — got one you'd try on a stage?" |
| `How do I sound more confident?` | *(normal RAG-grounded answer, no refusal)* |
| `What's a strong side?` | *(normal RAG-grounded answer, no refusal)* |

(The "Tell me a joke" row is intentional: even when the user asks for the
joke, redirect to "tell me yours" and turn it into coaching. The joke is
bait, not the goal.)

### Falsification probes (run against an authed session after wiring)
1. "What is the Rip from Yellowstone real name?" → varied refusal, scope
   statement, optional light joke, coaching-shaped invite.
2. "Lol" → different output than #1.
3. Same two again in one session → different wording the second time
   (confirms variation).
4. "What's a strong side?" → RAG-grounded answer, NO deflection (confirms
   no in-domain regression).
5. Anti-screen line appears in SOME turn of a multi-turn off-topic chat,
   not every turn.

---

## Part 3 — Probe-drift ticket (do this BEFORE the router)

Clean `main` dropped 12→11 on `tests/evals/master_doc_probe.py`
(MDR-05 off-topic redirect now fails) from parallel master-doc work
(§3.12 library splice / excision stages / doc edits). The router should
be built against a 12/12 baseline, not a drifted one — so fix this first.

Action:
1. `git bisect` or read the master_doc_rag diffs since the last known
   12/12 (commit `41b0e9f` was 12/12) to find which change nudged MDR-05.
2. Either restore the off-topic-redirect behavior or, if the new
   behavior is correct, re-tune the MDR-05 rubric (NOT to paper over a
   real regression — only if the bot's new answer is genuinely fine and
   the probe assertion was too strict).
3. **Process note going forward**: whoever edits the master-doc system
   prompt runs `python tests/evals/master_doc_probe.py` PRE-merge. It's
   not in CI (needs OPENAI_API_KEY + costs ~$0.06/run), so it's a manual
   gate — but it's the only thing catching silent persona/capability
   drift. A red probe blocks the merge.
