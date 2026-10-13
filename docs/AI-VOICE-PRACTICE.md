# The AI version of your voice — how it works

The lock (flow, words, rules) is
[`FOUNDER-LOCK-ai-voice-practice-2026-10-12.md`](FOUNDER-LOCK-ai-voice-practice-2026-10-12.md)
(decisions log N71). This page is for whoever runs or changes the code.

## The user flow

1. A speaker records a Take. When it finishes processing, one background job
   makes their AI voice (an ElevenLabs Instant Voice Clone) from the Take,
   once. A Take too short or too noisy makes none; the next Take tries again.
2. The walk reaches the **voice Exercise** (the lowest sentence, the voice the
   weaker half). Praise and the Clearer version never call ElevenLabs.
3. The walk asks for the clip (`POST …/confidence-practice/<id>/ai-voice`):
   when the Exercise screen opens if no video fits, or when Practise is
   tapped if one does. One clip per practice, made once (never remade when it
   fails its check), reused for every appearance.
4. The clip is shown in the video's place (no exact-fit video for the same
   problem), and after a try that isn't better yet, at most 3 times. It never
   plays by itself.
5. The next try is measured on the one problem practised and stored.
6. Data & consent: Delete removes the voice at ElevenLabs and here, with every
   clip; Turn on makes it again from the next Take.

## The architecture (one job per module)

| Module | Job |
|---|---|
| `services/ai_voice_severity.py` | severity 0–1 per problem against the speaker's own usual; picks one or none; the target phrase; the next try's outcome |
| `services/ai_voice_prompt.py` | the structured exercise → one Eleven v4 request, words unchanged, whitelisted tags only |
| `services/elevenlabs_client.py` | the five HTTP calls; errors by kind |
| `services/authorized_voice_provider.py` | every ElevenLabs call behind a processing permit |
| `services/ai_voice_validator.py` | decodes, clipping, silence, duration, words kept, the change really there |
| `services/ai_voice_clone.py` | the speaker's one voice: make, reuse, delete, turn on |
| `services/ai_voice_clip.py` | the lane, the video rule, the job, what the walk may know |
| `services/ai_voice_limits.py` | daily and monthly limits, fail closed |
| `services/ai_voice_store.py` | the two tables (migration 0462) |
| `routes/v2/ai_voice.py` | the walk's routes and the card's routes |

Job states (`ai_voice_cycles.status`): `pending → analyzing →
choosing_exercise → generating → validating → completed | failed | skipped`.
Provider failures and validation failures are told apart in `failure_kind`.
Latency is in `latency_ms`: each stage (`choose_exercise`, `generation`,
`validation`, `store`), the job's `total`, and end to end: `since_request`
(the walk asked for the clip → clip ready, what the speaker waits) and
`since_take_saved` (the Take finished processing → clip ready).
Provider retries are counted in `generation_metadata.provider_retries`.

The severity minimum (`AI_VOICE_MIN_SEVERITY`, 0.4) and every
normalization range (`AI_VOICE_PACE_*`, `AI_VOICE_PAUSE_*`,
`AI_VOICE_STRESS_GAP_DB`) are environment settings; see `config.py`.

## What Eleven v4 can and cannot do

No SSML; no `speed` or `style` on v4 (only `stability` and
`similarity_boost`). So pace is asked for with `[slowly]` and clause breaks,
the pause with `[pause]`, and stress with capitals (the one documented way;
there is no emphasis tag). Tags guide delivery and are not guaranteed, so
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

Not measured yet: the real-service smoke test is waiting on the founder
(ELEVENLABS_API_KEY in the local `.env` and on every Railway service, the
plan's credits confirmed, and their own consented voice sample). Run:

    .venv-ci/bin/python scripts/ai_voice_smoke.py \
        --sample <your own sample> --i-consent-this-is-my-own-voice

It prints, per exercise, PASS/FAIL, the failed checks and `latency_ms`
(`build`, `generation`, `re_transcription`, `validation`, `end_to_end`),
writes `report.json`, and deletes the test clone even when a step fails.
The numbers go in the table below. They are a prototype's numbers on one
voice, not a real-time claim.

| exercise | generation | re-transcription | validation | end to end | passed |
|---|---|---|---|---|---|
| pace | — | — | — | — | — |
| pause | — | — | — | — | — |
| stress (expected least reliable) | — | — | — | — | — |

Clone creation (once per speaker, in the background after Take 1): —

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
