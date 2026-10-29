"""
STORY    As a speaker, I want my Ideal Text's feedback block to be the V3
         feedback, each answered item keeping its decision, every Confident
         Voice item playable, served fast, and empty rather than wrong when
         something fails, so that I can trust what is marked (feedback on
         the critical path).
OUTCOME
  O1  A failing stage serves its named fallback (no rows, a named stage in
      `degraded`), never wrong rows.
  O2  When V3 fails on the way, no V2 rows are served and the failure is
      reported.
  O3  A served V3 Confident Voice row carries its recording
      (snippet_audio_ref), so the speaker can hear the moment.
  O4  An answered row stays, with its decision as its status.
  O5  Every served V3 row carries its learning handles and nothing else
      leaves the server with it.
  O6  The block equals the frozen block, each row read once, and the live
      read is served before the dark frame is written.
  O7  On a plan, the walk I see knows this week's level, and which helper
      words I had when I recorded (N246).
PROVES   O1 -> test_the_span_check_serving_none_is_a_named_fallback
         O2 -> test_a_failure_on_the_way_to_v3_serves_no_v2_rows
         O3 -> test_a_served_confident_voice_row_carries_its_recording
         O4 -> test_a_yes_on_the_legacy_route_marks_the_row_approved_and_keeps_it
         O5 -> test_every_served_v3_row_carries_its_learning_handles
         O6 -> test_the_block_is_the_same_block_and_no_row_is_read_twice
               test_the_live_read_serves_the_block_before_the_dark_frame_is_written
         O7 -> test_on_a_plan_the_walk_i_see_knows_my_level
WHY      services.ideal_text_changes (audit Q-C1). O3: founder 2026-09-20
         "there is no playback on the overlay". O4 and O5 drive stages of
         _ChangesRun directly; the rest go through build_changes_block.
"""
from __future__ import annotations

from unittest.mock import patch

from config import Config
from services.degradation import DegradationLog
from services.ideal_text_changes import (
    ChangesDeps,
    _ChangesRun,
    build_changes_block,
)

ARC = "11111111-1111-4111-8111-111111111111"
T1 = "22222222-2222-4222-8222-222222222222"
S1 = "33333333-3333-4333-8333-333333333333"
S2 = "44444444-4444-4444-8444-444444444444"
DOC = "We started small. And then we shipped it fast."


class FakeDB:
    """Only the reads the block makes on the legacy (no-contract) lane."""

    def __init__(self, *, sugs=None, snippets=None, boom=()):
        self.sugs = sugs or {}
        self.snippets = snippets if snippets is not None else [
            {"id": S1, "start_offset_ms": 0,
             "transcript": "We started small.",
             "metrics": {"piece": {"slide_index": 0}}},
            {"id": S2, "start_offset_ms": 10,
             "transcript": "And then we shipped it fast.",
             "metrics": {"piece": {"slide_index": 0}}},
        ]
        self.boom = set(boom)
        self.calls: list[str] = []

    def _maybe_boom(self, name):
        self.calls.append(name)
        if name in self.boom:
            raise RuntimeError(f"{name} is down")

    def get_arc_sessions(self, arc_id):
        self._maybe_boom("get_arc_sessions")
        return [{"id": T1, "take_index": 1, "recording_kind": "spoken"}]

    @property
    def takes(self):
        # audit Q-A2: production now calls db.takes.<method>();
        # this fake implements those methods directly on itself.
        return self

    def get_snippets_by_session(self, session_id):
        self._maybe_boom("get_snippets_by_session")
        return self.snippets

    def get_coach_snippet_drafts(self, *a, **k):
        return []

    def get_user_transcript_edits(self, *a, **k):
        return []

    def get_moment_suggestions_by_arc(self, arc_id):
        self._maybe_boom("get_moment_suggestions_by_arc")
        return dict(self.sugs)

    def get_suggestion_feedback_by_session(self, *a, **k):
        return []

    def get_coach_arc_ideal_text(self, arc_id):
        self._maybe_boom("get_coach_arc_ideal_text")
        return {}

    @property
    def ideal_text(self):
        # audit Q-A2: production now calls db.ideal_text.<method>(); this
        # fake implements those methods (and the boom/call tracking) on
        # itself, so the same instance serves both call shapes.
        return self

    def get_star_verdicts_by_snippet_ids(self, ids):
        return {}

    def get_snippets_by_ids(self, ids):
        self._maybe_boom("get_snippets_by_ids")
        return []

    def list_owner_voice_album_routes(self, arc_id):
        return []

    def v2_get_session_by_id(self, sid):
        self._maybe_boom("v2_get_session_by_id")
        return {}

    def get_ideal_text_parts(self, *a, **k):
        return []

    def list_ideal_decisions(self, *a, **k):
        return []

    def __getattr__(self, name):
        # Any read this fake does not model is a fault the stage must name.
        def _missing(*a, **k):
            raise AttributeError(f"FakeDB has no {name}")
        return _missing


def _deps(db, **overrides):
    base = dict(
        database=db,
        first_client_repository=None,
        applied_map=lambda ids: {},
        playback_map=lambda ids: {},
        previous_spoken_session=lambda arc_id, sid: None,
        locked_parts=lambda arc_id, user_id, text: [],
        with_evidence_coordinates=lambda rows, **k: rows,
        record_arms=lambda result, sid, uid: None,
    )
    base.update(overrides)
    return ChangesDeps(**base)


def _block(db, *, deps=None, degradation=None, **kw):
    with patch.object(Config, "LIVING_TRANSCRIPT_ENABLED", True):
        return build_changes_block(
            ARC, DOC, deps=deps or _deps(db), degradation=degradation, **kw)


def test_the_span_check_serving_none_is_a_named_fallback():
    db = FakeDB(sugs={S2: {"kind": "replace", "trigger": "polish",
                           "replacement_text": "And then we launched it fast.",
                           "why": "Tighter."}})

    def corrupt_spans(rows, **k):
        for row in rows:
            row["span"] = {"start": 0, "end": 1}
            row["quote"] = "ZZZ"
        return rows

    out = _block(db, deps=_deps(db, with_evidence_coordinates=corrupt_spans))
    assert out["changes"] == []
    assert {"stage": "ideal_text.changes.span_check",
            "kind": "span_check_failed"} in out["degraded"]


def _run_for_playback(deps):
    from services.ideal_text_changes import _ChangesRun
    return _ChangesRun(ARC, DOC, "user-1", T1, 1, deps,
                       DegradationLog("ideal_text"))


def _v3_row(snippet_id):
    """The shape `take_feedback_policy_v3_service` actually emits."""
    return {
        "id": f"cand:{snippet_id}",
        "kind": "bold",
        "source": "confident_voice",
        "feedback_family": "confident_voice",
        "snippet_id": snippet_id,
        "take_session_id": T1,
        "span": {"start": 0, "end": 17},
        "quote": "We started small.",
    }


# ---------------------------------------------------------------------------
#  AN ANSWERED V3 BOOKMARK IS SERVED WITH ITS DECISION (founder 2026-09-21).
#
#  Two readers trust one row. The lock gate: a change still served is
#  undecided. The page: an undecided item colours the mark, an approved or
#  dismissed one does not (24g-1). V2 kept both true by dropping answered
#  rows; V3 rebuilt its rows after that drop, so an answered item came back
#  undecided — the lock refused, the mark stayed lit. #602 dropped V3's rows
#  too, and the ladder behind an answered bookmark vanished with them
#  ("bookmarks are gone again"). Now the row stays and carries its status.
# ---------------------------------------------------------------------------

S2 = "22222222-2222-4222-8222-222222222222"


def _statuses(run):
    return [(row["id"], row.get("status")) for row in run.changes]


def test_a_yes_on_the_legacy_route_marks_the_row_approved_and_keeps_it():
    # The bare FakeDB raises on any read it does not model, so the marker
    # passing here also proves it asked the database nothing.
    run = _run_for_playback(_deps(FakeDB()))
    run.changes = [_v3_row(S1), _v3_row(S2)]
    run.v3_replaced_changes = True
    run.responded_ids = {f"cand:{S1}"}
    run.responses_by_id = {f"cand:{S1}": "yes"}
    run._mark_answered_service_items()
    assert _statuses(run) == [(f"cand:{S1}", "approved"), (f"cand:{S2}", None)]


# ══════════════════════════════════════════════════════════════════════════
#  V3 PACKETS — every served V3 card leaves a learning presentation
#  (founder 2026-09-29; the 29 Sep report's "V3 packets" finding)
# ══════════════════════════════════════════════════════════════════════════
#
# V2 froze a packet per card inside `_canonical_dual_write`, keyed by V2 row
# ids. V3's rows share no identity with those, so since the cutover no served
# card carried a packet and the browser had nothing to receipt. The V3 stage
# freezes the packets after the claim, from the bundle V3 served from.


def _v3_bundle(*keys):
    """The bundle `prepare_first_client_feedback` hands back, minimal."""
    family = {"cv": "confident_voice", "rw": "rewrite_clarity",
              "gf": "great_formulation"}
    candidates = [{
        "id": f"cand-{key}",
        "candidate_key": key,
        "feedback_family": family[key[:2]],
        "candidate_score": 0.5,
        "rank_evidence": {},
        "generated_output": {"quote": "We started small."},
        "training_eligible": False,
        "evidence": {"id": f"span-{key}", "evidence_hash": "b" * 64,
                     "exact_text": "We started small.", "audio_ref": "a.webm",
                     "start_ms": 0, "end_ms": 900},
    } for key in keys]
    return {
        "owner_principal_id": "owner", "project_id": ARC, "take_id": T1,
        "candidate_set_id": "set-1", "candidates": candidates,
        "selected_keys": [{"id": c["candidate_key"],
                           "feedback_family": c["feedback_family"]}
                          for c in candidates],
        "versions": {"taxonomy_version": "v1"}, "generation_runs": [],
    }


class _PacketDb:
    """The reads and the writes the claim and packet stages make."""

    def __init__(self):
        self.exposures: list[dict] = []
        self.presentations: list[dict] = []

    def v2_get_session_by_id(self, sid):
        return {"id": T1, "take_index": 1} if sid == T1 else {}

    def insert_take_feedback_exposure(self, **kwargs):
        self.exposures.append(kwargs)
        return True

    def __getattr__(self, name):
        def _missing(*a, **k):
            raise AttributeError(f"_PacketDb has no {name}")
        return _missing

    def create_learning_surface_presentation(self, row):
        self.presentations.append(row)
        return {"presentation_id": f"p-{len(self.presentations)}",
                "acknowledgement_token": "tok", "evaluation_only": False}


def _v3_verbal_row(key, family):
    return {"id": key, "kind": "replace", "source": "wording",
            "feedback_family": family, "snippet_id": S1,
            "span": {"start": 0, "end": 17}}


def test_every_served_v3_row_carries_its_learning_handles():
    db = _PacketDb()
    run = _ChangesRun(ARC, "Our approach is different, and that matters.", "user-1",
                      T1, 1, _deps(db), DegradationLog("ideal_text"))
    run.arm_sid = T1
    run.v3_replaced_changes = True
    run.v3_learning = {"bundle": _v3_bundle("cv1", "cv2", "rw1"),
                       "block_partition_version": "slide-run-75-word-partition-v1"}
    cv1, cv2 = _v3_row(S1), _v3_row("44444444-4444-4444-8444-444444444444")
    cv1["id"], cv2["id"] = "cv1", "cv2"
    cv1["bookmark_tier"], cv1["block_id"] = "exercise", "block-1"
    run.changes = [cv1, cv2, _v3_verbal_row("rw1", "rewrite_clarity")]
    run.styles = []

    run._v3_learning_presentations()
    out = run._finish()

    handles = {row["id"]: row.get("learning_exposures") for row in out["changes"]}
    assert set(handles) == {"cv1", "cv2", "rw1"}
    assert [h["learning_surface"] for h in handles["cv1"]] == [
        "confidence_classification"]
    assert {h["learning_surface"] for h in handles["rw1"]} == {
        "correction_generation", "correction_selection"}
    assert len(db.presentations) == 4
    for presentation in db.presentations:
        assert presentation["actor_role"] == "owner"
        assert presentation["delivery_mode"] == "production"
        assert presentation["versions"]["block_partition_version"] == \
            "slide-run-75-word-partition-v1"
        assert "candidate_score" not in presentation["visible_payload"]
    exercise_card = next(p for p in db.presentations
                         if p["visible_payload"]["candidate_key"] == "cv1")
    assert exercise_card["visible_payload"]["bookmark_tier"] == "exercise"
    # The handle is all that leaves the server with the row.
    for handle in handles["cv1"]:
        assert set(handle) == {"presentation_id", "acknowledgement_token",
                               "learning_surface", "evaluation_only"}


# ── CLOSE-OUT AUDIT 2026-10-04: V3 is never silenced or stood in for ──────
def _v3_block(db, *, deps=None):
    """The block with the V3 service on. The flag is patched where the block
    reads it (this file's `Config`, as `_block` does), and the service switch
    at its one function: another test reloads `config`, after which
    `from config import Config` inside a call names a different class from
    the one imported here (test order must not matter)."""
    with patch.object(Config, "LIVING_TRANSCRIPT_ENABLED", True), \
            patch("services.coach_guidance_delivery.runtime_is_enabled",
                  return_value=True):
        return build_changes_block(ARC, DOC, deps=deps or _deps(db))


def _replace_sug_db():
    return FakeDB(sugs={S2: {"kind": "replace", "trigger": "polish",
                             "replacement_text": "And then we launched it fast.",
                             "why": "Tighter."}})


def test_a_served_confident_voice_row_carries_its_recording():
    """V3 replaces the rows the clips were first attached to; the served
    Confident Voice row must still carry its recording."""
    db = _replace_sug_db()
    deps = _deps(db, playback_map=lambda ids: {
        S1: {"snippet_audio_ref": "takes/clip-1.webm"}} if T1 in ids else {})
    with patch("services.mlc3_first_client_feedback.prepare_first_client_feedback",
               return_value=[_v3_row(S1)]), \
            patch("services.ideal_text_parts.bind_pieces_to_parts",
                  side_effect=lambda doc, **_k: doc):
        out = _v3_block(db, deps=deps)
    served = [row for row in out["changes"]
              if row.get("feedback_family") == "confident_voice"]
    assert [row["id"] for row in served] == [f"cand:{S1}"]
    assert served[0]["snippet_audio_ref"] == "takes/clip-1.webm"


def test_on_a_plan_the_walk_i_see_knows_my_level():
    """Founder 2026-10-28 (N246): the walk the speaker saw never had this
    week's level; the server asked a store that cannot read a plan."""
    class PlanDB(FakeDB):
        def get_open_plan(self, user_id):
            return {"id": "plan-1", "status": "active", "level": "key_line",
                    "started_at": "2026-10-27T09:00:00Z"}

        def list_plan_level_events(self, user_id, plan_id):
            return []

        def list_slide_helper_words_log_for_slides(self, arc_id, user_id, slides):
            return {0: [{"phrases": ["shipped it"], "created_at": "2026-10-28T09:00:00Z"}]}

    run = _run_for_playback(_deps(PlanDB()))
    take = {"id": T1, "created_at": "2026-10-28T10:00:00Z"}
    with patch("services.plan_flow.enabled", return_value=True):   # the plan is on for me
        walk = run._walk_inputs(take, {"pieces": [{"slide_index": 0}]})
    assert walk["plan_level"] == "key_line"
    assert walk["held_words"] == {0: ["shipped it"]}


def test_a_failure_on_the_way_to_v3_serves_no_v2_rows():
    """The session read, the document and the binding ran outside the guard,
    so a raise there left V2's rows serving. It is V3 failing this Take."""
    with patch("services.ideal_text_parts.bind_pieces_to_parts",
               side_effect=RuntimeError("binding broke")):
        out = _v3_block(_replace_sug_db())
    assert out["changes"] == []
    assert out["feedback_status"] == {"state": "failed",
                                      "reason": "v3_error:RuntimeError"}


# ══════════════════════════════════════════════════════════════════════════
#  THE SAME BLOCK, READ ONCE (founder 2026-10-15, the timing lines)
# ══════════════════════════════════════════════════════════════════════════
#
# The Manager's seconds were round trips: the same session, snippets and
# arc rows read in stage after stage, and the V3 dark frame written inside
# the speaker's wait. The refactor must change what the speaker is served
# by nothing at all. The block below is the one `build_changes_block`
# served on this fixture BEFORE the per-run memo existed (a frozen dump).

_FROZEN_BLOCK = {
    "changes": [{
        "id": S2, "kind": "replace",
        "proposed_text": "And then we launched it fast.",
        "quote": "shipped", "snippet_id": S2, "source": "polish",
        "span": {"end": 37, "start": 30}, "take_session_id": T1,
        "visual": "underline", "why": "Tighter.", "why_key": "clarity",
    }],
}


def test_the_block_is_the_same_block_and_no_row_is_read_twice():
    db = _replace_sug_db()
    assert _block(db) == _FROZEN_BLOCK
    # Each read the run makes, it makes once: the session, the snippets
    # and the arc's Takes used to be asked for in stage after stage.
    assert len(db.calls) == len(set(db.calls)), db.calls


class _ShadowDb(FakeDB):
    """A Take in dark mode, whose frame write the test can hold back."""

    def __init__(self, *, go=None, done=None, **kw):
        super().__init__(**kw)
        self.writes: list[str] = []
        self.go, self.done = go, done

    def v2_get_session_by_id(self, sid):
        self._maybe_boom("v2_get_session_by_id")
        return {"id": sid, "owner_principal_id": "owner-1", "take_index": 1,
                "recording_id": "rec-1"}

    def record_take_feedback_policy_v3_shadow(self, **kw):
        if self.go is not None:
            self.go.wait(5)
        self.writes.append(kw["take_session_id"])
        if self.done is not None:
            self.done.set()
        return {"outcome": "duplicate"}   # stops before the V4 draw


def _dark(db, **kw):
    frame = {"recording_id": "rec-1", "take_index": 1, "frame_hash": "h" * 64}
    with patch("services.take_feedback_policy_v3.dark_enabled",
               return_value=True), \
            patch("services.take_feedback_policy_v3.build_shadow_frame",
                  return_value=frame):
        return _block(db, **kw)


def test_the_live_read_serves_the_block_before_the_dark_frame_is_written():
    import threading
    inline = _ShadowDb(sugs=_replace_sug_db().sugs)
    served_inline = _dark(inline)
    assert inline.writes == [T1]            # the worker's path: inline

    go, done = threading.Event(), threading.Event()
    live = _ShadowDb(sugs=_replace_sug_db().sugs, go=go, done=done)
    served_live = _dark(live, background_shadow=True)
    assert served_live == served_inline == _FROZEN_BLOCK
    assert live.writes == []                # served first ...
    go.set()
    assert done.wait(5) and live.writes == [T1]   # ... written after, once
