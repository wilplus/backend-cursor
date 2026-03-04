# Report screen: score and graph consistency

Use **one** score (Sniper Voice Alignment) for both the main “Your result” and the performance chart so the numbers always match.

## Backend

- **Single score source:** Sniper (`session_sniper_metrics.stage_score`) when the frontend has sent it via `POST .../sniper-session-complete`. Otherwise the backend uses `performance_score_end` from the session (which is also set from Sniper at completion when available).
- **`score_for_display`** (0–100) = canonical “your result” / “Voice Alignment”. Same value as the last bar on the chart.
- **`scores.overall`** = same as `score_for_display`. No other scores (warmup/final) are returned; one metric only.
- **Coach email:** The “End score: X%” in the lesson-complete email to the coach is this same single score (`performance_score_end` stored on the session — Sniper when available). No other performance metrics are shown.

## Frontend implementation

1. **Types:** Use `HomeworkReportResponseV2` from `docs/frontend-v2-deliverables/types-v2.ts` for the GET report response.

2. **Main “Your result” / “Voice Alignment”:**
   ```ts
   const score = report.score_for_display; // 0–100
   ```

3. **Performance chart (history):**
   - Use `report.performance_history` as-is: `{ date, score }[]`.
   - The last item is the current session; its `score` equals `score_for_display`.
   - Use only `score_for_display` (or `scores.overall`) for the main number and chart.

## Example (React)

```tsx
// Report data from GET /api/homework/session/[sessionId]/report
const report: HomeworkReportResponseV2 = await fetchReport(sessionId);

// Main result – use this everywhere you show “your score”
const mainScore = report.score_for_display; // 0–100

return (
  <>
    <h2>Your result: {mainScore}%</h2>
    <PerformanceChart data={report.performance_history} />
    {/* last bar value === mainScore */}
  </>
);
```

**Important:** The frontend must call `POST .../sniper-session-complete` with `stage_score` (0–100) when the user finishes recording, so the backend can store it and use it for the report and chart. Otherwise the displayed score may fall back to the batch metrics value.
