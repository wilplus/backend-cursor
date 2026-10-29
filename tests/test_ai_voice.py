"""
STORY    As a speaker practising, I want an AI clip of my own voice saying my
         own words with one improvement, never shown if it fails its check,
         and fully deleted when I ask, so that I hear a believable better
         version and keep control of my voice.
OUTCOME
  O1  One problem is picked against my own usual (or the default), and the
      sentence under the clip names it in words, with no numbers.
  O2  The clip says my own words (or the clearer version I accepted, with
      the ums taken out), in at most 17 seconds.
  O3  A clip that fails its check is made once more with a new seed and
      is never shown; a try after it is not scored; a real pause heard in
      the audio passes.
  O4  One clip per practice, started early once the exercise is known,
      within my daily and monthly limits (3 and 20, N188), and a new voice
      only while the plan has a voice slot free; a voice still being made is waited for a
      few times only; my next try is measured on that one problem. My
      voice starts being made as my spoken Take is stored, beside its
      processing (N84), so the clip can be ready by the walk.
  O5  Delete removes my voice at the provider and every clip, old links
      stop working, and deleting twice is safe; closing my account
      removes the voice first.
  O6  A clip names its problem (pace, pause, stress, fillers or default)
      and the phrase it is made with as soon as they are chosen, ready or
      still being made; never a number (N120).
  O7  A praised moment's practice gets its clip too, started early like a
      corrected moment's (N122).
  O8  On a plan, the clip practises the level's own problem whenever my
      clip shows it; where it doesn't, the pick is as without a plan (G7,
      N209).
PROVES   O1 -> test_a_problem_from_the_line_up_else_the_default,
               test_raw_units_are_never_compared_and_the_phrase_has_a_fallback,
               test_the_sentence_under_the_clip_comes_from_the_transcript_and_their_own_numbers,
               test_a_clean_sentence_never_gets_the_fillers_clip
         O2 -> test_the_request_says_the_speakers_own_words,
               test_no_clip_is_longer_than_the_limit,
               test_a_clearer_version_practice_gets_a_clip_of_the_accepted_words,
               test_a_sentence_with_fillers_is_said_without_them_and_the_next_try_is_measured_on_them
         O3 -> test_a_clip_that_fails_its_check_is_made_once_more_and_shown_only_if_it_passes,
               test_a_pause_heard_in_the_audio_passes_when_the_words_hide_it
         O4 -> test_a_speakers_daily_or_monthly_limit_stops_the_provider_call,
               test_no_new_voice_while_the_plans_voice_slots_are_full,
               test_two_corrected_moments_queue_two_prewarms,
               test_one_recording_makes_one_checked_clip_then_measures_the_next_try,
               test_a_stored_bake_with_a_voice_exercise_queues_one_prewarm_once,
               test_the_bake_queues_the_offered_exercise_and_never_a_rewrite,
               test_prewarm_opens_the_practice_and_the_clip_and_skips_without_a_voice,
               test_a_voice_still_being_made_is_waited_for_a_bounded_number_of_times,
               test_a_spoken_takes_upload_starts_the_voice_and_a_read_take_or_guest_does_not
         O5 -> test_after_delete_an_old_link_no_longer_serves_the_clip,
               test_a_voice_already_gone_at_elevenlabs_counts_as_deleted,
               test_account_deletion_removes_the_voice_before_the_account_is_blocked,
               test_delete_removes_the_voice_and_clips_and_is_safe_twice
         O6 -> test_a_ready_clip_names_its_problem_and_phrase
         O7 -> test_a_praised_moments_practice_gets_a_clip
         O8 -> test_on_a_plan_the_clip_practises_the_levels_problem
WHY      Founder lock 2026-10-12 (N71); Never-rule 1 for the sentence under
         the clip; 2026-10-23 (N120, the short bubble; N122, "do we practice
         the confident moments? I think yes we should!").
"""
from __future__ import annotations

import contextlib
import re
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


def _practice(kind="plain", fit=None, video=None):
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
        self.spoken, self.deleted, self.fail, self.bodies = 0, [], fail, []

    def speak(self, **k):
        self.spoken += 1
        self.bodies.append(dict(k.get("body") or {}))
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


def _heard(gap_before_target, phrase="match our price", step=0.17):
    tokens, target = SENTENCE.split(), phrase.split()
    at = next(i for i in range(len(tokens)) if tokens[i:i + len(target)] == target)
    words, t = [], 0.0
    for i, w in enumerate(tokens):
        if i == at:
            t += gap_before_target
        words.append({"word": w, "start": t, "end": t + 0.15})
        t += step
    return {"transcript": SENTENCE, "words": words}


def _ready_voice(db):
    db.client.tables.setdefault("ai_voice_clones", []).append(
        {"owner_user_id": OWNER, "status": "ready", "enabled": True,
         "provider_voice_id": "voice-abc", "created_at": "2026-10-11T00:00:00+00:00"})


def _run_pipeline(db, practice, voices, heard, pcm=None, objects=None, decode=None):
    def put(key, audio):
        if objects is not None:
            objects[key] = audio
        return "bucket"
    return ai_voice_clip.ensure(db, practice, user_id=OWNER, principal_id="", run=lambda cid, p: ai_voice_clip.generate(
        cid, p, database=db, provider=voices, transcribe=lambda _a: heard,
        put_object=put, decode=decode or (lambda _a: pcm if pcm is not None else _pcm_with_pause(1.0)),
        provider_usage={"used": 0}), sign=lambda b, k: f"https://signed/{k}")


# ── which one problem: severity against the speaker's own usual ──────────

@pytest.mark.parametrize("pause_ratio, picked", [
    (0.0915, "stress"), # just below 0.4: the default, the main point stands out
    (0.09, "pause"),    # exactly 0.4: the line itself counts
    (0.08, "pause"),    # above it
])
def test_a_problem_from_the_line_up_else_the_default(pause_ratio, picked):
    with _on(AI_VOICE_MIN_SEVERITY=0.4):
        medians = ai_voice_severity.own_medians(TAKE)
        out = ai_voice_severity.select(_snip(150, pause_ratio=pause_ratio), medians,
                                       sentence=SENTENCE, seed="s")
        assert out["exercise"] == picked and out["default"] is (picked == "stress")
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


def test_on_a_plan_the_clip_practises_the_levels_problem():
    with _on():
        medians = ai_voice_severity.own_medians(TAKE)
        clip = _snip(168, pause_ratio=0.05)  # fewer pauses is the worse problem
        plain = ai_voice_severity.select(clip, medians, sentence=SENTENCE, seed="s")
        assert plain["exercise"] == "pause"
        paced = ai_voice_severity.select(clip, medians, sentence=SENTENCE, seed="s", prefer="pace")
        assert paced["exercise"] == "pace" and not paced["default"]
        # A level the clip doesn't show (its loudness range is its usual):
        # the pick as without a plan.
        level_off = ai_voice_severity.select(clip, medians, sentence=SENTENCE, seed="s",
                                             prefer="stress")
        assert level_off["exercise"] == "pause"


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

def test_a_clearer_version_practice_gets_a_clip_of_the_accepted_words():
    """Founder 2026-10-18, "words first, then voice": after a clearer-version
    try that is not yet, the AI voice says the words the speaker accepted,
    never the ones they said."""
    with _on():
        snippet = {**_snip(150, pause_ratio=0.02),
                   "transcript": "So um we think, uh, the timing kind of matters to us"}
        db = _Db(_practice(kind="rewrite"), snippet, TAKE)
        _ready_voice(db)
        voices = _Voices()
        out = _run_pipeline(db, db.practice, voices, _heard(0.55, "the window closes once"))
        assert out["clip"]["state"] == "ready" and voices.spoken == 1
        cycle = db.client.tables["ai_voice_cycles"][0]
        assert "incumbents match our price" in cycle["prepared_text"]
        assert "kind of" not in cycle["prepared_text"]


def _pcm_louder(start_s, end_s):
    """2.8 s of voiced tone, louder (about 8 dB) between the two times."""
    sr = 16000
    t = np.arange(int(2.8 * sr)) / sr
    pcm = (0.2 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)
    pcm[int(start_s * sr):int(end_s * sr)] *= 2.5
    return pcm


PHRASE = "the window closes once"


def _pcm_flat():
    """2.8 s of voiced tone at one level: nothing stands out."""
    sr = 16000
    t = np.arange(int(2.8 * sr)) / sr
    return (0.2 * np.sin(2 * np.pi * 180 * t)).astype(np.float32)


@pytest.mark.parametrize("second, shown", [
    (_pcm_louder(1.0, 1.7), "ready"),    # the second clip makes the phrase stand out
    (_pcm_flat(), "unavailable"),        # flat again: no clip, never a third
])
def test_a_clip_that_fails_its_check_is_made_once_more_and_shown_only_if_it_passes(second, shown):
    """Founder 2026-10-21 (N93): the stress clip of 2026-10-20 came out flat
    (0.02 dB) and, made only once, never came. A failed clip is made once
    more with a new seed; a failed one is never shown, and a try after a
    clip that never came is not scored."""
    with _on():
        db = _Db(_practice(), _snip(150, dynamic_db=10.0), TAKE)
        _ready_voice(db)
        voices, clips = _Voices(), iter([_pcm_flat(), second])
        out = _run_pipeline(db, db.practice, voices, _heard(0.0, PHRASE),
                            decode=lambda _a: next(clips))
        cycle = db.client.tables["ai_voice_cycles"][0]
        assert out["clip"]["state"] == shown and voices.spoken == 2
        assert voices.bodies[0]["seed"] != voices.bodies[1]["seed"]
        assert cycle["generation_attempts"] == 2
        if shown == "unavailable":
            assert out["clip"]["url"] is None
            assert (cycle["failure_kind"], cycle["failure_code"]) == ("validation", "not_stressed")
            ai_voice_clip.note_attempts(db, db.practice, [
                {"attempt_index": 1, "duration_ms": 3000, "acoustic_metrics": {"dynamic_db": 30.0}}])
            assert cycle.get("outcome") is None and not cycle.get("retried")


@pytest.mark.parametrize("own_numbers, heard, pcm, change, quotes", [
    # fewer pauses than their usual: the clip pauses before the main point
    (dict(wpm=150, pause_ratio=0.02), lambda: _heard(0.55, PHRASE), None, "pause", PHRASE),
    # faster than their usual: the clip is slower, and no words are quoted
    (dict(wpm=180), lambda: _heard(0.0, PHRASE, step=0.4), None, "pace", None),
    # flatter than their usual: the main point stands out
    (dict(wpm=150, dynamic_db=10.0), lambda: _heard(0.0, PHRASE), _pcm_louder(1.0, 1.7), "stress", PHRASE),
    # nothing reached the line: the default clip, and the sentence says so
    (dict(wpm=150), lambda: _heard(0.0, PHRASE), _pcm_louder(1.0, 1.7), "default", PHRASE),
])
def test_the_sentence_under_the_clip_comes_from_the_transcript_and_their_own_numbers(
        own_numbers, heard, pcm, change, quotes):
    """WIL-82 (founder 2026-10-16). A speaker's transcript and their own
    numbers go in; the sentence under the clip names the change that was
    measured against their usual and really heard in the clip, quotes only
    words cut from that transcript, and says nothing was off when nothing
    was. No number is in it."""
    with _on():
        db = _Db(_practice(), _snip(**own_numbers), TAKE)
        _ready_voice(db)
        out = _run_pipeline(db, db.practice, _Voices(), heard(), pcm=pcm)
        cycle = db.client.tables["ai_voice_cycles"][0]
        assert out["clip"]["state"] == "ready", cycle.get("failure_kind")
        why = out["clip"]["why"]
        assert why == ai_voice_clip.WHY[change].format(phrase=quotes or "")
        assert cycle["exercise"] == ("stress" if change == "default" else change)
        assert bool(cycle["selection"]["default"]) == (change == "default")
        if quotes:
            assert quotes in SENTENCE and cycle["selection"]["target_phrase"] == quotes
        assert not re.search(r"\d", why)

@pytest.mark.parametrize("limit, code", [
    ("AI_VOICE_DAILY_CLIPS_PER_SPEAKER", "speaker_daily"),
    ("AI_VOICE_MONTHLY_CLIPS_PER_SPEAKER", "speaker_monthly"),
])
def test_a_speakers_daily_or_monthly_limit_stops_the_provider_call(limit, code):
    """N188: 3 clips a day and 20 a month for each speaker, so no one speaker
    uses up the plan's month. A limit reached makes no provider call."""
    with _on(**{limit: 0}):
        db = _Db(_practice(), _snip(150, pause_ratio=0.02), TAKE)
        _ready_voice(db)
        voices = _Voices()
        _run_pipeline(db, db.practice, voices, _heard(0.55, "the window closes once"))
        assert voices.spoken == 0
        assert db.client.tables["ai_voice_cycles"][0]["failure_code"] == code


def test_no_new_voice_while_the_plans_voice_slots_are_full():
    """N188: each speaker's voice holds one of the plan's slots. With every
    slot held, no voice is asked of the provider; with one free, it is."""
    made = []

    class _Cloner(_Voices):
        def create_voice(self, **k):
            made.append(k.get("owner_key"))
            return super().create_voice(**k)

    def clone(db):
        return ai_voice_clone.run_clone(
            OWNER, "principal", str(uuid.uuid4()), str(uuid.uuid4()), "r2", "bucket", "key",
            database=db, provider=_Cloner(), read_audio=lambda: b"audio",
            prepare=lambda audio: (audio, None))

    with _on(AI_VOICE_VOICE_SLOTS=2):
        full = _Db(_practice(), _snip(150), TAKE)
        full.client.tables["ai_voice_clones"] = [
            {"owner_user_id": str(uuid.uuid4()), "status": status, "enabled": True}
            for status in ("ready", "creating")]
        assert clone(full) == "voice_slots"
        assert made == []

        one_free = _Db(_practice(), _snip(150), TAKE)
        one_free.client.tables["ai_voice_clones"] = [
            {"owner_user_id": str(uuid.uuid4()), "status": status, "enabled": True}
            for status in ("ready", "deleted")]
        assert clone(one_free) == "ready"
        assert made == [OWNER]


def test_a_pause_heard_in_the_audio_passes_when_the_words_hide_it():
    """The founder's smoke run: Whisper put no gap between the words, yet
    the clip had a clear pause before the target phrase."""
    from services.ai_voice_validator import validate
    out = validate(audio=b"x", transcription=_heard(0.0, "the window closes once"),
                   spoken_words=SENTENCE.lower().split(),
                   exercise={"exercise": "pause", "target_phrase": "the window closes once"},
                   original_wpm=None, original_duration_s=None,
                   decode=lambda _a: _pcm_with_pause(1.0))
    assert out["passed"] and out["measurements"]["word_gap_s"] < 0.1
    assert out["measurements"]["pause_s"] >= 0.3


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


# ── fillers: the sentence said without its ums (founder 2026-10-18) ──────

FILLERS = ("We think, um, the timing matters because, uh, the window closes "
           "once incumbents match our price")


def test_a_sentence_with_fillers_is_said_without_them_and_the_next_try_is_measured_on_them():
    """Founder 2026-10-18 (Linear "Evaluate retaining filler words in
    transcripts"): the transcript stays clean; the speaker hears their own
    sentence without its hesitations, with L18 under the player, and the
    next try is measured on fillers only, from its own transcript, never
    shown."""
    with _on():
        practice = _practice()
        practice["exact_passage"] = FILLERS
        db = _Db(practice, {**_snip(150), "transcript": FILLERS}, TAKE)
        _ready_voice(db)
        voices = _Voices()
        out = _run_pipeline(db, practice, voices, _heard(0.0, PHRASE))
        cycle = db.client.tables["ai_voice_cycles"][0]
        assert out["clip"]["state"] == "ready", cycle.get("failure_kind")
        assert cycle["exercise"] == "fillers" and not cycle["selection"]["default"]
        # The provider is asked for the speaker's own words, the hesitations out.
        said = re.sub(r"[^a-z ]", "", voices.bodies[0]["text"].lower()).split()
        assert said == SENTENCE.lower().split()
        why = out["clip"]["why"]
        assert why == ai_voice_clip.WHY["fillers"] and not re.search(r"\d", why)
        assert cycle["metrics_before"]["fillers_per_100"] > 0
        # The next try: clean is improved; the same again is similar.
        ai_voice_clip.note_attempts(db, practice, [
            {"attempt_index": 1, "duration_ms": 3000, "acoustic_metrics": {},
             "transcript": SENTENCE}])
        assert cycle["outcome"] == "improved"
        assert cycle["metrics_after"]["fillers_per_100"] == 0
        ai_voice_clip.note_attempts(db, practice, [
            {"attempt_index": 2, "duration_ms": 3000, "acoustic_metrics": {},
             "transcript": FILLERS}])
        assert cycle["outcome"] == "similar"


def test_a_clean_sentence_never_gets_the_fillers_clip():
    """No hesitation in the sentence: fillers is never picked, and a request
    for it is refused before anything is sent."""
    with _on():
        out = ai_voice_severity.select(_snip(150), ai_voice_severity.own_medians(TAKE),
                                       sentence=SENTENCE, seed="s")
        assert out["exercise"] != "fillers" and out["severity_scores"]["fillers"] == 0.0
    with pytest.raises(ai_voice_prompt.PromptRejected):
        ai_voice_prompt.build(sentence=SENTENCE, exercise={"exercise": "fillers"},
                              practice_id="p")


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


def test_a_voice_already_gone_at_elevenlabs_counts_as_deleted():
    """ElevenLabs answers a missing voice with a 400 "voice_not_found", not
    a 404 (founder's smoke run, 2026-10-13); a repeated Delete must not stick
    at "deleting" because of it."""
    import httpx
    from services.elevenlabs_client import ElevenLabsClient
    gone = httpx.MockTransport(lambda _r: httpx.Response(
        400, json={"detail": {"status": "voice_not_found"}}))
    client = ElevenLabsClient(api_key="test-key-not-real", transport=gone)
    client.delete_voice("voice-abc")
    assert client.voice_exists("voice-abc") is False


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


# ── the clip starts when the exercise moment is known (founder 2026-10-15, B) ──

ARC, ACTOR, TAKE_ID, SNIP_ID = (str(uuid.uuid4()) for _ in range(4))


def _item(**extra):
    row = {"id": "cand-1", "kind": "bold", "source": "confident_voice",
           "feedback_family": "confident_voice", "block_id": "b1",
           "snippet_id": SNIP_ID, "take_session_id": TAKE_ID,
           "span": {"start": 0, "end": 20}, "quote": SENTENCE[:20],
           "bookmark_tier": "standard", "practice_prompt": True,
           "evidence": {"project_id": ARC, "take_session_id": TAKE_ID,
                        "slide_index": 0, "paragraph_index": 0,
                        "span": {"start": 0, "end": 20}}}
    row.update(extra)
    return row


class _BakeDb:
    def __init__(self):
        self.stored = 0

    def v2_get_session_by_id(self, take_id):
        return {"id": take_id, "user_id": ACTOR, "arc_id": ARC, "analysis_state": "ready"}

    def write_ideal_text_feedback_bake(self, *_a):
        self.stored += 1
        return True


@pytest.fixture
def baked(monkeypatch):
    """A bake whose Manager answer the test chooses, a broker that remembers
    its marks, and a queue that records what was asked of it."""
    from services import ideal_text_feedback_bake as bake
    from services import job_queue
    marks: dict = {}

    class _Redis:
        def set(self, key, value, nx=False, ex=None):
            if nx and key in marks:
                return None
            marks[key] = value
            return True

        def delete(self, *keys):
            return sum(marks.pop(k, None) is not None for k in keys)

    queued: list = []
    monkeypatch.setattr(job_queue, "queue_configured", lambda: True)
    monkeypatch.setattr(job_queue, "get_redis", lambda **_k: _Redis())
    monkeypatch.setattr(job_queue, "bake_queue_name", lambda: "bakes")
    monkeypatch.setattr(job_queue, "enqueue",
                        lambda path, *a, **k: (queued.append((path, a, k)), True)[1])
    monkeypatch.setattr(ai_voice_clip, "principal_for", lambda *_a: "principal-1")
    answers: dict = {}
    monkeypatch.setattr(bake, "_compute_block", lambda *_a, **_k: (answers["block"], 5))

    def run(block):
        answers["block"] = block
        db = _BakeDb()
        return bake._bake_and_store(db, ARC, ACTOR, "snap-1", (SENTENCE, TAKE_ID, 1)), db
    return run, queued


def test_a_stored_bake_with_a_voice_exercise_queues_one_prewarm_once(baked):
    """The moment the bake knows the exercise moment, the clip's job is
    queued in the bake's lane with what the walk would open (here the
    moment's own words); a rebake of the same Take never queues a second."""
    run, queued = baked
    with _on():
        stored, db = run({"changes": [_item()], "style_changes": []})
        assert stored and db.stored == 1
        assert len(queued) == 1
        path, args, kwargs = queued[0]
        assert path == "services.ai_voice_clip.prewarm" and kwargs["queue"] == "bakes"
        assert kwargs["rq_job_id"] == f"ai-voice-prewarm-{TAKE_ID}-{SNIP_ID}"
        user_id, take_id, snippet_id, principal, start, lane = args
        assert (user_id, take_id, snippet_id, principal, lane) == (ACTOR, TAKE_ID, SNIP_ID, "principal-1", "bakes")
        assert start["kind"] == "plain" and start["evidence"]["project_id"] == ARC
        # The rebake after an answer: the same Take, the same moment, no second job.
        stored, _db = run({"changes": [_item(status="approved")], "style_changes": []})
        assert stored and len(queued) == 1


def test_the_bake_queues_the_offered_exercise_and_never_a_rewrite(baked):
    """With an exercise offered on the moment the practice is the exercise's
    (the walk's own choice); a clearer version riding it, or a green moment
    the walk does not practise (no `confident_practice`), starts no clip."""
    run, queued = baked
    offer = {"exercise_id": "hear-every-word-v1", "passage": SENTENCE, "version": 1}
    with _on():
        run({"changes": [_item(practice_exercise=offer)], "style_changes": []})
        assert len(queued) == 1 and queued[0][1][4]["kind"] == "exercise"
        assert queued[0][1][4]["exercise_id"] == "hear-every-word-v1"
        run({"changes": [_item(block_id="b2", id="cand-2"),
                         _item(block_id="b2", id="rw-1", kind="replace",
                               feedback_family="rewrite_clarity",
                               proposed_text="A clearer version.")],
             "style_changes": []})
        run({"changes": [_item(block_id="b3", bookmark_tier="confident")],
             "style_changes": []})
        assert len(queued) == 1


class _PrewarmDb(_Db):
    """The reads the practice start makes, over the in-memory tables."""

    def __init__(self, snippet, take):
        super().__init__(None, snippet, take)
        self.practices: list = []

    def v2_get_session_by_id(self, take_id):
        return {"id": take_id, "user_id": OWNER, "arc_id": ARC}

    def get_confident_voice_practice_by_moment(self, take_id, snippet_id, owner=None):
        return next((p for p in self.practices
                     if p["take_session_id"] == take_id and p["snippet_id"] == snippet_id), None)

    def get_confident_voice_practice(self, practice_id, *_a):
        return next((p for p in self.practices if p["id"] == practice_id), None)

    def create_confident_voice_practice(self, row):
        self.practices.append({"id": str(uuid.uuid4()), "status": "open", **row})
        return self.practices[-1]


def _start_for(kind="plain"):
    return {"snippet_id": SNIP_ID, "take_session_id": TAKE_ID, "kind": kind,
            "exercise_id": None, "feedback_id": "cand-1",
            "evidence": {"project_id": ARC, "take_session_id": TAKE_ID,
                         "slide_index": 0, "paragraph_index": 0,
                         "span": {"start": 0, "end": 20}}}


@pytest.fixture
def allowed(monkeypatch):
    """The practice's purpose is on and the speaker's choice allows it."""
    from services import processing_authorization, processing_purposes
    monkeypatch.setattr(processing_purposes, "purpose_is_operational", lambda *_a, **_k: True)

    class _Gate:
        enforced = False

        def __init__(self, *_a):
            pass

        def choice_permitted(self, *_a):
            return True
    monkeypatch.setattr(processing_authorization, "ProcessingAuthorizationService", _Gate)


def test_prewarm_opens_the_practice_and_the_clip_and_skips_without_a_voice(allowed):
    """Before the walk reaches the Exercise screen the practice row exists
    (one per moment, as the walk would open it) and its clip is made; the
    walk's own ask then resumes both. With no voice coming, nothing is
    opened."""
    snippet = {**_snip(150, pause_ratio=0.02), "id": SNIP_ID, "session_id": TAKE_ID,
               "audio_segment_path": "a.webm", "start_offset_ms": 0}
    with _on():
        db = _PrewarmDb(snippet, TAKE)
        assert ai_voice_clip.prewarm(OWNER, TAKE_ID, SNIP_ID, "", _start_for(),
                                     database=db) == "skipped:no_voice"
        assert db.practices == [] and "ai_voice_cycles" not in db.client.tables
        _ready_voice(db)
        voices = _Voices()

        def run(cid, p):
            ai_voice_clip.generate(cid, p, database=db, provider=voices,
                                   transcribe=lambda _a: _heard(0.55, "the window closes once"),
                                   put_object=lambda k, a: "bucket",
                                   decode=lambda _a: _pcm_with_pause(1.0),
                                   provider_usage={"used": 0})
        assert ai_voice_clip.prewarm(OWNER, TAKE_ID, SNIP_ID, "", _start_for(),
                                     database=db, run=run) == "ready"
        assert len(db.practices) == 1 and db.practices[0]["kind"] == "plain"
        assert db.practices[0]["original_user_answer"] is None
        assert voices.spoken == 1
        # The walk's own ask: the same practice, the same clip, no second one.
        practice = db.practices[0]
        again = ai_voice_clip.ensure(db, practice, user_id=OWNER, principal_id="",
                                     run=run, sign=lambda b, k: f"https://signed/{k}")
        assert again["clip"]["state"] == "ready" and voices.spoken == 1
        assert ai_voice_clip.prewarm(OWNER, TAKE_ID, SNIP_ID, "", _start_for(),
                                     database=db, run=run) == "ready"
        assert len(db.practices) == 1 and voices.spoken == 1


def test_a_voice_still_being_made_is_waited_for_a_bounded_number_of_times(monkeypatch):
    """Asked for before the clone is ready: the cycle waits (`no_voice`),
    the walk already sees the clip's place, one delayed retry is queued per
    wait, and after the last wait the clip is unavailable (the walk stops
    showing the dots) until a later ask finds the voice."""
    from services import job_queue
    queued: list = []
    monkeypatch.setattr(job_queue, "enqueue",
                        lambda path, *a, **k: (queued.append((path, a, k)), True)[1])
    with _on():
        db = _Db(_practice(), _snip(150, pause_ratio=0.02), TAKE)
        db.client.tables.setdefault("ai_voice_clones", []).append(
            {"owner_user_id": OWNER, "status": "creating", "enabled": True,
             "created_at": "2026-10-11T00:00:00+00:00"})
        voices = _Voices()
        out = _run_pipeline(db, db.practice, voices, _heard(0.55, "the window closes once"))
        cycle = db.client.tables["ai_voice_cycles"][0]
        # Chosen before the wait: the clip already names what it fixes (N120).
        assert out == {"demo": "ai_voice", "clip": {
            "state": "pending", "url": None, "max_appearances": 3,
            **ai_voice_clip.problem_of(cycle)}}
        assert out["clip"]["problem"] == cycle["selection"]["exercise"]
        assert (cycle["status"], cycle["failure_kind"]) == ("pending", "no_voice")
        assert cycle["generation_metadata"] == {"no_voice_waits": 1}
        assert voices.spoken == 0 and len(queued) == 1
        path, args, kwargs = queued[0]
        assert path == "services.ai_voice_clip.generate" and args[0] == cycle["id"]
        assert kwargs["delay_seconds"] == ai_voice_clip.NO_VOICE_RETRY_SECONDS
        assert kwargs["rq_job_id"].endswith("-wait1")
        for _ in range(ai_voice_clip.NO_VOICE_MAX_WAITS + 2):
            ai_voice_clip.generate(cycle["id"], "", database=db, provider=voices)
        assert cycle["generation_metadata"] == {"no_voice_waits": ai_voice_clip.NO_VOICE_MAX_WAITS}
        assert len(queued) == ai_voice_clip.NO_VOICE_MAX_WAITS
        assert ai_voice_clip.state(db, db.practice, cycle)["clip"]["state"] == "unavailable"
        # The voice arrives: the next ask makes the clip as before.
        db.client.tables["ai_voice_clones"][0].update(
            {"status": "ready", "provider_voice_id": "voice-abc"})
        done = _run_pipeline(db, db.practice, voices, _heard(0.55, "the window closes once"))
        assert done["clip"]["state"] == "ready" and voices.spoken == 1


def test_a_voice_that_will_not_come_is_not_waited_for(monkeypatch):
    """A new speaker whose Take made no voice (too short, failed, or off):
    the clip is unavailable at once, so the walk shows the locked Exercise
    instead of the dots for minutes."""
    from services import job_queue
    queued: list = []
    monkeypatch.setattr(job_queue, "enqueue",
                        lambda path, *a, **k: (queued.append((path, a, k)), True)[1])
    with _on():
        db = _Db(_practice(), _snip(150, pause_ratio=0.02), TAKE)
        db.client.tables.setdefault("ai_voice_clones", []).append(
            {"owner_user_id": OWNER, "status": "none", "failure_kind": "too_short",
             "enabled": True, "created_at": "2026-10-11T00:00:00+00:00"})
        voices = _Voices()
        out = _run_pipeline(db, db.practice, voices, _heard(0.55, "the window closes once"))
        assert out["clip"]["state"] == "unavailable" and out["demo"] != "ai_voice"
        assert voices.spoken == 0 and queued == []


def test_a_spoken_takes_upload_starts_the_voice_and_a_read_take_or_guest_does_not():
    """N84 (founder 2026-10-20, "start the voice copy at upload"): the voice
    is asked for as the Take is stored, with the stored audio and the
    Take's acquisition principal, never for a read Take or a guest."""
    from types import SimpleNamespace
    from unittest.mock import MagicMock, patch

    from flask import Flask, request

    from routes.v2 import lab_recording

    def upload(kind: str, user_id):
        persisted = SimpleNamespace(session_id="take-1", recording_id="rec-1", bucket="b",
                                    storage_key="k", storage_provider="r2",
                                    acquisition_principal_id="p-1")
        project = SimpleNamespace(principal=SimpleNamespace(id="p-1"), duplicate_take=None)
        with Flask(__name__).test_request_context(method="POST", data={}), \
                patch.object(lab_recording, "resolve_take_project", return_value=project), \
                patch.object(lab_recording, "ProcessingAuthorizationService", return_value=MagicMock()), \
                patch.object(lab_recording, "_prepare_lab_upload", return_value=SimpleNamespace(recording_kind=kind)), \
                patch.object(lab_recording, "_persist_lab_take", return_value=persisted), \
                patch.object(lab_recording, "_analysis_response", return_value=({"state": "queued"}, 202)), \
                patch("services.ai_voice_clone.after_take") as after_take:
            request.user_id = user_id
            _, status = lab_recording.v2_lab_create_recording.__wrapped__()
        assert status == 202
        return after_take

    asked = upload("spoken", "u-1")
    asked.assert_called_once()
    kwargs = asked.call_args.kwargs
    assert (kwargs["user_id"], kwargs["principal_id"], kwargs["take_id"]) == ("u-1", "p-1", "take-1")
    assert kwargs["storage"] == {"storage_provider": "r2", "bucket": "b", "storage_key": "k"}
    upload("read", "u-1").assert_not_called()
    upload("spoken", None).assert_not_called()


def test_two_corrected_moments_queue_two_prewarms(baked):
    """Founder 2026-10-20: both shown moments below the floor are corrected,
    so a Take can carry two voice exercises; the bake queues a clip for each,
    once, and a rebake queues no more."""
    run, queued = baked
    second = _item(block_id="b2", id="cand-2", snippet_id="snip-2",
                   span={"start": 30, "end": 50}, quote=SENTENCE[30:50],
                   evidence={"project_id": ARC, "take_session_id": TAKE_ID,
                             "slide_index": 1, "paragraph_index": 1,
                             "span": {"start": 30, "end": 50}})
    with _on():
        stored, _db = run({"changes": [_item(), second], "style_changes": []})
        assert stored and len(queued) == 2
        assert sorted(q[1][2] for q in queued) == sorted([SNIP_ID, "snip-2"])
        assert {q[2]["rq_job_id"] for q in queued} == {
            f"ai-voice-prewarm-{TAKE_ID}-{SNIP_ID}", f"ai-voice-prewarm-{TAKE_ID}-snip-2"}
        run({"changes": [_item(), second], "style_changes": []})
        assert len(queued) == 2


@pytest.mark.parametrize("selection, problem, phrase", [
    ({"exercise": "stress", "target_phrase": "twice  as long"}, "stress", "twice as long"),
    ({"exercise": "pause", "target_phrase": "four days"}, "pause", "four days"),
    ({"exercise": "pace", "target_phrase": None}, "pace", None),
    ({"exercise": "fillers", "target_phrase": None}, "fillers", None),
    ({"exercise": "stress", "target_phrase": "the window", "default": True}, "default", "the window"),
])
def test_a_ready_clip_names_its_problem_and_phrase(selection, problem, phrase):
    practice = {"id": "p1", "kind": "plain"}
    cycle = {"status": "completed", "storage_key": "k", "bucket": "b", "duration_ms": 4200,
             "demo": "ai_voice", "exercise": selection["exercise"], "selection": selection}
    clip = ai_voice_clip.state(None, practice, cycle, sign=lambda *_a: "https://clip")["clip"]
    assert (clip["state"], clip["problem"], clip["phrase"]) == ("ready", problem, phrase)
    # Words only: the severity, the scores and the check never cross.
    assert set(clip) == {"state", "url", "duration_ms", "max_appearances", "why", "problem", "phrase"}
    # Chosen and still being made: named already, so the walk's bubble and
    # the chat say the same; not chosen yet: nothing to name.
    chosen = ai_voice_clip.state(None, practice, {**cycle, "status": "generating"})["clip"]
    assert (chosen["state"], chosen["problem"], chosen["phrase"]) == ("pending", problem, phrase)
    waiting = ai_voice_clip.state(None, practice, {"status": "pending", "demo": "ai_voice"})["clip"]
    assert "problem" not in waiting and "phrase" not in waiting


def test_a_praised_moments_practice_gets_a_clip(baked):
    """A praised moment is practised too (N122): the bake starts its clip
    as the walk would open it, the moment said again, beside a corrected
    moment's."""
    run, queued = baked
    corrected = str(uuid.uuid4())
    with _on():
        run({"changes": [_item(block_id="b1", bookmark_tier="confident", practice_prompt=False,
                               confident_practice=True),
                         _item(block_id="b2", id="cand-2", snippet_id=corrected)],
             "style_changes": []})
        assert sorted((q[1][2], q[1][4]["kind"]) for q in queued) == sorted(
            [(SNIP_ID, "plain"), (corrected, "plain")])
