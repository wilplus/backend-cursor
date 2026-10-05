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


# ── VERBAL ELIGIBILITY: ONE RULE, TWO READERS (N48.1, Wave 1, E1) ──────────
#
# A rewrite or praise row may compete under V3 only when it is evidence-backed,
# versioned, about THIS Take, and locatable in THIS Take's transcript. V3's
# `_verbal_inventory` applies that rule to rank; `ensure_required_families`
# applies the SAME rule to decide whether a lane is already covered. They used
# to disagree: the fallback check counted any row of the family as present, so
# an excluded row (a detector praise with no evidence, an LLM / prior-Take /
# coach-revision rewrite, a row left over from an older Take on an unspoken
# Slide) suppressed the honest fallback and V3 then excluded the row too —
# the Take ended with no praise and no rewrite. One predicate, `verbal_
# exclusion`, ends the disagreement; neither reader restates any part of it.
VERBAL_FAMILIES = ("rewrite_clarity", "great_formulation")
PRODUCER_VERSION_KEYS = (
    "suggestion_version",
    "model_version",
    "prompt_version",
    "rule_version",
    "detector_version",
)
VERBAL_EVIDENCE_KEYS = (
    "specificity",
    "fallback",
    "detector",
    "detector_rank",
    "lexical_words_invented",
    "basis",
    "anchor_score",
    "cue_count",
)


def producer_versions(row: Any) -> dict:
    """The producer version keys a row carries, each a string or None."""
    item = row if isinstance(row, dict) else {}
    return {
        key: str(item.get(key)) if item.get(key) not in (None, "") else None
        for key in PRODUCER_VERSION_KEYS
    }


def verbal_evidence(row: Any) -> dict:
    """The row's Manager evidence, limited to the keys the policy reads."""
    item = row if isinstance(row, dict) else {}
    raw = item.get("_manager_evidence")
    raw = raw if isinstance(raw, dict) else {}
    return {key: raw[key] for key in VERBAL_EVIDENCE_KEYS if key in raw}


def _int_or_none(value: Any) -> Optional[int]:
    return value if isinstance(value, int) and not isinstance(value, bool) \
        else None


class TakeDocumentMap:
    """Served Ideal Text offsets -> this Take's transcript-document offsets.

    TWO DOCUMENTS, TWO COORDINATE SYSTEMS (N48.1, Wave 1). A verbal row's
    `span` addresses the SERVED Ideal Text: that is where tracked changes,
    fallbacks and structural repairs are cut, and where the client draws.
    V3's blocks address the TAKE's transcript document (`start`/`end` of its
    pieces). From Take 2 on the two differ: a Slide the Take did not speak
    keeps its older Paragraph in the served text (`take_rebuild.
    merge_by_slide`), so every later offset is shifted by that Paragraph, and
    the served words can be edited or locked away from the transcript.
    Comparing a served span with block offsets anchored notes to whichever
    block the numbers happened to fall in, or dropped them as out of bounds.

    The map is proven, never guessed. Identical documents map 1:1. Otherwise
    a span maps only through pieces whose served slice IS their transcript
    slice (`served_start`/`served_end`, written by `ideal_text_parts.
    with_served_spans` / `bind_pieces_to_parts`), and only when the mapped
    transcript words equal the served words character for character. Words
    the Take did not say map nowhere: the row is excluded as
    `document_span_unmapped`.
    """

    def __init__(self, *, take_id: Any, document_text: Any, served_text: Any,
                 pieces: Any, snippet_takes: Optional[dict] = None) -> None:
        self.take_id = str(take_id or "")
        self.document_text = document_text if isinstance(document_text, str) \
            else ""
        self.served_text = served_text if isinstance(served_text, str) \
            else None
        self.snippet_takes = {
            str(key): str(value or "")
            for key, value in (snippet_takes or {}).items() if key
        }
        self._verbatim: list[tuple[int, int, int, int]] = []
        for piece in pieces or []:
            row = piece if isinstance(piece, dict) else {}
            start, end = _int_or_none(row.get("start")), _int_or_none(row.get("end"))
            s_start = _int_or_none(row.get("served_start"))
            s_end = _int_or_none(row.get("served_end"))
            if (start is None or end is None or s_start is None
                    or s_end is None or self.served_text is None
                    or not 0 <= start < end <= len(self.document_text)
                    or not 0 <= s_start < s_end <= len(self.served_text)):
                continue
            if (self.served_text[s_start:s_end]
                    == self.document_text[start:end]):
                self._verbatim.append((s_start, s_end, start, end))

    @classmethod
    def for_document(cls, take_document: Any, served_text: Any, *,
                     take_id: Any = None) -> "TakeDocumentMap":
        """The map for one Take document, its snippets taken from its pieces."""
        doc = take_document if isinstance(take_document, dict) else {}
        pieces = [p for p in doc.get("pieces") or [] if isinstance(p, dict)]
        return cls(
            take_id=take_id or doc.get("take_session_id"),
            document_text=doc.get("text"),
            served_text=served_text,
            pieces=pieces,
            snippet_takes={
                str(p.get("snippet_id")): str(p.get("take_session_id") or "")
                for p in pieces if p.get("snippet_id")
            },
        )

    def snippet_take(self, snippet_id: Any) -> Optional[str]:
        """The Take a snippet belongs to, or None when it is not this Take's."""
        return self.snippet_takes.get(str(snippet_id or ""))

    def to_document(self, start: int, end: int) -> Optional[tuple[int, int]]:
        """The same words in the Take document, or None when unproven."""
        served = self.served_text
        if served is None or not 0 <= start < end <= len(served):
            return None
        if served == self.document_text:
            return start, end
        lo = next((d0 + start - s0 for s0, s1, d0, _ in self._verbatim
                   if s0 <= start < s1), None)
        hi = next((d0 + end - s0 for s0, s1, d0, _ in self._verbatim
                   if s0 < end <= s1), None)
        if lo is None or hi is None or hi <= lo:
            return None
        if self.document_text[lo:hi] != served[start:end]:
            return None
        return lo, hi


def verbal_exclusion(
    row: Any, document_map: TakeDocumentMap,
) -> tuple[Optional[str], Optional[tuple[int, int]]]:
    """Why V3 would exclude this verbal row, and its Take-document span.

    THE rule (N48.1, Wave 1, E1). ``(None, (start, end))`` means eligible;
    otherwise the first failing condition names itself, in this order:
    identity, snippet lineage, Take, served span, evidence, producer version,
    and finally whether the words map into this Take's transcript.
    """
    item = row if isinstance(row, dict) else {}
    snippet_id = str(item.get("snippet_id") or "")
    snippet_take = document_map.snippet_take(snippet_id)
    resolved_take = str(item.get("take_session_id") or "") or (snippet_take or "")
    span = _span(item)
    reason: Optional[str] = None
    if not str(item.get("id") or ""):
        reason = "missing_candidate_identity"
    elif not snippet_id or snippet_take is None:
        reason = "missing_snippet_lineage"
    elif (resolved_take != document_map.take_id
          or snippet_take != document_map.take_id):
        reason = "candidate_take_mismatch"
    elif span is None:
        reason = "invalid_document_span"
    elif not verbal_evidence(item):
        reason = "missing_evidence_metadata"
    elif not any(producer_versions(item).values()):
        reason = "missing_suggestion_generator_version"
    if reason is not None or span is None:
        return reason, None
    mapped = document_map.to_document(*span)
    if mapped is None:
        return "document_span_unmapped", None
    return None, mapped


def _eligible_families(rows: list[dict],
                       document_map: Optional[TakeDocumentMap]) -> set:
    """The verbal families with at least one row V3 would let compete."""
    if document_map is None:
        return set()
    return {
        str(row.get("feedback_family")) for row in rows
        if row.get("feedback_family") in VERBAL_FAMILIES
        and verbal_exclusion(row, document_map)[0] is None
    }


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
        out.append(_exposure_row(raw, family))
    return out


def _exposure_row(raw: dict, family: str) -> dict:
    return {
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
        **_machine_readings(raw),
        "evidence": dict(raw.get("_manager_evidence") or {}),
        "_manager_evidence": dict(raw.get("_manager_evidence") or {}),
        "rank_key": list(_rank(raw)[:-3]),
        "selected": False,
    }


def _machine_readings(raw: dict) -> dict:
    """The machine prediction and acoustic snapshot, each only when present."""
    return {
        **({"machine_prediction": dict(raw["machine_prediction"])}
           if isinstance(raw.get("machine_prediction"), dict) else {}),
        **({
            "acoustic_feature_snapshot": dict(
                raw["acoustic_feature_snapshot"]),
        } if isinstance(raw.get("acoustic_feature_snapshot"), dict)
           else {}),
    }


#: THE FIELDS A SERVED ROW MAY CARRY (AC-9; N48.1, Wave 1). An ALLOWLIST,
#: because the denylist it replaces let every internal field through by
#: default: served V3 verbal rows are copies of exposure-ledger rows and
#: carried `evidence` (the Manager's specificity, detector rank, cue count),
#: `rank_key` (negated rank numbers), versions and machine readings to the
#: browser.
#:
#: WHERE THE LIST COMES FROM (checked against frontend origin/main df875245,
#: 2026-10-05). The frontend has exactly one reader of served `changes` /
#: `style_changes` rows: `mapDocumentSuggestion` in
#: src/services/api/idealText.ts (called only by `mapDocumentSuggestions`,
#: on `body.changes`, `body.style_changes`, `layers.changes`,
#: `layers.style_changes`). `CLIENT_READ_ROW_FIELDS` is every top-level key it
#: reads, including `readSuggestionSpan`'s legacy top-level `start` / `end`.
#: Its helpers (`mapCoachRequest`, `mapSuggestionEvidence`,
#: `mapPracticeExercise`, `mapFirstClientService`, `mapLearningExposures`,
#: `mapCueKeys`) read only inside the value they are handed. Every component
#: downstream consumes the mapped object, never the raw row.
#: `tests/test_verbal_lanes_take_document_n48_1.py` pins this list.
#:
#: `UNRENDERED_ROW_FIELDS` ride the speaker's item without being read yet, by
#: decision: data may reach the design-locked screens unrendered for the
#: designer (N45 Q7). Neither set may ever hold a field that grades the
#: speaker; a field the client starts reading is added the same day.
CLIENT_READ_ROW_FIELDS = frozenset({
    "id", "candidate_id", "feedback_membership_id", "feedback_exposure_id",
    "span", "start", "end", "quote", "kind", "proposed_text",
    "feedback_family", "tentative", "bookmark_tier", "practice_prompt",
    "coach_request", "open_card", "problem_recognised", "block_id",
    "device", "why_key", "why", "source", "coach_note", "status",
    "snippet_id", "take_session_id", "evidence", "take_index", "block_key",
    "visual", "pending_better_version", "pending_copy", "cue_keys",
    "praise_line", "rewrite_move", "snippet_audio_ref", "start_offset_ms",
    "duration_ms", "practice_exercise", "mlc3_service", "learning_exposures",
})
#: The coach's shared answer in words, `{kind, text, video_url?}`
#: (`confident_voice_practice.coach_shared_answer`). No number, no draft.
UNRENDERED_ROW_FIELDS = frozenset({"coach_answer"})
CLIENT_ROW_FIELDS = CLIENT_READ_ROW_FIELDS | UNRENDERED_ROW_FIELDS


def _client_evidence(value: Any) -> Optional[dict]:
    """`evidence` as the client reads it -- WHERE the moment is (Project,
    Take, Slide, Paragraph, span), written by the evidence-coordinate
    grounding -- or None. The same key also held the Manager's internal
    evidence copy on V3 verbal rows; that shape never leaves the server."""
    raw = value if isinstance(value, dict) else {}
    raw_span = raw.get("span")
    span: dict = raw_span if isinstance(raw_span, dict) else {}
    slide = raw.get("slide_index")
    if (not isinstance(raw.get("project_id"), str)
            or not isinstance(raw.get("take_session_id"), str)
            or _int_or_none(raw.get("paragraph_index")) is None
            or (slide is not None and _int_or_none(slide) is None)
            or _int_or_none(span.get("start")) is None
            or _int_or_none(span.get("end")) is None):
        return None
    return {
        "project_id": raw["project_id"],
        "take_session_id": raw["take_session_id"],
        "slide_index": slide,
        "paragraph_index": raw["paragraph_index"],
        "span": {"start": span["start"], "end": span["end"]},
    }


def strip_internal_evidence(changes: Iterable[Any]) -> list[dict]:
    """Only client-read fields ride a student payload (`CLIENT_ROW_FIELDS`).

    Internal evidence, rank inputs, scores, versions and machine readings
    stay on the server; `evidence` survives only as location coordinates.
    """
    out: list[dict] = []
    for row in changes or []:
        if not isinstance(row, dict):
            continue
        visible = {key: value for key, value in row.items()
                   if key in CLIENT_ROW_FIELDS and key != "evidence"}
        evidence = _client_evidence(row.get("evidence"))
        if evidence is not None:
            visible["evidence"] = evidence
        out.append(visible)
    return out


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
    snippet_ids_by_family: Optional[dict[str, Any]] = None,
    document_map: Optional[TakeDocumentMap] = None,
) -> list[dict]:
    """Add honest weak fallbacks only for genuinely absent text lanes.

    The fallback quote is an exact slice of the served Ideal Text. The rewrite
    changes punctuation/structure around the same words; the praise is marked
    tentative. No lexical content or certainty is invented.

    "ABSENT" MEANS "NOTHING THAT CAN COMPETE" (N48.1, Wave 1, E1). A lane is
    covered only by a row that passes `verbal_exclusion` against this Take's
    `document_map` -- the very rule V3 ranks by. A row V3 will exclude (no
    evidence, no producer version, another Take's snippet, words this Take
    did not say) no longer hides the fallback. With no map nothing can be
    proven to compete, so both fallbacks are offered and V3 arbitrates.
    """
    text = served_text if isinstance(served_text, str) else ""
    sid = str(snippet_id or "")
    family_snippets = _family_snippets(snippet_ids_by_family)
    take = str(take_session_id or "")
    rows = [dict(row) for row in (changes or []) if isinstance(row, dict)]
    present = _eligible_families(rows, document_map)
    candidates = _sentences(text)
    if not text or not take or not sid or not candidates:
        return rows
    rows.extend(_missing_lane_fallbacks(
        present, candidates, take=take, sid=sid,
        family_snippets=family_snippets))
    return rows


def _missing_lane_fallbacks(present: set, candidates: list, *, take: str,
                            sid: str, family_snippets: dict) -> list[dict]:
    """A weak fallback for each text lane with no row: the rewrite first,
    then the praise."""
    out: list[dict] = []
    if "rewrite_clarity" not in present:
        rewrite = _fallback_rewrite(
            candidates, take=take,
            snippet_id=family_snippets.get("rewrite_clarity", sid))
        if rewrite is not None:
            out.append(rewrite)
    if "great_formulation" not in present:
        out.append(_fallback_praise(
            candidates, take=take,
            snippet_id=family_snippets.get("great_formulation", sid)))
    return out


def _family_snippets(snippet_ids_by_family: Optional[dict[str, Any]]) -> dict:
    """The snippet id each known family's fallback should anchor to."""
    return {
        str(family): str(value)
        for family, value in (snippet_ids_by_family or {}).items()
        if family in FAMILIES and value
    }


def _fallback_rewrite(candidates: list, *, take: str,
                      snippet_id: str) -> Optional[dict]:
    """The longest sentence with an actionable rewrite, as a tentative
    rewrite_clarity row; None when no sentence has one."""
    ranked = sorted(
        candidates,
        key=lambda item: (-len(_WORD_RE.findall(item[2])), item[0]),
    )
    for start, end, quote in ranked:
        proposed = _actionable_rewrite(quote)
        if not proposed:
            continue
        return {
            "id": _stable_id("rewrite-review", take, quote),
            "snippet_id": snippet_id,
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
        }
    return None


def _fallback_praise(candidates: list, *, take: str, snippet_id: str) -> dict:
    # The shortest complete formulation is the most defensible weak
    # praise: its concision is directly observable in the exact quote.
    start, end, quote = min(
        candidates,
        key=lambda item: (len(_WORD_RE.findall(item[2])), item[0]),
    )
    return {
        "id": _stable_id("praise-review", take, quote),
        "snippet_id": snippet_id,
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
    }
