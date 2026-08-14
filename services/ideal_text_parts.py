"""The ideal text as an ordered list of PARTS with stable ids.

SPEC-parts-locking-and-layers §3.1, Step 0. Identity only — nothing here locks
anything. Pure: no DB, no clock, no I/O.

WHAT A PART IS. One paragraph of the student's document, carrying an id that
survives both reordering and rewording. That id is the thing PR 3 hangs a lock
on, and none of the obvious alternatives can hold one: an array index shifts on
reorder (and on any edit, since empty segments are dropped), a content hash
dies the first time an approved accentuation touches the words, and a character
offset needs re-anchoring on every edit — a second segmentation problem beside
the one F1 already owns.

THE BACKEND NEVER SPLITS TEXT, and this is the load-bearing decision in the
file. §9 asked for a server-side backfill running the FE's
`splitBadgeParagraphSpans` over stored texts. Building that would have
contradicted §2's own argument — a real distinction with no single home gets
re-derived slightly differently by each consumer until they disagree. The FE's
splitter is marker-aware: it refuses a split point inside a rich-marker token,
because a fold marker may legally contain a blank line and slicing it leaks raw
syntax. A Python mirror would be a SECOND definition of "paragraph", and the
two would drift on exactly the documents where the split is hard.

So the client mints ids and sends them; this module VALIDATES and the DB
stores. `joined()` is the one place the reverse direction lives, and it must
match the FE's `joinSegments` — that is a two-line rule ("\\n\\n", blanks
dropped) rather than a scanner, so mirroring it is safe where mirroring the
splitter is not.

REFUSED, NEVER REPAIRED. A malformed parts list is rejected whole. Half-
accepting one would persist an identity map that disagrees with the text the
student is looking at, and every lock set against it afterwards would be
anchored to the wrong words — unrecoverable, because a wrong anchor is
indistinguishable from a right one once written.
"""
from __future__ import annotations

import difflib
import logging
import re
import uuid
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The BE's own ceiling on the stored document (20000 chars, enforced on the
# user-edit PUT). Parts join into that same document, so the joined form is
# what has to fit — a per-part limit would let 500 parts of 100 chars through.
MAX_DOCUMENT_CHARS = 20000

# A document with more parts than this is not a document a person is arranging.
# Bounded so a malformed or hostile payload cannot turn one PUT into an
# unbounded write; the FE's paragraph split over a 20k document cannot
# realistically approach it.
MAX_PARTS = 500

# Client-minted, and validated as a real UUID rather than "some string". An
# unvalidated id would let a caller mint colliding or guessable ids across
# arcs, and the collision would surface as one document's lock appearing on
# another's paragraph.
_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE)


# ── the two layers (§3.2 / §4) ──────────────────────────────────────────────
#
# WHEN an intervention may fire, which is a different question from HOW it
# renders. `kind` (replace / bold / advice) is the render instruction and
# already exists; `layer` is the phase gate. They correlate today and will stop
# correlating the day a second accentuation kind ships (colour alongside bold),
# at which point one overloaded column would silently change the meaning of the
# phase logic — the `unit`/`denominator` bug in dimension_registry, again.
COMPOSITION = "composition"      # change the words
ACCENTUATION = "accentuation"    # style words already there

# The split is on WHAT THE CHANGE DOES TO THE TEXT, not on which lane emitted
# it. Sort the four `kind` enums in idealText.ts and they fall cleanly in two
# (§2) — this is that distinction, finally named. `advice` is accentuation: a
# delivery or structural prompt ("pause here", "make the second half land") is
# about how the words are said, and changes none of them.
_LAYER_BY_KIND = {
    "replace": COMPOSITION,
    "insert": COMPOSITION,
    "bold": ACCENTUATION,
    "advice": ACCENTUATION,
}


def layer_of_kind(kind: Any) -> Optional[str]:
    """Which layer a change belongs to, or None for an unknown kind.

    None means REFUSED downstream, never "allow it anyway". A kind nobody has
    classified is a kind nobody decided the phase rules for, and defaulting it
    into composition would let an unnamed lane rewrite locked text."""
    return _LAYER_BY_KIND.get(kind if isinstance(kind, str) else "")


def allowed_layer(part: Any) -> str:
    """§4 — the phase, DERIVED from the lock and never stored.

    A stored phase can desync from the lock that is supposed to imply it, and
    then two places disagree about whether a rewrite is legal on this
    paragraph. Deriving also gives progressive locking for free: part 1 locked
    while part 2 is open is simply what per-part state means, not a case
    anybody had to write.
    """
    locked = (part or {}).get("locked_at") if isinstance(part, dict) else None
    return ACCENTUATION if locked else COMPOSITION


def part_spans(parts: Any) -> list:
    """[(start, end, part)] over the JOINED document.

    Exact, not approximate, because `joined()` is the only mapping from parts
    to text and it is deterministic: part i begins where every earlier part
    plus its separator ended. The caller may only trust these offsets against a
    document the parts actually join to — which is why both the read and the
    write path check `agrees_with_text` first.
    """
    out: list = []
    cursor = 0
    for p in (parts or []):
        if not isinstance(p, dict):
            continue
        text = (p.get("text") or "").strip()
        if not text:
            continue
        if out:
            cursor += 2          # the "\n\n" separator
        out.append((cursor, cursor + len(text), p))
        cursor += len(text)
    return out


def part_at(spans: Any, start: Any, end: Any) -> Optional[dict]:
    """The part a span sits in, or None when it sits in no single part.

    None for a span that STRADDLES two parts, deliberately. Such a change is
    half in a locked paragraph and half in an open one, and there is no honest
    layer for it — picking either would let a rewrite touch locked words, or
    suppress a legal one. The caller drops it, which is the same "never guess
    an anchor" rule the tracked-change lane already follows (#219).
    """
    try:
        s, e = float(start), float(end)
    except (TypeError, ValueError):
        return None
    for p_start, p_end, part in (spans or []):
        if s >= p_start and e <= p_end:
            return part
    return None


def _norm(text: Any) -> str:
    """Whitespace- and case-insensitive form, for comparing a stored block's
    words against a part's. The served document is finalize-cased (sentence
    capitals) and stored block text is not — the #230 raw-vs-document class."""
    if not isinstance(text, str):
        return ""
    return " ".join(text.split()).lower()


def covered_by_locked_part(text: Any, parts: Any) -> bool:
    """Are these words inside a LOCKED part?

    THE SAVE HOLE THIS CLOSES (founder 2026-08-07). Save resolves every
    unactioned offer as kept-mine so the document is left clean. But R1 hides
    composition offers on a locked part — so a student could lock a section,
    say it better in a later take, hit Save, and have that upgrade silently
    DECLINED without it ever reaching the screen.

    That is the same defect R3 refuses on the lock button: it writes a decision
    the student never made, into the exact signal §6 depends on for
    manager-engine precision. Suppressed must mean pending, not refused.

    SUBSTRING, not span arithmetic, and deliberately so. Save has no served
    document in hand — that value is derived per request from four sources —
    and reconstructing it here would be a second implementation of the serve
    path. A part's text IS a slice of that document, so "the block's words sit
    inside a locked part's words" answers the same question without needing it.

    WHEN IN DOUBT, SKIP. An unmatched offer stays pending, which at worst
    leaves Save less tidy and the offer visible next time. The opposite error
    declines something the student never saw, silently and unrecoverably.
    """
    needle = _norm(text)
    if not needle:
        return False
    for p in (parts or []):
        if not isinstance(p, dict) or not p.get("locked_at"):
            continue
        if needle in _norm(p.get("text")):
            return True
    return False


class InvalidParts(ValueError):
    """The parts list cannot be trusted. Carries the reason for the 400."""


def joined(parts: Any) -> str:
    """The parts back into the document every read-only consumer sees.

    MIRRORS the FE's `joinSegments` exactly: trim each, drop the blanks, join
    on a blank line. Blanks are dropped rather than preserved because "\\n\\n"
    IS the separator — an empty part would emit a doubled separator and the
    next split would not round-trip.
    """
    out = []
    for p in (parts or []):
        text = (p.get("text") if isinstance(p, dict) else None) or ""
        text = text.strip()
        if text:
            out.append(text)
    return "\n\n".join(out)


def validate(raw: Any) -> list:
    """A client's parts list -> [{id, ord, text}], or raise InvalidParts.

    `ord` is ASSIGNED HERE from list position, never read from the payload. The
    order of the list IS the order of the document — accepting a client `ord`
    would allow a list whose positions disagree with its own sequence, and
    there would be no way to tell which one the student meant.
    """
    if not isinstance(raw, list):
        raise InvalidParts("parts must be a list")
    if not raw:
        # An empty document is a legitimate state (the student cleared it),
        # and it is NOT the same as "no parts sent" — the caller distinguishes
        # those by whether the key was present at all.
        return []
    if len(raw) > MAX_PARTS:
        raise InvalidParts("too many parts")

    out: list = []
    seen: set = set()
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise InvalidParts(f"part {i} is not an object")
        pid = item.get("id")
        if not isinstance(pid, str) or not _UUID_RE.match(pid):
            raise InvalidParts(f"part {i} has no valid id")
        pid = pid.lower()
        if pid in seen:
            # Two parts claiming one id is the single most damaging shape
            # here: a lock set on that id would apply to whichever row won,
            # and nothing downstream could detect it.
            raise InvalidParts(f"duplicate part id at {i}")
        seen.add(pid)
        text = item.get("text")
        if not isinstance(text, str):
            raise InvalidParts(f"part {i} has no text")
        locked = item.get("locked")
        if locked is not None and not isinstance(locked, bool):
            # A truthy-ish lock is not a lock. The flag decides whether the
            # machine may rewrite these words; coercion here would let a
            # malformed client pin or unpin paragraphs by accident.
            raise InvalidParts(f"part {i} has a non-boolean lock")
        text = text.strip()
        if not text:
            # A blank part has no words to move, no words to lock, and would
            # render as a dead drop target. The FE drops these at split time;
            # refusing rather than silently skipping keeps the id list the
            # client believes it sent identical to the one stored.
            raise InvalidParts(f"part {i} is empty")
        entry = {"id": pid, "ord": i, "text": text}
        if locked is not None:
            entry["locked"] = locked
        out.append(entry)

    if len(joined(out)) > MAX_DOCUMENT_CHARS:
        raise InvalidParts("text too long")
    return out


def agrees_with_text(parts: Any, text: Any) -> bool:
    """Does this parts list join back to this document?

    THE INVARIANT THAT KEEPS TWO REPRESENTATIONS FROM DRIFTING. `text` stays
    the stored, canonical document (every read-only consumer reads it) and
    `parts` carries identity for the same words. Two representations of one
    thing is precisely the shape that rots, so the write path checks them
    against each other and refuses the pair rather than storing a disagreement.

    Compared on the JOINED form, not span-by-span: the client may legitimately
    normalise whitespace inside a part, and `joined()` is the only mapping that
    has to hold.
    """
    return joined(parts) == ((text if isinstance(text, str) else "") or "").strip()


def _balanced(paragraph: str) -> bool:
    """Could this paragraph have been sliced out of a marker token?

    The FE's splitter refuses a split point inside a rich-marker token because
    a token may legally contain a blank line, and slicing it leaks raw syntax.
    The server-side split below inherits the same risk, so it inherits a guard:
    a paragraph with an ODD count of style tokens or unpaired moment brackets
    is evidence the split landed inside one, and compose refuses rather than
    serving half a token as text. Conservative on purpose — a false refusal
    costs one round of machine refresh; a false pass ships broken syntax."""
    if paragraph.count("**") % 2 != 0:
        return False
    return paragraph.count("[[") == paragraph.count("]]")


def compose_locked(base_text: Any, rows: Any) -> Optional[dict]:
    """Overlay the user's LOCKED parts onto the current machine document.

    THE UN-PARKED VERSIONING CHANGE (founder 2026-08-10). Until now the user's
    typed edit was one whole-document string stamped with a version, winning
    display only while that version was current — so ANY version bump swapped
    their words out from under them, and a card offered them back. This is the
    replacement: the document composes per part, a locked part keeps the
    user's words verbatim, an unlocked part refreshes to the machine's current
    text, and the swap that needed a card simply stops happening.

    Returns None when there is nothing to do (no parts stored, none locked) —
    the caller keeps today's behaviour exactly. Otherwise:

        {"text": str, "parts": [{id, ord, text, locked}], "changed": bool}

    ── WHY THE SERVER MAY SPLIT *THIS* TEXT (vs the §10.2 rule) ───────────────

    §10.2 forbids a server-side paragraph splitter because the FE's is
    marker-aware and a rival implementation would drift. That rule protects
    USER text. The base document here is the machine's own assembly, JOINED BY
    THIS CODEBASE with "\\n\\n" — splitting it is the inverse of our own join,
    the same standing `joined()` already has, not a second definition of
    "paragraph". User text is still never split server-side: stored parts
    arrive pre-split from the client. `_balanced` guards the residual marker
    risk, and refusal degrades to serving the stored parts wholesale — typed
    words protected, machine refresh deferred, never the other way round.

    ── ALIGNMENT: ANCHOR-FIRST (SPEC §12.1, founder 2026-08-14) ──────────────

    "Typed words are invincible." A locked part is a hard, immutable anchor,
    and the machine aligns AROUND it, never through it:

      1. ANCHOR PASS — each locked part claims its verbatim text in the
         machine paragraph list, monotonically. A machine paragraph equal to
         a locked part's words is CONSUMED by the anchor (the lock travels
         with its words — a moved paragraph serves once, under its lock,
         where the old positional and flat-diff paths both served it twice).
      2. ALL locks anchored → the anchors segment both lists into OPEN
         regions, each refreshed independently (equal keeps the id;
         reworked/new machine paragraphs get FRESH ids; dropped open
         paragraphs go with the machine). Open text refreshes even when
         every open paragraph changed.
      3. NO lock anchored (the normal case after a fresh take — the machine
         text never contains the typed words): equal counts → the POSITIONAL
         compose (the founder's flagship "refresh 1 and 3, skip 2" — slot
         correspondence is the only honest signal left, and duplication is
         impossible because the anchor pass exhausted verbatim matches);
         diverged counts → the conservative flat diff (a replace region
         containing a lock pins that region; machine rework held as offers).
      4. MIXED — some locks anchored, some gone — is a rebuild that cannot
         place every lock: the previous composed state serves wholesale
         (`_pinned`), drop-never-guess.
      5. THE INVARIANT, CHECKED: the output must carry every locked part
         exactly once, id and text intact — else the composition is refused
         and the pinned state serves. A lock is never lost to a refactor.

    Server-minted ids for machine paragraphs do not breach the client-mints
    rule either: that rule exists so no rival SPLIT decides where a paragraph
    begins. Identity for machine-authored paragraphs has no client claim at
    all — the client has never seen them.
    """
    parts = serve(rows)
    if not parts or not any(p.get("locked") for p in parts):
        return None
    base = (base_text if isinstance(base_text, str) else "").strip()

    def _pinned(changed: bool = False) -> dict:
        # The fallback: the user's stored document, exactly as saved.
        out = [dict(p, ord=i) for i, p in enumerate(parts)]
        return {"text": joined(out), "parts": out, "changed": changed}

    if not base:
        return _pinned()
    paras = [p.strip() for p in re.split(r"\n{2,}", base) if p.strip()]
    if not paras or not all(_balanced(p) for p in paras):
        return _pinned()

    # ── THE ANCHOR PASS (SPEC §12.1, founder 2026-08-14) ────────────────────
    #
    # A locked part is a HARD, IMMUTABLE ANCHOR. Each one claims its
    # VERBATIM text in the machine list, monotonically (first unused exact
    # match after the previous anchor's claim — the same first-occurrence
    # rule relocate_pieces pass 1 follows, so repeated wording cannot steal
    # an earlier anchor). A machine paragraph equal to a locked part's words
    # is CONSUMED by the anchor: the lock travels with its words, and they
    # serve exactly once, under the lock's id. This is what the two paths
    # this pass replaced could not guarantee:
    #
    #   * the count-equal POSITIONAL path slotted a locked part at its old
    #     ordinal even when the machine had MOVED that content — the words
    #     then served twice, once pinned and once as a fresh machine
    #     paragraph. Its justification ("the master's paragraph structure
    #     is block-stable") also died with the §11.1 cap, which re-grains
    #     paragraph counts on both builders.
    #   * the flat difflib walk expressed a move as delete+insert — the
    #     delete kept the locked part AND the insert minted the machine's
    #     copy. Same duplication, different mechanism.
    locked_ks = [k for k, p in enumerate(parts) if p.get("locked")]
    anchor_of: dict = {}
    scan_from = 0
    for k in locked_ks:
        want = parts[k]["text"]
        for j in range(scan_from, len(paras)):
            if paras[j] == want:
                anchor_of[k] = j
                scan_from = j + 1
                break

    out: list = []
    stored_texts = [p["text"] for p in parts]

    def _emit_open(stored_seg: list, mach_seg: list) -> None:
        # Open text follows the machine (equal keeps the id; anything the
        # machine reworded or added gets fresh identity — "a paragraph the
        # machine rewrote is not the part the student locked"; anything it
        # dropped goes).
        st = [p["text"] for p in stored_seg]
        sm = difflib.SequenceMatcher(None, st, mach_seg, autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                out.extend(dict(stored_seg[i]) for i in range(i1, i2))
            elif tag in ("replace", "insert"):
                out.extend({"id": str(uuid.uuid4()), "text": mach_seg[j],
                            "locked": False} for j in range(j1, j2))

    if anchor_of and len(anchor_of) == len(locked_ks):
        # (a) EVERY locked part found its words in the machine text → the
        # anchors segment both lists into OPEN regions, each refreshed
        # independently. This is the move-safe path the old code lacked,
        # and it lets open text refresh even when every open paragraph
        # changed — the old flat diff bundled the whole document into one
        # replace opcode, saw a lock inside it, and pinned everything.
        pairs = sorted((k, anchor_of[k]) for k in anchor_of)
        prev_k, prev_j = -1, -1
        for k, j in pairs:
            _emit_open([p for p in parts[prev_k + 1:k]
                        if not p.get("locked")], paras[prev_j + 1:j])
            out.append(dict(parts[k]))
            prev_k, prev_j = k, j
        _emit_open([p for p in parts[prev_k + 1:]
                    if not p.get("locked")], paras[prev_j + 1:])
    elif anchor_of:
        # (d) MIXED — some locked words are in the machine text, some are
        # gone. Placing the unfound ones relative to the found ones is a
        # guess, and the standing rule is drop-never-guess: the previous
        # composed state serves wholesale. (Two locks with identical text
        # and one machine copy land here too — deliberately.)
        return _pinned()
    elif len(paras) == len(stored_texts):
        # (b) NO lock anchored + EQUAL counts → positional. This is the
        # founder's flagship ("refresh 1 and 3, physically skip 2"): after
        # a fresh take the machine text never contains the typed words, and
        # slot correspondence is the only honest signal left. Duplication —
        # the §12.1 defect this rebuild kills — is IMPOSSIBLE here by
        # construction: the anchor pass exhausted verbatim matches, so no
        # machine paragraph equals any locked text; the lock's slot
        # replaces the machine's paragraph for that slot, and the machine's
        # version stays held as offers behind the lock.
        for k, part in enumerate(parts):
            if part.get("locked"):
                out.append(dict(part))
            elif paras[k] == part["text"]:
                out.append(dict(part))
            else:
                out.append({"id": str(uuid.uuid4()), "text": paras[k],
                            "locked": False})
    else:
        # (c) NO lock anchored + counts DIVERGED → the conservative flat
        # diff: equal keeps ids, a replace region containing a lock pins
        # that region (machine rework held as offers), a delete keeps only
        # locked parts, an insert is new machine material. Duplication is
        # impossible here for the same reason as (b): a machine paragraph
        # equal to a locked text would have anchored in the pass above.
        sm = difflib.SequenceMatcher(None, stored_texts, paras,
                                     autojunk=False)
        for tag, i1, i2, j1, j2 in sm.get_opcodes():
            if tag == "equal":
                out.extend(dict(parts[k]) for k in range(i1, i2))
            elif tag == "replace":
                if any(parts[k].get("locked") for k in range(i1, i2)):
                    out.extend(dict(parts[k]) for k in range(i1, i2))
                else:
                    out.extend({"id": str(uuid.uuid4()), "text": paras[j],
                                "locked": False} for j in range(j1, j2))
            elif tag == "delete":
                out.extend(dict(parts[k]) for k in range(i1, i2)
                           if parts[k].get("locked"))
            else:  # insert
                out.extend({"id": str(uuid.uuid4()), "text": paras[j],
                            "locked": False} for j in range(j1, j2))

    if not out:
        return _pinned()

    # ── THE §12.1 INVARIANT, CHECKED ON THE WAY OUT ─────────────────────────
    # Whatever the alignment above did, every locked part must appear in the
    # output EXACTLY ONCE, id and text intact. This is the fence itself, not
    # a debug assert: if a future edit to the alignment breaks the
    # guarantee, the composition is refused and the previous composed state
    # serves — a lock is never lost to a refactor.
    served_locked = [(p["id"], p["text"]) for p in out if p.get("locked")]
    want_locked = [(parts[k]["id"], parts[k]["text"]) for k in locked_ks]
    if served_locked != want_locked:
        logger.error(
            "compose_locked: alignment violated the §12.1 invariant "
            "(%d locked stored, %d served) — serving the pinned state",
            len(want_locked), len(served_locked))
        return _pinned()

    for i, p in enumerate(out):
        p["ord"] = i
    changed = [(p["id"], p["text"], p.get("locked", False)) for p in out] != \
              [(p["id"], p["text"], p.get("locked", False)) for p in parts]
    return {"text": joined(out), "parts": out, "changed": changed}


def pinned_parts(rows: Any) -> Optional[dict]:
    """The stored composition, exactly as saved — §12.1's failed-rebuild
    fallback, callable from the route when `compose_locked` itself RAISES.

    A compose exception used to fall through to serving the RAW machine
    text: the stored parts no longer joined to it, the parts block dropped
    off the wire, and every lock went invisible in one GET — the founder's
    field report #5 ("my locked chunk came back unlocked, with a
    recommendation on it"). The rule is the same as inside compose: a
    rebuild that cannot place the locks is a failed rebuild, and the
    previous composed state serves. None when there is nothing to pin (no
    stored parts, or none locked) — then the raw text is not protecting
    anything and may serve as before."""
    parts = serve(rows)
    if not parts or not any(p.get("locked") for p in parts):
        return None
    out = [dict(p, ord=i) for i, p in enumerate(parts)]
    return {"text": joined(out), "parts": out, "changed": False}


def serve(rows: Any) -> Optional[list]:
    """Stored rows -> the GET's `parts` block, or None when there are none.

    None (the key ABSENT) rather than [] — an absent key means "this document
    has no identity yet, derive as you always did", while [] means "this
    document is empty". The FE branches on exactly that difference, and
    collapsing the two would make a fresh document look like a cleared one.

    `locked` rides as a BOOLEAN, never the timestamp. The client needs to know
    which control to draw and nothing more; a timestamp on the wire invites a
    surface that renders "locked at 10:04", which is noise the student did not
    ask for. The timestamp stays server-side, where §6 needs it to tell a
    decision made before a lock from one made after.
    """
    if not rows:
        return None
    ordered: list[tuple[int, str, str, bool, int]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        pid, text = r.get("id"), r.get("text")
        if not isinstance(pid, str) or not isinstance(text, str):
            continue
        ordv = r.get("ord")
        # `isinstance(True, int)` is True in Python, and a bool `ord` would
        # sort as 0/1 and silently reorder the document.
        if not isinstance(ordv, int) or isinstance(ordv, bool):
            continue
        # The maturity counter rides as a plain int (slice 2). Missing
        # column / pre-migration rows read 0 — a chunk that never locked.
        try:
            _it = int(r.get("iteration") or 0)
        except Exception:
            _it = 0
        ordered.append((ordv, pid, text, bool(r.get("locked_at")), _it))
    if not ordered:
        return None
    ordered.sort(key=lambda t: t[0])
    out = [{"id": pid, "ord": ordv, "text": text, "locked": locked,
            "iteration": iteration}
           for ordv, pid, text, locked, iteration in ordered]
    # Re-index on the way out. A gap in `ord` (a partial write, a row deleted
    # by hand) would otherwise reach the client as a position it cannot use,
    # and the client's own list index is what it renders from.
    for i, p in enumerate(out):
        p["ord"] = i
    return out
