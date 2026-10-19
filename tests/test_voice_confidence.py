"""
STORY    As the founder, I want each moment's confidence read to stay on the
         server, stay neutral when a clip is middling and stay silent when it
         cannot read, so that the moments we praise are right.
OUTCOME
  O1  Every measurable piece is stamped with the current read: a score in
      [-1, 1], an internal band and the version.
  O2  A middling clip reads exactly 0.0 (neutral), never forced to a pole.
  O3  No baseline, or too few measurable cues, stamps nothing: silence,
      never an invented 0.0.
  O4  NEVER-1: the stamped read never reaches what a speaker is served
      (here the "practise new" queue built from the same pieces).
PROVES   O1 -> test_attach_stamps_every_measurable_piece
         O2 -> test_a_middling_clip_reads_neutral
         O3 -> test_no_baseline_or_too_few_cues_stamps_nothing
         O4 -> test_the_read_never_reaches_a_speaker_payload
WHY      Founder spec 2026-07-27 (Jiang & Pell 2017); AC-9. Cue DIRECTIONS
         are ML behaviour and belong in the golden evaluation set, not here.
"""
from __future__ import annotations

import json

from services.voice_album_practice_queue import build_practice_queue
from services.voice_confidence import BAND_NEUTRAL, BANDS, VERSION, attach_voice_confidence

# Every feature has mean 0.0 and sd 1.0, so a raw metric value IS its z-score.
_UNIT_BASELINE = {f: (0.0, 1.0) for f in (
    "f0_sd", "dynamic_db", "f0_mean", "wpm", "pause_ratio", "pause_ms",
    "f0_mid_end_delta", "intensity_envelope")}
_FLAT = {f: 0.0 for f in _UNIT_BASELINE}


def _pieces(n=6):
    return [{"id": f"s{i}", "metrics": {**_FLAT, "f0_sd": float(i)}} for i in range(n)]


def test_attach_stamps_every_measurable_piece():
    pieces = _pieces()
    attach_voice_confidence(pieces, baseline=_UNIT_BASELINE, baseline_kind="user")
    for piece in pieces:
        read = piece["metrics"]["voice_confidence"]
        assert read["version"] == VERSION and read["baseline"] == "user"
        assert read["band"] in BANDS
        assert -1.0 <= read["score"] <= 1.0
        assert "sex" not in read and "sex_source" not in read


def test_a_middling_clip_reads_neutral():
    # A small lean on one cue stays inside the dead zone.
    pieces = [{"metrics": {**_FLAT, "dynamic_db": 0.5}}]
    attach_voice_confidence(pieces, baseline=_UNIT_BASELINE)
    read = pieces[0]["metrics"]["voice_confidence"]
    assert (read["score"], read["band"]) == (0.0, BAND_NEUTRAL)


def test_no_baseline_or_too_few_cues_stamps_nothing():
    unread = _pieces(1)
    attach_voice_confidence(unread, baseline=None)
    assert "voice_confidence" not in unread[0]["metrics"]
    sparse = [{"metrics": {"f0_sd": 2.0, "wpm": 2.0}}]
    attach_voice_confidence(sparse, baseline=_UNIT_BASELINE)
    assert "voice_confidence" not in sparse[0]["metrics"]


class _Db:
    def __init__(self, snippets):
        self.snippets = snippets

    def get_moment_suggestions_by_arc(self, _arc):
        return {s["id"]: {"kind": "emphasize", "trigger": "confident"} for s in self.snippets}

    def list_confident_voice_self_reports(self, _arc):
        return []

    def list_owner_voice_album_routes(self, _arc):
        return []

    def get_snippets_by_session(self, _sid):
        return self.snippets


def test_the_read_never_reaches_a_speaker_payload():
    pieces = _pieces()
    attach_voice_confidence(pieces, baseline=_UNIT_BASELINE)
    assert all("voice_confidence" in p["metrics"] for p in pieces)
    queue = build_practice_queue(
        sessions_by_arc={"arc-1": [{"id": "t1", "take_index": 1}]}, database=_Db(pieces))
    assert [row["snippet_id"] for row in queue] == [p["id"] for p in pieces]
    flat = json.dumps(queue)
    for banned in ("voice_confidence", "score", "band", "delivery_signal", VERSION, "metrics"):
        assert banned not in flat, banned
