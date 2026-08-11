"""The label ledger — quorum, self-report separation and rater routing
(founder 2026-08-11, four rules).

WHAT THIS IS. One place that answers three questions about a snippet, from
its raw rating rows:

  1. is it SETTLED, and at what label?
  2. may it enter the gold set / an evaluation?
  3. does it need another rater, and how urgently?

Everything downstream — the corpus pull, the gold set, the routing queue —
reads its answer from here, so the four rules are enforced once instead of
re-derived (differently) at each call site.

────────────────────────────────────────────────────────────────────────────
RULE 1 · THE MACHINE IS A ROUTER, NOT A RATER.  Its prediction chooses WHICH
clip a human is asked about; it is never one of the answers. Quorum is
strictly two humans.

  Enforced STRUCTURALLY, not by discipline: ``resolve()`` counts rating ROWS,
  and there is no machine lane a row could carry (QUORUM_LANES is human-only,
  and every unknown lane is excluded, not defaulted in). The machine's
  proposal cannot reach ``resolve()`` at all — it has no parameter for it.
  It enters this module through ``routing_priority()``, which decides ORDER
  and nothing else. ``machine_votes: 0`` rides on every resolution so the
  invariant is auditable in a log line rather than merely asserted here.

  Storage half: ``confidence_labels.machine_value`` is a column BESIDE
  ``value``, never blended into it, stamped SERVER-SIDE at write time (a
  client-supplied proposal would mean the rater's screen could have carried
  it — I1). ``model_version_at_time`` says which model proposed it, because
  "the machine said yes" is meaningless without knowing which machine.

RULE 2 · THE OWNER IS NOT A PEER.  A rating of one's own clip is a
SELF-REPORT: marked distinctly (``self_report``), excluded from quorum,
counted separately, and kept for RATER CALIBRATION only. The speaker knows
what they intended, so their answer is self-assessment — the one judgment
that is not independent of the thing being judged. Rating ANOTHER user's clip
(or a YouTube clip) is ordinary peer work and counts in full.

  Why a column when ``lane='game_owner'`` already implies it: lane says which
  SURFACE the rating came from, not whose clip it was. A coach rating their
  own recording writes ``lane='coach'`` and is still a self-report. Conflating
  the two makes the exclusion unqueryable in exactly the case it matters.

RULE 3 · THE SINGLETON IS WEAK SUPERVISION.  One rating is never gold and
never evaluation — it is calibration signal, and it is a QUESTION. When the
lone rating DISAGREES with the machine's proposal, that clip is the most
informative unrated thing in the corpus: it is either a model miss or a rater
miss, and one more peer says which. It routes first (active learning).

RULE 4 · IDK IS A RESPONSE, NOT A NULL.  "I don't know" is counted like any
other answer, which makes both founder cases fall out of one rule:

      1 definite + 1 IDK  → nobody has agreed with anybody → 3rd rater
      2 IDK               → SETTLED, "perceptually ambiguous"

  The second is ground truth, not a gap: a detector that has been taught to
  say "uncertain" where humans are uncertain beats one that fakes confidence
  there, and this is the only place that class can come from (SPEC I10 —
  "keep disagreement", low agreement is a finding).

THE ONE RULE ALL FOUR CASES FALL OUT OF. Count every eligible response, IDK
included; a snippet is settled when one response is STRICTLY modal with at
least 2 votes:

    ┌────────────────────────────────┬───────────────────────────────────┐
    │ eligible responses             │ status                            │
    ├────────────────────────────────┼───────────────────────────────────┤
    │ (none)                         │ unrated                           │
    │ exactly 1 (any)                │ singleton        — weak only      │
    │ modal ≥2, unique, not IDK      │ quorum           — SETTLED        │
    │ modal ≥2, unique, IDK          │ perceptually_ambiguous — SETTLED  │
    │ ≥2 with no unique modal ≥2     │ needs_third                       │
    └────────────────────────────────┴───────────────────────────────────┘

  yes+IDK → 1/1, no modal ≥2 → needs_third (founder case B).
  IDK+IDK → modal IDK ×2      → perceptually_ambiguous (founder case C).
  yes+yes → modal yes ×2      → quorum.

  ASSUMPTION, flagged rather than buried — the founder specified case B for
  "1 definite + 1 IDK" and did not say what TWO CONFLICTING definites do
  (yes+no). This treats it the same way: two humans who disagree have not
  reached a quorum either, so it routes to a third rater rather than booking a
  coin-flip as ground truth. Change the founder's answer and only this table
  moves.

WHICH STORED RESPONSE IS "IDK" — ``IDK_RESPONSES``, one line, on purpose.
``unrateable`` is the response the schema currently stores as a NULL value,
which is precisely what rule 4 says it must stop being. ``neutral`` is
already a first-class answer ("the moment reads middling") and stays one.
KNOWN WRINKLE, needs a founder call, does not block this ledger: the ARC GAME
writes its third answer as ``neutral`` (game_engine._normalise_answer,
2026-08-10 "yes / no / idk"), while ``unrateable`` is documented as the rater
declining — usually because the audio is unclear. So today a
``perceptually_ambiguous`` row can be two people saying "I couldn't hear it"
rather than two people hearing genuine ambiguity, and those are different
findings. The fix is a capture-time reason on the abstention, not a guess
here; until then the constituent counts ride on every resolution so the class
stays auditable and re-derivable.

FENCES. AC-9: nothing here is ever serialized toward a student — a status, a
count and a settled label are all machine-facing, and "perceptually ambiguous"
is a DB state, never a badge. BLIND COACH: the machine proposal is stored
beside the human answer and read only for routing; it is never served into a
rating payload (I1), and ``saw_model_output`` stays false.

Pure: no DB, no I/O, unit-tested. The SQL view ``snippet_label_quorum``
(migrations/add_label_quorum_ledger.sql) computes the SAME table above so the
routing queue is one query; the two are kept in step by the truth table, which
is written out in both files.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# The ternary answers, mirrored from services.state_ratings (imported lazily
# where needed — this module stays import-light and DB-free).
VALUES = ("yes", "no", "neutral")

# Rule 4: the stored shape that means "I don't know". A one-line mapping so a
# founder decision moves it without touching the resolution rule.
IDK = "idk"
IDK_RESPONSES = ("unrateable",)

# Rule 1 + Rule 2: who may hold a vote. HUMAN PANEL LANES ONLY.
#   bootstrap  — one expert rating a MODEL-PROPOSED import. Not panel-grade
#                however expert the rater (SPEC §6.2); counting it makes one
#                opinion look like consensus.
#   game_owner — self-report by lane (rule 2); also caught by the flag.
# There is deliberately no machine lane. Unknown lanes are excluded, never
# defaulted in — a lane added later must be admitted here on purpose.
QUORUM_LANES = ("coach", "game_peer")

# Rule 1, stated as data: the number of votes a machine may ever hold.
MACHINE_VOTES = 0

# Quorum is strictly two humans (founder 2026-08-11, replacing SPEC §9.1's
# model+coach+peer three-way — the model's vote is gone, not downweighted).
QUORUM_N = 2

# ── statuses ────────────────────────────────────────────────────────────────

UNRATED = "unrated"
SINGLETON = "singleton"
NEEDS_THIRD = "needs_third"
QUORUM = "quorum"
PERCEPTUALLY_AMBIGUOUS = "perceptually_ambiguous"

# The two settled states. Only these may enter the gold set or an evaluation.
SETTLED_STATUSES = (QUORUM, PERCEPTUALLY_AMBIGUOUS)

# The settled label written for two IDKs. NOT a member of VALUES: it is a
# statement about the MOMENT (humans cannot separate it), and letting it into
# the rating domain would make it storable as one rater's answer.
AMBIGUOUS_LABEL = "ambiguous"

# ── routing priority (rule 3's active learning) ─────────────────────────────
#
# Higher is served sooner. The gaps are wide so a later tier can be inserted
# without renumbering a live queue.

P_SINGLETON_DISAGREES = 100   # rule 3: "route it IMMEDIATELY for a 2nd peer"
P_NEEDS_THIRD = 80            # rule 4 case B: quorum blocked on one rater
P_SINGLETON = 40              # one rating, machine agrees or has no opinion
P_UNRATED = 20                # never seen; the baseline queue
P_SETTLED = 0                 # done — never routed again


def is_self_report(row: Any) -> bool:
    """Rule 2. True when this rating is the speaker judging their own clip.

    Reads the flag first and falls back to the lane, so rows written BEFORE
    add_label_quorum_ledger.sql (no column) are still excluded correctly
    rather than silently entering the quorum on migration lag.
    """
    if not isinstance(row, dict):
        return False
    flag = row.get("self_report")
    if isinstance(flag, bool):
        return flag
    return (row.get("lane") or "") == "game_owner"


def response_of(row: Any) -> Optional[str]:
    """The countable response on one row — a ternary value, ``IDK``, or None
    when the row carries no answer at all (rule 4: an abstention IS an answer,
    a missing row is not)."""
    if not isinstance(row, dict):
        return None
    for key in IDK_RESPONSES:
        if row.get(key) is True:
            return IDK
    value = row.get("value")
    return value if isinstance(value, str) and value in VALUES else None


def _eligible(rows: Any, *, state_id: Optional[str] = None) -> tuple:
    """Split rows into (counted responses, excluded tallies).

    Rule 1 is enforced here by construction: only ``QUORUM_LANES`` rows are
    counted, and no machine proposal is a row.
    """
    counted: list[str] = []
    n_self_report = 0
    n_lane_excluded = 0
    # A non-list is not "no ratings", it is a CALLER BUG — but this runs on
    # the corpus read path, and taking a trace or an export down over one
    # malformed argument is worse than reporting an empty ledger. (A bare
    # string is the sharp case: iterating it would count characters.)
    if not isinstance(rows, list):
        rows = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if state_id is not None and str(r.get("state_id") or "confidence") != str(state_id):
            continue
        resp = response_of(r)
        if resp is None:
            continue                      # no answer on the row — not a vote
        if is_self_report(r):
            n_self_report += 1            # rule 2: counted, never quorum
            continue
        if (r.get("lane") or "") not in QUORUM_LANES:
            n_lane_excluded += 1          # bootstrap / unknown lane
            continue
        counted.append(resp)
    return counted, n_self_report, n_lane_excluded


def resolve(rows: Any, *, state_id: Optional[str] = None) -> dict:
    """The ledger's verdict on ONE snippet, from its rating rows.

    NOTE THE SIGNATURE — there is no machine parameter, and that absence IS
    rule 1: a proposal cannot influence a resolution it cannot be passed to.

    Returns::

        {status, value, settled, gold_eligible, eval_eligible,
         weak_supervision_only, needs_rater, next_rater_ordinal,
         n_responses, n_definite, n_idk, by_response, agreement,
         n_self_report, n_lane_excluded, machine_votes, responses}

    ``value`` is the settled label — a ternary value for ``quorum``,
    ``AMBIGUOUS_LABEL`` for ``perceptually_ambiguous``, and None for every
    unsettled status (an unsettled snippet HAS no label; returning the
    front-runner would be the fabricated-ground-truth failure this whole
    module exists to prevent).
    """
    counted, n_self_report, n_lane_excluded = _eligible(rows, state_id=state_id)

    by_response: dict = {}
    for resp in counted:
        by_response[resp] = by_response.get(resp, 0) + 1
    n = len(counted)
    n_idk = by_response.get(IDK, 0)

    modal_n = max(by_response.values()) if by_response else 0
    modal = [resp for resp, c in by_response.items() if c == modal_n]

    if n == 0:
        status, value = UNRATED, None
    elif n == 1:
        status, value = SINGLETON, None
    elif modal_n >= QUORUM_N and len(modal) == 1:
        if modal[0] == IDK:
            status, value = PERCEPTUALLY_AMBIGUOUS, AMBIGUOUS_LABEL
        else:
            status, value = QUORUM, modal[0]
    else:
        status, value = NEEDS_THIRD, None

    settled = status in SETTLED_STATUSES
    return {
        "status": status,
        "value": value,
        "settled": settled,
        # Rule 3, both halves: only a settled snippet is gold or eval data.
        "gold_eligible": settled,
        "eval_eligible": settled,
        "weak_supervision_only": status == SINGLETON,
        "needs_rater": status in (UNRATED, SINGLETON, NEEDS_THIRD),
        # Who the next rater would BE — 3rd on the founder's case B, and
        # honestly the 4th when three raters still haven't converged.
        "next_rater_ordinal": (n + 1) if not settled else None,
        "n_responses": n,
        "n_definite": n - n_idk,
        "n_idk": n_idk,
        "by_response": by_response,
        # Modal share over ALL counted responses, IDK included (rule 4). 1.0
        # at n=1 is arithmetically true and not a claim — the SINGLETON status
        # is what stops one rating counting for anything.
        "agreement": round(modal_n / n, 4) if n else 0.0,
        "n_self_report": n_self_report,
        "n_lane_excluded": n_lane_excluded,
        # Rule 1, auditable rather than asserted.
        "machine_votes": MACHINE_VOTES,
        "responses": counted,
    }


def machine_proposal(snippet: Any) -> Optional[str]:
    """The machine's PROPOSED ternary for a snippet, or None when it has no
    opinion — read off the stored voice-confidence blob
    (``metrics.voice_confidence.band``, services/voice_confidence.py).

    None is an honest absence and stays one: an unmeasurable clip must not be
    booked as a machine 'neutral', which would be indistinguishable from a
    real middling read and would make the routing look informed when it isn't.

    This is the value stamped into ``confidence_labels.machine_value`` beside
    the human answer. It is NOT a vote (rule 1) and is never served to a rater
    (I1) — it exists so a later trainer can ask "which prediction did this
    human disagree with", which is the whole active-learning signal.
    """
    if not isinstance(snippet, dict):
        return None
    metrics = snippet.get("metrics")
    read = metrics.get("voice_confidence") if isinstance(metrics, dict) else None
    if not isinstance(read, dict):
        read = snippet.get("voice_confidence")
    if not isinstance(read, dict):
        return None
    band = read.get("band")
    if band in ("confident", "close_to_confident"):
        return "yes"
    if band == "neutral":
        return "neutral"
    if band in ("unconfident", "doubtful"):
        return "no"
    return None


def machine_disagrees(resolution: Any, machine_value: Any) -> bool:
    """Rule 3's trigger: does the lone human answer contradict the machine?

    False when either side has no opinion — "the machine is silent" is not a
    disagreement, and neither is an IDK (a rater who could not judge has not
    contradicted anything; it is the DEFINITE mismatch that carries the
    information).
    """
    if not isinstance(resolution, dict):
        return False
    if machine_value not in VALUES:
        return False
    responses = [r for r in (resolution.get("responses") or []) if r in VALUES]
    if not responses:
        return False
    return all(r != machine_value for r in responses)


def routing_priority(resolution: Any, machine_value: Any = None) -> int:
    """How urgently this snippet needs a (next) human — higher first.

    THE ONLY PLACE THE MACHINE'S PROPOSAL IS READ (rule 1: router, not
    rater). It reorders the queue; it cannot change a label, a count or a
    status, none of which this function is able to touch.
    """
    if not isinstance(resolution, dict):
        return P_UNRATED
    status = resolution.get("status")
    if status in SETTLED_STATUSES:
        return P_SETTLED
    if status == SINGLETON:
        return (P_SINGLETON_DISAGREES
                if machine_disagrees(resolution, machine_value)
                else P_SINGLETON)
    if status == NEEDS_THIRD:
        return P_NEEDS_THIRD
    return P_UNRATED


def rating_queue(items: Any) -> list:
    """Order snippets for the rating queue, most informative first.

    ``items`` is a list of ``{snippet_id, resolution, machine_value?}``.
    Ties break on ``snippet_id`` so the queue is DETERMINISTIC and replayable
    — the same property the game's round order already holds; a queue that
    reshuffles on every read cannot be reasoned about when a rating goes
    missing.
    """
    out = []
    for it in (items if isinstance(items, list) else []):
        if not isinstance(it, dict):
            continue
        res = it.get("resolution")
        # An item with no snippet or no resolution is not an unrated clip, it
        # is a malformed row. Queueing it would send a rater to nothing.
        if not it.get("snippet_id") or not isinstance(res, dict):
            continue
        prio = routing_priority(res, it.get("machine_value"))
        if prio <= P_SETTLED:
            continue                      # settled clips leave the queue
        out.append((prio, str(it.get("snippet_id") or ""), it))
    out.sort(key=lambda t: (-t[0], t[1]))
    return [{**t[2], "priority": t[0]} for t in out]


def serving_rank(is_own: Any) -> int:
    """Rule 2's serving half: the user's OWN recordings are served first in
    the voice game (0 before 1).

    Their own clips are the ones they are most owed a look at, and — the part
    that matters for the corpus — a self-report is calibration signal about
    THIS rater, so getting it early makes every later peer rating they give
    interpretable. Front-loading it costs the quorum nothing, because a
    self-report was never going to count toward one (rule 2).

    A ranking function rather than a sort: the caller keeps its own
    deterministic tiebreak, and this composes as the first key element.
    """
    return 0 if bool(is_own) else 1


def corpus_ledger(resolutions: Any) -> dict:
    """Roll a bag of resolutions into the ledger dial — how much of the corpus
    is actually usable, by status.

    ``gold`` is the honest denominator for anything that calls itself ground
    truth: settled snippets only. ``weak`` (singletons) and ``blocked``
    (needs_third) are the two work queues, and surfacing them is what stops a
    corpus that is 80% singletons from reading as 80% labelled.
    """
    by_status: dict = {}
    n_self_report = 0
    for res in (resolutions or []):
        if not isinstance(res, dict):
            continue
        by_status[res.get("status")] = by_status.get(res.get("status"), 0) + 1
        n_self_report += int(res.get("n_self_report") or 0)
    total = sum(by_status.values())
    gold = sum(by_status.get(s, 0) for s in SETTLED_STATUSES)
    return {
        "snippets": total,
        "by_status": by_status,
        "gold": gold,
        "weak": by_status.get(SINGLETON, 0),
        "blocked": by_status.get(NEEDS_THIRD, 0),
        "ambiguous": by_status.get(PERCEPTUALLY_AMBIGUOUS, 0),
        "self_reports_excluded": n_self_report,
        "gold_share": round(gold / total, 3) if total else None,
        # Rule 1 as a reported number: if this is ever non-zero, a machine
        # got a vote and the corpus is circular.
        "machine_votes": MACHINE_VOTES,
    }
