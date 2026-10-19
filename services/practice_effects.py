"""One person's exercises, as facts (founder 2026-10-18, Linear WIL-29;
concept docs/CONCEPT-per-user-exercise-effectiveness-2026-10-18.md, v1;
decided in chat: "build option 1", "founder only").

For each library exercise this person practised, counts in words, never a
rate: did the machine hear it better right away, did the coach hear it
get better, what did they answer themselves, did it hold into
their next Take of the same project, and how far they went with it.

The speaker's answer, the coach's and the machine's stay separate lines
(L3); nothing here merges them into a verdict. Below ``TOO_FEW`` practices
an exercise is marked too few to read, so no one reads a pattern into one
or two tries.

Founder only, by the route that serves it. Never a speaker's screen, never
a coach's (AC-9).
"""
from __future__ import annotations

from typing import Any, Iterable

#: Below this many practices of one exercise, the page says "too few to read".
TOO_FEW = 5
VERSION = "practice-effects-v1"


def _rows(query: Any) -> list[dict]:
    return [r for r in (query.execute().data or []) if isinstance(r, dict)]


def _by_practice(rows: Iterable[dict], key: str) -> dict[str, str]:
    return {str(r.get("practice_id")): str(r.get(key) or "")
            for r in rows if r.get("practice_id")}


def _empty(exercise_id: str, title: str) -> dict:
    return {
        "exercise_id": exercise_id, "title": title, "practices": 0,
        "too_few": True,
        "right_away": {"better": 0, "not_yet": 0, "not_checked": 0},
        "coach": {"agreed": 0, "did_not": 0, "waiting": 0},
        "own_answer": {"yes": 0, "no": 0, "none": 0},
        "next_take": {"held": 0, "came_back": 0, "unknown": 0, "waiting": 0},
        "tries": {"none": 0, "one": 0, "two": 0, "three": 0},
        "skipped": 0,
    }


def summarize(practices: list[dict], *, tries: dict[str, int],
              coach: dict[str, str], held: dict[str, str],
              titles: dict[str, str]) -> dict:
    """Pure: the per-exercise facts from the rows already read."""
    out: dict[str, dict] = {}
    for p in practices:
        exercise_id = str(p.get("exercise_id") or "")
        if not exercise_id:
            continue
        pid = str(p.get("id"))
        slot = out.setdefault(exercise_id, _empty(
            exercise_id, titles.get(exercise_id) or exercise_id))
        slot["practices"] += 1
        said = p.get("after_practice")
        nxt = said.get("next") if isinstance(said, dict) else None
        slot["right_away"]["better" if nxt == "praise" else
                           "not_yet" if nxt in ("again", "moved_on") else
                           "not_checked"] += 1
        slot["coach"]["agreed" if coach.get(pid) == "yes" else
                      "did_not" if coach.get(pid) == "no" else
                      "waiting"] += 1
        answer = p.get("final_user_answer")
        slot["own_answer"][answer if answer in ("yes", "no") else "none"] += 1
        slot["next_take"][held.get(pid) if held.get(pid) in
                          ("held", "came_back", "unknown") else "waiting"] += 1
        n = min(int(tries.get(pid) or 0), 3)
        slot["tries"][("none", "one", "two", "three")[n]] += 1
        if p.get("status") == "dismissed":
            slot["skipped"] += 1
    for slot in out.values():
        slot["too_few"] = slot["practices"] < TOO_FEW
    exercises = sorted(out.values(), key=lambda s: (-s["practices"], s["title"]))
    return {"version": VERSION, "too_few_below": TOO_FEW, "exercises": exercises}


def for_person(database: Any, user_id: str) -> dict:
    """Read this person's library-exercise practices and what each led to."""
    client = database.client
    practices = [p for p in _rows(
        client.table("confident_voice_practice")
        .select("id,exercise_id,status,kind,after_practice,final_user_answer")
        .eq("owner_user_id", str(user_id)))
        if (p.get("kind") or "exercise") == "exercise" and p.get("exercise_id")]
    ids = [str(p["id"]) for p in practices]
    tries: dict[str, int] = {}
    coach: dict[str, str] = {}
    held: dict[str, str] = {}
    titles: dict[str, str] = {}
    for start in range(0, len(ids), 100):
        chunk = ids[start:start + 100]
        for row in _rows(client.table("confident_voice_practice_attempt")
                         .select("practice_id").in_("practice_id", chunk)):
            pid = str(row.get("practice_id"))
            tries[pid] = tries.get(pid, 0) + 1
        # The coach's own leg (0388, 0391): their blind rating of the
        # original against their answer on the attempt. Not the combined
        # outcome, which also reads the machine (L3: each voice its own line).
        coach.update(_by_practice(_rows(
            client.table("practice_more_confident_outcomes")
            .select("practice_id,coach_leg").in_("practice_id", chunk)), "coach_leg"))
        held.update(_by_practice(_rows(
            client.table("exercise_held_next_take_outcomes")
            .select("practice_id,outcome").in_("practice_id", chunk)), "outcome"))
    exercise_ids = sorted({str(p["exercise_id"]) for p in practices})
    if exercise_ids:
        titles = {str(r.get("exercise_id")): str(r.get("title") or "")
                  for r in _rows(client.table("diagnostic_exercise")
                                 .select("exercise_id,title")
                                 .in_("exercise_id", exercise_ids))}
    return summarize(practices, tries=tries, coach=coach, held=held, titles=titles)
