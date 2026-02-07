# Reference frontend components

Copy these into your Next.js/React app and adjust imports and styling as needed.

- **AnswerMetricQuestionsScreen.tsx** — Step 2 of homework: "Answer these three questions". Uses `task_block.metric_question_1/2/3.text` as labels and POSTs `answer_1`, `answer_2`, `answer_3` to `/api/homework/session/:sessionId/metric-answers`. Types: `TaskBlockV2`, `MetricAnswersResponseV2` in `../types-v2.ts`.
