#!/usr/bin/env python3
"""
Verify that every (theme, cursor, mode) combination yields >= 3 command options
using the same fallback chain as POST /session/start. No app imports required.

Run: python3 verify_command_options_coverage.py
"""
# --- Inline copy of theme/intent/command data (must match question_service.py) ---
THEMES = [
    "presence_grounding", "clarity_simplicity", "pacing_rhythm", "energy_conviction",
    "confidence_comfort", "structure_organization", "story_narrative",
]
INTENT_TO_THEME = {
    "permission_imperfect": "presence_grounding", "micro_start": "presence_grounding",
    "gentle_checkin": "presence_grounding", "breath_voice": "presence_grounding",
    "describe_obvious": "clarity_simplicity", "explain_simply": "clarity_simplicity",
    "simple_opinion": "energy_conviction", "strong_opinion": "energy_conviction",
    "energy_push": "energy_conviction", "cheeky_pressure": "energy_conviction",
    "short_memory": "confidence_comfort", "personal_reflection": "confidence_comfort",
    "reading_aloud": "structure_organization", "list_format": "structure_organization",
    "teach_back": "structure_organization",
    "slow_clarity": "pacing_rhythm", "time_constraint": "pacing_rhythm",
    "no_fillers_challenge": "pacing_rhythm",
    "neutral_story": "story_narrative", "contrast": "story_narrative",
}
# intent, cursor_range, mode (minimal for filtering)
COMMANDS = [
    ("permission_imperfect", (0.00, 0.15), ["guided", "open"]),
    ("micro_start", (0.00, 0.15), ["guided", "open"]),
    ("gentle_checkin", (0.00, 0.15), ["guided", "open"]),
    ("breath_voice", (0.00, 0.15), ["guided", "open"]),
    ("describe_obvious", (0.15, 0.30), ["guided", "open"]),
    ("simple_opinion", (0.15, 0.30), ["guided", "open"]),
    ("short_memory", (0.15, 0.30), ["guided", "open"]),
    ("reading_aloud", (0.15, 0.30), ["guided"]),
    ("explain_simply", (0.30, 0.45), ["guided", "open"]),
    ("list_format", (0.30, 0.45), ["guided", "open"]),
    ("slow_clarity", (0.30, 0.45), ["guided", "open"]),
    ("neutral_story", (0.30, 0.45), ["guided", "open"]),
    ("personal_reflection", (0.45, 0.60), ["guided", "open"]),
    ("teach_back", (0.45, 0.60), ["guided", "open"]),
    ("contrast", (0.45, 0.60), ["guided", "open"]),
    ("time_constraint", (0.45, 0.60), ["guided", "open"]),
    ("strong_opinion", (0.60, 0.80), ["guided", "open"]),
    ("energy_push", (0.60, 0.80), ["guided", "open"]),
    ("no_fillers_challenge", (0.60, 0.80), ["guided", "open"]),
    ("cheeky_pressure", (0.60, 0.80), ["guided", "open"]),
]


def _cmd(intent, cursor_range, mode):
    return {"intent": intent, "cursor_range": cursor_range, "mode": mode}


def filter_strict(theme_code, cursor, effective_mode, no_fillers_eligible):
    out = []
    for intent, cr, mode in COMMANDS:
        if INTENT_TO_THEME.get(intent) != theme_code:
            continue
        if not (cr[0] <= cursor <= cr[1]):
            continue
        if effective_mode not in mode:
            continue
        if intent == "reading_aloud" and effective_mode == "open":
            continue
        if intent == "no_fillers_challenge" and not no_fillers_eligible:
            continue
        out.append(_cmd(intent, cr, mode))
    return out


def theme_ignore_cursor(theme_code, effective_mode, no_fillers_eligible):
    out = []
    for intent, cr, mode in COMMANDS:
        if INTENT_TO_THEME.get(intent) != theme_code:
            continue
        if effective_mode not in mode:
            continue
        if intent == "reading_aloud" and effective_mode == "open":
            continue
        if intent == "no_fillers_challenge" and not no_fillers_eligible:
            continue
        out.append(_cmd(intent, cr, mode))
    return out


def any_theme(effective_mode, no_fillers_eligible):
    out = []
    for intent, cr, mode in COMMANDS:
        if effective_mode not in mode:
            continue
        if intent == "reading_aloud" and effective_mode == "open":
            continue
        if intent == "no_fillers_challenge" and not no_fillers_eligible:
            continue
        out.append(_cmd(intent, cr, mode))
    return out


def run_fallback_chain(theme_chosen, cursor, effective_mode, no_fillers_eligible):
    recent_codes = []
    candidates = filter_strict(theme_chosen, cursor, effective_mode, no_fillers_eligible)
    candidates = [c for c in candidates if c["intent"] not in recent_codes]
    seen_intents = {c["intent"] for c in candidates}

    if len(candidates) < 3:
        for c in theme_ignore_cursor(theme_chosen, effective_mode, no_fillers_eligible):
            if c["intent"] not in recent_codes and c["intent"] not in seen_intents:
                candidates.append(c)
                seen_intents.add(c["intent"])
                if len(candidates) >= 5:
                    break

    if len(candidates) < 3:
        for c in any_theme(effective_mode, no_fillers_eligible):
            if c["intent"] not in recent_codes and c["intent"] not in seen_intents:
                candidates.append(c)
                seen_intents.add(c["intent"])
                if len(candidates) >= 5:
                    break

    if len(candidates) < 3:
        for c in any_theme(effective_mode, no_fillers_eligible):
            if c["intent"] not in seen_intents:
                candidates.append(c)
                seen_intents.add(c["intent"])
                if len(candidates) >= 5:
                    break

    return candidates[:3]


def main():
    cursor_samples = [0.08, 0.225, 0.375, 0.525, 0.70]
    modes = ["guided", "open"]
    no_fillers_cases = [False, True]
    failed = []
    for theme in THEMES:
        for cursor in cursor_samples:
            for mode in modes:
                for no_fillers in no_fillers_cases:
                    selected = run_fallback_chain(theme, cursor, mode, no_fillers)
                    if len(selected) < 3:
                        failed.append((theme, cursor, mode, no_fillers, len(selected)))

    if failed:
        print("FAIL: Some combinations yield < 3 options:\n")
        for theme, cursor, mode, no_fillers, n in failed:
            print(f"  theme={theme!r} cursor={cursor} mode={mode!r} no_fillers={no_fillers} -> {n} options")
        print(f"\nTotal failing: {len(failed)}")
        return 1

    print("PASS: All combinations yield >= 3 options.")
    print("\nChecked: 7 themes x 5 cursor values x 2 modes x 2 no_fillers = 140 combinations.")
    print("Strict-only (theme+cursor+mode) min counts per theme:")
    for theme in THEMES:
        counts = []
        for cursor in cursor_samples:
            for mode in modes:
                counts.append(len(filter_strict(theme, cursor, mode, False)))
        print(f"  {theme}: min={min(counts)} max={max(counts)}")
    print("\nTheme-ignore-cursor sizes (options per theme before any-theme fallback):")
    for theme in THEMES:
        n_guided = len(theme_ignore_cursor(theme, "guided", False))
        n_open = len(theme_ignore_cursor(theme, "open", False))
        print(f"  {theme}: guided={n_guided} open={n_open}")
    return 0


if __name__ == "__main__":
    exit(main())
