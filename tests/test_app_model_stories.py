"""
GUARD      scripts/app_model_stories.py keeps The App Model's stories true and
           its page of what is left to build current (N574).
CATCHES
  C1  a story whose backend code ref names a missing file or a literal no
      line holds, or whose backend test is gone or unlisted, named by the
      story's id; the frontend's refs and tests are left to the frontend
  C2  a story marked built that names no test, unless the baseline holds it;
      a baselined story that names a test now, an id no story has, and an
      id new to the baseline (it only shrinks)
  C3  docs/APP-MODEL-TO-DO.md left stale after a story changes; code that
      only moves never makes it stale (it names no line numbers)
IF REMOVED A developer compares the code with stories that point at code and
           tests that are gone, and a story marked built proves nothing.
PROVES     C1 -> test_a_missing_ref_fails_with_the_story_id
           C2 -> test_a_built_story_with_no_test_fails_unless_baselined
           C3 -> test_a_stale_page_fails_until_it_is_written
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import app_model_stories as model

FOLDER = "docs/design/app-model-2026-11-09"
EVAL_SET = "tests/evals/golden/walk_voice.jsonl"


def story(sid, status="built", code=(), tests=(), evals=()):
    return {"id": sid, "area": "The plan", "title": f"Story {sid}", "status": status,
            "rules": ["N574 item 4"], "code": list(code), "tests": list(tests), "evals": list(evals)}


def save(root, stories, baseline=()):
    (root / FOLDER / "stories.json").write_text(json.dumps(stories), encoding="utf-8")
    (root / FOLDER / "no-test-baseline.json").write_text(json.dumps(list(baseline)), encoding="utf-8")
    model.write(root)


def repo(tmp_path, stories, baseline=()):
    """One service, a listed test, an unlisted one and a listed eval set, the
    model's folder, and its page as --write writes it."""
    for folder in ("services", "tests/evals/golden", FOLDER):
        (tmp_path / folder).mkdir(parents=True)
    (tmp_path / "services/plan.py").write_text("def plan():\n    return 'one plan'\n", encoding="utf-8")
    for name in ("tests/test_plan.py", "tests/test_unlisted.py", EVAL_SET):
        (tmp_path / name).write_text("", encoding="utf-8")
    (tmp_path / "docs/TEST-STORIES.csv").write_text(
        "file,type,story,outcomes,proves,why\ntests/test_plan.py,Story,,,,\n", encoding="utf-8")
    (tmp_path / "docs/TEST-STORIES.md").write_text(
        f"## Part 1 · Tests\n\n## Part 2 · Evals\n\n### walk_voice\n\n`{EVAL_SET}` · 1 cases\n", encoding="utf-8")
    save(tmp_path, stories, baseline)
    return tmp_path


def test_a_missing_ref_fails_with_the_story_id(tmp_path):
    root = repo(tmp_path, [
        story("PLAN-01", code=["be:services/plan.py::def plan", "be:services/gone.py::def gone",
                               "be:services/plan.py::def two_plans", "fe:src/Nowhere.tsx::anything"],
              tests=["tests/test_plan.py", "tests/test_gone.py", "tests/test_unlisted.py", "src/Nowhere.test.tsx"],
              evals=[EVAL_SET]),
    ])
    assert model.check(root, None) == [
        'PLAN-01: services/gone.py does not exist (code ref "be:services/gone.py::def gone").',
        'PLAN-01: "def two_plans" is on no line of services/plan.py.',
        "PLAN-01: the test tests/test_gone.py does not exist.",
        "PLAN-01: the test tests/test_unlisted.py is not in docs/TEST-STORIES.csv. Give it a STORY or GUARD "
        "header, then run python scripts/stories_csv.py.",
    ]


def test_a_built_story_with_no_test_fails_unless_baselined(tmp_path):
    tested = story("VOICE-08", evals=[EVAL_SET])
    root = repo(tmp_path, [story("WALK-05"), tested])
    assert model.check(root, None) == [
        "WALK-05: marked built but names no test. Name the test that proves it (N574 item 4).",
    ]

    save(root, [story("WALK-05"), tested], baseline=["WALK-05"])
    assert model.check(root, None) == []
    assert model.check(root, {"WALK-05"}) == []
    assert model.check(root, set()) == [
        "WALK-05 is new in no-test-baseline.json, which only shrinks (N574 item 4). Name the story's test instead.",
    ]

    save(root, [story("WALK-05", tests=["tests/test_plan.py"]), tested], baseline=["WALK-05", "GONE-01"])
    assert model.check(root, {"WALK-05", "GONE-01"}) == [
        "GONE-01 is in no-test-baseline.json but no story has this id: remove it from the baseline.",
        "WALK-05 names a test now: remove it from the baseline.",
    ]


def test_a_stale_page_fails_until_it_is_written(tmp_path):
    root = repo(tmp_path, [story("PLAN-16", status="not built", code=["be:services/plan.py::return 'one plan'",
                                                                       "fe:src/PlanCard.tsx::PlanCard"])])
    page = (root / model.PAGE).read_text(encoding="utf-8")
    assert "- **PLAN-16 · Story PLAN-16**" in page
    assert "Code: `services/plan.py` · `return 'one plan'`; frontend `src/PlanCard.tsx`" in page
    stale = ["docs/APP-MODEL-TO-DO.md is out of date: run python scripts/app_model_stories.py --write"]

    plan = root / "services/plan.py"
    plan.write_text("# The plan.\n" + plan.read_text(encoding="utf-8"), encoding="utf-8")
    assert model.check(root, None) == []

    (root / FOLDER / "stories.json").write_text(
        json.dumps([story("PLAN-16", tests=["tests/test_plan.py"])]), encoding="utf-8")
    assert model.check(root, None) == stale
    model.write(root)
    assert model.check(root, None) == []
    assert "PLAN-16" not in (root / model.PAGE).read_text(encoding="utf-8")
