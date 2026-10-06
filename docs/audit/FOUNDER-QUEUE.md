# Founder queue (from LEDGER.md)

Every ledger row that waits on you, grouped. Rows marked **?** also carry a question. Answer by row ID; the full row is in `LEDGER.md`.

## 1 · Questions first (rows I could not grade without you)

- **N17** — Is this service still wanted, or should it be deleted like the other retired monitors?
- **N20** — Was production's writer hand-patched to accept frame-v5? Only a read-only production query can tell.
- **B1.1** — Whether production's record_take_feedback_policy_v3_shadow_v3 was hand-updated to accept frame-v5 (migrations on main say no; only prod data can confirm) / Whether 'every candidate' includes the verbal (rewrite/praise) inventories or only Confident Voice clips
- **B1.2** — Is the 20% drawn from all snippets or only lineage-valid/blocked ones / Rounding rule (ceil/floor/min 1)
- **B1.3** — S mapping from voice-confidence [-1,1] to [0,1]: (s+1)/2, or band-based? / Hedging and filler as rates: per word, per 100 words, capped how? / 'Judge spread' with only the machine judge in Phase 1 is undefined (store null?) / Which 'LLM topic cohesion': snippet_stickiness composite (within-snippet) or the session stickiness metric (services/stickiness.py, fixation)?
- **B1.4** — 'From Stop' needs a client clock: is the FE stop timestamp acceptable, or server receive time?
- **B1.4b** — Which coach answers count: settled quorum only, or any single blind coach label? / Does In-between count toward 'Yes' (Q1 0.5) for the 7-in-10?
- **B1.5** — Paragraph identity = part id (breaks on rewording) or Slide index? / Per-paragraph willfidence from random moments only (W1) or all moments of that paragraph? / Threshold for 'rose' (any increase, or a margin)?
- **B1.6** — Which machine reads define 'disagreement' for sureness / Does V4 rank the anchored notes only, or also exercise routing
- **B1.7** — Soft label = share Yes (Q2) or weighted mean with In-between 0.5 (Q1)?
- **B1.8** — Does 'None needs it' count as agreement for the golden set when both pick it? / Which feedback kinds the pick is for (any note, or the rewrite slot only)?
- **B1.9** — 'Yes / No' for a two-version comparison: Yes = which one? / Which threshold splits above/below (reached bar 1.4b, or per-quality W)? / Is the pair two machine variants, or the speaker's words vs a variant?
- **BEXIT** — How 'beats' is decided (margin, minimum n, statistical test)? / How next-Take rise is attributed to V4 picks that were never served (off-policy estimate vs a served A/B)?
- **B2.1** — Is the V3 fallback per Take or per block? O2 cut-off value is open.
- **B2.2** — H2: do more than three orange bars show (which would end the window of three, D8/T11), or does the window stay and 'max 3 paragraphs' simply follow from it? Which recording does H1's question refer to: the reached practice attempt or the Take clip?
- **B2.3** — Is the stack per paragraph per Take, or across Takes?
- **V4 M5** — Brief has no Phase-1 item for the recognizer at all; daily picker teaching vs coach-panel lock C6 'Never daily'?
- **V4 M9** — The 10% coach re-pick (test-retest) after 2-3 weeks is in no brief item.
- **V4 SCR-expicker** — Brief says 'built, dark' but the backend constant is True on main: which is intended?
- **V4 P2** — O1 role list, O2 cut-off open.
- **V4 P3** — The 24b servability fix is on no brief item; is #908 to merge before Phase 1?
- **V4 P4** — 1.1 must extend the shadow frame to every speaker, not only the founder: is that in scope (consent/authorization)?
- **V4 W2** — 1.3 is machine-only: the backup rater, the <10 and >30% rules are in no brief item.
- **V4 FR5** — No brief item writes the lock amendment.
- **V4 H1** — Which recording does the answer refer to?
- **V4 H2** — Does 'other paragraphs keep their orange bar' retire the window of three?
- **A003b** (OPEN) — Does 'end-to-end' for B1-5 require real transcription and publish, or are stubs acceptable?
- **A003c** (OPEN) — Does B1-5 require a browser leg, or is the real-database backend test enough?
- **A004b** (FOUNDER) — Should the 2026-09-26 two-tap phrase model be replaced by lock B3's tap-per-word model with a four-tap stop?
- **A005** (FOUNDER) — For phrases saved before the cap, should Recording Mode clamp them to one or two lines (B3-3) or show them whole (B3-2)?
- **A010a** (OPEN) — Can one Slide hold more than one Paragraph, i.e. should a chip show only this paragraph's words from that Take?
- **A014a** (OPEN) — Is CONFIDENT_MOMENT_BUNDLE_V1_ENABLED off by decision, or only waiting on engineering?
- **A014b** (FOUNDER) — With B7 (a settled paragraph has no bar), where should the coach-exercise dot go on an answered paragraph?
- **A018a** (FOUNDER) — How should the back arrow let the speaker change an answer: reopen the judgement step, or a control on the paragraph sheet the design does not draw?
- **A018b** (FOUNDER) — Is the toast firing after the paragraph sheet finishes (lock B5) accepted as meeting journey Q3?
- **A019a** (OPEN) — Should the Lounge 'Practise again' door appear after Take 1 and Take 2 too, not only on Take 3?
- **A021** (FOUNDER) — Do you confirm #606, #607, #613 and #615 as permitted wiring or signed wording under N29.5?
- **A042a** (FOUNDER) — Will you run a period with JUDGEMENT_AFTER_FEEDBACK_ENABLED off to create the before baseline, or drop the before/after comparison from N19?
- **A042b** (FOUNDER) — Does N19 need a founder screen that reads the coach-load report, or is a backend-only report enough?
- **A045** (FOUNDER) — Is MOMENT_SUGGESTIONS_ENABLED on in production, and do you want it on?
- **A050a** (FOUNDER) — Should the Exercise step show an introduction, or is P1-6d retired (designer brief question 1.4)?
- **A052a** (FOUNDER) — Is DONE-1's 'on every block' superseded by lock D8 and 24e-1, so this line should be marked done or reworded?
- **A055a** (FOUNDER) — The follow-up matrix (24f, 35g-2) allows 'nothing now'; should In-between with no card show 'Say it again' instead?
- **A055b** (FOUNDER) — On No or Not sure with a weak read, should the praise riding the paragraph still outrank 'Say it again'?
- **A057** (FOUNDER) — Should the design-locked practise walk show exercise version and prior use (35d), and where?
- **A058** (FOUNDER) — Should the paragraph sheet's History list adopted practice rows, which the design does not draw?
- **A059b** (FOUNDER) — Lock E1 says the model's rewrites reach V3; the test calls it a separate decision. Is it decided, and should LLM rewrites be stamped with evidence?
- **A060** (OPEN) — The backend never files note_written into the library; should a note get the Home (file into library) screen like the other kinds?
- **A063b** (FOUNDER) — Is attaching a personal line to a shared exercise part of the designer session, or can engineering add it to the coach walk now?
- **A072b** (FOUNDER) — How should low volume and flat pitch be asked in the blind error audit (one operational question each)?
- **A074a** (FOUNDER) — Doors 1 and 2 opened before any weekly report ran; does L4 require any action now, or is this accepted?
- **A098b** (FOUNDER) — Should pairs from before #905 be backfilled with a passage and model version so they can count, or stay excluded?
- **A109c** (OPEN) — Does W8 include a frame-to-dataset reader and a confidence trainer, or do those stay outside the authorised slice?
- **A114** (FOUNDER) — Should the speaker's Feedback sheet be moved onto ml_presentations with a post-paint ACK, given it is design-locked?
- **A118** (OPEN) — Who owns the Gate 5 ML/data review, and must it be done retroactively now the cutover has shipped?
- **A123b** (FOUNDER) — Should the corpus copy job be removed or rebuilt to copy text only, given the signed 'Text only. Never your voice.'?
- **A126a** (FOUNDER) — Was seeding training_corpus active at v1.2 (before P5) intended?
- **A128** (FOUNDER) — After N50.2 (project delete removes training copies), is corpus survival on project delete still wanted?
- **A133** (FOUNDER) — After N50.2, should copies still survive project delete under an active yes, or is the survival half retired?
- **A135** (FOUNDER) — After N50.2, does survival of copies under an active yes still stand?
- **A139** (OPEN) — Is the DPIA update an engineering draft or a counsel/founder document?
- **A150a** (FOUNDER) — Should clause 30 be amended to match lock B7, or should a speaker's No still block orange?
- **A151c** (FOUNDER) — Is the Album intro's 'after Take 3' counted per project or per user?
- **A163** (FOUNDER) — With no coach on the panel, what should a moment read weak with a problem fired and no exercise show?
- **A169c** (FOUNDER) — Is the User No / Coach Yes disagreement exercise designed (screen and wording), or does it need a designer session first?
- **A180b** (OPEN) — Does contract 35j accept user action and coach provenance reachable by join, or must they be frozen into the exposure ledger row?
- **A187b** (OPEN) — Are the legacy confidence-review and confidence-agree routes covered by the N49.3 deferral, or may engineering remove them now?
- **A192** (PARKED) — Doc 02's counsel condition is engaged, not pending: should non-founder recording continue until counsel's signed letter arrives?
- **A200c** (FOUNDER) — Is Project Delete off by founder decision, and must it delete coach blind answers when it is turned on?
- **A210b** (OPEN) — Which older tables hold audio, and must they be brought under the 12-month rule or are they being retired?
- **A211b** (FOUNDER) — Is retention schedule v1.4 signed and only waiting to be registered, or does it still need the founder's sign-off?
- **A211c** (FOUNDER) — Should Project Delete ship to meet 'kept until deletion or request', or is account deletion the only request route?
- **A214a** (FOUNDER) — What event or period defines 'the need ends' for each of the four evidence kinds?
- **A217b** (OPEN) — Do feedback_pairs rows count as training copies that must be deleted when training is turned off, or is marking them not releasable enough?
- **A225b** (PARKED) — Should lending open to moments not yet in the Album, or should Privacy §4b be reworded?
- **A228d** (FOUNDER) — Does the Feedback sheet need its own AI-generated mark kind, or is the inherited ideal-text kind accepted?
- **A230** (FOUNDER) — Should a random slice of unseen moments enter the coach queue as K9 asks, given N48.2 Q1 A keeps unseen moments out?

## 2 · V4 build rows waiting on you

- **B1.3** Willfidence-v1 (machine only): per moment S, partial W, four boxes, judge spread, version… — Ingredients exist backend-only, composite absent; S scale mapping and W normalisation are not defined in the brief (O3 partly open).
- **B1.5** Outcome per pick: willfidence on the picked paragraph in Take N vs N+1, matched by… — Needs a decision on what 'paragraph identity' means across Takes (part ids are re-minted on change) and whether all moments or only random ones score the paragraph.
- **B1.6** V4 picker, dark: rank = importance x (1 - S*W) x sureness within what the sound read… — O1 (role list, importance values) and O2 (sureness cut-off) are open; nothing of the ranker exists.
- **B1.8** Coach sheet 'Pick the moment for feedback' (blind; words + audio; 'None needs it');… — New coach screen needs coach-panel-lock wording sign-off and an amendment of lock L6; depends on 1.6 sureness (O1/O2).
- **B1.9** Coach sheet 'Which sounds surer' (Yes / No / Can't tell); queue 40% above threshold, 40%… — Needs O3 (WORDS definitions), coach-panel-lock wording sign-off and a lock amendment for a comparison-pair DPO surface.
- **BEXIT** EXIT GATE: V4 beats V3 on golden-set agreement AND next-Take rise; coverage holds;… — Needs a founder-set definition of 'beats' (margin, sample size) and depends on O1/O2 via 1.6.
- **B2.1** Serve V4 — needs Phase 1 exit + founder switch-on + contract amendment (24/24h)
- **B2.2** New feedback walk (speaker screens; designer session only) — design lock (designer session) + lock/contract amendments + new copy sign-off
- **B2.3** Coach screen 'This paragraph's feedback' (stack of interventions and what the speaker did) — new coach screen + wording need the coach-panel lock
- **B2.4** A coach answer joins the paragraph's stack as its next intervention — changes a design-locked speaker screen and coach-panel lock C3
- **O1** importance role list and values
- **O2** "very low sureness" cut-off for the V3 fallback
- **O3** written definitions for each WORDS dimension; sales anchor

## 3 · Decisions no brief item carries (add a build row, or drop)

- **BG01** Exit-gate evaluator: no item builds the V4-vs-V3 comparison (golden-set agreement AND next-Take rise) or the off-policy evaluation from logged pick chances + 20% random (M7, EXIT GATE).
- **BG02** Coach re-pick ~10% after 2-3 weeks (test-retest, M9) is in no item; 1.8 omits it.
- **BG03** W2 rules (backup rater, <10 moments 'not enough data', >30% dropped 'audio problem') and person-level willfidence / spread aggregation are in no item.
- **BG04** Contract/SPEC/lock amendments (24, 24h, 24e, 29a, 32, SPEC D3/D7/D8/D16/D19, label_quorum rules, coach-panel C3/L6/L9/A-walk, helper-words B2/B5/B6/B8/D8/T11) have no item; brief only says 'founder rules changed'.
- **BG05** Coach-panel lock entries and wording sign-off for 'Pick the moment for feedback', 'Which sounds surer', 'This paragraph's feedback' (FR5) have no item.
- **BG06** Voice Album USER-leg rewiring and exact-recording identity for H1 (voice_album.py reads the answer on the displayed card) is not a named task in 2.2.
- **BG07** Shadow-frame scope: V3 shadow frames are written only for the founder (take_feedback_policy_v3.py:55-66); 1.1 does not say 'for every speaker' nor its authorization path (PLF1 processing authority).
- **BG08** The 24b servability defect fix (HELD #908) that V4 must inherit is on no item.
- **BG09** Re-specifying the coach follow-up matrix routing (35g-2/24e-1 ambiguity from speaker vs machine disagreement) once the speaker's per-attempt judgement stops driving the loop (2.2) is in no item.
- **BG10** M5 'recognizer trained first' has no Phase-1 measurement item for the recognizer itself (all recognizer training is parked in P-b).

## 4 · Contract or lock text that still says the old rule (amend)

- **CA01** CANONICAL_PRODUCT_CONTRACT.md 24 (:150-159 'V3 becomes the served policy') and 24h (:342 'V3 never silently substitutes another policy version'), backend CLAUDE.md F1/L2 'V3 is the served policy', helper-words lock N48.3 Q12 note '47 (V3 serves every Take)' -> FR4/P4/2.1/P2 fallback.
- **CA02** SPEC.md D8 (:39) and §7.2 (:424 'Confidence enters exactly once ... never summed') -> willfidence S=(coach+peer+machine)/3 (FR1, Q1); add KPI carve-out note to label_quorum.py:16 Rule 1 (ledger rule itself unchanged, Q3).
- **CA03** SPEC.md D19 (:55 'CONF-only, no lexical yes/no indicator') and :886 ('never blended into ... confidence') -> willfidence W and 'Which sounds surer' (FR2, 1.9).
- **CA04** SPEC.md D7 (:38 'Machine score at N+1 is banned as a target') and D16 (:47) -> P5/1.5/M9 next-Take machine-measured rise as the picker's teacher.
- **CA05** SPEC.md D3 (:34 'Do not build pair selection, pair-shaped responses, or a pair table') -> P6/1.9 one Yes/No per pair (confirm scope).
- **CA06** label_quorum.py Rule 3 (:311-313 settled-only gold/eval) and quorum-of-two; coach-panel lock L9 ('two blind humans per clip') -> Q2/FR3 soft labels from 3-5 raters for training.
- **CA07** Coach-panel lock L6 / golden_set.py (founder's golden set alone) -> M9 golden = coach and founder agree.
- **CA08** Contract 24e, 24e-1, 29a (:434), 13; helper-words lock B2, B5, B6, B8, D8/T11/B7 -> 2.2 machine fast read decides, helper words on 'reached', interventions 1..n, max 3 paragraphs, H2 bars.
- **CA09** Contract 32 (:522 exact recording) + voice_album.py USER leg -> H1 question after helper words.
- **CA10** Coach-panel lock C3 ('one card per moment') -> 2.2/2.4 intervention stack; A1-A8 / contract 35g-5 -> 2.3 paragraph screen and 1.8/1.9 sheets (FR5).
- **CA11** Contract L3 / clauses 30-31, MLC2-FOUNDATION.md (product actions 'not judgments or supervision') -> FR6 spoken adoption as an inferred signal (when P-d unparks).
- **CA12** Design lock (frontend CLAUDE.md journey Q1 'taps Review feedback') -> 2.2 entry 'tap an orange paragraph' (confirm both entries coexist).

## 5 · Overnight rows

- **N01** (FOUNDER, S1) The backend web deploy of #907 (migration 0429) failed; every further backend merge is paused until it is reverted or fixed.
- **N04b** (FOUNDER, S4) The personalised-practice branch of 0394 has the same always-NULL guard.
- **N06** (FOUNDER, S4) After #905 a coach re-picking a practice answer gets 409 and the walk shows "Couldn't save your answer." instead of the answer that stands.
- **N08** (FOUNDER, S2) The 7-day deletion promise is not kept automatically: completion needs PHASE1_PURGE_EXECUTION_ENABLED, v1.4 registered and the cron.
- **N13** (FOUNDER, S5) The helper-words lock doc's Q8 amendment quotes the wrong Take 1 note; the code matches the design.
- **N18** (FOUNDER, S5) A stray branch hold/b6-coach-reviewed-moment exists on the frontend repo.
- **N20** (CONFIRMED, S4) Every V3 shadow-frame write is refused by the database (code frame-v5, writer accepts only frame-v3), so no shadow frame is ever stored; the code only logs it.

## 6 · Audit rows waiting on you, by kind

### Ops (Railway, Supabase, config) (82)

- **A001** [BE] Neither repo holds the founder's signed helper-words lock PDF; only its sha256 (2024740823...3369) is recorded in the lock doc, and no check has compared a file against it.
- **A043a** [BE] The Privacy/Terms 3.3 policy version 'phase1-2026-10-02' is published in production public.processing_policy_versions.
- **A043b** [BE] Document 02 v1.1 (artifact_kind 'power_score_classification', version '1.1') is registered in production public.processing_legal_artifacts.
- **A043c** [BE] Retention schedule v1.2 (artifact_kind 'retention_schedule', version '1.2') and its rule rows are seeded in production.
- **A045** **?** [BE] Detector praise rows (delivery cues, structural devices) are generated only when MOMENT_SUGGESTIONS_ENABLED is on (config default '0'), so by default no Take carries cue-naming…
- **A052b** [BE] Whether V3 feedback serves for real speakers (rather than returning feedback_status 'failed') can only be settled from production Take data.
- **A053b** [BE] With MOMENT_SUGGESTIONS_ENABLED off, a Take carries at most the one tentative fallback praise, so most Yes answers show no card.
- **A065a** [BE] A scheduled weekly export run cannot be confirmed from code; production ledger_snapshots and pair_releases rows would show it.
- **A070** [BE] Whether the weekly learning job ran on schedule (a ledger_snapshots row for 2026-10-05, cron log 'HTTP 200') cannot be confirmed from code.
- **A073** [BE] Whether the Railway cron service for the weekly learning job exists and runs cannot be confirmed from code.
- **A074b** [BE] A scheduled weekly readiness run still cannot be confirmed.
- **A079** [BE] Whether the production readiness checker reads READY under cutover mode 'founder_canary' cannot be confirmed from code (Monitors panel or cron log).
- **A081** [BE] The Railway service that ran the annotation-export cron may still exist; its deletion cannot be confirmed from code.
- **A082** [BE] The weekly learning job runs on schedule only if a Railway cron service exists with LEARNING_WEEKLY_SECRET and LEARNING_WEEKLY_BACKEND_URL set (secret defaults to '').
- **A083a** [both] The pace panel's pair jars read pairs.<surface>.exportable, so every ledger snapshot stored before 6 Oct (before #905) shows as unknown and no measured rate is shown.
- **A083b** [both] New pace snapshots are written only by the weekly learning job or the founder's Run button on /admin/pace; no other writer exists.
- **A084** [BE] Production has at least one active row in public.research_users (unverified; settle with the given query).
- **A085** [both] The /admin/research drift panel shows only a note because no ledger week with a drift reading has been stored by the weekly job.
- **A086a** [BE] The weekly consent refresh and the voided-release purge are invoked only from the weekly learning job; no scheduled run is evidenced.
- **A086b** [both] Both Door 1 training-consent screens render only when the training-only-v1 policy row exists in production.
- **A087a** [BE] Pair-release exports run only inside the weekly job and no row in public.pair_releases is evidenced.
- **A087b** [BE] With PAIR_RELEASE_SIGNING_KEY empty (its default) the export refuses with why_not 'no signing key'; the prod value is not visible.
- **A093b** [BE] The two MLC-3 monitor cron services still exist on Railway (unverified from code).
- **A094a** [both] Ledger snapshots stored before #905 have no exportable count, so the pace panel reads them as unknown and shows no measured rate.
- **A094b** [both] New pace snapshots come only from the weekly job or the founder's Run button.
- **A095** [both] The research screen's drift panel shows only a note until a weekly-job week with a drift reading exists; the other panels render with pseudonyms only.
- **A096** [BE] The weekly learning job has run in production: public.ledger_snapshots has a row for the week of 2026-10-05 (unverified).
- **A100** [BE] The withdrawal sweep (stored copies, OpenAI copies, later runs, stale reports) runs only inside the weekly job; no scheduled run is evidenced and there are no releases or OpenAI…
- **A101** [BE] Door 2 is open in code for three surfaces, but no export exists because the signing key and a weekly run are not evidenced.
- **A104** [BE] An OpenAI DPA is on file, the production key may fine-tune and the organisation is verified (only the OpenAI dashboard can confirm).
- **A117a** [BE] The five-minute confidence readiness cron runs in production with MLC2_CONFIDENCE_MONITORING_ENABLED=true and alerts (unverified; ops notes report it failing on every deploy).
- **A126a** **?** [BE] The v1.2 retention rules script seeds the training_corpus rule as active, while the spec line says it stays inactive until P5.
- **A126b** [BE] Whether training_corpus and consent-evidence-v1 are active in prod public.data_retention_rules is unknown from code; a DB read settles it.
- **A127a** [FE] Project Delete is not offered to users (PROJECT_DELETE_ENABLED=false in the FE).
- **A127b** [BE] The v1.4 retention rules for the four N14.3 tables are not yet registered in prod, so they do not act.
- **A127c** [BE] Migration 0429 (P1, #907) is on main but not deployed (kept out of the boot path) pending v1.5 signature and registration.
- **A129a** [FE] Project Delete and its cancel are not offered to users although the 7-day self-completing backend is built.
- **A129b** [BE] A project deletion self-completes after 7 days only if the deletion cron, its secret and PHASE1_PURGE_EXECUTION_ENABLED are configured in prod.
- **A130** [FE] The signed line 'A model already trained stays.' ends the account delete confirm but does not appear on any live project delete confirm, because project Delete is off.
- **A131b** [BE] The training_corpus retention rule's prod state is recorded as seeded but not confirmed from the DB.
- **A131c** [FE] The training line is not shown on any project delete confirm because project Delete is off.
- **A132a** [BE] A real project purge stops at review_required because v1.4 rules for take_feedback_exposure, take_feedback_self_report, ideal_text_part_revision and phase1_processing_job_events…
- **A132b** [BE] The v1.5 purge entries (0429, #907) are merged but not deployed, pending v1.5 signature and registration.
- **A138** [both] Project delete request, cancel and signed copy are built but hidden from users until v1.4 is registered and P1 (0429) is deployed.
- **A140a** [BE] v1.4 retention rules are not registered, so P1 cannot finish a real delete.
- **A140b** [BE] P1 (0429) is merged but not deployed, pending v1.5.
- **A140c** [BE] The consent_evidence retention rule's prod state is recorded as seeded (v1.2) but not confirmed from the DB.
- **A141a** [both] The empty Take receipt on deletion is built but has never been produced by a real deletion, since none can finish yet.
- **A143a** [BE] Whether any weekly exercise_script pair release has run in prod is unknown from code; reading pair_releases and ledger_snapshots settles it.
- **A143b** [BE] The release job's secret, signing key and cron are still listed as founder ops steps, not confirmed set.
- **A144** [BE] Whether praise_line and clearer_version pair releases have run in prod is unknown from code; the pair_releases and ledger_snapshots reads settle it.
- **A165** [BE] REASONABLE_CONFIDENCE_ENABLED is not shown to have the same value on web, worker and every cron service (each boot 'gate flags' line), so web-computed V3 may order items…
- **A191** [BE] The doc 01 product-legal approval v1.0 PDF in R2 and its processing_legal_artifacts row are not verified to match sha256 2ca882c4…784a6b.
- **A193** [BE] Doc 02 v1.1 power_score_classification row and R2 object are not verified to match sha256 e00536d0…2ade.
- **A194c** [BE] Doc 03 v1.1 is signed but not uploaded or registered (phase1_register_article_50_v1_1.sql not applied).
- **A195** [BE] The retention schedule v1.0 PDF in R2 is not verified to match sha256 73d078ea…0c69.
- **A196** [BE] Retention schedule v1.2's five data_retention_rules rows and R2 object (b0439d18…f479) are not verified in prod.
- **A197** [BE] The training_only ml_consent_policies row and the training wording PDF in R2 (b1ec620e…1632) are not verified in prod.
- **A198** [BE] Weekly pair releases depend on R2_PAIR_RELEASE_BUCKET, PAIR_RELEASE_SIGNING_KEY, LEARNING_WEEKLY_SECRET and a deployed weekly cron, whose prod state is not verified.
- **A200a** [BE] Coach blind answers are deleted only inside a purge, and account erasure auto-completes only if PHASE1_PURGE_EXECUTION_ENABLED='true' on web and the completion cron runs; prod…
- **A200b** [BE] Until retention schedule v1.4 is registered, a real speaker's erasure stops for manual review on feedback-exposure and Paragraph-revision rows.
- **A200c** **?** [both] Project Delete is off, so deleting a project does not delete coach blind answers.
- **A205** [BE] A voice-album share row is deleted with its Take only inside a purge, which needs PHASE1_PURGE_EXECUTION_ENABLED on and v1.4 registered; with the peer lane off no share row is…
- **A206a** [BE] Listener answers and votes are erased with the listener's account only if PHASE1_PURGE_EXECUTION_ENABLED is on in prod (prod value not visible).
- **A206b** [BE] Until retention schedule v1.4 is registered, account erasure stops for manual review for any listener who also has a Take.
- **A210a** [BE] The 12-month audio clean-up only counts: RETENTION_CLEANER_LIVE is False, and a live run also needs RETENTION_CLEANER_SECRET and a cron service.
- **A211a** [BE] Requested account deletion completes after 7 days only if PHASE1_PURGE_EXECUTION_ENABLED='true' on web and the completion cron runs; neither is visible.
- **A211b** **?** [BE] Until retention schedule v1.4 is registered, every speaker's erasure stops for manual review on feedback-exposure and Paragraph-revision rows.
- **A212** [BE] No running job deletes voice measurements by age; the clean-up that removes them before their audio runs live only when RETENTION_CLEANER_LIVE (False) and the cron service are set.
- **A213b** [BE] Vendor-side log retention (90 days) cannot be confirmed from code; it is a vendor setting.
- **A216** [BE] Provider-held copies are bounded at 30 days only if the OpenAI organisation is set to 30-day retention with training data sharing off; not visible from code.
- **A217a** [BE] Training release files are deleted only by the weekly sweep, which runs only if the weekly cron and LEARNING_WEEKLY_SECRET are set in prod.
- **A219** [both] Policy version phase1-2026-10-02 (Privacy/Terms 3.3) being active in production cannot be confirmed from code; settle by querying processing_policy_versions.
- **A221b** [BE] PLF1_PROCESSING_AUTHORIZATION_MODE=enforce is unverified on web and the cron services.
- **A223** [BE] Enforce mode is confirmed only on the worker; web and each cron service are unverified until each boot log's 'gate flags' line is checked.
- **A228b** [BE] Registration of Article 50 assessment document 03 v1.1 in production is not visible; settle by querying processing_legal_artifacts.
- **A228c** [BE] The active policy publish script (phase1_policy_publish_3_3.sql) still carries a placeholder hash for the Article 50 assessment.
- **A234a** [BE] Automatic deletion completion after 7 days runs only if the Railway cron, DELETION_COMPLETION_SECRET and PHASE1_PURGE_EXECUTION_ENABLED=true are set in prod.
- **A235a** [BE] Whether the active policy records coach_review with lawful basis contract and required_for_core_service TRUE is not visible from code; settle by the given prod query.
- **A241a** [BE] Termination deletes database, R2, provider and dataset artifacts only if DELETION_COMPLETION_SECRET and PHASE1_PURGE_EXECUTION_ENABLED are set on web and the deletion-completion…
- **A243a** [BE] The purge (which applies retention rules) deletes only when PHASE1_PURGE_EXECUTION_ENABLED is on in prod.
- **A245** [BE] The production counts of practice attempts with a coach decision since 2026-10-01 are not known; settle with the three given prod queries.

### Decision (49)

- **A004a** [FE] In the helper-words picker, untapped words grey out only while a single anchor word is picked, not after a run is chosen.
- **A004b** **?** [FE] After a run is chosen in the picker, every word stays tappable and the next tap starts a new run, so a fifth tap is not ignored as lock B3 asks (the four-word cap itself holds on…
- **A018b** **?** [FE] The confirmation toast fires when the paragraph sheet finishes, not immediately after the answer.
- **A020a** [FE] A coach_reviewed moment runs the pre-lock DeckChunkModal ladder (exercise, then judgement, then helper words) instead of the paragraph sheet and the practise screen.
- **A021** **?** [FE] Nothing records which sessions were designer sessions; changes to the locked screens since 5 Oct (#606, #607, #613, #615) came from build sessions as wiring or signed wording.
- **A022b** [FE] A coach_reviewed moment runs the old DeckChunkModal ladder instead of the overlay and the practise screen (same as A020a).
- **A042a** **?** [both] The coach-load report has no before-switch baseline: no moment open/skip was recorded while JUDGEMENT_AFTER_FEEDBACK_ENABLED was off, so before/after cannot be compared.
- **A042b** **?** [FE] No frontend screen calls or renders the coach_load report (be/services/coach_load.py:21).
- **A059b** **?** [BE] test_rewrites_stay_without_evidence calls excluding LLM rewrites 'a separate decision' that no decisions-log entry records, contradicting lock E1.
- **A068a** [BE] No catalogue floor exists: PROPOSED_LINES_SIGNED = False holds off the nine praise lines and three rewrite moves pending the founder's signature.
- **A072b** **?** [BE] Low volume and flat pitch run in shadow but are not in the blind error audit, so they cannot reach READY.
- **A074a** **?** [BE] No weekly readiness report ran before doors 1 and 2 opened on 2026-10-01, contrary to L4's order.
- **A090** [BE] Door 4 is closed in code (MLC2_PROMOTION_ENABLED=False, empty PROMOTION_SURFACES) and no promotion candidate exists; the kill path works open or closed.
- **A092** [BE] low_volume and flat_pitch run in shadow per Take, but can never reach READY because the blind audit asks no question whose Yes answer counts for them, so no promotion migration…
- **A093a** [FE] The FE Confident Moment bundle's exercise panel still calls MLC-3 routes that the backend now answers with 410.
- **A097** [BE] The door constants for Doors 3 and 4 carry no founder sentence and both doors are closed.
- **A098b** **?** [BE] exercise_script pairs created before #905 lack a passage and a model version and are excluded from the 200-pair training count.
- **A107** [BE] No retrain path exists: a run that fails the regurgitation check is failed for good and its pairs never train again.
- **A120** [BE] K9's third selection component (balanced predicted regions) is not implemented and MIN_CLIP_MS is unset pending the founder.
- **A123a** [BE] Nothing writes to the corpus items table (MLC2_TRAINING_CORPUS_COPY_ENABLED is False).
- **A123b** **?** [BE] The (dark) corpus copy job copies audio, contrary to the signed 'Text only. Never your voice.' wording.
- **A128** **?** [BE] No retain_while_training_consented disposition exists; a project purge that meets training-corpus copies stops at review instead.
- **A133** **?** [BE] Corpus survival on project delete (frozen active yes + active rule) is not built; a project purge stops when it meets copies (erasure always deletes).
- **A135** **?** [BE] Copies-survive-project-delete-under-active-yes is not built; a project purge stops on copies (withdrawal and erasure purges exist; no copies exist).
- **A137b** [BE] Q3 (no retraining) has nothing to apply to because door 3 (fine-tuning) is closed.
- **A137c** [BE] Q5 operator confirmation is superseded: deletions self-complete after 7 days per N48.4 Q14 A / Q17 A.
- **A145a** [BE] Door 3 (fine-tune) is closed in code until the founder gives a sentence per surface.
- **A146** [BE] Door 4 (promote to runtime_config) is closed in code and no fine-tuned model exists.
- **A150a** **?** [both] Bar colour follows only the machine's read (B7), so a speaker's No no longer blocks orange; contract clause 30 still says it does.
- **A151a** [both] No reveal is shown to the coach after a judgement is submitted.
- **A151b** [both] The User No / Coach Yes disagreement exercise is not built.
- **A151c** **?** [both] Whether the Album intro triggers after Take 3 per project or per user is undecided.
- **A163** **?** [both] With no coach on the panel, a moment read weak with a problem fired and no exercise shows the rewrite via the page's own rule, which the follow-up matrix does not name.
- **A187a** [both] The legacy credits hook, arc redeem/unlock, retired tier keys and one Best Presentation cache read remain in code pending a founder decision (N49.3).
- **A211c** **?** [FE] Project deletion cannot be requested: PROJECT_DELETE_ENABLED=false in the FE.
- **A213a** [BE] Technical logs older than 90 days are not deleted today: the clean-up's log rule runs only live, and RETENTION_CLEANER_LIVE is False.
- **A214a** **?** [BE] No job deletes authorization, deletion, processor or transparency evidence when its accountability need ends.
- **A214b** [BE] The two proposed retain categories of v1.0 §3b (deletion and transparency evidence) are unconfirmed and absent from schedules v1.4 and v1.5.
- **A215a** [BE] token_ledger/llm_usage rows past five years are only counted, not deleted, because RETENTION_CLEANER_LIVE=False (nothing due before 2032-01-01).
- **A226** [both] POST /coach/training-imports (confidence-only analysis of uploads) always answers 410 PHASE2_DISABLED.
- **A230** **?** [BE] The coach queue for speakers' Takes is a census of surfaced Manager bookmarks (probability 1) with no random exploration slice, so K9's unbiased window does not exist for live…
- **A231** [BE] No live path builds a speaker-disjoint confidence dataset release (MLC2_DATASET_RELEASES_ENABLED=False; confidence_dataset has no non-test caller).
- **A232** [BE] No route, job or script runs the sealed multi-metric release gate; confidence_evaluation is reachable only via the uncalled confidence_rollout.
- **A233** [BE] The off/shadow/limited rollout exists only in an uncalled module; no learned confidence model is served (MLC2_PROMOTION_ENABLED=False).
- **A235b** [BE] Document 01 v1.1 (carrying the coach_review basis) is unsigned and the publish script references it by a placeholder hash.
- **A237b** [BE] Terms 3.3 has no PAdES signature row in SIGNED-ARTIFACTS.md.
- **A239** [both] No FE control ends the service without deleting the account; /terminate's service_termination kind has no caller.
- **A241b** [BE] Rows no active retention rule decides stop an erasure for review until v1.4 is registered and v1.5 is signed and registered.
- **A243b** [BE] The scheduled clean-up only counts due rows; RETENTION_CLEANER_LIVE is False.

### Design lock / designer session (36)

- **A002** [FE] A coach_reviewed moment in DeckChunkModal opens on its exercise and continues the old ladder after the answer (with its own 'Done' screens) instead of handing off to the paragraph…
- **A005** **?** [FE] RecordingRoadmap draws each helper-words cue as a plain paragraph with no line clamp, so a phrase saved before the four-word cap renders as a multi-line block.
- **A006** [FE] A coach_reviewed moment opens the old DeckChunkModal exercise ladder instead of the shared practise screens that rewrite, exercise and plain moments reach.
- **A008a** [FE] No side-by-side check of the overlay, helper-words and practise screens against the three external mocks has been done.
- **A008b** [FE] PractiseSheet draws a full-width 'Practise' pill where the mock draws a round record button.
- **A009** [FE] PractiseSheet draws a full-width 'Practise' pill where the mock draws a round record button (same divergence as A008b).
- **A011** [FE] After its answer, a coach_reviewed moment goes to the old Feedback-sheet ladder instead of the paragraph overlay's two states.
- **A012** [FE] ParagraphSheet's HelperWordsPicker opens with no walk header (‹ Slide N ›) nav, unlike the helper words overlay and the practise picker.
- **A014b** **?** [FE] The coach-exercise mark is drawn only on a waiting (unsettled) paragraph, not on an answered one.
- **A018a** **?** [FE] The back arrow (‹) reopens an answered moment as its paragraph sheet, which shows the answer with no way to re-answer, so the answer cannot be changed.
- **A022a** [FE] ParagraphSheet's helper-words picker opens without the ‹ Slide N › header the lock's mocks draw (same as A012).
- **A025** [FE] No speaker screen renders the coach's shared coach_answer (line, clearer version, note, video); it rides the item unrendered (N45 Q7).
- **A050a** **?** [FE] No speaker component renders practiceExercise.introduction, though idealText.ts maps it.
- **A055a** **?** [FE] On In-between with no exercise, rewrite or praise, practiseCardOf returns null (paragraphOverlay.ts:271) and the sheet shows no 'Say it again' card, only Next.
- **A055b** **?** [FE] On No or Not sure, a praise riding the paragraph is chosen ahead of the plain 'Say it again' moment even when the machine's read is weak (paragraphOverlay.ts:266).
- **A056c** [FE] For a brand-new speaker, 'Say it again' is not shown in every case where no other card applies (see A055).
- **A057** **?** [FE] The live practise walk (ParagraphSheet, PractiseSheet) shows neither the exercise version nor prior use; done-before exists only in DeckChunkModal.tsx:1715.
- **A058** **?** [FE] The backend serves adopted-practice rows in Paragraph history, but the paragraph sheet's History (historyRows) lists only Takes and accepted corrections, not practice.
- **A061** [FE] Coach-shared words (praise line, clearer version, note) and their videos are served on the speaker's item as coach_answer, but no speaker screen renders them; only shared…
- **A062** [FE] Per-moment coach-shared words and their videos are never rendered on the speaker side.
- **A063a** [FE] The coach's personal line per moment is stored and served in coach_answer but no speaker screen renders it.
- **A063b** **?** [FE] The coach walk has no UI to attach a personal line to a shared exercise (coachPanel.ts draftMomentLine has no UI caller).
- **A064** [FE] The speaker sheet's card per moment is never the coach's answer in words; only the machine's matrix card opens.
- **A069** [FE] Coach answers by kind other than the error video (praise lines, clearer versions, their videos) are served as coach_answer but not rendered for the speaker.
- **A078** [FE] Coach word answers are never rendered for the speaker, so Phase 2 DONE ('answer reaches speaker') is not met.
- **A114** **?** [both] The speaker's Feedback sheet does not write ml_presentations or post-paint ml_rendered_exposures, so no rendered exposure exists for a canonical Take.
- **A152** [both] No blind peer ratings exist because the peer lane is off and openLendYourEar has no caller (the Album reads only professional coach labels).
- **A172a** [FE] No speaker screen names the assigned exercise version.
- **A172b** [FE] Prior use (done-before) shows only on the judgement sheet's exercise step; a library exercise opened from the paragraph sheet goes to PractiseSheet, which shows no version and no…
- **A175a** [FE] The coach's shared words (praise line, clearer version, note, video) ride the moment as coach_answer, which no speaker screen maps or renders.
- **A177b** [FE] A coach's shared moment line never reaches the speaker because coach_answer is not rendered.
- **A182** [FE] A coach's clearer version cannot reach the speaker as an accept/reject proposal because coach_answer is not rendered.
- **A183** [FE] Per-moment coach word answers are in the payload as coach_answer but no speaker screen renders them.
- **A184** [FE] The speaker cannot see or accept a coach's clearer version (coach_answer not rendered).
- **A228d** **?** [FE] The Feedback sheet's AI-generated mark uses only the inherited ideal-text kind, not a kind of its own.
- **A229** [both] Only coaches form the blind panel: PEER_LANE_ENABLED is False, the Lend your ear routes answer 404 and no screen calls them (owner exclusion and machine-never-votes hold).

### Copy to sign (17)

- **A013** [FE] The walk end card does not draw the line "Your helper words show while you record." under its title, which the design shows.
- **A020b** [FE] The coach_reviewed DeckChunkModal path shows "Done" and "Practise again" pills where the amended lock says "Next".
- **A052a** **?** [both] The moment question is not asked on every block: at most three moments are open (WINDOW=3), uncoloured moments yield to coloured ones, and a skipped weak moment settles without it.
- **A077a** [FE] The errors page readinessLine says 'named by a coach on N of 30 moments' while N is now coaches' Yes answers in the blind error audit.
- **A077b** [FE] The pace panel jarLabel says 'named by a coach' while the count is now blind-audit Yes answers.
- **A124** [BE] The dark training-corpus copy job (MLC2_TRAINING_CORPUS_COPY_ENABLED, off) copies audio, although signed text-only training (N15) allows only text.
- **A125** [BE] label_provenance CHECKs exist in the training-copy schema, but no training-copy rows exist, so the wall has never been exercised on data.
- **A131a** [BE] The P5 copy job is off and, as built, copies audio, contrary to the signed text-only training wording.
- **A137a** [BE] The Q1 copy job is off and, as built, copies audio, contrary to the signed text-only wording.
- **A169c** **?** [both] No User No / Coach Yes disagreement exercise exists in code.
- **A174b** [FE] No FE code maps practice_exercise.fallback, so the ladder's caption has no screen.
- **A186** [both] The live Terms 3.3 section 2 (terms-3.3.txt:46-60) still describes renewing monthly plans; the replacement 3.4 section 2 is not in the repo.
- **A218a** [BE] ml_consent_snapshots still stop an erasure for manual review; the v1.5 consent-evidence entry (#907) is merged but not deployed and waits for v1.5 to be signed and registered.
- **A234b** [BE] Rows no active retention rule decides stop a deletion for manual review; the v1.5 purge (0429) is merged, not deployed, and inert until v1.5 is registered.
- **A236b** [both] Served Terms 3.3 §2 and §11 describe monthly plans that can no longer be bought; the Terms 3.4 §2 replacement waits for counsel and the founder.
- **A237a** [both] Served Terms 3.3 section 2 (terms-3.3.txt:40-64) describes renewing monthly allowances and paid plans that nothing sells; the 3.4 text is not in the repo.
- **A242a** [BE] Lineage rows are not deleted with the account (they stop erasure for review) until schedule v1.5 is signed and registered.

## 7 · Harness rows X1–X10: approve, change or drop (see LEDGER.md §X)
