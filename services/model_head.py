"""A model that learns: one small head per version, fitted on the vectors of
its settled examples (N616 item 8, N582 item 2; stories LEARN-01 to LEARN-05
and PIPE-06 of docs/design/the-blank-setup-2026-11-10/stories.json).

Like ``services/model_api.py`` this module has no storage of its own: plain
lists and dicts in, plain dicts out. ``services/model_head_store.py`` reads
the tables (migration a_model_learns_from_its_settled_examples) into them.

THE HEAD. Multinomial logistic regression over the model's answers (its
three), fitted with numpy by full-batch gradient descent with an L2 penalty.
Deterministic: the same examples give the same head.

"SURE" (N566 item 8, N594). Never a general model's claim. When a head is
fitted, k-fold cross-validation measures how often it is right at each
probability level; the table is kept with the version. An answer is sure
when the measured rate at its probability, or above it, is at least
``SURE_AT`` (0.70, the threshold today).

ENOUGH TO LEARN. A head needs at least ``MIN_SETTLED`` settled examples and
at least ``MIN_PER_ANSWER`` of each answer; until then the model answers as
before, from its recipe card (``services/model_api.py::answer_prompt``).

THE OWNER'S CHECK (N616 item 23). Ten examples the version was not fitted
on, never one of the owner's first 10 and never an exam case, the head's
guess first; Keep or Change. Passed when all ten are answered and at least
``CHECK_KEEP`` were kept. It opens gate one: the model may answer in its
owner's chat (N616 item 10).

THE EXAM (N566 item 5, N615 item 3). Computed by the app, never entered by
hand: the head's answers on the exam cases both experts settled, compared
case by case with the version before (the exact sign test,
``model_launchpad.sign_test``). Passed when the exam is full, the head agrees
with the experts on at least ``EXAM_AGREE`` of the cases, and it beats the
untrained version (the first version, N528 item 8) or is not clearly worse
than the version before (a later one). Only a passed exam opens gate two: shared for
tokens, or sold.
"""
from __future__ import annotations

import hashlib
import math
from typing import Any, Iterable, Optional

import numpy as np

from services.model_api import SURE_AT

# ── The defaults the founder is asked about (one place each) ───────────────
#: A head needs this many settled examples, and this many of each answer.
MIN_SETTLED = 10
MIN_PER_ANSWER = 2
#: The owner's check: this many unseen examples; passed with this many kept.
CHECK_SIZE = 10
CHECK_KEEP = 7
#: The exam: the head agrees with the experts on at least this share of
#: the cases (the threshold "sure" uses today).
EXAM_AGREE = SURE_AT
#: A new fit when the settled examples grew by this factor since the last one
#: (also: when the founder queues one, or a version is marked to retrain).
REFIT_GROWTH = 1.5
#: The probability levels of the confidence table.
LEVELS = (0.0, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9)
L2 = 1e-2
STEPS = 300
RATE = 0.5
FOLDS = 5


# ── Which answers, and is there enough to learn ─────────────────────────────
def answers_of(recipe: Any) -> list[str]:
    """The answers a head chooses from: the scale's, else the list's."""
    recipe = recipe if isinstance(recipe, dict) else {}
    raw = recipe.get("scale") or recipe.get("options") or []
    out: list[str] = []
    for a in raw:
        label = str(a.get("label") if isinstance(a, dict) else a).strip()
        if label and label not in out:
            out.append(label)
    return out


def learnable(example: dict, *, may_teach: Optional[dict] = None) -> bool:
    """An example a head may read (LEARN-01): settled, never an exam case,
    never a withdrawn speaker's. ``may_teach``: speaker id -> still allowed."""
    if example.get("in_exam") or example.get("known_answer") in (None, ""):
        return False
    speaker = example.get("speaker_id")
    if example.get("source") == "takes" and may_teach is not None:
        return bool(may_teach.get(str(speaker)))
    return True


def enough(labels: Iterable[str], answers: list[str]) -> bool:
    labels = list(labels)
    if len(answers) < 2 or len(labels) < MIN_SETTLED:
        return False
    return all(labels.count(a) >= MIN_PER_ANSWER for a in answers)


# ── Fitting and applying ────────────────────────────────────────────────────
def _softmax(z: np.ndarray) -> np.ndarray:
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def _fit(x: np.ndarray, y: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    n, d = x.shape
    w = np.zeros((d, k))
    b = np.zeros(k)
    onehot = np.eye(k)[y]
    for _ in range(STEPS):
        p = _softmax(x @ w + b)
        g = (p - onehot) / n
        w -= RATE * (x.T @ g + L2 * w)
        b -= RATE * g.sum(axis=0)
    return w, b


def _folds(n: int, labels: np.ndarray, k: int) -> list[np.ndarray]:
    """Stratified folds, deterministic: each answer's examples dealt in turn."""
    out: list[list[int]] = [[] for _ in range(k)]
    turn = 0
    for c in sorted(set(labels.tolist())):
        for i in np.where(labels == c)[0].tolist():
            out[turn % k].append(i)
            turn += 1
    return [np.array(f, dtype=int) for f in out if f]


def confidence_table(pairs: list[tuple[float, bool]]) -> dict:
    """How often the head was right at each probability level or above."""
    rows = []
    for lo in LEVELS:
        hits = [ok for p, ok in pairs if p >= lo]
        rows.append({"at": lo, "n": len(hits), "right": sum(1 for ok in hits if ok)})
    return {"levels": rows}


def fit(vectors: list[list[float]], labels: list[str], answers: list[str]) -> Optional[dict]:
    """The head and its confidence table, or None when there is not enough
    to learn. {"head": {...}, "confidence": {...}}."""
    if not vectors or len(vectors) != len(labels) or not enough(labels, answers):
        return None
    index = {a: i for i, a in enumerate(answers)}
    x = np.asarray(vectors, dtype=float)
    y = np.asarray([index[a] for a in labels], dtype=int)
    k = len(answers)
    pairs: list[tuple[float, bool]] = []
    folds = _folds(len(y), y, min(FOLDS, int(np.bincount(y, minlength=k).min())))
    for test in folds:
        train = np.setdiff1d(np.arange(len(y)), test)
        if len(set(y[train].tolist())) < 2:
            continue
        w, b = _fit(x[train], y[train], k)
        p = _softmax(x[test] @ w + b)
        for row, truth in zip(p, y[test]):
            pairs.append((float(row.max()), int(row.argmax()) == int(truth)))
    w, b = _fit(x, y, k)
    head = {"answers": list(answers), "dims": int(x.shape[1]),
            "weights": np.round(w.T, 6).tolist(), "bias": np.round(b, 6).tolist()}
    return {"head": head, "confidence": confidence_table(pairs)}


def probabilities(head: dict, vector: list[float]) -> Optional[list[float]]:
    try:
        w = np.asarray(head["weights"], dtype=float)
        b = np.asarray(head["bias"], dtype=float)
        v = np.asarray(vector, dtype=float)
        if w.shape[1] != v.shape[0]:
            return None
        return _softmax((w @ v + b)[None, :])[0].tolist()
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def is_sure(confidence: Any, p: float) -> bool:
    """Sure when the measured rate at this probability or above is at least
    SURE_AT. A level never measured is not sure."""
    levels = (confidence or {}).get("levels") if isinstance(confidence, dict) else None
    best = None
    for row in levels or []:
        if float(row.get("at", 0)) <= p and int(row.get("n") or 0) > 0:
            best = row
    if best is None:
        return False
    return int(best["right"]) / int(best["n"]) >= SURE_AT


def answer(version: dict, vector: Optional[list[float]]) -> Optional[dict]:
    """The head's answer: {"answer": one of its answers, "sure": bool}, or
    None when the version has no usable head."""
    head = version.get("head") if isinstance(version.get("head"), dict) else None
    if not head or vector is None:
        return None
    p = probabilities(head, vector)
    if p is None or not all(math.isfinite(v) for v in p):
        return None
    i = max(range(len(p)), key=lambda j: p[j])
    return {"answer": head["answers"][i], "sure": is_sure(version.get("confidence"), p[i]),
            "p": p[i]}


# ── When to fit again ───────────────────────────────────────────────────────
def needs_fit(latest: Optional[dict], settled: int, *, queued: bool) -> bool:
    if queued:
        return True
    if latest is None or not latest.get("head"):
        return settled >= MIN_SETTLED
    if latest.get("retrain_at"):
        return True
    return settled >= REFIT_GROWTH * max(1, len(latest.get("example_ids") or []))


# ── The owner's check (LEARN-03) ────────────────────────────────────────────
def check_pool(examples: list[dict], fitted: Iterable[str], first_ten: Iterable[str],
               version_id: str) -> list[str]:
    """Ten examples the version was not fitted on: never one of the first
    10, never an exam case. Picked by a hash of the version, so the same ten
    each time it is asked."""
    seen = {str(e) for e in fitted} | {str(e) for e in first_ten}
    pool = [str(e["id"]) for e in examples if not e.get("in_exam") and str(e["id"]) not in seen]
    pool.sort(key=lambda i: hashlib.sha256(f"{version_id}:{i}".encode()).hexdigest())
    return pool[:CHECK_SIZE]


def check_passed(items: list[dict]) -> bool:
    done = [i for i in items if i.get("kept") is not None]
    return len(items) >= CHECK_SIZE and len(done) == len(items) and \
        sum(1 for i in done if i["kept"]) >= CHECK_KEEP


# ── The exam (LEARN-05) ─────────────────────────────────────────────────────
def exam_result(cases: list[dict], target: int, before: Optional[dict] = None, *,
                first: bool = False) -> dict:
    """``cases``: [{"example_id", "truth", "guess"}] for the exam cases both
    experts settled. ``before``: the version before, as {"right": {id: bool}}:
    the previous head's exam, or, for the FIRST version, the untrained
    version's answers on the same cases. The first version must beat the
    untrained one (N528 item 8: more cases won than lost); a later one must
    not be clearly worse than the version before (N566 item 5). The app's
    result; nobody enters it."""
    from services.model_launchpad import RELEASE_ALPHA, sign_test
    right = {c["example_id"]: c["guess"] == c["truth"] for c in cases}
    agree = (sum(right.values()) / len(cases)) if cases else 0.0
    better = worse = same = 0
    prev = (before or {}).get("right") or {}
    for eid, ok in right.items():
        if eid not in prev:
            continue
        if ok and not prev[eid]:
            better += 1
        elif prev[eid] and not ok:
            worse += 1
        else:
            same += 1
    clearly_worse = worse > better and sign_test(better, worse) < RELEASE_ALPHA
    full = len(cases) >= max(1, int(target))
    return {"computed": True, "cases": len(cases), "full": full,
            "as_good_in_ten": int(round(10 * agree)) if cases else None,
            "better": better, "worse": worse, "same": same,
            "first": first,
            "passed": bool(full and agree >= EXAM_AGREE and not clearly_worse
                           and (better > worse if first else True)),
            "right": right}


# ── The two gates (LEARN-04) ────────────────────────────────────────────────
def gates(version: Optional[dict]) -> dict:
    v = version or {}
    has_head = bool(v.get("head"))
    return {"owner_chat": has_head and bool(v.get("owner_checked_at")),
            "share": has_head and v.get("status") in ("passed", "released")
            and bool((v.get("exam") or {}).get("passed"))}
