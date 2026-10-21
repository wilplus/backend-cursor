"""
GUARD      scripts/doc_guard.py: every part of the code has one home doc in
           README.md, every doc is listed there, and a new doc carries the
           founder's OK (N107, N111).
CATCHES    Code that no row of the home-doc table covers; a row that covers
           nothing or points at a missing, History or Archive doc; two rows
           claiming one file equally; a doc the master doc doesn't list; a new
           doc without `Founder-Approved:` on its line.
IF REMOVED The docs pile up again, one new file per piece of work, as they
           did until 21 October 2026 (423 files).
PROVES     test_code_no_row_covers_is_named
           test_the_most_exact_pattern_wins
           test_an_equal_claim_with_two_homes_is_refused
           test_a_stale_row_and_a_bad_home_are_refused
           test_every_doc_is_listed_except_runtime_prompts
           test_a_new_doc_needs_the_founders_ok
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import doc_guard as guard


def readme(*rows: str, extra: str = "") -> str:
    table = "\n".join(["| Part of the code | Files | Home doc |", "|---|---|---|", *rows])
    return f"# Master\n\n{guard.START}\n{table}\n{guard.END}\n{extra}"


def problems(files, text, root):
    return guard.check_homes(files, guard.parse_homes(text), root)


def test_code_no_row_covers_is_named(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/QUORUM.md").write_text("# Quorum\n")
    text = readme("| Labels | `services/label_*`, `routes/v2/research.py` | [`docs/QUORUM.md`](docs/QUORUM.md) |")
    files = ["services/label_quorum.py", "routes/v2/research.py", "services/brand_new.py",
             "tests/test_label_quorum.py", "docs/QUORUM.md", ".gitignore"]
    out = problems(files, text, tmp_path)
    assert out == ["services/brand_new.py has no home doc. Add it to a row of the table in README.md, or add a row."]


def test_the_most_exact_pattern_wins(tmp_path):
    text = readme("| Coach | `services/coach_*` | No page |",
                  "| Learning | `services/coach_word_pairs.py` | [`docs/Q.md`](docs/Q.md) |")
    rows = guard.parse_homes(text)
    winners, _ = guard.home_of("services/coach_word_pairs.py", rows)
    assert [w.part for w in winners] == ["Learning"]
    winners, _ = guard.home_of("services/coach_queue.py", rows)
    assert [w.home for w in winners] == [None]


def test_an_equal_claim_with_two_homes_is_refused(tmp_path):
    text = readme("| A | `services/x_*` | No page |",
                  "| B | `services/x_*` | [`docs/B.md`](docs/B.md) |")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/B.md").write_text("# B\n")
    out = problems(["services/x_one.py"], text, tmp_path)
    assert out == ["services/x_one.py is claimed equally by services/x_*, services/x_*, with different home docs."]


def test_a_stale_row_and_a_bad_home_are_refused(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs/OLD.md").write_text("# Old\n\n> **Label: History** · kept as written.\n")
    text = readme("| Gone | `services/gone.py` | No page |",
                  "| Old | `app.py` | [`docs/OLD.md`](docs/OLD.md) |",
                  "| Missing | `config.py` | [`docs/NOPE.md`](docs/NOPE.md) |",
                  "| Frontend | `worker.py` | [frontend](https://github.com/wilplus/frontend-cursor/blob/main/docs/flows/x.md) |")
    out = problems(["app.py", "config.py", "worker.py"], text, tmp_path)
    assert out == [
        "the pattern services/gone.py (Gone) matches no file. Remove it, or fix it after a rename.",
        "the home doc docs/OLD.md (Old) is History or Archive, which is not edited. Pick a doc that is.",
        "the home doc docs/NOPE.md (Missing) does not exist.",
    ]
    assert problems(["app.py"], readme(), tmp_path) == [
        "README.md has no home-doc table between <!-- code-homes:start --> and <!-- code-homes:end -->."]


def test_every_doc_is_listed_except_runtime_prompts():
    text = "- [Spec](docs/SPEC.md) · Reference\n- [Old](docs/history/OLD.md#top)\n"
    files = ["README.md", "docs/SPEC.md", "docs/history/OLD.md", "docs/NEW.md", "services/prompts/strategy.md"]
    assert guard.check_listed(files, text) == [
        "docs/NEW.md is not listed in README.md. Every doc has a line there with its label (N106)."]


def test_a_new_doc_needs_the_founders_ok():
    without = "- [New](docs/NEW.md) · `backend` `docs/NEW.md`\n"
    empty = "- [New](docs/NEW.md) · Founder-Approved:\n"
    approved = "- [New](docs/NEW.md) · Founder-Approved: decision page, 2026-10-21\n"
    added = ["docs/NEW.md", "services/new.py", "services/prompts/new_prompt.md"]
    assert len(guard.check_new(added, without)) == 1
    assert "docs/NEW.md is a new doc" in guard.check_new(added, empty)[0]
    assert guard.check_new(added, approved) == []
