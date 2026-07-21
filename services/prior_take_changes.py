"""Cross-take discernment on the Living Transcript (founder decision
2026-07-20 #4).

"When I say something differently the next time in a similar fragment,
the system should spot that and let me know that previous time or this
time it was better."

Version N+1 IS take N+1's transcript (decision #4). Wherever the PREVIOUS
take said the same thing BETTER, that fragment comes back as an
approvable tracked change on the new document:

    struck: what you just said     proposed: what you said last time
    why:   energy | steadiness | coverage | overall

Approve → the previous wording replaces the new one (and bakes forward
through the decision ledger, so it is never re-litigated); keep → the new
wording stands and the offer is remembered as dismissed. Repeat per take
and the document converges to the founder's 80/20 → 48/20/32 mix, with
per-fragment provenance telling the story. The percentages stay internal
(AC-9); only the badge and the why-key surface.

ALIGNMENT: fragments are matched by NORMALIZED-TEXT similarity under a
monotonic (order-preserving) constraint — the same thing said again sits
in roughly the same place in the talk. A fragment with no confident
counterpart is simply new material: no comparison, no change. Matching
by text (never by position) is what makes this survive a take that adds
or drops material — the positional-slot corruption the #227 review
found.

RANKING: the comparison itself is the SHIPPED blend (power_score, L2
untouched) — this module only decides WHICH pairs to compare and how to
say why. No LLM anywhere.
"""
from __future__ import annotations

import difflib
import logging
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Below this text similarity two fragments are different material, not
# two attempts at the same thing.
_MIN_SIMILARITY = 0.55
# The previous fragment must win by more than noise to be worth offering.
_MIN_MARGIN = 0.04
# One factor must lead by this relative margin to be named as THE reason.
_DOMINANCE = 0.15

WHY_KEYS = ("energy", "steadiness", "coverage", "overall")

_WS = re.compile(r"[^\w\s]+")


def _norm(text: Any) -> str:
    if not isinstance(text, str):
        return ""
    return " ".join(_WS.sub(" ", text).lower().split())


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def align_fragments(new_pieces: Any, old_pieces: Any) -> list:
    """[(new_piece, old_piece, similarity)] — each new fragment paired
    with the previous take's fragment that says the same thing, under a
    MONOTONIC constraint (an earlier new fragment can never claim a later
    old one than its successor). Unmatched new fragments are absent from
    the result: new material is not a comparison. Pure."""
    news = [p for p in (new_pieces or []) if isinstance(p, dict)]
    olds = [p for p in (old_pieces or []) if isinstance(p, dict)]
    if not news or not olds:
        return []
    norm_new = [_norm(p.get("text")) for p in news]
    norm_old = [_norm(p.get("text")) for p in olds]

    out: list = []
    lo = 0   # monotonic floor into olds
    for i, p in enumerate(news):
        best_j, best_score = -1, 0.0
        # A bounded look-ahead keeps this linear-ish and stops a distant
        # coincidental match from crossing the talk.
        for j in range(lo, min(len(olds), lo + 8)):
            score = _similarity(norm_new[i], norm_old[j])
            if score > best_score:
                best_j, best_score = j, score
        if best_j >= 0 and best_score >= _MIN_SIMILARITY:
            out.append((p, olds[best_j], best_score))
            lo = best_j + 1
    return out


def _candidate(snip: Any) -> dict:
    """The ranking inputs for one snippet — the same fields
    build_best_presentation feeds power_score with."""
    s = snip if isinstance(snip, dict) else {}
    metrics = s.get("metrics") if isinstance(s.get("metrics"), dict) else {}
    stick = metrics.get("slide_stickiness")
    if isinstance(stick, dict):
        stick = stick.get("composite")
    return {
        # `direction` is deliberately absent: the coach label lives in
        # training_labels, never on a snippet row — reading a field that
        # does not exist would silently rank delivery-only while looking
        # blended (review finding). Cross-take comparison is therefore
        # explicitly delivery+coverage, and says so.
        "activation": metrics.get("overall_score"),
        "slide_stickiness": stick,
        "tag": None,
        "breakthrough": False,
        "metrics": metrics,
    }


def _score(cand: dict) -> Optional[float]:
    try:
        from services.power_phrase_ranking import power_score
        return power_score(
            activation=cand.get("activation"),
            slide_stickiness=cand.get("slide_stickiness"),
            tag=cand.get("tag"),
            direction=cand.get("direction"),
            breakthrough=bool(cand.get("breakthrough")),
        )
    except Exception:
        return None


def why_key(new_cand: dict, old_cand: dict) -> str:
    """Why the PREVIOUS fragment reads better — the largest relative lead
    among the observable factors, else 'overall'. Deterministic; the four
    keys are the entire user-facing vocabulary (AC-9/CONSTRUCT: the FE
    holds the copy). Pure."""
    try:
        from services.delivery_stars import normalize_features
        nm = normalize_features(new_cand.get("metrics"))
        om = normalize_features(old_cand.get("metrics"))

        def _gain(*keys) -> float:
            best = 0.0
            for k in keys:
                a, b = nm.get(k), om.get(k)
                if a is None or b is None or a == 0:
                    continue
                best = max(best, (b - a) / abs(a))
            return best

        ranked = [(_gain("f0_sd", "dynamic_db"), "energy"),
                  (_gain("pause_ratio"), "steadiness")]
        n_st, o_st = (new_cand.get("slide_stickiness"),
                      old_cand.get("slide_stickiness"))
        if isinstance(n_st, (int, float)) and isinstance(o_st, (int, float)) \
                and not isinstance(n_st, bool) and n_st > 0:
            ranked.append(((o_st - n_st) / abs(n_st), "coverage"))
        ranked.sort(key=lambda t: -t[0])
        if ranked and ranked[0][0] >= _DOMINANCE:
            return ranked[0][1]
        return "overall"
    except Exception:
        return "overall"


def build_prior_take_changes(doc: Any, prev_doc: Any, *, database,
                             decided_ids: Any = None) -> list:
    """The `prior_take` changes for the current document: for every
    aligned fragment pair where the PREVIOUS fragment outranks the new
    one, a span-anchored replace offering the previous wording.

    `decided_ids` — snippet ids of previous fragments the student already
    accepted or dismissed here (never re-offered).

    Shape matches services/tracked_changes (same renderer). Best-effort;
    [] on anything missing."""
    try:
        if not isinstance(doc, dict) or not isinstance(prev_doc, dict):
            return []
        text = doc.get("text") or ""
        if not text:
            return []
        _decided = {str(x) for x in (decided_ids or [])}
        pairs = align_fragments(doc.get("pieces"), prev_doc.get("pieces"))
        if not pairs:
            return []

        _get = getattr(database, "get_snippet_by_id", None)
        out: list = []
        for new_p, old_p, _sim in pairs:
            old_id = str(old_p.get("snippet_id") or "")
            new_id = str(new_p.get("snippet_id") or "")
            if not old_id or not new_id or old_id in _decided:
                continue
            old_text = (old_p.get("text") or "").strip()
            new_text = (new_p.get("text") or "").strip()
            if not old_text or old_text == new_text:
                continue
            if not callable(_get):
                continue
            new_c, old_c = _candidate(_get(new_id)), _candidate(_get(old_id))
            # BOTH sides need a real measurement. Past the LLM budget a
            # piece has no overall_score, and treating that as 0 handed
            # out blanket "your previous take was better" offers on
            # unmeasured material (review finding).
            if new_c.get("activation") is None \
                    or old_c.get("activation") is None:
                continue
            s_new, s_old = _score(new_c), _score(old_c)
            if s_new is None or s_old is None:
                continue
            if s_old - s_new <= _MIN_MARGIN:
                continue   # the new take held its ground — nothing to say

            # Anchor on the piece's CARRIED span (relocated onto the
            # served text by the caller) — a bare search would point a
            # repeated phrase at the wrong occurrence.
            try:
                start, end = int(new_p["start"]), int(new_p["end"])
            except (KeyError, TypeError, ValueError):
                continue
            if text[start:end] != new_text:
                continue   # moved/baked away — never re-point (#219)
            out.append({
                "id": f"prior:{new_id}",
                "snippet_id": old_id,          # what Accept/Keep decides on
                "replaces_snippet_id": new_id,
                # The CURRENT take's session (the one on screen) — the FE
                # renders a replace only with a snippet+session pair (FE
                # contract 2026-07-21). The /prior-take/decide endpoint
                # itself keys on snippet_id+quote, not session, so this is
                # for the render gate; the displayed take is the honest
                # value.
                "take_session_id": new_p.get("take_session_id"),
                "kind": "replace",
                "source": "prior_take",
                "span": {"start": start, "end": end},
                "quote": new_text,
                "proposed_text": old_text,
                "take_index": old_p.get("take_index"),
                "why": None,
                "why_key": why_key(new_c, old_c),
            })
        out.sort(key=lambda c: (c["span"]["start"], c["span"]["end"]))
        return out
    except Exception as e:
        logger.warning("prior_take_changes failed: %s", e)
        return []
