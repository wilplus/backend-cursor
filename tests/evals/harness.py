"""Generic golden-eval harness — the master_doc_probe pattern, reusable.

master_doc_probe.py proved the shape: deterministic structural checks
first (code counts characters, LLMs don't), then an optional semantic
LLM grader at temperature 0, only when the rubric declares
``semantic_intent``. This module generalizes that so ANY surface can be
eval-gated from a golden JSONL dataset the founder authors — see
docs/prompt_evals.md for the dataset format.

Roles:
  * the FOUNDER owns the golden datasets (tests/evals/golden/*.jsonl)
    — inputs, rubrics, preferred outputs;
  * engineering owns the adapters (tests/evals/surfaces.py) that feed
    a case's ``input`` into the real production function;
  * CI owns when they run (prompt drift in the lockfile → the changed
    surfaces' datasets run against live LLM calls).

Never writes to the DB. Costs pennies per run (probe precedent:
~$0.06). Skips green without OPENAI_API_KEY — the gate is armed by the
repo secret, never red for a missing credential.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"

_POLISH_DIACRITICS = set("ąćęłńóśźż")
_DIGIT_RE = re.compile(r"\d")


# ─────────────────────────────────────────────────────────────────
# Golden cases
# ─────────────────────────────────────────────────────────────────


@dataclass
class GoldenCase:
    id: str
    surface: str
    input: dict
    rubric: dict
    description: str = ""
    notes: str = ""


@dataclass
class Verdict:
    case_id: str
    surface: str
    passed: bool
    reason: str = ""
    description: str = ""
    output: Any = None


_REQUIRED_KEYS = ("id", "surface", "input", "rubric")

_KNOWN_RUBRIC_KEYS = {
    "semantic_intent",
    "must_mention_substrings", "must_not_mention_substrings",
    "must_mention_any", "must_not_substring",
    "max_chars", "no_digits", "must_not_match_construct",
    "must_contain_polish_diacritic",
    "expect", "expect_contains", "substring_of_input",
    "allow_none_output",
}


def validate_case_dict(raw: Any, *, where: str = "") -> list[str]:
    """Structural validation of one golden-case dict. Returns problem
    strings (empty = valid). Pure — used by the unit tier and the
    validator CLI so a malformed dataset fails fast, not mid-eval."""
    problems: list[str] = []
    if not isinstance(raw, dict):
        return [f"{where}: case is not an object"]
    for key in _REQUIRED_KEYS:
        if key not in raw:
            problems.append(f"{where}: missing required key {key!r}")
    if not isinstance(raw.get("input"), dict):
        problems.append(f"{where}: 'input' must be an object")
    rubric = raw.get("rubric")
    if not isinstance(rubric, dict) or not rubric:
        problems.append(f"{where}: 'rubric' must be a non-empty object")
    else:
        unknown = set(rubric) - _KNOWN_RUBRIC_KEYS
        if unknown:
            problems.append(
                f"{where}: unknown rubric key(s) {sorted(unknown)} — "
                f"known keys: {sorted(_KNOWN_RUBRIC_KEYS)}"
            )
    return problems


def load_golden(surface: str) -> list[GoldenCase]:
    """Load tests/evals/golden/<surface>.jsonl. Raises ValueError on a
    malformed file — a broken golden dataset must fail loudly."""
    path = GOLDEN_DIR / f"{surface}.jsonl"
    cases: list[GoldenCase] = []
    problems: list[str] = []
    for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        where = f"{path.name}:{lineno}"
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as e:
            problems.append(f"{where}: invalid JSON — {e}")
            continue
        problems.extend(validate_case_dict(raw, where=where))
        if not problems:
            cases.append(GoldenCase(
                id=str(raw["id"]),
                surface=str(raw["surface"]),
                input=raw["input"],
                rubric=raw["rubric"],
                description=str(raw.get("description") or ""),
                notes=str(raw.get("notes") or ""),
            ))
    if problems:
        raise ValueError("golden dataset invalid:\n  " + "\n  ".join(problems))
    ids = [c.id for c in cases]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"{path.name}: duplicate case ids {sorted(dupes)}")
    return cases


def available_surfaces() -> list[str]:
    """Surfaces that have a golden dataset on disk."""
    if not GOLDEN_DIR.is_dir():
        return []
    return sorted(p.stem for p in GOLDEN_DIR.glob("*.jsonl"))


# ─────────────────────────────────────────────────────────────────
# Deterministic checks (run first; grader only after these pass)
# ─────────────────────────────────────────────────────────────────


def _flatten(output: Any) -> str:
    """The text the substring/length checks run against."""
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    return json.dumps(output, ensure_ascii=False, sort_keys=True)


def _dig(obj: Any, dotted: str) -> Any:
    cur = obj
    for part in dotted.split("."):
        if isinstance(cur, dict):
            cur = cur.get(part)
        elif isinstance(cur, list) and part.isdigit():
            idx = int(part)
            cur = cur[idx] if 0 <= idx < len(cur) else None
        else:
            return None
    return cur


def deterministic_check(case: GoldenCase, output: Any) -> Optional[str]:
    """None on pass, reason string on failure. Mirrors (and extends)
    master_doc_probe._deterministic_check."""
    rubric = case.rubric

    if output is None:
        if rubric.get("allow_none_output"):
            return None
        return "surface returned None (generation failed or was guarded away)"

    text = _flatten(output)
    text_lower = text.lower()

    max_chars = rubric.get("max_chars")
    if isinstance(max_chars, int) and len(text) > max_chars:
        return f"output too long ({len(text)} chars > {max_chars})"

    for needle in rubric.get("must_not_mention_substrings", []) or []:
        if needle.lower() in text_lower:
            return f"output contains forbidden substring: {needle!r}"

    for needle in rubric.get("must_mention_substrings", []) or []:
        if needle.lower() not in text_lower:
            return f"output is missing required substring: {needle!r}"

    any_of = rubric.get("must_mention_any")
    if any_of and not any(n.lower() in text_lower for n in any_of):
        return f"output mentions none of the required: {any_of!r}"

    for needle in rubric.get("must_not_substring", []) or []:
        if needle in text:
            return f"output contains forbidden verbatim substring: {needle!r}"

    # AC-9: user-facing coaching copy is qualitative — no digits.
    if rubric.get("no_digits") and _DIGIT_RE.search(text):
        return "output contains digits (AC-9: the read is qualitative)"

    # Retired-construct fence — reuse the production regex so the eval
    # and the runtime guard can never drift apart.
    if rubric.get("must_not_match_construct"):
        from services.master_doc_rag import _CONSTRUCT_RE
        m = _CONSTRUCT_RE.search(text)
        if m:
            return f"output contains a retired-construct token: {m.group(0)!r}"

    if rubric.get("must_contain_polish_diacritic"):
        if not any(c in _POLISH_DIACRITICS for c in text_lower):
            return f"output has no Polish diacritics — likely not Polish: {text[:80]!r}"

    # Exact-value pins into structured output, e.g. {"device": "contrast"}.
    for dotted, want in (rubric.get("expect") or {}).items():
        got = _dig(output, dotted)
        if got != want:
            return f"expected {dotted}={want!r}, got {got!r}"

    for dotted, want in (rubric.get("expect_contains") or {}).items():
        got = _dig(output, dotted)
        if not isinstance(got, str) or str(want).lower() not in got.lower():
            return f"expected {dotted} to contain {want!r}, got {got!r}"

    # L1 / anti-hallucination: an output field must be a verbatim
    # substring of an input field (e.g. structural_star.quote ⊂ transcript).
    for spec in rubric.get("substring_of_input", []) or []:
        got = _dig(output, spec.get("path", ""))
        src = case.input.get(spec.get("input", ""), "")
        if not isinstance(got, str) or not isinstance(src, str) \
                or got.lower() not in src.lower():
            return (
                f"output.{spec.get('path')} is not a verbatim substring of "
                f"input.{spec.get('input')}: {str(got)[:60]!r}"
            )

    return None


# ─────────────────────────────────────────────────────────────────
# Semantic grader (SPEC_EVAL_GRADER, temp 0 — probe precedent)
# ─────────────────────────────────────────────────────────────────


def llm_grade(case: GoldenCase, output: Any) -> tuple[bool, str]:
    intent = case.rubric.get("semantic_intent")
    if not intent:
        return True, ""
    try:
        from services.llm import chat_complete
        from services.llm_config import SPEC_EVAL_GRADER
    except Exception as e:
        return False, f"grader: llm import failed: {e}"

    grader_prompt = (
        "You are an evaluator. Given the INPUT a coaching feature "
        "received and the OUTPUT it produced, judge whether the output "
        "satisfies the rubric to a reasonable bar.\n\n"
        f"Input: {json.dumps(case.input, ensure_ascii=False)[:4000]}\n"
        f"Output: {_flatten(output)[:4000]}\n"
        f"Rubric: {intent}\n\n"
        "Return STRICT JSON: "
        "{\"passed\": true|false, \"reason\": \"<one sentence>\"}.\n"
        "Pass outputs that meet the rubric in substance, even if the "
        "wording differs from your expectations. Fail only when the "
        "output clearly misses the rubric's stated intent or "
        "contradicts it. Do not invent rubric requirements that "
        "aren't stated."
    )
    result = chat_complete(
        spec=SPEC_EVAL_GRADER,
        system="You are a strict but fair evaluator. JSON only.",
        user=grader_prompt,
        surface="prompt_eval_grader",
    )
    parsed = getattr(result, "parsed", None) if result else None
    if not isinstance(parsed, dict):
        return False, "grader: call failed or returned malformed JSON"
    return bool(parsed.get("passed")), \
        (parsed.get("reason") or "").strip() or "(no reason given)"


# ─────────────────────────────────────────────────────────────────
# Runner + report
# ─────────────────────────────────────────────────────────────────


def run_surface(surface: str,
                adapter: Callable[[dict], Any]) -> list[Verdict]:
    verdicts: list[Verdict] = []
    for case in load_golden(surface):
        try:
            output = adapter(case.input)
        except Exception as e:
            verdicts.append(Verdict(
                case_id=case.id, surface=surface, passed=False,
                reason=f"adapter raised: {type(e).__name__}: {e}",
                description=case.description))
            continue
        det = deterministic_check(case, output)
        if det:
            verdicts.append(Verdict(
                case_id=case.id, surface=surface, passed=False,
                reason=det, description=case.description, output=output))
            continue
        if output is None and case.rubric.get("allow_none_output"):
            # A permitted None is a complete verdict — nothing to grade.
            verdicts.append(Verdict(
                case_id=case.id, surface=surface, passed=True,
                reason="ok (None permitted)", description=case.description))
            continue
        ok, reason = llm_grade(case, output)
        verdicts.append(Verdict(
            case_id=case.id, surface=surface, passed=ok,
            reason="ok" if ok else reason,
            description=case.description, output=output))
    return verdicts


_RULE = "═" * 67


def print_report(verdicts: list[Verdict], elapsed_sec: float) -> None:
    print(_RULE)
    print("prompt golden evals")
    print(_RULE)
    for v in verdicts:
        mark = "PASS" if v.passed else "FAIL"
        print(f"{mark}  {v.case_id}  [{v.surface}]  {v.description}")
        if not v.passed:
            print(f"       reason: {v.reason}")
            if v.output is not None:
                out = _flatten(v.output)
                print(f"       output: {out[:200]}{'…' if len(out) > 200 else ''}")
    passed_n = sum(1 for v in verdicts if v.passed)
    print(_RULE)
    print(f"RESULT  {passed_n} / {len(verdicts)} passed"
          f"   wall_time {elapsed_sec:.1f}s")
    print(_RULE)


def has_api_key() -> bool:
    return bool((os.environ.get("OPENAI_API_KEY") or "").strip())


def run(surfaces: list[str],
        adapters: dict[str, Callable[[dict], Any]]) -> int:
    """0 = all passed (or skipped-green), 1 = failures."""
    if not has_api_key():
        print("OPENAI_API_KEY not set — skipping prompt golden evals "
              "(the gate arms itself when the secret exists).")
        return 0
    t0 = time.perf_counter()
    all_verdicts: list[Verdict] = []
    for surface in surfaces:
        adapter = adapters.get(surface)
        if adapter is None:
            print(f"note: no adapter for surface {surface!r} — skipped "
                  "(add one in tests/evals/surfaces.py)")
            continue
        if not (GOLDEN_DIR / f"{surface}.jsonl").exists():
            print(f"note: no golden dataset for surface {surface!r} — "
                  "skipped (add tests/evals/golden/{surface}.jsonl)")
            continue
        all_verdicts.extend(run_surface(surface, adapter))
    print_report(all_verdicts, time.perf_counter() - t0)
    return 1 if any(not v.passed for v in all_verdicts) else 0
