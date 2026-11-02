"""
STORY    As a speaker who noted what matters to me, I want the walk to pick
         the moment where my words matter most for me and to write its
         Clearer version with that in mind, in my own words, so that the one
         thing I fix is the one that helps me most, and nothing changes
         when the walk has nothing of mine to read.
OUTCOME
  O1  Without the ring row, without notes, or when the read fails, says
      something malformed or is late, the walk picks exactly as it did
      before; nobody waits for a read not known to reach them, and a read
      that does is waited for at most the cap (N326 items 4 and 5, N327).
  O2  With my note ("my manager says I explain too much and never give the
      answer") and my manager's question, the read flags my buried answer
      and it becomes my one thing to improve, with its Clearer version
      "With a second shift, ninety is possible by March."; a later read of
      the frozen Take keeps that walk; a flagged moment whose Clearer
      version fails the gate leaves the walk as it was, and such a rewrite
      never replaces the one I had (N326 item 5).
  O3  A Clearer version that repeats a phrase from my notes I did not say
      in the Take is refused (N326 item 5).
  O4  Will's private note about me is never read for the walk (N326 item 2).
  O5  A coach never sees my notes, that they were used, or a reason built
      from them: the frame and the stored rewrite carry only the choice of
      moments and my own words (N326 item 5, Never 2).
PROVES   O1 -> test_no_ring_no_notes_or_a_failed_read_leave_the_walk_as_it_was
         O2 -> test_my_note_makes_my_buried_answer_the_one_thing
         O3 -> test_a_clearer_version_never_repeats_my_notes
         O4 -> test_wills_private_note_is_never_read
         O5 -> test_a_coach_never_sees_my_notes_or_why_a_moment_was_picked
WHY      Founder 2026-11-02, the Claude Code chat, on the prototype
         https://claude.ai/artifact/KvAiek4DrxgbpDudcBFJNQ: "Go with your
         picks on all four" (N326, building N290).
"""
import json

import pytest

from services import inner_context, moment_suggestions, verbal_read
from services.take_feedback_policy_v3 import build_shadow_frame

_NOTE = "my manager says I explain too much and never give the answer"
_QUESTION = "Can we get back above ninety percent by March?"
_FOCUS = "Give the answer first, then the reasons."
_BURIED = ("I think there are a lot of factors here, the supplier and the staffing, "
           "and maybe if we add a second shift, ninety is possible by March.")
_CLEARER = "With a second shift, ninety is possible by March."
_FILLED = "So, like, you know, we looked at the numbers again and, you know, yeah, the numbers."
_UMS = "um so um we looked at the um numbers again and um yeah the numbers"
_DROP = "We will share the full staffing plan with the whole team next week."


def _take(rewrite=None, clean=False, **options):
    """Tomás's Take: his best (slide 0), a filler-heavy line with no
    Clearer version (1; ``clean``: said cleanly), the buried answer (2) and
    a voice drop (3)."""
    second = (_DROP, _DROP) if clean else (_FILLED, _UMS)
    said = [(" ".join(f"w0x{n}" for n in range(75)) + ".", None, 0.9),
            (*second, 0.5), (_BURIED, _BURIED, -0.2), (_DROP, _DROP, -0.6)]
    pieces, snippets, at = [], [], 0
    for index, (text, transcript, score) in enumerate(said):
        pieces.append({"snippet_id": f"s{index}", "take_session_id": "take-2",
                       "slide_index": index, "start": at, "end": at + len(text), "text": text,
                       "recording_id": "recording-1", "start_offset_ms": index * 5000,
                       "duration_ms": 5000})
        snippets.append({"id": f"s{index}", "session_id": "take-2", "recording_id": "recording-1",
                         "start_offset_ms": index * 5000, "duration_ms": 5000,
                         "transcript": transcript,
                         "metrics": {"piece": {"slide_index": index}, "voice_confidence": {
                             "version": "voice-confidence-universal-v3", "score": score}}})
        at += len(text) + 1
    buried = pieces[2]
    row = {"id": "r-buried", "feedback_family": "rewrite_clarity", "snippet_id": "s2",
           "take_session_id": "take-2", "span": {"start": buried["start"], "end": buried["end"]},
           "kind": "replace", "quote": _BURIED, "proposed_text": _CLEARER,
           "model_version": "moment-suggestion-clearer-v1",
           "_manager_evidence": {"specificity": 5, "fallback": False}, **(rewrite or {})}
    text = " ".join(piece["text"] for piece in pieces)
    frame = build_shadow_frame(
        take_document={"take_session_id": "take-2", "text": text, "pieces": pieces},
        snippets=snippets, suggestions={}, feedback_candidates=[row], take_index=2,
        expected_recording_id="recording-1", served_text=text, **options)
    return frame, snippets


def _walk(frame):
    return [(b["slide_index"], b["walk_slot"], b["exercise_kind"]) for b in frame["blocks"]
            if b["walk_slot"]]


class _Result:
    def __init__(self, parsed):
        self.parsed = parsed


class _Db:
    """The run's database: the Take, its moments, my notebook; anything
    about Will's private note fails the test."""

    def __init__(self, snippets):
        self.snippets = snippets
        self.stored = []

    def v2_get_session_by_id(self, session_id):
        return {"id": session_id, "user_id": "u",
                "intake_context": {"topic": _QUESTION, "audience": "My manager"}}

    def get_snippets_by_session(self, session_id):
        return self.snippets

    def get_open_plan(self, user_id):
        return None

    def get_voice_notebook_consent(self, user_id):
        return {"decision": "yes"}

    def list_voice_notes(self, user_id, limit=20):
        from datetime import datetime, timezone
        return [{"id": "n1", "text_clean": f"# {_NOTE}",
                 "created_at": datetime.now(timezone.utc).isoformat()}]

    def upsert_moment_suggestion(self, *args, **kwargs):
        self.stored.append(args)
        return True

    def __getattr__(self, name):
        if "memory" in name:
            raise AssertionError(f"Will's private note was read: {name}")
        raise AttributeError(name)


@pytest.fixture(autouse=True)
def _fresh_process(monkeypatch):
    """Each test is its own analysis run: nothing kept from another."""
    monkeypatch.setattr(verbal_read, "_kept", {})


@pytest.fixture
def mine(monkeypatch):
    """The walk's ring row and my notebook reach me; nothing else does."""
    from services import life_chat, rings
    monkeypatch.setattr(rings, "feature_is_on_for_user", lambda feature, user, database=None:
                        feature in (rings.WALK_INNER_CONTEXT, "voice_notebook"))
    monkeypatch.setattr(life_chat, "is_enabled", lambda: False)


def _model(monkeypatch, read_answer, rewrite=_CLEARER):
    """The provider, at the repo's seam: the read's answer, and the rewrite."""
    seen = []

    def chat_complete(*, spec, system, user, surface, **_kw):
        seen.append({"surface": surface, "system": system, "user": user})
        if surface == "verbal_read":
            return None if read_answer is None else _Result(read_answer(json.loads(user)))
        return _Result({"why": "It leads with the answer you were asked for.",
                        "replacement": rewrite})
    monkeypatch.setattr("services.llm.chat_complete", chat_complete)
    return seen


def _flags(payload):
    """The read flags the moment that holds the buried answer."""
    (buried,) = [m["id"] for m in payload["moments"] if "second shift" in m["text"]]
    return {"moments": [{"id": buried, "kinds": ["not_answering", "no_main_point"],
                         "matters": "high"}], "focus": _FOCUS}


def _generation_context(snippets):
    readout = [{"id": s["id"], "transcript": s["transcript"], "features": {}}
               for s in snippets if s["transcript"]]
    return moment_suggestions._GenerationContext(
        cap=8, sticky_max=0.15, readout={"snippets": readout},
        metrics_by_id={s["id"]: s["metrics"] for s in snippets}, session={"user_id": "u"},
        audience="My manager", strategic_context=None, confidence_baseline=None,
        context_document=None, decided_keys=set(), intent_keys=set(), take_texts=[])


def _run_the_read(monkeypatch, snippets, read_answer, rewrite=_CLEARER):
    """The run's read, start to finish, as the analysis worker does it."""
    monkeypatch.setattr(moment_suggestions, "_load_generation_context",
                        lambda session_id, arc_id, database: _generation_context(snippets))
    seen = _model(monkeypatch, read_answer, rewrite)
    db = _Db(snippets)
    handle = verbal_read.start(db, session_id="take-2", arc_id="arc", user_id="u")
    landed = verbal_read.finish(handle, db, session_id="take-2", arc_id="arc", wait=10)
    return landed, db, seen


def test_no_ring_no_notes_or_a_failed_read_leave_the_walk_as_it_was(monkeypatch, mine):
    today, snippets = _take()
    # Today: the filler line has no Clearer version, so the fix is the AI
    # clip on the voice drop.
    assert _walk(today) == [(0, "strongest", None), (3, "weakest", "voice")]

    # No read reached the Take: what the frame gets changes nothing, on a
    # first read or a frozen one.
    nothing = verbal_read.for_pick(_Db(snippets), "u", {"id": "take-never-read"})
    assert nothing["lifts"] == {}
    assert _take(verbal=nothing)[0]["frame_hash"] == today["frame_hash"]
    frozen = {"r-buried", "relative-confidence:take-2:s0"}
    assert (_take(verbal={"lifts": {}, "pin": lambda: False}, frozen_candidate_ids=frozen)[0]["blocks"]
            == _take(frozen_candidate_ids=frozen)[0]["blocks"])

    # The ring row does not reach me, or I noted nothing: no read at all.
    from services import rings
    monkeypatch.setattr(rings, "feature_is_on_for_user", lambda *a, **k: False)
    assert not inner_context.gather(_Db(snippets), "u")
    landed, db, seen = _run_the_read(monkeypatch, snippets, _flags)
    assert (landed, db.stored, seen) == (False, [], [])

    # The read fails, or answers something malformed: nothing is kept.
    monkeypatch.setattr(rings, "feature_is_on_for_user", lambda feature, user, database=None:
                        feature in (rings.WALK_INNER_CONTEXT, "voice_notebook"))
    for answer in (None, lambda p: "not json", lambda p: {"moments": "s2"},
                   lambda p: {"moments": [{"id": "M99", "kinds": ["not_answering"], "matters": "high"}]},
                   lambda p: {"moments": [{"id": "M3", "kinds": ["rude"], "matters": "high"}]},
                   lambda p: {"moments": [{"id": "M3", "kinds": ["not_answering"], "matters": 10}]}):
        landed, db, _seen = _run_the_read(monkeypatch, snippets, answer)
        assert (landed, db.stored, verbal_read.kept("take-2")) == (False, [], {})

    # Nobody waits for a read not yet known to reach them; one that does is
    # waited for at most the cap, then left (N327).
    unknown = verbal_read.Handle()
    assert verbal_read.finish(unknown, _Db(snippets), session_id="take-2", arc_id="arc") is False
    slow = verbal_read.Handle(reached=True)
    assert verbal_read.finish(slow, _Db(snippets), session_id="take-2", arc_id="arc", wait=0.01) is False
    assert slow.late and verbal_read.kept("take-2") == {}


def test_my_note_makes_my_buried_answer_the_one_thing(monkeypatch, mine):
    _today, snippets = _take()
    landed, db, seen = _run_the_read(monkeypatch, snippets, _flags)
    assert landed
    # One read of the Take, with my manager's question and my note; then
    # one Clearer version, written with what matters to me.
    read_call, rewrite_call = seen
    assert read_call["surface"] == "verbal_read"
    assert _QUESTION in read_call["user"] and _NOTE in read_call["user"]
    assert json.loads(rewrite_call["user"])["speaker_focus"] == _FOCUS
    assert db.stored == [("s2", "arc", "replace", _CLEARER, None, "unconfident")]

    # The bake reads the run's read: my buried answer is the one thing,
    # with its Clearer version, and the voice drop is not shown.
    verbal = verbal_read.for_pick(db, "u", {"id": "take-2"})
    assert verbal["lifts"] == {"s2": 1.0}
    frame, _ = _take(verbal=verbal)
    assert _walk(frame) == [(0, "strongest", None), (2, "between", "clearer")]
    assert frame["verbal_lanes"]["rewrite_clarity"]["selected_candidate_ids"] == ["r-buried"]

    # A later read of the frozen Take, in another process, keeps that walk.
    frozen = {"r-buried", "relative-confidence:take-2:s0", "relative-confidence:take-2:s2"}
    again, _ = _take(verbal={"lifts": {}, "pin": lambda: True}, frozen_candidate_ids=frozen)
    assert _walk(again) == _walk(frame)

    # A flagged moment whose Clearer version fails the gate costs me no fix:
    # the walk is today's.
    failing, _ = _take({"proposed_text": "We should think about adding more shifts later on."},
                       verbal={"lifts": {"s2": 1.0}})
    assert _walk(failing) == [(0, "strongest", None), (3, "weakest", "voice")]
    # And such a rewrite is never stored over the Clearer version I had.
    landed, db, _seen = _run_the_read(monkeypatch, snippets, _flags,
                                      rewrite="We should think about adding more shifts later on.")
    assert landed and db.stored == []


def test_a_clearer_version_never_repeats_my_notes(monkeypatch, mine):
    from services.rewrite_gate import leaks
    said = "We could add a second shift and reach ninety by March."
    assert leaks("I never give the answer, but a second shift works.", [_NOTE], said)
    assert not leaks(_CLEARER, [_NOTE], _BURIED)
    # Words I said myself in the Take are mine to keep.
    assert not leaks("Never give the answer late.", [_NOTE], "I never give the answer late.")

    _today, snippets = _take()
    landed, db, _seen = _run_the_read(monkeypatch, snippets, _flags,
                                      rewrite="Since I never give the answer, a second shift gets us there.")
    # The read still weighs the moment; the leaking rewrite is not stored.
    assert landed and db.stored == []


def test_wills_private_note_is_never_read(monkeypatch, mine):
    from services import speaker_memory

    def forbidden(*_a, **_k):
        raise AssertionError("Will's private note was read for the walk")
    for name in ("note_for", "history_for", "prompt_block", "refresh", "record", "rebuild"):
        monkeypatch.setattr(speaker_memory, name, forbidden)
    _today, snippets = _take()
    gathered = inner_context.gather(_Db(snippets), "u")
    assert len(gathered.phrases) == 1 and gathered.phrases[0].endswith(_NOTE)
    landed, _db, _seen = _run_the_read(monkeypatch, snippets, _flags)
    assert landed


def test_a_coach_never_sees_my_notes_or_why_a_moment_was_picked(monkeypatch, mine):
    from services.prompts.verbal_read import KINDS
    from services.tracked_changes import CLEARER_VERSION_REASONS
    _today, snippets = _take()
    _landed, db, _seen = _run_the_read(monkeypatch, snippets, _flags)
    frame, _ = _take(verbal=verbal_read.for_pick(db, "u", {"id": "take-2"}))
    # The same walk chosen without any read: the filler line said cleanly,
    # so the buried answer is today's one thing too.
    baseline, _ = _take(clean=True)
    assert _walk(baseline) == _walk(frame) == [(0, "strongest", None), (2, "between", "clearer")]

    def keys(value, out):
        if isinstance(value, dict):
            for key, item in value.items():
                out.add(key)
                keys(item, out)
        elif isinstance(value, list):
            for item in value:
                keys(item, out)
        return out

    stored = json.dumps(frame, ensure_ascii=False).lower()
    # The coach's frame: none of my note's words, no focus line, no kind,
    # and no key the frame did not already have.
    for said in (_NOTE, "my manager says", "never give the answer", _FOCUS.lower(), *KINDS):
        assert said.lower() not in stored
    assert keys(frame, set()) == keys(baseline, set())
    assert [sorted(b) for b in frame["blocks"]] == [sorted(b) for b in baseline["blocks"]]
    # The stored rewrite: my own words, the reason a coach already reads,
    # no why-line that could be built from my notes.
    ((_sid, _arc, kind, words, why, trigger),) = db.stored
    assert (kind, words, why) == ("replace", _CLEARER, None)
    assert trigger in CLEARER_VERSION_REASONS
