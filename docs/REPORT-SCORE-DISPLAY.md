# Report screen: score and graph consistency

Use **one** score for both the main “Your result” and the performance chart so the numbers always match.

## Backend

- **`score_for_display`** (0–100) = canonical “your result”. Same value as the last bar on the chart.
- **`scores.overall`** = same as `score_for_display` (derived from `performance_score_end`).
- **`scores.final`** = raw recording-2 average (5 metrics). Do **not** use this for the main display or it will not match the graph.

## Frontend implementation

1. **Types:** Use `HomeworkReportResponseV2` from `docs/frontend-v2-deliverables/types-v2.ts` for the GET report response.

2. **Main “Your result” / “Your score”:**
   ```ts
   const score = report.score_for_display; // 0–100
   // e.g. "Your result: 70%" or a big number + "%"
   ```

3. **Performance chart (history):**
   - Use `report.performance_history` as-is: `{ date, score }[]`.
   - The last item is the current session; its `score` equals `score_for_display`.
   - Do not derive the main number from `scores.final` or `performance_score_2`; use `score_for_display` (or `scores.overall`) only.

4. **Optional breakdown:** If you show warmup vs final, use `scores.warmup` and `scores.final` as secondary info, but keep the **primary** displayed score as `score_for_display` so it matches the chart.

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

If you previously used `report.scores.final` or `report.scores.overall` for the main number, switch to `report.score_for_display` so the main result and the graph always show the same value.
