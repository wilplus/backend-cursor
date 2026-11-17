"""
STORY    As the founder building a speaking coach, I want a draft I can
         preview without saving it as live, and publish only when I say so,
         so a paste is checked and never run.
OUTCOME
  O1  A document with the wrong recording clock is refused, and a preview
      of it writes nothing.
  O2  A paste that calls eval is rejected and is not executed. A paste with
      the detector lines and nothing banned is checked.
  O3  A good document's preview lists its steps and writes nothing.
  O4  A digit in a fixed line, another line, a variant, or a choice is refused.
  O5  A saved draft is not the active coach until it is published.
PROVES   O1 -> test_a_bad_clock_is_refused_and_preview_does_not_write
         O2 -> test_a_paste_that_calls_eval_is_rejected_and_not_executed
         O3 -> test_preview_of_a_good_document_lists_the_steps_and_writes_nothing
         O4 -> test_a_digit_in_a_line_a_variant_or_a_choice_is_refused
         O5 -> test_a_saved_draft_is_not_active_until_it_is_published
WHY      Chat Builder phase 1 (frontend PR 1427): the walk keeps today's
         constants unless this person's coach document is published.
"""
from services import coach_definition as coach


class _Store:
    def __init__(self):
        self.rows = {}
        self.writes = 0

    def get_runtime_config(self, key):
        return self.rows.get(key)

    def get_runtime_config_entry(self, key):
        if key not in self.rows:
            return None
        return {"value": self.rows[key], "updated_at": "t"}

    def put_runtime_config_entry(self, key, value, *, updated_by, expected_updated_at):
        self.rows[key] = value
        self.writes += 1
        return True


def _document():
    return {
        "schema": 1,
        "id": "speaking-coach",
        "shell": {
            "recordingClockSeconds": 300,
            "publicLink": "hardcoded_will",
            "surfaces": ["feedback_walk", "ideal_text"],
        },
        "will": {"composer": "text", "recording": False},
        "theme": {"canvasMaxPx": 1080},
        "noticing": {"pinned": [{"name": name, "value": value} for name, value in coach.PINNED.items()]},
        "walk": {"steps": [
            {"key": "page", "screen": "walk.page", "fixed": ""},
            {"key": "tempo", "screen": "walk.tempo", "fixed": "You rushed here. Let it breathe."},
            {"key": "done", "screen": "walk.done", "fixed": "Lesson done."},
        ]},
        "plugins": [],
    }


def test_a_bad_clock_is_refused_and_preview_does_not_write():
    store = _Store()
    bad = _document()
    bad["shell"]["recordingClockSeconds"] = 240
    assert coach.refuse(bad) == "COACH_CLOCK"
    try:
        coach.preview(bad)
    except coach.CoachRefused:
        pass
    assert store.writes == 0


def test_a_paste_that_calls_eval_is_rejected_and_not_executed():
    checked = coach.check_plugin("eval(source)\nid: x\nrole: detector\ninterventionType: NOTICE\nhears: hedging\nstep: walk.message\n")
    assert checked["status"] == "rejected"
    assert "eval" in checked["reasons"]
    clean = coach.check_plugin("# id: hedge\n# role: detector\n# interventionType: NOTICE\n# hears: hedging\n# step: walk.message\n")
    assert clean["status"] == "checked"


def test_preview_of_a_good_document_lists_the_steps_and_writes_nothing():
    store = _Store()
    assert coach.preview(_document()) == {"ok": True, "keys": ["page", "tempo", "done"], "wrote": False}
    assert store.writes == 0


def test_a_digit_in_a_line_a_variant_or_a_choice_is_refused():
    for extra in (
        {"lines": ["Take 2"]},
        {"variants": [{"fixed": "3 times"}]},
        {"choices": ["Option 1"]},
        {"fixed": "Lesson 1"},
    ):
        document = _document()
        document["walk"]["steps"][1].update(extra)
        assert coach.refuse(document) == "COACH_NUMBER"


def test_a_saved_draft_is_not_active_until_it_is_published():
    store = _Store()
    coach.save_draft(store, "founder", _document())
    assert coach.read_active(store, "founder") is None
    coach.publish(store, "founder")
    assert coach.read_active(store, "founder")["id"] == "speaking-coach"
