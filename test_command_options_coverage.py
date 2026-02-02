"""
Verify that every (theme, cursor, mode) combination yields >= 3 command options
using the same fallback chain as POST /session/start.

Run (with venv): pytest test_command_options_coverage.py -v
Or: python -m pytest test_command_options_coverage.py -v
"""
import pytest
from services.question_service import (
    THEMES,
    filter_commands_for_theme_cursor_mode,
    get_commands_for_theme_ignore_cursor,
    get_commands_for_mode_any_theme,
)


def run_fallback_chain(theme_chosen, cursor, effective_mode, no_fillers_eligible):
    """Same logic as routes/session.py: strict -> theme-ignore-cursor -> any-theme -> guarantee >= 3."""
    recent_codes = []
    candidates = filter_commands_for_theme_cursor_mode(
        theme_chosen, cursor, effective_mode, no_fillers_eligible
    )
    candidates = [c for c in candidates if c["intent"] not in recent_codes]
    seen_intents = {c["intent"] for c in candidates}

    if len(candidates) < 3:
        extra = get_commands_for_theme_ignore_cursor(
            theme_chosen, effective_mode, no_fillers_eligible
        )
        for c in extra:
            if c["intent"] not in recent_codes and c["intent"] not in seen_intents:
                candidates.append(c)
                seen_intents.add(c["intent"])
                if len(candidates) >= 5:
                    break

    if len(candidates) < 3:
        any_theme = get_commands_for_mode_any_theme(effective_mode, no_fillers_eligible)
        for c in any_theme:
            if c["intent"] not in recent_codes and c["intent"] not in seen_intents:
                candidates.append(c)
                seen_intents.add(c["intent"])
                if len(candidates) >= 5:
                    break

    if len(candidates) < 3:
        any_theme = get_commands_for_mode_any_theme(effective_mode, no_fillers_eligible)
        for c in any_theme:
            if c["intent"] not in seen_intents:
                candidates.append(c)
                seen_intents.add(c["intent"])
                if len(candidates) >= 5:
                    break

    return candidates[:3]


# One cursor value per tier (mid-band)
CURSOR_SAMPLES = [0.08, 0.225, 0.375, 0.525, 0.70]
MODES = ["guided", "open"]


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("cursor", CURSOR_SAMPLES)
@pytest.mark.parametrize("mode", MODES)
@pytest.mark.parametrize("no_fillers_eligible", [False, True])
def test_every_theme_cursor_mode_has_at_least_three_options(theme, cursor, mode, no_fillers_eligible):
    """Every (theme, cursor, mode) must yield >= 3 command options (A/B/C)."""
    selected = run_fallback_chain(theme, cursor, mode, no_fillers_eligible)
    assert len(selected) >= 3, (
        f"theme={theme!r} cursor={cursor} mode={mode!r} no_fillers={no_fillers_eligible} "
        f"yielded only {len(selected)} options"
    )


def test_theme_ignore_cursor_sizes():
    """Each theme must have at least 1 intent for each mode (so theme-ignore-cursor is never empty for guided)."""
    for theme in THEMES:
        for mode in MODES:
            cmds = get_commands_for_theme_ignore_cursor(theme, mode, False)
            assert len(cmds) >= 1, f"theme={theme!r} mode={mode!r} has 0 intents (theme-ignore-cursor)"


def test_any_theme_has_many_options():
    """Any-theme fallback must offer >= 3 options per mode (so we can always fill to 3)."""
    for mode in MODES:
        cmds = get_commands_for_mode_any_theme(mode, False)
        assert len(cmds) >= 3, f"mode={mode!r} has only {len(cmds)} commands (any-theme fallback)"
    guided = get_commands_for_mode_any_theme("guided", False)
    assert len(guided) >= 3
    open_mode = get_commands_for_mode_any_theme("open", False)
    assert len(open_mode) >= 3
