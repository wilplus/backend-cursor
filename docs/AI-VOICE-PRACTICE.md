# The AI version of your voice — how it works

> **Label: Reference** · how something works today; where it differs from the In force docs, they win. Every doc and its label: [`README.md`](../README.md) (N106).

The lock (flow, words, rules) is
[`FOUNDER-LOCK-ai-voice-practice-2026-10-12.md`](FOUNDER-LOCK-ai-voice-practice-2026-10-12.md)
(decisions log N71). This page is for whoever runs or changes the code.

## The user flow

1. A speaker records a Take. As it is stored, beside its processing (founder
   2026-10-20, N84; before that, only when processing finished), one
   background job makes their AI voice (an ElevenLabs Instant Voice Clone)
   from the Take, once. A Take too short or too noisy makes none; the next
   Take tries again. The pipeline still asks at its end, and a voice already
   on its way is not asked twice.
2. The walk reaches the **voice Exercise** (the lowest sentence, the voice the
   weaker half). Praise and the Clearer version never call ElevenLabs.
3. The clip starts at the end of the bake (founder 2026-10-15, B): when the
   Manager's feedback block is stored, `ideal_text_feedback_bake` reads the
   voice-exercise moment from it (`ai_voice_clip.exercise_moment_of`, the
   walk's own rule) and queues `ai_voice_clip.prewarm` in the bake's lane
   (`BAKE_QUEUE_NAME`, else the pipeline queue), once per Take and moment.
   The prewarm opens the moment's practice server-side through
   `practice_start.start_practice` (the kind the walk would open: the
   offered exercise, else `plain`; the same purpose and consent checks as
   the routes) and runs the clip job. The walk's own ask
   (`POST …/confidence-practice/<id>/ai-voice`, when the Exercise screen
   opens if no video fits, or when Practise is tapped if one does) is the
   fallback: it resumes the same practice and finds the same cycle. One clip
   per practice, reused for every appearance; a clip that fails its check is
   made once more with a new seed, never a third time
   (`AI_VOICE_GENERATION_RETRIES`, 1; founder 2026-10-21, N93), and a failed
   one is never shown. While the job is queued or waiting for the voice,
   `demo` already says `ai_voice` with the clip `pending`, so the walk shows
   the clip's place. A voice not ready yet (the clone from Take 1 still
   being made) is asked for again every 30 s, at most 5 times
   (`generation_metadata.no_voice_waits`); after that the clip is
   `unavailable` (cycle `skipped`, `no_voice`) and a later ask with a voice
   on its way starts it again. A voice that will not come (the clone row is
   `none`, `failed` or off: a Take too short or too noisy to copy) is not
   waited for: the clip is `unavailable` at once, so the walk shows the
   locked Exercise rather than the dots.
4. The clip is shown in the video's place (no exact-fit video for the same
   problem), and after a try that isn't better yet, at most 3 times. It never
   plays by itself.
5. The next try is measured on the one problem practised and stored, only
   after a clip that was made (N93: a try after a failed clip used to be
   scored and could hold that problem back for the speaker). For
   fillers (founder 2026-10-18) the measure is hesitations per 100 words of
   the try's own transcript, against the same line as the pick.
6. Data & consent: Delete removes the voice at ElevenLabs and here, with every
   clip; Turn on makes it again from the next Take.

## The architecture (one job per module)

| Module | Job |
|---|---|
| `services/ai_voice_severity.py` | severity 0–1 per problem (pace, pause, stress, fillers) against the speaker's own usual; picks one or none; the target phrase; the next try's outcome |
| `services/ai_voice_prompt.py` | the structured exercise → one Eleven v4 request, words unchanged (the fillers clip leaves the hesitations out, nothing else), whitelisted tags only |
| `services/elevenlabs_client.py` | the five HTTP calls; errors by kind |
| `services/authorized_voice_provider.py` | every ElevenLabs call behind a processing permit |
| `services/ai_voice_validator.py` | decodes, clipping, silence, duration, words kept, the change really there |
| `services/ai_voice_clone.py` | the speaker's one voice: make, reuse, delete, turn on |
| `services/ai_voice_clip.py` | the lane, the video rule, the job, what the walk may know |
| `services/ai_voice_limits.py` | daily and monthly limits, fail closed: 3 clips a day and 20 a calendar month for each speaker (N188), the app's day, the month's credits, and no new voice while the plan's voice slots are full (`AI_VOICE_VOICE_SLOTS`, Starter's 10) |
| `services/ai_voice_store.py` | the two tables (migration 0462; 0475 admits the fillers exercise) |
| `services/admin_takes.py` | the admin Take view: each Take's clip, its outcome and the fillers rate before and after |
| `routes/v2/ai_voice.py` | the walk's routes and the card's routes |

Job states (`ai_voice_cycles.status`): `pending → analyzing →
choosing_exercise → generating → validating → completed | failed | skipped`.
Provider failures and validation failures are told apart in `failure_kind`.
Latency is in `latency_ms`: each stage (`choose_exercise`, `generation`,
`validation`, `store`), the job's `total`, and end to end: `since_request`
(the walk asked for the clip → clip ready, what the speaker waits) and
`since_take_saved` (the Take finished processing → clip ready).
Provider retries are counted in `generation_metadata.provider_retries`.

The severity minimum (`AI_VOICE_MIN_SEVERITY`, 0.2; 0.4 is the line itself) and every
normalization range (`AI_VOICE_PACE_*`, `AI_VOICE_PAUSE_*`,
`AI_VOICE_STRESS_GAP_DB`, `AI_VOICE_FILLER_GAP_PER_100`) are environment
settings; see `config.py`.

**Fillers** (founder 2026-10-18, lock section "Decided after the lock,
fillers"): the hesitations counted are the closed list the transcript fence
removes (`services/transcript_smoothing.py`, the English list: the lane
speaks and is re-heard in English). The sentence sent is the speaker's own
with those tokens left out (`ai_voice_prompt._without_fillers`); the
validator refuses the clip if one is heard (`fillers_heard`). The sentence
under the player is L18. The library has no fillers exercise, so fillers
always takes the AI clip.

When nothing reaches the minimum, the clip still comes: the default is
stress, the main point said so it stands out (founder 2026-10-15, A). The
selection says `default: true` and `reason: no_clear_problem_default`, so
the stored cycles never count it as a problem found. A sentence of under
five words has no main point apart from itself and gets no clip.

## What Eleven v4 can and cannot do

No SSML; no `speed` or `style` on v4 (only `stability` and
`similarity_boost`). So pace is asked for with `[slowly]` and clause breaks,
the pause with `[pause]`, stress with capitals (the one documented way;
there is no emphasis tag), and fillers by sending the sentence without them. Tags guide delivery and are not guaranteed, so
**the validator decides**: a clip that didn't apply the change is never shown.
Stress is the least reliable of the three; measure it in the smoke test.

## Environment

Put these in `.env` locally and on **every** Railway service (web, worker,
cron) before merging (CONFIG-FIRST): `ELEVENLABS_API_KEY`. That's all: the
feature is always on for every speaker once the key is there, and does nothing
without it. `AI_VOICE_ENABLED=0` is only an emergency off; `AI_VOICE_ALLOWLIST`
(user ids) optionally narrows it. The rest have defaults; see
`.env.example`. The key is never logged and never sent to the frontend.

## Local testing

- `bash scripts/local_ci.sh` runs `tests/test_ai_voice.py` with the rest.
  No real audio, no real provider.
- The manual smoke test, with your own consented voice and the real account:
  `scripts/ai_voice_smoke.py --sample <your file> --i-consent-this-is-my-own-voice`.
  It writes the three clips and a report next to the sample and deletes the
  clone afterwards.

## Measured prototype latency

One run, the founder's own consented voice, on their laptop, 2026-10-13
(`scripts/ai_voice_smoke.py`, Eleven v4, the default sentence, Whisper
re-hearing the clip). Milliseconds. A prototype's numbers on one voice and
one sentence, not a real-time claim.

| exercise | generation | re-transcription | validation | end to end | passed |
|---|---|---|---|---|---|
| pace | 8,853 | 4,356 | 3,990 | 17,203 | yes |
| pause | 1,978 | 879 | 66 | 2,925 | no: `pause_length`, `pause_not_distinct` |
| stress | 1,707 | 2,224 | 64 | 3,997 | yes |

- The pace row is the run's first clip: its generation and validation
  include cold starts (the first provider connection, the audio decoder's
  first load). The later clips took 3 to 4 s end to end.
- Second run, same day (ellipsis before the `[pause]` tag): pace 10,888 ms
  end to end (8,574 generation, 2,127 re-transcription, 183 validation),
  passed; pause 3,913 ms, failed; stress 3,275 ms, passed. The test clone
  was deleted and confirmed gone.
- The pause clip had a clearly audible pause (the founder listened; the
  audio held a 1.24 s silence), but Whisper's word times showed no gap at
  all: they stretch the words over short silences. The check now reads the
  pause from the audio's silence around the target phrase.
- Third run (2026-10-14): pace 10,825 ms end to end, passed; stress 3,023 ms,
  passed; pause 3,803 ms, now distinct but 1.24 s long, over the 1.2 s
  limit. The limit is now 1.5 s (still under the 1.6 s dead-air limit).
- In the app the job also waits on the queue and stores the clip; the walk
  shows the breathing mark meanwhile (`latency_ms.since_request`).
- The run's delete of the test clone was reported as refused: ElevenLabs
  answers a missing voice with a 400 `voice_not_found`, which the client
  now reads as already deleted.

To measure again:

    .venv-ci/bin/python scripts/ai_voice_smoke.py \
        --sample <your own sample> --i-consent-this-is-my-own-voice

## Known limitations

- **Permits.** ElevenLabs calls run as `feedback_generation` with provider
  `elevenlabs` until counsel sets a dedicated purpose (then one migration of
  the permit function), before launch.
- **Practice tries over 45 s** are not rejected by the existing attempt route;
  the AI voice simply doesn't measure them (`inconclusive`).
- **Credits** are estimated per character until the smoke test reads the
  provider's real cost header; the monthly check also reads the plan's own
  counter when it can.
- **Zero-retention mode** is Enterprise-only, so ElevenLabs keeps request data
  under its standard retention. This is for counsel.
- The walk's frontend isn't built yet; this backend returns `demo` (`video`,
  `ai_voice` or `none`) and the clip's state and link for it.
