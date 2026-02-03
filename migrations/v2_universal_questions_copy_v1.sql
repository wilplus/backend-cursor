-- Update v2 universal questions to match v1-style wording and task_score mapping.
-- Run this if you already ran v2_flow.sql and want the new question text.
-- Scoring: Q1 good=1 not great=0; Q2 1-10 → 0.1..1; Q3 guide me=0 I will choose=1.

UPDATE v2_universal_questions SET
  text = 'Do you feel more like: Good or Not great?',
  answer_type = 'binary'
WHERE code = 'mood';

UPDATE v2_universal_questions SET
  text = 'How ready is your body and mind to present? (1-10)',
  answer_type = 'scale_1_10'
WHERE code = 'readiness';

UPDATE v2_universal_questions SET
  text = 'Do you want to be guided?',
  answer_type = 'binary'
WHERE code = 'mode_preference';
