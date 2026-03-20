-- Student details for admin-editable name and live lesson price (USD).
-- Safe to run multiple times.

CREATE TABLE IF NOT EXISTS v2_student_details (
  user_id UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  name TEXT,
  price_per_live_lesson NUMERIC(10,2),
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'v2_student_details_price_non_negative'
  ) THEN
    ALTER TABLE v2_student_details
      ADD CONSTRAINT v2_student_details_price_non_negative
      CHECK (price_per_live_lesson IS NULL OR price_per_live_lesson >= 0);
  END IF;
END $$;

COMMENT ON TABLE v2_student_details IS 'Admin-editable student details used by admin UI.';
COMMENT ON COLUMN v2_student_details.price_per_live_lesson IS 'USD dollars per live lesson (decimal, e.g. 49.99).';
