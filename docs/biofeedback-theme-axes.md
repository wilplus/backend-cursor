# Biofeedback theme → axes (for LLM or manual profile design)

Use this when proposing or tuning **biofeedback profiles per theme** (dartboard axes + targets). Backend already maps `theme_chosen_code` → profile in `services/biofeedback_service.py`; this file is the reference for theme codes and intent mapping.

---

## Theme codes (THEMES)

```text
presence_grounding
clarity_simplicity
pacing_rhythm
energy_conviction
confidence_comfort
structure_organization
story_narrative
```

---

## Intent → theme (INTENT_TO_THEME)

Each recording “task” has an **intent**; the session’s **theme** is chosen first, then commands (intents) are filtered by theme. So a session has one theme and one selected intent per recording.

| intent                 | theme_code            |
|------------------------|-----------------------|
| permission_imperfect   | presence_grounding    |
| micro_start            | presence_grounding    |
| gentle_checkin         | presence_grounding    |
| breath_voice           | presence_grounding    |
| describe_obvious       | clarity_simplicity    |
| explain_simply         | clarity_simplicity    |
| simple_opinion         | energy_conviction     |
| strong_opinion         | energy_conviction     |
| energy_push            | energy_conviction     |
| cheeky_pressure        | energy_conviction     |
| short_memory           | confidence_comfort    |
| personal_reflection    | confidence_comfort    |
| list_format            | structure_organization|
| teach_back             | structure_organization|
| slow_clarity           | pacing_rhythm         |
| time_constraint        | pacing_rhythm         |
| no_fillers_challenge   | pacing_rhythm         |
| neutral_story          | story_narrative       |
| contrast               | story_narrative       |

---

## Axis metrics (client-side)

- **loudness_db** — RMS-based, dB-like scale (e.g. target center -25, radius 6).
- **speech_rate_proxy** — VAD + voiced-frame density / “syllable-ish” proxy (no STT); target e.g. center 4.0, radius 1.0.
- **steadiness_proxy** — e.g. low variance of loudness over a short window; target center 0.5, radius 0.25.

---

## v1 profiles (already in backend)

- **pacing_rhythm:** pace, strength  
- **presence_grounding:** strength, steadiness  
- **clarity_simplicity:** strength, pace  
- **energy_conviction:** strength, pace  
- **confidence_comfort:** strength, steadiness  
- **structure_organization:** pace, strength  
- **story_narrative:** pace, strength  
- **default (unknown theme):** strength, pace  

---

## For LLM: what to propose

1. **v1:** 2-axis profile per theme (from the list above): which two of `strength` / `pace` / `steadiness` (or later `variation` / `intonation`) and suggested `target.center` / `target.radius` if you want to refine.
2. **v2:** How to add a 3rd axis (e.g. variation/intonation) using transcript or post-hoc signals first, then live later.
