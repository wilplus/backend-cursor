"""
STORY    As a person in WillpowerLab, I want to find AI models, see how far
         each is, teach the ones in my field from one queue, and, as a
         model's founder, release a version only when it is clearly better
         (N528, N563, N566; the locked prototype "The Model Launchpad").
OUTCOME
  O1  The list puts my draft on top, then the most mature models, with
      search, the three filters, and an empty state that offers to start one.
  O2  A public model's page is in totals only; a private one is unseen by
      outsiders; nobody's page reads on a person.
  O3  Teaching follows the model's recipe card (rate, pick, answer in words),
      and nothing of the machine's read reaches the teacher.
  O4  A newcomer's answers count only once the quiet trust check admits
      them, and only then are they told, once.
  O5  One queue across my models, what helps most first, none starved, with
      Pause; an empty queue says so.
  O6  An answer counts for two models only on the same question and scale; a
      private example only for its own model; added examples count once a
      second teacher agrees and stay under 1 in 5.
  O7  Release appears only when the new version is clearly not better by
      luck.
  O8  A speaker's Takes reach teachers only while their training yes is on.
PROVES   O1 -> test_mod05_the_list_puts_the_draft_on_top_then_the_most_mature
         O2 -> test_mod03_a_public_page_holds_totals_only_and_a_private_one_is_unseen
         O3 -> test_mod09_nothing_of_the_machine_reaches_the_teacher
         O4 -> test_mod10_a_newcomer_counts_only_after_20_answers_that_hear_what_experts_hear
         O5 -> test_mod15_one_queue_across_models_helpful_first_and_none_starved
         O6 -> test_mod16_same_question_same_scale_counts_for_both
         O7 -> test_mod22_a_close_result_has_no_release_button
         O8 -> test_mod02_only_takes_after_the_training_yes_reach_teachers
WHY      The model launchpad, locked on its prototype (N566); its rules live
         once in services/model_launchpad.py, before its tables.
"""
from __future__ import annotations

from services import model_launchpad as ml

ARTUR, MARTA, KASIA, TOMEK = "u-artur", "u-marta", "u-kasia", "u-tomek"


def _model(id_, name, *, owner=ARTUR, owner_name="Artur", visibility="public", status="learning",
           answers=0, exam=0, teachers=0, contributors=(), question="Does the speaker sound confident here?",
           scale=("Yes", "In-between", "No"), input_="voice", steps=("rate",), options=(), field="",
           draft_step=None):
    return {
        "id": id_, "name": name, "owner_id": owner, "owner_name": owner_name,
        "visibility": visibility, "status": status, "field": field, "description": "",
        "draft_step": draft_step,
        "recipe": {"input": input_, "steps": list(steps), "question": question, "scale": list(scale),
                   "pick_question": "Which first reply would you send?", "options": list(options)},
        "jars": {"counted_answers": answers, "exam_cases": exam},
        "teachers": teachers, "contributor_ids": list(contributors),
    }


SPEAKING = _model("m-speak", "Speaking confidence", answers=310, exam=70, teachers=6,
                  contributors=(MARTA,), field="speaking voice")
INTERVIEW = _model("m-int", "Interview voice", owner=TOMEK, owner_name="Tomek", answers=50, exam=10, teachers=2)
PITCH = _model("m-pitch", "Pitch Coach", owner=MARTA, owner_name="Marta", visibility="private",
               answers=180, exam=60, teachers=3, question="How rushed does it sound?",
               scale=("Calm", "Mostly calm", "Hurried in places", "Rushed", "Racing"))
RASP = _model("m-rasp", "RASP sales replies", owner=TOMEK, owner_name="Tomek", visibility="private",
              contributors=(MARTA,), input_="text", steps=("pick", "words"),
              options=("Ask what they compared us with", "Offer a smaller first order",
                       "Show what the price saves them"))
READY = _model("m-job", "Job interview coach", owner="u-dan", owner_name="Daniel Okafor",
               status="ready", teachers=9)


# MOD-01 · nothing of the models while joining: the acceptance offers no
# optional purpose. The backend half: the launchpad never touches consent.
def test_mod01_the_launchpad_asks_nothing_at_joining():
    assert not any("consent" in k for k in ml.WORDS)


# MOD-02 · the training yes decides whether her Takes can teach
def test_mod02_only_takes_after_the_training_yes_reach_teachers():
    takes = [{"id": "t1", "recorded_at": "2026-11-01T10:00:00Z"},
             {"id": "t2", "recorded_at": "2026-11-05T10:00:00Z"}]
    assert ml.takes_offered_to_teachers(takes, {"active": False, "granted_at": None}) == []
    on = {"active": True, "granted_at": "2026-11-03T00:00:00Z"}
    assert [t["id"] for t in ml.takes_offered_to_teachers(takes, on)] == ["t2"]
    # "Turn off training?" takes them out again
    assert ml.takes_offered_to_teachers(takes, {"active": False, "granted_at": on["granted_at"]}) == []


def test_mod02_the_yes_is_read_from_the_consent_status_and_a_failed_read_offers_nothing():
    class Db:
        def __init__(self, status): self.status = status
        def get_mlc2_training_consent_status(self, _owner):
            if isinstance(self.status, Exception):
                raise self.status
            return self.status
    assert ml.take_consent(Db({"active": True, "granted_at": "x"}), KASIA) == {"active": True, "granted_at": "x"}
    assert ml.take_consent(Db(RuntimeError("down")), KASIA)["active"] is False


# MOD-03 · a speaker never sees a model's page or its numbers about her
def test_mod03_a_public_page_holds_totals_only_and_a_private_one_is_unseen():
    page = ml.model_page(SPEAKING, KASIA)
    assert page["role"] == "public"
    assert not {"jars", "recipe", "own_part", "owner", "contributor_ids", "reliability"} & set(page)
    assert ml.model_page(PITCH, KASIA) is None
    assert ml.model_page(SPEAKING, MARTA)["role"] == "contributor"
    assert "owner" not in ml.model_page(SPEAKING, MARTA)
    assert "owner" in ml.model_page(SPEAKING, ARTUR)


# MOD-04 · the AI models row sits under the people
def test_mod04_the_two_rows_under_the_people():
    rows = ml.chat_rows(12, 3, teaches_any=True)
    assert rows == [{"name": "Your queue", "line": "12 examples wait · 3 models"},
                    {"name": "AI models", "line": "Teach one, or start your own"}]
    assert ml.chat_rows(0, 0, teaches_any=False) == [{"name": "AI models", "line": "Teach one, or start your own"}]


# MOD-05 · the list, the most mature first, with search and filters
def test_mod05_the_list_puts_the_draft_on_top_then_the_most_mature():
    draft = _model("m-d", "Pitch Coach", owner=MARTA, status="draft", draft_step="scale")
    out = ml.model_list([INTERVIEW, SPEAKING, READY, PITCH, draft], MARTA)
    assert out["intro"] == ("Each model learns one skill from people who know it well. "
                            "The ones furthest along are at the top.")
    assert out["filters"] == ["For you", "Ready to use", "Still learning"]
    assert out["drafts"] == [{"id": "m-d", "name": "Pitch Coach", "badge": "Your draft",
                              "line": "You stopped at the scale. Nothing is lost.", "actions": ["Continue"]}]
    names = [r["name"] for r in out["models"]]
    assert names[0] == "Job interview coach"
    assert names.index("Speaking confidence") < names.index("Interview voice")
    speak = next(r for r in out["models"] if r["name"] == "Speaking confidence")
    assert speak["started_by"] == "Started by Artur"
    assert speak["line"] == "62% of the way to its first training · 6 teachers"
    assert ml.progress_line(READY) == "Passed its final exam · 9 teachers"


def test_mod05_filters_and_search_and_private_models_stay_out_of_the_directory():
    names = lambda out: [r["name"] for r in out["models"]]  # noqa: E731
    assert names(ml.model_list([SPEAKING, READY], KASIA, filter_="ready")) == ["Job interview coach"]
    assert names(ml.model_list([SPEAKING, READY], KASIA, filter_="learning")) == ["Speaking confidence"]
    assert names(ml.model_list([SPEAKING, READY, PITCH], KASIA, query="speaking")) == ["Speaking confidence"]
    assert "Pitch Coach" not in names(ml.model_list([PITCH], KASIA))
    assert names(ml.model_list([SPEAKING, INTERVIEW], KASIA, filter_="for_you", viewer_fields=["Speaking coach"])) \
        == ["Speaking confidence"]


# MOD-06 · a public model's page in totals only
def test_mod06_the_public_page_in_words():
    page = ml.model_page(SPEAKING, KASIA)
    assert page["summary"] == "Speaking confidence is 62% of the way to its first training. Six people teach it."
    assert page["actions"] == ["Teach it", "Try it"]


# MOD-07 · a disclaimer at the door
def test_mod07_the_door():
    assert ml.door() == {
        "title": "Before you teach",
        "lines": ["Everyone who uses this model relies on what it learns from you.",
                  "Teach it only what you know well. If this is not your field, your answers would make it "
                  "worse for all of us.",
                  "It learns from your ratings and the words of your answers. Your voice recordings stay "
                  "with WillpowerLab."],
        "actions": ["This is my field", "Not now"],
    }


# MOD-08 · teaching a voice model looks like the coach panel's Judge
def test_mod08_a_voice_model_asks_on_the_judge():
    screen = ml.teaching_screen(SPEAKING, {"id": "e1", "model_id": "m-speak"})
    assert screen["title"] == "Judge this moment"
    assert screen["question"] == "Does the speaker sound confident here?"
    assert screen["answers"] == ["Yes", "In-between", "No", "Audio unclear", "Skip"]


# MOD-09 · a teacher never sees the machine's guess before answering
def test_mod09_nothing_of_the_machine_reaches_the_teacher():
    example = {"id": "e1", "model_id": "m-speak", "machine_label": "yes", "machine_score": 0.8,
               "draft": "Sounded sure", "what_happened": "steady pitch", "sureness": 0.4,
               "machine": {"label": "yes"}, "known_answer": "Yes", "in_exam": False,
               "speaker_id": "u-kasia"}
    screen = ml.teaching_screen(SPEAKING, example)
    assert screen["example"] == {"id": "e1", "model_id": "m-speak"}
    queue = ml.build_queue([SPEAKING], [example], MARTA)
    assert queue["examples"] == [{"id": "e1", "model_id": "m-speak"}]


# MOD-10 · the quiet trust check
def _answers(n, agree_every, known=5):
    out = []
    for i in range(n):
        truth = ["Yes", "In-between", "No"][i % 3]
        out.append({"answer": truth if i % agree_every else "No" if truth != "No" else "Yes",
                    "consensus": truth, "known": i < known})
    return out


def test_mod10_a_newcomer_counts_only_after_20_answers_that_hear_what_experts_hear():
    trusted = [0.7, 0.75, 0.8]
    assert ml.trust_status(_answers(19, 50), trusted) == "learning"
    assert ml.trust_status(_answers(25, 50, known=4), trusted) == "learning"
    assert ml.trust_status(_answers(30, 50), trusted) == "counts"
    assert ml.trust_status(_answers(30, 2), trusted) == "learning"     # half wrong
    assert ml.trust_status(_answers(30, 2), trusted, was_trusted=True) == "counts"   # not low enough to stop
    assert ml.trust_status(_answers(30, 1), trusted, was_trusted=True) == "stopped"  # hears nothing experts hear


def test_mod10_no_screen_during_the_check_and_one_when_answers_count():
    assert ml.trust_screen("learning", just_changed=False) is None
    assert ml.trust_screen("stopped", just_changed=True) is None
    screen = ml.trust_screen("counts", just_changed=True)
    assert screen["lines"][0] == "Your answers now count."
    assert screen["lines"][1].startswith("You earn a token for each answer that counts.")
    assert not any(ch.isdigit() for line in screen["lines"] for ch in line)


def test_mod10_known_clips_are_one_in_four_then_one_in_ten():
    assert sum(ml.known_clip_due(i) for i in range(20)) == 5
    assert sum(ml.known_clip_due(i) for i in range(20, 120)) == 10


# MOD-12 · What do I get?
def test_mod12_three_short_cards():
    out = ml.what_do_i_get()
    assert [c["title"] for c in out["cards"]] == ["Teach a model", "Start a model", "Use a model in your business"]
    assert all(c["line"] for c in out["cards"])
    assert out["back"] == "Back to the list"


# MOD-13 · an empty search
def test_mod13_an_empty_search_offers_to_start_one():
    out = ml.model_list([SPEAKING], KASIA, query="beekeeping")
    assert out["models"] == []
    assert out["empty"] == {"title": "No models here yet.",
                            "line": "Nobody has started a model about this. You could be the first.",
                            "actions": ["Start the first one", "Clear the search"]}


# MOD-14 / MOD-15 · the one queue, what helps most first, Pause per model
def test_mod15_one_queue_across_models_helpful_first_and_none_starved():
    examples = (
        [{"id": f"r{i}", "model_id": "m-rasp", "private": True, "sureness": 0.9} for i in range(7)]
        + [{"id": "s-sure", "model_id": "m-speak", "sureness": 0.95},
           {"id": "s-unsure", "model_id": "m-speak", "sureness": 0.5},
           {"id": "s-lack", "model_id": "m-speak", "sureness": 0.9, "kind": "quiet"},
           {"id": "s4", "model_id": "m-speak", "sureness": 0.8}]
        + [{"id": "p1", "model_id": "m-pitch"}]
    )
    q = ml.build_queue([RASP, SPEAKING, PITCH], examples, MARTA, lacking={"m-speak": {"quiet"}},
                       company_line={"m-rasp": "Your company · you joined when Tomek invited the team"})
    assert q["header"] == "12 examples are waiting. The ones that help most come first."
    assert [(r["name"], r["line"], r["waiting"], r["action"]) for r in q["models"]] == [
        ("RASP sales replies", "Your company · you joined when Tomek invited the team", 7, "Pause"),
        ("Speaking confidence", "You teach it", 4, "Pause"),
        ("Pitch Coach", "You started it", 1, "Pause")]
    assert q["hint"] == "Pause a model to stop its examples for a while. Tap a model to teach only it."
    assert q["actions"] == ["Start", "Add an example you know well"]
    assert [e["id"] for e in q["examples"][:3]] == ["r0", "s-lack", "p1"]       # each model in turn
    speak = [e["id"] for e in q["examples"] if e["model_id"] == "m-speak"]
    assert speak[:2] == ["s-lack", "s-unsure"]


def test_mod15_a_paused_model_sends_nothing_and_one_model_can_be_taught_alone():
    examples = [{"id": "s1", "model_id": "m-speak"}, {"id": "p1", "model_id": "m-pitch"}]
    q = ml.build_queue([SPEAKING, PITCH], examples, MARTA, paused=["m-pitch"])
    assert [e["id"] for e in q["examples"]] == ["s1"]
    assert next(r for r in q["models"] if r["name"] == "Pitch Coach")["paused"] is True
    only = ml.build_queue([SPEAKING, PITCH], examples, MARTA, only="m-pitch")
    assert [e["id"] for e in only["examples"]] == ["p1"]


# MOD-16 · one answer counts for two models only on the same question and scale
def test_mod16_same_question_same_scale_counts_for_both():
    out = ml.counts_for({"id": "c1"}, SPEAKING, [SPEAKING, INTERVIEW])
    assert [m["name"] for m in out["counts_for"]] == ["Speaking confidence", "Interview voice"]
    assert out["note"] == "Counts for Speaking confidence and Interview voice: both ask this question"


def test_mod16_another_scale_does_not_count_twice():
    other = _model("m-x", "Other", scale=("Yes", "No"))
    out = ml.counts_for({"id": "c1"}, SPEAKING, [other])
    assert [m["name"] for m in out["counts_for"]] == ["Speaking confidence"]
    assert out["note"] is None


# MOD-17 · another model's question on the same clip follows right after
def test_mod17_the_other_question_follows():
    pitch_public = {**PITCH, "visibility": "public"}
    out = ml.counts_for({"id": "c1"}, SPEAKING, [pitch_public])
    assert out["follow"][0]["line"] == \
        "Pitch Coach asks something else about the same clip: how rushed does it sound?"
    screen = ml.teaching_screen(pitch_public, {"id": "c1"})
    assert screen["answers"][:5] == ["Calm", "Mostly calm", "Hurried in places", "Rushed", "Racing"]


# MOD-18 · a private example teaches only its company's model
def test_mod18_a_private_example_never_counts_for_a_public_model():
    out = ml.counts_for({"id": "x", "private": True}, RASP, [RASP, SPEAKING, INTERVIEW])
    assert [m["name"] for m in out["counts_for"]] == ["RASP sales replies"]
    assert out["note"] == "Your company’s own example: it teaches only RASP sales replies."
    assert out["follow"] == []


# MOD-19 · a recipe card that picks from a list shows the list
def test_mod19_the_pick_step_shows_the_list():
    screen = ml.teaching_screen(RASP, {"id": "x", "private": True}, step=0)
    assert screen["question"] == "Which first reply would you send?"
    assert screen["answers"] == ["Ask what they compared us with", "Offer a smaller first order",
                                 "Show what the price saves them"]
    assert screen["source_note"] == "Your company’s own example: it teaches only RASP sales replies."


# MOD-20 · an answer in words is spoken
def test_mod20_the_words_step_asks_for_a_recording():
    screen = ml.teaching_screen(RASP, {"id": "x"}, step=1)
    assert screen["question"] == "Now say how you would answer them, in your own words."
    assert screen["answers"] == ["Record your answer", "Skip"]


# MOD-21 · an added example counts once another teacher agrees; at most 1 in 5
def test_mod21_an_added_example_counts_only_with_a_second_teacher():
    ex = {"id": "a1", "source": "teacher", "added_by": MARTA}
    assert ml.added_example_counts(ex, [{"teacher_id": MARTA, "answer": "Yes"}]) is False
    assert ml.added_example_counts(ex, [{"teacher_id": MARTA, "answer": "Yes"},
                                        {"teacher_id": TOMEK, "answer": "No"}]) is False
    assert ml.added_example_counts(ex, [{"teacher_id": MARTA, "answer": "Yes"},
                                        {"teacher_id": TOMEK, "answer": "Yes"}]) is True
    sheet = ml.add_example_sheet()
    assert sheet["intro"] == "Do you know a case this model should learn from? Add it, then answer it yourself."
    assert [c["title"] for c in sheet["choices"]] == ["Record one", "Upload a file"]
    assert sheet["note"] == "It counts once another teacher agrees with your answer."


def test_mod21_added_examples_are_never_more_than_one_in_five():
    examples = [{"id": f"t{i}", "source": "takes"} for i in range(8)] + \
               [{"id": f"a{i}", "source": "teacher", "added_at": f"2026-11-0{i + 1}"} for i in range(5)]
    mix = ml.training_mix(examples)
    added = [e for e in mix if e["source"] == "teacher"]
    assert len(added) == 2 and len(added) * 5 <= len(mix)


# MOD-22 · release only when the gap is not luck
def test_mod22_a_clear_gap_offers_release_as_the_founders_choice():
    screen = ml.release_screen(PITCH, 2, better=14, worse=3, same=83)
    assert screen["title"] == "Version 2 is ready"
    assert screen["exam"]["intro"] == "On the 100 exam cases:"
    assert screen["verdict"] == "Version 2 is clearly better: a gap of 14 against 3 is very unlikely to be luck."
    assert screen["choice"] == ("Releasing it is your choice. Businesses on version 1 keep it "
                                "until they decide to switch.")
    assert screen["actions"] == ["Release version 2", "Not yet"]


def test_mod22_a_close_result_has_no_release_button():
    screen = ml.release_screen(PITCH, 2, better=9, worse=6, same=85)
    assert screen["verdict"] == "Not clearly better yet"
    assert screen["release"] is False and screen["actions"] == []


# MOD-23 · an empty queue says so
def test_mod23_the_empty_queue():
    q = ml.build_queue([SPEAKING], [], MARTA)
    assert q["empty"] == {"title": "Nothing waits for you.",
                          "line": "Thank you. New examples come when your models need you.",
                          "action": "Back to your chats"}


# MOD-49 · an invite to teach stays in the chat after Not now
def test_mod49_the_invite_stays_after_not_now():
    card = ml.invite_card("Kasia", "Short news cuts", said_not_now=True)
    assert card["lines"][1] == "You said not now. The invite stays here; open it whenever you like."
    assert card["lines"][0].startswith("Kasia invited you to teach Short news cuts with ")
    assert card["action"] == "Open"


# MOD-50 · the profile lists the models a person started and teaches
def test_mod50_the_profile_section():
    pitch = {**PITCH, "jars": {"counted_answers": 180, "exam_cases": 36}}
    out = ml.profile_models([pitch, SPEAKING], MARTA, {"m-speak": 86})
    assert out["title"] == "AI models"
    assert out["models"] == [
        {"name": "Pitch Coach", "badge": "Private", "line": "You started it · 36% of the way · 3 teachers",
         "actions": ["Make public", "Archive", "Download its data"]},
        {"name": "Speaking confidence", "badge": "Public",
         "line": "You teach it · 86 answers counted this month", "actions": []},
    ]
    assert ml.profile_models([SPEAKING], KASIA, {}) is None
