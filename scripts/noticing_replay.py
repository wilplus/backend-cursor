"""Replay what the speaking coach notices, to show a settings change changed
nothing (N647 item 8, step 3; ``services/noticing_settings.py``).

It runs every rule that reads a noticing setting over one fixed, seeded
corpus and prints a digest of all their answers:

  verbal_cues.measure           filler, hedging and restart verdicts
  tempo_stretch.pick            the rushed or slow stretch, and stays_inside
  moment_pick.pick / unfixed    the shown moments and the unfixed one
  take_context.carries          a sentence carries the key line
  _practice_routing             which blocks offer practice

    python scripts/noticing_replay.py            # one digest
    python scripts/noticing_replay.py --compare  # live record vs today's constants

Run it on main and on a branch: equal digests mean equal answers. With
``--compare`` it runs the corpus under the live record (read from
runtime_config) and under the defaults, and says whether they differ. It
reads, never writes. The corpus is made up: no speaker's words.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

SEED = 647
WORDS = ("our new plan cuts the wait for every customer by half and the team "
         "built it in six weeks with the data we had").split()
FILLERS = ("um", "uh", "erm")
HEDGES = ("i think", "kind of", "sort of", "maybe", "i guess", "basically")
BANDS = (-0.9, -0.6, -0.5, -0.3, -0.01, 0.0, 0.01, 0.3, 0.5, 0.8)


def _transcript(rng: random.Random) -> str:
    out: list[str] = []
    for _ in range(rng.randint(8, 90)):
        roll = rng.random()
        if roll < 0.07:
            out.append(rng.choice(FILLERS))
        elif roll < 0.12:
            out.append(rng.choice(HEDGES))
        elif roll < 0.16 and out:
            out.append(out[-1])
        out.append(rng.choice(WORDS))
    return " ".join(out) + "."


def _clip(rng: random.Random, start: float) -> dict:
    timed, t = [], start
    word_s, gap_s = rng.uniform(0.2, 0.45), rng.uniform(0.0, 0.9)
    for i in range(rng.randint(5, 60)):
        timed.append({"word": f"w{i}", "start": round(t, 3), "end": round(t + word_s, 3)})
        t += word_s + (gap_s if rng.random() < 0.4 else 0.05)
    return {"id": f"c{start}", "transcript": "a clip of the talk", "words": timed}


def _row(rng: random.Random, i: int) -> dict:
    s, w = round(rng.random(), 3), round(rng.random(), 3)
    return {"block_id": f"b{i}", "slide_index": i % 4, "word_count": rng.randint(2, 40),
            "candidate_id": f"b{i}-clip", "voice": round(1 - s, 3),
            "held": rng.random() < 0.2,
            "read": {"s": s, "w": w, "value": s * w, "sound": rng.random() < 0.9,
                     "words_help": None}}


def answers() -> dict:
    from services import moment_pick, take_context, tempo_stretch, verbal_cues
    from services.take_feedback_policy_v3 import _practice_routing

    rng = random.Random(SEED)
    out: dict = {"verbal": [], "tempo": [], "pick": [], "carries": [], "practice": []}
    for _ in range(400):
        out["verbal"].append(verbal_cues.measure(_transcript(rng), "en"))
    for _ in range(200):
        take, t = [], 0.0
        for _ in range(3):
            take.append(_clip(rng, t))
            t = take[-1]["words"][-1]["end"] + rng.uniform(0.3, 2.0)
        chosen = tempo_stretch.pick(take)
        ids = {str(c["id"]) for c in take}
        out["tempo"].append([chosen, tempo_stretch.stays_inside(take, ids, "rushed"),
                             tempo_stretch.stays_inside(take, ids, "slow")])
    for _ in range(300):
        rows = [_row(rng, i) for i in range(rng.randint(1, 7))]
        picked = moment_pick.pick(rows)
        low = moment_pick.unfixed(rows, picked["shown"])
        out["pick"].append([picked, low and low["block_id"]])
    for _ in range(300):
        out["carries"].append(take_context.carries(
            _transcript(rng), " ".join(rng.sample(WORDS, rng.randint(1, 6)))))
    for _ in range(200):
        blocks = [{"block_id": f"b{i}", "selected_candidate_id": f"x{i}",
                   "confidence_candidates": [{"candidate_id": f"x{i}",
                                              "machine_score": rng.choice(BANDS)}]}
                  for i in range(rng.randint(1, 5))]
        out["practice"].append(_practice_routing(blocks))
    return out


def digest(found: dict) -> dict:
    def one(value) -> str:
        blob = json.dumps(value, sort_keys=True, default=str, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    return {**{name: one(v) for name, v in found.items()}, "all": one(found)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--compare", action="store_true",
                        help="the live record against today's constants")
    args = parser.parse_args()
    if not args.compare:
        with _defaults():
            print(json.dumps(digest(answers()), indent=2))
        return 0
    from services import noticing_settings
    live = digest(answers())
    with noticing_settings.trying(noticing_settings.DEFAULTS):
        constants = digest(answers())
    same = live == constants
    print(json.dumps({"live_version": noticing_settings.version(), "live": live,
                      "constants": constants, "same": same}, indent=2))
    return 0 if same else 1


def _defaults():
    """The constants, with no database read (on main, where there is no
    settings module, nothing to do)."""
    try:
        from services import noticing_settings
    except ImportError:
        return contextlib.nullcontext()
    noticing_settings.use_reader(lambda: None)
    return contextlib.nullcontext()


if __name__ == "__main__":
    raise SystemExit(main())
