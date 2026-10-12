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

import httpx
import numpy as np
import pytest

from config import Config
from services import ai_voice_clip, ai_voice_clone, ai_voice_prompt, ai_voice_severity
from services.ai_voice_validator import validate
from services.elevenlabs_client import ElevenLabsClient, Speech, VoiceProviderError

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
        "AI_VOICE_ENABLED", "AI_VOICE_ALLOWLIST", "AI_VOICE_EXPLORE_SHARE", *extra)}
    Config.AI_VOICE_ENABLED, Config.AI_VOICE_ALLOWLIST = True, frozenset({OWNER})
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


def _run_pipeline(db, practice, voices, heard, pcm=None):
    return ai_voice_clip.ensure(db, practice, user_id=OWNER, principal_id="", run=lambda cid, p: ai_voice_clip.generate(
        cid, p, database=db, provider=voices, transcribe=lambda _a: heard,
        put_object=lambda k, a: "bucket", decode=lambda _a: pcm if pcm is not None else _pcm_with_pause(1.0),
        provider_usage={"used": 0}), sign=lambda b, k: f"https://signed/{k}")


# ── which problem ─────────────────────────────────────────────────────────

def test_one_problem_by_severity_against_the_speakers_own_usual():
    medians = ai_voice_severity.own_medians(TAKE)
    fast = ai_voice_severity.select(_snip(190), medians, sentence=SENTENCE, seed="p1")
    assert fast["exercise"] == "pace" and fast["severity"] >= 0.4
    # Every signal at the speaker's own usual: no exercise at all.
    assert ai_voice_severity.select(_snip(150), medians, sentence=SENTENCE, seed="p1") is None


def test_severity_reaches_the_minimum_exactly_at_the_existing_pace_line():
    line = max(150.5 + 18.0, 150.5 * 1.12)  # the median of TAKE is 150.5
    assert ai_voice_severity.pace_severity(line, 150.5) == pytest.approx(0.4)
    assert ai_voice_severity.pace_severity(line - 1, 150.5) < 0.4


def test_units_are_never_compared_raw():
    # A big raw words-per-minute number loses to a stronger pause problem.
    medians = {"wpm": 150.0, "pause_ratio": 0.16, "dynamic_db": 28.0}
    pick = ai_voice_severity.select(_snip(172, pause_ratio=0.02), medians,
                                    sentence=SENTENCE, seed="p2")
    assert pick["exercise"] == "pause"
    assert pick["target_phrase"]


def test_an_exercise_that_did_not_help_twice_is_held_back():
    medians = {"wpm": 150.0, "pause_ratio": 0.16, "dynamic_db": 28.0}
    history = [{"exercise": "pause", "outcome": "similar"},
               {"exercise": "pause", "outcome": "worsened"}]
    pick = ai_voice_severity.select(_snip(178, pause_ratio=0.08), medians,
                                    sentence=SENTENCE, seed="p3", history=history)
    assert pick["exercise"] == "pace" and pick["held_back"] == ["pause"]


def test_the_main_point_is_the_last_clause():
    assert ai_voice_severity.target_phrase(SENTENCE) == "the window closes once"


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


def test_brackets_in_a_transcript_never_become_tags():
    out = ai_voice_prompt.build(sentence="[shouts] We grew fast this year", exercise={"exercise": "pace"},
                                practice_id="p")
    assert "[shouts]" not in out["prepared_text"]


# ── a clip is shown only when it passed ───────────────────────────────────

def test_a_pause_clip_passes_only_with_a_natural_pause_before_the_point():
    common = dict(audio=b"x", spoken_words=SENTENCE.lower().split(),
                  exercise={"exercise": "pause", "target_phrase": "match our price"},
                  original_wpm=170, original_duration_s=2.6)
    good = validate(transcription=_heard(0.55), decode=lambda _a: _pcm_with_pause(1.0), **common)
    assert good["passed"], good
    none = validate(transcription=_heard(0.0), decode=lambda _a: _pcm_with_pause(1.0), **common)
    assert not none["passed"] and "pause_length" in none["failed_checks"]


def test_changed_words_or_clipping_fail_the_check():
    loud = _pcm_with_pause(1.0)
    loud[:4000] = 1.0
    heard = _heard(0.55)
    heard["transcript"] = "We think the price is right"
    out = validate(audio=b"x", transcription=heard, decode=lambda _a: loud,
                   spoken_words=SENTENCE.lower().split(),
                   exercise={"exercise": "pause", "target_phrase": "match our price"},
                   original_wpm=170, original_duration_s=2.6)
    assert {"clipped", "words_changed"} <= set(out["failed_checks"])


# ── the lane, once, the limits ────────────────────────────────────────────

def test_a_rewrite_practice_never_calls_the_provider():
    with _on():
        db = _Db(_practice(kind="rewrite"), _snip(190), TAKE)
        voices = _Voices()
        out = ai_voice_clip.ensure(db, db.practice, user_id=OWNER, principal_id="",
                                   run=lambda *a: pytest.fail("generated in the rewrite lane"))
        assert out == {"demo": "none", "clip": None} and voices.spoken == 0


def test_the_voice_lane_makes_one_checked_clip_and_reuses_it():
    with _on():
        db = _Db(_practice(), _snip(150, pause_ratio=0.02), TAKE)
        _ready_voice(db)
        voices = _Voices()
        first = _run_pipeline(db, db.practice, voices, _heard(0.55, "the window closes once"))
        cycle = db.client.tables["ai_voice_cycles"][0]
        assert cycle["status"] == "completed", cycle
        assert first["demo"] == "ai_voice"  # no video: the clip takes its place
        again = _run_pipeline(db, db.practice, voices, _heard(0.55, "the window closes once"))
        assert voices.spoken == 1 and len(db.client.tables["ai_voice_cycles"]) == 1
        assert again["demo"] == "ai_voice"


def test_an_exact_video_for_the_same_problem_stays():
    with _on():
        db = _Db(_practice(kind="exercise", fit="exact", video="https://v"), _snip(190), TAKE)
        _ready_voice(db)
        selection = ai_voice_severity.select(_snip(190), ai_voice_severity.own_medians(TAKE),
                                             sentence=SENTENCE, seed="x")
        assert ai_voice_clip.demo_for(db, db.practice, selection) == "video"
        db.practice["machine_assessment"]["exercise_fit"] = "trial"
        assert ai_voice_clip.demo_for(db, db.practice, selection) == "ai_voice"


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


def test_nobody_outside_the_allowlist_gets_a_clip():
    db = _Db(_practice(), _snip(190), TAKE)
    out = ai_voice_clip.ensure(db, db.practice, user_id=OWNER, principal_id="",
                               run=lambda *a: pytest.fail("generated while off"))
    assert out["clip"] is None


# ── the voice, and deleting it ────────────────────────────────────────────

def test_a_noisy_take_makes_no_voice():
    flat = np.full(16000 * 60, 0.05, dtype=np.float32)
    sample, reason = ai_voice_clone.prepare_sample(b"x", decode=lambda _a: flat,
                                                   transcode=lambda _a: b"mp3")
    assert sample is None and reason == "too_noisy"


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


def test_a_provider_failure_on_delete_is_reported_not_hidden():
    with _on():
        db = _Db(_practice(), _snip(150), TAKE)
        _ready_voice(db)
        out = ai_voice_clone.delete(db, OWNER, provider=_Voices(fail=VoiceProviderError("outage")))
        assert out["state"] == "deleting"


# ── the provider's errors, by kind ────────────────────────────────────────

@pytest.mark.parametrize("status,body,kind,transient", [
    (401, {"detail": {"status": "invalid_api_key"}}, "invalid_key", False),
    (401, {"detail": {"status": "quota_exceeded"}}, "quota_exceeded", False),
    (429, {"detail": {"status": "too_many_concurrent_requests"}}, "rate_limited", True),
    (503, {}, "outage", True),
])
def test_provider_errors_are_named_and_only_transient_ones_retry(status, body, kind, transient):
    client = ElevenLabsClient(api_key="k" * 40, transport=httpx.MockTransport(
        lambda _r: httpx.Response(status, json=body)))
    with pytest.raises(VoiceProviderError) as caught:
        client.speak(voice_id="v", body={"text": "hi"})
    assert caught.value.kind == kind and caught.value.transient is transient


def test_a_missing_key_never_calls_out():
    with pytest.raises(VoiceProviderError) as caught:
        ElevenLabsClient(api_key="").speak(voice_id="v", body={})
    assert caught.value.kind == "missing_key"
