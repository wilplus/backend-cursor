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

  Rule 2's SERVING half — the player's own recordings first — lives in
  ``game_engine._source_class`` as the founder's 2026-08-14 three-class queue
  order (own → consented app users → YouTube corpus), which supersedes the
  own-first rank this module briefly carried.

RULE 3 · THE SINGLETON IS WEAK SUPERVISION.  One rating is never gold and
never evaluation — it is calibration signal, and it is a QUESTION. When the
lone rating DISAGREES with the machine's proposal, that clip is the most
informative unrated thing in the corpus: it is either a model miss or a rater
miss, and one more peer says which. It routes first (active learning).

RULE 4 · IDK IS A ROUTING RESPONSE, NOT A CONFIDENCE LABEL. ``not_sure`` is
stored and counted for audit, but it can never settle a clip. Two matching
perceptual ratings settle; disagreement or IDK requests a third rater:

    ┌────────────────────────────────┬───────────────────────────────────┐
    │ eligible responses             │ status                            │
    ├────────────────────────────────┼───────────────────────────────────┤
    │ (none)                         │ unrated                           │
    │ exactly 1 (any)                │ singleton        — weak only      │
    │ 2 matching perceptual answers  │ quorum           — SETTLED        │
    │ 2 responses, no quorum         │ needs_third                       │
    │ 3+ responses, no quorum        │ unresolved       — quarantined    │
    │ 1 unclear-audio report         │ audio_retry      — one fresh ear  │
    │ 2 unclear-audio reports        │ audio_quarantined — no training   │
    └────────────────────────────────┴───────────────────────────────────┘

  yes+IDK and IDK+IDK both route to a third rater. yes+no does too.
  yes+yes, in_between+in_between, or no+no settle immediately.

WHICH STORED RESPONSE IS "IDK" — in the v2 instrument it is the explicit
``not_sure`` value. ``in_between`` is a real perceptual middle and may reach
quorum in its own right. Historical v1 ``neutral`` rows retain their original
IDK interpretation; versioning prevents old judgments being silently recast.

``audio_unclear``/``unrateable`` is the OTHER thing: a TECHNICAL abstention
(the rater could not hear/judge the clip as an artifact — a failure of the
audio, not a reading of the voice). It carries NO confidence answer and can
never settle anything. One independent technical report routes the artifact
once to a fresh eligible rater; two independent technical reports quarantine
it from labeling, gold, evaluation, and training.

FENCES. AC-9: nothing here is ever serialized toward a student — a status, a
count and a settled label are all machine-facing. BLIND COACH: the machine proposal is stored
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
VALUES = ("yes", "in_between", "no", "not_sure", "audio_unclear", "neutral")
PERCEPTUAL_VALUES = ("yes", "in_between", "no")

# Polar verdicts used by the high-priority machine-disagreement router.
DEFINITE_VALUES = ("yes", "no")

# Rater uncertainty is recorded for routing/audit but cannot settle a label.
IDK = "idk"
IDK_VALUES = ("not_sure", "neutral")
NON_RESPONSE_VALUES = ("audio_unclear",)
NON_RESPONSE_FLAGS = ("unrateable",)

# Rule 1 + Rule 2: who may hold a vote. HUMAN PANEL LANES ONLY.
#   bootstrap  — seeded/historical evidence whose rater, blindness, or
#                language match cannot be verified as panel-grade.
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
UNRESOLVED = "unresolved"
AUDIO_RETRY = "audio_retry"
AUDIO_QUARANTINED = "audio_quarantined"
QUORUM = "quorum"

# Only an exact perceptual quorum may enter gold/evaluation data.
SETTLED_STATUSES = (QUORUM,)

# ── routing priority (rule 3's active learning) ─────────────────────────────
#
# Higher is served sooner. The gaps are wide so a later tier can be inserted
# without renumbering a live queue.

P_SINGLETON_DISAGREES = 100   # rule 3: "route it IMMEDIATELY for a 2nd peer"
P_NEEDS_THIRD = 80            # rule 4 case B: quorum blocked on one rater
P_AUDIO_RETRY = 60            # one technical failure: one fresh eligible ear
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
    """The countable response on one row — a DEFINITE ternary value, ``IDK``,
    or None when the row carries no answer at all.

    ``not_sure`` and historical ``neutral`` map to ``IDK``: they count toward
    routing and agreement diagnostics but never settle ground truth. An
    ``unrateable`` row is a TECHNICAL abstention — a failure of the audio, not
    a reading of it — and is no response whatever its ``value`` says."""
    if not isinstance(row, dict):
        return None
    for key in NON_RESPONSE_FLAGS:
        if row.get(key) is True:
            return None
    value = row.get("value")
    if not isinstance(value, str) or value not in VALUES:
        return None
    if value in NON_RESPONSE_VALUES:
        return None
    return IDK if value in IDK_VALUES else value


def is_audio_unclear(row: Any) -> bool:
    """True for the v2 technical answer or its legacy flag equivalent."""
    return isinstance(row, dict) and (
        row.get("value") == "audio_unclear"
        or any(row.get(key) is True for key in NON_RESPONSE_FLAGS)
    )


def _eligible(rows: Any, *, state_id: Optional[str] = None) -> tuple:
    """Split rows into perceptual/IDK responses and technical failures.

    Rule 1 is enforced here by construction: only ``QUORUM_LANES`` rows are
    counted, and no machine proposal is a row.
    """
    counted: list[str] = []
    n_self_report = 0
    n_lane_excluded = 0
    n_audio_unclear = 0
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
        technical = is_audio_unclear(r)
        resp = response_of(r)
        if resp is None and not technical:
            continue
        if is_self_report(r):
            n_self_report += 1
            continue
        if (r.get("lane") or "") not in QUORUM_LANES:
            n_lane_excluded += 1
            continue
        if technical:
            n_audio_unclear += 1
            continue
        if resp is not None:
            counted.append(resp)
    return counted, n_self_report, n_lane_excluded, n_audio_unclear


def resolve(rows: Any, *, state_id: Optional[str] = None) -> dict:
    """The ledger's verdict on ONE snippet, from its rating rows.

    NOTE THE SIGNATURE — there is no machine parameter, and that absence IS
    rule 1: a proposal cannot influence a resolution it cannot be passed to.

    Returns::

        {status, value, settled, gold_eligible, eval_eligible,
         weak_supervision_only, needs_rater, next_rater_ordinal,
         n_responses, n_definite, n_idk, n_audio_unclear,
         by_response, agreement,
         n_self_report, n_lane_excluded, machine_votes, responses}

    ``value`` is one of the three perceptual positions only after two
    independent humans match. Every unsettled status returns None; exposing a
    front-runner as truth would fabricate a label.
    """
    counted, n_self_report, n_lane_excluded, n_audio_unclear = _eligible(
        rows, state_id=state_id)

    by_response: dict = {}
    for resp in counted:
        by_response[resp] = by_response.get(resp, 0) + 1
    n = len(counted)
    n_idk = by_response.get(IDK, 0)

    modal_n = max(by_response.values()) if by_response else 0
    perceptual = {
        response: count for response, count in by_response.items()
        if response in PERCEPTUAL_VALUES
    }
    perceptual_modal_n = max(perceptual.values()) if perceptual else 0
    perceptual_modal = [
        response for response, count in perceptual.items()
        if count == perceptual_modal_n
    ]

    if n_audio_unclear >= 2:
        status, value = AUDIO_QUARANTINED, None
    elif n == 0 and n_audio_unclear == 1:
        status, value = AUDIO_RETRY, None
    elif n == 0:
        status, value = UNRATED, None
    elif n == 1:
        status, value = SINGLETON, None
    elif perceptual_modal_n >= QUORUM_N and len(perceptual_modal) == 1:
        status, value = QUORUM, perceptual_modal[0]
    elif n < 3:
        status, value = NEEDS_THIRD, None
    else:
        # Safe holding state: three valid responses without a perceptual
        # quorum cannot be promoted to truth and do not route indefinitely.
        status, value = UNRESOLVED, None

    settled = status in SETTLED_STATUSES
    return {
        "status": status,
        "value": value,
        "settled": settled,
        # Rule 3, both halves: only a settled snippet is gold or eval data.
        "gold_eligible": settled,
        "eval_eligible": settled,
        "weak_supervision_only": status == SINGLETON,
        "needs_rater": status in (
            UNRATED, SINGLETON, NEEDS_THIRD, AUDIO_RETRY,
        ),
        "next_rater_ordinal": (
            n + n_audio_unclear + 1
            if status in (UNRATED, SINGLETON, NEEDS_THIRD, AUDIO_RETRY)
            else None
        ),
        "n_responses": n,
        "n_definite": n - n_idk,
        "n_idk": n_idk,
        "n_audio_unclear": n_audio_unclear,
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
        return "in_between"
    if band in ("unconfident", "doubtful"):
        return "no"
    return None


def machine_disagrees(resolution: Any, machine_value: Any) -> bool:
    """Rule 3's trigger: does the lone human answer contradict the machine?

    False when either side lacks a DEFINITE opinion — "the machine is
    silent" is not a disagreement, a machine 'neutral' (its own ambiguous
    read) cannot be definitely contradicted, and a human IDK has not
    contradicted anything. It is the DEFINITE-vs-DEFINITE mismatch that
    carries the active-learning information.
    """
    if not isinstance(resolution, dict):
        return False
    if machine_value not in DEFINITE_VALUES:
        return False
    responses = [r for r in (resolution.get("responses") or [])
                 if r in DEFINITE_VALUES]
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
    if status in SETTLED_STATUSES or status in (
        UNRESOLVED, AUDIO_QUARANTINED,
    ):
        return P_SETTLED
    if status == SINGLETON:
        return (P_SINGLETON_DISAGREES
                if machine_disagrees(resolution, machine_value)
                else P_SINGLETON)
    if status == NEEDS_THIRD:
        return P_NEEDS_THIRD
    if status == AUDIO_RETRY:
        return P_AUDIO_RETRY
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


def rater_submission_access(rows: Any, rater_id: Any) -> dict:
    """Whether one authenticated human may submit on this snippet now.

    This is the assignment-side companion to :func:`resolve`. A first
    technical report must be retried by a *different* eligible human; a
    settled, unresolved, or audio-quarantined artifact is closed to new
    raters. Existing perceptual answers remain editable under the current
    rater's ordinary revision policy, but an unclear-audio report cannot be
    converted into a second listen by the same person.

    Language eligibility is deliberately checked by the route before this
    function. Mixing language into quorum state would turn a routing concern
    into evidence about the clip.
    """
    rid = str(rater_id or "")
    labels = [row for row in (rows if isinstance(rows, list) else [])
              if isinstance(row, dict)]
    mine = [row for row in labels
            if rid and str(row.get("rater_id") or "") == rid]
    resolution = resolve(labels)

    if resolution.get("status") == AUDIO_QUARANTINED:
        return {
            "allowed": False,
            "outcome": "audio_quarantined",
            "has_own_rating": bool(mine),
            "resolution": resolution,
        }
    if mine and any(is_audio_unclear(row) for row in mine):
        return {
            "allowed": False,
            "outcome": "fresh_rater_required",
            "has_own_rating": True,
            "resolution": resolution,
        }
    if mine:
        return {
            "allowed": True,
            "outcome": "update",
            "has_own_rating": True,
            "resolution": resolution,
        }
    if resolution.get("needs_rater"):
        return {
            "allowed": True,
            "outcome": "new",
            "has_own_rating": False,
            "resolution": resolution,
        }
    return {
        "allowed": False,
        "outcome": "closed",
        "has_own_rating": False,
        "resolution": resolution,
    }


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
        "unresolved": by_status.get(UNRESOLVED, 0),
        "audio_retry": by_status.get(AUDIO_RETRY, 0),
        "audio_quarantined": by_status.get(AUDIO_QUARANTINED, 0),
        "self_reports_excluded": n_self_report,
        "gold_share": round(gold / total, 3) if total else None,
        # Rule 1 as a reported number: if this is ever non-zero, a machine
        # got a vote and the corpus is circular.
        "machine_votes": MACHINE_VOTES,
    }
