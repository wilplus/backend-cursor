# Wheel: real-time metrics only (no glow)

**We only need the real-time metrics with the wheel. No glow.**

- **Wheel (real-time loudness & pace):** 100% client-side. Mic → AudioContext → AnalyserNode → RMS (loudness) and voiced ratio → WPM (pace). Example: `useRealtimeStrengthPace`. **No BFF routes required.** No `/api/...` call involved.
- **Glow (green circle + red pause dot):** Not used. Would require `recording-metrics-chunk` (PCM → backend → pause_score); we don't use it.
- **Full homework flow:** If you add it later, you’d add BFF routes for task-block, recording-1/2, metric-answers, questions, post-answers (restore from git or re-create).

**Summary:** Wheel = client-side only. No BFF needed for the wheel.
