"""
GUARD    What the speaking coach notices moved from code into one settings
         record, unchanged (N647 item 8, step 3): today's thresholds are its
         defaults, and a missing, broken or out-of-bounds record changes
         nothing a speaker sees.
CATCHES
  C1  a default drifting from the constant it replaced, so the move itself
      changes what is noticed
  C2  a missing, unreadable or out-of-bounds record changing a verdict, or a
      moved threshold logging its verdicts under today's version
  C3  a candidate (a silent try, step 4) leaking out of its own block into
      what the live rules read, or a step moving a ranking or pinned value,
      or leaving its bounds
IF REMOVED  moving a threshold could change the walk with no log to tell.
PROVES   C1 -> test_the_defaults_are_todays_constants
         C2 -> test_a_bad_record_keeps_todays_values_and_a_moved_one_is_versioned
         C3 -> test_a_candidate_is_read_only_inside_its_block
               test_a_step_moves_only_a_things_dials_one_notch
"""
import json

import pytest

from services import (moment_pick, noticing_settings, rewrite_gate, take_context,
                      take_feedback_policy_v3, tempo_stretch, v4_picker, v4_reached_bar,
                      verbal_cues, willfidence)

FILLERS = "um we um built it uh in six weeks with the data we had"


@pytest.fixture(autouse=True)
def _no_record():
    noticing_settings.use_reader(lambda: None)
    yield
    noticing_settings.use_reader(lambda: None)


def test_the_defaults_are_todays_constants():
    modules = {m.__name__.split(".")[-1]: m for m in (
        tempo_stretch, verbal_cues, moment_pick, take_context, take_feedback_policy_v3,
        rewrite_gate, v4_picker, v4_reached_bar, willfidence)}
    assert len(noticing_settings.DEFAULTS) == 25
    for name, default in noticing_settings.DEFAULTS.items():
        module, constant = name.split(".")
        assert getattr(modules[module], constant) == default, name
        assert noticing_settings.value(name) == default, name
    assert noticing_settings.version() == noticing_settings.DEFAULT_VERSION


def test_a_bad_record_keeps_todays_values_and_a_moved_one_is_versioned():
    for raw in (None, "", "not json", "[]", json.dumps({"values": "x"}),
                json.dumps({"values": {"verbal_cues.FILLER_MIN_COUNT": 99,
                                       "moment_pick.FLOOR": "high",
                                       "take_feedback_policy_v3.PRACTICE_BANDS": ["x"]}}),
                json.dumps({"values": noticing_settings.DEFAULTS})):
        noticing_settings.use_reader(lambda raw=raw: raw)
        assert noticing_settings.live() == noticing_settings.DEFAULTS, raw
        assert verbal_cues.detector_version() == verbal_cues.VERBAL_CUES_VERSION
    noticing_settings.use_reader(lambda: (_ for _ in ()).throw(RuntimeError("down")))
    assert noticing_settings.live() == noticing_settings.DEFAULTS

    noticing_settings.use_reader(lambda: json.dumps(
        {"version": "x", "values": {"verbal_cues.FILLER_MIN_COUNT": 4}}))
    assert noticing_settings.value("verbal_cues.FILLER_MIN_COUNT") == 4
    assert noticing_settings.version() != noticing_settings.DEFAULT_VERSION
    rows = verbal_cues.take_observations(
        [{"id": "s1", "recording_id": "r1", "transcript": FILLERS}], take_session_id="t", language_of=lambda _: "en")
    assert {r["detector_version"] for r in rows} == {
        f"{verbal_cues.VERBAL_CUES_VERSION}+{noticing_settings.version()}"}
    assert not next(r for r in rows if r["error_id"] == "filler_cluster")["fired"]


def test_a_candidate_is_read_only_inside_its_block():
    live = verbal_cues.measure(FILLERS, "en")["filler_cluster"]["fired"]
    for typo in ({"verbal_cues.FILLER_MIN_CONT": 4}, {"take_context.MATCH": 5.0},
                 {"tempo_stretch.GREEN_LOW": 0.1}):
        with pytest.raises(ValueError):
            noticing_settings.candidate(typo)
    # A candidate keeps every other value that is live.
    noticing_settings.use_reader(lambda: json.dumps(
        {"values": {"moment_pick.FLOOR": 0.65}}))
    tried = noticing_settings.candidate({"verbal_cues.FILLER_MIN_COUNT": 4})
    assert tried["moment_pick.FLOOR"] == 0.65
    with noticing_settings.trying(tried):
        assert verbal_cues.measure(FILLERS, "en")["filler_cluster"]["fired"] is not live
        assert verbal_cues.detector_version() != verbal_cues.VERBAL_CUES_VERSION
    assert verbal_cues.measure(FILLERS, "en")["filler_cluster"]["fired"] is live
    assert noticing_settings.value("verbal_cues.FILLER_MIN_COUNT") == 2
    assert noticing_settings.value("moment_pick.FLOOR") == 0.65


def test_a_step_moves_only_a_things_dials_one_notch():
    live = noticing_settings.defaults()
    assert noticing_settings.setting_for("Filler words") == {
        "verbal_cues.FILLER_MIN_COUNT": 2, "verbal_cues.FILLER_MIN_PER_100_WORDS": 5.0}
    more = noticing_settings.step(live, "Filler words", noticing_settings.MORE)
    assert more["verbal_cues.FILLER_MIN_COUNT"] == 1
    assert more["verbal_cues.FILLER_MIN_PER_100_WORDS"] == 4.0
    assert {n for n in more if more[n] != live[n]} <= set(noticing_settings.THINGS["Filler words"])
    assert noticing_settings.step(more, "Filler words", noticing_settings.FEWER) == live
    edge = live
    for _ in range(10):
        edge = noticing_settings.step(edge, "Filler words", noticing_settings.MORE)
    assert edge["verbal_cues.FILLER_MIN_COUNT"] == 1
    every_dial = {n for names in noticing_settings.THINGS.values() for n in names}
    assert every_dial == noticing_settings.DIALABLE
    with pytest.raises(ValueError):
        noticing_settings.candidate({"moment_pick.MIN_WORDS": 9})
