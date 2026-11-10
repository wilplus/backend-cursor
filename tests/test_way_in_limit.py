"""
STORY    As a newcomer waiting for my first Take, I want Will's chat to keep
         answering while the app checks every few seconds what is due, so
         that the way in never stops with "too many requests" in the wait.
OUTCOME
  L1  The way in's poll (no answer, no audio) is not counted against the
      model's limit: more polls than that limit allows in a minute all
      pass, under the poll's own, higher limit.
  L2  An answer, which may call the model, is still counted against it.
PROVES   L1, L2 -> test_polls_pass_the_models_limit_and_answers_do_not
WHY      The app polls POST /v2/plan/way-in every 5 s while Take 1 waits
         (N572, N592); under the model's 400 per hour it got 429s after
         about half an hour (coordinator's end-to-end review, 9 Nov 2026).
"""
import pytest
from flask import Flask, jsonify

from services import rate_limits as R


@pytest.fixture
def client(monkeypatch):
    if isinstance(R.limiter, R._NullLimiter):
        pytest.skip("flask_limiter is not installed")
    monkeypatch.setenv("RATE_LIMIT_LLM", "3 per minute")
    monkeypatch.setenv("RATE_LIMIT_POLL", "10 per minute")
    monkeypatch.setenv("RATE_LIMIT_STORAGE_URI", "memory://")
    monkeypatch.setenv("RATE_LIMIT_ENABLED", "1")
    app = Flask(__name__)

    @app.route("/way-in", methods=["POST"])
    @R.poll_limit
    @R.answering_llm_limit
    def way_in():
        return jsonify({"ok": True})

    was = getattr(R.limiter, "initialized", None)
    R.limiter.initialized = False
    R.init_app(app)
    yield app.test_client()
    if was is not None:
        R.limiter.initialized = was


def test_polls_pass_the_models_limit_and_answers_do_not(client):
    polls = [client.post("/way-in", json={"chat": "artur"}).status_code for _ in range(6)]
    assert polls == [200] * 6  # twice the model's 3 a minute
    answers = [client.post("/way-in", json={"answer": {"beat": "choice"}}).status_code
               for _ in range(4)]
    assert answers == [200, 200, 200, 429]  # the model's 3, then its limit
