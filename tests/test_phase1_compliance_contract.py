"""
STORY    As the founder, I want retired constructs, demographic inputs and
         direct provider calls kept out of the code, and exercise routes behind
         the purpose gate, so that the Phase-1 legal boundary holds.
OUTCOME
  O1  The power score takes no retired direction/breakthrough input, and the
      active coaching document carries no retired construct copy.
  O2  Universal voice confidence has no demographic input.
  O3  The protected user-data modules import no provider client (a lint: it
      reads source text).
  O4  Every personalised-exercise route, speaker and coach, answers 410
      PURPOSE_NOT_OPERATIONAL while the purpose is off.
PROVES   O1 -> test_power_score_has_no_retired_direction_inputs
            -> test_active_coaching_document_has_no_retired_construct_copy
         O2 -> test_universal_voice_confidence_has_no_demographic_runtime_contract
         O3 -> test_protected_user_data_modules_do_not_import_provider_client
         O4 -> test_every_exercise_route_refuses_while_the_purpose_is_off
WHY      ED-PLF-1.3 Phase-1 boundary (add_phase1_processing_boundary.sql;
         0335 moved the exercise purpose to phase 1 behind its registry row).
"""
from __future__ import annotations

import ast
import re
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def _function_args(path: str, function_name: str) -> set[str]:
    tree = ast.parse((ROOT / path).read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                and node.name == function_name:
            return {argument.arg for argument in (
                node.args.posonlyargs + node.args.args + node.args.kwonlyargs
            )}
    raise AssertionError(f"{function_name} not found")


def test_power_score_has_no_retired_direction_inputs():
    args = _function_args("services/power_phrase_ranking.py", "power_score")
    assert "direction" not in args
    assert "breakthrough" not in args
    source = (ROOT / "services" / "power_phrase_ranking.py").read_text()
    assert "_DIRECTION_TERM" not in source
    assert "_W_D" not in source
    assert "_W_B" not in source


def test_active_coaching_document_has_no_retired_construct_copy():
    from services.master_doc_rag import MASTER_DOCUMENT

    active_copy = MASTER_DOCUMENT.lower()
    assert "threat" not in active_copy
    assert "breakthrough" not in active_copy


def test_universal_voice_confidence_has_no_demographic_runtime_contract():
    source = (ROOT / "services" / "voice_confidence.py").read_text()
    tree = ast.parse(source)
    identifiers = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    identifiers |= {
        node.arg for node in ast.walk(tree) if isinstance(node, ast.arg)
    }
    for retired in (
        "sex", "gender", "profile_sex", "sex_source",
        "male", "female", "speaker_sex",
    ):
        assert retired not in identifiers


def test_protected_user_data_modules_do_not_import_provider_client():
    protected = (
        "services/analysis_worker.py",
        "services/recording_transcription.py",
        "services/recording_piece_analysis.py",
        "services/slide_selection.py",
        "services/coach_comment_drafter.py",
        "services/master_doc_rag.py",
        "services/moment_suggestions.py",
        "routes/v2/lab_recording.py",
        "routes/v2/projects.py",
        "routes/v2/coach.py",
    )
    for relative in protected:
        source = (ROOT / relative).read_text()
        assert "services.openai_service" not in source, relative
        assert "from openai" not in source, relative
        assert "import openai" not in source, relative


#: The personalised-exercise routes, by path: every speaker practice route
#: and the coach's practice and exercise-request routes. A new route under
#: these paths is held to the gate without being listed.
_EXERCISE_ROUTES = re.compile(
    r"^/v2/user/(confidence-practice/|snippets/<snippet_id>/"
    r"(confidence-practice|exercise-rendered)$)"
    r"|^/v2/coach/sessions/<session_id>/snippets/<snippet_id>/"
    r"(confidence-practice|practice-judgement|exercise-request(/draft)?)$")


def test_every_exercise_route_refuses_while_the_purpose_is_off():
    import flask

    from routes.v2 import register_domains
    from routes.v2.blueprint import v2_bp
    from services import processing_purposes

    register_domains()
    app = flask.Flask(__name__)
    app.register_blueprint(v2_bp, url_prefix="/v2")
    answered = {}
    with mock.patch.object(processing_purposes, "purpose_is_operational",
                           lambda *_a, **_k: False):
        for rule in app.url_map.iter_rules():
            if not _EXERCISE_ROUTES.search(rule.rule):
                continue
            # Peel only the auth decorator; the purpose gate sits under it.
            gated = app.view_functions[rule.endpoint].__wrapped__
            args = {name: "00000000-0000-4000-8000-000000000000"
                    for name in rule.arguments}
            for method in sorted(rule.methods - {"HEAD", "OPTIONS"}):
                with app.test_request_context(rule.rule, method=method, json={}):
                    flask.request.user_id = "speaker-1"
                    body, status = gated(**args)
                answered[f"{method} {rule.rule}"] = (status, body.get_json()["code"])
    assert len(answered) >= 15, answered
    assert {k: v for k, v in answered.items()
            if v != (410, "PURPOSE_NOT_OPERATIONAL")} == {}
