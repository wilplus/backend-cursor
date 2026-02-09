# Cursor prompt — Real-time Strength + Pace wheel (smooth ball)

**Paste this into Cursor (frontend repo) as your instruction. It is scoped to real-time Strength + Pace only and produces a smooth-moving ball on a 2D wheel/dartboard. Cursor should wait for your confirmation before implementing.**

---

You are implementing **real-time Strength (volume) + Pace** feedback only, shown as a **smooth-moving ball** on a 2D wheel/dartboard UI while the user is recording.

### Hard constraints
- Real-time metrics are **Strength + Pace only**. Do **not** attempt fillers/emotion/keywords/score_1 in real time.
- No backend changes required for MVP real-time view.
- Update loop: **every 100ms**
- Must be **smooth motion** (no jitter). Use smoothing (EMA / low-pass) + animation frame interpolation.
- Keep existing recording flow intact (upload still computes final scores after).

---

# 1) What to build (frontend)

## 1.1 A reusable hook: `useRealtimeStrengthPace()`
Create a hook that:
- Requests mic access (`getUserMedia({ audio: true })`)
- Creates `AudioContext`, `MediaStreamAudioSourceNode`, and an `AnalyserNode`
- Every 100ms:
  1) reads time-domain samples (`getFloatTimeDomainData`)
  2) computes RMS and converts to dB
  3) converts dB → `strengthScore` (0..1) using a band score with smoothstep:
     - target = **-22 dB**, tolerance = **±6 dB**
  4) estimates speech activity / pace:
     - compute per-frame energy; mark "voiced" if RMS > threshold (e.g. -45 dB)
     - maintain a rolling window (e.g. last 3 seconds) of voiced ratio
     - map voiced ratio → WPM estimate (simple linear mapping is OK for realtime)
     - convert WPM → `paceScore` (0..1) using band score with smoothstep:
       - target = **140 WPM**, tolerance = **±30 WPM**
- Applies smoothing:
  - Use an EMA to smooth scores and ball position:
    - `smoothed = alpha*current + (1-alpha)*prev`
    - alpha around 0.15–0.25
- Expose:
  - `strengthScore` (smoothed)
  - `paceScore` (smoothed)
  - `strengthDb` (raw)
  - `wpmEstimate` (raw)
  - `isActive` + `start()` + `stop()` to manage lifecycle and cleanup

## 1.2 A component: `StrengthPaceDartboard`
Render a 2D dartboard/wheel in **SVG**:
- X-axis = strength (quiet ↔ loud)
- Y-axis = pace (slow ↔ fast)
- Show:
  - rings / target circle
  - axis labels ("Quiet/Loud", "Too Slow/Too Fast")
  - moving ball
- Ball position mapping:
  - convert scores (0..1) to normalized (-1..+1):
    - `x = (strengthScore - 0.5) * 2`
    - `y = (paceScore - 0.5) * 2`
  - clamp x,y to [-1,1]
- Smooth movement requirement:
  - Use requestAnimationFrame to animate the ball toward the latest target position
  - Or set SVG circle cx/cy from smoothed x/y values updated every 100ms (acceptable if EMA is used)

## 1.3 Integrate into recording UI
- When recording starts: call `start()`
- When recording stops: call `stop()`
- Show real-time numeric readouts (optional):
  - `strengthDb` (dB)
  - `wpmEstimate` (WPM)
- Ensure cleanup:
  - stop audio tracks
  - close AudioContext
  - clear intervals/raf

---

# 2) Definitions (use these formulas)

## 2.1 RMS → dB
- `rms = sqrt(mean(samples[i]^2))`
- `db = 20 * log10(rms + 1e-8)`

## 2.2 Band score helper (0..1)
Implement `bandScore(value, target, tolerance)`:
- `distance = abs(value - target)`
- `raw = 1 - (distance / tolerance)`
- clamp 0..1
Then apply smoothstep:
- `smoothstep(t) = t*t*(3 - 2*t)`

### Strength score
- targetDb = -22
- toleranceDb = 6

### Pace score
- targetWpm = 140
- toleranceWpm = 30

## 2.3 Pace estimation (simple, realtime)
- Define `voiced = (db > -45)` per frame
- Maintain a rolling window over ~3 seconds (30 samples if you update 100ms)
- `voicedRatio = voicedCount / windowSize`
- Map to WPM estimate:
  - `wpmEstimate = 60 + voicedRatio * 160`
  - clamp to [60, 220] (or reasonable bounds)

---

# 3) Do NOT do
- Do not compute final `score_1` or integrate with backend scoring.
- Do not add new backend endpoints.
- Do not try to infer fillers/emotion/keywords in real time.

---

# 4) Deliverables
1) `useRealtimeStrengthPace.ts` hook (or similar path in repo)
2) `StrengthPaceDartboard.tsx` SVG component
3) Integration into the existing recording step (warmup + main can reuse it)
4) Short README comment in code explaining: realtime = strength/pace feedback only; final score still post-upload.

---

# 5) Before implementing: show me the plan
First respond with:
- Which files you will create/edit
- The exact public API of the hook (functions + returned values)
- The SVG coordinate system and mapping
- The smoothing approach (EMA parameters)
- Any UI changes/screens where it appears

Then stop and ask:

**"Waiting for confirmation: Reply YES to implement, or list changes."**

Do not implement until I confirm.
