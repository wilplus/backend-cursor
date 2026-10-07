# The coach panel redesign · build plan P2 to P7

Written 2026-10-07 (build plan D-CP-1). It turns the locked coach panel
(`docs/FOUNDER-LOCK-coach-panel-redesign-2026-10-06.md`; prototype
<https://claude.ai/artifact/TEBvGMehRF6wXCvJTEYTUA>, copy in
`docs/design/coach-panel-redesign-2026-10-06.html`; decisions log N56, N57,
N62 Q-B7/Q-B12/Q-B13, N63 Q-B14) into pull-request-sized steps. Screen ids
are the prototype's `NAMES` keys. Every new screen sits behind
`NEXT_PUBLIC_COACH_PANEL_V2`; today's coach walk stays live until P6.

The rules for every step: build exactly what the prototype shows; nothing
about a moment is fetched until the coach's blind answer is saved (BLIND
COACH); no number, read or machine pick on any coach screen (AC-9); every
database change gets a GPT check before it merges.

| Step | What | Screens | Endpoints | Build plan rows |
|---|---|---|---|---|
| **P2** | The door and the queue: the Lounge's pinned Speakers and Training corpus buttons, the queue (speakers first, then the blind work), a speaker's goal and Takes | `lounge`, `queue`, `speakers`, `speaker` | `GET /v2/coach/queue`, `GET /v2/coach/queue/moments` (carries `speaker_goal`), `GET /v2/coach/speakers` | D-CP-2 (BE, merged #924), D-CP-11, D-CP-12 |
| **P3** | Judge, then what happened | `judge`, `reveal` | the blind confidence answer (`PUT /v2/coach/snippets/<id>/confidence-label`), then the moment read with `heard` (error, cue or reason key, or `nothing`) | D-CP-3 (BE, merged #925), D-CP-13 |
| **P4** | The diagnosis before the cure | `diagnose`, `nameerr`, `decide`, `swap`, `exdetail` | new: diagnosis (machine-heard errors first, a newly named error, or "I don't hear an error"); the served exercise and a swap pool filtered by the diagnosis; an exercise made under a newly named error reaches the speaker now and waits in the library | D-CP-4 (migration), D-CP-5, D-CP-6 (migration), D-CP-14, D-CP-15 |
| **P5** | The coach's words, video, the kind question, Ready for {p}, Summary and Change my answer, a word for this Take | `words`, `video`, `kind`, `share`, `summary`, `takeword`, `takevideo` | existing request answer, video and share routes; new: change an answer keeping every earlier answer in history (Q-B12 A); the Take word (`GET/PUT /v2/coach/sessions/<id>/word`, `.../word/draft`) | D-CP-7 (migration), D-CP-16, D-CP-17, D-CP-18 |
| **P5b** | The blind sheets, the training corpus inside the panel, the founder's Library and Speaking errors in admin | `audit`, `pick` (and V4's two sheets once signed, S-B8), `corpushome`, `corpusimport`, `corpusanalyse`, `corpus`, `library`, `libitem`, `libpraise`, `libkind`, `libwords`, `libvideo`, `errors`, `error` | `GET/POST /v2/coach/error-audit…`, `GET/POST /v2/coach/block-picks…`, `GET/POST/PUT /v2/coach/training-imports…` (set-up, `setup_complete`), `PUT /v2/admin/exercises/<id>/active`; new: the listen-again work-list item | D-CP-8, D-CP-9 (BE, merged #924), D-CP-10 (migration), D-CP-19, D-CP-20, D-CP-21 |
| **P6** | Blind and fence tests for every new screen, the panel on a computer (Q-B14 A: the same phone-width screens, centred), pictures of every screen to the founder, then the switch | all | none | D-CP-22, D-CP-23, D-CP-24 |
| **P7** | After a clean run: remove today's coach walk and the old corpus page | none | retire the old walk's coach-only routes | D-CP-25 |

Order: P2 and P3 are independent of P4's migrations and go first; P4 and
P5 wait for their GPT checks; P5b's screens can land in any order; P6 only
when every screen above is built; P7 only after the founder's switch and a
clean run.
