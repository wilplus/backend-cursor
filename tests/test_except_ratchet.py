"""Silent catch-all handlers may only get fewer (audit A4, 2026-09-28).

scripts/except_ratchet.py counts, per file, the handlers that catch
everything and keep neither the error nor its traceback. The count is
frozen in scripts/except_ratchet_baseline.json and only ever shrinks.
"""
from __future__ import annotations

import json
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import except_ratchet as er  # noqa: E402


def _silent(body: str, clause: str = "except Exception as e:") -> int:
    src = textwrap.dedent(f"""
        def f():
            try:
                work()
            {clause}
        {textwrap.indent(textwrap.dedent(body), "        ")}
    """)
    return len(er.silent_handlers(src))


def test_the_ratchet_holds_on_the_repository():
    problems = er.check(er.measure(), json.loads(er.BASELINE.read_text()))
    assert problems == [], "\n".join(problems)


def test_the_baseline_is_sorted_and_lists_only_files_with_silent_handlers():
    baseline = json.loads(er.BASELINE.read_text())
    assert baseline, "an empty baseline means the ratchet scanned nothing"
    assert list(baseline) == sorted(baseline)
    assert all(n > 0 for n in baseline.values())


@pytest.mark.parametrize("body", [
    "pass",
    "return None",
    "return []",
    "logger.warning('failed: %s', e)",
    "logger.error('failed: %s', e)",
    "log.info('x', exc_info=False)",
    "continue_with = None",
])
def test_catching_everything_without_the_traceback_is_silent(body):
    assert _silent(body) == 1


@pytest.mark.parametrize("body", [
    "raise",
    "raise RuntimeError('wrapped') from e",
    "logger.exception('failed arc=%s', arc_id)",
    "logger.warning('failed: %s', e, exc_info=True)",
    "logger.error('failed', exc_info=e)",
    "sentry_sdk.capture_exception(e)",
    "capture_exception(e)",
])
def test_re_raising_or_keeping_the_traceback_is_not_silent(body):
    assert _silent(body) == 0


@pytest.mark.parametrize("clause", [
    "except:",
    "except BaseException:",
    "except (ValueError, Exception):",
    "except builtins.Exception:",
])
def test_every_way_of_catching_everything_is_broad(clause):
    assert _silent("pass", clause) == 1


def test_a_narrow_except_is_not_counted():
    assert _silent("pass", "except (KeyError, ValueError):") == 0


def test_an_explained_noqa_is_not_counted_but_a_bare_one_is():
    explained = "except Exception:  # noqa: BLE001 - best-effort wake-up"
    assert _silent("pass", explained) == 0
    assert _silent("pass", "except Exception:  # noqa: BLE001") == 1


def test_check_catches_growth_a_first_offender_and_a_stale_baseline():
    baseline = {"a.py": 2, "gone.py": 1}
    problems = er.check({"a.py": 3, "b.py": 1}, baseline)
    text = "\n".join(problems)
    assert "a.py: 3 silent catch-all handlers (frozen at 2)" in text
    assert "b.py: 1 silent catch-all handlers (frozen at 0)" in text
    assert "gone.py: in the baseline but no longer scanned" in text
    shrunk = er.check({"a.py": 1}, {"a.py": 2})
    assert shrunk and "Lock the gain in" in shrunk[0]
    assert er.check({"a.py": 2, "c.py": 0}, {"a.py": 2}) == []
