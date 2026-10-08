"""V4 B1.3: willfidence-v1-machine, the pure rules (build plan D-ML-8;
founder S-B1 A, S-B1b A, V4 A, V5 B, V6 A, W1, W2, H3). The database's
copy is pinned equal in tests/test_the_machine_reads_willfidence_postgres.py.
"""
from __future__ import annotations

import pathlib

import pytest

from services import v4_take_tags as tags
from services import willfidence as wf
from services.data_purge_registry import DEPENDENCIES

ROOT = pathlib.Path(__file__).resolve().parents[1]


# ── S (V4 A) ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("score,s", [(-1, 0.0), (0, 0.5), (1, 1.0), (0.5, 0.75)])
def test_the_sound_read_is_stretched_evenly(score, s):
    assert wf.stretch(score) == s


@pytest.mark.parametrize("score", [1.01, -1.5, None, True, "0.2"])
def test_a_sound_read_out_of_range_is_no_read(score):
    assert wf.stretch(score) is None


def test_s_averages_only_universal_v3_reads():
    clips = [
        {"voice_confidence": {"version": wf.SOUND_VERSION, "score": 0.2}},
        {"voice_confidence": {"version": wf.SOUND_VERSION, "score": -0.6}},
        {"voice_confidence": {"version": "voice-confidence-v2", "score": 0.9}},
        {"voice_confidence": {"version": wf.SOUND_VERSION, "score": 3}},
        None, {},
    ]
    assert wf.sound(clips) == pytest.approx(((0.2 - 0.6) / 2 + 1) / 2)
    assert wf.sound([{}, None]) is None


# ── Filler and Hedging (S-B1 A, V5 B) ──────────────────────────────────────

def _words(n, extra=""):
    return " ".join(["word"] * n) + (" " + extra if extra else "")


def test_no_filler_reads_one_and_ten_per_hundred_reads_zero():
    assert wf.filler(_words(100)) == 1.0
    assert wf.filler(_words(90, " ".join(["um"] * 10))) == 0.0
    assert wf.filler(_words(80, " ".join(["um"] * 20))) == 0.0


def test_the_filler_scale_is_a_straight_line():
    # 5 fillers in 100 words: 5 per 100 -> 0.5.
    assert wf.filler(_words(95, "um uh erm basically literally")) == pytest.approx(0.5)


def test_so_like_and_right_never_count_as_fillers():
    assert wf.filler(_words(90, "so like right so like right so like")) == 1.0
    for term in ("so", "like", "right", "you know", "actually"):
        assert term not in wf.FILLER_TERMS


def test_the_filler_list_is_the_signed_unambiguous_one():
    for term in ("um", "uh", "erm", "basically", "literally"):
        assert term in wf.FILLER_TERMS


def test_hedging_counts_unambiguous_hedges_and_never_modals():
    assert wf.hedging(_words(98, "maybe probably")) == pytest.approx(0.8)
    assert wf.hedging(_words(90, "might could may would should")) == 1.0
    for term in ("sort of", "i think", "maybe", "probably", "perhaps"):
        assert term in wf.HEDGE_TERMS
    for term in ("might", "could", "may", "would"):
        assert term not in wf.HEDGE_TERMS


def test_no_words_is_no_read():
    assert wf.filler("") is None
    assert wf.hedging(None) is None


# ── Slide fit (S-B1 A) ─────────────────────────────────────────────────────

def test_slide_fit_takes_the_best_clip_of_the_point_check():
    clips = [{"slide_stickiness": {"composite": 0.0}},
             {"slide_stickiness": {"composite": 0.5}}, {}]
    assert wf.slide_fit(clips) == 0.5
    assert wf.slide_fit([{"slide_stickiness": {"composite": 1.0}}]) == 1.0
    assert wf.slide_fit([{}, None]) is None
    assert wf.slide_fit([{"slide_stickiness": {"composite": 0.33}}]) is None


# ── W, boxes, spread, status (H3, W1, W2) ──────────────────────────────────

def test_partial_w_is_the_mean_of_the_signals_present():
    assert wf.partial_w(1.0, 0.5, None, 0.0) == pytest.approx(0.5)
    assert wf.partial_w(None, None) is None


def test_the_four_boxes_add_to_one():
    b = wf.boxes(0.8, 0.25)
    assert b == pytest.approx({"willfident": 0.2, "hollow": 0.6,
                               "hidden": 0.05, "lost": 0.15})
    assert sum(b.values()) == pytest.approx(1.0)
    assert wf.boxes(None, 0.5) is None


@pytest.mark.parametrize("random_moments,rated,expected", [
    (10, 10, "measured"), (13, 10, "measured"), (15, 10, "audio_problem"),
    (10, 7, "not_enough_data"), (10, 6, "audio_problem"), (3, 3, "not_enough_data"),
    (0, 0, "not_enough_data"),
])
def test_w2_status(random_moments, rated, expected):
    assert wf.status(random_moments, rated) == expected


def test_the_take_line_averages_rated_random_moments_only():
    reads = [
        {"is_random": True, "s": 0.8, "w": 0.5},
        {"is_random": True, "s": 0.4, "w": 1.0},
        {"is_random": True, "s": None, "w": 0.5},
        {"is_random": False, "s": 1.0, "w": 1.0},
    ]
    line = wf.summary(reads)
    assert line["willfidence"] == pytest.approx(0.4)
    assert line["random_moments"] == 3
    assert line["rated_random_moments"] == 2
    assert line["status"] == "audio_problem"


# ── the Take's reads ───────────────────────────────────────────────────────

def test_take_reads_send_every_block_with_its_word_signals_only():
    frame = {"blocks": [
        {"block_id": "b1", "snippet_ids": ["c1", "c2"]},
        {"block_id": "b2", "snippet_ids": ["c3"]},
    ]}
    snippets = [
        {"id": "c1", "transcript": "um we grew", "metrics": {
            "slide_stickiness": {"composite": 0.5},
            "voice_confidence": {"version": wf.SOUND_VERSION, "score": 0.9}}},
        {"id": "c2", "transcript": "fast this year", "metrics": {}},
        {"id": "c3", "transcript": "", "metrics": {}},
    ]
    reads = wf.take_reads(frame, snippets, {"b1": {"role": "main_point",
                                                   "holding_together": 1.0}})
    assert [r["block_id"] for r in reads] == ["b1", "b2"]
    assert reads[0]["slide_fit"] == 0.5
    assert reads[0]["role"] == "main_point"
    assert reads[0]["holding_together"] == 1.0
    assert reads[1] == {"block_id": "b2", "filler": None, "hedging": None,
                        "slide_fit": None, "holding_together": None, "role": None}
    # S is the database's to compute from the clips; the app never sends it.
    assert all(not {"s", "w", "willfident"} & set(r) for r in reads)


# ── the one call per Take (S-B1b A) ────────────────────────────────────────

def test_the_roles_are_the_signed_version_one():
    assert tags.ROLE_WEIGHTS == {"opening": 1.0, "main_point": 1.0, "close": 1.0,
                                 "evidence": 0.7, "transition": 0.4, "aside": 0.2}
    assert tags.ROLES_VERSION == "v4-moment-roles-v1"


def test_the_answer_is_parsed_per_ref_and_never_trusted():
    parsed = tags.parse({"moments": [
        {"ref": "a", "role": "evidence", "holds_together": "partly"},
        {"ref": "b", "role": "keynote", "holds_together": "yes"},
        {"ref": "c", "role": "aside", "holds_together": "no"},
        {"ref": "c", "role": "close", "holds_together": "yes"},
        {"ref": "zzz", "role": "aside", "holds_together": "no"},
    ]}, ["a", "b", "c"])
    assert parsed == {"a": {"role": "evidence", "holding_together": 0.5},
                      "b": {"role": None, "holding_together": 1.0}}
    assert tags.parse("nope", ["a"]) is None
    assert tags.parse({"moments": []}, ["a"]) is None


def test_the_call_failing_gives_no_tags(monkeypatch):
    import services.llm as llm

    def boom(**_):
        raise RuntimeError("provider down")
    monkeypatch.setattr(llm, "chat_complete", boom)
    assert tags.tag_take([{"ref": "a", "text": "hello"}]) is None
    assert tags.tag_take([]) is None


def test_the_prompt_is_registered_and_names_every_role():
    from services.prompts.v4_take_tags import REGISTER, SYSTEM
    assert "v4_take_tags.system" in REGISTER
    for role in tags.ROLES:
        assert f'"{role}"' in SYSTEM
    # The weights stay inside the machine: the call never sees them.
    assert "0.7" not in SYSTEM and "weight" not in SYSTEM.lower()


# ── wiring and fences ──────────────────────────────────────────────────────

def test_the_read_is_queued_once_the_moments_are_first_drawn():
    source = (ROOT / "services" / "ideal_text_changes.py").read_text()
    drawn = source.index('get("outcome") == "drawn"')
    queued = source.index("enqueue_read(_arm_sid)")
    assert drawn < queued


def test_the_job_never_raises(monkeypatch):
    import services.db as dbmod

    class Boom:
        def get_v4_dark_frame(self, take):
            raise RuntimeError("db down")
    monkeypatch.setattr(dbmod, "db", Boom())
    assert wf.run_read("t") is None


def test_the_reads_go_with_the_take_in_the_purge_registry():
    rows = {d.code: d for d in DEPENDENCIES}
    for code in ("v4_willfidence_reads", "v4_willfidence_takes"):
        assert (rows[code].relation, rows[code].selector_column,
                rows[code].disposition) == (code, "take_session_id", "delete")


def test_no_route_reads_willfidence():
    """AC-9: no route names the read, its tables or its functions."""
    for path in (ROOT / "routes").rglob("*.py"):
        text = path.read_text()
        for name in ("willfidence", "v4_take_tags", "v4_speaker_willfidence"):
            assert name not in text, (path, name)
