"""Offline protocol for the later activation and felt-valence study (N697)."""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from math import isfinite
from statistics import mean, stdev
from typing import Literal

from services.experiment_baseline import ENERGIES, VALENCES

VERSION = "activation-valence-study-v1"
# Same-span inputs from a versioned extractor. Every direction is positive in this pilot hypothesis.
FEATURE_FLOORS = (
    ("f0_median_st", 0.75), ("f0_variability_st", 0.5), ("loudness_db", 3.0),
    ("speech_rate_per_s", 0.5), ("high_frequency_energy_ratio", 0.03),
)
ELEVATION_THRESHOLD = 1.0
MIN_COMBINED_FEATURES = 3
MIN_NEUTRAL_RECORDINGS = 2
MAX_NEUTRAL_RECORDINGS = 3

PROMPTS = {
    "pl": {
        "routine": "Opowiedz, co zwykle robisz po przebudzeniu, krok po kroku.",
        "familiar_place": "Opisz drogę od wejścia do miejsca, w którym zwykle siadasz.",
        "ordinary_object": "Wybierz przedmiot, którego często używasz. Opowiedz, gdzie go trzymasz i do czego służy.",
        "opportunity": "Przypomnij sobie sytuację, w której otworzyła się przed tobą ważna możliwość. Co się działo i jaki był twój następny krok?",
        "stakes": "Przypomnij sobie sytuację, w której coś dla ciebie ważnego było stawką. Co się działo i jaki był twój następny krok?",
    },
    "en": {
        "routine": "Talk me through what you usually do after waking up.",
        "familiar_place": "Describe the route from the entrance to where you usually sit in a familiar place.",
        "ordinary_object": "Pick an object you use often. Tell me where you keep it and what you use it for.",
        "opportunity": "Think of a time an important opportunity opened up for you. What was happening, and what did you do next?",
        "stakes": "Think of a time something important to you was at stake. What was happening, and what did you do next?",
    },
}
QUESTIONS = {
    "pl": {
        "energy": "Jak silne było twoje pobudzenie podczas tej wypowiedzi?",
        "valence": "Jak przyjemne lub nieprzyjemne było twoje odczucie podczas mówienia?",
        "goal_effect": "Czy to pobudzenie pomagało ci osiągnąć cel, przeszkadzało, czy było bez znaczenia?",
        "obstacle": "Co konkretnie utrudniło ci osiągnięcie celu w tym fragmencie?",
        "goal_ease": "Jak łatwo było ci osiągnąć ten sam cel w tej próbie?",
        "intervention_effect": "Czy ćwiczenie pomogło ci osiągnąć cel, przeszkodziło, czy nie zrobiło różnicy?",
    },
    "en": {
        "energy": "How activated did you feel while saying this?",
        "valence": "How pleasant or unpleasant did it feel while you were speaking?",
        "goal_effect": "Did that activation help you achieve your goal, get in the way, or make no difference?",
        "obstacle": "What specifically got in the way of your goal in this passage?",
        "goal_ease": "How easy was it to achieve the same goal on this attempt?",
        "intervention_effect": "Did the exercise help you reach your goal, get in the way, or make no difference?",
    },
}


def next_neutral_prompt(language: str, *, attempted: int, usable: int) -> str | None:
    """Collect two usable neutral recordings, with one replacement invitation."""
    order = ("routine", "familiar_place", "ordinary_object")
    if not 0 <= usable <= attempted <= len(order):
        raise ValueError("invalid neutral collection progress")
    if attempted == len(order) or usable >= MIN_NEUTRAL_RECORDINGS:
        return None
    return PROMPTS[language][order[attempted]]


@dataclass(frozen=True)
class Report:
    felt_energy: str | None = None
    felt_valence: str | None = None
    goal_effect: str | None = None
    obstacle: str = ""
    goal_ease: str | None = None
    intervention_effect: str | None = None


def next_question(report: Report, language: str, *, measure_goal_ease: bool = False,
                  needs_help_decision: bool = False, intervention_tried: bool = False) -> str | None:
    """Ask one neutral question at a time using only the speaker's self-report."""
    questions = QUESTIONS[language]
    if report.felt_energy not in ENERGIES:
        return questions["energy"]
    if report.felt_valence not in VALENCES:
        return questions["valence"]
    if needs_help_decision and report.goal_effect is None:
        return questions["goal_effect"]
    if needs_help_decision and _reappraisal_candidate(report) and not report.obstacle.strip():
        return questions["obstacle"]
    if (measure_goal_ease or intervention_tried) and report.goal_ease is None:
        return questions["goal_ease"]
    if intervention_tried and report.intervention_effect is None:
        return questions["intervention_effect"]
    return None


def _reappraisal_candidate(report: Report) -> bool:
    return report.felt_energy == "high" and report.felt_valence == "unpleasant" and report.goal_effect == "hindered"


def coaching_option(report: Report) -> Literal["support", "reappraise"] | None:
    if report.felt_energy == "high" and report.goal_effect == "helped":
        return "support"
    if _reappraisal_candidate(report) and report.obstacle.strip():
        return "reappraise"
    return None


@dataclass(frozen=True)
class Span:
    speaker: str
    session: str
    capture_order: int
    recording: str
    start_ms: int
    end_ms: int
    audio_sha256: str
    language: str
    setup: str

    def __post_init__(self) -> None:
        if not 0 <= self.start_ms < self.end_ms:
            raise ValueError("use the exact nonempty recording span")


@dataclass(frozen=True)
class AcousticReading:
    span: Span
    extractor_version: str
    features: Mapping[str, float]


def _same_recording(a: Span, b: Span) -> bool:
    return (a.speaker, a.recording) == (b.speaker, b.recording) or a.audio_sha256 == b.audio_sha256


def neutral_reference(target: AcousticReading, candidates: Sequence[tuple[AcousticReading, Report]]) -> tuple[AcousticReading, ...]:
    reference: list[AcousticReading] = []
    span = target.span
    for sample, report in sorted(candidates, key=lambda pair: pair[0].span.capture_order, reverse=True):
        sample_span = sample.span
        if (report.felt_energy != "low" or report.felt_valence != "neutral"
                or sample.extractor_version != target.extractor_version
                or (sample_span.speaker, sample_span.language, sample_span.setup) != (span.speaker, span.language, span.setup)
                or sample_span.capture_order >= span.capture_order or _same_recording(sample_span, span)
                or not _usable_reference(sample)
                or any(_same_recording(sample_span, old.span) for old in reference)):
            continue
        reference.append(sample)
        if len(reference) == MAX_NEUTRAL_RECORDINGS:
            break
    return tuple(reference) if len(reference) >= MIN_NEUTRAL_RECORDINGS else ()


def _feature(reading: AcousticReading, name: str) -> float | None:
    value = reading.features.get(name)
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not isfinite(value):
        return None
    return float(value)


def _usable_reference(sample: AcousticReading) -> bool:
    return sum(_feature(sample, name) is not None for name, _ in FEATURE_FLOORS) >= MIN_COMBINED_FEATURES


def vocal_scores(target: AcousticReading, candidates: Sequence[tuple[AcousticReading, Report]]) -> dict[str, float | None]:
    """Compare the F0-only arm and the mean of reliable personal z-scores."""
    reference = neutral_reference(target, candidates)
    scores = {}
    for name, floor in FEATURE_FLOORS:
        value = _feature(target, name)
        values = [v for sample in reference if (v := _feature(sample, name)) is not None]
        if value is not None and len(values) >= MIN_NEUTRAL_RECORDINGS:
            scores[name] = (value - mean(values)) / max(floor, stdev(values))
    return {
        "f0_only": scores.get("f0_median_st"),
        "multifeature": mean(scores.values()) if len(scores) >= MIN_COMBINED_FEATURES else None,
    }


def vocal_elevation(score: float | None) -> str | None:
    if score is None:
        return None
    return "elevated" if score >= ELEVATION_THRESHOLD else "not_elevated"


@dataclass(frozen=True)
class KnownContext:
    """Context saved before the question is shown. No elicitation metadata or reports."""

    goal: str = ""
    audience: str = ""


def blinded_valence(audio: bytes, exact_transcript: str, context: KnownContext, *,
                    voice_only: Callable[[bytes], str | None],
                    multimodal: Callable[[bytes, str, KnownContext], str | None]) -> dict[str, str | None]:
    """Run the two predeclared arms with no access to the prompt or felt report."""
    if not audio:
        return {"voice_only": None, "audio_text_context": None}
    predictions = {
        "voice_only": voice_only(audio),
        "audio_text_context": multimodal(audio, exact_transcript, context) if exact_transcript.strip() else None,
    }
    if any(value is not None and value not in VALENCES for value in predictions.values()):
        raise ValueError("unknown valence class")
    return {arm: None if prediction == "unsure" else prediction for arm, prediction in predictions.items()}


def validate_split(tuning: Sequence[Span], test: Sequence[Span], *, hold_out_speakers: bool) -> None:
    """Hold out complete speakers or later sessions and reject reused source audio."""
    if not tuning or not test:
        raise ValueError("both study partitions are required")
    tuned_speakers = {span.speaker for span in tuning}
    test_speakers = {span.speaker for span in test}
    if hold_out_speakers and tuned_speakers & test_speakers:
        raise ValueError("speaker appears in both partitions")
    if not hold_out_speakers and tuned_speakers != test_speakers:
        raise ValueError("both partitions must cover the same speakers")
    tuned_sessions = {(span.speaker, span.session) for span in tuning}
    if any((span.speaker, span.session) in tuned_sessions for span in test):
        raise ValueError("session appears in both partitions")
    if any(_same_recording(a, b) for a in tuning for b in test):
        raise ValueError("audio appears in both partitions")
    if not hold_out_speakers:
        for speaker in tuned_speakers:
            last_tuned = max(row.capture_order for row in tuning if row.speaker == speaker)
            first_test = min(row.capture_order for row in test if row.speaker == speaker)
            if first_test <= last_tuned:
                raise ValueError("test must use a later session")


def score_held_out(rows: Sequence[tuple[str | None, str | None]],
                   labels: Sequence[str]) -> dict:
    """Score independently recorded labels, keeping abstentions and label coverage visible."""
    eligible = [(felt, predicted) for felt, predicted in rows if felt in labels]
    pairs = Counter((felt, predicted) for felt, predicted in eligible if predicted in labels)
    covered = sum(pairs.values())
    return {
        "excluded_labels": len(rows) - len(eligible),
        "eligible": len(eligible),
        "covered": covered,
        "correct": sum(n for (felt, predicted), n in pairs.items() if felt == predicted),
        "by_label": {label: {
            "eligible": sum(felt == label for felt, _ in eligible),
            "predicted": {prediction: pairs[(label, prediction)] for prediction in labels},
        } for label in labels},
    }


def score_activation(rows: Sequence[tuple[str | None, str | None]]) -> dict:
    """Compare the low/high contrast without recoding intermediate self-reports."""
    contrast = {"low": "not_elevated", "high": "elevated"}
    return score_held_out([(contrast.get(felt) if felt else None, predicted) for felt, predicted in rows],
                          tuple(contrast.values()))


@dataclass(frozen=True)
class Attempt:
    span: Span
    goal_key: str
    report: Report
    retry_of: Span | None = None


def compare_attempts(original: Attempt, retry: Attempt) -> dict | None:
    """Pair the original and a distinct retry on the same communication goal."""
    if (retry.retry_of != original.span or not original.goal_key or retry.goal_key != original.goal_key
            or retry.span.speaker != original.span.speaker or retry.span.capture_order <= original.span.capture_order
            or _same_recording(retry.span, original.span)):
        return None
    return {
        "felt_energy": (original.report.felt_energy, retry.report.felt_energy),
        "felt_valence": (original.report.felt_valence, retry.report.felt_valence),
        "goal_ease": (original.report.goal_ease, retry.report.goal_ease),
        "intervention_effect": retry.report.intervention_effect,
    }
