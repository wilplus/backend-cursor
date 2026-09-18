"""No route may hardcode the coach-media bucket name.

WHAT WENT WRONG (traced 2026-09-17 from Sentry PYTHON-FLASK-67).

Until #484 the R2 branch of `put_coach_object_bytes` / `presigned_get_coach_object`
IGNORED its `bucket` argument::

    b = r2_bucket_name()                           # before #484
    b = (bucket or "").strip() or r2_bucket_name()  # after

so the literal "coach_feedback_videos" sprinkled through the routes was inert
and provably harmless. #484 made the caller's string authoritative — to enable
the lab-audio bucket split — and at that moment every remaining literal became
a REAL bucket name.

It is not a valid one. S3/R2 bucket names take no underscores; config's own
comment gives the hyphenated "coach-feedback-videos" as the example. So the
write target became a bucket that cannot exist, which R2 rejects as
InvalidBucketName, and the presign target became a URL pointing at nothing.

#513 fixed the deck-upload site. This test exists because fixing call sites one
Sentry issue at a time is how the next one gets missed: `routes/v2/user_account.py`
was still passing the literal a week later.

`r2_bucket_name()` (R2_BUCKET_NAME, else COACH_FEEDBACK_VIDEO_BUCKET) is the
single source of truth, and passing "" selects it.

NOT A BAN ON THE STRING. config.py legitimately holds it as the default, and
the Supabase fallback path accepts underscores — the default is correct THERE.
The rule is only that a ROUTE must not pass it as a literal argument.

Run: python3 -m unittest tests.test_coach_bucket_literals
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

#: Call sites that hand a bucket to the storage layer.
_CALLS = re.compile(
    r"(?:put_coach_object_bytes|presigned_get_coach_object|get_coach_object_bytes)"
    r"\(\s*\"coach_feedback_videos\""
)


def _route_files() -> list[Path]:
    return sorted(Path("routes").rglob("*.py"))


class RoutesResolveTheBucket(unittest.TestCase):
    def test_no_route_passes_the_literal_to_the_storage_layer(self):
        offenders = []
        for path in _route_files():
            text = path.read_text(encoding="utf-8")
            for match in _CALLS.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{path}:{line}")
        self.assertEqual(
            offenders, [],
            "pass \"\" (or r2_bucket_name()) instead of the literal: "
            + ", ".join(offenders),
        )

    def test_the_config_default_is_still_allowed_to_hold_it(self):
        """The rule is about ROUTES, not about the string existing. config.py
        is where the Supabase-fallback default legitimately lives."""
        config = Path("config.py").read_text(encoding="utf-8")
        self.assertIn("coach_feedback_videos", config)

    def test_r2_bucket_name_is_the_single_source_of_truth(self):
        storage = Path("services/coach_video_storage.py").read_text(encoding="utf-8")
        self.assertIn("def r2_bucket_name()", storage)
        # The caller's string still wins when given — that is #484's contract
        # and the lab-audio split depends on it. Passing "" is what selects
        # the configured default.
        self.assertIn('(bucket or "").strip() or r2_bucket_name()', storage)


if __name__ == "__main__":
    unittest.main()
