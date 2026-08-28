"""The one Take-level feedback contract.

Every usable spoken Take exposes exactly one candidate from each independent
family: Confident Voice, actionable wording/structure, and evidence-backed
praise. Selection ranks the complete family pool; input order is only the last
stable tie-break. Internal evidence stays server-side and is snapshotted in the
exposure ledger before any user response exists.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable, Optional


POLICY_VERSION = "take-feedback-manager-v2"
EVIDENCE_SCHEMA_VERSION = "take-feedback-manager-evidence-v1"
STRUCTURAL_REWRITE_RULE_VERSION = "structural-rewrite-v1"
FALLBACK_GENERATOR_RULE_VERSION = "take-feedback-fallback-generator-v1"
FAMILIES = (
    "confident_voice",
    "rewrite_clarity",
    "great_formulation",
)
_SENTENCE_RE = re.compile(r"[^\n.!?]+(?:[.!?]+|$)")
_WORD_RE = re.compile(r"[^\W_]+(?:[’'-][^\W_]+)*", re.UNICODE)
_LEADING_FILLER_RE = re.compile(
    r"^(?:so|well|actually|basically|literally|you know)\b[, ]*",
    re.IGNORECASE,
)
_STRANDED_NEGATED_PREDICATE_RE = re.compile(
    r"\b(?:do(?:es|did)?\s+not|don['’]t|doesn['’]t|didn['’]t|"
    r"can(?:not|['’]t)|won['’]t|wouldn['’]t|shouldn['’]t|couldn['’]t)\s+"
    r"(?:want|need|prefer|choose|include|use|mean|like|have)\s*$",
    re.IGNORECASE,
)
_OBJECT_PHRASE_START_RE = re.compile(
    r"^(?:a|an|the|my|your|our|their|his|her|its)\b",
    re.IGNORECASE,
)


def _span(row: Any) -> Optional[tuple[int, int]]:
    if not isinstance(row, dict):
        return None
    raw = row.get("span")
    if not isinstance(raw, dict):
        return None
    start, end = raw.get("start"), raw.get("end")
    if (not isinstance(start, int) or isinstance(start, bool)
            or not isinstance(end, int) or isinstance(end, bool)
            or start < 0 or end <= start):
        return None
    return start, end


def _rank(row: dict) -> tuple:
    """Higher evidence first; document position is only the final tie-break."""
    family = str(row.get("feedback_family") or "")
    evidence = row.get("_manager_evidence")
    evidence = evidence if isinstance(evidence, dict) else {}
    cue_count = len([
        key for key in (row.get("cue_keys") or []) if isinstance(key, str)
    ])
    exact = 1 if row.get("anchor_role") != "slide_route" else 0
    generated = 0 if evidence.get("fallback") else 1
    detector = int(evidence.get("detector_rank") or 0)
    specificity = int(evidence.get("specificity") or 0)
    changed = int(bool(
        row.get("proposed_text")
        and str(row.get("proposed_text")).strip()
        != str(row.get("quote") or "").strip()
    ))
    family_terms = {
        "confident_voice": (detector, cue_count, exact, generated),
        "rewrite_clarity": (changed, specificity, generated, exact),
        "great_formulation": (cue_count, specificity, generated, exact),
    }.get(family, (generated, specificity, exact, 0))
    span = _span(row) or (10**9, 10**9)
    # Negate positive evidence so ordinary ascending sort puts best first.
    return tuple(-int(value) for value in family_terms) + (
        span[0], span[1], str(row.get("id") or ""),
    )


def rank_family_pool(changes: Iterable[Any]) -> list[dict]:
    """Exactly one best candidate per family, or [] if any family is absent."""
    pools: dict[str, list[dict]] = {family: [] for family in FAMILIES}
    for raw in changes or []:
        if not isinstance(raw, dict) or _span(raw) is None:
            continue
        family = str(raw.get("feedback_family") or "")
        if family in pools:
            pools[family].append(raw)
    if any(not pools[family] for family in FAMILIES):
        return []
    selected = [sorted(pools[family], key=_rank)[0] for family in FAMILIES]
    selected.sort(key=lambda row: (
        (_span(row) or (10**9, 10**9))[0],
        FAMILIES.index(str(row.get("feedback_family"))),
    ))
    return selected


def exposure_snapshot(changes: Iterable[Any]) -> list[dict]:
    """Complete candidate pool with evidence/scores, safe only for storage."""
    out: list[dict] = []
    for raw in changes or []:
        if not isinstance(raw, dict):
            continue
        family = str(raw.get("feedback_family") or "")
        if family not in FAMILIES or _span(raw) is None:
            continue
        out.append({
            "id": str(raw.get("id") or ""),
            "feedback_family": family,
            "snippet_id": str(raw.get("snippet_id") or "") or None,
            "take_session_id": (
                str(raw.get("take_session_id"))
                if raw.get("take_session_id") else None
            ),
            "span": dict(raw.get("span") or {}),
            # Exact generated/source material is retained only in the
            # internal exposure ledger. It is needed to reproduce ranking
            # and to build surface-specific preference pairs later; none of
            # these fields ride the student payload.
            "quote": raw.get("quote"),
            "proposed_text": raw.get("proposed_text"),
            "why_key": raw.get("why_key"),
            "device": raw.get("device"),
            "tentative": bool(raw.get("tentative")),
            "cue_keys": list(raw.get("cue_keys") or []),
            "detector_version": raw.get("detector_version"),
            "rule_version": raw.get("rule_version"),
            "model_version": raw.get("model_version"),
            "prompt_version": raw.get("prompt_version"),
            **({"machine_prediction": dict(raw["machine_prediction"])}
               if isinstance(raw.get("machine_prediction"), dict) else {}),
            **({
                "acoustic_feature_snapshot": dict(
                    raw["acoustic_feature_snapshot"]),
            } if isinstance(raw.get("acoustic_feature_snapshot"), dict)
               else {}),
            "evidence": dict(raw.get("_manager_evidence") or {}),
            "_manager_evidence": dict(raw.get("_manager_evidence") or {}),
            "rank_key": list(_rank(raw)[:-3]),
            "selected": False,
        })
    return out


def strip_internal_evidence(changes: Iterable[Any]) -> list[dict]:
    """Internal evidence and rank inputs must never ride a student payload."""
    return [
        {key: value for key, value in row.items()
         if not str(key).startswith("_manager_")}
        for row in (changes or []) if isinstance(row, dict)
    ]


def _stable_id(prefix: str, take_session_id: str, quote: str) -> str:
    digest = hashlib.sha256(
        f"{prefix}\0{take_session_id}\0{quote}".encode("utf-8")
    ).hexdigest()[:16]
    return f"{prefix}:{digest}"


def _sentences(text: str) -> list[tuple[int, int, str]]:
    out: list[tuple[int, int, str]] = []
    for match in _SENTENCE_RE.finditer(text or ""):
        raw = match.group(0)
        left = len(raw) - len(raw.lstrip())
        right = len(raw.rstrip())
        if right <= left:
            continue
        start, end = match.start() + left, match.start() + right
        out.append((start, end, text[start:end]))
    return out


def _actionable_rewrite(quote: str) -> Optional[str]:
    """A conservative structural edit using only the speaker's own words."""
    if not quote or len(_WORD_RE.findall(quote)) < 4:
        return None
    no_filler = _LEADING_FILLER_RE.sub("", quote, count=1)
    if no_filler and no_filler != quote:
        return no_filler[0].upper() + no_filler[1:]
    words = list(_WORD_RE.finditer(quote))
    middle = len(words) // 2
    # Prefer a real clause boundary near the middle.
    candidates: list[int] = []
    for match in re.finditer(r"[,;:]\s+|\s+(?:and|but|so|because)\s+", quote,
                             flags=re.IGNORECASE):
        candidates.append(match.end())
    split_at = min(
        candidates,
        key=lambda at: abs(at - words[middle].start()),
        default=words[middle].start(),
    )
    left, right = quote[:split_at].rstrip(" ,;:"), quote[split_at:].lstrip()
    if not left or not right:
        return None
    right = right[0].upper() + right[1:]
    proposed = f"{left.rstrip('.!?')}. {right}"
    return proposed if proposed != quote else None


def evidence_backed_rewrite_candidates(
    served_text: Any,
    *,
    take_session_id: Any,
    snippet_id: Any,
) -> list[dict]:
    """Return every high-signal, word-preserving structural repair.

    These are ordinary Manager candidates, not fallbacks. That distinction is
    load-bearing: a model-created rewrite elsewhere in the Take must not hide
    a more obvious broken boundary before ranking even begins. Each detector
    operates only on exact slices of the served Ideal Text and may change
    punctuation/case, never lexical content.

    The first rule repairs the common deletion scar where a negated transitive
    predicate is stranded at a full stop and its object phrase starts the next
    sentence ("I don't want. A script ..."). It emits every match; the Manager
    ranks the complete rewrite family instead of accepting the first fit.
    """
    text = served_text if isinstance(served_text, str) else ""
    take = str(take_session_id or "")
    sid = str(snippet_id or "")
    sentences = _sentences(text)
    if not text or not take or not sid or len(sentences) < 2:
        return []

    rows: list[dict] = []
    for left, right in zip(sentences, sentences[1:]):
        start, _, first = left
        _, end, second = right
        first_body = first.rstrip().rstrip(".!?").rstrip()
        second_body = second.lstrip()
        if not _STRANDED_NEGATED_PREDICATE_RE.search(first_body):
            continue
        if not _OBJECT_PHRASE_START_RE.match(second_body):
            continue
        lowered_second = second_body[0].lower() + second_body[1:]
        quote = text[start:end]
        proposed = f"{first_body} {lowered_second}"
        if not quote or proposed == quote:
            continue
        rows.append({
            "id": _stable_id("structural-rewrite", take, quote),
            "snippet_id": sid,
            "take_session_id": take,
            "kind": "replace",
            "source": "wording",
            "span": {"start": start, "end": end},
            "quote": quote,
            "proposed_text": proposed,
            "why_key": "clarity",
            "feedback_family": "rewrite_clarity",
            "tentative": False,
            "rule_version": STRUCTURAL_REWRITE_RULE_VERSION,
            "_manager_evidence": {
                "fallback": False,
                "detector": "stranded_negated_object_boundary",
                "detector_rank": 5,
                "specificity": 5,
                "lexical_words_invented": 0,
            },
        })
    return rows


def ensure_required_families(
    served_text: Any,
    changes: Iterable[Any],
    *,
    take_session_id: Any,
    snippet_id: Any,
) -> list[dict]:
    """Add honest weak fallbacks only for genuinely absent text lanes.

    The fallback quote is an exact slice of the served Ideal Text. The rewrite
    changes punctuation/structure around the same words; the praise is marked
    tentative. No lexical content or certainty is invented.
    """
    text = served_text if isinstance(served_text, str) else ""
    sid = str(snippet_id or "")
    take = str(take_session_id or "")
    rows = [dict(row) for row in (changes or []) if isinstance(row, dict)]
    present = {
        str(row.get("feedback_family")) for row in rows
        if row.get("feedback_family") in FAMILIES
    }
    candidates = _sentences(text)
    if not text or not take or not sid or not candidates:
        return rows

    if "rewrite_clarity" not in present:
        ranked = sorted(
            candidates,
            key=lambda item: (-len(_WORD_RE.findall(item[2])), item[0]),
        )
        for start, end, quote in ranked:
            proposed = _actionable_rewrite(quote)
            if not proposed:
                continue
            rows.append({
                "id": _stable_id("rewrite-review", take, quote),
                "snippet_id": sid,
                "take_session_id": take,
                "kind": "replace",
                "source": "wording",
                "span": {"start": start, "end": end},
                "quote": quote,
                "proposed_text": proposed,
                "why_key": "clarity_tentative",
                "feedback_family": "rewrite_clarity",
                "tentative": True,
                "rule_version": FALLBACK_GENERATOR_RULE_VERSION,
                "_manager_evidence": {
                    "fallback": True,
                    "specificity": min(3, len(_WORD_RE.findall(quote)) // 6),
                    "lexical_words_invented": 0,
                },
            })
            break

    if "great_formulation" not in present:
        # The shortest complete formulation is the most defensible weak
        # praise: its concision is directly observable in the exact quote.
        start, end, quote = min(
            candidates,
            key=lambda item: (len(_WORD_RE.findall(item[2])), item[0]),
        )
        rows.append({
            "id": _stable_id("praise-review", take, quote),
            "snippet_id": sid,
            "take_session_id": take,
            "kind": "advice",
            "source": "structural",
            "span": {"start": start, "end": end},
            "quote": quote,
            "device": "tentative_formulation",
            "feedback_family": "great_formulation",
            "tentative": True,
            "rule_version": FALLBACK_GENERATOR_RULE_VERSION,
            "_manager_evidence": {
                "fallback": True,
                "specificity": 1,
                "basis": "exact_concise_formulation",
            },
        })
    return rows
