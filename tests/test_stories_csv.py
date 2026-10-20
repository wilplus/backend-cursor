"""
GUARD    docs/TEST-STORIES.csv lists every backend test file's story, and every test file has one.
CATCHES
  C1  a new or edited test whose STORY/GUARD header is missing, or not copied into the CSV
IF REMOVED  the founder reviews a stories file that silently stops matching the tests.
PROVES   C1 -> test_every_test_file_has_a_story_and_the_csv_is_current
"""

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_every_test_file_has_a_story_and_the_csv_is_current():
    result = subprocess.run(
        [sys.executable, "scripts/stories_csv.py", "--check"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout
