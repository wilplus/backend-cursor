# FE HANDOFF — measure the recorder clock offset (F1)

**Repo:** `frontend-cursor`. BE side is **already merged/ready** — the field is
accepted and applied; it just needs you to send it.

**Priority:** this is **F1-CORE** — it directly improves per-slide transcription
accuracy, which is the app's load-bearing piece. Not a polish task.

---

## The problem, in one paragraph

We run on **two clocks**. Whisper's word timestamps are measured from the
**audio file**. Slide tap times (`slide_advances[].t_ms`) are measured from the
**UI clock**. `MediaRecorder` does not start producing audio the instant the
user hits record — there's a warm-up of tens to low-hundreds of milliseconds. So
the audio clock runs *behind* the UI clock, and the first words spoken after a
slide tap get bucketed to the **previous slide**.

Today the BE compensates by **guessing**: it looks for a silence near each tap
and assumes the tap belongs in it (`SLIDE_PAUSE_SNAP_ENABLED`, live in prod).
That works when the speaker pauses as they tap, and does nothing when they talk
straight through.

**You can measure the number instead of us guessing it.**

---

## What to send

One optional field on the existing Lab upload, `POST /v2/lab/recordings`:

```
slide_clock_offset_ms   (optional, integer, multipart form field)
```

**Definition — please match this exactly:**

> The number of milliseconds to **subtract** from every `slide_advances[].t_ms`
> to convert it to audio time.
>
> `slide_clock_offset_ms = t_recorderFirstAudio − t_zeroUsedForTapTimes`

Where:
- `t_zeroUsedForTapTimes` — the timestamp your tap times are measured from
  (whatever "0" means for `t_ms` today)
- `t_recorderFirstAudio` — when the recorder actually began capturing audio.
  `MediaRecorder`'s `start` event, or more precisely the timestamp when the
  first non-empty `dataavailable` chunk arrives.

Use one monotonic source for both (`performance.now()`), not `Date.now()` —
wall-clock can jump.

Normal values are **positive and small** (roughly 20–400ms). Send it once per
recording; it's a per-take constant.

### Even better, if it's easy

If you can simply **anchor `t_ms` to the recorder's start event** rather than to
page-load or button-press, then the offset is zero by construction — send
`slide_clock_offset_ms=0` or omit it. That's the cleanest possible fix: no
correction needed because the two clocks never diverged.

Either approach works. The field exists so you don't have to restructure the
recorder if that's risky.

---

## What the BE does with it

- Subtracts it from every tap time **once**, at the top of the pipeline, so
  per-slide transcripts, the piece cutter and slide-stickiness all inherit the
  corrected timeline.
- **Pause-snap still runs afterwards, deliberately.** Your measurement removes
  the *systematic* start bias; snap cleans up whatever per-boundary residue is
  left. They're complementary. (Whether snap still earns its keep once real
  offsets are flowing is a question for the boundary metrics, not an assumption
  we've baked in.)

### Degradation is total and silent, by design

| You send | BE behaviour |
|---|---|
| nothing / `0` | exactly today's behaviour, byte-identical |
| a sane value | applied exactly |
| unparseable (`"abc"`, `NaN`) | ignored → today's behaviour |
| out of range (>30000 or <−5000) | **rejected with a 422**, not clamped |

That last row is deliberate: an offset that far off means a bug in the sender
(sending **seconds** where milliseconds are expected is the classic), and
silently clamping it to 30s would bake a wrong timeline into the transcript
while looking like it worked. So a unit mistake fails loudly in your testing
rather than quietly corrupting production transcripts.

---

## How to verify you got it right

1. Record a deck talk, tapping to the next slide **mid-sentence** (don't pause).
2. Check the per-slide transcript: the words spoken right after each tap should
   sit on the **new** slide, not the previous one.
3. Sanity-check the value you compute: consistently 0 means you're measuring the
   same clock twice; consistently >1000ms means a unit error.

---

## Why this matters more than it looks

Every slide boundary that lands wrong corrupts two things at once: the per-slide
transcript the user reads, **and** the per-slide ranking that picks their best
take. F1 is "every word bucketed to the slide that was on screen when it was
spoken" — this is that, made exact rather than inferred.

There's a companion BE change ([#265]) that now measures how many words sit near
a boundary and how many actually move. Once your offsets are flowing we'll be
able to see the drift shrink in real data rather than arguing about it.

---

## Optional follow-up: pre-warm the microphone

The offset exists because the recorder needs time to spin up. If you open the
stream and start the recorder **before** the user taps record — discarding the
lead-in audio — there's no warm-up ramp at the moment that matters, and the
offset trends toward zero on its own. Worth considering separately; it also
removes the "first half-second of my talk got cut" class of complaint.
