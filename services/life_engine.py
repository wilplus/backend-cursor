"""The Life Panel — derivations (BE-4 … BE-8, founder-directed 2026-07-26).

The layer that thinks. It proposes; it never commits. Everything it produces
lands in a triage state and waits for an approve — a bad prompt day cannot
silently corrupt sixty principles earned over four years.

What it may do
──────────────
  * pick the 👾 category from the FIXED six (§3.1)
  * RETRIEVE which of the user's existing principles bore on a case — this is
    slot 3, and it is the moment the archive turns into a machine
  * propose the ⚜️ one-line phrasing of a new principle
  * generate the strategy document set from the user's OWN setup answers
  * compare a note against those documents and propose an edit, with one of
    the user's own principles displayed as its warrant
  * answer in an advisor's lens, saying which and why

What it must never do
─────────────────────
  * write ``reflections`` (L-1 / N5). Reflections are the founder's, polished
    through the Ideal Text tool EXTERNALLY and pasted in. There is no code
    path here that generates that field and no call into the F1 ideal-text
    pipeline — the panel is isolated from the record → transcribe → coach →
    read loop, and this is the specific place someone would be tempted to
    break that.
  * resolve a paradox (L-3). Conflicting principles come back as a PAIR.
  * touch the immutable core (L-2a). A proposal against Section I or the rank
    of the bets is never created — the response is report-only.
  * send the corpus as context. Retrieval is top-N by relevance, always.

Privacy (BE-10, §2.4)
─────────────────────
  * LLM calls go through ``_client()``, which prefers
    ``LIFE_PANEL_OPENAI_API_KEY`` so the operator can point this surface at a
    zero-data-retention project without touching the product's key.
  * Log lines carry DERIVATION OUTPUTS and sizes — never a raw note body.
    ``_log_derivation`` is the only logger used for model results, and the
    isolation test asserts no raw body reaches a log call.
  * Retrieval is capped at ``RETRIEVAL_LIMIT``; a full corpus dump is never
    assembled, let alone sent.
"""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timezone
from typing import Any, Optional

from config import Config
from services import life_import as life_importer
from services import life_panel as lp
from services import life_store as store
from services.llm_config import CHEAP_MODEL, STRONG_MODEL, LLMSpec

logger = logging.getLogger(__name__)
config = Config()

# Retrieval cap — "retrieve the ~10 relevant principles, not all 60" (§2.4).
# The cap is the privacy control AND the quality control: a model handed sixty
# principles picks the eloquent ones, not the applicable ones.
RETRIEVAL_LIMIT = 10

# The specs live HERE rather than in services/llm_config.py, breaking that
# module's "add your spec here" convention on purpose. llm_config is a shared
# product module; the fence for this feature is that it adds no third contact
# point beyond the chat router and the per-user master-doc block. A constant in
# a shared file is a small thing to add and an easy thing to grow, and the
# whole isolation argument rests on that list staying at two.
SPEC_LIFE_CASE = LLMSpec(
    model=CHEAP_MODEL,
    # Near-deterministic: this is a classification against a closed list plus
    # a one-line phrasing. Creativity here would mean a different category for
    # the same case on a re-run, which reads as the system changing its mind
    # about a four-year-old reflection.
    temperature=0.2,
    max_tokens=500,
    response_format={"type": "json_object"},
)

SPEC_LIFE_STRATEGY_DIFF = LLMSpec(
    model=STRONG_MODEL,
    # A proposal that edits the founder's own strategy is worth the stronger
    # model: the failure mode is a plausible-sounding contradiction that is
    # not actually a contradiction, and that failure spends the one daily
    # budget slot on noise.
    temperature=0.1,
    max_tokens=700,
    response_format={"type": "json_object"},
)

SPEC_LIFE_DOCS = LLMSpec(
    model=STRONG_MODEL,
    # Structuring the user's OWN answers into eight documents. Low temp: it is
    # formatting and cross-referencing, not invention.
    temperature=0.3,
    max_tokens=3000,
    response_format={"type": "json_object"},
)

SPEC_LIFE_BOARD = LLMSpec(
    model=CHEAP_MODEL,
    temperature=0.6,
    max_tokens=500,
    response_format={"type": "json_object"},
)


# ═════════════════════════════════════════════════════════════════════════
# LLM plumbing
# ═════════════════════════════════════════════════════════════════════════

def _client():
    """The OpenAI client for life derivations, or None.

    Prefers ``LIFE_PANEL_OPENAI_API_KEY`` (BE-10: an API path with no training
    retention) and falls back to the shared product key so dev works. Going
    direct rather than through services.llm.chat_complete is what makes the
    separate key possible — that wrapper builds its client from the product
    key by design."""
    key = (getattr(config, "LIFE_PANEL_OPENAI_API_KEY", "") or "").strip()
    if key:
        try:
            import openai
            return openai.OpenAI(api_key=key)
        except Exception as e:
            logger.warning("life: dedicated OpenAI client failed: %s", e)
            return None
    try:
        from services.openai_service import OpenAIService
        return OpenAIService().client
    except Exception as e:
        logger.warning("life: OpenAI client unavailable: %s", e)
        return None


def _log_derivation(surface: str, *, user_id: str, outcome: str,
                    **fields: Any) -> None:
    """The ONLY logger for model results in this module.

    Logs the derivation OUTPUT and sizes, never the note body (BE-10). The
    corpus contains addiction, sexual behaviour, confession-shaped religious
    material and named third parties; a log aggregator is a second, less
    guarded copy of all of it."""
    extra = " ".join(f"{k}={v}" for k, v in fields.items())
    logger.info("life.%s user=%s outcome=%s %s", surface, user_id, outcome,
                extra)


# Why a derivation produced nothing. Every value except "ok" means WE failed,
# not that the user's document was empty — a distinction the panel used to
# throw away, and the reason a 19,787-character goals document could come back
# as "nothing that reads as a goal came out of that document".
OUTCOME_OK = "ok"
OUTCOME_NO_CLIENT = "no_client"
OUTCOME_CALL_FAILED = "call_failed"
OUTCOME_EMPTY = "empty"
OUTCOME_TRUNCATED = "truncated"
OUTCOME_UNPARSEABLE = "unparseable"

# The outcomes that mean "we could not read it", as opposed to "we read it and
# it holds none of these". Callers use this to avoid telling somebody their
# document was empty when the truth is that we were cut off.
FAILED_OUTCOMES = frozenset({
    OUTCOME_NO_CLIENT, OUTCOME_CALL_FAILED, OUTCOME_EMPTY,
    OUTCOME_TRUNCATED, OUTCOME_UNPARSEABLE,
})


def _complete(spec: LLMSpec, *, system: str, user: str, surface: str,
              user_id: str) -> Optional[dict]:
    """One JSON-mode call. Returns the parsed dict, or None on ANY failure.

    Every caller treats None as "no derivation this turn" and still answers —
    capture never fails and never blocks, so an OpenAI outage costs the
    proposal, not the note."""
    parsed, _ = _complete_ex(spec, system=system, user=user, surface=surface,
                             user_id=user_id)
    return parsed


def _complete_ex(spec: LLMSpec, *, system: str, user: str, surface: str,
                 user_id: str) -> tuple[Optional[dict], str]:
    """``_complete``, plus WHY it produced what it did.

    Same call and the same never-raises contract; the second element is one of
    the OUTCOME_* constants. Callers that have to tell the user something about
    the result need it, because "the model returned no goals" and "the model
    was cut off mid-answer" are the same None to everyone else — and they are
    opposite things to say to a person who just handed over a document."""
    client = _client()
    if client is None:
        return None, OUTCOME_NO_CLIENT
    try:
        response = client.chat.completions.create(
            model=spec.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=spec.temperature,
            max_tokens=spec.max_tokens,
            response_format=spec.response_format,
            # Explicit, not inherited. `store=False` is already the default,
            # but a default is a decision someone else can change — and this
            # is the one surface where a silent flip to stored completions
            # would put addiction, confession-shaped material and named third
            # parties into a dashboard. Stating it also keeps these calls in
            # the STATELESS shape that zero-data-retention actually covers;
            # ZDR excludes the stateful products (conversations, files,
            # agents, batch), so a future "just use the Conversations API"
            # refactor here would quietly leave that protection behind.
            store=False,
        )
        # Cost ledger (token-pricing Phase 0). Recorded HERE, immediately
        # after the call returns and BEFORE any parsing — we have already
        # paid for this response, so a downstream parse failure must not
        # lose the cost row. This service bypasses services/llm.py, so
        # without this hook it is invisible to the ledger.
        # user_id is DELIBERATELY not recorded for the Life Panel: this
        # module handles addiction / confession-shaped material and keeps
        # no per-user trail outside its own tables. A per-surface cost
        # total is all Phase 0 needs.
        try:
            from services.llm_usage import record_response_usage
            record_response_usage(response, surface=f"life_{surface}",
                                  model=spec.model,)
        except Exception:
            pass
        choice = response.choices[0]
        raw = (choice.message.content or "").strip()
        # The model says when it stopped because it ran out of room rather
        # than because it was finished. In JSON mode that leaves a string that
        # ends mid-object, so json.loads fails and the whole extraction reads
        # as "found nothing" — which is how a 19,787-character document full
        # of goals came back empty. Read it.
        finish_reason = getattr(choice, "finish_reason", None)
    except Exception as e:
        _log_derivation(surface, user_id=user_id,
                        outcome=OUTCOME_CALL_FAILED, err=type(e).__name__)
        return None, OUTCOME_CALL_FAILED
    if not raw:
        _log_derivation(surface, user_id=user_id, outcome=OUTCOME_EMPTY)
        return None, OUTCOME_EMPTY
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        # Reported as TRUNCATED rather than unparseable when the model told us
        # it was cut off: they need different fixes. Truncation means the cap
        # is too low for documents this size; unparseable means the model
        # returned something malformed at its own length.
        outcome = (OUTCOME_TRUNCATED if finish_reason == "length"
                   else OUTCOME_UNPARSEABLE)
        _log_derivation(surface, user_id=user_id, outcome=outcome,
                        chars=len(raw), max_tokens=spec.max_tokens)
        return None, outcome
    if not isinstance(parsed, dict):
        return None, OUTCOME_UNPARSEABLE
    if finish_reason == "length":
        # Parsed anyway — the model happened to close its JSON right as it ran
        # out. The content is still short of what the document holds, so this
        # is not a clean read and must not be reported as one.
        _log_derivation(surface, user_id=user_id, outcome=OUTCOME_TRUNCATED,
                        chars=len(raw), max_tokens=spec.max_tokens,
                        parsed=True)
        return parsed, OUTCOME_TRUNCATED
    return parsed, OUTCOME_OK


# ═════════════════════════════════════════════════════════════════════════
# Retrieval — top-N, never the corpus
# ═════════════════════════════════════════════════════════════════════════

def retrieve_principles(user_id: str, text: str, *,
                        limit: int = RETRIEVAL_LIMIT) -> list[dict]:
    """The ~N principles that bear on this text, most relevant first.

    Deterministic lexical scoring over the user's own rows. Cheap enough to
    run on every note, and — more importantly — it never leaves the process,
    so the ranking step itself sends nothing anywhere."""
    rows = store.principles(user_id)
    scored: list[tuple[float, dict]] = []
    for row in rows:
        blob = f"{row.get('title') or ''} {row.get('body') or ''}"
        score = lp.phrase_relevance(text, blob)
        if score > 0:
            scored.append((score, row))
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("created_at") or "")))
    return [row for _, row in scored[:max(1, limit)]]


def attach_phrase(user_id: str, text: str) -> Optional[dict]:
    """The single best-fitting wall phrase for this note, or None.

    None is a real answer. Below the relevance floor, or when everything that
    clears it was used inside the rolling window, the right move is silence —
    a mismatched aphorism on a `#sin` note about addiction is worse than
    nothing, and it teaches the founder the wall is noise."""
    phrases = store.list_items(user_id, kind="phrase", status="active")
    if not phrases:
        return None
    recent = store.recently_attached_phrase_ids(user_id)
    picked = lp.pick_phrase(text, phrases, recently_used_ids=recent)
    if picked:
        store.insert_applications(user_id, lp.application_rows_for(
            user_id, [picked.get("id")], context="phrase"))
    return picked


def life_chat_context(user_id: str, question: str) -> Optional[dict]:
    """BE-9 — the per-user block for the Lounge prompt, or None.

    Returns ``{"principles": [...], "phrases": [...], "strategy": str}``
    already narrowed to the top few by relevance. ``master_doc_rag`` caps and
    trims again on the way in; both bounds are deliberate, because the failure
    this guards against is not a big payload — it is the Lounge prompt going
    back over its attention ceiling (PRs #81–#89), where the symptom is the
    bot quietly forgetting a rule rather than an error anyone sees.

    None when the user has nothing, so a participating user with an empty
    archive gets the same prompt as everyone else."""
    principles = retrieve_principles(user_id, question, limit=6)
    phrases = store.list_items(user_id, kind="phrase", status="active")
    scored = sorted(
        ((lp.phrase_relevance(question, p.get("body") or p.get("title") or ""),
          p) for p in phrases),
        key=lambda pair: -pair[0],
    )
    top_phrases = [p for score, p in scored
                   if score >= lp.PHRASE_RELEVANCE_FLOOR][:3]

    # The DAILY document only — the shortest of the eight and the one that
    # describes what the user is doing now. Sending the twenty-year vision to
    # a question about a speech would be the corpus dump this cap exists to
    # prevent.
    strategy = (store.latest_strategy(user_id).get("daily") or {}).get("body") or ""

    if not (principles or top_phrases or strategy):
        return None
    return {"principles": principles, "phrases": top_phrases,
            "strategy": strategy}


# ═════════════════════════════════════════════════════════════════════════
# BE-5 — the principles engine
# ═════════════════════════════════════════════════════════════════════════

_CASE_SYSTEM = f"""You assist a personal principles archive. The user has \
written a CASE (something that went wrong) and their OWN reflections on it.

You do THREE things and nothing else:
 1. Pick the mistake category from this CLOSED list. Use the exact keys. A \
case may carry more than one; do not invent a seventh.
    {', '.join(lp.CATEGORIES)}
 2. Say which of the user's EXISTING principles (given below, numbered) bore \
on this case. Return their numbers. Return an empty list if none apply — \
"I had no principles at that time" is a valid and honest answer for anything \
predating the archive.
 3. Propose ONE line phrasing a NEW principle this case teaches. One sentence, \
imperative, in the language the user wrote in. If the case teaches nothing \
new, return an empty string.

YOU DO NOT WRITE REFLECTIONS. The reflective prose is the user's and is \
already written. Never rewrite it, never extend it, never summarise it back.

Return STRICT JSON:
{{"category": ["<key>", ...],
  "applied_principle_numbers": [<int>, ...],
  "new_principle": "<one line or empty string>"}}"""


def derive_case(user_id: str, case_text: str, *,
                reflections: str = "") -> dict:
    """Propose the category, the applied principles and the ⚜️ one-liner.

    Returns ``{category, principles, new_principle, conflicts}`` — all
    PROPOSALS. Nothing is written to life_cases or life_items here; the route
    persists on approve.

    ``reflections`` is passed to the model as READ-ONLY context so its
    retrieval is grounded in what the user actually concluded. It is never
    echoed back into the return value, and no field of the return value is
    ever written to ``life_cases.reflections`` — that column takes request
    input only (N5).
    """
    existing = retrieve_principles(user_id, f"{case_text}\n{reflections}")
    numbered = "\n".join(
        f"{i + 1}. {(p.get('title') or p.get('body') or '').strip()}"
        for i, p in enumerate(existing)
    ) or "(the archive is empty)"

    parsed = _complete(
        SPEC_LIFE_CASE,
        system=_CASE_SYSTEM,
        user=(
            f"USER'S EXISTING PRINCIPLES (numbered, top {len(existing)} by "
            f"relevance — this is NOT the whole archive):\n{numbered}\n\n"
            f"CASE:\n{case_text}\n\n"
            f"THE USER'S OWN REFLECTIONS (read-only context — never rewrite "
            f"these):\n{reflections}"
        ),
        surface="case",
        user_id=user_id,
    ) or {}

    categories = lp.normalize_categories(parsed.get("category"))
    applied: list[dict] = []
    for n in (parsed.get("applied_principle_numbers") or []):
        try:
            idx = int(n) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(existing):
            applied.append(existing[idx])

    new_principle = parsed.get("new_principle")
    new_principle = new_principle.strip() if isinstance(new_principle, str) else ""

    _log_derivation("case", user_id=user_id,
                    outcome="ok" if parsed else "no_derivation",
                    categories=",".join(categories) or "-",
                    applied=len(applied),
                    proposed_principle=bool(new_principle),
                    retrieved=len(existing))

    # L-3: if the retrieved set pulls opposite ways, BOTH sides come back.
    # The system never picks.
    conflicts = lp.pair_conflicts(applied or existing)

    return {
        "category": categories,
        "principles": applied,
        "new_principle": new_principle,
        "conflicts": conflicts,
    }


def log_case_applications(user_id: str, case_id: str,
                          principles: list[dict]) -> int:
    """L-5: every principle cited by a case is logged as an application."""
    return store.insert_applications(user_id, lp.application_rows_for(
        user_id, [p.get("id") for p in (principles or [])],
        context="case", ref_id=case_id))


# ═════════════════════════════════════════════════════════════════════════
# BE-7 — retire
# ═════════════════════════════════════════════════════════════════════════

def retire_candidate(user_id: str, new_principle: dict) -> Optional[dict]:
    """The existing principle a new one appears to supersede, or None.

    Returns the candidate for a *"does this retire #12?"* prompt. Never
    retires anything on its own: veto is absolute, and a pair the founder
    already answered `no` on is never asked about again (BE-7). That
    persistence is the whole reason this checks the store first — a system
    that re-asks a settled veto is wearing someone down into an answer they
    already declined to give."""
    text = f"{new_principle.get('title') or ''} {new_principle.get('body') or ''}"
    for candidate in retrieve_principles(user_id, text, limit=3):
        if str(candidate.get("id")) == str(new_principle.get("id")):
            continue
        decided = store.retire_decision(
            user_id,
            old_principle_id=str(candidate.get("id")),
            new_principle_id=str(new_principle.get("id") or ""),
        )
        if decided:
            continue          # already answered — never re-asked
        return candidate
    return None


# ═════════════════════════════════════════════════════════════════════════
# BE-6 — strategy comparison, proposals, budget
# ═════════════════════════════════════════════════════════════════════════

_DIFF_SYSTEM = """You compare ONE observation a user just wrote against their \
own strategy documents, and report a DIRECT inconsistency if one exists.

Rules:
 * A direct inconsistency means the observation states something that \
contradicts a specific line in the documents. Vague tension is NOT an \
inconsistency. Most observations contradict nothing — returning \
{"inconsistent": false} is the common and correct answer.
 * If you report one, you MUST quote the contradicted line verbatim and name \
the section it came from, and you MUST propose the replacement text.
 * You MUST cite exactly one of the user's OWN principles (given below, \
numbered) as the warrant for the change. If no principle of theirs justifies \
it, there is no proposal — return {"inconsistent": false}.
 * Never propose a change to Section I (The Anchor) or to the RANK of the \
three bets. Those are hand-edited only. If that is what the observation bears \
on, set {"inconsistent": true, "target": "anchor"} and stop — report, do not \
propose.

Return STRICT JSON:
{"inconsistent": bool, "target": "<horizon.section>", "current": "<quoted \
line>", "proposed": "<replacement>", "warrant_principle_number": <int|null>,
 "report": "<one sentence for the report-only case>"}"""


def compare_to_strategy(user_id: str, note_text: str, *,
                        note_id: Optional[str] = None,
                        today: Optional[date] = None) -> dict:
    """Compare an ``#observation``-class note against the document set.

    Returns one of three shapes:
      ``{"kind": "none"}``          — no inconsistency (the common case)
      ``{"kind": "report", ...}``   — it bears on the immutable core (L-2a):
                                      reported, not proposed, and it STOPS
      ``{"kind": "proposal", ...}`` — a life_proposals row was created, either
                                      surfaced (today's one slot) or queued

    The budget (L-2b) is applied HERE rather than at render time, so a queued
    proposal is queued in the database and stays queued across restarts.
    """
    docs = store.latest_strategy(user_id)
    if not docs:
        return {"kind": "none", "reason": "no_strategy"}

    candidates = retrieve_principles(user_id, note_text)
    if not candidates:
        # No warrant is available, so no proposal can be created (L-2). Said
        # plainly rather than silently dropped: "nothing in your archive
        # justifies this change yet" is useful information.
        _log_derivation("diff", user_id=user_id, outcome="no_warrant")
        return {"kind": "none", "reason": "no_warrant"}

    numbered = "\n".join(
        f"{i + 1}. {(p.get('title') or p.get('body') or '').strip()}"
        for i, p in enumerate(candidates)
    )
    doc_block = "\n\n".join(
        f"### {horizon}\n{(row.get('body') or '')[:4000]}"
        for horizon, row in sorted(docs.items())
    )

    parsed = _complete(
        SPEC_LIFE_STRATEGY_DIFF,
        system=_DIFF_SYSTEM,
        user=(f"STRATEGY DOCUMENTS:\n{doc_block}\n\n"
              f"THE USER'S OWN PRINCIPLES (numbered):\n{numbered}\n\n"
              f"OBSERVATION:\n{note_text}"),
        surface="diff",
        user_id=user_id,
    ) or {}

    if not parsed.get("inconsistent"):
        _log_derivation("diff", user_id=user_id, outcome="consistent")
        return {"kind": "none", "reason": "consistent"}

    target = str(parsed.get("target") or "")

    # L-2a — the immutable core. Report and STOP. No row, no approve button.
    if lp.is_immutable_target(target):
        _log_derivation("diff", user_id=user_id, outcome="immutable_core",
                        target=target)
        return {
            "kind": "report",
            "target": target,
            # Redundant with kind="report", and stated anyway: the FE reads
            # this one field to decide whether an approve button exists, and
            # the two shapes must agree on the name. A reader who has only
            # ever seen `kind` would not know that omitting `report_only`
            # here is the difference between a report and an editable
            # proposal over the Anchor.
            "report_only": True,
            "report": (parsed.get("report") or "").strip() or (
                "This bears on the Anchor or the rank of the bets. Those are "
                "hand-edited only — nothing is proposed here."
            ),
        }

    warrant = None
    try:
        idx = int(parsed.get("warrant_principle_number")) - 1
        if 0 <= idx < len(candidates):
            warrant = candidates[idx]
    except (TypeError, ValueError):
        warrant = None
    if not warrant:
        # A proposal without a warrant is not created — the DB CHECK enforces
        # the same thing, so this is defence in depth rather than the only
        # guard.
        _log_derivation("diff", user_id=user_id, outcome="warrant_missing")
        return {"kind": "none", "reason": "no_warrant"}

    day = (today or datetime.now(timezone.utc).date())
    status = lp.plan_proposal_status(
        already_surfaced_today=store.count_surfaced_today(
            user_id, kind="strategy", today=day))

    row = store.insert_proposal(user_id, {
        "kind": "strategy",
        "target": target,
        "current": (parsed.get("current") or "")[:8000],
        "proposed": (parsed.get("proposed") or "")[:8000],
        "warrant_principle_id": warrant.get("id"),
        "origin_note_id": note_id,
        "status": status,
        "surfaced_on": day.isoformat() if status == "surfaced" else None,
        "expires_at": lp.expiry_for(),
        # Rank orders the weekly batch of three. Relevance of the warrant to
        # the note is the honest proxy: the change the archive most clearly
        # justifies goes first.
        "rank": lp.phrase_relevance(
            note_text,
            f"{warrant.get('title') or ''} {warrant.get('body') or ''}"),
    })
    if not row:
        return {"kind": "none", "reason": "write_failed"}

    # L-5 — creating a proposal cites its warrant principle.
    store.insert_applications(user_id, lp.application_rows_for(
        user_id, [warrant.get("id")], context="diff", ref_id=row.get("id")))

    _log_derivation("diff", user_id=user_id, outcome=status, target=target)
    return {"kind": "proposal", "proposal": row, "warrant": warrant,
            "status": status}


def apply_proposal(user_id: str, proposal: dict) -> Optional[dict]:
    """Approve a strategy proposal: write a NEW strategy version and mark it.

    Refuses the immutable core a second time. The first refusal is at creation
    (compare_to_strategy) — this one covers a row that reached the table by
    any other route, because "never proposed against" has to hold for the
    write path too, not only the path that happens to be in front of it."""
    target = str(proposal.get("target") or "")
    if lp.is_immutable_target(target):
        return None
    horizon = target.split(".")[0].strip().lower()
    if horizon not in lp.STRATEGY_HORIZONS:
        horizon = "weekly"

    current_row = store.latest_strategy(user_id).get(horizon)
    body = (current_row or {}).get("body") or ""
    old = proposal.get("current") or ""
    new = proposal.get("proposed") or ""
    if old and old in body:
        body = body.replace(old, new, 1)
    else:
        # The quoted line drifted since the proposal was written (another
        # approval edited it). Appending keeps the approved text rather than
        # discarding it, and the version history shows exactly what happened —
        # silently dropping an approved change would be the worse failure.
        body = f"{body}\n\n{new}".strip()

    written = store.insert_strategy_version(user_id, horizon=horizon,
                                            body=body)
    if not written:
        return None
    store.update_proposal(user_id, str(proposal.get("id")), {
        "status": "approved",
        "decided_at": datetime.now(timezone.utc).isoformat(),
    })
    if proposal.get("warrant_principle_id"):
        store.insert_applications(user_id, lp.application_rows_for(
            user_id, [proposal["warrant_principle_id"]], context="diff",
            ref_id=str(proposal.get("id"))))
    return written


# ═════════════════════════════════════════════════════════════════════════
# BE-4 — setup → document generation
# ═════════════════════════════════════════════════════════════════════════

_DOCS_SYSTEM = f"""You STRUCTURE a user's own answers into a set of strategy \
documents. You are formatting and cross-referencing THEIR material — you are \
not inventing goals, and you never add an ambition they did not state.

Produce one document per horizon: {', '.join(lp.STRATEGY_HORIZONS)}.

Every document begins with "## Section I — The Anchor", carrying the user's \
own words about who they are becoming. Section II lists the three bets in \
THEIR stated rank (1 The Life, 2 The Company, 3 The Dream) — never reorder \
them. Later sections hold the goals for that horizon with the user's own due \
labels copied VERBATIM (e.g. "[NOW]", "[Aug]", "[Jul '27]", "2035").

Write in the language the user answered in. Do not translate.

Return STRICT JSON: {{"documents": {{"<horizon>": "<markdown body>", ...}}}}"""


def generate_documents(user_id: str, answers: dict) -> dict[str, str]:
    """The eight-horizon document set, generated from the user's OWN answers.

    L-2 as amended: the system drafts the documents; every later CHANGE is
    gated by an approve with a warrant. The initial draft is not a change — it
    is the user's setup answers rendered as documents, which is why it lands
    directly at v1 rather than through the proposal queue.

    Item 9 (founder 2026-07-30): when the user uploaded a current strategy
    document during setup, its EXTRACTED TEXT rides along as clearly
    delimited read-only context, so the crafted documents align with what
    they already wrote. Still their material — the system prompt's "never add
    an ambition they did not state" covers the upload exactly as it covers
    the form answers."""
    payload = json.dumps(answers or {}, ensure_ascii=False)[:20000]
    uploaded = life_importer.latest_setup_document_text(user_id)
    if uploaded:
        payload += ("\n\nThe user's uploaded current strategy document:\n"
                    + uploaded[:12000])
    parsed = _complete(
        SPEC_LIFE_DOCS,
        system=_DOCS_SYSTEM,
        user=payload,
        surface="docs",
        user_id=user_id,
    ) or {}
    docs = parsed.get("documents")
    if not isinstance(docs, dict):
        _log_derivation("docs", user_id=user_id, outcome="no_documents")
        return {}
    out: dict[str, str] = {}
    for horizon, body in docs.items():
        key = str(horizon).strip().lower()
        if key in lp.STRATEGY_HORIZONS and isinstance(body, str) and body.strip():
            out[key] = body.strip()
    _log_derivation("docs", user_id=user_id, outcome="ok", horizons=len(out))
    return out


_DOC_DRAFT_SYSTEM = """Today is {today}.

You read ONE strategy document a user uploaded and EXTRACT what THEY \
EXPLICITLY WROTE. You are a transcriber, not a coach: you never invent, never \
complete, and never add an ambition they did not state. If the document states \
nothing for a list, return it empty.

Extract three lists:
 1. goals — each with the user's own wording. Copy any due notation VERBATIM \
(e.g. "[NOW]", "[This week]", "[Aug]", "[Jul '27]", "to July 2031", "2035") \
into due_label — that is what the person reads back, so it keeps their words.

    ALSO RESOLVE that notation into due_date, a strict calendar date, \
YYYY-MM-DD. This is the one place you are allowed to compute rather than copy, \
and it is not interpretation: "to July 2031" is 2031-07-01, "[Aug]" is the \
first day of the NEXT August from today, "[Jul '27]" is 2027-07-01, "2035" is \
2035-01-01, "by Friday" is the coming Friday, "this week" is the coming Sunday, \
"end of the quarter" is the last day of the current quarter. A month with no \
year means the next time that month occurs. A bare year means January 1st of \
it. Never a date in the past for a goal written as still to come.

    due_date is "" ONLY when the document gives no timing at all for that goal, \
or gives one no calendar can hold ("someday", "eventually"). A standing \
intention like "[NOW]" has no end date either: leave due_date "" for it. Do not \
guess a date to fill the field — an invented deadline reads as a fact the \
person committed to.

    horizon is one of: now, week, month, quarter, year, five_year, ten_year, \
twenty_year — or "" when the document does not say. Use "week" only when the \
document itself scopes the goal to a week ("this week", "by Friday", a weekly \
plan or review heading); a goal simply written down under no heading is "", \
not "week". bet is one of: life, company, dream — or "" when the document \
does not tie the goal to a bet.
 2. habits — recurring practices the document names.
 3. distractions — each with the ENVIRONMENTAL response the document pairs \
it with, if one is written; "" otherwise.

Keep the user's language. Do not translate. due_date is a date, not language: \
it is the same digits whatever the document is written in.

Return STRICT JSON:
{{"goals": [{{"title": "", "horizon": "", "due_label": "", "due_date": "", \
"bet": ""}}],
 "habits": [{{"title": ""}}],
 "distractions": [{{"title": "", "response": ""}}]}}"""

SPEC_LIFE_DOC_DRAFT = LLMSpec(
    model=STRONG_MODEL,
    # Extraction, not invention — the same temperature reasoning as the
    # strategy diff: creativity here would be goals the user never wrote.
    temperature=0.1,
    # 2000 was too small and produced a SILENT wrong answer, not a slow one.
    # The upload accepts 20,000 characters of strategy document; a dense one
    # holds far more than 2000 tokens of goals, so the model stopped
    # mid-object, JSON mode left a string that would not parse, and the person
    # was told their document contained no goals. Sized to fit the largest
    # document the endpoint will accept.
    #
    # max_tokens is a CEILING, not a spend: a short document still generates a
    # short answer and still costs what it always did. Only the documents that
    # were being silently truncated pay more, and they are the ones that were
    # returning nothing.
    max_tokens=8000,
    response_format={"type": "json_object"},
)


# ─────────────────────────────────────────────────────────────────────────
# The kind hint (FE dock, 2026-07-31)
# ─────────────────────────────────────────────────────────────────────────
# The upload used to have one door, at the foot of /panel/goals. It now sits
# under every panel view, and the FE says which view the user was standing on
# when they handed the document over.
#
# The hint SCOPES a second read of the same text; it never filters the answer.
# A phrases document opened from /panel/phrases that also holds three goals
# still offers the goals — hiding them would be the panel overruling what the
# person actually wrote. Two consequences, both deliberate:
#
#   * an OMITTED hint runs exactly the pass this function has always run, so
#     the un-hinted call is byte-for-byte the endpoint it was yesterday;
#   * a hint the base pass already covers (goal / habit / distraction / bet)
#     also changes nothing — /panel/goals keeps the rows, the bets and the due
#     labels it had before the dock existed.
#
# `task` and `event` are accepted as hints and add no pass of their own. Both
# would draft rows the base pass already drafts under a different name — a
# dated goal is exactly what /v2/life/timeline renders as a marker — and two
# tickable copies of one line is a worse answer than an honest empty one.
_DOC_DRAFT_LINE_DEFINITIONS: dict[str, str] = {
    "phrase": (
        "PHRASES — lines the person wants handed back to them at the right "
        "moment: aphorisms, quotations, prayers, one-liners they wrote down "
        "to keep. Copy each one VERBATIM, without the surrounding quotation "
        "marks. A paragraph of prose is not a phrase."),
    "principle": (
        "PRINCIPLES — rules the person wrote for themselves: 'always X', "
        "'never Y', a lesson stated as a rule they intend to live by. Copy "
        "their wording. A goal they intend to reach is not a principle, and "
        "an account of what happened to them is not a principle."),
    "win": (
        "WINS — what the person records as having gone well: what they did, "
        "what they are counting as a win. Copy their wording. Something they "
        "still intend to do is not a win."),
}

_DOC_DRAFT_LINES_SYSTEM = """You read ONE document a user uploaded and \
EXTRACT what THEY EXPLICITLY WROTE. You are a transcriber, not a coach: you \
never invent, never complete, never rephrase, and never add one they did not \
write. If the document holds none, return an empty list — that is a real \
answer and the product says so plainly.

{definition}

Keep the user's language. Do not translate. One written line is one entry: \
never merge two, never split one.

Return STRICT JSON: {{"lines": ["", ""]}}"""


def _draft_lines_from_document(user_id: str, text: str,
                               kind: str) -> list[dict]:
    """The hinted kind's own read of the same text. WRITES NOTHING.

    A failure here costs the hinted rows and nothing else: the caller keeps
    the base pass's rows and the user gets a screen with something on it,
    which is the same bargain every derivation in this module makes."""
    definition = _DOC_DRAFT_LINE_DEFINITIONS.get(kind)
    if not definition:
        return []
    # _complete_ex, not _complete: BOTH document passes go through one seam,
    # so a truncated hinted read is as visible as a truncated base one — and
    # so there is a single place to stub when testing this path.
    parsed, outcome = _complete_ex(
        SPEC_LIFE_DOC_DRAFT,
        system=_DOC_DRAFT_LINES_SYSTEM.format(definition=definition),
        user=(text or "")[:20000],
        surface="doc_draft_kind",
        user_id=user_id,
    )
    parsed = parsed or {}
    lines = parsed.get("lines")
    rows = life_importer.plan_document_lines(
        user_id, kind, lines if isinstance(lines, list) else [])
    _log_derivation("doc_draft_kind", user_id=user_id, outcome=outcome,
                    kind=kind, drafted=len(rows))
    return rows


def draft_items_from_document(user_id: str, text: str, *,
                              kind: Optional[str] = None) -> list[dict]:
    """Item 9 — DRAFT rows from an uploaded strategy document. Returns planned
    rows only; WRITES NOTHING.

    Extraction (model, closed shape) feeds ``life_import.plan_strategy`` so
    the drafted rows take exactly the shape the importer would give them —
    including the three bets seeded at their LOCKED rank (L-2a), never taken
    from the document. The route returns these as checkable rows; only what
    the user ticks is ever created (N5), and that happens in a separate,
    explicit call.

    ``kind`` is the panel view the user was standing on, and it is a HINT —
    see the block above for what it does and, more importantly, what it does
    not do."""
    items, _ = draft_items_from_document_ex(user_id, text, kind=kind)
    return items


def draft_items_from_document_ex(
        user_id: str, text: str, *,
        kind: Optional[str] = None) -> tuple[list[dict], str]:
    """``draft_items_from_document``, plus whether the read actually worked.

    The second element is one of the OUTCOME_* constants, and anything in
    FAILED_OUTCOMES means the rows are short because WE fell over — not
    because the document held nothing. The endpoint needs that distinction:
    without it, a truncated read and a genuinely goal-less document are the
    same empty list, and the person gets told their document had no goals in
    it when we simply ran out of room reading it."""
    parsed, outcome = _complete_ex(
        SPEC_LIFE_DOC_DRAFT,
        # The date is PASSED IN, not left to the model's own idea of now.
        # "[Aug]", "by Friday" and "this week" cannot be resolved without it,
        # and a model guessing the year is how a 2026 goal lands on 2024.
        system=_DOC_DRAFT_SYSTEM.format(
            today=datetime.now(timezone.utc).date().isoformat()),
        user=(text or "")[:20000],
        surface="doc_draft",
        user_id=user_id,
    )
    parsed = parsed or {}
    plan = life_importer.plan_strategy(user_id, {
        "goals": parsed.get("goals") or [],
        "habits": parsed.get("habits") or [],
        "distractions": parsed.get("distractions") or [],
    })
    items = plan.get("items") or []
    hinted = kind if kind in life_importer.DOC_DRAFT_LINE_KINDS else None
    if hinted:
        # Hinted rows lead. The user is standing on that view; the kind they
        # asked about should be the first thing they see, with everything
        # else the document holds still under it.
        items = _draft_lines_from_document(user_id, text, hinted) + items
    # The setup flow folds these rows onto the eight STRATEGY screens, whose
    # vocabulary is not the item one: an item's `horizon` says when a goal is
    # due (now/month/quarter/…), a strategy horizon says which document you are
    # looking at (daily/weekly/monthly/…). They coincide only on the long end,
    # so the FE cannot fold on `horizon` alone.
    #
    # `horizon` is left EXACTLY as-is — /setup/apply-proposed validates it
    # against HORIZONS when it writes the item, so renaming it would make every
    # applied row fail validation. The translation rides alongside instead, and
    # is null when there is no mapping (the FE routes those to its remainder
    # review rather than dropping them).
    #
    # Stamped AFTER the hinted prepend, deliberately: the FE branches on the
    # VALUE of `strategy_horizon`, not on whether the key is there, so every
    # row it is handed must carry it — and the hinted rows are the ones
    # LEADING the response. A phrase has no `horizon` at all, so it maps to
    # None and routes to the remainder review, which is the right screen for
    # it: a phrase does not belong on a dated strategy document.
    for _it in items:
        if isinstance(_it, dict):
            _it["strategy_horizon"] = lp.strategy_horizon_for(_it.get("horizon"))
    _log_derivation("doc_draft", user_id=user_id, outcome=outcome,
                    kind=kind or "-", drafted=len(items))
    return items, outcome


def complete_setup_and_generate(user_id: str) -> dict:
    """Finish setup: write v1 of every horizon, then REPLAY the notes the user
    typed before the gate let them in (§6.2), oldest first.

    The replay is not a nicety. Setup is a hard gate: a `#` typed by a user who
    has not completed setup returns a redirect. Someone who reaches for
    `#mistake` is holding a thought they wanted recorded — losing it to a
    redirect teaches them the tag costs something, and they stop using it."""
    setup = store.get_setup(user_id) or {}
    answers = setup.get("answers") or {}
    docs = generate_documents(user_id, answers)
    written = []
    for horizon, body in docs.items():
        row = store.insert_strategy_version(user_id, horizon=horizon,
                                            body=body)
        if row:
            written.append(horizon)
    store.complete_setup(user_id)

    replayed = []
    pending = store.pending_replay_notes(user_id)
    for note in pending:
        tag, route, remainder = lp.parse_tag(note.get("body") or "")
        result: dict[str, Any] = {"note_id": note.get("id"), "tag": tag,
                                  "route": route}
        if route == "case":
            result["derivation"] = derive_case(user_id, remainder)
        elif route == "goal_diff":
            result["derivation"] = compare_to_strategy(
                user_id, remainder, note_id=str(note.get("id")))
        replayed.append(result)
    store.mark_replayed(user_id, [str(n.get("id")) for n in pending])

    return {"horizons": written, "replayed": replayed}


# ═════════════════════════════════════════════════════════════════════════
# BE-7 — board + lookup
# ═════════════════════════════════════════════════════════════════════════

_BOARD_SYSTEM = """You answer as ONE named advisor, in that advisor's lens, \
to a person stuck on something.

Rules:
 * Stay in the lens you are given. You are not a generic assistant.
 * Be short. Three to six sentences.
 * You are advice, not a substitute for the user's prayer or their own \
judgement. Never present yourself as either.
 * Answer in the language the question was asked in.

Return STRICT JSON: {"answer": "<the advice>"}"""


def board_answer(user_id: str, question: str) -> dict:
    """Route to one of the five advisors by domain and answer in that lens.

    Says WHICH advisor and WHY — a bad routing should be visible and
    correctable rather than felt as a vague wrongness."""
    key, why = lp.route_advisor(question)
    advisor = next(a for a in lp.ADVISORS if a["key"] == key)
    parsed = _complete(
        SPEC_LIFE_BOARD,
        system=_BOARD_SYSTEM,
        user=(f"ADVISOR: {advisor['name']}\nLENS: {advisor['lens']}\n\n"
              f"QUESTION:\n{question}"),
        surface="board",
        user_id=user_id,
    ) or {}
    answer = (parsed.get("answer") or "").strip()
    _log_derivation("board", user_id=user_id,
                    outcome="ok" if answer else "no_answer", advisor=key)
    return {
        "advisor": advisor["name"],
        "advisor_key": key,
        "why": why,
        "answer": answer,
        "note": lp.ADVISOR_PRAYER_LINE,
    }


def lookup(user_id: str, query: str) -> dict:
    """Top-10 retrieval over principles + phrases. Never a corpus dump."""
    found = retrieve_principles(user_id, query)
    phrases = store.list_items(user_id, kind="phrase", status="active")
    scored = sorted(
        ((lp.phrase_relevance(query, p.get("body") or p.get("title") or ""), p)
         for p in phrases),
        key=lambda pair: -pair[0],
    )
    top_phrases = [p for score, p in scored
                   if score >= lp.PHRASE_RELEVANCE_FLOOR][:RETRIEVAL_LIMIT]
    if found:
        store.insert_applications(user_id, lp.application_rows_for(
            user_id, [p.get("id") for p in found], context="lookup"))
    return {"principles": found, "phrases": top_phrases,
            "conflicts": lp.pair_conflicts(found)}


# ═════════════════════════════════════════════════════════════════════════
# User copy overrides (founder decision 2026-07-30)
# ═════════════════════════════════════════════════════════════════════════
# The daily check-in's mantra header and distraction question ship with the
# founder's strings as DEFAULTS (they live in the FE's copy.ts) and are
# per-user editable. NULL means "use the default", so clearing a field is how
# the original line comes back. Table I/O sits here — next to the daily-card
# engine whose surface renders these lines — because life_store is out of
# scope for this change; same db-client-owned-table precedent as the setup
# documents in life_import.

_USER_COPY_TABLE = "life_user_copy"
_USER_COPY_FIELDS = ("mantra_title", "mantra_question",
                     "distraction_question")
_USER_COPY_MAX_LEN = 300


def _copy_table():
    from services.db import db
    return db.client.table(_USER_COPY_TABLE)


def _copy_rows(result: Any) -> list[dict]:
    data = getattr(result, "data", None)
    return list(data) if isinstance(data, list) else []


def get_user_copy(user_id: str) -> dict:
    """This user's overrides. Every field present, NULL when unset — the FE
    falls back to the founder defaults on NULL. Never raises."""
    try:
        rows = _copy_rows(_copy_table().select("*")
                          .eq("user_id", user_id).limit(1).execute())
        row = rows[0] if rows else {}
    except Exception as e:
        logger.warning("life: get_user_copy failed user=%s: %s", user_id, e)
        row = {}
    return {field: row.get(field) or None for field in _USER_COPY_FIELDS}


def sanitize_user_copy(body: Any) -> dict:
    """The PUT contract: only the three known fields; trimmed and capped;
    blank or non-string ⇒ NULL, which MEANS "back to the founder's line"."""
    if not isinstance(body, dict):
        return {}
    out: dict[str, Any] = {}
    for field in _USER_COPY_FIELDS:
        if field not in body:
            continue
        value = body.get(field)
        text = value.strip()[:_USER_COPY_MAX_LEN] \
            if isinstance(value, str) else ""
        out[field] = text or None
    return out


def upsert_user_copy(user_id: str, fields: dict) -> Optional[dict]:
    """Write the user's own wording. Returns the effective overrides."""
    clean = sanitize_user_copy(fields)
    if not clean:
        return get_user_copy(user_id)
    try:
        _copy_table().upsert({
            "user_id": user_id,
            **clean,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="user_id").execute()
    except Exception as e:
        logger.error("life: upsert_user_copy failed user=%s: %s", user_id, e)
        return None
    return get_user_copy(user_id)


def delete_user_copy(user_id: str) -> Optional[int]:
    """Hard-delete path (BE-10). Count, or None so the route can report."""
    try:
        res = _copy_table().delete().eq("user_id", user_id).execute()
        return len(_copy_rows(res))
    except Exception as e:
        logger.error("life: delete_user_copy failed user=%s: %s", user_id, e)
        return None


def export_user_copy(user_id: str) -> Optional[list[dict]]:
    """The raw rows for the panel export. None on failure so the export can
    report itself incomplete."""
    try:
        return _copy_rows(_copy_table().select("*")
                          .eq("user_id", user_id).limit(10).execute())
    except Exception as e:
        logger.warning("life: export_user_copy failed user=%s: %s",
                       user_id, e)
        return None


# ═════════════════════════════════════════════════════════════════════════
# BE-8 — the daily card
# ═════════════════════════════════════════════════════════════════════════

# Founder 2026-08-01, via the FE handoff: "separate must-dos from like-to-dos,
# rank by expected value (probability × payoff, weighed against the cost of
# waiting), highest-impact-highest-probability first — for each bet."
#
# THE NUMBERS STAY IN THE MODEL'S HEAD (AC-9 / N4). This call returns an
# ORDER of ids and nothing else: no expected value, no probability, no payoff
# ever reaches a payload, a log line or a table. What persists is order_key —
# a sort position, the same field every list already rides. The estimate is
# internal machinery, never a surfaced figure.
SPEC_LIFE_GOAL_RANK = LLMSpec(
    model=CHEAP_MODEL,
    # Near-deterministic: the same goals should rank the same way on a re-run.
    # A ranking that reshuffles daily without the goals changing reads as the
    # system changing its mind about the founder's priorities overnight.
    temperature=0.1,
    max_tokens=1000,
    response_format={"type": "json_object"},
)

_GOAL_RANK_SYSTEM = """You order ONE person's goals within each of their \
three bets, following Ray Dalio's expected-value discipline:

 * separate the must-dos from the like-to-dos — a goal with a hard \
consequence for missing it outranks a nice-to-have;
 * among the rest, rank by expected value: probability of success times the \
size of the payoff, weighed against the cost of waiting — \
highest-impact-highest-probability first;
 * a goal whose window is closing soon outranks an equal goal that can wait.

Estimate whatever you need internally. Return ONLY the order — never a \
number, a score or a reason. Do not drop, merge or invent an id; every id \
you were given for a bet appears exactly once in that bet's list.

Return STRICT JSON: {"order": {"<bet>": ["<id>", ...], ...}}"""


def rank_goals_by_expected_value(user_id: str) -> int:
    """Write the Dalio order into ``order_key``, per bet. Returns rows moved.

    Runs at GENERATION TIME — once, when the day's card does not exist yet —
    because that is the moment the order is consumed: the card's one-thing and
    focus blocks take the head of it, and every list view sorts by it. The FE
    defers to this order for every undated goal, so writing it here is the
    whole of the ship.

    THE FAILURE MODE IS THE STANDING BARGAIN: any failure costs the re-rank
    and nothing else. The card is still built, the lists still serve, and the
    order is simply yesterday's — which was also good.

    Only ``order_key`` is ever written. A goal the model forgets keeps its
    place at the tail in its previous order; an id the model invents is
    ignored; a bet with fewer than two goals has nothing to rank."""
    goals = [g for g in store.list_items(user_id, kind="goal",
                                         status="active")
             if str(g.get("collection") or "").strip().lower()
             in {str(b["key"]) for b in lp.BETS}]
    grouped: dict[str, list[dict]] = {}
    for goal in goals:
        grouped.setdefault(
            str(goal.get("collection")).strip().lower(), []).append(goal)
    rankable = {key: rows for key, rows in grouped.items() if len(rows) >= 2}
    if not rankable:
        return 0

    payload = {
        key: [{"id": str(g.get("id")),
               "goal": (g.get("title") or "")[:300],
               "detail": (g.get("body") or "")[:300],
               "due": g.get("due_label") or "",
               "horizon": g.get("horizon") or ""}
              for g in rows]
        for key, rows in rankable.items()
    }
    parsed, outcome = _complete_ex(
        SPEC_LIFE_GOAL_RANK,
        system=_GOAL_RANK_SYSTEM,
        user=json.dumps(payload, ensure_ascii=False)[:20000],
        surface="goal_rank",
        user_id=user_id,
    )
    order = (parsed or {}).get("order")
    if outcome in FAILED_OUTCOMES or not isinstance(order, dict):
        return 0

    moved = 0
    for key, rows in rankable.items():
        proposed = order.get(key)
        if not isinstance(proposed, list):
            continue
        known = {str(g.get("id")): g for g in rows}
        # The model's order first (unknown ids dropped), then anything it
        # forgot, in the order it already had — nothing is ever lost to a
        # short answer.
        ranked = [str(i) for i in proposed if str(i) in known]
        ranked += [gid for g in rows
                   if (gid := str(g.get("id"))) not in ranked]
        for index, gid in enumerate(ranked):
            new_key = float(index + 1) * 1000.0
            if float(known[gid].get("order_key") or 0) == new_key:
                continue
            if store.update_item(user_id, gid, {"order_key": new_key}):
                moved += 1
    _log_derivation("goal_rank", user_id=user_id, outcome=outcome,
                    bets=len(rankable), moved=moved)
    return moved


# The drafted day-sized action (founder-agreed contract, 2026-08-02 —
# docs/life-checkin-learning-contract.md). The card used to show the goal's
# TITLE as the one thing: "Profitable" is not something you can do before
# lunch. This drafts the concrete step; the goal it serves stays named beside
# it, and the deterministic title card is the fallback for every failure.
SPEC_LIFE_DAY_DRAFT = LLMSpec(
    model=CHEAP_MODEL,
    # Low, not zero: the same goal should yield a similar-sized step on a
    # re-run, but today's step is allowed to differ from yesterday's — that
    # is what makes it a day's work rather than a rename of the goal.
    temperature=0.3,
    max_tokens=600,
    response_format={"type": "json_object"},
)

_DAY_DRAFT_SYSTEM = """Today is {today}.

You draft ONE day-sized action for each of a person's goals — the concrete \
step they could take TODAY that moves that goal, in their own working \
language (keep Polish Polish, English English, matching each goal's own \
wording).

A day-sized action names something finishable before the day ends: "send the \
deck to the three warm leads", not "grow the company". Never restate the \
goal, never merge two goals, never invent a goal that is not given, and \
never add advice, encouragement or commentary — the action line is the whole \
answer.

Return STRICT JSON: {{"actions": {{"<goal_id>": "<the action>", ...}}}}"""


def draft_daily_actions(user_id: str, card: dict) -> dict:
    """Overlay drafted day-sized actions onto a built card. Never raises.

    The card arrives deterministic — goal titles in the slots, and a
    ``draft_meta`` skeleton naming which goal each slot serves. One model
    call drafts an action per slot; each drafted action replaces the slot's
    display text AND is recorded in ``draft_meta`` as ``drafted``, which is
    the silent learner's input side (the contract's extraction/formulation
    layers). A goal the model skips keeps its title; a failed call keeps the
    whole card exactly as built — the fallback IS yesterday's behaviour."""
    meta = card.get("draft_meta") or {}
    slots: list[dict] = []
    if meta.get("one_thing"):
        slots.append(meta["one_thing"])
    slots.extend(meta.get("focus") or [])
    if not slots:
        return card
    payload = {
        "goals": [{"id": s.get("goal_id"),
                   "goal": (s.get("goal") or "")[:300],
                   "detail": (s.get("detail") or "")[:300],
                   "due": s.get("due") or "",
                   "bet": s.get("bet") or ""}
                  for s in slots]
    }
    parsed, outcome = _complete_ex(
        SPEC_LIFE_DAY_DRAFT,
        system=_DAY_DRAFT_SYSTEM.format(
            today=datetime.now(timezone.utc).date().isoformat()),
        user=json.dumps(payload, ensure_ascii=False)[:20000],
        surface="day_draft",
        user_id=user_id,
    )
    actions = (parsed or {}).get("actions")
    if outcome in FAILED_OUTCOMES or not isinstance(actions, dict):
        _log_derivation("day_draft", user_id=user_id, outcome=outcome,
                        drafted=0)
        return card

    def _action_for(slot: Optional[dict]) -> Optional[str]:
        if not slot:
            return None
        text = actions.get(str(slot.get("goal_id")))
        text = str(text).strip()[:500] if isinstance(text, str) else ""
        if text:
            slot["drafted"] = text
        return text or None

    drafted = 0
    one = _action_for(meta.get("one_thing"))
    if one:
        card["one_thing"] = one
        drafted += 1
    for index, slot in enumerate(meta.get("focus") or []):
        text = _action_for(slot)
        blocks = card.get("focus_blocks") or []
        if text and index < len(blocks):
            blocks[index]["text"] = text
            drafted += 1
    _log_derivation("day_draft", user_id=user_id, outcome=outcome,
                    drafted=drafted)
    return card


def swap_one_thing(user_id: str, day_row: dict, goal_id: str) -> Optional[dict]:
    """The founder replaces the ranked one thing with another goal of theirs.

    Returns the fields to write, or None when the goal cannot be resolved as
    the caller's own active goal.

    Two records, two consumers, NEVER crossed (the contract's hard line):
    the swap sets ``displaced_goal_id`` — once, the first time, naming the
    RANKED goal that got moved aside — which only the Sunday-review gate may
    read. The drafting learner never sees it, and the swap writes nothing
    into the (drafted → accepted) pairs."""
    goal = store.get_item(user_id, goal_id)
    if not goal or goal.get("kind") != "goal" \
            or (goal.get("status") or "active") != "active":
        return None
    meta = dict(day_row.get("draft_meta") or {})
    # If the chosen goal already holds a drafted action on today's card (it
    # was a focus block), promote that action; otherwise the goal's title is
    # the honest text — no fresh model call on a PATCH.
    text = goal.get("title") or goal.get("body") or ""
    for slot in [meta.get("one_thing"), *(meta.get("focus") or [])]:
        if slot and str(slot.get("goal_id")) == str(goal_id) \
                and slot.get("drafted"):
            text = slot["drafted"]
            break
    bets = {str(b.get("id")): b
            for b in store.list_items(user_id, kind="bet", status="active")}
    bet_row = bets.get(str(goal.get("bet_id") or ""))
    locked = {str(b["key"]): b for b in lp.BETS}.get(
        str(goal.get("collection") or "").strip().lower())
    bet_title = ((bet_row or {}).get("title")
                 or (f"{locked['emoji']} {locked['title']}" if locked else ""))
    if not meta.get("displaced_goal_id"):
        displaced = (meta.get("one_thing") or {}).get("goal_id")
        if displaced and str(displaced) != str(goal_id):
            meta["displaced_goal_id"] = str(displaced)
    meta["one_thing"] = {"goal_id": str(goal_id),
                         "goal": goal.get("title") or "",
                         "drafted": None}
    return {"one_thing": text, "one_thing_bet": bet_title,
            "draft_meta": meta}


def build_daily_card(user_id: str, day: date) -> dict:
    """The card's content for one date, from the user's own rows.

    Deterministic — habits, the ranked bets and the goals are the founder's
    own data, so assembling the card needs no model and therefore costs
    nothing and cannot hallucinate a task.

    All three bets are eligible from day one (founder 2026-07-26,
    ``lp.BET_3_DRIVES_DAILY_EXECUTION``). What holds the weekly document's
    rule is the SORT, not an exclusion: goals are ordered by bet rank first, so
    🟣 The Dream can only take the ONE THING slot when Bets 1 and 2 have
    nothing left — the one day you want the dream on the card instead of an
    empty card. On every other day it fills the tail.

    Every block carries the bet it serves, because §3.2 requires the card to be
    able to SAY which bet a proposed task belongs to. Without that the rank is
    invisible on the surface where it matters most: a 🟣 item and a 🔵 item
    look identical, and "Bet 3 never outranks Bet 2" becomes unverifiable by
    the person reading the card."""
    habits = store.list_items(user_id, kind="habit", status="active")
    goals = store.list_items(user_id, kind="goal", status="active")
    bets = {str(b.get("id")): b
            for b in store.list_items(user_id, kind="bet", status="active")}
    # `collection` carries the bet on every goal apply-proposed creates —
    # "life" / "company" / "dream" — while `bet_id` (a row uuid) is only ever
    # set by older paths. Resolving bet_id ALONE made every document-drafted
    # goal "unattached": rank 99, sorted last, no bet named on the card. The
    # same one-field bug the FE's mapper had, mirrored here.
    by_key = {str(b["key"]): b for b in lp.BETS}

    def _bet(goal: dict) -> Optional[dict]:
        row = bets.get(str(goal.get("bet_id") or ""))
        if row:
            return {"rank": float(row.get("order_key") or 99),
                    "title": row.get("title") or ""}
        locked = by_key.get(str(goal.get("collection") or "").strip().lower())
        if locked:
            return {"rank": float(locked["rank"]),
                    "title": f"{locked['emoji']} {locked['title']}"}
        return None

    def _bet_rank(goal: dict) -> float:
        # An unattached goal sorts last. It is not a Bet-3 item — it is a goal
        # nobody has decided a bet for, and it should not outrank one that has
        # been thought about.
        bet = _bet(goal)
        return bet["rank"] if bet else 99.0

    def _bet_title(goal: dict) -> str:
        bet = _bet(goal)
        return bet["title"] if bet else ""

    def _current(goal: dict) -> bool:
        # THE CARD ASSERTS ITS CONTENT IS TODAY'S WORK, in its own copy — so a
        # row whose date has passed must not be selected as current, whatever
        # the list views (rightly, honestly) still display. This is the 29/07
        # task shown on 01/08. Due TODAY is current all day, matching the FE's
        # calendar-day rule; the row is left out rather than re-dated, because
        # silently rewriting the date the person wrote would be the system
        # editing their data to make its own claim true (N5), and expiry is
        # silent state, never a nudge (N3).
        due = str(goal.get("due_at") or "")[:10]
        return not due or due >= day.isoformat()

    eligible = [
        g for g in goals
        if _current(g)
        and (lp.BET_3_DRIVES_DAILY_EXECUTION or _bet_rank(g) < 3)
    ]
    eligible.sort(key=lambda g: (_bet_rank(g),
                                 0 if g.get("horizon") == "now" else 1,
                                 float(g.get("order_key") or 0)))

    def _text(goal: dict) -> str:
        return goal.get("title") or goal.get("body") or ""

    one_thing = _text(eligible[0]) if eligible else ""
    # `goal` / `goal_id` ride the block so the card can say what an action is
    # TOWARD once drafting replaces the text — and so a swap can promote a
    # focus block's own drafted action.
    focus = [{"text": _text(g), "box": False, "bet": _bet_title(g),
              "goal": _text(g), "goal_id": str(g.get("id") or "")}
             for g in eligible[1:4]]

    def _slot(goal: dict) -> dict:
        # The draft_meta skeleton: who each slot serves, with the context the
        # drafting pass needs. `drafted` stays None until a draft lands, so a
        # card built without the model is exactly the card we always built.
        return {"goal_id": str(goal.get("id") or ""),
                "goal": _text(goal),
                "detail": goal.get("body") or "",
                "due": goal.get("due_label") or "",
                "bet": _bet_title(goal),
                "drafted": None}

    return {
        "morning_checks": {
            (h.get("title") or f"habit-{i}"): False
            for i, h in enumerate(habits)
        },
        "one_thing": one_thing,
        "one_thing_bet": _bet_title(eligible[0]) if eligible else "",
        "focus_blocks": focus,
        "draft_meta": {
            "one_thing": _slot(eligible[0]) if eligible else None,
            "focus": [_slot(g) for g in eligible[1:4]],
        },
        "evening_line": "am I becoming the man I described?",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def ensure_daily_card(user_id: str, day: Optional[date] = None) -> Optional[dict]:
    """Today's card, generated if it does not exist yet — and then it WAITS.

    Generation is scheduled; delivery is not (L-4 / N8). Nothing in this
    function or anywhere below it sends an email, a push or a notification.
    Calling it from a 05:00 cron and calling it from the panel's first read of
    the day produce the same row, which is why the cron is an optimisation
    rather than a dependency: if it never runs, the card is simply generated
    when the founder opens the panel."""
    target = day or datetime.now(timezone.utc).date()
    existing = store.get_day(user_id, target.isoformat())
    if existing:
        return existing
    # A new day is the one moment the Dalio order is recomputed — BEFORE the
    # card is built, because the card's one-thing and focus blocks take the
    # head of that order. Once per day, not per read: the card existing is
    # the marker that today's ranking already ran. Any failure inside costs
    # the re-rank and nothing else; the card is still built on yesterday's
    # order, which was also good.
    try:
        rank_goals_by_expected_value(user_id)
    except Exception as e:                          # pragma: no cover
        logger.warning("life: goal rank failed user=%s: %s", user_id, e)
    card = build_daily_card(user_id, target)
    try:
        card = draft_daily_actions(user_id, card)
    except Exception as e:                          # pragma: no cover
        logger.warning("life: day draft failed user=%s: %s", user_id, e)
    row = store.upsert_day(user_id, target.isoformat(), card)
    if row is None and "draft_meta" in card:
        # "On main" is not "run in prod": draft_meta ships with
        # migrations/add_life_days_draft_meta.sql. A migration nobody ran
        # costs the day's learning record — never the card.
        card.pop("draft_meta")
        row = store.upsert_day(user_id, target.isoformat(), card)
    return row


def build_evening_pass(day_row: dict) -> dict:
    """The evening recap, from the morning card's own row.

    Deterministic and model-free. The evening review asks "did you do it?",
    and that only works if it can say WHAT — by 23:00 the morning's one thing
    has usually stopped being obvious, which is the entire reason this pass
    exists rather than the view just re-reading the card.

    It recaps; it never judges. No completion count, no streak, no score —
    the ticks are the founder's to make, and a pass that pre-filled them
    would be answering its own question."""
    focus = day_row.get("focus_blocks")
    return {
        "one_thing": day_row.get("one_thing") or "",
        "one_thing_bet": day_row.get("one_thing_bet") or "",
        "focus_blocks": focus if isinstance(focus, list) else [],
        "habits": sorted((day_row.get("morning_checks") or {}).keys()),
        "distraction_flagged": day_row.get("distraction_flagged"),
    }


def evening_pass_due(now: Optional[datetime] = None) -> bool:
    """Whether the evening pass may generate yet.

    The API path asks this before generating, so a card opened at 09:00 does
    not stamp ``evening_generated_at`` and open the evening section twelve
    hours early — the FE branches on that stamp, so an early stamp is a wrong
    screen, not a cosmetic issue."""
    hour = int(getattr(config, "LIFE_PANEL_EVENING_HOUR_UTC", 21) or 21)
    return (now or datetime.now(timezone.utc)).hour >= max(0, min(23, hour))


def ensure_evening_pass(user_id: str, day: Optional[date] = None, *,
                        now: Optional[datetime] = None,
                        force: bool = False) -> Optional[dict]:
    """Generate the evening recap once, then WAIT.

    Same contract as the morning card and the same L-4 line: generation is
    scheduled, delivery is not. Nothing is sent at 23:00; the recap sits in
    the row until the panel is opened, or it is never seen, and that is
    allowed.

    ``force=True`` is the cron's entry point — it has already decided it is
    23:00 and should not re-derive that from a UTC clock. Idempotent: a second
    run on the same day is a no-op, so a cron that fires twice cannot
    overwrite an evening the founder has already started answering."""
    target = day or datetime.now(timezone.utc).date()
    row = store.get_day(user_id, target.isoformat())
    if not row:
        # No morning card means nothing to recap. Not an error — it is a day
        # the founder never opened, which L-4 says is living, not failing.
        return None
    if row.get("evening_generated_at"):
        return row
    if not (force or evening_pass_due(now)):
        return row
    return store.update_day(user_id, str(row.get("id")), {
        "evening_summary": build_evening_pass(row),
        "evening_generated_at": (now or datetime.now(timezone.utc)).isoformat(),
    }) or row


def edit_daily_card(user_id: str, text: str) -> dict:
    """``#edit <text>`` — retarget today's ONE THING, and capture the why.

    Two rules from BE-8, both enforced here:

      * The target is PINNED to the most recent daily-card row. Any other
        target is refused rather than guessed — "edit the bubble above" is
        ambiguous the moment a second bubble exists.
      * The FRAME is fixed and the CONTENT is editable. You cannot edit away
        the fact that there IS a one thing for the day; you can edit what it
        is, and say why.

    The "why" is the payload: it is captured as a candidate strategy
    correction so tomorrow's card is already right. If it also bears on a
    longer horizon that becomes a normal BE-6 proposal — warrant displayed,
    approve button, inside the daily budget. A `#edit` never silently reaches
    the 5- or 10-year document."""
    row = store.latest_day(user_id)
    if not row:
        return {"ok": False, "reason": "no_card",
                "message": "There is no daily card to edit yet."}

    body = (text or "").strip()
    if not body:
        return {"ok": False, "reason": "empty",
                "message": "Say what today's one thing should be."}

    # "<the new one thing> — <why>" or just the new one thing.
    one_thing, _, why = body.partition("—")
    if not why:
        one_thing, _, why = body.partition(" because ")
    one_thing = one_thing.strip() or body
    why = why.strip()

    updated = store.update_day(user_id, str(row.get("id")), {
        "one_thing": one_thing,
        "edit_why": why or None,
    })

    correction = None
    if why:
        # The why goes through the SAME gate as any other observation: warrant
        # required, immutable core refused, inside the one-per-day budget.
        correction = compare_to_strategy(user_id, f"{one_thing}. {why}")

    return {"ok": bool(updated), "day": updated or row,
            "correction": correction}
