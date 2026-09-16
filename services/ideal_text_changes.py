"""The `changes` block of the student Ideal Text GET, one stage at a time.

Moved out of ``routes/v2/explore_ideal_text._tracked_changes_block`` (audit
Q-C1 / Q-C3, Phase 5). The route keeps a thin wrapper with the same name and
signature; every stage body below is the wrapper's former code, in the same
order, with the same fallbacks. What changed is that every swallow-all
``except`` is now a named stage run through :class:`DegradationLog` — the
same default value is served, and the payload says which stage degraded
(founder decision Q-C1: never a silently shorter payload).

THE MANAGER ENGINE IS THE SOLE GATEKEEPER (founder 2026-08-07). The lanes
below PRODUCE candidates; none of them SERVES one. Everything they assemble
goes through ``intervention_candidates.select``, which applies the frozen
exact-three family contract and collision resolution.

Anchors are resolved against the SERVED text: each piece of the take the
document came from is located as an exact substring, then the change is
narrowed inside that window. A piece whose words are no longer there (baked,
coach-corrected, student-edited) yields NO change rather than a mis-pointed
one (#219).

THE CUE SHEET IS DEFERRED (founder 2026-08-07): ``services/key_points.py``
and its tests are kept; only the wiring is gone, so ``KEY_POINTS_ENABLED`` no
longer does anything and should be deleted from Railway.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional

from services.degradation import DegradationLog

logger = logging.getLogger(__name__)

READ_PATH = "ideal_text"


@dataclass(frozen=True)
class ChangesDeps:
    """What the block needs from its caller: the database service and the
    route-level helpers it shares with the rest of the Ideal Text surface.
    They are injected so the route's own names stay the ones tests patch."""

    database: Any
    first_client_repository: Any
    applied_map: Callable[[list], dict]
    playback_map: Callable[[list], dict]
    previous_spoken_session: Callable[[str, Any], Optional[str]]
    locked_parts: Callable[[str, str, str], list]
    with_evidence_coordinates: Callable[..., list]
    record_arms: Callable[[Any, str, str], None]


class _ChangesRun:
    """One read's state, stage by stage. Attributes are the former locals of
    the one-function version, under the same names without the underscore."""

    def __init__(self, arc_id, served_text, user_id, take_session_id,
                 review_version, deps: ChangesDeps, log: DegradationLog):
        self.arc_id = arc_id
        self.served_text = served_text
        self.user_id = user_id
        self.take_session_id = take_session_id
        self.review_version = review_version
        self.deps = deps
        self.db = deps.database
        self.log = log
        # Only a durable review identity activates the immutable Take
        # contract. The student GET always supplies it. Keeping the legacy
        # no-version mode is intentional for internal pre-review callers; it
        # cannot claim a set whose Take/version provenance it does not know.
        self.take_contract_on = (
            bool(take_session_id)
            and isinstance(review_version, int)
            and not isinstance(review_version, bool)
            and review_version >= 1
        )
        self.master_on = False
        self.doc: dict = {}
        self.pieces: list = []
        self.canonical_pieces: list = []
        self.sugs: dict = {}
        self.ledger: Any = None
        self.verdicts: dict = {}
        self.released_verdicts: Any = None
        self.user_sugs: Any = None
        self.applied: list = []
        self.kp_by_snip: dict = {}
        self.changes: list = []
        self.review_sid = ""
        self.review_doc: Any = None
        self.review_evidence_piece: Any = None
        self.additions: list = []
        self.feedback_set: Any = None
        self.feedback_exposure: list = []
        self.frozen_family_snippets: dict = {}
        self.learning_presentations: dict[str, list[dict]] = {}
        self.feedback_response_count = 0
        self.response_rows: list = []
        self.session: Any = None
        self.sel: dict = {}
        self.styles: list = []
        self.add: dict = {}
        self.arm_sid = ""

    # ── stages, in order ────────────────────────────────────────────────

    def execute(self) -> dict:
        from services.ideal_text_block import _living_transcript_enabled
        if not _living_transcript_enabled():
            return {}
        log = self.log
        self._load_document()
        if not self.doc:
            return {}
        self._relocate()
        log.run("changes.canonical_provenance", self._canonical_provenance)
        self._suggestions_and_verdicts()
        log.run("changes.applied_map", self._applied_map)
        log.run("changes.emphasis_key_phrases", self._emphasis_key_phrases)
        self._build_candidates()
        if self.take_contract_on and self.review_sid:
            log.run("changes.current_take_confident_voice",
                    self._current_take_confident_voice)
        log.run("changes.praise_playback", self._praise_playback)
        if self.master_on:
            log.run("changes.upgrade_changes", self._upgrade_changes)
            log.run("changes.block_additions", self._block_additions)
        log.run("changes.prior_take", self._prior_take)
        self._feedback_set_and_fallbacks()
        log.run("changes.v3_shadow", self._v3_shadow)
        self._immutable_membership()
        self._select()
        self._evidence_coordinates()
        log.run("changes.practice_offer", self._practice_offer)
        early = self._span_checks()
        if early is not None:
            return early
        self._claim_or_filter()
        from services.take_lifecycle import (
            confidence_prior_learning_writes_enabled,
        )
        if (self.feedback_set is not None and self.take_contract_on
                and self.arm_sid
                and confidence_prior_learning_writes_enabled()):
            log.run("changes.canonical_dual_write",
                    self._canonical_dual_write)
        log.run("changes.first_client_feedback", self._first_client_feedback)
        return self._finish()

    def _load_document(self) -> None:
        from services.transcript_document import build_transcript_document
        from services.master_document import (
            assemble_master_document, master_document_enabled,
        )
        self.master_on = master_document_enabled()
        if self.master_on:
            # MASTER MODEL (founder 2026-07-22): the document is the
            # persistent master; its pieces carry per-piece spans + the
            # origin take badge, so the star lane anchors unchanged. The
            # prior-take lane is superseded by block upgrade offers.
            _master = assemble_master_document(self.arc_id, database=self.db)
            if _master.get("ready"):
                doc = _master.get("document") or {}
                doc["text"] = _master.get("text")
            else:
                # No skeleton yet (flip-ON before the next take / pre-
                # migration): the star lane keeps anchoring on the
                # living-transcript document rather than going dark.
                self.master_on = False
                doc = build_transcript_document(self.arc_id, database=self.db)
        else:
            doc = build_transcript_document(self.arc_id, database=self.db)
        self.doc = doc

    def _relocate(self) -> None:
        from services.transcript_document import relocate_pieces
        # The served text may already carry approved bakes / coach text —
        # re-anchor the pieces onto it MONOTONICALLY (never a bare
        # first-occurrence search, the review's mis-anchor defect).
        # PARAGRAPH FALLBACK (founder 2026-08-12). This is the call that
        # was taking the feedback engine dark: lock a paragraph — even the
        # AI's own words, unedited — and the NEXT take's pieces no longer
        # match the composed text, so every one of them was dropped and
        # build_tracked_changes below received nothing to anchor to.
        # Unlocatable pieces now take their paragraph's span, tagged
        # anchor_grain='paragraph' so word-precise consumers decline.
        self.pieces = relocate_pieces(
            self.served_text, self.doc.get("pieces") or [],
            paragraph_fallback=True)

    def _canonical_provenance(self) -> None:
        # The canonical Take-1 provenance stays beside the canonical words.
        # Later-Take feedback is evaluated against new audio, but its deck
        # route must come from the document actually being served — never
        # from whichever transcript happened to be latest when this GET ran.
        from services.transcript_document import relocate_pieces
        _canonical_row = self.db.ideal_text.get_coach_arc_ideal_text(self.arc_id) or {}
        _canonical_document = _canonical_row.get("document") or {}
        self.canonical_pieces = relocate_pieces(
            self.served_text,
            _canonical_document.get("pieces") or [],
            paragraph_fallback=True,
        )

    def _suggestions_and_verdicts(self) -> None:
        from services.ideal_decision_ledger import load_ledger
        from services.star_verdicts import (
            filter_user_suggestions, released_user_verdicts,
        )
        db = self.db
        self.sugs = db.get_moment_suggestions_by_arc(self.arc_id) or {}
        self.ledger = load_ledger(db, self.arc_id)
        self.verdicts = db.get_star_verdicts_by_snippet_ids(
            list(self.sugs.keys())) if self.sugs else {}
        # BLIND COACH / publish boundary: a saved coach verdict is still
        # private review state. It can suppress or supersede user feedback
        # only after that snippet's take has been published.
        self.released_verdicts = released_user_verdicts(
            self.verdicts, self.pieces,
            db.takes.get_arc_sessions(self.arc_id) or [])
        self.user_sugs = filter_user_suggestions(
            self.sugs, self.released_verdicts)

    def _applied_map(self) -> None:
        # The master document spans takes: feed EVERY distinct origin
        # session, not the doc-level take_session_id (which is None
        # under the master flag and starved the applied map — review
        # findings #12/#16).
        doc = self.doc
        _sess_ids = {p.get("take_session_id")
                     for p in (doc.get("pieces") or [])
                     if p.get("take_session_id")}
        if doc.get("take_session_id"):
            _sess_ids.add(doc.get("take_session_id"))
        self.applied = [k for k, v in self.deps.applied_map(
            sorted(_sess_ids)).items() if v]

    def _emphasis_key_phrases(self) -> None:
        # T3 (founder 2026-07-23): an emphasis star bolds only its
        # KEY-PHRASE sub-span, not the whole fragment. The signal is the
        # snippet's say-it-stronger upgrade wordings — bulk-read once for
        # the emphasize snippets only (bounded; get_snippets_by_ids added
        # #232), never a per-snippet storm. Best-effort → no narrowing
        # falls back to the whole fragment (today's behavior).
        from services.tracked_changes import (
            key_phrases_from_say_it_stronger,
        )
        _emph_ids = [k for k, v in (self.user_sugs or {}).items()
                     if isinstance(v, dict)
                     and v.get("kind") == "emphasize"]
        if _emph_ids:
            for _srow in (self.db.get_snippets_by_ids(_emph_ids) or []):
                _phr = key_phrases_from_say_it_stronger(
                    _srow.get("say_it_stronger"))
                if _phr:
                    self.kp_by_snip[str(_srow.get("id"))] = _phr

    def _build_candidates(self) -> None:
        from services.tracked_changes import (
            build_coach_revision_changes, build_tracked_changes,
        )
        self.changes = build_tracked_changes(
            self.served_text, self.pieces, self.user_sugs,
            applied=self.applied, key_phrases_by_snippet=self.kp_by_snip)
        self.changes.extend(build_coach_revision_changes(
            self.served_text, self.pieces, self.sugs, self.ledger,
            self.released_verdicts))
        self.review_sid = str(
            self.take_session_id or self.doc.get("take_session_id") or "")

    def _current_take_confident_voice(self) -> None:
        # REQUIRED CURRENT-TAKE CONFIDENT VOICE (founder 2026-08-26).
        # The canonical words may stay unchanged while Take 2/3 supplies a
        # new delivery. Build one acoustic evaluation from that exact Take
        # and route it to the corresponding canonical slide. Playback is the
        # evidence; a span marked slide_route is navigation only and is never
        # presented as words the user said. Historical confident moments are
        # excluded from this Take's immutable set.
        from services.take_feedback_candidates import (
            current_take_confident_voice_candidate,
        )
        from services.transcript_document import build_transcript_document
        _answered_confidence = {
            str(row.get("snippet_id"))
            for row in (self.db.list_owner_voice_album_routes(
                str(self.arc_id)) or [])
            if isinstance(row, dict) and row.get("snippet_id")
        }
        self.review_doc = build_transcript_document(
            self.arc_id, database=self.db, session_id=self.review_sid)
        _review_cv, self.review_evidence_piece = \
            current_take_confident_voice_candidate(
                self.served_text,
                canonical_pieces=(self.canonical_pieces or self.pieces),
                take_document=self.review_doc,
                suggestions=self.user_sugs,
                excluded_snippet_ids=_answered_confidence,
            )
        self.changes = [
            c for c in self.changes
            if not (isinstance(c, dict)
                    and c.get("source") == "confident_voice"
                    and str(c.get("take_session_id") or "")
                    != self.review_sid)
        ]
        if _review_cv is not None:
            # One suggestion row owns one identity. Replace any direct
            # relocation of the same snippet with the explicit Take-scoped
            # candidate, then put the reserved family at the front of the
            # Manager pool.
            self.changes = [
                c for c in self.changes
                if not (isinstance(c, dict)
                        and c.get("source") == "confident_voice")
            ]
            self.changes.insert(0, _review_cv)

    def _praise_playback(self) -> None:
        # ── HEAR IT (founder 2026-08-15): the praise lane is the ONE lane
        # whose claim is about the SOUND, so it is the one lane that cannot
        # be taken on trust. Playback makes it checkable in one tap. FREE,
        # and deliberately from the free map (`_moment_playback_map` plays a
        # student's own recording ABOVE the paywall, audit 2026-07-18). ONLY
        # the praise device gets it. No player is a smaller loss than no
        # praise. ──
        _praise = [c for c in self.changes
                   if isinstance(c, dict)
                   and (c.get("source") == "confident_voice"
                        or c.get("device") == "impeccable")
                   and c.get("take_session_id")]
        if _praise:
            _pb = self.deps.playback_map(
                sorted({c["take_session_id"] for c in _praise}))
            for _c in _praise:
                _row = _pb.get(str(_c.get("snippet_id") or ""))
                if _row and _row.get("snippet_audio_ref"):
                    _c.update(_row)

    def _upgrade_changes(self) -> None:
        # Block-level upgrade offers — the master model's cross-take lane.
        from services.master_document import upgrade_changes
        self.changes.extend(
            upgrade_changes(self.arc_id, self.served_text, self.db))

    def _block_additions(self) -> None:
        # MATERIAL RECOVERY, a separate lane on purpose. A candidate block
        # is a decked slide the master has never seen, carrying the words
        # the speaker actually said over it. It is NOT a span-anchored
        # edit — there is nothing in the document to anchor to — and while
        # it was forced into the `changes` shape as a zero-width `insert`
        # it reached nobody at all.
        from services.master_document import block_additions
        self.additions = block_additions(
            self.arc_id, self.served_text, self.db)

    def _prior_take(self) -> None:
        # ── CROSS-TAKE DISCERNMENT (founder decision 2026-07-20 #4):
        # where the PREVIOUS take said the same thing better, its wording
        # comes back as an approvable change on this document. The
        # ranking blend does the judging (L2 untouched); a fragment the
        # student already decided on is never re-offered. ──
        from services.transcript_document import build_transcript_document
        _prev = None if self.master_on else self.deps.previous_spoken_session(
            self.arc_id, self.doc.get("take_session_id"))
        if _prev:
            from services.prior_take_changes import (
                build_prior_take_changes,
            )
            from services.ideal_decision_ledger import load_ledger
            _prev_doc = build_transcript_document(
                self.arc_id, database=self.db, session_id=_prev)
            if _prev_doc:
                # ONLY cross-take decisions suppress a cross-take
                # offer — a star-lane decision on the same snippet
                # must not silence it (review finding).
                _decided = {
                    str(r.get("snippet_id"))
                    for r in (load_ledger(self.db, self.arc_id) or [])
                    if r.get("snippet_id")
                    and r.get("source") == "prior_take"
                }
                self.changes.extend(build_prior_take_changes(
                    {"text": self.served_text, "pieces": self.pieces},
                    _prev_doc, database=self.db, decided_ids=_decided))

    def _feedback_set_and_fallbacks(self) -> None:
        # ── THE GATE'S INPUT. THE SESSION KEY is not doc-level: under the
        # master flag `doc["take_session_id"]` is None (review findings
        # #12/#16), which would make `is_withheld` short-circuit to False
        # and every arm row carry an empty session_id. The caller passes
        # the arc's latest spoken take instead: the take this arbitration
        # is about. ──
        from services.intervention_candidates import feedback_family_of
        from services.take_feedback_set import (
            load_feedback_set, snippet_ids_by_family,
        )
        self.arm_sid = self.review_sid
        # Classify the COMPLETE pool before selection, then add only honest
        # weak fallbacks for genuinely absent text lanes. Fallbacks are
        # exact document slices; they invent neither lexical content nor
        # certainty. This full pool, not merely the winners, is snapshotted
        # for later ranking evaluation.
        self.feedback_set = (
            load_feedback_set(self.db, str(self.arc_id), self.arm_sid)
            if self.take_contract_on and self.arm_sid else None
        )
        if self.take_contract_on and self.arm_sid:
            for _candidate in self.changes:
                if not isinstance(_candidate, dict):
                    continue
                _family = feedback_family_of(_candidate)
                if _family:
                    _candidate["feedback_family"] = _family
            # Text-lane fallback provenance must not move when the owner
            # answers a Confident Voice card. Use the exact family clips
            # from an existing immutable set; for a new set use the first
            # persisted source piece, whose identity is stable across GETs.
            self.frozen_family_snippets = snippet_ids_by_family(
                (self.feedback_set or {}).get("selected_keys"))
            _current_doc = self.review_doc
            _candidate_sid = next((
                p.get("snippet_id")
                for p in ((_current_doc or {}).get("pieces") or [])
                if isinstance(p, dict) and p.get("snippet_id")
            ), None)
            _rewrite_sid = self.frozen_family_snippets.get(
                "rewrite_clarity", _candidate_sid)
            from services.take_feedback_manager import (
                evidence_backed_rewrite_candidates,
                ensure_required_families,
                exposure_snapshot,
            )
            # Structural deletion scars are a real candidate lane, not an
            # emergency fallback. Add the complete exact-text pool before
            # the Manager ranks it, so the presence of any weaker model
            # rewrite cannot suppress an obvious word-preserving repair.
            self.changes.extend(evidence_backed_rewrite_candidates(
                self.served_text,
                take_session_id=self.arm_sid,
                snippet_id=_rewrite_sid,
            ))
            self.changes = ensure_required_families(
                self.served_text,
                self.changes,
                take_session_id=self.arm_sid,
                snippet_id=_candidate_sid,
                snippet_ids_by_family=self.frozen_family_snippets,
            )
            self.feedback_exposure = exposure_snapshot(self.changes)
        else:
            self.feedback_exposure = []

    def _v3_shadow(self) -> None:
        # TAKE FEEDBACK V3 SHADOW. A real, founder-scoped comparison write
        # over the complete current-Take inventory; not the serving path and
        # it cannot create a rendered exposure. Default OFF; ML/data reviews
        # these frames before any user-visible activation. Shadow evaluation
        # can never darken the current feedback product.
        from services.take_feedback_policy_v3 import (
            POLICY_VERSION as V3_POLICY_VERSION,
            build_shadow_frame,
            dark_enabled,
        )
        from services.transcript_document import build_transcript_document
        db = self.db
        _arm_sid = self.arm_sid
        _v3_session = (
            db.v2_get_session_by_id(_arm_sid) or {}
            if _arm_sid else {}
        )
        _v3_principal_id = _v3_session.get("owner_principal_id")
        if _arm_sid and dark_enabled(_v3_principal_id):
            _v3_take_index = _v3_session.get("take_index")
            _v3_doc = self.review_doc
            if not isinstance(_v3_doc, dict):
                _v3_doc = build_transcript_document(
                    self.arc_id, database=db, session_id=_arm_sid)
            _v3_frame = build_shadow_frame(
                take_document=_v3_doc,
                snippets=db.get_snippets_by_session(_arm_sid) or [],
                suggestions=self.user_sugs,
                feedback_candidates=self.changes,
                take_index=_v3_take_index,
                expected_recording_id=_v3_session.get("recording_1_id"),
            )
            if _v3_frame is not None:
                _v3_saved = db.record_take_feedback_policy_v3_shadow(
                    arc_id=str(self.arc_id),
                    take_session_id=_arm_sid,
                    recording_id=str(_v3_frame["recording_id"]),
                    acquisition_principal_id=str(_v3_principal_id),
                    owner_user_id=str(self.user_id),
                    take_index=int(_v3_frame["take_index"]),
                    policy_version=V3_POLICY_VERSION,
                    frame=_v3_frame,
                    frame_hash=_v3_frame["frame_hash"],
                )
                if not _v3_saved or _v3_saved.get("outcome") != "stored":
                    logger.warning(
                        "take feedback v3 dark frame not stored "
                        "arc=%s take=%s", self.arc_id, _arm_sid,
                    )

    def _immutable_membership(self) -> None:
        # IMMUTABLE TAKE MEMBERSHIP (founder 2026-08-26). The first complete
        # Manager result is claimed in the database; every later GET may only
        # rebuild those identities. Playback URLs refresh and decided items
        # disappear, but accepting item one can never reveal item four.
        from services.take_feedback_set import filter_candidates_to_selected
        self.learning_presentations = {}
        self.feedback_response_count = 0
        if self.feedback_set is None:
            return
        self.changes = filter_candidates_to_selected(
            self.changes, self.feedback_set["selected_keys"])
        self.response_rows = self.db.list_take_feedback_self_reports(
            self.arm_sid, str(self.user_id))
        self.log.run("changes.decision_backfill", self._decision_backfill)
        _responded_ids = {
            str(row.get("feedback_id")) for row in self.response_rows
            if isinstance(row, dict) and row.get("feedback_id")
        }
        self.feedback_response_count = len(_responded_ids)
        if _responded_ids:
            self.changes = [row for row in self.changes
                            if str(row.get("id") or "") not in _responded_ids]

    def _decision_backfill(self) -> None:
        # DECISION BACKFILL-ON-READ. A compatibility response may have
        # landed during the brief backend-first window before migration
        # 0294 existed. Because that legacy response is first-write-final,
        # the user cannot safely be asked to tap it again. Rebuilding the
        # typed canonical decision from its explicit family/response is
        # deterministic and idempotent; ambiguous editor-open actions
        # intentionally remain unresolved.
        from services.feedback_data_contract import (
            canonical_feedback_decision,
        )
        db = self.db
        _decision_session = db.v2_get_session_by_id(self.arm_sid) or {}
        if _decision_session.get("project_id"):
            for _response_row in self.response_rows:
                if not isinstance(_response_row, dict):
                    continue
                _canonical_decision = canonical_feedback_decision(
                    take_id=self.arm_sid,
                    rater_id=str(self.user_id),
                    feedback_id=str(
                        _response_row.get("feedback_id") or ""),
                    feedback_family=str(
                        _response_row.get("feedback_family") or ""),
                    response=str(
                        _response_row.get("response") or ""),
                    candidate_id=_response_row.get("candidate_id"),
                    feedback_membership_id=_response_row.get(
                        "feedback_membership_id"),
                    feedback_exposure_id=_response_row.get(
                        "feedback_exposure_id"),
                )
                if _canonical_decision is not None:
                    db.record_canonical_feedback_decision(
                        project_id=str(
                            _decision_session["project_id"]),
                        take_id=self.arm_sid,
                        rater_id=str(self.user_id),
                        decision=_canonical_decision,
                    )

    def _select(self) -> None:
        # THE TAKE'S SPENT BUDGET (founder 2026-08-10: "each feedback needs
        # to be there; full and end to end and waiting; not that it appears
        # once the other is accepted"). Decided interventions keep their
        # slots: the count rides into the gate, which subtracts it from
        # the frozen three, so the set on screen is chosen once and only
        # shrinks. A count miss reads 0 and degrades to per-read arbitration.
        from services.intervention_candidates import select as _select
        from services.intervention_spend import (
            spent_by_paragraph, spent_count, style_spend,
        )
        # THE STYLE LANE'S OWN LEDGER (founder 2026-08-12). Its ≤3-per-take /
        # ≤2-per-slide cap is cumulative like the budgeted one, so it needs
        # the decisions the two reads above deliberately exclude. One read,
        # both numbers — this lands on the polled ideal-text GET.
        from services.part_acoustics import current_focus
        db = self.db
        arc_id = self.arc_id
        user_id = self.user_id
        _arm_sid = self.arm_sid
        served_text = self.served_text
        _style_spent = style_spend(db, arc_id, _arm_sid, served_text)
        # SINGLE-POINT FOCUS (founder 2026-08-12): the one paragraph feedback
        # is routed to until it comes onboard. None on cold start — no
        # baseline, a first take, or a document whose worst part is already
        # at the speaker's own level — and None means "behave exactly as
        # before", never "suppress everything".
        self.sel = _select(
            self.changes, user_id=user_id,
            session_id=_arm_sid,
            # Under the immutable three-family contract, only an explicit
            # self-report consumes a frozen slot. The legacy mutation
            # endpoint may also write a spend row for Apply/Keep; counting
            # both would make one action look like two resolved items.
            decided_count=(
                self.feedback_response_count if self.take_contract_on
                else spent_count(db, arc_id, _arm_sid)
            ),
            focus_part_id=current_focus(arc_id, user_id, database=db),
            # PER SLIDE, UP TO 1. The served text is the unit map: one
            # paragraph per slide, and the paragraph is the chunk the
            # student decides on. `decided_count` rides along untouched so
            # a caller without the text still gets the flat cap.
            served_text=served_text,
            spent_by_paragraph=spent_by_paragraph(
                db, arc_id, _arm_sid, served_text),
            # Historical style spend remains a separate ledger lane, but
            # its count is subtracted before the current whole-Take
            # exact-three selection. This preserves provenance without
            # granting style an extra allowance.
            style_decided_count=(
                0 if self.take_contract_on else _style_spent["count"]
            ),
            style_spent_by_paragraph=_style_spent["by_paragraph"],
            mvp_feedback_contract=self.take_contract_on,
            # R1 gen-3 — the layer filter runs inside the gate, BEFORE the
            # budget: an open part takes everything; a locked part takes
            # the STYLE LANE (bold only) plus a pending Confident Voice.
            # Both still enter the same whole-Take exact-three selection
            # after admissibility.
            parts=self.deps.locked_parts(arc_id, user_id, served_text))
        self.changes = self.sel["changes"]
        # Style has a distinct payload only because it has a distinct
        # action; its membership was already selected inside the same
        # frozen Take set. It is span-verified against the same served text.
        self.styles = self.sel.get("style_changes") or []

    def _evidence_coordinates(self) -> None:
        # Exact evidence coordinates are part of the feedback item, not an
        # optional UI convenience. Verbal feedback stops at text evidence;
        # only Confident Voice carries playback. A row whose project/take/
        # slide/paragraph cannot be proven is withheld rather than guessed.
        _evidence_pieces = [
            p for p in [
                self.review_evidence_piece,
                *self.canonical_pieces,
                *self.pieces,
            ] if isinstance(p, dict)
        ]
        evidence_args = {
            "arc_id": self.arc_id,
            "served_text": self.served_text,
            "pieces": _evidence_pieces,
        }
        self.changes = self.deps.with_evidence_coordinates(
            self.changes, **evidence_args)
        self.styles = self.deps.with_evidence_coordinates(
            self.styles, **evidence_args)

    def _practice_offer(self) -> None:
        # OPTIONAL CONFIDENT VOICE MICRO-PRACTICE. This runs only after the
        # Feedback Manager has selected the Take's final three interactions,
        # so the exercise cannot become a fourth card or bypass the
        # manager's feedback mix. It annotates at most one already-selected
        # Confident Voice row; no new intervention is created. Missing
        # migration/config is a clean no-offer, never a reason to lose the
        # feedback itself.
        from services.confident_voice_practice import attach_exercise_offer
        self.changes = attach_exercise_offer(
            self.changes, take_session_id=self.arm_sid, database=self.db)

    def _span_checks(self) -> Optional[dict]:
        from services.tracked_changes import verify_changes
        served_text = self.served_text
        if self.styles and not verify_changes(served_text, self.styles):
            self.log.note("changes.style_span_check", "span_check_failed")
            self.styles = []
        # Additions ride OUTSIDE the budget and outside the span check —
        # they have no span. Absent when there are none, so the FE draws
        # nothing rather than an empty section. See
        # master_document.block_additions for why they are not arbitrated.
        self.add = {"additions": self.additions} if self.additions else {}
        if not verify_changes(served_text, self.changes):
            self.log.note("changes.span_check", "span_check_failed")
            from services.take_feedback_manager import strip_internal_evidence
            self.styles = strip_internal_evidence(self.styles)
            return {
                "changes": [],
                **self.add,
                **({"style_changes": self.styles} if self.styles else {}),
            }
        return None

    def _claim_or_filter(self) -> None:
        # Claim only the FINAL, coordinate-proven, span-verified rows. The
        # set spans both the budgeted and style lanes and is therefore
        # capped at three for the whole Take. A set without Confident Voice
        # is refused — the required evaluation cannot be silently replaced
        # by a third rewrite. On a concurrent first open, the database
        # returns the one winner and this response immediately conforms.
        from services.take_feedback_set import (
            claim_feedback_set, filter_to_selected, has_required_families,
            selected_keys,
        )
        db = self.db
        if self.feedback_set is not None:
            self.changes = filter_to_selected(
                self.changes, self.feedback_set["selected_keys"])
            self.styles = filter_to_selected(
                self.styles, self.feedback_set["selected_keys"])
        elif self.take_contract_on and self.arm_sid:
            self.session = db.v2_get_session_by_id(self.arm_sid) or {}
            _take_index = self.session.get("take_index")
            _version_int = (
                self.review_version if isinstance(self.review_version, int)
                and not isinstance(self.review_version, bool) else _take_index
            )
            _combined = [*self.changes, *self.styles]
            _keys = selected_keys(_combined)
            if (not isinstance(_take_index, int)
                    or isinstance(_take_index, bool)
                    or _version_int != _take_index
                    or not has_required_families(_keys)):
                logger.error(
                    "feedback set not claimable arc=%s take=%s index=%s "
                    "version=%s families=%s",
                    self.arc_id, self.arm_sid, _take_index, _version_int,
                    [key.get("feedback_family") for key in _keys])
                self.log.note("changes.feedback_set_claim", "not_claimable")
                self.changes, self.styles = [], []
            else:
                self.feedback_set = claim_feedback_set(
                    db,
                    arc_id=str(self.arc_id),
                    owner_user_id=str(self.user_id),
                    take_session_id=self.arm_sid,
                    take_index=_take_index,
                    review_version=_version_int,
                    changes=_combined,
                )
                if self.feedback_set is None:
                    logger.error(
                        "feedback set claim failed arc=%s take=%s",
                        self.arc_id, self.arm_sid)
                    self.log.note("changes.feedback_set_claim",
                                  "claim_failed")
                    self.changes, self.styles = [], []
                else:
                    from services.take_feedback_manager import POLICY_VERSION
                    _selected_ids = {
                        str(key.get("id") or "")
                        for key in self.feedback_set["selected_keys"]
                    }
                    for _snapshot_row in self.feedback_exposure:
                        _snapshot_row["selected"] = (
                            str(_snapshot_row.get("id") or "")
                            in _selected_ids
                        )
                    db.insert_take_feedback_exposure(
                        arc_id=str(self.arc_id),
                        take_session_id=self.arm_sid,
                        review_version=_version_int,
                        policy_version=POLICY_VERSION,
                        candidate_set=self.feedback_exposure,
                        selected_keys=self.feedback_set["selected_keys"],
                    )
                    self.changes = filter_to_selected(
                        self.changes, self.feedback_set["selected_keys"])
                    self.styles = filter_to_selected(
                        self.styles, self.feedback_set["selected_keys"])

    def _canonical_dual_write(self) -> None:
        # CANONICAL DUAL-WRITE / BACKFILL-ON-READ. Deliberately runs for both
        # a newly claimed compatibility set and an already frozen set. During
        # a backend-first rollout the canonical migration may be briefly
        # unavailable on the first GET; limiting this write to the claim
        # branch would then leave a permanent provenance hole because the
        # compatibility set is insert-once. The canonical RPC is itself
        # idempotent, so every later read safely ensures parity without
        # changing membership or user-visible behavior.
        from services.feedback_data_contract import (
            build_feedback_exposure_bundle, canonical_feedback_decision,
        )
        from services.take_feedback_manager import POLICY_VERSION
        from services.transcript_document import build_transcript_document
        db = self.db
        arc_id = self.arc_id
        _arm_sid = self.arm_sid
        user_id = self.user_id
        _canonical_session = self.session
        if not isinstance(_canonical_session, dict):
            _canonical_session = db.v2_get_session_by_id(_arm_sid) or {}
        _selected_ids = {
            str(key.get("id") or "")
            for key in self.feedback_set["selected_keys"]
        }
        for _snapshot_row in self.feedback_exposure:
            _snapshot_row["selected"] = (
                str(_snapshot_row.get("id") or "")
                in _selected_ids
            )
        _canonical_doc = self.review_doc
        if not isinstance(_canonical_doc, dict):
            _canonical_doc = build_transcript_document(
                arc_id, database=db, session_id=_arm_sid)
        _canonical_bundle = build_feedback_exposure_bundle(
            session=_canonical_session,
            transcript_document=_canonical_doc,
            served_text=self.served_text,
            candidates=self.feedback_exposure,
            selected_keys=self.feedback_set["selected_keys"],
            manager_rules_version=POLICY_VERSION,
        )
        if _canonical_bundle is None:
            logger.warning(
                "canonical feedback bundle unavailable "
                "arc=%s take=%s", arc_id, _arm_sid,
            )
            return
        _canonical_result = db.record_canonical_feedback_exposure(
            _canonical_bundle)
        if _canonical_result is None:
            logger.warning(
                "canonical feedback dual-write missing "
                "arc=%s take=%s", arc_id, _arm_sid,
            )
            return

        def _prepare_presentations() -> None:
            from services.learning_exposures import (
                prepare_feedback_presentations,
            )
            self.learning_presentations = (
                prepare_feedback_presentations(
                    database=db,
                    bundle=_canonical_bundle,
                    actor_id=str(user_id),
                    delivery_mode="canary",
                )
            )
        # The feedback remains a valid product result, but it is not
        # silently counted as exposed learning data. Readiness reports the
        # missing ACK coverage.
        self.log.run("changes.learning_presentations", _prepare_presentations)
        # Selection and exposure are separate durable stages: the first
        # proves which three won, the second proves the complete
        # selected/unselected ledger committed.
        from services.processing_stages import recorder_for_take
        _feedback_stage_recorder = recorder_for_take(
            database=db,
            session=_canonical_session,
            input_provenance={
                "candidate_set_id": _canonical_bundle["candidate_set_id"],
                "input_hash": _canonical_bundle["input_hash"],
            },
        )
        if _feedback_stage_recorder is not None:
            _feedback_stage_recorder.record(
                "manager_selection", "succeeded",
                output=self.feedback_set["selected_keys"],
            )
            _feedback_stage_recorder.record(
                "exposure", "succeeded",
                output={
                    "candidate_set_id": _canonical_result.get(
                        "candidate_set_id"),
                    "candidate_count": len(
                        _canonical_bundle["candidates"]),
                    "selected_count": 3,
                },
            )
        # If this GET just repaired a missing canonical exposure, replay any
        # already-final compatibility responses now as well; one reopen
        # reaches parity.
        for _response_row in self.response_rows or []:
            if not isinstance(_response_row, dict):
                continue
            _canonical_decision = canonical_feedback_decision(
                take_id=_arm_sid,
                rater_id=str(user_id),
                feedback_id=str(
                    _response_row.get("feedback_id") or ""),
                feedback_family=str(
                    _response_row.get("feedback_family") or ""),
                response=str(
                    _response_row.get("response") or ""),
                candidate_id=_response_row.get("candidate_id"),
                feedback_membership_id=_response_row.get(
                    "feedback_membership_id"),
                feedback_exposure_id=_response_row.get(
                    "feedback_exposure_id"),
            )
            if _canonical_decision is not None:
                db.record_canonical_feedback_decision(
                    project_id=str(
                        _canonical_session["project_id"]),
                    take_id=_arm_sid,
                    rater_id=str(user_id),
                    decision=_canonical_decision,
                )

    def _first_client_feedback(self) -> None:
        # ALLOWLISTED FEEDBACK V3 SERVICE. A fresh calculation over the
        # complete current-Take pool, not a conversion of the dark frame.
        # Any missing snapshot, provenance, database contract or exact N1
        # dependency returns None and preserves the working legacy response.
        # The frontend flag remains presentation-only; both backend and DB
        # authority are independently required by the called service RPCs.
        from services.mlc3_first_client_feedback import (
            prepare_first_client_feedback,
        )
        from services.transcript_document import build_transcript_document
        db = self.db
        _arm_sid = self.arm_sid
        _service_session = db.v2_get_session_by_id(_arm_sid) or {} \
            if _arm_sid else {}
        _service_doc = self.review_doc
        if not isinstance(_service_doc, dict) and _arm_sid:
            _service_doc = build_transcript_document(
                self.arc_id, database=db, session_id=_arm_sid,
            )
        _service_rows = prepare_first_client_feedback(
            database=self.deps.first_client_repository,
            session=_service_session,
            take_document=_service_doc,
            served_text=self.served_text,
            snippets=(
                db.get_snippets_by_session(_arm_sid) or []
                if _arm_sid else []
            ),
            suggestions=self.user_sugs,
            feedback_candidates=self.feedback_exposure,
            owner_user_id=str(self.user_id),
        )
        if _service_rows is not None:
            self.changes = _service_rows
            self.styles = []

    def _finish(self) -> dict:
        from services.take_feedback_manager import strip_internal_evidence
        changes = self.changes
        _styles = self.styles
        # THE EXPERIMENT'S RECORD — after the span check on purpose: a row
        # stamped surfaced=True for a serve the guard then zeroed would
        # claim notes the student never saw. Only when the arms actually
        # ran: rows written with the controls inert would stamp the policy
        # (gamma, withhold_rate) as if an assignment had happened when none
        # did.
        if ((changes or _styles) and self.sel.get("controls")
                and self.sel.get("result") is not None):
            self.deps.record_arms(self.sel["result"], self.arm_sid,
                                  self.user_id)
        changes = strip_internal_evidence(changes)
        _styles = strip_internal_evidence(_styles)
        for _visible_row in [*changes, *_styles]:
            _visible_key = str(_visible_row.get("id") or "")
            _packets = self.learning_presentations.get(_visible_key) or []
            if _packets:
                _visible_row["learning_exposures"] = _packets
        _style = {"style_changes": _styles} if _styles else {}
        return {"changes": changes, **self.add, **_style}


def build_changes_block(arc_id, served_text, user_id="", take_session_id="",
                        review_version=None, *, deps: ChangesDeps,
                        degradation: Optional[DegradationLog] = None) -> dict:
    """The `changes` block — {} when the Living Transcript flag is off, so
    the key is simply ABSENT and the FE keeps rendering today's star layer.

    ``degradation`` is the request's log; the route passes its own so the
    payload carries one `degraded` list. Without one (the internal callers
    and the tests), the block owns a log and appends `degraded` itself.
    """
    own_log = degradation is None
    log = degradation if degradation is not None else DegradationLog(READ_PATH)
    run = _ChangesRun(arc_id, served_text, user_id, take_session_id,
                      review_version, deps, log)
    try:
        result = run.execute()
    except Exception as error:
        # The whole block fell back (it used to vanish with one log line):
        # the FE renders the star layer, and now knows why the changes are
        # missing.
        log.record("changes", error)
        result = {}
    if own_log:
        result = {**result, **log.payload()}
    return result
