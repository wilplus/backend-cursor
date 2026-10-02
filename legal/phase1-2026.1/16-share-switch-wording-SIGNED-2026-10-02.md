# The share switch — Terms and Privacy wording for the next policy version — SIGNED by the founder 2026-10-02

    record:              share-switch-wording-2026-10-02
    author:              Artur Willoński, founder and controller; not reviewed by outside counsel
    rests on:            14-founder-determinations-2026-10-02/q3.md (A), q4.md (A), q5.md (A)
    gates it serves:     Phases 4 and 5 · PEER_LANE_ENABLED and DELAYED_MEASURE_ENABLED (off until the version is published and re-accepted)
    status:              SIGNED by the founder 2026-10-02 (in chat: "I sign it all"). The lines in §1 are
                         now the bytes of `legal/phase1-2026.1/copy/privacy-3.3.txt` and
                         `legal/phase1-2026.1/copy/terms-3.3.txt`, published by `scripts/phase1_policy_publish_3_3.sql`
                         (version phase1-2026-10-02; not yet run)

**What the switch does.** A speaker may lend one Voice Album moment (a short
clip of their own voice) to other users, per recording, off by default. Other
users then hear it without the speaker's name or words, in Lend your ear (they
answer one question about how assured it sounds) and in Bold voices (they
listen). The delayed measure's pair, the original clip and the practised
attempt, rides the same switch. Switching it off pulls the clip from every
pool at once (`services/lend_your_ear.py`, `services/delayed_measure.py`;
contract 29d and 29e). The switch exists only for a speaker whose current
authorization is on the policy version that describes it
(`PEER_SHARE_POLICY_VERSION` in `config.py`), so nobody is offered it before
reading these lines.

## 1. The lines — the copy of Privacy 3.3 and Terms 3.3 (signed 2026-10-02)

### Privacy §3 — "The sound of your voice", one sentence added at the end

> Other users never hear your voice unless you lend a particular recording to
> them yourself, as section 4b describes.

### Privacy §4b — a new choice, after section 4a

> 4b. Lending a recording to other users — optional, per recording
>
> You can let other WillpowerLab users hear one short clip of your voice, one
> recording at a time. It is off unless you turn it on for that recording, and
> you can turn it off again at any time.
>
> What others hear and do: a clip of a few seconds, with no name, no words on
> screen and nothing about you. A listener answers one question about how
> assured the clip sounds, or simply listens to it as an example. If you
> practised that moment, the practised version may be played the same way.
> Their answers help settle, together with a coach's, whether that moment
> belongs in your Voice Album; no listener learns who you are, and you never
> learn who listened.
>
> Legal basis: your explicit consent (Article 9(2)(a) GDPR), given per
> recording by the switch itself. Turning it off withdraws it for that
> recording: the clip leaves every place it could be heard at once. Nothing
> you did before is affected, and nothing else in your account changes.
>
> Your own answers as a listener: when you answer a question about someone
> else's clip, that answer is about their voice and it is also your own data.
> It stays tied to your account, you can ask us for a copy of it (section 8),
> and it is deleted when you delete your account.

### Privacy §5 — a new reader, after "Human coaches"

> Other users
> If you lend a recording (section 4b), other WillpowerLab users hear that
> clip, without your name or your words. Nobody else does.

### Privacy §7 — "How long we keep it", two sentences added

> A recording you lent stops being heard by others the moment you turn the
> switch off, and is deleted with the recording like everything else.
> Your answers about other users' clips are kept while your account is open
> and deleted when you delete it.

### Terms §8 — "Your content is yours", one paragraph added at the end

> If you turn on lending for a recording (Privacy Policy, section 4b), you
> give us permission to play a short clip of that recording to other users,
> without your name or your words, for one purpose: letting them judge or
> listen to how it sounds. The permission is per recording, free of charge,
> and ends the moment you turn it off. Everything else in this section is
> unchanged: your content stays yours.

### Terms §11 — one sentence added at the end

> Other users hear a recording of yours only if you lend it (Privacy Policy,
> section 4b); nothing in this section lends anything for you.

**How the lines were placed in the 3.3 bytes (engineering, 2026-10-02).** The
§3 sentence is the last paragraph of Privacy §3; §4b follows §4a with its
heading in the capitals every section heading of the text uses ("4b. LENDING
A RECORDING TO OTHER USERS — OPTIONAL, PER RECORDING"); "Other users"
follows "Human coaches" in §5; the two §7 sentences form one paragraph after
the recordings paragraph; the Terms §8 paragraph closes §8 and the §11
sentence closes §11. Not a word of the lines changed. The version line and
the version note at the top of each text are engineering's and are put to
the founder in the same reply as this record (see `15-…` §1).

## 2. The path (the 1 October one)

1. The founder signs the lines in §1 and in `15-…` §1 (one version carries
   both: one re-acceptance, not two) — done 2026-10-02.
2. `legal/phase1-2026.1/copy/privacy-3.3.txt` and `legal/phase1-2026.1/copy/terms-3.3.txt`
   are produced as exact bytes (done; the effective date is set on the day);
   the AI notice and the agreement screen are unchanged.
3. Registered as `phase1-2026-10-02` by `scripts/phase1_policy_publish_3_3.sql`
   (the registration described in `04-policy-registration-DRAFT.md`),
   activated, and re-accepted through the six screens.
4. `PEER_SHARE_POLICY_VERSION` is set to that version in one reviewed PR;
   until then the share route refuses (`TERMS_REACCEPT_REQUIRED`).
5. `PEER_LANE_ENABLED`, then `DELAYED_MEASURE_ENABLED` after the founder signs
   `docs/MEASURE-exercise-human-delayed-v1.md`, each one reviewed PR.

## 3. The retention rows (carried into `18-retention-schedule-v1.2-blind-check-and-lending-DRAFT.md`)

| Category | Period | Trigger |
|---|---|---|
| The lending switch for a recording (on, off, when) | with the recording's Take | deletion of the recording |
| A listener's answer about another user's clip, and a listener's vote in the delayed measure | until the listener deletes their account | account deletion (Q5) |

| `rule_code` | `evidence_category` | `retention_until_rule` | What it covers |
|---|---|---|---|
| `voice-album-shares-v1` | `share_switch` | `deleted_with_source_recording` | `voice_album_shares`; keyed to the Take in `services/data_purge_registry.py` |
| `listener-answers-v1` | `listener_answers` | `account_erased` | `lend_your_ear_answers`, `delayed_measure_votes`; keyed to the listener's principal, account level in `services/data_purge_project_scope.py` |
