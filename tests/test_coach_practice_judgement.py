"""The coach's judgement of a practice recording comes back (founder
2026-10-05, Q6; N45).

Pins: the Read screen carries the speaker's chosen recording and the
coach's own saved answer, never the machine's read; the save takes one of
the five answers on the selected attempt only, records the after-practice
result and reconciles the Album; the route sits behind the blind gate and
the speaker's practice choice.
"""
from __future__ import annotations

import pathlib
from unittest import mock

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _quiet_side_effects():
    with mock.patch("services.practice_more_confident.record_after_coach_decision") as after, \
            mock.patch("services.confident_voice_practice.reconcile_practice_voice_album",
                       return_value=False) as album, \
            mock.patch("services.audio_ref_resolver.resolve_playable_ref",
                       side_effect=lambda ref: f"https://media/{ref}"):
        yield after, album


def test_the_route_sits_behind_the_blind_gate_and_the_speakers_choice():
    source = (ROOT / "routes/v2/coach.py").read_text()
    start = source.index("def v2_coach_practice_judgement(")
    head = source[:start].rsplit("@v2_bp.route", 1)[1]
    body = source[start:source.index("\n@v2_bp.route", start)]
    assert "/practice-judgement" in head
    assert "@require_admin_or_coach" in head
    assert body.index("_moment_gate(session_id, snippet_id)") < body.index("judge_selected_attempt")
    assert body.index("_speaker_practice_permitted") < body.index("judge_selected_attempt")


# ── LOCKIN §5c, contract 34 (W6 2026-10-05): written once ──────────────────
