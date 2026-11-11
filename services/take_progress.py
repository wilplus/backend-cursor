"""Is the speaker getting better, and did the fix work? (founder 2026-10-31,
N291 items 1 and 2; N290 item 6.)

Two measures, for the founder only (the admin profile's Takes table,
``services.admin_takes``). Neither ever reaches a speaker (Never 1) or a
coach (Never 2).

ANCHORED WILLFIDENCE (N291 item 2). The willfidence the moments are picked
by reads the voice against the speaker's recent Takes, so as they improve
the reference rises with them and their progress disappears from it. This
one reads the voice against a frozen reference: the speaker's first Takes
(``FIRST_TAKES``, at least ``voice_confidence._BASELINE_MIN_SAMPLES`` usable
clips), the same cues, weights and words as the rolling one. Until those
first Takes exist it is not measured. A reference from all speakers, for
new speakers, comes later.

DID THE FIX WORK (N291 item 1). A fix worked when the same issue does not
come back on the next Take of the same talk, on the same slide. The fixes a
Take gave are read from its stored frame by the walk's own rule
(``walk_gave``, C2, N309 item 1): the One thing walk's one fix as the frame
records it (``one_fix``: the pace game's tempo stretch, ``tempo_stretch.pick``,
or the blocks the picker marked ``weakest`` or ``between``, N289), the same
for the Takes table, Last time and what worked. On the next Take's clips of
that slide:

  voice    came back when the slide's best heard clip is still under the floor
  clearer  came back when a clip of the slide still has words that need help
  tempo    came back unless every clip stays inside the green on the side the
           stretch leaned, by the bar that picks a stretch
           (``tempo_stretch.stays_inside``, N350 item 3)

"not_measured" when there is no next Take, the slide is not in it, or its
clips cannot be read. Read on demand; nothing is stored.

THIS TAKE'S FRAME IS ALWAYS THERE FOR THE WALK (founder 2026-11-06). Last
time and the tempo step read the frame of the Take being walked through
``ideal_text_feedback_bake.walk_frame``: when the Ideal Text was computed
live and its frame is not written yet, the reader writes it, or waits for
the write under way, so the walk never reads a Take as frameless.

LAST TIME (founder 2026-10-31, N309 item 1). The One thing walk opens with
the last Take's fix played back when it rose: "Last time: {the tip}. You
did." with this Take's clip on that slide (``last_fix``). A fix rose when
its issue is gone on that slide, by the same rule as the table's: the pace
game's too (the Sniper, when the last walk fixed no moment, N347 item 3,
N350 item 3). The speaker never sees a number.

WHAT WORKED IS NOT GIVEN AGAIN (founder 2026-11-02, N359). The fixes the
walk of the Take before gave (``last_walk``: the completed spoken Take
before this one in the talk, ``previous_take``; its fixes, ``walk_fixes``)
whose issue is gone on this Take's same slide (``worked``, by ``outcome``,
the rule above) are not given again on that slide by this Take's walk
(``take_feedback_policy_v3``), nor its tempo step there (``pace_worked``).
Nothing of it reaches the speaker or a coach.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from services.ideal_text_feedback_bake import walk_frame

logger = logging.getLogger(__name__)

#: How many of the speaker's first Takes make the frozen reference.
FIRST_TAKES = 5

CAME_BACK = "came_back"
GONE = "gone"
NOT_MEASURED = "not_measured"


# ── anchored willfidence ─────────────────────────────────────────────────────

def frozen_reference(first_takes_metrics: list[list[Any]]) -> Optional[dict]:
    """The speaker's frozen voice reference from their first Takes' clip
    metrics (oldest first), or None when there are too few usable clips.
    Pure."""
    from services.voice_confidence import _BASELINE_MIN_SAMPLES, feature_stats
    metrics = [m for take in first_takes_metrics[:FIRST_TAKES] for m in take if isinstance(m, dict)]
    return feature_stats(metrics, min_samples=_BASELINE_MIN_SAMPLES)


def anchored_willfidence(pieces: list[dict], reference: Optional[dict]) -> Optional[float]:
    """The mean S x W of a Take's clips, the voice read against the frozen
    reference; None when there is no reference or no clip can be read.
    Pure."""
    if not reference:
        return None
    from services import willfidence
    from services.voice_confidence import read_for_piece
    values = []
    for piece in pieces:
        metrics = piece.get("metrics") if isinstance(piece.get("metrics"), dict) else None
        read = read_for_piece(metrics, reference) if metrics else None
        s = willfidence.stretch(read.get("score")) if read else None
        if s is None:
            continue
        text = piece.get("transcript")
        w = willfidence.partial_w(willfidence.filler(text), willfidence.hedging(text),
                                  willfidence.slide_fit([metrics]))
        values.append(s * (1.0 if w is None else w))
    return sum(values) / len(values) if values else None


# ── did the fix work ─────────────────────────────────────────────────────────

def _clips_by_slide(frame: Any, snippets: list[dict]) -> dict[Any, list[dict]]:
    by_id = {str(s.get("id")): s for s in snippets if isinstance(s, dict) and s.get("id")}
    out: dict[Any, list[dict]] = {}
    for block in (frame or {}).get("blocks") or []:
        clips = [by_id[str(c)] for c in block.get("snippet_ids") or [] if str(c) in by_id]
        out.setdefault(block.get("slide_index"), []).extend(clips)
    return out


def fixes_of(frame: Any, snippets: list[dict]) -> list[dict]:
    """The fixes a Take gave: ``[{"slide_index", "kind"}]``, kind "voice",
    "clearer" or "tempo" (with the side its stretch leaned, ``reading``), in
    slide order. Pure."""
    found = []
    for block in (frame or {}).get("blocks") or []:
        if block.get("walk_slot") in ("weakest", "between") and block.get("carries_exercise") \
                and block.get("exercise_kind") in ("voice", "clearer"):
            found.append({"slide_index": block.get("slide_index"), "kind": block["exercise_kind"]})
    stretch = _stretch(frame, snippets)
    if stretch is not None:
        found.append(stretch)
    return sorted(found, key=lambda f: (f["slide_index"] is None, f["slide_index"] or 0))


def _stretch(frame: Any, snippets: list[dict]) -> Optional[dict]:
    """The Take's tempo stretch on its slide: ``{"kind": "tempo",
    "slide_index", "reading"}``; None when no clip leaves the green, it is
    on no slide, or it cannot be read."""
    from services import tempo_stretch
    try:
        chosen = tempo_stretch.pick(snippets)
    except Exception:  # noqa: BLE001 -- no stretch read: no tempo fix
        return None
    if not chosen:
        return None
    clip = str(snippets[chosen["index"]].get("id"))
    for slide, clips in _clips_by_slide(frame, snippets).items():
        if any(str(c.get("id")) == clip for c in clips):
            return {"kind": "tempo", "slide_index": slide, "reading": chosen["reading"]}
    return None


def _issue(fix: dict, clips: list[dict], snippets: list[dict]) -> Optional[bool]:
    """Whether the fix's issue is on the slide's clips; None when
    unreadable."""
    from services import moment_pick, noticing_settings, tempo_stretch
    from services.voice_confidence import stamped_score
    kind = fix["kind"]
    if kind == "tempo":
        inside = tempo_stretch.stays_inside(snippets, {str(c.get("id")) for c in clips},
                                            fix["reading"])
        return None if inside is None else not inside
    reads = [moment_pick.read(stamped_score(c.get("metrics")), c.get("transcript"), c.get("metrics"))
             for c in clips]
    if kind == "voice":
        heard = [r["s"] for r, c in zip(reads, clips)
                 if r["sound"] and len(str(c.get("transcript") or "").split()) >= moment_pick.MIN_WORDS]
        return max(heard) < noticing_settings.value("moment_pick.FLOOR") if heard else None
    if kind == "clearer":
        return any(r["words_help"] for r in reads) if reads else None
    return None


def outcome(fix: dict, next_frame: Any, next_snippets: list[dict]) -> str:
    """Whether one fix's issue came back on the next Take, same slide. Pure."""
    if not isinstance(next_frame, dict):
        return NOT_MEASURED
    clips = _clips_by_slide(next_frame, next_snippets).get(fix.get("slide_index"))
    if not clips:
        return NOT_MEASURED
    found = _issue(fix, clips, next_snippets)
    if found is None:
        return NOT_MEASURED
    return CAME_BACK if found else GONE


def fix_outcomes(database: Any, take_id: Any, next_take_id: Optional[Any]) -> list[dict]:
    """The fixes a Take gave and whether each came back on the next Take of
    the talk: ``[{"slide_index", "kind", "outcome"}]``. Never raises."""
    try:
        frame = database.get_v4_dark_frame(str(take_id))
        if not isinstance(frame, dict):
            return []
        fixes = walk_gave(database, take_id, frame,
                          database.get_snippets_by_session(str(take_id)) or [])
        if not fixes:
            return []
        next_frame = database.get_v4_dark_frame(str(next_take_id)) if next_take_id else None
        next_snippets = (database.get_snippets_by_session(str(next_take_id)) or []) if next_take_id else []
        return [{"slide_index": f["slide_index"], "kind": f["kind"],
                 "outcome": outcome(f, next_frame, next_snippets)} for f in fixes]
    except Exception as error:  # noqa: BLE001 -- the Takes table stands without it
        logger.warning("take progress: fixes unread take=%s: %s", take_id, error)
        return []


# ── last time (N309 item 1), and what worked (N359) ──────────────────────────

def previous_take(sessions: Any, take_id: Any) -> Optional[str]:
    """The Take whose walk this Take's follows: the latest spoken Take of the
    talk ordered before it (take index, then when it was made) whose
    processing completed. None for the first, or when this Take is not
    among them. Pure."""
    from services.slide_selection import spoken_arc_sessions
    spoken = sorted((s for s in spoken_arc_sessions(sessions) if s.get("id")),
                    key=lambda s: (s.get("take_index") or 0, str(s.get("created_at") or "")))
    ids = [str(s["id"]) for s in spoken]
    if str(take_id) not in ids:
        return None
    done = [s for s in spoken[:ids.index(str(take_id))]
            if s.get("analysis_state") in (None, "ready")]
    return str(done[-1]["id"]) if done else None


#: The One thing walk's one fix as its frame records it, on the strongest
#: block (`take_feedback_policy_v3._one_thing`, C-SNIPER).
_ONE_FIX = ("tempo", "moment", "none")


def walk_gave(database: Any, take_id: Any, frame: Any,
              snippets: Optional[list[dict]] = None) -> list[dict]:
    """The fixes a Take's walk gave, by the walk's own rule (C2, N309 item
    1, N323 item 6), for the Takes table, Last time and what worked alike:

    the frame's ``one_fix``, when it records one: "tempo" the pace game's
    stretch (``_stretch``), "moment" the moments' fixes (``fixes_of``),
    "none" nothing;
    a frame with walk slots but no ``one_fix`` (baked before it was kept):
    the moments' fixes, else the stretch only when it would have been the
    Sniper, rushed or on a pace or pause week (``_tempo_week``); a slow
    stretch off a week left the fix a moment;
    a frame from before N289, with no walk slot: the moments' and the
    stretch, as the tempo step then came on any Take with a stretch.

    ``snippets``: the Take's clips; when None, read only if the stretch is
    needed. Raises on a database failure; the callers catch."""
    blocks = [b for b in (frame or {}).get("blocks") or [] if isinstance(b, dict)]

    def clips() -> list[dict]:
        if snippets is not None:
            return snippets
        return database.get_snippets_by_session(str(take_id)) or []

    if not any("walk_slot" in block for block in blocks):
        return fixes_of(frame, clips())
    chosen = next((b["one_fix"] for b in blocks if b.get("one_fix") in _ONE_FIX), None)
    moments = _as_shown(database, take_id, blocks, fixes_of(frame, []))
    if chosen == "moment" or (chosen is None and moments):
        return moments
    if chosen == "none":
        return []
    stretch = _stretch(frame, clips())
    if stretch and (chosen == "tempo" or stretch["reading"] == "rushed"
                    or _tempo_week(database, take_id)):
        return [stretch]
    return []


#: What an "opened" moment event says the walk showed (``co_exposed.shown``,
#: `moment_events`), as the fix's kind.
_SHOWN_AS = {"rewrite": "clearer", "exercise": "voice"}


def _as_shown(database: Any, take_id: Any, blocks: list[dict],
              moments: list[dict]) -> list[dict]:
    """The moments' fixes as the speaker met them (the audit's 3.4): a fix
    counts only when the walk opened it, an "opened" event on its block's
    clip, and its kind is what that screen showed (a Clearer version, or the
    voice Exercise its lost Clearer version gave its place to, N547, N548);
    an event that names nothing keeps the frame's kind. A fix the walk never
    opened is not one the walk gave, so Last time never names it. The
    frame's own fixes when the events cannot be read. Never raises."""
    if not moments:
        return moments
    try:
        events = database.list_moment_events_for_take(str(take_id)) or []
    except Exception as error:  # noqa: BLE001 -- the frame's fixes then
        logger.warning("take progress: walk events unread take=%s: %s", take_id, error)
        return moments
    shown: dict[str, set] = {}
    for row in events:
        if isinstance(row, dict) and row.get("event") == "opened" and row.get("snippet_id"):
            seen = ((row.get("co_exposed") or {}).get("shown") or []) \
                if isinstance(row.get("co_exposed"), dict) else []
            shown.setdefault(str(row["snippet_id"]), set()).update(
                _SHOWN_AS[s] for s in seen if s in _SHOWN_AS)
    out = []
    for fix in moments:
        block = next((b for b in blocks if b.get("slide_index") == fix["slide_index"]
                      and b.get("exercise_kind") == fix["kind"] and b.get("walk_slot")), None)
        clips = [str(s) for s in (block or {}).get("snippet_ids") or []]
        opened = [shown[c] for c in clips if c in shown]
        if not opened:
            continue
        kinds = set().union(*opened)
        out.append({**fix, "kind": next(iter(kinds)) if len(kinds) == 1 else fix["kind"]})
    return out


def _tempo_week(database: Any, take_id: Any) -> bool:
    """Whether the Take was recorded on a pace or pause week
    (``plan_walk.TEMPO_LEVELS``), where any stretch is the Sniper (N309
    item 1). False on any failure."""
    from services import plan_walk
    try:
        take = database.v2_get_session_by_id(str(take_id)) or {}
    except Exception as error:  # noqa: BLE001 -- no level read: off a week
        logger.warning("take progress: take unread take=%s: %s", take_id, error)
        return False
    return plan_walk.level_for_take(database, take.get("user_id"), take) in plan_walk.TEMPO_LEVELS


def walk_fixes(database: Any, previous_take_id: Optional[Any]) -> list[dict]:
    """The fixes a Take's walk gave (``walk_gave``): its one fix, the pace
    game's only when it was the Sniper (N347 item 3, N323 item 6). [] when
    there is no such Take, it gave no fix or cannot be read. Never
    raises."""
    if not previous_take_id:
        return []
    try:
        before = database.get_v4_dark_frame(str(previous_take_id))
        if not isinstance(before, dict):
            return []
        return walk_gave(database, previous_take_id, before)
    except Exception as error:  # noqa: BLE001 -- the walk picks as without it
        logger.warning("take progress: walk unread take=%s: %s", previous_take_id, error)
        return []


def last_walk(database: Any, arc_id: Any, take_id: Any) -> list[dict]:
    """The fixes the walk of the Take before this one gave (``walk_fixes``
    of ``previous_take``), for this Take's walk (N359). [] for the first
    Take, or on any failure. Never raises."""
    try:
        sessions = database.takes.get_arc_sessions(str(arc_id)) or []
    except Exception as error:  # noqa: BLE001 -- the walk picks as without it
        logger.warning("take progress: talk unread take=%s: %s", take_id, error)
        return []
    return walk_fixes(database, previous_take(sessions, take_id))


def last_parts(database: Any, arc_id: Any, take_id: Any) -> dict:
    """Where in the talk the walk of the Take before this one praised and
    fixed (``walk_parts`` of ``previous_take``'s frame), so this Take's
    praise and fix spread over the talk (founder 2026-11-06, N546 item 3).
    {} for the first Take, or on any failure. Never raises."""
    try:
        sessions = database.takes.get_arc_sessions(str(arc_id)) or []
        before = previous_take(sessions, take_id)
        if not before:
            return {}
        frame = database.get_v4_dark_frame(str(before))
        if not isinstance(frame, dict):
            return {}
        return walk_parts(frame, walk_gave(database, before, frame))
    except Exception as error:  # noqa: BLE001 -- the walk picks as without it
        logger.warning("take progress: last walk's parts unread take=%s: %s", take_id, error)
        return {}


def walk_parts(frame: Any, fixes: Any) -> dict:
    """``{"praise": part, "fix": {part, ...}}``: the part of the talk
    (`moment_pick.part_of`, by where each paragraph stands in the frame) of
    the walk's best (``highest_moment``) and of each fix it gave (``fixes``,
    `walk_gave`): a moment's own paragraph, the pace game's the middle one
    of its slide. Keys with nothing are left out. Pure."""
    from services.moment_pick import part_of
    blocks = [b for b in (frame or {}).get("blocks") or [] if isinstance(b, dict)]
    out: dict = {}
    praised = next((at for at, b in enumerate(blocks) if b.get("highest_moment")), None)
    if praised is not None:
        out["praise"] = part_of(praised, len(blocks))
    fixed = set()
    for fix in fixes or []:
        on_slide = [at for at, b in enumerate(blocks)
                    if b.get("slide_index") == fix.get("slide_index")]
        own = [at for at in on_slide if blocks[at].get("carries_exercise")
               and blocks[at].get("exercise_kind") == fix.get("kind")]
        chosen = own or on_slide
        if chosen:
            fixed.add(part_of(chosen[len(chosen) // 2], len(blocks)))
    fixed.discard(None)
    if fixed:
        out["fix"] = fixed
    return out


def worked(fixes: Any, frame: Any, snippets: list[dict]) -> frozenset:
    """``{(slide_index, kind)}``: the fixes (``walk_fixes``) whose issue is
    gone on this Take's same slide (``outcome``), which this Take's walk
    does not give again there (N359). Pure."""
    return frozenset((f["slide_index"], f["kind"]) for f in fixes or []
                     if outcome(f, frame, snippets) == GONE)


def pace_worked(database: Any, sessions: Any, take_id: Any) -> bool:
    """Whether this Take's tempo stretch is on a slide where the pace game
    the walk of the Take before gave worked (``worked``, N359): the walk's
    tempo step is then not offered, as the frame gives no Sniper there.
    False with no such walk, or on any failure. Never raises."""
    fixes = [f for f in walk_fixes(database, previous_take(sessions, take_id))
             if f["kind"] == "tempo"]
    if not fixes:
        return False
    try:
        frame = walk_frame(database, take_id)
        snippets = database.get_snippets_by_session(str(take_id)) or []
        now = _stretch(frame, snippets)
        return now is not None and (now["slide_index"], "tempo") in worked(fixes, frame, snippets)
    except Exception as error:  # noqa: BLE001 -- the step as without it
        logger.warning("take progress: pace unread take=%s: %s", take_id, error)
        return False


def last_fix(database: Any, take_id: Any, previous_take_id: Optional[Any]) -> Optional[dict]:
    """The fix the previous Take's walk gave, when it rose on this Take's
    same slide: ``{"kind", "slide_index", "clip": {"snippet_id", "url",
    "start_offset_ms", "duration_ms"}}``, the clip this Take's best on that
    slide. A fix rose when its issue is gone (``outcome``); with no moment
    fixed, the fix is the pace game's ("tempo", N347 item 3). None when there
    is no previous Take, it gave no fix, it did not rise or could not be
    read, or no clip plays. The Clearer version is the fix when an older Take
    gave two (words come first, N309). Never raises."""
    fixes = walk_fixes(database, previous_take_id)
    if not fixes:
        return None
    try:
        frame = walk_frame(database, take_id)
        snippets = database.get_snippets_by_session(str(take_id)) or []
        fix = next((f for f in fixes if f["kind"] == "clearer"), fixes[0])
        if outcome(fix, frame, snippets) != GONE:
            return None
        clip = _best_clip(_clips_by_slide(frame, snippets).get(fix["slide_index"]) or [])
        from services.corpus_coach_queue import playback_body
        body = playback_body(clip) if clip else None
        if not body:
            return None
        return {"kind": fix["kind"], "slide_index": fix["slide_index"],
                "clip": {"snippet_id": body["snippet_id"], "url": body["url"],
                         "start_offset_ms": body.get("start_offset_ms"),
                         "duration_ms": body.get("duration_ms")}}
    except Exception as error:  # noqa: BLE001 -- the walk opens without it
        logger.warning("take progress: last fix unread take=%s: %s", take_id, error)
        return None


def _best_clip(clips: list[dict]) -> Optional[dict]:
    """The slide's clip with the highest willfidence, clips with a whole
    thought first; None for none."""
    from services import moment_pick
    from services.voice_confidence import stamped_score

    def rank(c: dict) -> tuple:
        read = moment_pick.read(stamped_score(c.get("metrics")), c.get("transcript"), c.get("metrics"))
        worded = len(str(c.get("transcript") or "").split()) >= moment_pick.MIN_WORDS
        return (worded, read["value"])

    return max(clips, key=rank, default=None)
