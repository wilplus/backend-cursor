"""
STORY: The founder labels exact examples from Takes and Training Corpus in one private pattern library.
OUTCOME: Hear the clip before seeing cues, preserve multiple observations and save each match independently of retry outcomes.
PROVES: test_labels_stay_blind_until_saved, test_error_and_praise_can_coexist_with_distinct_matches,
    test_pattern_routes_require_founder, test_source_gate_rechecks_exact_cohort_and_language,
    test_removed_sources_are_hidden_from_the_library, test_corpus_observation_cannot_store_a_retry,
    test_a_shaped_fix_keeps_its_words_pace_and_pauses, test_the_rewrite_is_the_kept_one_else_made_once.
"""
from unittest.mock import Mock, patch

import pytest
from flask import Flask

from services import speaking_patterns
from services.refusal import Refusal

TAKE = "00000000-0000-4000-8000-000000000010"
SNIP = "00000000-0000-4000-8000-000000000020"
EXAMPLE = "00000000-0000-4000-8000-000000000030"
MOMENT = {"id": SNIP, "duration_ms": 5000, "metrics": {"wpm": 176, "private_read": 30}}
PATH = f"/v2/user/speaking-patterns/corpus/{TAKE}/{SNIP}"
OBSERVATION = {"kind": "error", "pattern": "Rushed ending", "start_ms": 3500, "end_ms": 5000, "note": "Last phrase."}


@pytest.fixture()
def client():
    import auth
    from routes.v2 import register_domains
    from routes.v2.blueprint import v2_bp

    register_domains()
    app = Flask(__name__)
    app.register_blueprint(v2_bp, url_prefix="/v2")
    with (patch.object(auth, "verify_supabase_token", return_value={"sub": "curator", "email": "curator@example.com"}),
          patch("routes.admin._token_email", return_value="curator@example.com"),
          patch("routes.admin.is_founder_email", return_value=True),
          patch("routes.admin.is_admin", return_value=True)):
        yield app.test_client()


def test_labels_stay_blind_until_saved():
    database = Mock()
    query = database.client.table.return_value.select.return_value
    query.eq.return_value = query
    query.order.return_value = query
    response = query.execute
    response.return_value.data = []
    assert speaking_patterns.clip_examples(database, "curator", "corpus", TAKE, MOMENT)["cues"] == {}
    response.return_value.data = [OBSERVATION]
    assert speaking_patterns.clip_examples(database, "curator", "corpus", TAKE, MOMENT)["cues"] == {"wpm": 176}


def test_error_and_praise_can_coexist_with_distinct_matches():
    database = Mock()
    praise = {"kind": "praise", "pattern": "Clear, concise point", "start_ms": 0, "end_ms": 3500}
    for observation in (OBSERVATION, praise):
        speaking_patterns.save_observation(database, "curator", "corpus", TAKE, MOMENT, observation)
    inserts = [call.args[0] for call in database.client.table.return_value.insert.call_args_list]
    assert [(row["kind"], row["start_ms"], row["end_ms"]) for row in inserts] == [
        ("error", 3500, 5000), ("praise", 0, 3500),
    ]
    assert all(row["snippet_id"] == SNIP and row["source"] == "corpus" for row in inserts)
    sniper = {"tool": "sniper", "name": "Slow the ending", "status": "draft"}
    sniper["values"] = {"pause_ms": 500}
    assert speaking_patterns.intervention({"intervention": sniper}, "error")["values"] == {"pause_ms": 500}
    with pytest.raises(Refusal, match="INVALID_MATCH"):
        speaking_patterns.intervention({"intervention": {**sniper, "values": {"pause_ms": -1}}}, "error")
    with pytest.raises(Refusal, match="INVALID_MATCH"):
        speaking_patterns.intervention({"intervention": sniper}, "praise")
    playback = {"tool": "play_strength", "name": "Listen to that point", "status": "approved"}
    assert speaking_patterns.intervention({"intervention": playback}, "praise")["status"] == "approved"


def test_pattern_routes_require_founder(client):
    headers = {"Authorization": "Bearer test"}
    assert client.get(PATH).status_code == 401
    with patch("routes.admin.is_founder_email", return_value=False):
        assert client.get(PATH, headers=headers).status_code == 403
        assert client.get("/v2/user/speaking-patterns", headers=headers).status_code == 403


def test_source_gate_rechecks_exact_cohort_and_language(client):
    imported = {"id": TAKE, "intake_context": {}}
    headers = {"Authorization": "Bearer test"}
    from routes.v2 import speaking_patterns as routes
    with (patch.object(routes, "queued_corpus_clip", return_value=(MOMENT, imported)) as clip,
          patch("routes.v2.coach._rater_language_outcome", return_value=("matched", "pl")) as language,
          patch.object(speaking_patterns, "clip_examples", return_value={"examples": [], "cues": {}}) as load):
        assert client.get(PATH, headers=headers).status_code == 200
        imported["intake_context"]["archived_at"] = "2026-11-25"
        assert client.get(PATH, headers=headers).status_code == 404
        imported["intake_context"].clear()
        assert client.get(PATH.replace(TAKE, EXAMPLE), headers=headers).status_code == 404
        language.return_value = ("mismatch", "en")
        assert client.get(PATH, headers=headers).status_code == 404
        clip.return_value = (None, None)
        assert client.get(PATH, headers=headers).status_code == 404
        load.assert_called_once()


def test_removed_sources_are_hidden_from_the_library(client):
    from routes.v2 import speaking_patterns as routes
    from services.speaking_patterns import PAGE_SIZE
    row = {"source": "corpus", "session_id": TAKE, "snippet_id": SNIP}
    with (patch.object(speaking_patterns, "page", return_value=[row] * PAGE_SIZE),
          patch.object(routes, "_source_moment", side_effect=Refusal("NOT_FOUND", status=404)) as authorize):
        response = client.get("/v2/user/speaking-patterns", headers={"Authorization": "Bearer test"})
        assert response.get_json() == {"examples": [], "next_offset": PAGE_SIZE}
        assert authorize.call_count == 1
        assert response.headers["Cache-Control"] == "private, no-store"


def test_corpus_observation_cannot_store_a_retry(client):
    from routes.v2 import speaking_patterns as routes
    with patch.object(routes, "_source_moment", return_value=MOMENT):
        response = client.post(PATH, headers={"Authorization": "Bearer test"},
                               json={**OBSERVATION, "retry_cues": {"wpm": 123}})
        assert response.status_code == 400
    with pytest.raises(Refusal, match="INVALID_MATCH"):
        speaking_patterns.intervention({"intervention": {"retry_outcome": "improved"}}, "error")


def test_a_shaped_fix_keeps_its_words_pace_and_pauses():
    sniper = {"tool": "sniper", "name": "Sniper", "status": "approved", "marks": {"speed": 0.8, "pauses": [4, 2, 4]}}
    assert speaking_patterns.intervention({"intervention": sniper}, "error")["marks"] == {"speed": 0.8, "pauses": [2, 4]}
    for bad in ({"speed": 3}, {"pauses": [-1]}, {"pauses": list(range(40))}, {"tempo": 1}):
        with pytest.raises(Refusal, match="INVALID_MATCH"):
            speaking_patterns.intervention({"intervention": {**sniper, "marks": bad}}, "error")
    rewrite = {"tool": "rewrite", "name": "Rephrase", "status": "approved",
               "text": "We start in March.", "suggested": "We begin in March."}
    kept = speaking_patterns.intervention({"intervention": rewrite}, "error")
    assert (kept["text"], kept["suggested"]) == ("We start in March.", "We begin in March.")


def test_the_rewrite_is_the_kept_one_else_made_once():
    clip = {"transcript": "um so we start maybe in March", "say_it_stronger": {"rewrite_your_voice": "We start in March."}}
    with patch("services.say_it_stronger.generate_say_it_stronger") as made:
        assert speaking_patterns.rewrite_for(clip) == "We start in March."
        made.assert_not_called()
        made.return_value = {"rewrite_your_voice": "So we start in March."}
        assert speaking_patterns.rewrite_for({"transcript": "um so we start in March"}) == "So we start in March."
        assert speaking_patterns.rewrite_for({"transcript": "  "}) is None
        assert made.call_count == 1
