# Frontend prompt: Metrics editor (3 custom questions, same design as warm-up tasks)

Copy the prompt below into your frontend app or hand it to your frontend developer.

---

## Prompt for frontend

**1. Remove Pitch Variance from the list**

- In the **"Metrics (1 fixed + 3 custom)"** (or "Metrics") section, **remove the "Pitch Variance" card** entirely from the list of questions.
- The list should show **only the 3 custom metric questions** (metric_question_1, metric_question_2, metric_question_3). Pitch variance is not an editable question; it is a real-time metric from the recording stream and should not appear in this editor list.

**2. Design the 3 custom questions like warm-up tasks**

- **Do not** use separate heavy cards with bold titles like "Metric Question 1" and an "(editable)" label.
- **Do** use the **same design as the warm-up tasks list**: a simple vertical list where each item is a **single rounded input field** (one line per question), with minimal or no per-row title. Examples of the desired style:
  - Row 1: one input, placeholder or value e.g. "What is the 1 thing you want your audience to understand?"
  - Row 2: one input, e.g. "What is the main emotion you want them to feel during your talk?"
  - Row 3: one input, e.g. "What is your key message?"
- Same visual style as warm-up tasks: **rounded rectangles**, **one question per row**, **light background per row** if you use it for warm-up tasks, **no "Metric Question 1/2/3" headings** — just the editable text fields in a list.

**3. Data and API**

- **Load:** Call **GET /user/metric-questions** (with auth). Response: `{ metric_question_1, metric_question_2, metric_question_3 }`. Map these to the three inputs (e.g. input 1 = metric_question_1, input 2 = metric_question_2, input 3 = metric_question_3).
- **Save:** When the user finishes editing (e.g. on blur, or with a "Save" button), call **PATCH /user/metric-questions** with body:
  `{ "metric_question_1": "<value1>", "metric_question_2": "<value2>", "metric_question_3": "<value3>" }`.
- You can ignore `pitch_variance_ideal` in the UI for this list (do not show a Pitch Variance field in the metrics editor).

**4. Summary**

- **Remove** the Pitch Variance card from the metrics list.
- **Show only** the 3 custom questions, styled like the warm-up task list: simple list of rounded inputs, one per question, no bold "Metric Question N" cards or "(editable)" labels.

---

## Student flow: "Answer these questions" screen

On the screen where the student answers the metric questions (after the first recording, before "Continue"):

- **Use the actual question text from the task block** as the label for each answer field. Do **not** show generic labels like "Metric question 1" / "Metric question 2".
- **Source of text:** The task block (from recording-1 response or from the step that shows the task block) contains **metric_question_1**, **metric_question_2**, **metric_question_3**. Each has a **text** property (e.g. "What is the 1 thing you want your audience to understand?"). Use **metric_question_1.text**, **metric_question_2.text**, **metric_question_3.text** as the labels above each "Your answer..." input.
- **Number of fields:** Show **three** answer fields if the backend sends three questions (even if one has empty text; you can fallback to "Question 1" etc. when `text` is empty). Match the backend’s three questions so **answer_1**, **answer_2**, **answer_3** map correctly when submitting **POST .../metric-answers**.
- **Title:** You can change "Answer these two questions:" to "Answer these three questions:" (or "Answer the questions below:") and render the three question texts as the labels for the three inputs.
