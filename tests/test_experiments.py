"""
STORY    As a volunteer in the chat builder's experiments area, I keep my own
         sessions, takes, prompts and interventions, and nobody else's, and I
         can delete all of it.
OUTCOME
  O1  The shipped prompts_v1.yaml loads as UTF-8 Polish, and the gate order,
      each cell's reference and the self-rating choices come from that file.
  O2  A session stores my consent and, when I send one, a single PDF page or
      slides. My volunteer id is not my auth id.
  O3  A take keeps the tag, the rating, the words Whisper returned, and the
      audio in the private bucket. A rating outside the prompt set is refused.
  O4  Asking for an analysis answers 202. The stored result is
      analyze-take/v0.1. A locked step's score_if_unlocked stays stored and
      is left out of the read the volunteer gets. No feeling is named.
  O5  My prompt library and my interventions are mine. The picker returns at
      most two, and the earlier step in the file's order wins.
  O6  Export is my rows only. A researcher export needs my explicit consent.
  O7  Deleting me removes my rows and my stored files. Someone else cannot
      read or delete them.
PROVES   O1 -> test_the_shipped_prompt_set_loads
         O2 -> test_a_session_stores_consent_and_not_my_auth_id
         O3 -> test_a_take_keeps_the_words_and_the_rating
         O4 -> test_analyze_take_follows_the_prompt_set
         O5 -> test_the_earlier_step_wins_and_at_most_two_fire
         O6 -> test_export_is_only_mine_and_researcher_needs_consent
         O7 -> test_delete_me_removes_my_rows_and_files
"""
from __future__ import annotations

import io
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from services.canonical_product import OwnerPrincipal
from services.db import db
from services.experiments import coaching_context
from services import experiment_analysis as analysis
from services.experiments_config import (
    CONFIDENCE_FLOOR,
    PROMPT_SET_PATH,
    PromptSetError,
    analyze_example,
    baseline_tags,
    cell_references,
    check_self_rating,
    gate_for,
    load_prompt_set,
    rank_interventions,
    validate_prompt_set,
)
from services.processing_authorization import ProcessingAuthorizationService
from services.project_repository import ProjectRepository
from tests.test_chats import _Store

ME = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
CONSENT = {"participant": True, "researcher": False, "version": "experiments-v1"}
FEELING_WORDS = (
    "happy", "sad", "angry", "anger", "fear", "anxious", "anxiety",
    "stressed", "disgust", "joy", "nervous", "emotion",
)
_PACKAGE = Path(__file__).resolve().parents[1] / "vendor" / "wpl_arousal_v0.2"


def _fake_wav(raw, name, dest):
    dest.write_bytes(raw or b"R")
    return str(dest)


def _inline(take_id, volunteer_id):
    analysis.run(take_id, volunteer_id)
    return "inline"


class _Model:
    def __init__(self):
        self.calls = []
        self.built = None

    def build_baseline(self, paths, volunteer_id):
        self.built = volunteer_id
        return {"baseline_version": "analyze-take/v0.1", "volunteer_id": volunteer_id,
                "seconds": 1.0, "n_chunks": len(paths), "warnings": []}

    def analyze_take(self, path, transcript=None, baseline=None, business_case=None,
                     take_id=None, prompt_tag=None):
        self.calls.append({
            "transcript": transcript, "business_case": business_case,
            "take_id": take_id, "prompt_tag": prompt_tag,
        })
        return {
            "schema": "analyze-take/v0.1",
            "value_range": [-1, 1],
            "value_scaling": "fixed",
            "thresholds": {
                "engagement_score_min": -0.5,
                "arousal_conf_min": 0.363,
                "valence_conf_min": 0.482,
            },
            "takes": [{
                "take_id": take_id,
                "prompt_tag": prompt_tag,
                "duration_s": 1.0,
                "transcript": transcript,
                "order": ["engagement", "arousal", "valence", "clarity"],
                "moments": [{"t_start": 0.0, "t_end": 1.0, "grid": [
                    {"step": "engagement", "cue": "loudness", "value": 0.1, "vs": "baseline"},
                ]}],
                "summary": {
                    "engagement": {"score": 0.1, "confidence": 0.9, "vs": "baseline", "unlocked": True},
                    "arousal": {"score": None, "confidence": 0.2, "vs": "baseline",
                                "unlocked": False, "score_if_unlocked": 0.4},
                    "valence": {"score": None, "confidence": 0.2, "vs": "baseline+reference",
                                "unlocked": False, "score_if_unlocked": 0.2},
                    "clarity": {"score": None, "confidence": 0.2, "vs": "reference",
                                "unlocked": False, "score_if_unlocked": 0.0},
                },
                "gate": {"step": "arousal", "reason": "confidence"},
            }],
        }

    def warmup(self):
        return None


def _pdf(pages: int) -> bytes:
    from pypdf import PdfWriter
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=72, height=72)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


class _Files:
    def __init__(self):
        self.objects: dict[str, tuple[bytes, str]] = {}

    def put(self, path, data, content_type):
        self.objects[path] = (bytes(data), content_type)

    def remove(self, paths):
        for path in paths:
            self.objects.pop(path, None)

    def fetch(self, path):
        item = self.objects.get(path)
        return item[0] if item else None


class PromptSetTests(unittest.TestCase):
    def test_the_shipped_prompt_set_loads(self):
        raw = PROMPT_SET_PATH.read_bytes()
        text = raw.decode("utf-8")
        self.assertIn("dwunastoletniemu bratankowi", text)
        prompt_set = load_prompt_set()
        self.assertEqual(prompt_set["version"], 1)
        self.assertEqual(prompt_set["language"], "pl")
        self.assertEqual(prompt_set["order"], ["engagement", "arousal", "valence", "clarity"])
        self.assertEqual(
            prompt_set["baseline_scored"],
            ["engagement", "arousal", "valence_voice"])
        self.assertEqual(prompt_set["reference_scored"], ["valence_words", "clarity"])
        self.assertEqual(
            prompt_set["self_report"],
            {"energy": ["low", "high"], "feeling": ["good", "tense"]})
        self.assertEqual(
            [prompt["id"] for prompt in prompt_set["prompts"]],
            ["b1", "b2", "b3", "p1", "p2", "p3", "p4", "c1", "c2", "c3", "c4", "c5", "k1", "k2"])
        nephew = next(prompt for prompt in prompt_set["prompts"] if prompt["id"] == "k1")
        self.assertEqual(nephew["reference"], "business_case")
        self.assertIn("dwunastoletniemu bratankowi", nephew["text"])
        calm = next(prompt for prompt in prompt_set["prompts"] if prompt["id"] == "b1")
        self.assertNotIn("reference", calm)
        self.assertEqual(baseline_tags(prompt_set), {"baseline_calm"})

    def test_references_and_the_gate_follow_the_file(self):
        prompt_set = load_prompt_set()
        refs = cell_references(prompt_set)
        self.assertEqual(refs[("engagement", "verbal")], "baseline")
        self.assertEqual(refs[("engagement", "vocal")], "baseline")
        self.assertEqual(refs[("arousal", "vocal")], "baseline")
        self.assertEqual(refs[("valence", "vocal")], "baseline")
        self.assertEqual(refs[("valence", "verbal")], "reference")
        self.assertEqual(refs[("clarity", "verbal")], "reference")
        self.assertEqual(refs[("clarity", "vocal")], "reference")
        example = analyze_example(prompt_set)
        for dimension, channels in example["moments"][0]["grid"].items():
            for channel, cell in channels.items():
                self.assertEqual(cell["reference"], refs[(dimension, channel)])
        summary = {step: {"score": 0.0, "confidence": 0.9} for step in prompt_set["order"]}
        self.assertIsNone(gate_for(summary, prompt_set["order"], CONFIDENCE_FLOOR))
        summary[prompt_set["order"][1]] = {"score": 0.0, "confidence": 0.1}
        self.assertEqual(
            gate_for(summary, prompt_set["order"], CONFIDENCE_FLOOR),
            prompt_set["order"][1])
        swapped = ["clarity", "engagement"]
        unsure = {"clarity": {"confidence": 0.1}, "engagement": {"confidence": 0.1}}
        self.assertEqual(gate_for(unsure, swapped, CONFIDENCE_FLOOR), "clarity")

    def test_a_rating_is_checked_against_self_report(self):
        prompt_set = load_prompt_set()
        self.assertEqual(
            check_self_rating({"energy": "high", "feeling": "tense"}, prompt_set),
            {"energy": "high", "feeling": "tense"})
        with self.assertRaises(PromptSetError):
            check_self_rating({"energy": "medium", "feeling": "good"}, prompt_set)
        custom = {"self_report": {"pace": ["slow", "fast"]}}
        self.assertEqual(check_self_rating({"pace": "slow"}, custom), {"pace": "slow"})
        with self.assertRaises(PromptSetError):
            check_self_rating({"energy": "low", "feeling": "good"}, custom)

    def test_a_prompt_set_with_an_extra_key_is_refused(self):
        prompt_set = load_prompt_set()
        broken = dict(prompt_set)
        broken["notes"] = "no"
        with self.assertRaises(PromptSetError):
            validate_prompt_set(broken)

    def test_the_example_document_matches_the_schema(self):
        import jsonschema
        schema = json.loads((_PACKAGE / "schema.json").read_text(encoding="utf-8"))
        for name in ("example_analyze_take_v0.1.json", "example_analyze_take_v0.2.json"):
            example = json.loads((_PACKAGE / "examples" / name).read_text(encoding="utf-8"))
            jsonschema.validate(example, schema)
            shown = analysis.for_volunteer(example)
            self.assertNotIn("score_if_unlocked", json.dumps(shown))
            self.assertIn("score_if_unlocked", json.dumps(example))
            jsonschema.validate(shown, schema)

    def test_the_earlier_step_wins_and_at_most_two_fire(self):
        order = load_prompt_set()["order"]
        grid = {
            step: {"verbal": {"value": 1.0, "reference": "baseline"},
                   "vocal": {"value": 1.0, "reference": "baseline"}}
            for step in order
        }
        pattern = {"verbal": 1.0, "vocal": 1.0}
        rows = [
            {"id": "late", "grid": {"clarity": pattern}, "threshold": 0.5,
             "rule": {"step": "clarity"}},
            {"id": "mid", "grid": {"arousal": pattern}, "threshold": 0.5,
             "rule": {"step": "arousal"}},
            {"id": "early", "grid": {"engagement": pattern}, "threshold": 0.5,
             "rule": {"step": "engagement"}},
        ]
        fired = rank_interventions(rows, grid, order)
        self.assertEqual([row["id"] for row in fired], ["early", "mid"])
        quiet = {"verbal": {"value": -1.0, "reference": "baseline"},
                 "vocal": {"value": -1.0, "reference": "baseline"}}
        missed = rank_interventions(
            [{"id": "no", "grid": {"engagement": {"verbal": 1.0, "vocal": 1.0}},
              "threshold": 1.0, "rule": {"step": "engagement"}}],
            {"engagement": quiet}, order)
        self.assertEqual(missed, [])


class ExperimentsApiTests(unittest.TestCase):
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
        self.files = _Files()
        self.who = ME
        self.choices = {"has_receipt": True, "personalised_practice": True,
                        "sensitive_information": True}
        self.authority = {"authorized": True, "pooled_learning_eligible": False}
        self.words = [{"word": "cześć", "start": 0.2, "end": 0.6}]
        self.model = _Model()

        def _transcribe(raw, name, user_id):
            self.heard = user_id
            return list(self.words)

        for item in (
            patch.object(auth, "verify_supabase_token", lambda _t: {"sub": self.who}),
            patch.object(db, "client", self.store),
            patch("services.experiments._storage", lambda: self.files),
            patch("services.experiments.transcribe_words", _transcribe),
            patch("services.experiments.vocal_measures", lambda raw, name: None),
            patch("services.experiment_analysis._model", lambda: self.model),
            patch("services.experiment_analysis.to_wav", _fake_wav),
            patch("services.experiment_analysis.dispatch", _inline),
            patch.dict(os.environ, {
                "PLF1_PROCESSING_AUTHORIZATION_MODE": "off",
                "INVITE_ONLY_SINCE": "off",
                "EXPERIMENTS_VOLUNTEER_PEPPER": "test-pepper",
            }),
            patch.object(ProjectRepository, "owner_for_user",
                         lambda _repo, user: OwnerPrincipal(f"owner-{user}", user, False)),
            patch.object(ProcessingAuthorizationService, "resolve_acquisition_principal",
                         lambda _service, owner, **_k: owner),
            patch.object(ProcessingAuthorizationService, "consent_choices",
                         lambda _service, _principal: dict(self.choices)),
            patch.object(ProcessingAuthorizationService, "status",
                         lambda _service, _principal: dict(self.authority)),
        ):
            item.start()
            self.addCleanup(item.stop)

    def _headers(self):
        return {"Authorization": "Bearer t"}

    def _refused_as_guest(self, chat_id):
        put = self.client.put(
            f"/v2/chats/{chat_id}/experiment-config", headers=self._headers(),
            json={"model_id": "wpl_arousal@0.2"})
        examples = self.client.get(
            f"/v2/chats/{chat_id}/reply-examples", headers=self._headers())
        for response in (put, examples):
            self.assertEqual(response.status_code, 403, response.get_json())
            self.assertEqual(response.get_json()["code"], "NOT_HOST")
            self.assertEqual(response.get_json()["error"], "Only the host can change this.")

    def _session(self, consent=None, **extra):
        return self.client.post(
            "/v2/experiments/sessions", headers=self._headers(),
            json={"consent": consent or CONSENT}, **extra)

    def _take(self, session_id, **form):
        body = {
            "prompt_id": "b1",
            "tag": "baseline_calm",
            "self_rating": json.dumps({"energy": "low", "feeling": "good"}),
            "audio": (io.BytesIO(b"not-really-audio"), "talk.webm"),
        }
        body.update(form)
        return self.client.post(
            f"/v2/experiments/sessions/{session_id}/takes",
            headers=self._headers(), data=body)

    def test_a_session_stores_consent_and_not_my_auth_id(self):
        denied = self.client.post("/v2/experiments/sessions")
        self.assertEqual(denied.status_code, 401)
        missing = self._session({"participant": False, "researcher": False, "version": "experiments-v1"})
        self.assertEqual(missing.status_code, 400)
        made = self._session().get_json()
        self.assertEqual(made["consent"]["participant"], True)
        self.assertNotEqual(made["volunteer_id"], ME)
        self.assertEqual(len(made["volunteer_id"]), 64)
        self.assertIsNone(made["business_case"])
        self.assertNotIn(ME, json.dumps(made))
        pages = self.client.post(
            "/v2/experiments/sessions", headers=self._headers(),
            data={"consent": json.dumps(CONSENT),
                  "business_case": (io.BytesIO(_pdf(2)), "two.pdf")})
        self.assertEqual(pages.status_code, 400)
        self.assertEqual(pages.get_json()["code"], "ONE_PAGE")
        one = self.client.post(
            "/v2/experiments/sessions", headers=self._headers(),
            data={"consent": json.dumps({**CONSENT, "researcher": True}),
                  "business_case": (io.BytesIO(_pdf(1)), "one.pdf")})
        self.assertEqual(one.status_code, 200)
        self.assertEqual(one.get_json()["business_case"]["name"], "one.pdf")
        slides = self.client.post(
            "/v2/experiments/sessions", headers=self._headers(),
            data={"consent": json.dumps(CONSENT),
                  "business_case": (io.BytesIO(b"slides"), "deck.pptx")})
        self.assertEqual(slides.status_code, 200)
        blob = json.dumps(self.store.tables)
        self.assertIn(ME, blob)  # the key row, and only that table
        for name, rows in self.store.tables.items():
            if name == "experiment_volunteer_keys":
                continue
            self.assertNotIn(ME, json.dumps(rows))

    def test_a_take_keeps_the_words_and_the_rating(self):
        session_id = self._session().get_json()["id"]
        bad = self._take(session_id, self_rating=json.dumps(
            {"energy": "medium", "feeling": "good"}))
        self.assertEqual(bad.status_code, 400)
        self.assertEqual(bad.get_json()["code"], "RATING")
        self.assertEqual(self.files.objects, {})
        made = self._take(session_id)
        self.assertEqual(made.status_code, 200, made.get_json())
        body = made.get_json()
        self.assertEqual(body["transcript"], "cześć")
        self.assertEqual(body["words"][0]["start"], 0.2)
        self.assertEqual(body["tag"], "baseline_calm")
        self.assertEqual(body["self_rating"], {"energy": "low", "feeling": "good"})
        self.assertNotIn(ME, json.dumps(body))
        self.assertEqual(self.heard, ME)
        self.assertEqual(len(self.files.objects), 1)
        self.choices["sensitive_information"] = False
        refused = self._take(session_id)
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(len(self.files.objects), 1)

    def test_analyze_take_queues_the_model_and_hides_locked_scores(self):
        session_id = self._session().get_json()["id"]
        self.store.tables["experiment_sessions"][0]["business_case_text"] = "The case."
        take_id = self._take(session_id).get_json()["id"]
        queued = self.client.post(
            "/v2/experiments/analyze-take", headers=self._headers(),
            json={"take_id": take_id, "model_id": "wpl_arousal@0.1"})
        self.assertEqual(queued.status_code, 202, queued.get_json())
        self.assertEqual(queued.get_json()["status"], "queued")
        self.assertEqual(queued.get_json()["model_id"], "wpl_arousal@0.2")
        self.assertEqual(self.model.calls[0]["transcript"], "cześć")
        self.assertEqual(self.model.calls[0]["business_case"], "The case.")
        self.assertEqual(self.model.calls[0]["prompt_tag"], "baseline_calm")
        self.assertEqual(len(self.model.built), 64)
        self.assertNotEqual(self.model.built, ME)
        shown = self.client.get(
            f"/v2/experiments/takes/{take_id}/analysis", headers=self._headers())
        self.assertEqual(shown.status_code, 200, shown.get_json())
        body = shown.get_json()
        self.assertEqual(body["schema"], "analyze-take/v0.1")
        self.assertEqual(body["model_id"], "wpl_arousal@0.2")
        self.assertEqual(body["intervention"], [])
        for step in ("engagement", "arousal", "valence", "clarity"):
            self.assertIsInstance(body["takes"][0]["summary"][step]["unlocked"], bool)
        self.assertNotIn("score_if_unlocked", json.dumps(body))
        stored = self.store.tables["experiment_takes"][0]["analysis"]
        self.assertIn("score_if_unlocked", json.dumps(stored))
        for word in FEELING_WORDS:
            self.assertNotIn(word, json.dumps(body).lower())
        self.who = OTHER
        hidden = self.client.get(
            f"/v2/experiments/takes/{take_id}/analysis", headers=self._headers())
        self.assertEqual(hidden.status_code, 404)
        self.who = ME
        self.client.delete("/v2/experiments/me", headers=self._headers())
        self.assertEqual(self.store.tables.get("experiment_volunteer_baselines"), [])

    def test_a_take_without_a_calm_baseline_is_not_queued(self):
        session_id = self._session().get_json()["id"]
        take_id = self._take(
            session_id, prompt_id="p1", tag="positive").get_json()["id"]
        refused = self.client.post(
            "/v2/experiments/analyze-take", headers=self._headers(),
            json={"take_id": take_id})
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(refused.get_json()["code"], "NO_BASELINE")
        self.assertEqual(self.model.calls, [])

    def test_a_model_is_the_callers_and_a_chat_keeps_the_hosts_choice(self):
        listed = self.client.get("/v2/experiments/models", headers=self._headers())
        self.assertEqual(listed.status_code, 200, listed.get_json())
        builtin = listed.get_json()["models"][0]
        self.assertEqual(builtin["id"], "wpl_arousal@0.2")
        self.assertEqual(builtin["version"], "0.2")
        self.assertEqual(builtin["name"], "Voice and words")
        self.assertNotIn("arousal", builtin["name"].lower())
        self.assertEqual(builtin["source"], "built_in")
        self.assertEqual(builtin["research_only"], True)
        self.assertEqual(builtin["steps"], ["engagement", "arousal", "valence", "clarity"])
        self.assertEqual(builtin["baseline_prompt_ids"], ["b1", "b2", "b3"])
        self.assertIn("how clear it was", builtin["measures"])
        made = self.client.post("/v2/experiments/models", headers=self._headers(), json={
            "name": "Mine", "base_model_id": "wpl_arousal@0.1",
            "measures": "A short line about the four steps.",
            "baseline_prompt_ids": ["b1"],
            "interventions": [{
                "name": "Join in", "text": "Say one more sentence.", "step": "engagement",
                "threshold": 0.0, "grid": [{"step": "engagement", "cue": "loudness", "value": 0.1}],
            }],
        })
        self.assertEqual(made.status_code, 200, made.get_json())
        model_id = made.get_json()["id"]
        self.assertEqual(made.get_json()["source"], "user")
        session_id = self._session().get_json()["id"]
        take_id = self._take(session_id).get_json()["id"]
        unknown = self.client.post("/v2/experiments/analyze-take", headers=self._headers(),
                                   json={"take_id": take_id, "model_id": "missing"})
        self.assertEqual(unknown.status_code, 404)
        queued = self.client.post("/v2/experiments/analyze-take", headers=self._headers(),
                                  json={"take_id": take_id, "model_id": model_id})
        self.assertEqual(queued.status_code, 202, queued.get_json())
        shown = self.client.get(f"/v2/experiments/takes/{take_id}/analysis",
                                headers=self._headers()).get_json()
        self.assertEqual(shown["model_id"], model_id)
        self.assertEqual(shown["intervention"], [{
            "id": shown["intervention"][0]["id"],
            "name": "Join in",
            "text": "Say one more sentence.",
            "step": "engagement",
            "score": shown["intervention"][0]["score"],
        }])
        self.assertGreater(shown["intervention"][0]["score"], 0)
        self.who = OTHER
        hidden = self.client.get("/v2/experiments/models", headers=self._headers()).get_json()
        self.assertEqual([row["id"] for row in hidden["models"]], ["wpl_arousal@0.2"])
        self.assertEqual(self.client.delete(
            f"/v2/experiments/models/{model_id}", headers=self._headers()).status_code, 404)
        self.who = ME
        self.assertEqual(self.client.delete(
            f"/v2/experiments/models/{model_id}", headers=self._headers()).status_code, 200)

    def test_the_host_sets_the_chat_model_and_reads_taught_answers(self):
        saved = self.client.put("/v2/chats/own-abc/experiment-config", headers=self._headers(), json={
            "model_id": "wpl_arousal@0.1", "baseline_prompt_ids": ["b1", "b2"],
        })
        self.assertEqual(saved.status_code, 200, saved.get_json())
        body = saved.get_json()
        self.assertEqual(body["model_id"], "wpl_arousal@0.2")
        self.assertEqual(body["needs_baseline"], True)
        self.assertEqual([prompt["id"] for prompt in body["baseline_prompts"]], ["b1", "b2"])
        self.assertIn("poranek", body["baseline_prompts"][0]["text"])
        self.who = OTHER
        self.assertEqual(self.client.put(
            "/v2/chats/own-abc/experiment-config", headers=self._headers(),
            json={"model_id": "wpl_arousal@0.1"}).status_code, 200)
        # own-abc is each caller's own builder chat. A shared thread is the host's.
        self.who = ME
        thread = "33333333-3333-4333-8333-333333333333"
        self.store.table("chat_threads").insert({
            "id": thread, "kind": "customer", "title": "Host", "widget_owner_id": ME,
        }).execute()
        self.store.table("chat_members").insert([
            {"thread_id": thread, "user_id": ME},
            {"thread_id": thread, "user_id": OTHER},
        ]).execute()
        self.store.table("chat_reply_examples").insert([
            {"host_id": ME, "chat_id": thread, "ask": "First?", "answer": "Yes."},
            {"host_id": ME, "chat_id": thread, "ask": "Second?", "answer": "No."},
        ]).execute()
        self.who = OTHER
        seen = self.client.get(f"/v2/chats/{thread}/experiment-config", headers=self._headers())
        self.assertEqual(seen.status_code, 200, seen.get_json())
        self.assertEqual(seen.get_json()["baseline_prompt_ids"], ["b1", "b2"])
        self._refused_as_guest(thread)
        self.who = ME
        page = self.client.get(
            f"/v2/chats/{thread}/reply-examples?limit=1&offset=0", headers=self._headers())
        self.assertEqual(page.status_code, 200, page.get_json())
        payload = page.get_json()
        self.assertEqual(payload["count"], 2)
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["kind"], "text")
        self.assertEqual(payload["items"][0]["question"], payload["items"][0]["prompt"])
        self.assertIn(payload["items"][0]["answer"], ("Yes.", "No."))

    def test_a_member_is_not_the_host_without_an_owner(self):
        thread = "44444444-4444-4444-8444-444444444444"
        self.store.table("chat_threads").insert(
            {"id": thread, "kind": "team", "title": "No owner"}).execute()
        self.store.table("chat_members").insert([
            {"thread_id": thread, "user_id": ME},
            {"thread_id": thread, "user_id": OTHER},
        ]).execute()
        for who in (ME, OTHER):
            self.who = who
            self._refused_as_guest(thread)

    def test_a_member_is_refused_when_someone_else_is_host(self):
        thread = "55555555-5555-4555-8555-555555555555"
        link = "66666666-6666-4666-8666-666666666666"
        self.store.table("chat_links").insert({"id": link, "user_id": ME}).execute()
        self.store.table("chat_threads").insert({
            "id": thread, "kind": "customer", "title": "Link", "link_id": link,
        }).execute()
        self.store.table("chat_members").insert([
            {"thread_id": thread, "user_id": ME},
            {"thread_id": thread, "user_id": OTHER},
        ]).execute()
        self.who = OTHER
        self._refused_as_guest(thread)
        missing = "77777777-7777-4777-8777-777777777777"
        stranger = "88888888-8888-4888-8888-888888888888"
        for chat_id, who in ((missing, ME), (thread, stranger)):
            self.who = who
            put = self.client.put(
                f"/v2/chats/{chat_id}/experiment-config", headers=self._headers(),
                json={"model_id": "wpl_arousal@0.2"})
            examples = self.client.get(
                f"/v2/chats/{chat_id}/reply-examples", headers=self._headers())
            self.assertEqual(put.status_code, 404, put.get_json())
            self.assertEqual(put.get_json()["code"], "NOT_FOUND")
            self.assertEqual(examples.status_code, 404)
            self.assertEqual(examples.get_json()["code"], "NOT_FOUND")

    def test_prompts_import_the_polish_set_and_stay_mine(self):
        imported = self.client.post(
            "/v2/experiments/prompts/import", headers=self._headers())
        self.assertEqual(imported.status_code, 200, imported.get_json())
        prompts = imported.get_json()["prompts"]
        self.assertEqual(len(prompts), 14)
        nephew = next(prompt for prompt in prompts if prompt["id"] == "k1")
        self.assertIn("bratankowi", nephew["text"])
        again = self.client.post("/v2/experiments/prompts/import", headers=self._headers())
        self.assertEqual(len(again.get_json()["prompts"]), 14)
        listed = self.client.get("/v2/experiments/prompts", headers=self._headers()).get_json()
        self.assertEqual(len(listed["prompts"]), 14)
        created = self.client.post(
            "/v2/experiments/prompts", headers=self._headers(),
            json={"id": "mine", "tag": "positive", "text": "Moje zdanie."})
        self.assertEqual(created.status_code, 200)
        changed = self.client.put(
            "/v2/experiments/prompts/mine", headers=self._headers(),
            json={"tag": "positive", "text": "Inne zdanie."})
        self.assertEqual(changed.get_json()["text"], "Inne zdanie.")
        self.who = OTHER
        stolen = self.client.delete("/v2/experiments/prompts/mine", headers=self._headers())
        self.assertEqual(stolen.status_code, 404)
        self.who = ME
        gone = self.client.delete("/v2/experiments/prompts/mine", headers=self._headers())
        self.assertEqual(gone.status_code, 200)
        ids = [prompt["id"] for prompt in self.client.get(
            "/v2/experiments/prompts", headers=self._headers()).get_json()["prompts"]]
        self.assertNotIn("mine", ids)
        self.assertIn("k1", ids)

    def test_interventions_are_picked_for_the_coaching_context(self):
        made = self.client.post(
            "/v2/experiments/interventions", headers=self._headers(),
            json={"grid": {"engagement": {"verbal": 1.0, "vocal": 1.0}},
                  "threshold": 0.5, "rule": {"step": "engagement"}})
        self.assertEqual(made.status_code, 200, made.get_json())
        late = self.client.post(
            "/v2/experiments/interventions", headers=self._headers(),
            json={"grid": {"clarity": {"verbal": 1.0, "vocal": 1.0}},
                  "threshold": 0.5, "rule": {"step": "clarity"}})
        self.assertEqual(late.status_code, 200)
        grid = {
            step: {"verbal": {"value": 1.0, "reference": "baseline"},
                   "vocal": {"value": 1.0, "reference": "baseline"}}
            for step in load_prompt_set()["order"]
        }
        context = coaching_context(db, ME, {"start": 0.0, "end": 1.0, "grid": grid})
        self.assertEqual(context["order"], load_prompt_set()["order"])
        self.assertEqual([row["step"] for row in context["fired"]], ["engagement", "clarity"])
        self.assertNotIn("emotion", json.dumps(context))
        self.who = OTHER
        listed = self.client.get(
            "/v2/experiments/interventions", headers=self._headers()).get_json()
        self.assertEqual(listed["interventions"], [])

    def test_export_is_only_mine_and_researcher_needs_consent(self):
        session_id = self._session().get_json()["id"]
        self._take(session_id)
        missing = self.client.get("/v2/experiments/export", headers=self._headers())
        self.assertEqual(missing.status_code, 400)
        own = self.client.get(
            "/v2/experiments/export?format=json", headers=self._headers())
        self.assertEqual(own.status_code, 200)
        payload = own.get_json()
        self.assertEqual(payload["takes"][0]["transcript"], "cześć")
        self.assertNotIn(ME, json.dumps(payload))
        blocked = self.client.get(
            "/v2/experiments/export?format=json&audience=researcher",
            headers=self._headers())
        self.assertEqual(blocked.status_code, 403)
        self._session({"participant": True, "researcher": True, "version": "experiments-v1"})
        opened = self.client.get(
            "/v2/experiments/export?format=csv&audience=researcher",
            headers=self._headers())
        self.assertEqual(opened.status_code, 200)
        self.assertIn("cześć", opened.get_data(as_text=True))
        self.assertNotIn(ME, opened.get_data(as_text=True))
        self.who = OTHER
        theirs = self.client.get(
            "/v2/experiments/export?format=json", headers=self._headers())
        self.assertEqual(theirs.get_json()["takes"], [])

    def test_delete_me_removes_my_rows_and_files(self):
        session_id = self._session().get_json()["id"]
        self._take(session_id)
        self.client.post("/v2/experiments/prompts/import", headers=self._headers())
        self.assertTrue(self.files.objects)
        gone = self.client.delete("/v2/experiments/me", headers=self._headers())
        self.assertEqual(gone.status_code, 200)
        self.assertEqual(self.files.objects, {})
        self.assertEqual(self.store.tables.get("experiment_sessions"), [])
        self.assertEqual(self.store.tables.get("experiment_takes"), [])
        self.assertEqual(self.store.tables.get("experiment_prompts"), [])
        self.assertEqual(self.store.tables.get("experiment_volunteer_keys"), [])
        self.who = OTHER
        session_id = self._session().get_json()["id"]
        self._take(session_id)
        kept = dict(self.files.objects)
        self.who = ME
        self.client.delete("/v2/experiments/me", headers=self._headers())
        self.assertEqual(self.files.objects, kept)

    def test_a_take_that_is_too_big_is_refused_before_whisper(self):
        session_id = self._session().get_json()["id"]
        with patch("services.experiments.too_big", return_value=True):
            refused = self._take(session_id)
        self.assertEqual(refused.status_code, 413)
        self.assertFalse(hasattr(self, "heard"))


if __name__ == "__main__":
    unittest.main()
