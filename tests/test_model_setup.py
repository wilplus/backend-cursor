"""
STORY    As someone starting a model, I want the setup to walk me through
         three chapters one step at a time, propose what my model does and
         which AI does each part, check my data the way a data scientist
         would, keep the final exam fair, and show me afterwards what needs
         me, in plain words, so a model I start can learn from day one
         (N528 item 4, N566 items 2 to 6, N570, N585).
OUTCOME
  O1  The setup has three chapters with a thin bar; the caption says where
      I am and optional steps say so (MOD-24).
  O2  From my three answers the app proposes what the model does, and each
      part gets the AI that fits it: a voice score is WillpowerLab's voice
      scorer, picking and answering GPT-4o mini; others say "Soon"
      (MOD-27, MOD-29).
  O3  The scale step says what one example is, with a word for every point,
      and a model can start right there; what is left becomes a checklist
      (MOD-28, MOD-36).
  O4  Uploaded data is checked: repeats and near repeats removed, rows with
      no score skipped, mislabelled rows flagged, names removed, a column
      naming a person left out; 60 rows are re-rated first (MOD-31).
  O5  The exam takes whole speakers, never an upload, never one of my first
      10; it is set aside by two experts (MOD-32).
  O6  Shorter and Longer switch the teachers' steps; Public shows its
      disclaimer first (MOD-33, MOD-34).
  O7  My page puts "Needs you now" on top where teachers disagree, gives an
      honest range and the slowest jar, and agreement within one point and
      exactly; a starting rule is kept or dropped on the first 50 ratings
      (MOD-30, MOD-37).
PROVES   O1 -> SetupRulesTest::test_three_chapters_with_a_thin_bar
         O2 -> SetupRulesTest::test_what_it_does_and_the_ai_for_each_part
         O3 -> SetupRulesTest::test_the_scale_and_starting_early_leave_a_checklist
         O4 -> SetupRulesTest::test_uploaded_data_is_checked_before_it_counts
         O5 -> SetupRulesTest::test_the_exam_is_fair
         O6 -> SetupRulesTest::test_shorter_longer_and_the_public_disclaimer
         O7 -> SetupRulesTest::test_the_owners_page_says_what_needs_them
WHY      services/model_setup.py holds the setup's rules and signed words
         (the locked prototype, version 8).
"""
from __future__ import annotations

import unittest

from services import model_setup as S

MARTA = {
    "problem": "Founders rush their pitch when they talk to investors. The ending gets lost.",
    "today": "I listen to their pitch, tell them where they sped up, and give them one exercise.",
    "teach": "I will rate short clips of pitches, pick the exercise, and say what I would tell the founder.",
}
RUSH = [{"t": "Calm", "d": "Room to breathe"}, {"t": "Mostly calm", "d": ""}, {"t": "Hurried in places", "d": ""},
        {"t": "Rushed", "d": ""}, {"t": "Racing", "d": "Words run together"}]


def _marta(**more):
    d = S.apply_drafted(dict(MARTA), {"name": "Pitch Coach", "input": "voice",
                                      "unit": "a pitch clip of about 30 seconds",
                                      "question": "How rushed does it sound?",
                                      "part_titles": {"score": "Score how rushed it sounds",
                                                      "pick": "Pick the exercise"}})
    d.update({"parts": S.suggest_parts(d), "scale": RUSH, **more})
    return d


class SetupRulesTest(unittest.TestCase):
    def test_three_chapters_with_a_thin_bar(self):
        d = _marta()
        first = S.step_screen(d, "problem")
        self.assertEqual(first["caption"], "Describe · 1 of 3")
        self.assertEqual([c["name"] for c in first["chapters"]], ["Describe", "Shape", "Share"])
        self.assertEqual(first["lines"], ["What problem should your model solve?"])
        self.assertEqual(S.step_screen(d, "today")["lines"], ["How do you solve it today?"])
        self.assertEqual(S.step_screen(d, "teach")["lines"], ["How will you teach your model?"])
        rules = S.step_screen(d, "rules")
        self.assertEqual(rules["optional"], "Optional")
        self.assertLess(first["bar"], rules["bar"])
        self.assertLess(rules["bar"], S.step_screen(d, "invite")["bar"])

    def test_what_it_does_and_the_ai_for_each_part(self):
        d = _marta()
        kind = S.step_screen(d, "kind")
        self.assertEqual(kind["lines"], ["From your answers, your model will do three things. "
                                         "Untick what it should not do."])
        self.assertEqual([c["title"] for c in kind["choices"]],
                         ["It gives a score on a scale", "It picks from a list", "It learns to answer like you"])
        self.assertEqual(kind["actions"], ["That’s right"])
        ai = S.step_screen(d, "ai")
        self.assertEqual([(c["title"], c["line"]) for c in ai["choices"]], [
            ("Score how rushed it sounds",
             "WillpowerLab’s voice scorer: it learns from how the voice sounds, not only from the words"),
            ("Pick the exercise", "GPT-4o mini, choosing only from your list"),
            ("It learns to answer like you", "GPT-4o mini")])
        self.assertEqual([(c["title"], c["tag"]) for c in ai["others"]["choices"]],
                         [("GPT-4o", "Soon"), ("Mistral", "Soon"), ("Llama", "Soon")])

    def test_the_scale_and_starting_early_leave_a_checklist(self):
        d = _marta()
        scale = S.step_screen(d, "scale")
        self.assertEqual(scale["lines"], ["One example is a pitch clip of about 30 seconds. "
                                          "Your teachers will rate each clip on this scale."])
        self.assertEqual([(p["point"], p["t"]) for p in scale["fields"]["scale"]][::4],
                         [(1, "Calm"), (5, "Racing")])
        self.assertEqual(scale["actions"], ["Use this scale", "Start with this, finish the rest later"])
        self.assertTrue(S.can_start(d))
        ready = S.ready_screen("Pitch Coach", d, ratings_target=500)
        self.assertEqual(ready["lines"], ["Pitch Coach is ready to learn. Today it answers from your "
                                          "starting rules and examples."])
        self.assertEqual(ready["checklist"]["title"], "To finish setting it up")
        left = [i["title"] for i in ready["checklist"]["items"] if not i["done"]]
        self.assertIn("The final exam", left)
        self.assertIn("Your first 10 answers", left)
        self.assertEqual(ready["locked"]["lines"][0],
                         "This opens once its first training beats today’s version on the final exam.")
        self.assertEqual(ready["actions"], ["Try it", "Back to the list"])
        self.assertFalse(S.can_start({**d, "scale": RUSH[:2]}))

    def test_uploaded_data_is_checked_before_it_counts(self):
        csv_text = ("clip,speaker_name,score\n"
                    "Anna Nowak pitches our seed round and slows down at the end,Anna Nowak,2\n"
                    "Anna Nowak pitches our seed round and slows down at the end,Anna Nowak,2\n"
                    "We grow ten percent each month and we need two million to hire,Tom Lee,\n"
                    "Call me at +48 600 100 200 for the deck and the numbers,Eva Kim,3\n")
        parsed = S.parse_file("pitch-ratings.csv", csv_text.encode())
        mapping = S.map_columns(parsed["columns"], {"score": True})
        self.assertEqual({m["col"]: m["role"] for m in mapping},
                         {"clip": "example", "speaker_name": "out", "score": "score"})
        check = S.check_data(parsed, mapping, RUSH, {"score": True})
        self.assertEqual((check["total"], check["usable"], check["repeats"], check["no_score"]), (4, 2, 1, 1))
        self.assertNotIn("Anna", " ".join(r["example"] for r in check["rows"]))
        self.assertNotIn("600 100 200", " ".join(r["example"] for r in check["rows"]))
        self.assertGreaterEqual(check["names_removed"], 2)
        d = _marta(data={"columns": parsed["columns"], "map": mapping,
                         "check": {k: v for k, v in check.items() if k != "rows"}})
        cols = S.step_screen(d, "columns")
        self.assertIn("→ Left out: it names a person", [c["line"] for c in cols["choices"]])
        screen = S.step_screen(d, "check")
        self.assertEqual(screen["lines"], ["We checked your data."])
        self.assertEqual([r[0] for r in screen["table"]],
                         ["Rows we can use", "Repeats removed", "Near repeats removed",
                          "Rows with no score, skipped", "Rows that look mislabelled",
                          "Names and places removed"])
        self.assertIn("Before your data counts, your teachers re-rate 60 of its examples.", screen["after"][0])
        self.assertEqual(screen["choices"][0]["title"], "I have the right to use this data, and the people "
                                                        "in it agreed to its use for training.")
        self.assertEqual(screen["actions"], ["Upload it", "Fix the file first"])
        rows = [{"example": f"case {i}", "mislabelled": i == 7} for i in range(200)]
        sample = S.rerate_sample(rows, "m1")
        self.assertEqual(len(sample), 60)
        self.assertEqual(sample[0], 7)
        self.assertEqual(S.upload_counts([(3, 3)] * 50 + [(1, 5)] * 10)["counts"], True)
        self.assertIsNone(S.upload_counts([(3, 3)] * 10))

    def test_the_exam_is_fair(self):
        examples = [{"id": f"{s}-{i}", "source": "takes", "speaker_id": s} for s in
                    (f"speaker{n}" for n in range(60)) for i in range(4)]
        examples += [{"id": "up", "source": "upload", "speaker_id": None},
                     {"id": "first", "source": "takes", "speaker_id": "speaker0", "first_ten": True}]
        picked = S.exam_split(examples, 0)
        speakers_in = {e["speaker_id"] for e in examples if e["id"] in picked}
        speakers_out = {e["speaker_id"] for e in examples if e["id"] not in picked and e["speaker_id"]}
        self.assertTrue(picked)
        self.assertFalse(speakers_in & (speakers_out - {"speaker0"}))
        self.assertNotIn("up", picked)
        self.assertNotIn("first", picked)
        self.assertEqual(S.exam_split(examples, 100), set())
        self.assertEqual(S.exam_settled([{"teacher_id": "a", "answer": "3"}, {"teacher_id": "b", "answer": "3"}],
                                        ["a", "b"]), "3")
        screen = S.step_screen(_marta(exam={"experts": ["me", "dan"]}), "exam",
                               people=[{"id": "dan", "name": "Daniel Okafor", "line": "Speaking coach"}])
        self.assertEqual(screen["lines"], [
            "Before anyone teaches it, two experts set aside a final exam: 100 clips your model never learns from.",
            "It can be sold only when it does clearly better on this exam than it does today."])
        self.assertEqual(screen["actions"], ["Ask Daniel"])

    def test_shorter_longer_and_the_public_disclaimer(self):
        d = _marta()
        journey = S.step_screen(d, "journey")
        self.assertEqual(journey["lines"], ["Here is what each teacher will do. Make it shorter or longer."])
        self.assertEqual(len(journey["fields"]["steps"]), 4)
        d["journey_off"] = S.journey_change(d, longer=False)
        self.assertEqual(len(S.step_screen(d, "journey")["fields"]["steps"]), 3)
        self.assertEqual(S.recipe_of(d)["steps"], ["rate", "pick"])
        d["journey_off"] = S.journey_change(d, longer=True)
        self.assertEqual(S.recipe_of(d)["steps"], ["rate", "pick", "words"])
        self.assertEqual([c["title"] for c in S.step_screen(d, "journey")["choices"]], ["Shorter", "Longer"])
        share = S.step_screen(d, "share")
        self.assertEqual(share["lines"], ["Who can see your model?"])
        self.assertEqual([c["title"] for c in share["choices"]], ["Private", "Public"])
        public = S.step_screen(d, "public")
        self.assertIn("Anyone will be able to see your model and teach it.", public["lines"])
        self.assertIn("Recordings never leave WillpowerLab.", public["lines"][2])
        self.assertEqual(public["actions"], ["Make it public", "Keep it private"])

    def test_the_owners_page_says_what_needs_them(self):
        rates = {}
        n = 0
        while len(rates) < 12:
            eid = f"e{n}"
            n += 1
            if S.measured(eid):
                rates[eid] = [3, 4]
        agree = S.agreement(rates)
        self.assertEqual((agree["within"], agree["exact"], agree["confused"]), (1.0, 0.0, (3, 4)))
        panel = S.owner_panel({"name": "Pitch Coach", "recipe": {}}, _marta(), pct=36,
                              jars={"ratings": 180, "exam": 100, "voices": 0},
                              targets={"ratings": 500, "exam": 100}, pace={"ratings": 60, "exam": 0},
                              agree=agree, sources={"takes": 12, "teacher": 2}, upload=None,
                              rules_checked=[])
        self.assertEqual(panel["needs_you"]["line"],
                         "Your teachers disagree most between 3 (Hurried in places) and 4 (Rushed). "
                         "Clearer words for those two points would help.")
        self.assertEqual(panel["needs_you"]["actions"], ["Make those two clearer"])
        self.assertEqual(panel["head"], "Pitch Coach is 36% of the way to its first training: about 4 to 7 "
                                        "weeks more. The slowest jar decides: ratings from trusted teachers.")
        self.assertEqual(panel["rows"][0], ["How often your teachers agree",
                                            "Within one point 10 times in 10 · exactly 0 in 10"])
        self.assertEqual(panel["folds"][0]["title"], "Where its examples come from")
        self.assertEqual(panel["folds"][1]["title"], "What runs by itself")
        rule = {"text": "A pitch faster than 170 words a minute sounds rushed.", "measure": "pace_wpm",
                "op": ">", "cut": 170, "answer": "Rushed", "on": True}
        fast = [{"measures": {"pace_wpm": 190}, "answer": "Rushed"}] * 40 + \
               [{"measures": {"pace_wpm": 190}, "answer": "Calm"}] * 10
        self.assertEqual(S.check_rule(rule, fast), {"agree_of_50": 40, "kept": True})
        self.assertEqual(S.check_rule(rule, fast[:20]), None)
        self.assertEqual(S.check_rule(rule, [{"measures": {"pace_wpm": 190}, "answer": "Calm"}] * 50)["kept"],
                         False)


if __name__ == "__main__":
    unittest.main()
