"""willab — the Community Content Studio (founder 2026-07-26).

One button in the Journal CMS turns a blog post into the three derived
community formats. Pinned here, token by token:

  C-1  the content model actually reaches the model (the strategy file is
       loaded and the six pillars are in the system prompt).
  C-2  the user prompt carries title/excerpt/body, the requested formats and
       the founder's steer — and truncates a book-length body.
  C-3  cleaning: markdown stripped, caps re-enforced, unknown/duplicate
       formats dropped, a bogus pillar becomes None rather than a guess.
  C-4  the AC-9 construct guard FLAGS a body, it never drops it — a founder
       reviewing a flagged draft beats a draft that silently vanished.
  C-5  the fabrication guard: a claim or number the source essay does not
       make raises "verify"; one the essay does make does not.
  C-6  generate_community_posts returns None on every failure path and never
       raises into the route.
  C-7  a SINGLE-format regenerate inherits the week's framing from a sibling
       instead of re-theming the other two.
  C-8  routes: the CMS password gate, the flag, the input contract.
  C-9  the fences — community drafts never reach a public route, and no F1
       assembly module may depend on this marketing surface (L1).

Run: python3 -m unittest test_community_content
"""
from __future__ import annotations

import sys
import types
import unittest
from unittest.mock import MagicMock, patch

# services.db pulls in supabase — stub in setUpModule, RESTORE the saved
# original in tearDownModule (willab test-stub-isolation convention: a bare
# pop leaves a second DatabaseService singleton behind and silently breaks
# other modules' patches).
_ORIG_SERVICES_DB = None


def setUpModule():
    global _ORIG_SERVICES_DB
    _ORIG_SERVICES_DB = sys.modules.get("services.db")
    stub = types.ModuleType("services.db")
    stub.db = MagicMock()
    sys.modules["services.db"] = stub


def tearDownModule():
    if _ORIG_SERVICES_DB is not None:
        sys.modules["services.db"] = _ORIG_SERVICES_DB
    else:
        sys.modules.pop("services.db", None)


from services import community_content as cc  # noqa: E402

try:
    from flask import Flask
    from routes import journal as jroutes
    _IMPORT_ERROR = None
except Exception as e:  # pragma: no cover
    Flask = None
    jroutes = None
    _IMPORT_ERROR = e

PW = "s3cret-pw"
PID = "11111111-1111-4111-8111-111111111111"
IID = "22222222-2222-4222-8222-222222222222"

ESSAY = (
    "The re-entry note is how I get back into deep work after an "
    "interruption.\n\nBefore you step away, write one line about what you "
    "were about to do next. Coming back, you read the line instead of "
    "re-reading everything."
)


def _post(**over):
    row = {"id": PID, "title": "The Re-Entry Note",
           "excerpt": "Get back in without re-reading everything.",
           "body": ESSAY}
    row.update(over)
    return row


def _model_output(**over):
    out = {
        "pillar_id": 1,
        "pillar_name": "Focus & attention",
        "theme": "The Re-Entry Note",
        "posts": [
            {"format": "myth_bust", "title": "Myth: momentum is fragile",
             "body": "Myth: once you are interrupted the session is gone."},
            {"format": "fear", "title": "The part I do not admit",
             "body": "I am afraid the thread is gone for good. Are you?"},
            {"format": "win", "title": "Your turn",
             "body": "Share the last note that got you back in."},
        ],
        "soft_cta_line": "",
        "app_proof_line": "This started as a voice note.",
    }
    out.update(over)
    return out


# ── C-1 the content model reaches the model ───────────────────────────────

class StrategyTests(unittest.TestCase):

    def setUp(self):
        cc._strategy_cache = None

    def tearDown(self):
        cc._strategy_cache = None

    def test_strategy_file_loads_and_is_not_empty(self):
        self.assertTrue(len(cc.load_strategy()) > 500)

    def test_system_prompt_carries_all_six_pillars(self):
        prompt = cc.build_system_prompt()
        for pillar in ("Focus & attention", "Mental load & capture",
                       "Social energy & presence", "Starting & momentum",
                       "Letting go & self-compassion",
                       "Communicating clearly"):
            self.assertIn(pillar, prompt)

    def test_system_prompt_carries_the_hard_rules(self):
        prompt = cc.build_system_prompt()
        self.assertIn("Never introduce a fact", prompt)
        self.assertIn("SAME LANGUAGE", prompt)

    def test_missing_strategy_file_yields_an_empty_system_prompt(self):
        # No content model ⇒ refuse, rather than generate generic slop under
        # the founder's name.
        with patch.object(cc, "load_strategy", return_value=""):
            self.assertEqual(cc.build_system_prompt(), "")


# ── C-2 the user prompt ───────────────────────────────────────────────────

class UserPromptTests(unittest.TestCase):

    def test_carries_the_source_and_the_requested_formats(self):
        out = cc.build_user_prompt(_post(), formats=("fear",),
                                   notes="lean on the freeze")
        self.assertIn("The Re-Entry Note", out)
        self.assertIn("re-reading everything", out)
        self.assertIn("Fear", out)
        self.assertIn("lean on the freeze", out)
        self.assertIn("Return exactly 1 post(s)", out)

    def test_a_book_length_body_is_truncated(self):
        out = cc.build_user_prompt(_post(body="x" * 50_000))
        self.assertLess(len(out), cc._MAX_SOURCE_CHARS + 2_000)
        self.assertIn("…", out)

    def test_unknown_formats_fall_back_to_all_three(self):
        out = cc.build_user_prompt(_post(), formats=("nonsense",))
        self.assertIn("Return exactly 3 post(s)", out)

    def test_non_dict_post_does_not_raise(self):
        self.assertIsInstance(cc.build_user_prompt(None), str)


# ── C-3 cleaning ──────────────────────────────────────────────────────────

class CleanPayloadTests(unittest.TestCase):

    def test_happy_path(self):
        out = cc._clean_payload(_model_output(), ESSAY)
        self.assertEqual(len(out["posts"]), 3)
        self.assertEqual(out["pillar_id"], 1)
        self.assertEqual(out["theme"], "The Re-Entry Note")
        self.assertEqual(out["posts"][0]["char_count"],
                         len(out["posts"][0]["body"]))

    def test_markdown_is_stripped(self):
        raw = _model_output()
        raw["posts"][0]["body"] = "## Heading\n**bold** and __under__"
        out = cc._clean_payload(raw, ESSAY)
        body = out["posts"][0]["body"]
        for marker in ("**", "__", "#"):
            self.assertNotIn(marker, body)

    def test_empty_bodies_and_unknown_formats_are_dropped(self):
        raw = _model_output(posts=[
            {"format": "myth_bust", "title": "t", "body": "   "},
            {"format": "sonnet", "title": "t", "body": "real text"},
            {"format": "win", "title": "t", "body": "kept"},
        ])
        out = cc._clean_payload(raw, ESSAY)
        self.assertEqual([p["format"] for p in out["posts"]], ["win"])

    def test_duplicate_formats_are_deduped(self):
        raw = _model_output(posts=[
            {"format": "fear", "title": "a", "body": "first"},
            {"format": "fear", "title": "b", "body": "second"},
        ])
        out = cc._clean_payload(raw, ESSAY)
        self.assertEqual(len(out["posts"]), 1)
        self.assertEqual(out["posts"][0]["body"], "first")

    def test_formats_outside_the_request_are_dropped(self):
        # A single-format reroll must not quietly rewrite its siblings.
        out = cc._clean_payload(_model_output(), ESSAY, wanted=("fear",))
        self.assertEqual([p["format"] for p in out["posts"]], ["fear"])

    def test_caps_are_re_enforced_in_code(self):
        raw = _model_output(posts=[
            {"format": "win", "title": "T" * 400, "body": "b" * 5_000},
        ], soft_cta_line="s" * 900)
        out = cc._clean_payload(raw, ESSAY)
        self.assertEqual(len(out["posts"][0]["title"]), cc._MAX_TITLE_LEN)
        self.assertEqual(len(out["posts"][0]["body"]), cc._MAX_BODY_LEN)
        self.assertEqual(len(out["soft_cta_line"]), cc._MAX_LINE_LEN)

    def test_a_bogus_pillar_becomes_none_not_a_guess(self):
        for bad in (0, 7, "one", None, True):
            out = cc._clean_payload(_model_output(pillar_id=bad), ESSAY)
            self.assertIsNone(out["pillar_id"], repr(bad))
            self.assertEqual(out["pillar_name"], "")

    def test_nothing_usable_returns_none(self):
        self.assertIsNone(cc._clean_payload({"posts": []}, ESSAY))
        self.assertIsNone(cc._clean_payload("not a dict", ESSAY))
        self.assertIsNone(cc._clean_payload(None, ESSAY))


# ── C-4 the AC-9 construct guard ──────────────────────────────────────────

class ConstructGuardTests(unittest.TestCase):

    def test_construct_vocabulary_is_flagged_not_dropped(self):
        raw = _model_output(posts=[
            {"format": "fear", "title": "t",
             "body": "Your charisma score says otherwise."},
        ])
        out = cc._clean_payload(raw, ESSAY)
        self.assertEqual(len(out["posts"]), 1, "the draft must survive")
        self.assertIn("construct", out["posts"][0]["flags"])

    def test_clean_copy_carries_no_construct_flag(self):
        out = cc._clean_payload(_model_output(), ESSAY)
        for post in out["posts"]:
            self.assertNotIn("construct", post["flags"])


# ── C-5 the fabrication guard ─────────────────────────────────────────────

class FabricationGuardTests(unittest.TestCase):

    def test_a_study_the_essay_never_cited_is_flagged(self):
        flags = cc._guard_flags(
            "A 2019 study at Stanford found this works.", ESSAY)
        self.assertIn("verify", flags)

    def test_a_number_the_essay_does_use_is_not_flagged(self):
        source = "Write 1 line before you step away."
        self.assertNotIn("verify", cc._guard_flags("Write 1 line.", source))

    def test_a_number_the_essay_never_uses_is_flagged(self):
        self.assertIn("verify", cc._guard_flags("It takes 23 minutes.", ESSAY))

    def test_research_wording_the_essay_shares_is_not_flagged(self):
        source = "The research on task-switching is clear."
        self.assertNotIn("verify",
                         cc._guard_flags("The research is clear.", source))

    def test_plain_copy_is_unflagged(self):
        self.assertEqual(cc._guard_flags("Write the line. Then walk away.",
                                         ESSAY), [])


# ── C-6 the call never raises ─────────────────────────────────────────────

class GenerateTests(unittest.TestCase):

    def test_empty_body_returns_none_without_calling_the_model(self):
        with patch.object(cc, "build_system_prompt") as sysp:
            self.assertIsNone(cc.generate_community_posts(_post(body="  ")))
            sysp.assert_not_called()

    def test_missing_content_model_returns_none(self):
        with patch.object(cc, "build_system_prompt", return_value=""):
            self.assertIsNone(cc.generate_community_posts(_post()))

    def test_llm_returning_nothing_returns_none(self):
        stub = types.ModuleType("services.llm")
        stub.chat_complete = lambda **kw: None
        with patch.dict(sys.modules, {"services.llm": stub}):
            self.assertIsNone(cc.generate_community_posts(_post()))

    def test_llm_raising_returns_none(self):
        def boom(**kw):
            raise RuntimeError("openai down")
        stub = types.ModuleType("services.llm")
        stub.chat_complete = boom
        with patch.dict(sys.modules, {"services.llm": stub}):
            self.assertIsNone(cc.generate_community_posts(_post()))

    def test_malformed_json_returns_none(self):
        stub = types.ModuleType("services.llm")
        stub.chat_complete = lambda **kw: types.SimpleNamespace(
            parsed=None, text="{not json")
        with patch.dict(sys.modules, {"services.llm": stub}):
            self.assertIsNone(cc.generate_community_posts(_post()))

    def test_happy_path_stamps_the_model(self):
        stub = types.ModuleType("services.llm")
        stub.chat_complete = lambda **kw: types.SimpleNamespace(
            parsed=_model_output(), text="")
        with patch.dict(sys.modules, {"services.llm": stub}):
            out = cc.generate_community_posts(_post())
        self.assertEqual(len(out["posts"]), 3)
        self.assertTrue(out["model"])
        self.assertTrue(out["generated_at"])


# ── C-7 a single-format reroll inherits the week's framing ────────────────

class RowsForUpsertTests(unittest.TestCase):

    def test_full_run_uses_the_fresh_batch_fields(self):
        rows = cc.rows_for_upsert(PID, cc._clean_payload(_model_output(),
                                                         ESSAY))
        self.assertEqual(len(rows), 3)
        self.assertTrue(all(r["theme"] == "The Re-Entry Note" for r in rows))
        self.assertTrue(all(r["journal_post_id"] == PID for r in rows))

    def test_single_format_reroll_inherits_pillar_theme_and_lines(self):
        payload = cc._clean_payload(
            _model_output(pillar_id=5, pillar_name="Letting go",
                          theme="A DIFFERENT WEEK",
                          app_proof_line="a different line",
                          posts=[{"format": "fear", "title": "t",
                                  "body": "new fear body"}]),
            ESSAY, wanted=("fear",))
        sibling = {"pillar_id": 1, "pillar_name": "Focus & attention",
                   "theme": "The Re-Entry Note", "soft_cta_line": "",
                   "app_proof_line": "This started as a voice note."}
        rows = cc.rows_for_upsert(PID, payload, inherit=sibling)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["body"], "new fear body")
        # the week's framing survives the reroll
        self.assertEqual(rows[0]["theme"], "The Re-Entry Note")
        self.assertEqual(rows[0]["pillar_id"], 1)
        self.assertEqual(rows[0]["app_proof_line"],
                         "This started as a voice note.")


class SerializeTests(unittest.TestCase):

    def test_labels_and_days_come_from_the_cadence(self):
        out = cc.serialize_community_item(
            {"id": IID, "kind": "fear", "body": "abc", "flags": []})
        self.assertEqual((out["label"], out["day"]), ("Fear", "Tue"))
        self.assertEqual(out["char_count"], 3)

    def test_flags_survive_a_json_string_column(self):
        out = cc.serialize_community_item(
            {"id": IID, "kind": "win", "body": "x", "flags": '["verify"]'})
        self.assertEqual(out["flags"], ["verify"])

    def test_never_serializes_a_publishable_field(self):
        out = cc.serialize_community_item(
            {"id": IID, "kind": "win", "body": "x", "slug": "leaked",
             "status": "published", "published_at": "2026-01-01"})
        for banned in ("slug", "status", "published_at"):
            self.assertNotIn(banned, out)


# ── C-8 the routes ────────────────────────────────────────────────────────

class _FakeDb:
    """Records calls; returns canned rows."""

    def __init__(self, post=None, items=None, written=None, item=None,
                 updated=None):
        self.post = post
        self.items = items if items is not None else []
        self.written = written
        self.item = item
        self.updated = updated
        self.calls = []

    def get_journal_post_by_id(self, pid):
        self.calls.append(("by_id", pid))
        return self.post

    def list_journal_community_posts(self, pid=None):
        self.calls.append(("list", pid))
        return self.items

    def upsert_journal_community_posts(self, pid, rows):
        self.calls.append(("upsert", pid, rows))
        return self.written if self.written is not None else rows

    def get_journal_community_post(self, iid):
        self.calls.append(("get_item", iid))
        return self.item

    def update_journal_community_post(self, iid, changes):
        self.calls.append(("update_item", iid, changes))
        return self.updated

    def delete_journal_community_post(self, iid):
        self.calls.append(("delete_item", iid))
        return True


def _row(**over):
    row = {"id": IID, "journal_post_id": PID, "kind": "fear",
           "title": "t", "body": "b", "flags": [], "pillar_id": 1,
           "pillar_name": "Focus & attention", "theme": "The Re-Entry Note",
           "soft_cta_line": "", "app_proof_line": "line"}
    row.update(over)
    return row


@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class CommunityRouteTests(unittest.TestCase):

    def setUp(self):
        self.app = Flask(__name__)

    def _call(self, fn, body, pw=PW, flag=True):
        with self.app.test_request_context(json=body):
            with patch.object(jroutes.config, "JOURNAL_ADMIN_PASSWORD", pw), \
                    patch.object(jroutes.config, "COMMUNITY_CONTENT_ENABLED",
                                 flag):
                out = fn()
                resp, status = out if isinstance(out, tuple) else (out, 200)
                return resp.get_json(), status

    # -- the gate ---------------------------------------------------------

    def test_every_route_401s_on_a_wrong_password(self):
        for fn in (jroutes.journal_community_generate,
                   jroutes.journal_community_list,
                   jroutes.journal_community_update,
                   jroutes.journal_community_delete):
            _, status = self._call(fn, {"password": "nope", "id": IID,
                                        "post_id": PID})
            self.assertEqual(status, 401, fn.__name__)

    def test_every_route_503s_when_the_password_is_unconfigured(self):
        for fn in (jroutes.journal_community_generate,
                   jroutes.journal_community_list,
                   jroutes.journal_community_update,
                   jroutes.journal_community_delete):
            _, status = self._call(fn, {"password": "", "id": IID,
                                        "post_id": PID}, pw="")
            self.assertEqual(status, 503, fn.__name__)

    def test_generate_503s_when_the_flag_is_off(self):
        with patch.object(jroutes, "db", _FakeDb(post=_post())):
            body, status = self._call(jroutes.journal_community_generate,
                                      {"password": PW, "post_id": PID},
                                      flag=False)
        self.assertEqual(status, 503)
        self.assertEqual(body["code"], "DISABLED")

    def test_the_flag_does_not_disable_reading_existing_drafts(self):
        with patch.object(jroutes, "db", _FakeDb(items=[_row()])):
            body, status = self._call(jroutes.journal_community_list,
                                      {"password": PW}, flag=False)
        self.assertEqual(status, 200)
        self.assertEqual(len(body["items"]), 1)

    # -- the input contract ------------------------------------------------

    def test_generate_needs_a_post_id(self):
        with patch.object(jroutes, "db", _FakeDb()):
            _, status = self._call(jroutes.journal_community_generate,
                                   {"password": PW})
        self.assertEqual(status, 400)

    def test_generate_rejects_a_bad_formats_list(self):
        for bad in ([], ["sonnet"], "fear", {}, [1]):
            with patch.object(jroutes, "db", _FakeDb(post=_post())):
                _, status = self._call(
                    jroutes.journal_community_generate,
                    {"password": PW, "post_id": PID, "formats": bad})
            self.assertEqual(status, 400, repr(bad))

    def test_generate_404s_on_an_unknown_post(self):
        with patch.object(jroutes, "db", _FakeDb(post=None)):
            _, status = self._call(jroutes.journal_community_generate,
                                   {"password": PW, "post_id": PID})
        self.assertEqual(status, 404)

    def test_generate_400s_when_the_post_has_no_body(self):
        with patch.object(jroutes, "db", _FakeDb(post=_post(body="  "))):
            body, status = self._call(jroutes.journal_community_generate,
                                      {"password": PW, "post_id": PID})
        self.assertEqual(status, 400)
        self.assertIn("nothing to derive", body["error"])

    # -- generation --------------------------------------------------------

    def test_generate_happy_path_returns_the_full_current_set(self):
        fake = _FakeDb(post=_post(), items=[_row(kind=k) for k in cc.FORMATS])
        payload = cc._clean_payload(_model_output(), ESSAY)
        with patch.object(jroutes, "db", fake), \
                patch.object(cc, "generate_community_posts",
                             return_value=payload):
            body, status = self._call(jroutes.journal_community_generate,
                                      {"password": PW, "post_id": PID})
        self.assertEqual(status, 200)
        self.assertEqual(len(body["items"]), 3)
        self.assertEqual({i["kind"] for i in body["items"]}, set(cc.FORMATS))

    def test_generate_503s_when_the_model_gives_nothing(self):
        with patch.object(jroutes, "db", _FakeDb(post=_post())), \
                patch.object(cc, "generate_community_posts",
                             return_value=None):
            _, status = self._call(jroutes.journal_community_generate,
                                   {"password": PW, "post_id": PID})
        self.assertEqual(status, 503)

    def test_generate_500s_when_the_save_fails(self):
        fake = _FakeDb(post=_post(), written=[])
        payload = cc._clean_payload(_model_output(), ESSAY)
        with patch.object(jroutes, "db", fake), \
                patch.object(cc, "generate_community_posts",
                             return_value=payload):
            _, status = self._call(jroutes.journal_community_generate,
                                   {"password": PW, "post_id": PID})
        self.assertEqual(status, 500)

    def test_single_format_reroll_inherits_from_a_sibling(self):
        # Only `fear` is regenerated; the surviving `win` row carries the
        # week's framing and the written row must adopt it.
        sibling = _row(kind="win", theme="The Re-Entry Note", pillar_id=1)
        fake = _FakeDb(post=_post(), items=[sibling])
        payload = cc._clean_payload(
            _model_output(theme="A DIFFERENT WEEK", pillar_id=5,
                          posts=[{"format": "fear", "title": "t",
                                  "body": "new"}]),
            ESSAY, wanted=("fear",))
        with patch.object(jroutes, "db", fake), \
                patch.object(cc, "generate_community_posts",
                             return_value=payload):
            _, status = self._call(
                jroutes.journal_community_generate,
                {"password": PW, "post_id": PID, "formats": ["fear"]})
        self.assertEqual(status, 200)
        wrote = [c for c in fake.calls if c[0] == "upsert"][0][2]
        self.assertEqual(len(wrote), 1)
        self.assertEqual(wrote[0]["theme"], "The Re-Entry Note")
        self.assertEqual(wrote[0]["pillar_id"], 1)

    # -- update / delete ---------------------------------------------------

    def test_update_writes_only_title_and_body_and_clears_flags(self):
        fake = _FakeDb(item=_row(), updated=_row(title="Edited"))
        with patch.object(jroutes, "db", fake):
            _, status = self._call(
                jroutes.journal_community_update,
                {"password": PW, "id": IID, "title": "Edited",
                 "kind": "win", "journal_post_id": "elsewhere"})
        self.assertEqual(status, 200)
        wrote = [c for c in fake.calls if c[0] == "update_item"][0][2]
        self.assertEqual(set(wrote), {"title", "flags"})
        self.assertEqual(wrote["flags"], [])

    def test_update_404s_on_an_unknown_item(self):
        with patch.object(jroutes, "db", _FakeDb(item=None)):
            _, status = self._call(jroutes.journal_community_update,
                                   {"password": PW, "id": IID, "body": "x"})
        self.assertEqual(status, 404)

    def test_update_needs_an_id_and_at_least_one_field(self):
        with patch.object(jroutes, "db", _FakeDb(item=_row())):
            _, no_id = self._call(jroutes.journal_community_update,
                                  {"password": PW, "body": "x"})
            _, no_fields = self._call(jroutes.journal_community_update,
                                      {"password": PW, "id": IID})
        self.assertEqual((no_id, no_fields), (400, 400))

    def test_delete(self):
        with patch.object(jroutes, "db", _FakeDb()):
            body, status = self._call(jroutes.journal_community_delete,
                                      {"password": PW, "id": IID})
        self.assertEqual((status, body["deleted"]), (200, True))


# ── C-9 the fences ────────────────────────────────────────────────────────

@unittest.skipIf(_IMPORT_ERROR is not None, f"needs app deps: {_IMPORT_ERROR}")
class FenceTests(unittest.TestCase):
    """Community drafts are a marketing surface: unreachable from the public
    site, and invisible to the F1 assembly path."""

    def test_no_public_journal_route_reads_the_community_table(self):
        import inspect
        src = inspect.getsource(jroutes)
        public = src.split("# ── ADMIN")[0]
        for banned in ("journal_community_post", "community_content"):
            self.assertNotIn(
                banned, public,
                "the PUBLIC journal section must never touch community drafts")

    def test_community_items_carry_no_publishable_fields(self):
        # Structural: there is no slug/status/published_at to serve, so a
        # community draft cannot be rendered as an article.
        out = cc.serialize_community_item(_row())
        for banned in ("slug", "status", "published_at", "sort_order"):
            self.assertNotIn(banned, out)

    def test_l1_no_assembly_module_imports_this_surface(self):
        import inspect
        import importlib
        for name in ("services.best_presentation", "services.ideal_text_block",
                     "services.ideal_text_report",
                     "services.cross_take_selection",
                     "services.charisma_snippet_service"):
            try:
                mod = importlib.import_module(name)
            except Exception:  # pragma: no cover - optional deps
                continue
            self.assertNotIn(
                "community_content", inspect.getsource(mod),
                f"{name} must not depend on the marketing surface (L1)")

    def test_the_service_names_nothing_from_the_loop(self):
        import inspect
        src = inspect.getsource(cc)
        for banned in ("best_presentation", "ideal_text", "charisma_snippets",
                       "lab_recording", "power_score", "delivery_stars"):
            self.assertNotIn(banned, src)

    def test_no_scores_reach_a_community_payload(self):
        import json
        raw = json.dumps(cc.serialize_community_item(_row()))
        for banned in ("power_score", "charisma", "overall_score", "threat"):
            self.assertNotIn(banned, raw)


if __name__ == "__main__":
    unittest.main()
