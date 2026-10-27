"""
STORY    As a speaker on the plan, I want Will to ask for my yes before the
         plan's personal questions, and to delete what I gave if I turn it
         off, so that I share how I feel only when I choose to.
OUTCOME
  O1  With the switch off, the plan asks as it did: no ask, nothing written.
  O2  With it on and no answer yet, Will asks once, after the speaker's
      first voice message, and waits; nothing else is taken meanwhile.
      "Yes, ask me" is kept (the sentence's hash, the policy version) and
      the plan goes on: the worry question, the two ratings.
  O3  "Not now" is kept; the worry is never asked or kept, the ratings are
      not asked (then or at any later moment), the plan still reaches the
      calls and its end without "How did it go?".
  O4  The card's Turn off deletes the personal answers: the answers and
      their recordings, their bubbles in the Lounge, the plan's worry,
      Will's memory of them (his note is cleared), the feelings before a
      Take; then it is kept. A step that fails leaves the yes on and says
      so, never "deleted".
  O5  A plan made before the switch is asked at its next personal moment:
      the last practice's ratings and "How did it go?" at its end wait for
      the yes; "Not now" skips them, and the end goes on to what's next.
  O6  When the answer cannot be read, nothing personal is asked; a yes that
      cannot be kept is not a yes: Will asks again before the next personal
      question.
PROVES   O1 -> test_with_the_switch_off_the_plan_asks_as_before
         O2 -> test_will_asks_once_and_a_yes_goes_on_with_the_personal_questions
         O3 -> test_not_now_skips_the_personal_questions_and_keeps_the_plan
         O4 -> test_turning_off_deletes_what_the_speaker_gave
               test_a_turn_off_that_fails_leaves_the_yes_on
         O5 -> test_the_last_ratings_wait_for_the_yes
               test_the_plans_end_asks_for_the_yes_before_how_did_it_go
         O6 -> test_a_doubt_means_nothing_personal_is_asked
               test_a_yes_that_cannot_be_kept_is_not_a_yes
WHY      The plan's own yes, drawn and approved by the founder 2026-10-27
         (N211; Privacy 3.9 section 4e, to be published); the rules are
         frontend docs/flows/the-plan.md.
"""
from datetime import date, datetime, timedelta

import pytest

from config import Config
from services import plan_consent as C
from services import plan_flow as F
from tests.test_plan_flow import USER, _Adapter, _Db, bodies


class _ConsentDb(_Db):
    def __init__(self):
        super().__init__()
        self.consent, self.memory = [], []
        self.read_fails = self.keep_fails = self.feelings_fail = False
        self.erased = {"feelings": 0, "worry": 0}
        self.note = "Artur fears freezing."

    def latest_plan_consent_event(self, user_id):
        if self.read_fails:
            raise RuntimeError("down")
        return dict(self.consent[-1]) if self.consent else None

    def insert_plan_consent_event(self, row):
        if self.keep_fails:
            return False
        self.consent.append(dict(row))
        return True

    def get_active_processing_policy(self):
        return {"version": "phase1-2026-10-28-3.9"}

    def list_plan_answers_of_kinds(self, user_id, kinds):
        return [dict(a) for a in self.answers if a["kind"] in kinds]

    def delete_plan_answers(self, user_id, ids):
        self.answers = [a for a in self.answers if a["id"] not in ids]
        for i in ids:
            self.audio.pop(i, None)

    def list_speaker_memory_events(self, user_id):
        return list(self.memory)

    def delete_speaker_memory_events(self, user_id, ids):
        self.memory = [e for e in self.memory if e["id"] not in ids]

    def erase_plan_fact(self, user_id, key):
        for p in self.plans:
            p["facts"].pop(key, None)
        self.erased["worry"] += 1
        return 1

    def erase_pre_take_feelings(self, user_id):
        if self.feelings_fail:
            raise RuntimeError("down")
        self.erased["feelings"] += 1
        return 1

    def delete_lounge_message_by_client_id(self, user_id, client_id):
        self.thread = [r for r in self.thread if r["client_id"] != client_id]
        return True

    def save_speaker_memory(self, row):
        self.note = row["note"]
        return True


@pytest.fixture
def db(monkeypatch):
    d = _ConsentDb()
    monkeypatch.setattr(Config, "PLAN_CONSENT_ENABLED", True)
    monkeypatch.setattr("services.rings.feature_is_on_for_user", lambda *a, **k: True)
    monkeypatch.setattr(F, "_readings", lambda *a, **k: {})
    # The audience and the length are known, so after the key line the next question is the worry.
    monkeypatch.setattr(F, "_turn", lambda *a, **k: {"facts": {
        "audience": "five board members", "length": "three minutes", "worry": "freezing"}})
    monkeypatch.setattr("services.speaker_memory.record", lambda database, uid, kind, payload, **k: d.memory.append(
        {"id": f"m{len(d.memory)}", "kind": kind, "payload": payload}))
    rebuilt = []
    monkeypatch.setattr("services.speaker_memory.rebuild", lambda *a, **k: rebuilt.append(a))
    monkeypatch.setattr("services.parallel.start_scoped_thread", lambda target, **k: target())
    d.rebuilt = rebuilt
    return d


def _say(db, text):
    return F.answer_voice(db, USER, _Adapter(text), b"audio", filename="a.webm",
                          content_type="audio/webm", duration_ms=4000)


def _to_the_ask(db):
    F.state(db, USER, tz="UTC", first_name="Artur")
    F.answer_deadline(db, USER, (date.today() + timedelta(days=21)).isoformat(), tz="UTC")
    return _say(db, "It's our board pitch for two more hires.")


def _asked(db):
    return [r for r in db.thread if (r["metadata"] or {}).get("plan_ask") == "consent"]


def _active_before_the_switch(db, monkeypatch):
    """A plan made while the switch was off, then the switch on."""
    monkeypatch.setattr(Config, "PLAN_CONSENT_ENABLED", False)
    _to_the_ask(db)
    for said in ("The window closes soon.", "I'm afraid I will freeze.", "Starting with the cost."):
        _say(db, said)
    F.answer_rating(db, USER, 7)
    F.answer_rating(db, USER, 4)
    F.book_call(db, USER, "kickoff", None)
    F.book_call(db, USER, "summary", None)
    monkeypatch.setattr(Config, "PLAN_CONSENT_ENABLED", True)
    return db.get_open_plan(USER)


def test_with_the_switch_off_the_plan_asks_as_before(db, monkeypatch):
    monkeypatch.setattr(Config, "PLAN_CONSENT_ENABLED", False)
    _to_the_ask(db)
    assert _asked(db) == [] and db.consent == []
    assert bodies(db)[-1].startswith("If your audience remembers one sentence")
    assert C.state(db, USER) == C.GRANTED


def test_will_asks_once_and_a_yes_goes_on_with_the_personal_questions(db):
    _to_the_ask(db)
    assert F.state(db, USER, tz="UTC", first_name="Artur")["plan"]["step"] == "consent"
    assert len(_asked(db)) == 1
    assert bodies(db)[-1] == F.P.COPY["consent_ask"]
    with pytest.raises(F.PlanError):  # nothing else is taken while Will waits
        _say(db, "I would rather go on.")
    with pytest.raises(F.PlanError):
        F.answer_rating(db, USER, 7)
    assert db.consent == []

    out = F.answer_consent(db, USER, True)
    assert bodies(db)[-2] == "Yes, ask me"
    assert out["plan"]["step"] == "followup"
    assert bodies(db)[-1].startswith("If your audience remembers one sentence")
    _say(db, "The window closes soon.")
    assert "What worries you most" in bodies(db)[-1]
    _say(db, "I'm afraid I will freeze.")
    kept = db.get_open_plan(USER)
    assert kept["facts"].get("worry") == "freezing"
    assert [r["event_kind"] for r in db.consent] == ["grant"]
    assert db.consent[0]["copy_sha256"] == C.sentence_sha256()
    assert db.consent[0]["policy_version"] == "phase1-2026-10-28-3.9"
    with pytest.raises(F.PlanError):  # asked once: it is answered
        F.answer_consent(db, USER, True)
    assert len(_asked(db)) == 1


def test_not_now_skips_the_personal_questions_and_keeps_the_plan(db):
    _to_the_ask(db)
    F.answer_consent(db, USER, False)
    assert bodies(db)[-2] == "Not now"
    for said in ("The window closes soon.", "Starting with the cost.", "Two years in sales."):
        _say(db, said)
    said = " ".join(bodies(db))
    assert "What worries you most" not in said and "How stressed" not in said
    plan = db.get_open_plan(USER)
    assert "worry" not in plan["facts"] and plan["step"] == "kickoff"
    assert [r["event_kind"] for r in db.consent] == ["decline"]
    F.book_call(db, USER, "kickoff", None)
    F.book_call(db, USER, "summary", None)
    assert bodies(db)[-2] == "You're all set. Here's your plan."
    assert [a for a in db.answers if a["kind"] in ("stress", "ready")] == []
    assert len(_asked(db)) == 1  # never asked again


def test_turning_off_deletes_what_the_speaker_gave(db):
    _to_the_ask(db)
    F.answer_consent(db, USER, True)
    _say(db, "The window closes soon.")
    _say(db, "I'm afraid I will freeze.")
    _say(db, "Starting with the cost.")
    F.answer_rating(db, USER, 7)
    F.answer_rating(db, USER, 4)
    why = next(a for a in db.answers if a["kind"] == "why")
    assert {"worry", "stress", "ready"} <= {a["kind"] for a in db.answers}
    voices = [r for r in db.thread if (r["metadata"] or {}).get("plan_voice")]
    assert len(voices) == 4 and len(db.memory) == 4

    F.set_consent(db, USER, False)

    assert [r["event_kind"] for r in db.consent] == ["grant", "withdraw"]
    assert C.state(db, USER) == C.DECLINED
    left = {a["kind"] for a in db.answers}
    assert left.isdisjoint({"worry", "stress", "ready"})
    assert why in db.answers  # the plan itself stays
    assert why["id"] in db.audio and len(db.audio) == len(db.answers)
    kept = [r["metadata"]["plan_voice"] for r in db.thread if (r["metadata"] or {}).get("plan_voice")]
    assert sorted(kept) == sorted(a["id"] for a in db.answers) and len(kept) == 3
    assert [e["payload"]["question"] for e in db.memory if "worries" in e["payload"]["question"]] == []
    assert len(db.memory) == 3 and db.note == "" and len(db.rebuilt) == 1
    assert db.erased == {"feelings": 1, "worry": 1}
    assert "worry" not in db.get_open_plan(USER)["facts"]
    assert F.set_consent(db, USER, False) == {}  # nothing more to turn off
    assert [r["event_kind"] for r in db.consent] == ["grant", "withdraw"]


def test_a_turn_off_that_fails_leaves_the_yes_on(db):
    _to_the_ask(db)
    F.answer_consent(db, USER, True)
    _say(db, "The window closes soon.")
    db.feelings_fail = True
    with pytest.raises(C.ConsentError, match="feelings"):
        F.set_consent(db, USER, False)
    assert C.state(db, USER) == C.GRANTED and [r["event_kind"] for r in db.consent] == ["grant"]
    db.feelings_fail = False
    F.set_consent(db, USER, False)  # the speaker tries again
    assert C.state(db, USER) == C.DECLINED


def test_a_doubt_means_nothing_personal_is_asked(db):
    db.read_fails = True
    assert C.state(db, USER) == C.DECLINED
    _to_the_ask(db)
    assert _asked(db) == []  # no ask on a doubt: and nothing personal
    for said in ("The window closes soon.", "Starting with the cost.", "Two years in sales."):
        _say(db, said)
    assert "What worries you most" not in " ".join(bodies(db))
    assert db.get_open_plan(USER)["step"] == "kickoff"


def test_a_yes_that_cannot_be_kept_is_not_a_yes(db):
    db.keep_fails = True
    _to_the_ask(db)
    F.answer_consent(db, USER, True)
    assert db.consent == [] and C.state(db, USER) == C.UNANSWERED
    assert "What worries you most" not in " ".join(bodies(db))
    _say(db, "The window closes soon.")  # the worry is next: Will asks again, first
    assert len(_asked(db)) == 2 and db.get_open_plan(USER)["facts"].get("awaiting") == "consent"


@pytest.mark.parametrize("yes", [True, False])
def test_the_last_ratings_wait_for_the_yes(db, monkeypatch, yes):
    plan = _active_before_the_switch(db, monkeypatch)
    db.update_plan(USER, plan["id"], {"total": 1})
    started = datetime.fromisoformat(plan["started_at"])
    db.takes.rows = [{"created_at": (started + timedelta(minutes=5)).isoformat(),
                      "arc_id": "arc-1", "take_index": 1}]
    F.after_take(db, USER)
    assert bodies(db)[-1] == F.P.COPY["consent_ask"] and len(_asked(db)) == 1
    F.answer_consent(db, USER, yes)
    if yes:
        assert bodies(db)[-1] == "How stressed do you feel about it right now?"
    else:
        assert "How stressed do you feel about it right now?" not in bodies(db)[-2:]
        assert db.get_open_plan(USER)["step"] == "done"
        F.after_take(db, USER)
        assert len(_asked(db)) == 1  # not asked again


@pytest.mark.parametrize("yes", [True, False])
def test_the_plans_end_asks_for_the_yes_before_how_did_it_go(db, monkeypatch, yes):
    plan = _active_before_the_switch(db, monkeypatch)
    monkeypatch.setattr(F, "today_in", lambda name: date.fromisoformat(plan["deadline"]) + timedelta(days=1))
    F.state(db, USER, tz="UTC", first_name="Artur")
    assert bodies(db)[-1] == F.P.COPY["consent_ask"]
    assert F.P.COPY["how_did_it_go"] not in bodies(db)
    F.answer_consent(db, USER, yes)
    if yes:
        assert bodies(db)[-1] == F.P.COPY["how_did_it_go"]
        assert db.get_open_plan(USER)["step"] == "how_it_went"
    else:
        assert F.P.COPY["how_did_it_go"] not in bodies(db)
        assert F.P.COPY["thanks_told"] not in bodies(db)
        assert bodies(db)[-1] == F.P.COPY["whats_next"]
        assert db.get_open_plan(USER)["step"] == "whats_next"
