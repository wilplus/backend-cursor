# The willab engine map — what runs where, and how it all connects

**Date:** 2026-07-28 · verified against the code on `feat/coach-star-verdict`
(`ac9b800`). Plain-language reference for the founder; every claim is checked
against a real file, named in parentheses.

---

## The one-sentence version

A recording flows through **one measurement pass**, gets cut into **pieces**,
each piece gets **acoustic + content reads**, a **ranking** picks the best
version of every slide into the **ideal text**, a set of **advice engines**
decorates it, the **coach** reviews on their own surfaces — and since this
wave, everything the coach corrects or endorses lands in **learning corpora**
that will feed the three future models (confidence, voice-text analytics,
transcription).

---

## 1. The engines

**Legal column added 2026-08-13**, when Terms v1.1 and Privacy v1.1 went live
(`frontend-cursor/src/app/{terms,privacy}/page.tsx`). It names the published
section that governs each engine and the open backlog item that gates it —
Epic L in [docs/BACKLOG.md](BACKLOG.md). Three things bind every row and are not
repeated: audio is **Voice Data** and transcripts **Text Data** (Privacy §2),
both retained under Privacy §10 (**L-5**, no purge job exists), and anything a
coach corrects trains the models under Privacy §5 (objection route **L-1**).

| # | Engine | Lives in | Eats | Produces | Who sees it | Legal constraint |
|---|---|---|---|---|---|---|
| E1 | **Transcription** | `audio_metrics` (decode/compress), Whisper, `slide_word_split` (punctuation restore, run-on splits, 200-char pieces) | raw audio + slide vocab prime | word-level transcript, cut into ≤200-char pieces 1:1 with slides | everyone (it's the text) | Privacy **§2** (Voice + Text Data) · retention **§10** → **L-5**. The transcript is the User Content the licence in Terms **§3** covers. |
| E2 | **Acoustic measurement** | `audio_metrics` | 16 kHz PCM per piece | the 11-feature metrics blob (f0, pauses, loudness, rate…) + librosa extras on budget pieces | nobody directly — feeds E3–E7 | Privacy **§6** — these are the "acoustic measurements" §6 discloses. Internal only; surfacing one as a number breaks AC-9 **and** §6's own promise. |
| E3 | **Selection gate** | `snippet_salience` | metrics | which pieces get the LLM budget / become coach candidates (transient scores, never stored) | nobody | Transient, never stored → nothing to disclose. Privacy **§10** by omission. |
| E4 | **Content reads** | `snippet_stickiness`, `slide_alignment` | transcript + slides | topic + slide coherence → `overall_score` | coach packet only | Coach packet only ⇒ human review, Terms **§6** / Privacy **§8**. `share_consent` is the live consent. |
| E5 | **Ranking** | `power_phrase_ranking` → `best_presentation`, `cross_take_selection`, `prior_take_changes` | coach tag (publish-gated, 2026-08-13) + `overall_score` + slide stickiness + confidence (panel aggregate, else machine stamp — flag-off) — the direction/breakthrough ranking terms are RETIRED with the charisma construct | the winning line per slide → the ideal text | nobody sees the score; everyone sees the winner | Privacy **§6** ("used to select which version… to assemble"). Score never surfaced — AC-9 and §6 agree. |
| E6 | **Coach reads** | `acoustic_read` (the potentiometer — ⚠ RETIRED-construct vocabulary, kept coach-only; no longer routes any user-facing lane since 2026-08-13), `auto_comment` (coach branch) | metrics vs the speaker's own baseline | the potentiometer + outside-normal-range flag | **coach only** | Terms **§6** / Privacy **§8** — human review, consent-gated, withdrawable. BLIND COACH is a product fence, not a legal one. |
| E7 | **Advice engines** | `delivery_stars`, `delivery_alignment` (congruence), `moment_suggestions` (emphasize/replace/structure), `say_it_stronger`, `prior_take_changes`, `auto_comment` (user branch), `user_patterns` | metrics + transcript (+ LLM) | stars, cards, rewrites, qualitative notes | user (qualitative only, AC-9) | Terms **§7** — output is AI-generated unless marked human-reviewed. User-facing, so LIVE LOOP: copy needs founder sign-off. |
| E8 | **Ideal text assembly** | `ideal_text_block` | E5's picks + coach corrections + approved suggestions | the one marker-carrying block, auto draft frozen in `auto_text` | coach edits it; user reads the verified version | Terms **§3** — user owns the words; the licence permits transform-to-serve. L1 (select + light polish) is what keeps that short of an authorship claim. |
| E9 | **The game** | `game_engine` | coach `challenge` labels (keys — legacy corpus vocabulary, SPEC §3.2) + the user's other moments (decoys) | ≤10 blind rounds; every answer → a peer label | user (owner only) | ⚠ **The sharp one.** Peer labels mean users hear each other ⇒ Terms **§5** / Privacy **§7**, which promise per-recording, revocable consent that **does not exist** — gate **L-2**. Confirm `/game` reachability. |
| E10 | **Voice-confidence composite** | `voice_confidence` | 7 Jiang & Pell cues vs own baseline, **cue weights routed by speaker sex** (`user_settings.profile_sex`; cue 1 REVERSES direction, so the sex term is explicit and normalisation cannot stand in for it) | a −1…+1 spectrum score per piece, stamped with `sex`/`sex_source`, **ranking-inert until validated** (flag off) | nobody | ⚠ **EU AI Act — emotion recognition** (**L-11**): infers a speaker state from voice. Prohibited in workplace/education (mirrored in Terms **§7**); transparency duty unassessed. Open **GDPR Art. 9** question and the DPIA trigger (**L-9**). Privacy **§6** claims it is opt-in and off by default — true only while gated on `mic_consent`. |

## 2. The learning corpora — what the system remembers, as of this wave

| Corpus (table) | What it records | Written by | Feeds | Fence |
|---|---|---|---|---|
| `training_labels` | the coach's **blind** challenge/threat (→ confidence/weakness) voice labels | coach labeling surface | the shadow direction classifier (`learning_train`, ≥50 labels) | **BLIND** — coach never sees a machine guess here |
| `star_verdicts` *(new)* | keep / wrong_kind+correction / should_not_fire per fired star | `PUT /coach/snippets/<id>/star-verdict` | the future star **detector** (when to speak / stay quiet) | decision lane; never joined into training_labels; never shown to users |
| `admin_annotation_events` | (AI draft, coach final) TEXT pairs: comments, follow-ups, coach notes, **say-it-stronger cards, kept star texts, ideal-text sentences** *(all new)* | publish capture + keep-verdict emit + verify emit | SFT + DPO exports → the future **writer** models | ⭐ was DEAD CODE until this wave — zero rows had ever been written |
| `snippet_peer_labels` | game answers (key_moment/neutral), source + rater | `game_engine.answer_round` | second-order signal for the confidence model | **fenced below coach truth**; opening it is a founder decision |
| `user_suggestion_feedback` + decision ledger | which advice users apply/dismiss | user star taps | second-order preference signal | same fence |
| `candidate_windows` | the full offered-vs-chosen selection pool, raw features | record-time capture | learning the selection step itself | raw only — no derived scores stored |
| `coach_video_assets` | coach videos + comment pairs per moment | coach upload | the coach-clone corpus (L3) | capture-only |

## 3. How they connect (the full loop)

```
 recording ──E1──> pieces ──E2──> metrics ──E3──> budget/candidates
                                    │                    │
                     E4 content ────┤          E6 coach needle ──> coach panel
                     reads          │                    │
                                    ▼                    ▼
                              E5 ranking          coach LABELS (blind) ──> training_labels ──> shadow model ┐
                                    │                                                                       │
                                    ▼                                                    (fallback direction┘
                              E8 ideal text <── coach corrections/verify                  term back into E5)
                                    │                │
                     E7 advice ─────┤                └──> ideal_text_sentence pairs ──> admin_annotation_events
                     (stars/cards)  │                                                        ▲          │
                          │         ▼                                                        │          ▼
                          │    user reads/records again (the loop)              SiS pairs ───┘   SFT/DPO exports
                          │                                                     keep-verdict texts    │
                          └──> coach STAR VERDICTS ──> star_verdicts                                  ▼
                                                          │                              future writer models
                                                          ▼
                                            future detector model (when to speak)
 coach challenge labels ──> E9 game rounds ──> user answers ──> snippet_peer_labels ──> (fenced) confidence model
```

## 4. The three future models, and what now exists for each

| Model | Purpose | Corpus status after this wave |
|---|---|---|
| **Confidence** (fuels the game) | recognize the confident-voice moment | coach labels flowing (blind); game answers captured (fenced); `voice_confidence` composite stamped awaiting human-rating validation; **still missing: the agreement aggregator** joining coach + peer + self labels |
| **Voice-text analytics** | better advice, better silence | ⭐ went from zero to three live corpora: star verdicts (decisions), SiS/star/comment text pairs, ideal-text sentence pairs — all now actually writing |
| **Transcription** | per-user correction memory | **PAUSED by founder decision** — corrections are captured (`coach_transcript_correction`) but deliberately not fed back yet |

## 5. Operational notes

- ⚠️ Run `migrations/add_star_verdicts.sql` (from the coach-learning wave).
- ⚠️ Run `migrations/add_speaker_sex.sql` (E10's sex term). Until it is run,
  `profile_sex` reads as "never asked" everywhere and E10 falls back to the
  sex-blind v1 weights — un-improved, never broken.
- The keep-flip guard has an accepted read-then-write race under truly
  concurrent coach PUTs (single-coach product; a DB constraint would close it).
- `log_rlhf_auto_accept_events` (assignment lane) is imported but never
  invoked — a second dead-emitter of the same family, untouched by this wave.
- FE handoffs: `docs/PROMPT-FE-star-verdict.md`, `docs/PROMPT-FE-game.md`.
