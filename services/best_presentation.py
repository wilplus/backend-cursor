"""Best-Presentation composition (willab Prompt D §4) — REPLACES the audit.

After the explore arc's 3 (optional 4th) takes, this assembles the user's
strongest version of the talk: for EACH slide, their best-rated delivery of
that slide across takes, lightly stitched into continuous "ideal presentation"
text.

Pieces:
  • select_best_per_slide — PURE: rank with the combined power_score, keep the
    best per slide.
  • compose_presentation — ONE constrained LLM pass that MOSTLY keeps the user's
    words and changes only a few per slide for continuity + slide-accuracy; on
    any failure it falls back to the snippet VERBATIM (the §9-safe degradation).
  • build_best_presentation — orchestration: pulls the arc's takes, resolves the
    confidence lane per snippet, builds candidates, selects, composes, returns
    the payload.

RANKING RUNS ON CONFIDENCE, NOT CHARISMA (founder 2026-08-13, SPEC §7.2). The
retired blend carried a ``direction`` term over challenge/threat and gave its
top automatic bonus to a single coach ``challenge`` mark. Both are gone:
confidence enters exactly once — blind panel aggregate when one exists, the
speaker-relative machine composite otherwise (SPEC D8, never summed). The 2.5
breakthrough bonus is DELETED outright (founder verdict, same evening): it was
a ghost of the retired charisma system, and the Voice Album it was briefly
re-pointed at is an ENTRY decision (acoustic moment → user agrees → coach
agrees), never a ranking term. The coach's strong / to_work_on tag keeps its
dominant weight: that is an expert assessment of the phrase, not a percept.

FENCES (§0/§7): the composed text is grounded — no invented content, empty
slide stays blank; scores are internal (AC-9), never serialized.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

TAKES_TARGET = 3


def _moment_note(snippet: Any) -> str:
    """Score-free, plain-language delivery qualities (the breakthrough "why").
    Reuses the coach drafter's metric→words conversion; "" when nothing
    computable. AC-9 — never a number."""
    try:
        from services.coach_comment_drafter import metric_observations
        obs = metric_observations(
            snippet.get("metrics") if isinstance(snippet, dict) else None
        )
    except Exception:
        obs = {}
    parts = [obs[k] for k in ("pace", "pitch", "pauses", "volume", "clarity")
             if obs.get(k)]
    if not parts:
        return ""
    phrase = ", ".join(parts)
    return phrase[0].upper() + phrase[1:] + "."


# ── Selection (pure) ────────────────────────────────────────────────────
_SENTENCE_END = (".", "!", "?", "…", '."', '!"', '?"')


def _norm_text(t: Any) -> str:
    """Lowercased, whitespace-collapsed — the cross-slide dedupe key."""
    return " ".join(str(t or "").lower().split())


def _is_complete_sentence(text: Any) -> bool:
    """Heuristic for a self-contained line — ends with terminal punctuation and
    isn't a tiny stub. Used to PREFER a complete line over a truncated one (#4),
    never to discard (a slide still falls back to its best if none are complete).
    """
    t = str(text or "").strip()
    if len(t.split()) < 4:
        return False
    return t.endswith(_SENTENCE_END)


def select_best_per_slide(candidates: Any) -> dict:
    """candidates = list of per-snippet dicts: {slide_index, snippet_id,
    transcript, audio_ref, take_index, panel_confidence, machine_confidence,
    activation, slide_stickiness, tag}. Returns
    ``{slide_index: winning_candidate}`` — the best line per slide.

    NOT a confidence-only filter (founder, 2026-06-17, and unchanged by the
    2026-08-13 re-point): every moment is eligible, so a slide always shows its
    best line (never blank). Confidence is a RATING adjustment inside
    power_score — an assured delivery lifts, an unsure one sinks. (The
    short-lived album-quorum bonus was deleted the day it shipped — founder
    verdict: the album is an entry decision, never a ranking term.)

    #4 (2026-06-21) — read as coherent prose:
      • PREFER a COMPLETE sentence over a higher-scored truncated fragment
        (ranked complete-first, then by score); if a slide has no complete
        line, it still keeps its best-scored one (never blank).
      • DEDUPE across slides — the same line never lands on two slides. Slides
        (in index order) take their top-ranked line whose text isn't already
        used; if every alternative is taken, keep the best (a repeat beats a
        blank). The compose pass stays light (mostly verbatim, founder)."""
    from services.power_phrase_ranking import power_score

    by_slide: dict = {}
    for c in candidates if isinstance(candidates, list) else []:
        if not isinstance(c, dict):
            continue
        si = c.get("slide_index")
        if not isinstance(si, int) or si < 0:
            continue
        score = power_score(
            activation=c.get("activation"),
            slide_stickiness=c.get("slide_stickiness"),
            tag=c.get("tag"),
            panel_confidence=c.get("panel_confidence"),
            machine_confidence=c.get("machine_confidence"),
        )
        by_slide.setdefault(si, []).append({**c, "_score": score})

    # Rank each slide's candidates: complete sentence first, then by score.
    for si in by_slide:
        by_slide[si].sort(
            key=lambda c: (_is_complete_sentence(c.get("transcript")), c["_score"]),
            reverse=True,
        )

    # Assign in slide order, deduping by normalized text across slides.
    best: dict = {}
    used: set = set()
    for si in sorted(by_slide):
        ranked = by_slide[si]
        chosen = next(
            (c for c in ranked if _norm_text(c.get("transcript")) not in used),
            ranked[0],  # all alternatives taken → keep best (never blank)
        )
        used.add(_norm_text(chosen.get("transcript")))
        best[si] = chosen
    return best


# ── Composition (LLM, light edits, verbatim fallback) ───────────────────
def _render_composition(picks_text: list, slides: list) -> Optional[dict]:
    """ONE constrained LLM pass. ``picks_text`` = [{slide_index, transcript}]
    (challenge picks, in slide order). Returns ``{slide_index: edited_text}`` or
    None on any failure (caller falls back to verbatim)."""
    if not picks_text:
        return {}
    try:
        import json as _json

        from services.llm import chat_complete
        from services.llm_config import SPEC_BEST_PRESENTATION
        # Prompt text lives in the registry (services/prompts/) — moved
        # verbatim 2026-08-03; hash-locked in prompts.lock.json.
        from services.prompts import best_presentation as _prompts
    except Exception as e:  # pragma: no cover - import guard
        from services.f1_observability import observe_f1_degrade
        observe_f1_degrade("polish_import_failed", exc=e)
        return None

    system = _prompts.system()
    payload = {
        "slides": [
            {
                "slide_index": p["slide_index"],
                "slide_title": (slides[p["slide_index"]].get("title")
                                if 0 <= p["slide_index"] < len(slides)
                                and isinstance(slides[p["slide_index"]], dict)
                                else ""),
                "slide_body": (slides[p["slide_index"]].get("body")
                               if 0 <= p["slide_index"] < len(slides)
                               and isinstance(slides[p["slide_index"]], dict)
                               else ""),
                "spoken_line": p["transcript"],
            }
            for p in picks_text
        ]
    }
    schema = {
        "name": "best_presentation",
        "schema": {
            "type": "object", "additionalProperties": False,
            "required": ["slides"],
            "properties": {"slides": {"type": "array", "items": {
                "type": "object", "additionalProperties": False,
                "required": ["slide_index", "text"],
                "properties": {
                    "slide_index": {"type": "integer"},
                    "text": {"type": "string", "maxLength": 1200},
                },
            }}},
        },
        "strict": True,
    }
    try:
        result = chat_complete(
            spec=SPEC_BEST_PRESENTATION, system=system,
            user=_json.dumps(payload, ensure_ascii=False),
            surface="best_presentation",
            response_format_override={"type": "json_schema", "json_schema": schema},
        )
    except Exception as e:
        from services.f1_observability import observe_f1_degrade
        observe_f1_degrade("polish_compose_failed", exc=e,
                           slides=len(picks_text))
        return None
    if not result:
        from services.f1_observability import observe_f1_degrade
        observe_f1_degrade("polish_empty_result", slides=len(picks_text))
        return None
    parsed = result.parsed
    if not isinstance(parsed, dict):
        try:
            parsed = _json.loads((result.text or "").strip())
        except Exception as e:
            from services.f1_observability import observe_f1_degrade
            observe_f1_degrade("polish_parse_failed", exc=e,
                               slides=len(picks_text))
            return None
    out = {}
    for row in (parsed.get("slides") if isinstance(parsed, dict) else []) or []:
        if isinstance(row, dict) and isinstance(row.get("slide_index"), int):
            t = str(row.get("text") or "").strip()
            if t:
                out[row["slide_index"]] = t
    return out


_DECKLESS_MAX_SECTIONS = 5


def select_best_deckless(candidates: Any, max_sections: int = _DECKLESS_MAX_SECTIONS) -> dict:
    """Deckless analogue of select_best_per_slide: rank ALL the arc's moments
    with the SAME blended power_score (complete sentences preferred), take the
    top ``max_sections`` distinct-text winners, and order them by where they
    sit in the talk (start_offset_ms — every take covers the same talk, so
    offset is the speech-order proxy). Returns {section_index: candidate},
    section_index 0..K-1. Pure; {} on no usable candidates."""
    from services.power_phrase_ranking import power_score

    pool = []
    for c in candidates if isinstance(candidates, list) else []:
        if not isinstance(c, dict):
            continue
        if not (c.get("transcript") or "").strip():
            continue
        score = power_score(
            activation=c.get("activation"),
            slide_stickiness=c.get("slide_stickiness"),
            tag=c.get("tag"),
            panel_confidence=c.get("panel_confidence"),
            machine_confidence=c.get("machine_confidence"),
        )
        pool.append({**c, "_score": score})
    if not pool:
        return {}
    pool.sort(
        key=lambda c: (_is_complete_sentence(c.get("transcript")), c["_score"]),
        reverse=True,
    )
    winners: list = []
    seen_text: set = set()
    for c in pool:
        norm = " ".join((c.get("transcript") or "").lower().split())
        if norm in seen_text:
            continue
        seen_text.add(norm)
        winners.append(c)
        if len(winners) >= max_sections:
            break
    # Speech order — the assembled text must read start-to-finish.
    winners.sort(key=lambda c: (c.get("start_offset_ms") or 0))
    return {i: c for i, c in enumerate(winners)}


_MAX_KEY_PHRASES = 5
_MAX_KEY_PHRASE_LEN = 60


def _key_phrases(pick: Any) -> list:
    """Glanceable key phrases for one slide (ideal-text view, backlog 1.7) —
    derived from the winning pick's Say-It-Stronger upgrades (the strengthened
    wordings). Deduped case-insensitively, capped, over-long entries skipped.
    Display hints only — never fed back into any composed text (L1). Pure."""
    sis = pick.get("say_it_stronger") if isinstance(pick, dict) else None
    if not isinstance(sis, dict):
        return []
    out: list = []
    seen: set = set()
    for u in (sis.get("upgrades") or []):
        if not isinstance(u, dict):
            continue
        phrase = (u.get("upgrade") or "").strip()
        if not phrase or len(phrase) > _MAX_KEY_PHRASE_LEN:
            continue
        k = phrase.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(phrase)
        if len(out) >= _MAX_KEY_PHRASES:
            break
    return out


def compose_presentation(picks: dict, slides: list) -> list:
    """``picks`` = {slide_index: winning_candidate}. Returns the per-slide
    payload list (slide order), each
    {index, title, text, audio_ref, start_offset_ms, duration_ms, take_index,
    breakthrough, key_phrases}. The text is the
    lightly-edited line, or the snippet VERBATIM if the LLM didn't return one.
    A slide with no challenge pick is included with empty text (never invented).
    """
    slides = slides if isinstance(slides, list) else []
    n = max([len(slides)] + [si + 1 for si in picks], default=0)

    picks_text = [
        {"slide_index": si, "transcript": picks[si].get("transcript") or ""}
        for si in sorted(picks)
        if (picks[si].get("transcript") or "").strip()
    ]
    edited = _render_composition(picks_text, slides) or {}

    out = []
    for i in range(n):
        slide = slides[i] if i < len(slides) and isinstance(slides[i], dict) else {}
        pick = picks.get(i)
        if pick:
            verbatim = pick.get("transcript") or ""
            _edited_text = (edited.get(i) or "").strip()
            out.append({
                "index": i,
                "title": slide.get("title") or "",
                # slide body — the text-slide fallback when there's no deck PDF.
                "body": slide.get("body") or "",
                "text": edited.get(i) or verbatim,  # light-edit, else verbatim
                # The RAW words the speaker actually said (founder 2026-07-18):
                # the polish-as-suggestions lane serves THIS and offers the
                # edit as an approvable star, instead of silently replacing.
                "verbatim": verbatim,
                # True when the light polish changed the words (an approvable
                # diff exists). Trivial whitespace-only diffs don't count.
                "polished": bool(
                    _edited_text and _edited_text != (verbatim or "").strip()),
                # the winning moment's snippet id — the FE deep-links the
                # exported PDF's "Key moment" link to /game?snippet=<id>
                # (P8). Metadata, not deliverable text: NOT hidden pre-finalize
                # (same class as take_index / breakthrough).
                "snippet_id": pick.get("snippet_id"),
                # The take this pick came from — feedback-page deep link
                # (metadata, same class as take_index; null on filler slides).
                "session_id": pick.get("session_id"),
                "audio_ref": pick.get("audio_ref"),
                # span of THIS line inside the take audio — the FE plays
                # [start_offset_ms, start_offset_ms+duration_ms] so the spoken
                # line matches the shown text and isn't cut short (founder #1).
                "start_offset_ms": pick.get("start_offset_ms"),
                "duration_ms": pick.get("duration_ms"),
                "take_index": pick.get("take_index"),
                # "you turned your stress into charisma" badge — set when this
                # slide's best line was a threat→challenge turn. breakthrough_note
                # is the score-free "why" the user expands (plain-language
                # delivery qualities); null when not a breakthrough.
                "breakthrough": bool(pick.get("breakthrough")),
                "breakthrough_note": (
                    (pick.get("note") or None) if pick.get("breakthrough") else None
                ),
                # Glanceable phrases for the ideal-text view (backlog 1.7).
                "key_phrases": _key_phrases(pick),
            })
        else:
            out.append({
                "index": i, "title": slide.get("title") or "",
                "body": slide.get("body") or "",
                "text": "", "snippet_id": None, "session_id": None,
                "audio_ref": None,
                "start_offset_ms": None, "duration_ms": None,
                "take_index": None, "breakthrough": False,
                "breakthrough_note": None,
                "key_phrases": [],
            })
    return out


def spoken_arc_sessions(sessions: Any) -> list:
    """Only the SPOKEN takes of an arc (founder 2026-07-15 — reads are paired
    variants, coach-listening material): a read must never count toward the
    3-take readiness NOR compete as an ideal-text candidate. Rows without
    recording_kind (legacy / pre-migration) read as spoken. Pure."""
    return [
        s for s in (sessions or [])
        if isinstance(s, dict)
        and s.get("recording_kind") != "read"
        and not s.get("paired_session_id")
    ]


# ── Progress ────────────────────────────────────────────────────────────
def presentation_progress(takes_done: int) -> dict:
    td = takes_done if isinstance(takes_done, int) and takes_done >= 0 else 0
    return {
        "takes_done": td,
        "takes_target": TAKES_TARGET,
        # "we need N more takes to generate your best lines" (FE copy).
        "takes_remaining": max(0, TAKES_TARGET - td),
        "ready": td >= TAKES_TARGET,
    }


# ── Orchestration (DB + shadow model) ───────────────────────────────────
def _resolve_take_directions(snippets: list, coach_labels: dict) -> list:
    """Attach directions to each snippet:
      • ``direction``        — resolved (coach blind label → shadow). Feeds the
        RANKING (challenge/threat term).
      • ``coach_direction``  — COACH label ONLY (no shadow). Gates the
        BREAKTHROUGH badge: a breakthrough must be coach-CONFIRMED (founder —
        the model's guess never surfaces a badge to the user)."""
    from services.challenge_threat import resolve_direction
    try:
        from services.learning_serve import predict_direction
    except Exception:
        predict_direction = None  # type: ignore
    # Graduated-autonomy floor (readiness rig #3, default-OFF): when set, a
    # low-confidence shadow guess is NOT used for the ranking direction term —
    # the snippet routes to the human (no machine term) instead. Read once.
    _min_conf = None
    try:
        from config import Config
        _mc = Config().DIRECTION_SHADOW_MIN_CONFIDENCE
        _min_conf = float(_mc) if _mc and float(_mc) > 0 else None
    except Exception:
        _min_conf = None
    out = []
    for s in snippets or []:
        if not isinstance(s, dict):
            continue
        coach = coach_labels.get(str(s.get("id")))
        shadow = None
        shadow_conf = None
        if predict_direction and isinstance(s.get("metrics"), dict):
            try:
                pred = predict_direction(s.get("metrics"))
                shadow = (pred or {}).get("label")
                shadow_conf = (pred or {}).get("confidence")
            except Exception:
                shadow = None
                shadow_conf = None
        out.append({
            **s,
            "direction": resolve_direction(
                coach, shadow,
                shadow_confidence=shadow_conf, min_confidence=_min_conf,
            ),
            "coach_direction": resolve_direction(coach, None),  # coach-only
        })
    return out


def _batch_arc_reads(db, sessions):
    """ONE snippets query + ONE labels query for ALL of an arc's takes — kills
    the per-take N+1 in build_best_presentation / build_arc_breakthroughs (a
    28-take arc was ~56 round-trips). Returns ``(snips_by_sid|None,
    labels_by_sid|None)``; None when the db lacks the batch method (injected
    fake dbs in tests) → callers fall back to per-session reads. select *
    (include_words) preserves exact column behavior vs the per-session read."""
    sess_ids = [s.get("id") for s in (sessions or [])
                if isinstance(s, dict) and s.get("id")]
    snips = (db.get_snippets_by_sessions(sess_ids, include_words=True)
             if sess_ids and hasattr(db, "get_snippets_by_sessions") else None)
    labels = (db.get_training_labels_by_sessions(sess_ids)
              if sess_ids and hasattr(db, "get_training_labels_by_sessions")
              else None)
    return snips, labels


def _arc_snippets(db, snips_batch, sid):
    """A take's snippets from the batched read, else a per-session fallback."""
    if snips_batch is not None:
        return snips_batch.get(str(sid), [])
    return db.get_snippets_by_session(sid) if sid else []


def _arc_labels(db, labels_batch, sid):
    """A take's training labels from the batched read, else a per-session
    fallback."""
    if labels_batch is not None:
        return labels_batch.get(str(sid), [])
    return db.get_training_labels(sid) or []


def _panel_by_snippet(db, snippet_ids: list) -> dict:
    """``{snippet_id: {"panel": aggregate|None, "quorum": bool}}`` for the arc.

    The blind ternary panel (SPEC §3.2) is the human half of the confidence
    term the 2026-08-13 re-point put into power_score. ONE batched query for
    the whole arc — the same N+1 lesson `_batch_arc_reads` exists for.
    (It briefly also computed an album-quorum flag for the `_W_B` bonus;
    both were deleted the same day by founder verdict.)

    Best-effort by design: {} when the db predates the reader (injected fakes
    in tests) or the query fails. An arc with no panel rows then ranks on the
    machine composite alone, which is exactly the pre-panel behaviour and the
    only safe direction for a read path in the live loop.
    """
    ids = [str(s) for s in (snippet_ids or []) if s]
    if not ids or not hasattr(db, "get_confidence_labels_by_snippet_ids"):
        return {}
    try:
        rows_by_snippet = db.get_confidence_labels_by_snippet_ids(ids) or {}
    except Exception as e:
        logger.warning("best_presentation: panel read failed: %s", e)
        return {}
    try:
        from services.state_ratings import aggregate
    except Exception:
        return {}
    out: dict = {}
    for snippet_id, rows in rows_by_snippet.items():
        if not isinstance(rows, list):
            continue
        out[str(snippet_id)] = {"panel": aggregate(rows)}
    return out


# Bump when the cached compose PAYLOAD shape changes (a new per-slide field
# must force one recompute per arc — the content signature alone can't see
# shape changes). v2: + key_phrases (backlog 1.7, 2026-07-11).
_BP_PAYLOAD_VERSION = "v9"  # v9: the coach tag now enters assembly ranking
                            # (publish-gated) — a published arc with tags and
                            # a warm v8 cache would keep serving untagged
                            # picks with no row moving, so only a bump forces
                            # the recompute.
                            # (v8: power_score re-pointed onto confidence and
                            # _W_B deleted (2026-08-13) — the RANKING SEMANTICS
                            # changed while no session row moved, so every
                            # warm cache was still serving picks ranked by the
                            # retired charisma blend. Only a payload bump can
                            # force the recompute (the audit's finding #3).
                            # (v7: the voice-confidence WEIGHTING changed (sex
                            # routing) and history was backfilled — the stamped
                            # scores under a warm cache are not the ones that
                            # produced its picks, and no session row moved, so
                            # only a payload bump forces the recompute
                            # (v6: voice_confidence entered the rank blend;
                            # v5: verbatim+polished; v4: picks carry
                            # session_id, delivery layer)


def _voice_confidence_term(metrics: Any) -> Optional[float]:
    """The delivery term for one snippet's metrics blob, or None. Isolated so a
    missing/failed import can never break assembly — the ranking simply falls
    back to its pre-delivery behaviour."""
    try:
        from services.voice_confidence import rank_term
        return rank_term(metrics)
    except Exception:
        return None


def _bp_signature(sessions: list, corrections: Optional[dict] = None) -> str:
    """Content signature for the best-presentation cache (Part B). Changes
    EXACTLY when a recompose is needed: a take added/removed, a coach publish
    (which re-ranks + confirms breakthroughs), a payload-shape version bump, or
    a flip of the voice-confidence ranking flag. User pencil-edits are applied
    on READ, so they're intentionally NOT part of the signature. Cheap —
    computed from the session list the route already loaded, no extra reads.

    The FLAG is in the signature because flipping it re-ranks every arc without
    touching any session row; without it a warm cache would keep serving picks
    made under the old blend and the flip would look like a no-op.

    The composite's VERSION is in for the same reason, one level down: a
    weighting change (v1 sex-blind → v2 sex-routed) alters which take wins
    without adding a take or a publish. Deploying the bump alone would leave
    warm arcs serving picks from the retired weighting until something
    unrelated invalidated them, so the change would land arc-by-arc at random
    times — the worst of both. Folding it in makes every future weighting
    change self-invalidating."""
    import hashlib
    import json as _json
    try:
        from services.voice_confidence import ranking_enabled, _VERSION as _vc_v
        flag = ("vc1" if ranking_enabled() else "vc0") + "|" + str(_vc_v)
    except Exception:
        flag = "vc0"
    key = sorted(
        (
            [str(s.get("id")), s.get("take_index"),
             str(s.get("results_published_at") or "")]
            for s in (sessions or []) if isinstance(s, dict)
        ),
        key=lambda r: r[0],
    )
    corr_key = sorted(
        (str(k), hashlib.sha1(str(v).encode("utf-8")).hexdigest())
        for k, v in (corrections or {}).items()
    )
    return hashlib.sha1(
        (_BP_PAYLOAD_VERSION + "|" + flag + "|" + _json.dumps(
            key, sort_keys=True, default=str)
         + "|" + _json.dumps(corr_key)).encode("utf-8")
    ).hexdigest()


def build_best_presentation(
    arc_id: Optional[str], *, database=None, coach_view: bool = False,
) -> dict:
    """Assemble the best-presentation payload for an arc. Best-effort; returns
    a progress-only payload (ready=False) when there's nothing to compose.

    Part B — the composed slides (the ~2-4s LLM pass) are CACHED keyed by arc +
    content signature; an unchanged arc returns the cached compose (no LLM, no
    snippet reads). Edits + coach_reviewed/coach_finalized are applied fresh on
    every read.

    ``coach_view`` (founder 2026-07-06 — coach-owned ideal-text correction):
      • False (default, the STUDENT-facing read): the raw auto-assembled draft
        is NEVER served. Slide text is emptied unless ``coach_finalized`` (every
        slide has a coach correction) — see ``_finalize_best_presentation``.
        User pencil-edits still layer on top once finalized.
      • True (the COACH's own editing surface): always the CURRENT text (auto,
        or the coach's own edit where saved) regardless of finalized state —
        the coach needs to see their own progress. User pencil-edits are NOT
        applied here (irrelevant to the coach's correction pass).
    """
    from services.slide_alignment import slide_index_for_offset
    db = database if database is not None else _default_db()

    # SPOKEN takes only (founder 2026-07-15): reads must neither count toward
    # readiness nor feed the candidate pool — one filter at the load point so
    # progress, corrections, the cache signature, candidates, and finalize all
    # inherit it.
    sessions = spoken_arc_sessions(db.get_arc_sessions(arc_id)) if arc_id else []
    progress = presentation_progress(len(sessions))

    # Coach transcript corrections (Engine 2, founder 2026-07-11): the
    # assembler's verbatim source is the COACH-corrected transcript of a
    # moment when one exists (raw Whisper otherwise) — "assembled from the
    # corrected takes". Read BEFORE the cache check so corrections are part
    # of the content signature (a new correction invalidates the compose).
    # Batch-cap keeps arcs ≤3-4 takes, so a per-session read is cheap.
    corrections: dict = {}
    _get_drafts = getattr(db, "get_coach_snippet_drafts", None)
    if callable(_get_drafts):
        for _sess in sessions:
            try:
                for _d in (_get_drafts(_sess.get("id")) or []):
                    _tc = _d.get("transcript_corrected")
                    if isinstance(_tc, str) and _tc.strip() \
                            and _d.get("snippet_id") is not None:
                        corrections[str(_d["snippet_id"])] = _tc.strip()
            except Exception:
                continue

    # ── Compose cache (Part B). Hit → reuse the composed slides + deck ref,
    # skipping the snippet reads + LLM. getattr guards keep injected fake dbs
    # (tests) working without the cache methods.
    signature = _bp_signature(sessions, corrections)
    _get_cache = getattr(db, "get_best_presentation_cache", None)
    _put_cache = getattr(db, "upsert_best_presentation_cache", None)
    cached = _get_cache(arc_id) if (arc_id and callable(_get_cache)) else None
    if (isinstance(cached, dict) and cached.get("signature") == signature
            and isinstance(cached.get("payload"), dict)):
        slides_payload = cached["payload"].get("slides") or []
        canonical_presentation_ref = cached["payload"].get("presentation_ref")
        return _finalize_best_presentation(
            db, arc_id, sessions, progress, slides_payload,
            canonical_presentation_ref, coach_view=coach_view,
        )

    # Batch the per-take reads — ONE snippets query + ONE labels query for the
    # whole arc instead of 2 per take (a 28-take arc was ~56 round-trips on
    # every cold assembly). select * (include_words) preserves exact column
    # behavior; getattr guards keep injected fake dbs (tests) on the per-session
    # fallback below.
    _snips_batch, _labels_batch = _batch_arc_reads(db, sessions)
    # Resolve every take's snippets ONCE, up front, so the arc's snippet ids
    # are known before the candidate loop — the panel read is per-snippet and
    # batching it is the same N+1 lesson as the two reads above. On the
    # fake-db fallback this is still exactly one read per session, not two.
    _snips_by_sid = {
        str(s.get("id")): _arc_snippets(db, _snips_batch, s.get("id"))
        for s in sessions if isinstance(s, dict) and s.get("id")
    }
    _panel = _panel_by_snippet(db, [
        sn.get("id")
        for rows in _snips_by_sid.values() if isinstance(rows, list)
        for sn in rows if isinstance(sn, dict)
    ])

    candidates = []
    canonical_slides: list = []
    canonical_presentation_ref = None
    for sess in sessions:
        sid = sess.get("id")
        ctx = sess.get("intake_context") if isinstance(sess.get("intake_context"), dict) else {}
        slides = ctx.get("slides") or []
        advances = ctx.get("slide_advances")
        if slides and len(slides) >= len(canonical_slides):
            canonical_slides = slides  # most-complete deck wins
        # Deck PDF = the FIRST NON-NULL across takes — NEVER clobbered to None
        # by a re-take that dropped presentation_ref (so the FE renders pages).
        if canonical_presentation_ref is None and ctx.get("presentation_ref"):
            canonical_presentation_ref = ctx.get("presentation_ref")
        take_index = sess.get("take_index")
        snippets = _snips_by_sid.get(str(sid), [])
        coach_labels = {
            str(r.get("snippet_id")): r.get("value")
            for r in _arc_labels(db, _labels_batch, sid)
        }
        # OPTION D (founder 2026-08-13): the coach's strong/to_work_on tag
        # finally reaches the F1 assembly ranking. `_W_C` (2.0) is the blend's
        # DOMINANT term and had never fired on this path — "tag": None was
        # hardcoded below since the beginning, so the human verdict ordered
        # /strengths but not the ideal text. Safe to wire now BECAUSE `_W_B`
        # is deleted: the audit showed the old bonus + a panel read could
        # cross the 4.0 coach gap, and wiring the tag was exactly the change
        # that would have armed it.
        #
        # PUBLISH-GATED, deliberately. Tags live in coach_snippet_drafts from
        # the moment the coach types; ranking on a draft would leak work-in-
        # progress into the student's document before the coach said "done" —
        # and `_bp_signature` only changes on publish, so a pre-publish tag
        # would also be invisible to the cache. Gate and signature move
        # together or not at all.
        coach_tags: dict = {}
        if sess.get("results_published_at"):
            try:
                coach_tags = {
                    str(d.get("snippet_id")): d.get("tag")
                    for d in (db.get_coach_snippet_drafts(sid) or [])
                    if d.get("snippet_id") and d.get("tag")
                }
            except Exception as _tag_err:
                logger.warning(
                    "best_presentation: coach tag read failed sid=%s: %s",
                    sid, _tag_err)
        directed = _resolve_take_directions(snippets, coach_labels)
        from services.challenge_threat import detect_breakthroughs
        # COACH-CONFIRMED breakthroughs only (gate on coach_direction, not the
        # shadow-resolved direction) — the badge never surfaces a model guess.
        breakthroughs = detect_breakthroughs([
            {"id": s.get("id"), "start_offset_ms": s.get("start_offset_ms"),
             "direction": s.get("coach_direction")}
            for s in directed
        ])
        for s in directed:
            metrics = s.get("metrics") if isinstance(s.get("metrics"), dict) else {}
            stick = metrics.get("slide_stickiness")
            if isinstance(stick, dict):
                stick = stick.get("composite")
            candidates.append({
                "slide_index": slide_index_for_offset(s.get("start_offset_ms"), advances),
                "snippet_id": s.get("id"),
                # The take this pick came from — the feedback-page deep link
                # (ideal-text key-moment anchors) + the FE's snippet lookup.
                # Metadata, same class as take_index.
                "session_id": sid,
                # Ideal-text key phrases (backlog 1.7): the winning pick's
                # Say-It-Stronger upgrades become the slide's glanceable
                # phrases (derived in compose_presentation). Display hints
                # only — never touches the composed text (L1).
                "say_it_stronger": s.get("say_it_stronger"),
                # Engine 2: the coach-corrected transcript IS the verbatim
                # (L1 — the coach's verbatim, never an AI rewrite).
                "transcript": (
                    corrections.get(str(s.get("id")))
                    or s.get("transcript") or s.get("transcript_excerpt") or ""
                ),
                "audio_ref": s.get("audio_ref") or s.get("storage_path"),
                # The snippet's span inside the (concatenated) take audio, so the
                # FE can clamp playback to THIS line instead of playing the whole
                # file from 0 and cutting off mid-way (founder #1).
                "start_offset_ms": s.get("start_offset_ms"),
                "duration_ms": s.get("duration_ms"),
                "take_index": take_index,
                # BADGE ONLY, and no longer a ranking input (SPEC §7.2). This
                # is the coach's own challenge mark behind the breakthrough
                # badge. The 2.5 ranking bonus it used to carry is DELETED
                # (founder verdict, 2026-08-13 evening — a ghost of the
                # retired charisma system; the Voice Album is an entry
                # decision, never a ranking term). Kept on the payload so the
                # badge surfaces are unchanged.
                "breakthrough": s.get("id") in breakthroughs,
                "activation": metrics.get("overall_score"),
                "slide_stickiness": stick,
                # CONFIDENCE — enters power_score exactly once (SPEC D8). The
                # panel blob wins when the blind raters have seen this clip;
                # the machine composite covers the unlabelled majority and is
                # None whenever the ranking flag is off or the piece predates
                # the composite → power_score no-op.
                "panel_confidence": _panel.get(str(s.get("id")), {}).get("panel"),
                "machine_confidence": _voice_confidence_term(metrics),
                # power_score's _COACH_TERM maps only strong/to_work_on;
                # any other draft tag value harmlessly scores 0.
                "tag": coach_tags.get(str(s.get("id"))),
                # score-free plain-language delivery qualities — the "why" the
                # user expands on a breakthrough badge (reuses the cross-take
                # rationale; AC-9 — no numbers).
                "note": _moment_note(s),
            })

    if canonical_slides:
        picks = select_best_per_slide(candidates)
    else:
        # DECKLESS assembly (Engine 2, founder 2026-07-11): no slides to
        # bucket by, so the ideal text = the user's best moments across the
        # batch's takes, in speech order, as numbered SECTIONS under the
        # FE's single mock slide. Same coach editor + coach_finalized gate
        # (edits key by section index exactly like slide index).
        picks = select_best_deckless(candidates)
    slides_payload = compose_presentation(picks, canonical_slides)

    # Cache the composed (pre-edit) result keyed by the content signature so the
    # next open with an unchanged arc skips the LLM. Best-effort.
    if callable(_put_cache) and arc_id:
        _put_cache(arc_id, signature, {
            "slides": slides_payload,
            "presentation_ref": canonical_presentation_ref,
        })

    return _finalize_best_presentation(
        db, arc_id, sessions, progress, slides_payload,
        canonical_presentation_ref, coach_view=coach_view,
    )


def _finalize_best_presentation(
    db, arc_id, sessions, progress, slides_payload, canonical_presentation_ref,
    coach_view: bool = False,
) -> dict:
    """Apply coach + user edits, coach_finalized, and assemble the payload.
    Runs on BOTH the cache-hit and fresh-compose paths — edits + review state
    must be fresh, so they are never part of the cached compose."""
    # COACH corrections (founder 2026-07-06 — the real "corrected ideal text").
    # Applied to EVERY view (coach + student) since this IS the corrected
    # content; only the STUDENT view additionally hides it until finalized
    # (below). `coach_edited` tells the FE this slide has been through the
    # coach's own pass (vs still the machine's auto-pick).
    coach_edits = db.get_coach_best_presentation_edits(arc_id) or {}
    # Coach-corrected key phrases (Engine 2, 2026-07-11): override the
    # auto-derived set per slide once the coach saves theirs. getattr guard
    # keeps injected fake dbs (tests) working.
    _get_kp = getattr(db, "get_coach_best_presentation_key_phrases", None)
    coach_kp = (_get_kp(arc_id) or {}) if callable(_get_kp) else {}
    for s in slides_payload:
        cov = coach_edits.get(s.get("index"))
        if isinstance(cov, str) and cov.strip():
            s["text"] = cov
            s["coach_edited"] = True
        else:
            s["coach_edited"] = False
        kp = coach_kp.get(s.get("index"))
        if isinstance(kp, list) and kp:
            s["key_phrases"] = kp

    # coach_finalized: has the coach corrected EVERY slide? This — NOT payment
    # — is what decides whether the student sees ANY text at all (founder: the
    # raw auto-assembled draft must NEVER reach the student; only the coach
    # sees the in-progress draft, via coach_view=True).
    coach_finalized = bool(slides_payload) and all(
        isinstance(coach_edits.get(s.get("index")), str)
        and coach_edits[s.get("index")].strip()
        for s in slides_payload
    )

    if not coach_view:
        if coach_finalized:
            # Apply the user's saved per-slide edits (the pencil) — they
            # override the coach-corrected text and stick across
            # recompositions. `edited` tells the FE. Unchanged behavior.
            edits = db.get_best_presentation_edits(arc_id) or {}
            for s in slides_payload:
                ov = edits.get(s.get("index"))
                if isinstance(ov, str) and ov.strip():
                    s["text"] = ov
                    s["edited"] = True
                else:
                    s["edited"] = False
        else:
            # NOT finalized — hide ALL slide text (never the raw draft),
            # regardless of payment state. The route's payment gate runs
            # separately/first; this hides content even on a PAID arc until
            # the coach has actually finished. Key phrases hide with the
            # text: the coach-corrected set is deliverable content, and the
            # auto set describes a draft the student must not infer.
            for s in slides_payload:
                s["text"] = ""
                s["edited"] = False
                s["key_phrases"] = []

    # "Draft / pending coach" (founder 2026-06-20, retained as a SEPARATE,
    # softer signal from coach_finalized): flips True once a coach has
    # DELIVERED (published) any take in the arc — the older "is a human
    # involved at all yet" cosmetic label. coach_finalized (above) is the hard
    # gate on content; this stays for any existing FE surface reading it.
    coach_reviewed = any(
        bool(s.get("results_published_at")) for s in sessions
    )

    # Presentation NAME — the arc's topic, so the FE can title the best
    # presentation + the deep link / ready-card show a real name (founder
    # 2026-06-26). Take the latest take's topic (the convention elsewhere is
    # "topic from intake_context, latest take"), else any non-empty one.
    name = None
    _best_ti = -1
    for s in sessions:
        if not isinstance(s, dict):
            continue
        ctx = s.get("intake_context") if isinstance(s.get("intake_context"), dict) else {}
        topic = ctx.get("topic")
        ti = s.get("take_index") if isinstance(s.get("take_index"), int) else -1
        if isinstance(topic, str) and topic.strip() and ti >= _best_ti:
            name = topic.strip()
            _best_ti = ti

    return {
        "ready": progress["ready"],
        "progress": progress,
        # the presentation's title (arc topic) — null when no take carried one.
        "name": name,
        # False until a coach has published a take → FE shows "draft / pending
        # coach"; True once the human has confirmed.
        "coach_reviewed": coach_reviewed,
        # HARD gate on content (founder 2026-07-06): True once the coach has
        # corrected every slide. Until then the student sees no slide text
        # (regardless of payment) — only coach_view=True ever sees the draft.
        "coach_finalized": coach_finalized,
        # the deck PDF so the FE renders real slide pages (null → text-slide
        # fallback from each slide's title/body).
        "presentation_ref": canonical_presentation_ref,
        "slides": slides_payload,
    }


def build_arc_breakthroughs(arc_id: Optional[str], *, database=None) -> dict:
    """ALL coach-confirmed breakthrough moments in an arc, newest → oldest.

    The "explore my breakthrough moments" list (founder #5, scoped to THIS
    presentation's arc). Same gate as the best-presentation badge — a
    threat→challenge turn on the coach's OWN labels (``coach_direction``,
    never a model guess) — but returns EVERY breakthrough snippet across all
    takes (not just the per-slide winner), each with the playback data the FE
    needs. Score-free (AC-9); best-effort → empty list when there's nothing.
    """
    from services.challenge_threat import detect_breakthroughs
    from services.slide_alignment import slide_index_for_offset
    db = database if database is not None else _default_db()

    sessions = db.get_arc_sessions(arc_id) if arc_id else []
    _snips_batch, _labels_batch = _batch_arc_reads(db, sessions)
    out: list = []
    for sess in sessions:
        sid = sess.get("id")
        ctx = sess.get("intake_context") if isinstance(sess.get("intake_context"), dict) else {}
        advances = ctx.get("slide_advances")
        created_at = sess.get("created_at")
        take_index = sess.get("take_index")
        snippets = _arc_snippets(db, _snips_batch, sid)
        coach_labels = {
            str(r.get("snippet_id")): r.get("value")
            for r in _arc_labels(db, _labels_batch, sid)
        }
        directed = _resolve_take_directions(snippets, coach_labels)
        bt = detect_breakthroughs([
            {"id": s.get("id"), "start_offset_ms": s.get("start_offset_ms"),
             "direction": s.get("coach_direction")}
            for s in directed
        ])
        if not bt:
            continue
        # The coach's own words + video per breakthrough (founder 2026-07-28,
        # FE §1 close-out): the key-moment note and the breakthrough video
        # both live on the drafts lane, keyed by snippet — same source the
        # game's reveal uses. One read per session WITH breakthroughs (the
        # continue above skips it entirely for takes that have none).
        # Best-effort: no drafts → both fields null, the list still serves.
        _drafts_by_snip: dict = {}
        try:
            _get_drafts = getattr(db, "get_coach_snippet_drafts", None)
            if callable(_get_drafts):
                _drafts_by_snip = {
                    str(d.get("snippet_id")): d
                    for d in (_get_drafts(sid) or []) if d.get("snippet_id")
                }
        except Exception:
            _drafts_by_snip = {}
        for s in directed:
            if s.get("id") not in bt:
                continue
            _draft = _drafts_by_snip.get(str(s.get("id"))) or {}
            out.append({
                "snippet_id": s.get("id"),
                "session_id": sid,
                "take_index": take_index,
                "created_at": created_at,
                "slide_index": slide_index_for_offset(
                    s.get("start_offset_ms"), advances),
                "transcript": (s.get("transcript")
                               or s.get("transcript_excerpt") or ""),
                "audio_ref": s.get("audio_ref") or s.get("storage_path"),
                # span inside the take audio so the FE clamps playback (#1).
                "start_offset_ms": s.get("start_offset_ms"),
                "duration_ms": s.get("duration_ms"),
                # ── The FE's shipped mapper contract (HANDOFF-BE-2026-07-28,
                # §1) — names matter more than history here:
                #   note     the COACH's human-authored key-moment note (the
                #            drafts lane). The FE renders it as THE comment.
                #   comment  the SYSTEM's score-free delivery explanation
                #            (AC-9 — never a number), shown ONLY when the
                #            coach left no note (FE enforces the override).
                #   video_ref the coach's breakthrough video (game naming, so
                #            the FE reuses its player).
                # HISTORY NOTE: before 2026-07-28 `note` carried the MACHINE
                # text — the shipped FE reads `note` as the coach's words, so
                # serving machine prose there would misattribute machine
                # voice as the human coach. The rename is the fix, not a
                # cosmetic choice.
                "note": (_draft.get("note") or None),
                "comment": _moment_note(s),
                "video_ref": (_draft.get("breakthrough_video_ref") or None),
            })

    # Newest → oldest: latest take first, latest moment within a take first.
    out.sort(
        key=lambda b: (
            b.get("created_at") or "",
            b["take_index"] if isinstance(b.get("take_index"), int) else -1,
            b["start_offset_ms"] if isinstance(b.get("start_offset_ms"), int) else -1,
        ),
        reverse=True,
    )
    return {"breakthroughs": out, "count": len(out)}


def _default_db():
    from services.db import db as _db
    return _db
