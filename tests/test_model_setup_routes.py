"""
STORY    As someone starting a model, I want "Start your own" to keep my
         draft at every step, fill itself from my first Take, tell me when a
         model like mine exists, let me start right after the scale, take my
         existing data only with my tick, have me answer the first 10, and
         let me invite people who each choose; and as a speaker, I want my
         Takes to teach someone's model only while my training yes is on
         (N528 item 4, N563 item 4, N566, N570, N571, N575, N582).
OUTCOME
  O1  Without the ring row every setup route is 404, and a draft is 404 to
      anyone but its owner.
  O2  Three answers, one per screen; ✕ keeps the draft, which the list shows
      with "You stopped at the scale. Nothing is lost." and Continue
      (MOD-24, MOD-25).
  O3  "A model like yours already exists" slides up over the third answer,
      once; "Set up mine anyway" goes on (MOD-26).
  O4  After a first Take, Describe opens filled from its answers, with
      "Filled from your first Take. Change any word." (MOD-54).
  O5  "Start with this, finish the rest later" starts the model learning
      after its scale; the rest is a checklist on its page (MOD-28, MOD-36).
  O6  Existing data counts only after the tick: its rows become the model's
      private examples, their labels never sent to a teacher, and only the
      60 re-rates reach the queue (MOD-31).
  O7  The owner answers the first 10 on the teachers' screen, never an exam
      case, and their answers are kept like any teacher's (MOD-38, MOD-55).
  O8  Public shows its disclaimer before it goes public; the second expert
      and the people invited each get an invite (MOD-32, MOD-34, MOD-35).
  O9  When the processing authorization is not current, no provider call is
      made and the rules' draft stands.
  O11 An erased person's id is nowhere in a model's setup: it never keeps
      one, and the expert and the invited people come from rows the purge
      registry deletes.
  O12 The owner's first 10 become the model's known answers; an answer
      counts only once another trusted teacher gives the same one, and two
      matching trusted answers settle an example (N570 item 4).
  O13 A teacher hears a voice example by a signed link, and never receives
      the speaker, the Take or the snippet.
  O14 A deleted Take leaves every model it taught.
  O10 A host's model gathers the moments of Takes sent to them only from
      speakers whose training yes is on, recorded after it; turning it off
      takes them out again (MOD-02).
PROVES   O1 -> ModelSetupRoutesTest::test_without_the_ring_or_as_someone_else_nothing_is_shown
         O2 -> ModelSetupRoutesTest::test_three_answers_and_the_draft_kept
         O3 -> ModelSetupRoutesTest::test_a_model_like_yours_slides_up_once
         O4 -> ModelSetupRoutesTest::test_the_first_take_fills_describe
         O5 -> ModelSetupRoutesTest::test_start_after_the_scale_leaves_a_checklist
         O6 -> ModelSetupRoutesTest::test_existing_data_counts_only_with_the_tick
         O7 -> ModelSetupRoutesTest::test_the_owner_answers_the_first_ten
         O8 -> ModelSetupRoutesTest::test_public_after_its_disclaimer_and_invites
         O9 -> ModelSetupRoutesTest::test_no_provider_call_without_authorization
         O10 -> ModelSetupRoutesTest::test_takes_teach_only_with_the_training_yes
         O11 -> ModelSetupRoutesTest::test_an_erased_person_is_nowhere_in_the_setup
         O12 -> ModelSetupRoutesTest::test_nobody_teaches_a_model_alone
         O13 -> ModelSetupRoutesTest::test_a_voice_example_plays_by_a_signed_link_only
         O14 -> ModelSetupRoutesTest::test_a_deleted_take_leaves_every_model
WHY      routes/v2/model_setup.py over services/model_setup_store.py, and the
         job services/model_examples_from_takes.py.
"""
from __future__ import annotations

import io
import unittest
from unittest.mock import patch

from services.db import db
from tests.test_chats import _Store

MARTA = "22222222-2222-4222-8222-222222222222"
KASIA = "33333333-3333-4333-8333-333333333333"
DANIEL = "44444444-4444-4444-8444-444444444444"
TOMEK = "55555555-5555-4555-8555-555555555555"
PUBLIC = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
DRAFT = {"name": "Pitch Coach", "input": "voice", "unit": "a pitch clip of about 30 seconds",
         "question": "How rushed does it sound?", "pick_question": "Which exercise fits?",
         "options": ["Pause before the ask", "Slow the last line"],
         "scale": [{"t": "Calm", "d": ""}, {"t": "Mostly calm", "d": ""}, {"t": "Hurried in places", "d": ""},
                   {"t": "Rushed", "d": ""}, {"t": "Racing", "d": ""}],
         "part_titles": {"score": "Score how rushed it sounds"}}
ANSWERS = ["Founders rush their pitch when they talk to investors.",
           "I listen to their pitch and tell them where they sped up.",
           "I will rate short clips of pitches, pick the exercise, and say what I would tell the founder."]


class ModelSetupRoutesTest(unittest.TestCase):
    def setUp(self):
        from flask import Flask

        import auth
        from routes.v2 import register_domains
        from routes.v2.blueprint import v2_bp
        from services.rate_limits import limiter

        register_domains()
        if hasattr(limiter, "initialized"):
            self.addCleanup(setattr, limiter, "initialized", limiter.initialized)
            limiter.initialized = False
        app = Flask(__name__)
        app.register_blueprint(v2_bp, url_prefix="/v2")
        self.client = app.test_client()
        self.store = _Store()
        self.who = MARTA
        self.ring = True
        self.calls: list[str] = []
        self.memory: list[dict] = []
        people = [{"user_id": DANIEL, "name": "Daniel Okafor", "title": "Speaking coach"},
                  {"user_id": TOMEK, "name": "Tomek", "title": None}]

        def complete(_system, _payload, surface, _me):
            self.calls.append(surface)
            if surface == "model_setup_rules":
                return {"rules": [{"text": "A pitch faster than 170 words a minute sounds rushed.",
                                   "src": "From pitch-pace-study.pdf, page 4",
                                   "measured_on": "a study of 40 English-speaking founders",
                                   "measure": "pace_wpm", "op": ">", "cut": 170, "answer": "Rushed"}]}
            return dict(DRAFT)
        for p in (patch.object(auth, "verify_supabase_token", lambda _t: {"sub": self.who}),
                  patch.object(db, "client", self.store),
                  patch("services.rings.feature_is_on_for_user", lambda *_a, **_k: self.ring),
                  patch("services.model_setup_store._complete", complete),
                  patch("services.take_sends._people", lambda *_a: people),
                  patch.object(db, "list_speaker_memory_events", lambda *_a, **_k: self.memory, create=True)):
            p.start()
            self.addCleanup(p.stop)
        self.store.tables["ai_models"] = [
            {"id": PUBLIC, "name": "Pitch pace", "owner_id": KASIA, "owner_name": "Kasia",
             "visibility": "public", "status": "learning", "field": "pitch investors",
             "description": "How rushed a founder's pitch to investors sounds", "draft_step": None,
             "recipe": {"input": "voice", "steps": ["rate"], "question": "How rushed does the pitch sound?",
                        "scale": ["Calm", "Rushed"]}, "targets": {}, "setup": {}}]

    def _get(self, path):
        return self.client.get(path, headers={"Authorization": "Bearer t"})

    def _post(self, path, body=None):
        return self.client.post(path, json=body or {}, headers={"Authorization": "Bearer t"})

    def _begin(self):
        out = self._post("/v2/models/setup").get_json()
        return out["model_id"], out

    def _through_describe(self, mid, *, anyway=True):
        for step, text in zip(("problem", "today", "teach"), ANSWERS):
            out = self._post(f"/v2/models/{mid}/setup/{step}", {"value": text, "anyway": anyway}).get_json()
        return out

    def _model(self, mid):
        return next(m for m in self.store.tables["ai_models"] if m["id"] == mid)

    def test_without_the_ring_or_as_someone_else_nothing_is_shown(self):
        mid, _ = self._begin()
        self.who = KASIA
        self.assertEqual(self._get(f"/v2/models/{mid}/setup").status_code, 404)
        self.assertEqual(self._post(f"/v2/models/{mid}/setup/problem", {"value": "x"}).status_code, 404)
        self.who, self.ring = MARTA, False
        for path in (f"/v2/models/{mid}/setup", f"/v2/models/{mid}/setup/first-ten"):
            self.assertEqual(self._get(path).status_code, 404, path)
        self.assertEqual(self._post("/v2/models/setup").status_code, 404)

    def test_three_answers_and_the_draft_kept(self):
        mid, first = self._begin()
        self.assertEqual(first["screen"]["caption"], "Describe · 1 of 3")
        self.assertEqual(first["screen"]["lines"], ["What problem should your model solve?"])
        self.assertEqual(self._post(f"/v2/models/{mid}/setup/problem", {"value": " "}).status_code, 400)
        kind = self._through_describe(mid)["screen"]
        self.assertEqual(kind["step"], "kind")
        self.assertEqual(kind["fields"]["name"], "Pitch Coach")
        self._post(f"/v2/models/{mid}/setup/kind", {"parts": {"score": True}, "name": "Pitch Coach"})
        # ✕ now: the list keeps the draft where it stopped
        out = self._get("/v2/models").get_json()
        self.assertEqual(out["drafts"], [{"id": mid, "name": "Pitch Coach", "badge": "Your draft",
                                          "line": "You stopped at the scale. Nothing is lost.",
                                          "actions": ["Continue"]}])
        again = self._get(f"/v2/models/{mid}/setup").get_json()["screen"]
        self.assertEqual(again["step"], "scale")
        self.assertEqual(again["caption"], "Shape · 2 of 11")

    def test_a_model_like_yours_slides_up_once(self):
        mid, _ = self._begin()
        sheet = self._through_describe(mid, anyway=False)["screen"]
        self.assertEqual(sheet["step"], "teach")
        self.assertEqual(sheet["sheet"]["title"], "A model like yours already exists")
        self.assertEqual(sheet["sheet"]["card"]["name"], "Pitch pace")
        self.assertEqual(sheet["sheet"]["actions"], ["Teach this one", "Set up mine anyway"])
        after = self._post(f"/v2/models/{mid}/setup/teach", {"value": ANSWERS[2], "anyway": True}).get_json()
        self.assertEqual(after["screen"]["step"], "kind")

    def test_the_first_take_fills_describe(self):
        self.memory = [
            {"kind": "answer", "payload": {"question": "What do you know better than most people you meet?",
                                           "said": "How founders pitch to investors."}},
            {"kind": "answer", "payload": {"question": "What could you teach someone in five minutes that "
                                                       "would save them a year?",
                                           "said": "Slow down before the ask."}}]
        mid, out = self._begin()
        self.assertEqual(out["screen"]["fields"], {"problem": "How founders pitch to investors."})
        self.assertEqual(out["screen"]["notes"], ["Filled from your first Take. Change any word."])
        today = self._get(f"/v2/models/{mid}/setup?step=today").get_json()["screen"]
        self.assertEqual(today["fields"], {"today": "Slow down before the ask."})
        self.assertEqual(self.calls, ["model_setup_draft"])

    def test_start_after_the_scale_leaves_a_checklist(self):
        mid, _ = self._begin()
        self._through_describe(mid)
        self._post(f"/v2/models/{mid}/setup/kind", {"parts": {"score": True, "pick": True}, "name": "Pitch Coach"})
        out = self._post(f"/v2/models/{mid}/setup/start-now", {"scale": DRAFT["scale"]}).get_json()
        self.assertEqual(out["status"], "learning")
        self.assertEqual(out["screen"]["lines"], ["Pitch Coach is ready to learn. Today it answers from your "
                                                  "starting rules and examples."])
        self.assertIn("The question your teachers answer",
                      [i["title"] for i in out["screen"]["checklist"]["items"] if not i["done"]])
        recipe = self._model(mid)["recipe"]
        self.assertEqual((recipe["steps"], recipe["question"], recipe["scale"][0]),
                         (["rate", "pick"], "How rushed does it sound?", "Calm"))
        page = self._get(f"/v2/models/{mid}").get_json()
        self.assertEqual(page["owner"]["checklist"]["title"], "To finish setting it up")

    def test_existing_data_counts_only_with_the_tick(self):
        mid, _ = self._begin()
        self._through_describe(mid)
        self._post(f"/v2/models/{mid}/setup/kind", {"parts": {"score": True}, "name": "Pitch Coach"})
        self._post(f"/v2/models/{mid}/setup/scale", {"scale": DRAFT["scale"]})
        rows = "".join(f"Pitch number {i} about our seed round and the team we hire,Anna Nowak,{1 + i % 5}\n"
                       for i in range(80))
        out = self.client.post(f"/v2/models/{mid}/setup/data", headers={"Authorization": "Bearer t"},
                               data={"file": (io.BytesIO(("clip,speaker_name,score\n" + rows).encode()),
                                              "pitch-ratings.csv")},
                               content_type="multipart/form-data").get_json()
        self.assertEqual(out["screen"]["step"], "columns")
        check = self._post(f"/v2/models/{mid}/setup/columns", {}).get_json()["screen"]
        self.assertEqual(check["step"], "check")
        self.assertEqual(check["table"][0], ["Rows we can use", "80 / 80"])
        self.assertEqual(self._post(f"/v2/models/{mid}/setup/check", {}).status_code, 400)
        self.assertEqual([e for e in self.store.tables.get("ai_model_examples", []) if e["model_id"] == mid], [])
        self._post(f"/v2/models/{mid}/setup/check", {"consent": True})
        mine = [e for e in self.store.tables["ai_model_examples"] if e["model_id"] == mid]
        self.assertEqual(len(mine), 80)
        self.assertTrue(all(e["private"] and e["source"] == "upload" and not e.get("in_exam") for e in mine))
        self.assertNotIn("Anna", str([e["content"] for e in mine]))
        self.assertEqual(sum(1 for e in mine if e["kind"] == "rerate"), 60)
        self._model(mid)["status"] = "learning"
        self.who = DANIEL
        self.store.tables["ai_model_teachers"].append({"model_id": mid, "user_id": DANIEL, "role": "contributor",
                                                       "trust_status": "learning", "paused_at": None})
        queue = self._get(f"/v2/models/queue?only={mid}").get_json()
        self.assertEqual(len(queue["examples"]), 60)
        self.assertNotIn("uploaded", str(queue))
        self.assertNotIn("machine", str(queue))

    def test_the_owner_answers_the_first_ten(self):
        mid, _ = self._begin()
        self._through_describe(mid)
        self._post(f"/v2/models/{mid}/setup/kind", {"parts": {"score": True}, "name": "Pitch Coach"})
        self._post(f"/v2/models/{mid}/setup/start-now", {"scale": DRAFT["scale"]})
        empty = self._get(f"/v2/models/{mid}/setup/first-ten").get_json()["screen"]
        self.assertEqual(empty["actions"], ["Do it later"])
        self.store.tables["ai_model_examples"] = [
            {"id": f"e{i:07d}-0000-4000-8000-000000000000", "model_id": mid, "source": "takes",
             "private": False, "kind": None, "content": {"text": f"moment {i}"}, "in_exam": i == 0,
             "known_answer": None, "speaker_id": KASIA, "machine": {"label": "4"}, "sureness": 0.4}
            for i in range(12)]
        screen = self._get(f"/v2/models/{mid}/setup/first-ten").get_json()["screen"]
        self.assertEqual(screen["caption"], "Your first 10 · 1 of 10")
        self.assertEqual(screen["teaching"]["question"], "How rushed does it sound?")
        self.assertNotIn("machine", str(screen))
        self.assertNotEqual(screen["teaching"]["example"]["id"], "e0000000-0000-4000-8000-000000000000")
        for _ in range(10):
            eid = screen["teaching"]["example"]["id"]
            out = self._post(f"/v2/models/{mid}/setup/first-ten/{eid}", {"step": "rate", "answer": "Rushed"})
            screen = out.get_json()["screen"]
        self.assertEqual(screen["lines"][0], "You answered your first 10.")
        mine = [a for a in self.store.tables["ai_model_answers"] if a["teacher_id"] == MARTA]
        self.assertEqual(len(mine), 10)
        self.assertNotIn("e0000000-0000-4000-8000-000000000000", {a["example_id"] for a in mine})

    def test_public_after_its_disclaimer_and_invites(self):
        mid, _ = self._begin()
        self._through_describe(mid)
        self._post(f"/v2/models/{mid}/setup/kind", {"parts": {"score": True}, "name": "Pitch Coach"})
        self._post(f"/v2/models/{mid}/setup/scale", {"scale": DRAFT["scale"]})
        exam = self._get(f"/v2/models/{mid}/setup?step=exam").get_json()["screen"]
        self.assertEqual([c["title"] for c in exam["choices"]], ["You", "Daniel Okafor", "Tomek"])
        self.assertEqual(self._post(f"/v2/models/{mid}/setup/exam", {"expert": KASIA}).status_code, 400)
        self._post(f"/v2/models/{mid}/setup/exam", {"expert": DANIEL})
        sheet = self._post(f"/v2/models/{mid}/setup/share", {"visibility": "public"}).get_json()["screen"]
        self.assertEqual(sheet["step"], "public")
        self.assertEqual(sheet["caption"], "Before you make it public")
        self.assertEqual(self._model(mid)["visibility"], "private")
        invite = self._post(f"/v2/models/{mid}/setup/public", {"confirm": True}).get_json()["screen"]
        self.assertEqual(self._model(mid)["visibility"], "public")
        self.assertEqual(invite["lines"], ["Who should teach it with you?"])
        self.assertEqual(invite["actions"], ["Invite them", "Copy an invite link"])
        done = self._post(f"/v2/models/{mid}/setup/invite", {"people": [TOMEK, KASIA]}).get_json()
        self.assertEqual(done["status"], "learning")
        invited = {(i["invitee_id"], i["status"]) for i in self.store.tables["ai_model_invites"]}
        self.assertEqual(invited, {(DANIEL, "open"), (TOMEK, "open")})
        link = self._get(f"/v2/models/{mid}/setup/invite-link").get_json()["link"]
        self.assertTrue(link.endswith(f"/models/{mid}"))

    def test_an_erased_person_is_nowhere_in_the_setup(self):
        from services.data_purge_registry import DEPENDENCIES
        mid, _ = self._begin()
        self._through_describe(mid)
        self._post(f"/v2/models/{mid}/setup/kind", {"parts": {"score": True}, "name": "Pitch Coach"})
        self._post(f"/v2/models/{mid}/setup/scale", {"scale": DRAFT["scale"]})
        self._post(f"/v2/models/{mid}/setup/exam", {"expert": DANIEL})
        self._post(f"/v2/models/{mid}/setup/share", {"visibility": "private"})
        self._post(f"/v2/models/{mid}/setup/invite", {"people": [TOMEK]})
        stored = str(self._model(mid)["setup"])
        for person in (DANIEL, TOMEK, MARTA):
            self.assertNotIn(person, stored)
        exam = self._get(f"/v2/models/{mid}/setup?step=exam").get_json()["screen"]
        self.assertEqual(exam["actions"], ["Ask Daniel"])
        # Daniel's account is erased: the registry's rows for the models go.
        for dep in DEPENDENCIES:
            if dep.relation.startswith("ai_model"):
                rows = self.store.tables.get(dep.relation, [])
                if dep.clears_selector:
                    for r in rows:
                        if r.get(dep.selector_column) == DANIEL:
                            r[dep.selector_column] = None
                else:
                    self.store.tables[dep.relation] = [r for r in rows if r.get(dep.selector_column) != DANIEL]
        self.assertNotIn(DANIEL, str(self.store.tables["ai_models"]))
        after = self._get(f"/v2/models/{mid}/setup?step=exam").get_json()["screen"]
        self.assertEqual(after["actions"], ["Choose the second expert"])
        invite = self._get(f"/v2/models/{mid}/setup?step=invite").get_json()["screen"]
        self.assertEqual([c["key"] for c in invite["choices"] if c["check"]], [TOMEK])

    def _learning_model(self):
        mid, _ = self._begin()
        self._through_describe(mid)
        self._post(f"/v2/models/{mid}/setup/kind", {"parts": {"score": True}, "name": "Pitch Coach"})
        self._post(f"/v2/models/{mid}/setup/start-now", {"scale": DRAFT["scale"]})
        return mid

    def _examples(self, mid, n, **more):
        self.store.tables["ai_model_examples"] = [
            {"id": f"e{i:07d}-0000-4000-8000-000000000000", "model_id": mid, "source": "takes",
             "private": False, "kind": None, "content": {"text": f"moment {i}"}, "in_exam": False,
             "known_answer": None, "speaker_id": KASIA, "machine": None, "sureness": None,
             "added_by": None, "snippet_id": f"clip-{i}", "take_id": "take-1", **more} for i in range(n)]
        return [e["id"] for e in self.store.tables["ai_model_examples"]]

    def _counted(self, who):
        return {a["example_id"] for a in self.store.tables["ai_model_answers"]
                if a["teacher_id"] == who and a.get("counted")}

    def test_nobody_teaches_a_model_alone(self):
        mid = self._learning_model()
        first, other = self._examples(mid, 2)
        self._post(f"/v2/models/{mid}/setup/first-ten/{first}", {"step": "rate", "answer": "Rushed"})
        ex = {e["id"]: e for e in self.store.tables["ai_model_examples"]}
        self.assertEqual(ex[first]["known_answer"], "Rushed")
        self.assertEqual(self._counted(MARTA), set())          # one vote never trains it
        self.store.tables["ai_model_teachers"] += [
            {"model_id": mid, "user_id": u, "role": "contributor", "trust_status": "counts",
             "paused_at": None, "company_line": None, "trust_kappa": None, "trust_told_at": "x"}
            for u in (DANIEL, TOMEK)]
        self.who = DANIEL
        self._post(f"/v2/models/{mid}/examples/{first}/answer", {"step": "rate", "answer": "Rushed"})
        self._post(f"/v2/models/{mid}/examples/{other}/answer", {"step": "rate", "answer": "Calm"})
        self.assertEqual(self._counted(DANIEL), {first})
        self.assertEqual(self._counted(MARTA), {first})
        self.who = TOMEK
        self._post(f"/v2/models/{mid}/examples/{other}/answer", {"step": "rate", "answer": "Calm"})
        self.assertEqual(self._counted(DANIEL), {first, other})
        ex = {e["id"]: e for e in self.store.tables["ai_model_examples"]}
        self.assertEqual(ex[other]["known_answer"], "Calm")

    def test_a_voice_example_plays_by_a_signed_link_only(self):
        mid = self._learning_model()
        self._examples(mid, 1)
        self.store.tables["ai_model_teachers"].append(
            {"model_id": mid, "user_id": DANIEL, "role": "contributor", "trust_status": "learning",
             "paused_at": None, "company_line": None})
        self.who = DANIEL
        with patch.object(db, "get_snippet_playback_rows",
                          lambda ids, **_: [{"id": i, "storage_path": "takes/x.webm",
                                             "start_offset_ms": 1000, "duration_ms": 4000} for i in ids],
                          create=True), \
                patch("services.snippet_audio_url.resolve_snippet_audio_url",
                      lambda row, database=None: "https://signed.example/clip?token=short"):
            queue = self._get(f"/v2/models/queue?only={mid}").get_json()
        content = queue["examples"][0]["content"]
        self.assertEqual(content["audio_url"], "https://signed.example/clip?token=short")
        self.assertEqual((content["start_offset_ms"], content["duration_ms"]), (1000, 4000))
        for hidden in (KASIA, "take-1", "clip-0", "speaker_id", "snippet_id", "take_id"):
            self.assertNotIn(hidden, str(queue))

    def test_a_deleted_take_leaves_every_model(self):
        from services.data_purge_registry import DEPENDENCIES
        mid = self._learning_model()
        self._examples(mid, 3)
        self.store.tables["ai_model_examples"].append(
            {"id": "e9999999-0000-4000-8000-000000000000", "model_id": mid, "source": "takes",
             "take_id": "take-2", "speaker_id": KASIA, "in_exam": False})
        takes = [d for d in DEPENDENCIES if d.relation == "ai_model_examples" and d.locator_kind == "take"]
        self.assertEqual([(d.selector_column, d.disposition) for d in takes], [("take_id", "delete")])
        for d in takes:
            self.store.tables[d.relation] = [r for r in self.store.tables[d.relation]
                                             if r.get(d.selector_column) != "take-1"]
        self.assertEqual([e["take_id"] for e in self.store.tables["ai_model_examples"]], ["take-2"])

    def test_no_provider_call_without_authorization(self):
        from services.processing_authorization import ProcessingAuthorizationError

        class Gate:
            enforced = True

            def __init__(self, _db):
                pass

            def resolve_acquisition_principal(self, owner, **_):
                return owner

            def require_current(self, *_a, **_k):
                raise ProcessingAuthorizationError("PROCESSING_AUTHORIZATION_REQUIRED", "no", 403)
        with patch("services.processing_authorization.ProcessingAuthorizationService", Gate), \
                patch("services.rings.principal_for_user", lambda *_a, **_k: "principal-1"):
            mid, _ = self._begin()
            kind = self._through_describe(mid)["screen"]
        self.assertEqual(self.calls, [])
        self.assertEqual(kind["step"], "kind")
        self.assertTrue(kind["fields"]["name"])
        self.assertTrue([c for c in kind["choices"] if c["check"]])

    def test_takes_teach_only_with_the_training_yes(self):
        from services import model_examples_from_takes as job
        mid, _ = self._begin()
        self._through_describe(mid)
        self._post(f"/v2/models/{mid}/setup/kind", {"parts": {"score": True}, "name": "Pitch Coach"})
        self._post(f"/v2/models/{mid}/setup/start-now", {"scale": DRAFT["scale"]})
        t = self.store.tables
        t["chat_members"] = [{"id": "m-marta", "thread_id": "t1", "user_id": MARTA},
                             {"id": "m-kasia", "thread_id": "t1", "user_id": KASIA},
                             {"id": "m-marta2", "thread_id": "t2", "user_id": MARTA},
                             {"id": "m-tomek", "thread_id": "t2", "user_id": TOMEK}]
        t["chat_messages"] = [
            {"id": "s1", "thread_id": "t1", "author_member_id": "m-kasia", "kind": "take",
             "meta": {"take_session_id": "take-new"}},
            {"id": "s0", "thread_id": "t1", "author_member_id": "m-kasia", "kind": "take",
             "meta": {"take_session_id": "take-old"}},
            {"id": "s2", "thread_id": "t2", "author_member_id": "m-tomek", "kind": "take",
             "meta": {"take_session_id": "take-tomek"}}]
        yes = {KASIA: {"active": True, "granted_at": "2026-11-01T00:00:00+00:00"},
               TOMEK: {"active": False}}
        recorded = {"take-new": "2026-11-05T00:00:00+00:00", "take-old": "2026-10-01T00:00:00+00:00",
                    "take-tomek": "2026-11-05T00:00:00+00:00"}
        with patch("services.rings.principal_for_user", lambda uid, **_: uid), \
                patch.object(db, "get_mlc2_training_consent_status", lambda p: yes[p]), \
                patch("services.account_deletion.learning_stopped", lambda *_a: False), \
                patch.object(db, "v2_get_session_by_id", lambda s: {"created_at": recorded[s]}), \
                patch.object(db, "get_snippets_by_session",
                             lambda s: [{"id": f"{s}-clip{i}", "transcript": f"moment {i} of {s}"} for i in range(3)]):
            out = job.sweep(database=db)
            mine = [e for e in t["ai_model_examples"] if e["model_id"] == mid]
            self.assertEqual(out["added"], 3)
            self.assertEqual({e["take_id"] for e in mine}, {"take-new"})
            self.assertTrue(all(e["speaker_id"] == KASIA and not e["private"] for e in mine))
            self.assertEqual(job.sweep(database=db)["added"], 0)
            yes[KASIA] = {"active": False}
            self.assertEqual(job.sweep(database=db)["removed"], 3)
        self.assertEqual([e for e in t["ai_model_examples"] if e["model_id"] == mid], [])


if __name__ == "__main__":
    unittest.main()
