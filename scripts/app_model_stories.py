#!/usr/bin/env python3
"""The App Model's stories stay true, and the page of what is left to build is
generated from them (founder, the Claude Code chat, 9 November 2026, N574).

WHY. The App Model joins every locked prototype into one clickable phone, with
the user stories beside it: each a Given, a When and a Then, the rule it comes
from, the code that does it, the test that proves it, and its state (built,
partly, not built, differs). A developer compares the code with it; where they
differ, the code is the bug to fix (N95). The stories help only while they
point at code and tests that exist, so CI checks them, and the list of what is
left to build is generated from them instead of kept by hand.

The model is the newest docs/design/app-model-<date>/ that has a stories.json.
A story's code refs are in source form: "be:<path>::<literal>" in this repo,
"fe:<path>::<literal>" in the frontend; the literal may be left out. Its tests
are paths: a backend test (.py) or eval set (.jsonl), or a frontend test (any
other file, which the frontend checks; N574 item 4).

    python scripts/app_model_stories.py --check   # CI ("App Model stories") and scripts/local_ci.sh
    python scripts/app_model_stories.py --write   # regenerate docs/APP-MODEL-TO-DO.md

--check fails when
  * a "be:" ref's file does not exist, or its literal is on no line of it;
  * a backend test a story names does not exist, or is not in
    docs/TEST-STORIES.csv (an eval set: not in docs/TEST-STORIES.md part 2);
  * a story marked built names no test and no eval set, and its id is not in
    the folder's no-test-baseline.json (the stories before N574);
  * an id in the baseline names a test now, is no longer marked built, or no
    longer exists (remove it from the baseline), or is not in the base's
    baseline (it only shrinks; the base is origin/main, as for the docs guard);
  * docs/APP-MODEL-TO-DO.md is not what --write would write.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DESIGN = "docs/design"
FOLDER = "app-model-"
STORIES = "stories.json"
BASELINE = "no-test-baseline.json"
PAGE = "docs/APP-MODEL-TO-DO.md"
TESTS_CSV = "docs/TEST-STORIES.csv"
TESTS_PAGE = "docs/TEST-STORIES.md"
LINK = "https://claude.ai/artifact/G3Lbr2CNTGMAbyfZ8EfMGg"
WRITE = "python scripts/app_model_stories.py --write"
#: The states left to build, in the page's order, with their headings.
LEFT = {"not built": "Not built", "partly": "Partly built", "differs": "Differs: the code disagrees with the rule"}
STATES = (*LEFT, "built")
_EVAL_SET = re.compile(r"^`([^`]+\.jsonl)` · ", re.M)

Story = dict[str, Any]


def model_dir(root: Path) -> Path | None:
    """The newest docs/design/app-model-<date>/ with a stories.json."""
    found = sorted(p.parent for p in (root / DESIGN).glob(f"{FOLDER}*/{STORIES}"))
    return found[-1] if found else None


def load(folder: Path) -> tuple[list[Story], set[str]]:
    """The stories, and the ids in the baseline (none when the file is missing).
    Raises ValueError when either file is not the JSON it should be."""
    stories = json.loads((folder / STORIES).read_text(encoding="utf-8"))
    if not isinstance(stories, list) or not all(isinstance(s, dict) for s in stories):
        raise ValueError(f"{STORIES} is not a list of stories")
    for story in stories:
        if not_lists := [k for k in ("then", "rules", "code", "tests", "evals") if not isinstance(story.get(k, []), list)]:
            raise ValueError(f"{story.get('id')}: {', '.join(not_lists)} must be a list")
    baseline = folder / BASELINE
    ids = json.loads(baseline.read_text(encoding="utf-8")) if baseline.is_file() else []
    if not isinstance(ids, list):
        raise ValueError(f"{BASELINE} is not a list of story ids")
    return stories, {str(i) for i in ids}


def parse_ref(ref: str) -> tuple[str, str, str] | None:
    """("be" or "fe", path, literal) for "be:<path>::<literal>"; None when malformed."""
    side, sep, rest = ref.partition(":")
    path, _, literal = rest.partition("::")
    if not sep or side not in ("be", "fe") or not path or Path(path).is_absolute() or ".." in Path(path).parts:
        return None
    return side, path, literal


def locate(root: Path, path: str, literal: str) -> int | None:
    """The first line of the file that holds the literal, 0 for a ref with no
    literal, None when the file or the literal is not there."""
    file = root / path
    if not file.is_file():
        return None
    if not literal:
        return 0
    lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
    return next((n for n, line in enumerate(lines, 1) if literal in line), None)


def is_backend_test(path: str) -> bool:
    return path.endswith((".py", ".jsonl"))


def tests_of(story: Story) -> list[str]:
    """The tests and the eval sets a story names."""
    return [str(t) for t in (*(story.get("tests") or []), *(story.get("evals") or []))]


def listed_tests(root: Path) -> tuple[set[str], set[str]]:
    """The test files docs/TEST-STORIES.csv lists, and the eval sets in part 2
    of docs/TEST-STORIES.md (both written by scripts/stories_csv.py)."""
    tests: set[str] = set()
    evals: set[str] = set()
    table = root / TESTS_CSV
    if table.is_file():
        with table.open(encoding="utf-8", newline="") as fh:
            tests = {row["file"] for row in csv.DictReader(fh) if row.get("file")}
    page = root / TESTS_PAGE
    if page.is_file():
        evals = set(_EVAL_SET.findall(page.read_text(encoding="utf-8").partition("## Part 2")[2]))
    return tests, evals


def check_story(story: Story, root: Path, tests: set[str], evals: set[str]) -> list[str]:
    """One story's problems: its state, its backend code refs and its backend tests."""
    sid = story.get("id") or "a story with no id"
    problems = []
    if story.get("status") not in STATES:
        problems.append(f"{sid}: the status {story.get('status')!r} is not one of: {', '.join(STATES)}.")
    for ref in map(str, story.get("code") or []):
        parsed = parse_ref(ref)
        if parsed is None:
            problems.append(f'{sid}: the code ref "{ref}" is not "be:<path>::<literal>" or "fe:<path>::<literal>".')
            continue
        _, path, literal = parsed
        if ref.startswith("be:") and locate(root, path, literal) is None:
            problems.append(f'{sid}: "{literal}" is on no line of {path}.' if (root / path).is_file()
                            else f'{sid}: {path} does not exist (code ref "{ref}").')
    for test in filter(is_backend_test, tests_of(story)):
        if not (root / test).is_file():
            problems.append(f"{sid}: the test {test} does not exist.")
        elif test.endswith(".jsonl") and test not in evals:
            problems.append(f"{sid}: the eval set {test} is not in {TESTS_PAGE} part 2. "
                            "Run python scripts/stories_csv.py.")
        elif test.endswith(".py") and test not in tests:
            problems.append(f"{sid}: the test {test} is not in {TESTS_CSV}. Give it a STORY or GUARD header, "
                            "then run python scripts/stories_csv.py.")
    return problems


def check_baseline(stories: list[Story], baseline: set[str], base: set[str] | None) -> list[str]:
    """A story marked built names a test, unless the baseline holds it; the
    baseline holds only such stories, and only shrinks against the base's."""
    by_id = {s.get("id"): s for s in stories}
    problems = [f"{s.get('id')}: marked built but names no test. Name the test that proves it (N574 item 4)."
                for s in stories
                if s.get("status") == "built" and not tests_of(s) and s.get("id") not in baseline]
    for sid in sorted(baseline):
        story = by_id.get(sid)
        if story is None:
            problems.append(f"{sid} is in {BASELINE} but no story has this id: remove it from the baseline.")
        elif tests_of(story):
            problems.append(f"{sid} names a test now: remove it from the baseline.")
        elif story.get("status") != "built":
            problems.append(f"{sid} is no longer marked built: remove it from the baseline.")
        elif base is not None and sid not in base:
            problems.append(f"{sid} is new in {BASELINE}, which only shrinks (N574 item 4). "
                            "Name the story's test instead.")
    return problems


def check(root: Path, base: set[str] | None) -> list[str]:
    """Every problem --check reports. `base` is the base's baseline, None when
    the base has no model yet."""
    folder = model_dir(root)
    if folder is None:
        return [f"no {DESIGN}/{FOLDER}<date>/{STORIES}: the model is not pinned (N574 item 1)."]
    try:
        stories, baseline = load(folder)
    except ValueError as err:
        return [f"{folder.relative_to(root).as_posix()}: {err}."]
    tests, evals = listed_tests(root)
    ids = [s.get("id") for s in stories]
    problems = [f"{sid}: two stories have this id." for sid in sorted({i for i in ids if ids.count(i) > 1}, key=str)]
    for story in stories:
        problems += check_story(story, root, tests, evals)
    problems += check_baseline(stories, baseline, base)
    page = root / PAGE
    if not page.is_file() or page.read_text(encoding="utf-8") != render(root):
        problems.append(f"{PAGE} is out of date: run {WRITE}")
    return problems


def _ref(root: Path, ref: str) -> str:
    """A code ref as the page shows it: this repo's as `file:line`, the
    frontend's as its path."""
    parsed = parse_ref(ref)
    if parsed is None:
        return f"`{ref}`"
    side, path, literal = parsed
    if side == "fe":
        return f"frontend `{path}`"
    line = locate(root, path, literal)
    return f"`{path}:{line}`" if line else f"`{path}`"


def _test(path: str) -> str:
    if path.endswith(".jsonl"):
        return f"`{path}` (eval set)"
    return f"`{path}`" if is_backend_test(path) else f"frontend `{path}`"


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _rules(story: Story) -> str:
    return "; ".join(_text(r) for r in story.get("rules") or []) or "none named"


def _entry(root: Path, story: Story) -> list[str]:
    code = _unique([_ref(root, str(r)) for r in story.get("code") or []])
    tests = _unique([_test(t) for t in tests_of(story)])
    lines = [f"- **{story.get('id')} · {_text(story.get('title'))}**",
             f"  - Rules: {_rules(story)}",
             f"  - Code: {'; '.join(code) or 'none yet'}",
             f"  - Tests: {'; '.join(tests) or 'none yet'}"]
    if story.get("note"):
        lines.append(f"  - Note: {_text(story['note'])}")
    return lines


def render(root: Path) -> str:
    """docs/APP-MODEL-TO-DO.md, from the stories and this repo's files."""
    folder = model_dir(root)
    if folder is None:
        return ""
    stories, _ = load(folder)
    where = folder.relative_to(root).as_posix()
    count = {state: sum(1 for s in stories if s.get("status") == state) for state in STATES}
    left = [s for s in stories if s.get("status") in LEFT]
    untested = [s for s in stories if s.get("status") == "built" and not tests_of(s)]
    out = ["# The App Model: what is left to build", "",
           "> **Label: Reference** · generated from The App Model's stories (N574); where it differs from the "
           "In force docs, they win. Every doc and its label: [`README.md`](../README.md) (N106).", "",
           f"Generated by `{WRITE}` from the stories of The App Model, the developer's "
           f"reference (<{LINK}>), pinned in [`{where}/`]({where.removeprefix('docs/')}/). Generated, do not "
           f"edit: change `{STORIES}` there, then run the script. CI fails while this page is out of date.", "",
           f"**{len(stories)} stories:** {count['built']} built, {count['partly']} partly built, "
           f"{count['not built']} not built, {count['differs']} where the code disagrees with the rule. This page "
           f"lists the {len(left)} left to build, by state, then by area, each with its rules, its code (this "
           "repo's as `file:line`, the frontend's as paths), its tests and its note; then the built stories "
           f"that name no test yet, the baseline in `{BASELINE}`, which only shrinks."]
    areas = _unique([str(s.get("area")) for s in stories])
    for state, heading in LEFT.items():
        in_state = [s for s in left if s.get("status") == state]
        out += ["", f"## {heading} ({len(in_state)})"]
        for area in areas:
            in_area = [s for s in in_state if str(s.get("area")) == area]
            if in_area:
                out += ["", f"### {area} ({len(in_area)})", ""]
                for story in in_area:
                    out += _entry(root, story)
    out += ["", f"## Built, with no test yet ({len(untested)})", ""]
    out += [f"- **{s.get('id')} · {_text(s.get('title'))}** ({_rules(s)})" for s in untested]
    return "\n".join(out).rstrip() + "\n"


def write(root: Path) -> Path:
    page = root / PAGE
    page.write_text(render(root), encoding="utf-8")
    return page


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def base_baseline(base: str) -> set[str] | None:
    """The baseline in the base's newest model folder; None when the base has
    no model yet. Raises CalledProcessError when the base cannot be seen."""
    git("rev-parse", "--verify", "--quiet", f"{base}^{{commit}}")
    names = git("ls-tree", "-r", "--name-only", base, "--", DESIGN).splitlines()
    folders = sorted(n.rsplit("/", 1)[0] for n in names
                     if re.fullmatch(rf"{re.escape(DESIGN)}/{FOLDER}[^/]+/{STORIES}", n))
    if not folders:
        return None
    path = f"{folders[-1]}/{BASELINE}"
    return {str(i) for i in json.loads(git("show", f"{base}:{path}"))} if path in names else set()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="fail when a story is not true or the page is stale")
    mode.add_argument("--write", action="store_true", help=f"regenerate {PAGE}")
    ap.add_argument("--base", default="origin/main", help="the baseline is compared with this one's")
    args = ap.parse_args(argv)
    folder = model_dir(ROOT)
    if args.write:
        if folder is None:
            print(f"no {DESIGN}/{FOLDER}<date>/{STORIES}: nothing to write.")
            return 2
        try:
            print(f"wrote {write(ROOT).relative_to(ROOT)} from {folder.relative_to(ROOT).as_posix()}")
        except ValueError as err:
            print(f"{folder.relative_to(ROOT).as_posix()}: {err}. Nothing written.")
            return 2
        return 0
    code = 1
    try:
        problems = check(ROOT, base_baseline(args.base))
    except subprocess.CalledProcessError:
        code = 2
        problems = check(ROOT, None) + [f"cannot see the base {args.base}, so the baseline was not compared "
                                        "with it. Fetch it (git fetch origin main)."]
    if problems:
        print("App Model stories: " + ("RED" if code == 1 else "CANNOT CHECK") + f", {len(problems)} problem(s):")
        for line in problems:
            print("  " + line)
        print(f"The model and its stories: {DESIGN}/{FOLDER}<date>/ (N574). The page: {PAGE}.")
        return code
    assert folder is not None
    stories, baseline = load(folder)
    print(f"App Model stories: clean. {len(stories)} stories in {folder.relative_to(ROOT).as_posix()}; every "
          f"backend ref and test holds; {len(baseline)} built stories with no test in the baseline; "
          f"{PAGE} is current.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
