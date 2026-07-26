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


def _complete(spec: LLMSpec, *, system: str, user: str, surface: str,
              user_id: str) -> Optional[dict]:
    """One JSON-mode call. Returns the parsed dict, or None on ANY failure.

    Every caller treats None as "no derivation this turn" and still answers —
    capture never fails and never blocks, so an OpenAI outage costs the
    proposal, not the note."""
    client = _client()
    if client is None:
        return None
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
        raw = (response.choices[0].message.content or "").strip()
    except Exception as e:
        _log_derivation(surface, user_id=user_id, outcome="call_failed",
                        err=type(e).__name__)
        return None
    if not raw:
        _log_derivation(surface, user_id=user_id, outcome="empty")
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        _log_derivation(surface, user_id=user_id, outcome="unparseable",
                        chars=len(raw))
        return None
    return parsed if isinstance(parsed, dict) else None


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
    directly at v1 rather than through the proposal queue."""
    parsed = _complete(
        SPEC_LIFE_DOCS,
        system=_DOCS_SYSTEM,
        user=json.dumps(answers or {}, ensure_ascii=False)[:20000],
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
# BE-8 — the daily card
# ═════════════════════════════════════════════════════════════════════════

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

    def _bet_rank(goal: dict) -> float:
        bet = bets.get(str(goal.get("bet_id") or ""))
        # An unattached goal sorts last. It is not a Bet-3 item — it is a goal
        # nobody has decided a bet for, and it should not outrank one that has
        # been thought about.
        return float((bet or {}).get("order_key") or 99)

    def _bet_title(goal: dict) -> str:
        bet = bets.get(str(goal.get("bet_id") or ""))
        return (bet or {}).get("title") or ""

    eligible = [
        g for g in goals
        if lp.BET_3_DRIVES_DAILY_EXECUTION or _bet_rank(g) < 3
    ]
    eligible.sort(key=lambda g: (_bet_rank(g),
                                 0 if g.get("horizon") == "now" else 1,
                                 float(g.get("order_key") or 0)))

    def _text(goal: dict) -> str:
        return goal.get("title") or goal.get("body") or ""

    one_thing = _text(eligible[0]) if eligible else ""
    focus = [{"text": _text(g), "box": False, "bet": _bet_title(g)}
             for g in eligible[1:4]]

    return {
        "morning_checks": {
            (h.get("title") or f"habit-{i}"): False
            for i, h in enumerate(habits)
        },
        "one_thing": one_thing,
        "one_thing_bet": _bet_title(eligible[0]) if eligible else "",
        "focus_blocks": focus,
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
    return store.upsert_day(user_id, target.isoformat(),
                            build_daily_card(user_id, target))


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
