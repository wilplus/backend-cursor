"""The experiments prompt set, and the rules that set reads out of it.

``services/experiments/prompts_v1.yaml`` is the first prompt set. The gate
order, which grid cell is compared with a baseline take and which with the
business case, and the self-rating choices all come from that file. Nothing
here names a feeling. ``valence`` and ``arousal`` are field names from the
file's ``order``, kept inside this API.
"""
from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

PROMPT_SET_PATH = Path(__file__).resolve().parent / "experiments" / "prompts_v1.yaml"
MODEL_SLOT = "placeholder-v1"
#: Placeholder-slot parameter. Not a cue, and not in the prompt set: the
#: set says the order the gate walks, and this says how sure a step must be
#: to pass. A later model can replace the number without renaming a cue.
CONFIDENCE_FLOOR = 0.55
#: Config token suffix -> the two channels of a grid cell.
_CHANNEL_OF = {"words": "verbal", "voice": "vocal"}
CHANNELS = ("verbal", "vocal")
_TOP = {
    "version", "language", "order", "baseline_scored", "reference_scored",
    "prompts", "self_report",
}
_PROMPT_KEYS = {"id", "tag", "text", "reference"}
_WORD = re.compile(r"\w+", re.UNICODE)


class PromptSetError(Exception):
    """The prompt set file does not match its schema."""


def _strings(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value:
        raise PromptSetError(f"{label} must be a non-empty list")
    out: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip() or item != item.strip():
            raise PromptSetError(f"{label} must be bare strings")
        if item in out:
            raise PromptSetError(f"{label} repeats {item!r}")
        out.append(item)
    return out


def _targets(token: str, order: list[str]) -> list[tuple[str, str]]:
    """The cells one scored token names: a whole dimension, or one channel."""
    if token in order:
        return [(token, channel) for channel in CHANNELS]
    for suffix, channel in _CHANNEL_OF.items():
        marker = "_" + suffix
        if token.endswith(marker):
            dimension = token[: -len(marker)]
            if dimension in order and dimension:
                return [(dimension, channel)]
    raise PromptSetError(f"{token!r} is not a dimension in order")


def cell_references(prompt_set: dict[str, Any]) -> dict[tuple[str, str], str]:
    """``(dimension, channel) -> 'baseline' | 'reference'``, from the file."""
    order = list(prompt_set["order"])
    found: dict[tuple[str, str], str] = {}
    groups = (
        ("baseline_scored", "baseline"),
        ("reference_scored", "reference"),
    )
    for key, label in groups:
        for token in prompt_set[key]:
            for cell in _targets(str(token), order):
                if cell in found:
                    raise PromptSetError(f"{cell} is scored twice")
                found[cell] = label
    missing = [
        (dimension, channel)
        for dimension in order
        for channel in CHANNELS
        if (dimension, channel) not in found
    ]
    if missing:
        raise PromptSetError(f"unscored cells: {missing}")
    return found


def _prompts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        raise PromptSetError("prompts must be a non-empty list")
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise PromptSetError("a prompt must be a mapping")
        extra = set(item) - _PROMPT_KEYS
        if extra or not {"id", "tag", "text"} <= set(item):
            raise PromptSetError("a prompt has id, tag, text, and optional reference")
        prompt_id = item["id"]
        tag = item["tag"]
        text = item["text"]
        if not isinstance(prompt_id, str) or not prompt_id.strip() or prompt_id in seen:
            raise PromptSetError("prompt ids must be unique strings")
        if not isinstance(tag, str) or not tag.strip():
            raise PromptSetError("a prompt tag must be a string")
        if not isinstance(text, str) or not text.strip():
            raise PromptSetError("a prompt's text must be a string")
        row: dict[str, Any] = {"id": prompt_id, "tag": tag, "text": text}
        if "reference" in item:
            if item["reference"] != "business_case":
                raise PromptSetError("a prompt reference must be business_case")
            row["reference"] = "business_case"
        seen.add(prompt_id)
        out.append(row)
    return out


def _report(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict) or not value:
        raise PromptSetError("self_report must be a mapping")
    out: dict[str, list[str]] = {}
    for key, choices in value.items():
        if not isinstance(key, str) or not key.strip():
            raise PromptSetError("self_report keys must be strings")
        out[key] = _strings(choices, f"self_report.{key}")
    return out


def validate_prompt_set(data: Any) -> dict[str, Any]:
    """The schema of prompts_v1.yaml. Extra keys are refused."""
    if not isinstance(data, dict) or set(data) != _TOP:
        raise PromptSetError("the prompt set keys do not match the schema")
    version = data["version"]
    language = data["language"]
    if isinstance(version, bool) or not isinstance(version, int):
        raise PromptSetError("version must be an integer")
    if not isinstance(language, str) or not language.strip():
        raise PromptSetError("language must be a string")
    order = _strings(data["order"], "order")
    baseline = _strings(data["baseline_scored"], "baseline_scored")
    reference = _strings(data["reference_scored"], "reference_scored")
    prompts = _prompts(data["prompts"])
    report = _report(data["self_report"])
    prompt_set = {
        "version": version,
        "language": language,
        "order": order,
        "baseline_scored": baseline,
        "reference_scored": reference,
        "prompts": prompts,
        "self_report": report,
    }
    cell_references(prompt_set)
    return prompt_set


@lru_cache(maxsize=1)
def _cached(path: str) -> dict[str, Any]:
    file = Path(path)
    try:
        raw = file.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptSetError(f"prompt set cannot be read: {file.name}") from exc
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover - pinned in requirements.txt
        raise PromptSetError("PyYAML is required to read the prompt set") from exc
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise PromptSetError("prompt set is not valid YAML") from exc
    return validate_prompt_set(data)


def load_prompt_set(path: Path | None = None) -> dict[str, Any]:
    """The prompt set. The shipped file is cached; a passed path is not."""
    if path is None:
        return _cached(str(PROMPT_SET_PATH))
    return _read(Path(path))


def _read(file: Path) -> dict[str, Any]:
    try:
        raw = file.read_text(encoding="utf-8")
    except OSError as exc:
        raise PromptSetError(f"prompt set cannot be read: {file.name}") from exc
    try:
        import yaml
    except ImportError as exc:  # pragma: no cover
        raise PromptSetError("PyYAML is required to read the prompt set") from exc
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise PromptSetError("prompt set is not valid YAML") from exc
    return validate_prompt_set(data)


def prompt_tags(prompt_set: dict[str, Any]) -> set[str]:
    return {str(prompt["tag"]) for prompt in prompt_set["prompts"]}


def baseline_tags(prompt_set: dict[str, Any]) -> set[str]:
    """Prompt tags that mark a baseline take. The shipped tag is baseline_calm."""
    return {tag for tag in prompt_tags(prompt_set) if tag.startswith("baseline")}


def canonical_prompt(prompt_set: dict[str, Any], prompt_id: str) -> dict[str, Any] | None:
    for prompt in prompt_set["prompts"]:
        if prompt["id"] == prompt_id:
            return prompt
    return None


def check_self_rating(rating: Any, prompt_set: dict[str, Any]) -> dict[str, str]:
    """The rating, or an error. The keys and choices are ``self_report``."""
    report = prompt_set["self_report"]
    if not isinstance(rating, dict) or set(rating) != set(report):
        raise PromptSetError("self_rating does not match self_report")
    cleaned: dict[str, str] = {}
    for key, choices in report.items():
        value = rating[key]
        if not isinstance(value, str) or value not in choices:
            raise PromptSetError("self_rating does not match self_report")
        cleaned[key] = value
    return cleaned


def gate_for(summary: dict[str, Any], order: list[str], floor: float) -> str | None:
    """The first step in ``order`` whose confidence is below ``floor``."""
    for step in order:
        cell = summary.get(step) or {}
        confidence = cell.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            return step
        if float(confidence) < floor:
            return step
    return None


def _sign(value: float) -> int:
    if abs(value) < 1e-9:
        return 0
    return 1 if value > 0 else -1


def score_overlap(pattern: dict[str, Any], moment_grid: dict[str, Any]) -> float:
    """Match plus match intensity, averaged over the pattern's cells.

    A cell matches when the pattern and the moment have the same sign
    (zero only matches zero). Intensity is how close the two values are,
    from 1 (the same) to 0 (as far as -1 and +1). A miss scores 0. The
    average is in ``[0, 2]``.
    """
    scores: list[float] = []
    if not isinstance(pattern, dict) or not isinstance(moment_grid, dict):
        return 0.0
    for dimension, cells in pattern.items():
        if not isinstance(cells, dict):
            continue
        moment = moment_grid.get(dimension)
        moment = moment if isinstance(moment, dict) else {}
        for channel, expected in cells.items():
            if isinstance(expected, bool) or not isinstance(expected, (int, float)):
                continue
            actual = moment.get(channel)
            if not isinstance(actual, dict):
                scores.append(0.0)
                continue
            got = actual.get("value")
            if isinstance(got, bool) or not isinstance(got, (int, float)):
                scores.append(0.0)
                continue
            match = 1.0 if _sign(float(expected)) == _sign(float(got)) else 0.0
            intensity = (1.0 - min(1.0, abs(float(expected) - float(got)) / 2.0)) if match else 0.0
            scores.append(match + intensity)
    if not scores:
        return 0.0
    return round(sum(scores) / len(scores), 4)


def step_of(rule: Any, pattern: dict[str, Any], order: list[str]) -> str | None:
    """The intervention's step: ``rule.step`` when it is in ``order``, else
    the pattern's strongest dimension, ties broken by ``order``."""
    if isinstance(rule, dict):
        named = rule.get("step")
        if isinstance(named, str):
            return named if named in order else None
    best: str | None = None
    best_key: tuple[float, int] | None = None
    for index, dimension in enumerate(order):
        cells = pattern.get(dimension)
        if not isinstance(cells, dict):
            continue
        strength = 0.0
        seen = False
        for channel in CHANNELS:
            value = cells.get(channel)
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            seen = True
            strength = max(strength, abs(float(value)))
        if not seen:
            continue
        key = (-strength, index)
        if best_key is None or key < best_key:
            best, best_key = dimension, key
    return best


def rank_interventions(
    interventions: list[dict[str, Any]], moment_grid: dict[str, Any], order: list[str],
) -> list[dict[str, Any]]:
    """Those at or above their threshold, at most two.

    The earlier step in ``order`` wins. Inside one step, the closer overlap
    wins.
    """
    fired: list[dict[str, Any]] = []
    for item in interventions:
        raw_grid = item.get("grid")
        pattern: dict[str, Any] = raw_grid if isinstance(raw_grid, dict) else {}
        step = step_of(item.get("rule"), pattern, order)
        if step is None:
            continue
        threshold = item.get("threshold")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            continue
        overlap = score_overlap(pattern, moment_grid)
        if overlap + 1e-9 < float(threshold):
            continue
        fired.append({
            "id": item.get("id"),
            "step": step,
            "overlap": overlap,
            "threshold": float(threshold),
            "rule": item.get("rule"),
            "grid": pattern,
        })
    fired.sort(key=lambda row: (order.index(str(row["step"])), -float(row["overlap"]), str(row["id"])))
    return fired[:2]


def placeholder_value(seed: str) -> float:
    """A stable stand-in in ``[-1, +1]``. The same seed always returns it."""
    number = int(hashlib.sha256(seed.encode("utf-8")).hexdigest()[:8], 16)
    return round((number / 0xFFFFFFFF) * 2 - 1, 4)


def vocal_cue(rms: float, baseline: float | None) -> float:
    """Map a loudness into ``[-1, +1]``. With a baseline, the distance from it.

    This is a stand-in acoustic comparison, not a reading of a feeling.
    ``0.05`` is a quiet-speech RMS used only so an uncompared measurement
    has a midpoint.
    """
    origin = 0.05 if baseline is None else baseline
    return round(max(-1.0, min(1.0, (float(rms) - origin) / 0.05)), 4)


def lexical_cue(transcript: str, case_text: str) -> float | None:
    """How much of the business-case wording the take used, in ``[-1, +1]``.

    ``None`` when there is no business-case text to compare with. Shared
    words over the case's words: none is -1, all of them is +1.
    """
    case = {word.lower() for word in _WORD.findall(case_text or "")}
    if not case:
        return None
    said = {word.lower() for word in _WORD.findall(transcript or "")}
    ratio = len(said & case) / len(case)
    return round(max(-1.0, min(1.0, ratio * 2 - 1)), 4)


def analyze_example(prompt_set: dict[str, Any] | None = None) -> dict[str, Any]:
    """One response in the shape ``POST /v2/experiments/analyze-take`` returns.

    The numbers are the placeholder slot. ``reference`` on each cell is
    taken from the prompt set, not written in by hand.
    """
    prompt_set = load_prompt_set() if prompt_set is None else prompt_set
    refs = cell_references(prompt_set)
    grid = {
        dimension: {
            channel: {"value": 0.0, "reference": refs[(dimension, channel)]}
            for channel in CHANNELS
        }
        for dimension in prompt_set["order"]
    }
    summary: dict[str, Any] = {
        dimension: {"score": 0.0, "confidence": 0.2}
        for dimension in prompt_set["order"]
    }
    summary["gate"] = gate_for(summary, list(prompt_set["order"]), CONFIDENCE_FLOOR)
    return {
        "take_id": "00000000-0000-4000-8000-000000000000",
        "model": MODEL_SLOT,
        "moments": [{"start": 0.0, "end": 1.0, "grid": grid}],
        "summary": summary,
    }
