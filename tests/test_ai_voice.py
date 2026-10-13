"""The AI version of your voice (founder lock 2026-10-12, N71): the
contracts a speaker and the founder care about.

  * one problem is picked, by severity against the speaker's own usual,
    or none when every signal is weak;
  * the provider is only called in the voice Exercise lane, once per
    practice, within the limits;
  * a clip that fails its check is never shown;
  * the request keeps the speaker's words;
  * deleting removes the voice at the provider and every clip, safely twice.

No real audio and no real provider: synthetic numbers, a fake provider and
an in-memory table store.
"""
from __future__ import annotations

import contextlib
import uuid

import numpy as np
import pytest

from config import Config
from services import ai_voice_clip, ai_voice_clone, ai_voice_prompt, ai_voice_severity
from services import ai_voice_store as store
from services.elevenlabs_client import Speech, VoiceProviderError

OWNER = "11111111-1111-1111-1111-111111111111"
SENTENCE = "We think the timing matters because the window closes once incumbents match our price"


# ── an in-memory PostgREST stand-in: filters really filter ───────────────

class _Q:
    def __init__(self, store, name):
        self.s, self.name, self.filters, self.op, self.body = store, name, [], "select", None
        self._limit, self._order = None, None

    def select(self, *_a, **_k):
        return self

    def eq(self, c, v):
        self.filters.append(lambda r: str(r.get(c)) == str(v))
        return self

    def gte(self, c, v):
        self.filters.append(lambda r: str(r.get(c) or "") >= str(v))
        return self

    def gt(self, c, v):
        self.filters.append(lambda r: (r.get(c) or 0) > v)
        return self

    def order(self, c, desc=False):
        self._order = (c, desc)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def insert(self, row):
        self.op, self.body = "insert", row
        return self

    def update(self, row):
        self.op, self.body = "update", row
        return self

    def upsert(self, row, on_conflict=None):
        self.op, self.body, self.key = "upsert", row, on_conflict
        return self

    def execute(self):
        rows = self.s.setdefault(self.name, [])
        if self.op == "insert":
            key = "practice_id" if self.name == "ai_voice_cycles" else "owner_user_id"
            if any(str(r.get(key)) == str(self.body.get(key)) for r in rows):
                raise RuntimeError("duplicate key")
            row = {"id": str(uuid.uuid4()), "created_at": "2026-10-12T10:00:00+00:00",
                   "generation_attempts": 0, "enabled": True, "status": "pending",
                   "plays": 0, **self.body}
            rows.append(row)
            return type("R", (), {"data": [row]})
        hits = [r for r in rows if all(f(r) for f in self.filters)]
        if self.op == "update":
            for r in hits:
                r.update(self.body)
            return type("R", (), {"data": hits})
        if self.op == "upsert":
            match = [r for r in rows if str(r.get(self.key)) == str(self.body.get(self.key))]
            if match:
                match[0].update(self.body)
                return type("R", (), {"data": match})
            row = {"created_at": "2026-10-12T10:00:00+00:00", "enabled": True, **self.body}
            rows.append(row)
            return type("R", (), {"data": [row]})
        if self._order:
            hits = sorted(hits, key=lambda r: str(r.get(self._order[0]) or ""),
                          reverse=self._order[1])
        return type("R", (), {"data": hits[: self._limit] if self._limit else hits})


class _Client:
    def __init__(self):
        self.tables = {}

    def table(self, name):
        return _Q(self.tables, name)


class _Db:
    """The few app-database reads the pipeline makes, plus the table client."""

    def __init__(self, practice, snippet, take):
        self.client = _Client()
        self.practice, self.snippet, self.take = practice, snippet, take

    def get_confident_voice_practice(self, *_a):
        return self.practice

    def get_snippet_by_id(self, *_a):
        return self.snippet

    def get_snippets_by_session(self, *_a):
        return self.take

    def get_active_diagnostic_exercise(self, *_a):
        return {"acoustic_problem_tags": ["rushing"],
                "matching_criteria": {"primary_problem_tag": "rushing"}}


def _snip(wpm, pause_ratio=0.15, dynamic_db=28.0):
    return {"metrics": {"wpm": wpm, "pause_ratio": pause_ratio, "dynamic_db": dynamic_db},
            "duration_ms": 2600, "transcript": SENTENCE}


TAKE = [_snip(150), _snip(152), _snip(148), _snip(151)]


def _practice(kind="moment", fit=None, video=None):
    return {"id": str(uuid.uuid4()), "kind": kind, "take_session_id": str(uuid.uuid4()),
            "snippet_id": str(uuid.uuid4()), "exact_passage": SENTENCE,
            "exercise_id": "x", "exercise_snapshot": {"explanation_video_url": video},
            "machine_assessment": {"exercise_fit": fit}}


@contextlib.contextmanager
def _on(**extra):
    saved = {k: getattr(Config, k) for k in (
        "AI_VOICE_ENABLED", "AI_VOICE_ALLOWLIST", "AI_VOICE_EXPLORE_SHARE",
        "ELEVENLABS_API_KEY", *extra)}
    Config.AI_VOICE_ENABLED, Config.AI_VOICE_ALLOWLIST = True, frozenset()
    Config.ELEVENLABS_API_KEY = "test-key-not-real"
    Config.AI_VOICE_EXPLORE_SHARE = 0.0
    for k, v in extra.items():
        setattr(Config, k, v)
    try:
        yield
    finally:
        for k, v in saved.items():
            setattr(Config, k, v)


class _Voices:
    def __init__(self, fail=None):
        self.spoken, self.deleted, self.fail = 0, [], fail

    def speak(self, **_k):
        self.spoken += 1
        if self.fail:
            raise self.fail
        return Speech(b"mp3", "audio/mpeg", "req", 90)

    def delete_voice(self, *, owner_key, voice_id):
        if self.fail:
            raise self.fail
        self.deleted.append(voice_id)

    def create_voice(self, **_k):
        return "voice-abc"


def _pcm_with_pause(pause_at_s):
    """2.8 s of voiced tone with one silent gap at ``pause_at_s`` (0.5 s)."""
    sr = 16000
    t = np.arange(int(2.8 * sr)) / sr
    pcm = (0.2 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)
    a = int(pause_at_s * sr)
    pcm[a:a + sr // 2] = 0.0
    return pcm


def _heard(gap_before_target, phrase="match our price"):
    tokens, target = SENTENCE.split(), phrase.split()
    at = next(i for i in range(len(tokens)) if tokens[i:i + len(target)] == target)
    words, t = [], 0.0
    for i, w in enumerate(tokens):
        if i == at:
            t += gap_before_target
        words.append({"word": w, "start": t, "end": t + 0.15})
        t += 0.17
    return {"transcript": SENTENCE, "words": words}


def _ready_voice(db):
    db.client.tables.setdefault("ai_voice_clones", []).append(
        {"owner_user_id": OWNER, "status": "ready", "enabled": True,
         "provider_voice_id": "voice-abc", "created_at": "2026-10-11T00:00:00+00:00"})


def _run_pipeline(db, practice, voices, heard, pcm=None, objects=None):
    def put(key, audio):
        if objects is not None:
            objects[key] = audio
        return "bucket"
    return ai_voice_clip.ensure(db, practice, user_id=OWNER, principal_id="", run=lambda cid, p: ai_voice_clip.generate(
        cid, p, database=db, provider=voices, transcribe=lambda _a: heard,
        put_object=put, decode=lambda _a: pcm if pcm is not None else _pcm_with_pause(1.0),
        provider_usage={"used": 0}), sign=lambda b, k: f"https://signed/{k}")


# ── which one problem: severity against the speaker's own usual ──────────

@pytest.mark.parametrize("pause_ratio, picked", [
    (0.0915, None),     # severity just below 0.4: no exercise at all
    (0.09, "pause"),    # exactly 0.4: the line itself counts
    (0.08, "pause"),    # above it
])
def test_one_problem_is_picked_only_from_the_line_up(pause_ratio, picked):
    with _on():
        medians = ai_voice_severity.own_medians(TAKE)
        out = ai_voice_severity.select(_snip(150, pause_ratio=pause_ratio), medians,
                                       sentence=SENTENCE, seed="s")
        assert (out or {}).get("exercise") == picked
        if out:
            assert 0.0 <= out["severity"] <= 1.0 and out["target_phrase"]


def test_raw_units_are_never_compared_and_the_phrase_has_a_fallback():
    """168 words a minute is a big number and 0.05 a small one; on the
    speaker's own scale the missing pauses are the worse problem."""
    with _on():
        medians = ai_voice_severity.own_medians(TAKE)
        out = ai_voice_severity.select(_snip(168, pause_ratio=0.05), medians,
                                       sentence=SENTENCE, seed="s")
        scores = out["severity_scores"]
        assert out["exercise"] == "pause" and scores["pause"] > scores["pace"] > 0
    # No comma or joining word: the last third of the sentence.
    assert ai_voice_severity.target_phrase(
        "Our revenue grew twelve percent last quarter in Europe") == "quarter in Europe"


# ── the request keeps the words ───────────────────────────────────────────

@pytest.mark.parametrize("exercise", [
    {"exercise": "pace"},
    {"exercise": "pause", "target_phrase": "match our price"},
    {"exercise": "stress", "target_phrase": "match our price"},
])
def test_the_request_says_the_speakers_own_words(exercise):
    out = ai_voice_prompt.build(sentence=SENTENCE, exercise=exercise, practice_id="p")
    assert out["spoken_words"] == SENTENCE.lower().split()
    assert set(out["metadata"]["tags"]) <= ai_voice_prompt.ALLOWED_TAGS
    assert "speed" not in out["body"]["voice_settings"]  # not on Eleven v4


def test_no_clip_is_longer_than_the_limit():
    """Founder 2026-10-13: the whole sentence, at most 17 s. A sentence too
    long to say in that time is never sent; a longer clip fails its check."""
    with pytest.raises(ai_voice_prompt.PromptRejected):
        ai_voice_prompt.build(sentence=" ".join([SENTENCE] * 3), exercise={"exercise": "pace"},
                              practice_id="p")
    from services.ai_voice_validator import validate
    pcm = (0.2 * np.sin(2 * np.pi * 180 * np.arange(18 * 16000) / 16000)).astype(np.float32)
    out = validate(audio=b"x", transcription=None, spoken_words=SENTENCE.lower().split(),
                   exercise={"exercise": "pace"}, original_wpm=None,
                   original_duration_s=None, decode=lambda _a: pcm)
    assert "too_long" in out["failed_checks"] and not out["passed"]


# ── the lane, once, the limits ────────────────────────────────────────────

def test_a_rewrite_practice_never_calls_the_provider():
    with _on():
        db = _Db(_practice(kind="rewrite"), _snip(190), TAKE)
        voices = _Voices()
        out = ai_voice_clip.ensure(db, db.practice, user_id=OWNER, principal_id="",
                                   run=lambda *a: pytest.fail("generated in the rewrite lane"))
        assert out == {"demo": "none", "clip": None} and voices.spoken == 0


def test_a_clip_that_fails_its_check_is_never_shown():
    with _on():
        db = _Db(_practice(), _snip(150, pause_ratio=0.02), TAKE)
        _ready_voice(db)
        out = _run_pipeline(db, db.practice, _Voices(), _heard(0.0, "the window closes once"))
        assert out["clip"]["state"] == "unavailable" and out["clip"]["url"] is None
        assert db.client.tables["ai_voice_cycles"][0]["failure_kind"] == "validation"


def test_the_daily_limit_stops_the_provider_call():
    with _on(AI_VOICE_DAILY_CLIPS_PER_SPEAKER=0):
        db = _Db(_practice(), _snip(150, pause_ratio=0.02), TAKE)
        _ready_voice(db)
        voices = _Voices()
        _run_pipeline(db, db.practice, voices, _heard(0.55, "the window closes once"))
        assert voices.spoken == 0
        assert db.client.tables["ai_voice_cycles"][0]["failure_code"] == "speaker_daily"


def test_one_recording_makes_one_checked_clip_then_measures_the_next_try(monkeypatch):
    """The whole cycle with a fake provider: one exercise, one clip that
    passed its check, stored with what it was made from and how long each
    stage took, never made twice; then the next try's outcome."""
    seen = []
    real_update, real_claim = store.update_cycle, store.claim_cycle
    monkeypatch.setattr(store, "update_cycle", lambda d, c, f: (
        seen.append(f["status"]) if "status" in f else None, real_update(d, c, f))[1])
    monkeypatch.setattr(store, "claim_cycle", lambda d, c: (
        seen.append("analyzing"), real_claim(d, c))[1])
    with _on():
        db = _Db(_practice(), _snip(150, pause_ratio=0.02), TAKE)
        _ready_voice(db)
        voices = _Voices()
        out = _run_pipeline(db, db.practice, voices, _heard(0.55, "the window closes once"))
        assert out["demo"] == "ai_voice" and out["clip"]["state"] == "ready"
        assert "voice-abc" not in str(out) and "settings" not in str(out)
        assert seen == ["analyzing", "choosing_exercise", "generating", "validating", "completed"]
        cycle = db.client.tables["ai_voice_cycles"][0]
        assert cycle["exercise"] == "pause" and cycle["validation"]["passed"]
        assert {"reason", "severity_scores", "target_change", "generation_intent"} <= set(cycle["selection"])
        assert cycle["metrics_before"]["pause_ratio"] == 0.02
        assert {"choose_exercise", "generation", "validation", "store", "total",
                "since_request"} <= set(cycle["latency_ms"])
        assert (cycle["generation_attempts"], cycle["characters"]) == (1, 90)
        assert cycle["credits_estimated"] > 0
        # Asked again (a retry, a second screen): the same clip, no second generation.
        again = _run_pipeline(db, db.practice, voices, _heard(0.55, "the window closes once"))
        assert voices.spoken == 1 and again["clip"]["url"] == out["clip"]["url"]
        # The next try, on the one problem only.
        ai_voice_clip.note_attempts(db, db.practice, [
            {"attempt_index": 1, "duration_ms": 3000, "acoustic_metrics": {"pause_ratio": 0.15}}])
        assert cycle["outcome"] == "improved" and cycle["retried"]
        ai_voice_clip.note_attempts(db, db.practice, [
            {"attempt_index": 2, "duration_ms": 3000, "acoustic_metrics": {}}])
        assert cycle["outcome"] == "inconclusive"


# ── the voice, and deleting it ────────────────────────────────────────────

def test_after_delete_an_old_link_no_longer_serves_the_clip():
    """The link a speaker was given points at a stored object; Delete removes
    that object, so the old link has nothing behind it, and no new link is
    ever issued for the clip."""
    with _on():
        db = _Db(_practice(), _snip(150, pause_ratio=0.02), TAKE)
        _ready_voice(db)
        objects: dict = {}
        out = _run_pipeline(db, db.practice, _Voices(), _heard(0.55, "the window closes once"),
                            objects=objects)
        old = out["clip"]["url"]
        served = lambda url: objects.get(url.split("https://signed/", 1)[1])  # noqa: E731
        assert served(old) == b"mp3"
        ai_voice_clone.delete(db, OWNER, provider=_Voices(),
                              delete_clip_objects=lambda key, *_a: objects.pop(key))
        assert served(old) is None
        cycle = db.client.tables["ai_voice_cycles"][0]
        after = ai_voice_clip.state(db, db.practice, cycle, sign=lambda b, k: f"https://signed/{k}")
        assert after["clip"]["url"] is None and after["demo"] != "ai_voice"
        assert all(cycle[k] is None for k in ("storage_key", "prepared_text",
                                              "generation_metadata", "validation"))
        ai_voice_clip.note_play(db, db.practice["id"])
        assert cycle["plays"] == 0


def test_account_deletion_removes_the_voice_before_the_account_is_blocked():
    """Once the account is blocked the provider permit is refused, so the AI
    voice must go first (routes/v2/processing_authorization.py)."""
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / "routes/v2/processing_authorization.py").read_text()
    route = source[source.index("def v2_processing_terminate"):]
    assert route.index("erase_on_termination(") < route.index("request_account_deletion(")

def test_delete_removes_the_voice_and_clips_and_is_safe_twice():
    with _on():
        db = _Db(_practice(), _snip(150, pause_ratio=0.02), TAKE)
        _ready_voice(db)
        _run_pipeline(db, db.practice, _Voices(), _heard(0.55, "the window closes once"))
        voices, removed = _Voices(), []
        out = ai_voice_clone.delete(db, OWNER, provider=voices,
                                    delete_clip_objects=lambda *a: removed.append(a))
        assert out == {"state": "off"} and voices.deleted == ["voice-abc"] and len(removed) == 1
        assert ai_voice_clone.card_state(db, OWNER)["state"] == "off"
        assert ai_voice_clone.delete(db, OWNER, provider=voices) == {"state": "off"}
        # A provider that can't confirm is reported, never hidden.
        _ready_voice(db)
        db.client.tables["ai_voice_clones"][0].update(provider_voice_id="voice-abc")
        failing = _Voices(fail=VoiceProviderError("outage"))
        assert ai_voice_clone.delete(db, OWNER, provider=failing)["state"] == "deleting"
