"""
STORY    As a pilot participant, I can report how a recording actually felt
         without seeing the research prediction first.
OUTCOME
  O1  Ask energy first, then valence, in either language. Keep support and
      reappraisal tied to the speaker's report and communication goal.
  O2  Compare vocal evidence to suitable prior neutral recordings, withhold
      the prompt and ratings, and keep held-out sessions and speakers separate.
PROVES   O1 -> test_private_reports_come_one_at_a_time_even_at_low_activation
         O2 -> test_blind_voice_and_multimodal_arms_receive_only_the_exact_span_and_prior_context
"""
from dataclasses import replace

import pytest

from services import experiment_baseline_study as study


_FEATURES = dict(zip((name for name, _ in study.FEATURE_FLOORS), (24.0, 2.1, -24.0, 2.7, 0.12)))
_NEUTRAL = study.Report("low", "neutral")


def reading(order, *, speaker="volunteer-a", session="visit-a", language="pl", setup="mic-a", features=None):
    span = study.Span(speaker, session, order, f"clip-{order}", 1000, 8500, f"sha-{order}", language, setup)
    return study.AcousticReading(span, "features-v1", _FEATURES if features is None else features)


@pytest.mark.parametrize("language", ["pl", "en"])
def test_private_reports_come_one_at_a_time_even_at_low_activation(language):
    questions = study.QUESTIONS[language]
    assert study.next_question(study.Report(), language) == questions["energy"]
    assert study.next_question(study.Report("low"), language) == questions["valence"]
    for label in ("neutral", "mixed", "unsure"):
        assert study.next_question(study.Report("low", label), language) is None
    assert study.next_question(_NEUTRAL, language, measure_goal_ease=True) == questions["goal_ease"]
    assert study.next_question(_NEUTRAL, language, needs_help_decision=True) == questions["goal_effect"]
    assert study.next_question(_NEUTRAL, language, intervention_tried=True) == questions["goal_ease"]
    assert study.next_question(replace(_NEUTRAL, goal_ease="easy"), language, intervention_tried=True) == questions["intervention_effect"]
    prompts = study.PROMPTS[language]
    assert study.next_neutral_prompt(language, attempted=0, usable=0) == prompts["routine"]
    assert study.next_neutral_prompt(language, attempted=1, usable=1) == prompts["familiar_place"]
    assert study.next_neutral_prompt(language, attempted=2, usable=1) == prompts["ordinary_object"]
    assert study.next_neutral_prompt(language, attempted=2, usable=2) is None
    assert study.next_neutral_prompt(language, attempted=3, usable=1) is None


def test_opportunity_and_stakes_prompts_do_not_decide_valence_or_the_intervention():
    assert study.PROMPTS["en"]["stakes"] != study.PROMPTS["en"]["opportunity"]
    helpful = study.Report("high", "pleasant", "helped")  # A response to the stakes prompt.
    assert study.coaching_option(helpful) == "support"
    assert study.coaching_option(replace(helpful, felt_valence="unpleasant")) == "support"
    assert study.coaching_option(study.Report("high", "mixed", "hindered", "I lost the transition")) is None
    assert study.coaching_option(study.Report("medium", "unpleasant", "hindered", "I lost the transition")) is None
    confirmed = study.Report("high", "unpleasant", "hindered")
    assert study.next_question(confirmed, "pl", needs_help_decision=True) == study.QUESTIONS["pl"]["obstacle"]
    assert study.coaching_option(confirmed) is None
    assert study.coaching_option(replace(confirmed, obstacle="I forgot I could use my example")) == "reappraise"


def test_personal_reference_requires_recorded_quiet_neutral_speech_in_matching_conditions():
    first, second, third = (reading(i) for i in (1, 2, 3))
    target = reading(12)
    candidates = [
        (first, _NEUTRAL), (second, _NEUTRAL), (third, _NEUTRAL),
        (reading(4, language="en"), _NEUTRAL), (reading(5, setup="mic-b"), _NEUTRAL),
        (reading(6, speaker="volunteer-b"), _NEUTRAL), (reading(7, features={}), _NEUTRAL),
        (reading(8), study.Report("low", "pleasant")),
        (reading(9), study.Report("medium_to_high", "neutral")),
        (target, _NEUTRAL), (reading(13), _NEUTRAL),
    ]
    assert study.neutral_reference(target, candidates) == (third, second, first)
    assert study.neutral_reference(target, candidates[2:]) == ()


def test_f0_ablation_and_multifeature_index_use_frozen_personal_floors_and_can_abstain():
    references = [(reading(i), _NEUTRAL) for i in (1, 2)]
    features = dict(_FEATURES, f0_median_st=24.75, loudness_db=-24 + 6, speech_rate_per_s=3.2)
    scores = study.vocal_scores(reading(3, features=features), references)
    assert scores == {"f0_only": pytest.approx(1), "multifeature": pytest.approx(0.8)}
    assert study.vocal_elevation(scores["f0_only"]) == "elevated"
    assert study.vocal_elevation(scores["multifeature"]) == "not_elevated"
    assert study.vocal_scores(reading(3, features={"f0_median_st": float("nan")}), references) == {
        "f0_only": None, "multifeature": None,
    }
    assert study.vocal_elevation(None) is None


def test_blind_voice_and_multimodal_arms_receive_only_the_exact_span_and_prior_context():
    fragment = b"owned exact audio span"
    transcript = 'He said, "I am terrified." I then made my recommendation.'
    context = study.KnownContext(goal="make a recommendation", audience="the committee")

    def audio_only(audio):
        assert audio == fragment
        return "unsure"

    def combined(audio, words, prior):
        assert (audio, words, prior) == (fragment, transcript, context)
        return "mixed"

    predictions = study.blinded_valence(fragment, transcript, context, voice_only=audio_only, multimodal=combined)
    assert predictions == {"voice_only": None, "audio_text_context": "mixed"}
    assert study.blinded_valence(b"", transcript, context, voice_only=audio_only, multimodal=combined) == {
        "voice_only": None, "audio_text_context": None,
    }


def test_held_out_sessions_and_speakers_keep_source_audio_out_of_both_partitions():
    first = reading(1).span
    later = reading(3, session="later").span
    other = reading(4, speaker="new-speaker").span
    study.validate_split([first], [later], hold_out_speakers=False)
    study.validate_split([first], [other], hold_out_speakers=True)
    for candidate, hold_out_speakers in ((reading(2).span, False), (later, True),
                                         (replace(later, capture_order=0), False),
                                         (replace(other, audio_sha256=first.audio_sha256), True)):
        with pytest.raises(ValueError):
            study.validate_split([first], [candidate], hold_out_speakers=hold_out_speakers)


def test_scoring_retains_abstentions_and_pairs_retry_by_exact_original_and_goal():
    measured = study.score_held_out([("pleasant", None), ("pleasant", "pleasant"), ("mixed", "neutral")], study.VALENCES)
    assert (measured["eligible"], measured["covered"], measured["correct"]) == (3, 2, 1)
    assert measured["by_label"]["pleasant"]["eligible"] == 2
    activation = study.score_activation([("low", "not_elevated"), ("high", None), ("medium_to_high", "elevated")])
    assert (activation["eligible"], activation["covered"], activation["correct"], activation["excluded_labels"]) == (2, 1, 1, 1)
    first = study.Attempt(reading(1).span, "explain-delay", study.Report("high", "unpleasant", goal_ease="hard"))
    retry_report = study.Report("high", "pleasant", goal_ease="easy", intervention_effect="helped")
    retry = study.Attempt(reading(2).span, "explain-delay", retry_report, first.span)
    assert study.compare_attempts(first, retry) == {
        "felt_energy": ("high", "high"), "felt_valence": ("unpleasant", "pleasant"), "goal_ease": ("hard", "easy"),
        "intervention_effect": "helped",
    }
    assert study.compare_attempts(first, replace(retry, goal_key="ask-for-approval")) is None
