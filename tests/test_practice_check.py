"""The machine checks each practise try (founder lock 2026-10-06, the
Feedback walk; decisions log N52.3). On; its switch was deleted 2026-10-11.

Pins: the speaker is never asked; a try measurably better than the original
(the targeted problem cleared, a cue moved, or the machine leg higher) is
praise and closes the practice on that try; anything else is again, with
the encouragement's step or effort key; a rewrite practice is praised, never
measured against the original; the decision is never written as the
speaker's answer (L3); the screen sees only the outcome and the line key
(AC-9); the moment counts as settled and its helper words can be tapped; the
route is off until the walk's screens ship.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


# ── the decision ──────────────────────────────────────────────────────────


# ── the loop ──────────────────────────────────────────────────────────────


# ── what a machine-closed practice means elsewhere ───────────────────────


# ── the route ──────────────────────────────────────────────

def test_the_route_is_fenced_and_hides_the_measure():
    source = (ROOT / "routes/v2/user_sessions.py").read_text()
    start = source.index("def v2_check_confident_voice_practice_attempt")
    route = source[start:source.index("@v2_bp.route", start)]
    assert "machine_practice_check_enabled" not in route
    head = source[source.rindex("@v2_bp.route", 0, start):start]
    assert '"<attempt_id>/check", methods=["POST"]' in head
    for fence in ("@require_auth", 'operational_purpose_disabled("personalized_exercise_recommendation")',
                  'consent_choice_required("personalised_practice")'):
        assert fence in head
    assert '"after_practice": _after_practice_public(' in source


# ── the third try that is not praise (CM3a A, CM3b A; decisions log N55) ──
