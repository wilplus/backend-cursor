"""The republished policy does not make an OPTIONAL purpose a condition.

P11. `scripts/phase1_policy_publish.sql` ran in production on 2026-09-20 and
published all five purposes with `lawful_basis_code 'consent'` AND
`required_for_core_service TRUE`. Consent that is a condition of service, for
purposes that are not necessary to the service, is not freely given (Art
4(11), Art 7(4), Recital 43). `legal/phase1-2026.1/01-product-legal-approval`
§3 assesses that structure as invalid.

⚠ REWRITTEN 2026-09-23. These cases previously asserted that coach_review is
ABSENT from the policy and that the privacy copy promises coach review is
refusable — doc 01 §6's v1 shape. The founder reversed that on 2026-09-23:

    "Coach review is core to the product. A user who refuses to allow a human
     to listen to their recordings cannot use WillpowerLab."

and, on the practice/exercise step, the same day: "you can always leave the
app and not do it, you can skip it". So the two purposes move in OPPOSITE
directions — coach_review to 6(1)(b) contract and required,
personalized_exercise_recommendation to 6(1)(a) consent and refusable. The
old cases were pinning a product decision that no longer holds; they are
inverted here, not dropped, and the invariant they existed to protect is now
asserted structurally rather than by counting.

THE INVARIANT, which did not change and is the whole point: no purpose may be
published on CONSENT while also being REQUIRED. That pairing is the Art 7(4)
defect. Everything else in this file is a consequence.

These cases cannot prove the policy lawful — that is counsel's — but they can
prove it says what the determination says, and they catch the two drifts that
have already happened once each:

  * the published bytes and the .txt files in `legal/phase1-2026.1/copy/`
    disagreeing (agreement-1.0.txt already said a coach is asked for
    separately, while the bytes published on 09-20 bundle it), and
  * a consent policy reaching `migrations/manifest.txt`, where
    `MIGRATE_ON_BOOT=1` would publish it at container start.
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "phase1_policy_publish_unbundled.sql"
COPY = ROOT / "legal" / "phase1-2026.1" / "copy"
MANIFEST = ROOT / "migrations" / "manifest.txt"

#: Required for the service to exist at all. Art 6(1)(b) contract.
#: coach_review joined these on 2026-09-23 by founder ruling.
REQUIRED_PURPOSES = (
    "recording_voice_processing",
    "transcription_feedback",
    "coach_review",
)

#: Genuinely refusable. Art 6(1)(a) consent, required_for_core_service FALSE.
#: Five routes return 410 PURPOSE_NOT_OPERATIONAL today and the record →
#: transcript → Ideal Text → Feedback loop completes without any of them,
#: which is the necessity test answered by the running system.
OPTIONAL_PURPOSES = (
    "personalized_exercise_recommendation",
    "individual_learning_profile",
)

#: Held out of the policy entirely. EMPTY since 2026-09-23: the founder ruled
#: individual_learning_profile optional ("it personalises the exercises you
#: get"), so all five registry purposes are now published — three required on
#: contract, two refusable on consent. The guard stays armed for the next
#: purpose somebody adds to the registry and reaches for here.
UNJUSTIFIED_PURPOSES: tuple[str, ...] = ()

#: The dollar-quoted tag in the script -> the file it must match byte for byte.
MIRRORED = {
    "terms": "terms-3.1.txt",
    "privacy": "privacy-3.1.txt",
    "notice": "ai-notice-3.1.txt",
    "agree": "agreement-3.1.txt",
}


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _quoted(tag: str) -> str:
    match = re.search(rf"\${tag}\$(.*?)\${tag}\$", _script(), re.S)
    assert match, f"the script no longer carries a ${tag}$ block"
    return match.group(1)


def _purposes_block() -> str:
    """Just the jsonb_build_array of policy purposes, comments stripped.

    Read without comments on purpose: the header and the inline notes discuss
    the excluded and the optional purposes by name, and a test that searched
    the whole file for those names would fail on the explanation of why a
    purpose is absent.

    ⚠ The slice used to start at the FIRST `jsonb_build_array(` after
    `'allowed_countries'` — which is the country list, not the purposes — so
    it silently swept in the three legal-artifact objects too. Any artifact
    metadata mentioning a purpose or a basis would have corrupted the counts
    below. It now anchors on the LAST array before the actor argument, which
    is the purposes array and nothing else.
    """
    body = _script()
    end = body.index("'founder:artur@willonski.com'\n) FROM c;")
    start = body.rindex("jsonb_build_array(", 0, end)
    return re.sub(r"--[^\n]*", "", body[start:end])


def _purpose_objects() -> list[str]:
    """Each purpose's jsonb_build_object, so basis and requiredness are read
    together. Counting them separately across the whole block cannot tell you
    WHICH purpose carries which — and the defect is a pairing, not a tally."""
    block = _purposes_block()
    chunks = block.split("jsonb_build_object(")[1:]
    assert chunks, "the purposes array no longer builds any purpose objects"
    return chunks


class TestNoConsentPurposeIsAConditionOfService:
    """The finding itself, asserted as the pairing it actually is."""

    def test_no_purpose_is_both_consent_and_required(self):
        """Art 7(4). This is the one line that must never go green by
        accident: it reads each purpose object whole, so a consent purpose
        cannot hide behind a required one elsewhere in the array."""
        offenders = []
        for chunk in _purpose_objects():
            consent = "'lawful_basis_code','consent'" in chunk
            required = "'required_for_core_service',true" in chunk
            if consent and required:
                name = re.search(r"r\.id = '([a-z_]+)'", chunk)
                offenders.append(name.group(1) if name else "unnamed purpose")

        assert offenders == [], (
            "compelled consent is back in the policy: "
            f"{offenders}. A purpose on consent must be refusable without "
            "losing the service, or the consent is not freely given and the "
            "contract basis fails for everything else too."
        )

    def test_every_required_purpose_is_on_contract(self):
        """If it is compulsory, consent is the wrong basis for it — 6(1)(b)
        is. The inverse of the case above, so neither can pass alone."""
        wrong = []
        for chunk in _purpose_objects():
            if "'required_for_core_service',true" not in chunk:
                continue
            if "'lawful_basis_code','contract'" not in chunk:
                name = re.search(r"r\.id = '([a-z_]+)'", chunk)
                wrong.append(name.group(1) if name else "unnamed purpose")

        assert wrong == [], f"a required purpose is not on contract: {wrong}"

    def test_the_optional_purpose_is_genuinely_refusable(self):
        """An 'optional' purpose published as required is how optionality
        quietly disappears. It must be consent AND false, together."""
        published = _purposes_block()
        for purpose in OPTIONAL_PURPOSES:
            assert f"r.id = '{purpose}'" in published, (
                f"{purpose} is missing; without it the acceptance screen has "
                "nothing to offer and practice can never be opted into"
            )

        refusable = [
            chunk for chunk in _purpose_objects()
            if "'required_for_core_service',false" in chunk
            and "'lawful_basis_code','consent'" in chunk
        ]
        assert len(refusable) == len(OPTIONAL_PURPOSES), (
            "the optional lane is not published as consent + refusable; "
            "see the script header's ordering note"
        )


class TestItPublishesExactlyWhatWasRuled:

    def test_the_required_purposes_are_all_present(self):
        published = _purposes_block()
        missing = [p for p in REQUIRED_PURPOSES
                   if f"r.id = '{p}'" not in published]
        assert missing == [], (
            f"a purpose the service cannot run without is absent: {missing}. "
            "coach_review is required by founder ruling 2026-09-23 — remove "
            "it and the delivery channel, the corrected transcript and the "
            "word→slide ground truth go with it."
        )

    def test_unjustified_purposes_stay_out(self):
        published = _purposes_block()
        present = [p for p in UNJUSTIFIED_PURPOSES if p in published]
        assert present == [], (
            f"a purpose nobody has justified is in the policy: {present}. "
            "It returns when something actually reads it AND a lawful basis "
            "has been decided for it on its own merits — not because it "
            "exists in the registry."
        )

    def test_the_array_publishes_nothing_else(self):
        """A purpose that is neither ruled required nor ruled optional has no
        business being published at all."""
        named = set(re.findall(r"r\.id = '([a-z_]+)'", _purposes_block()))
        expected = set(REQUIRED_PURPOSES) | set(OPTIONAL_PURPOSES)
        assert named == expected, (
            f"the published set drifted from the rulings: "
            f"unexpected={sorted(named - expected)}, "
            f"missing={sorted(expected - named)}"
        )


class TestTheCopyDescribesTheSameProductAsThePurposes:
    """The copy and the purposes have to describe one product. This is the
    half that was pointing the wrong way before 2026-09-23."""

    def test_the_agreement_tick_names_coach_review(self):
        """coach_review is compulsory, so the tick must say so — burying a
        mandatory human listener is worse than bundling an optional one."""
        agreement = _quoted("agree").lower()

        assert "coach" in agreement, (
            "the acceptance sentence no longer tells the person that a coach "
            "may listen, while the policy makes it a condition of service"
        )
        # ⚠ AN ASSERTION LEFT HERE DELIBERATELY. This case used to require
        # "18 or over" in the tick sentence. The v3.1 copy moves the age
        # attestation to its own control — Phase1AcceptanceFlow renders "I am
        # {policy.minimumAge} or older" as a separate checkbox, canSubmit
        # refuses without it, and it travels as p_age_18_attested rather than
        # as words inside the agreement. That is better than burying it in a
        # sentence, so the assertion is not restored here; it belongs to the
        # screen's own suite. Recorded rather than deleted quietly, because a
        # missing age check is exactly the kind of thing that should never
        # vanish without a reason written down.
        #
        # NOT a newline count. An earlier version of this case demanded a
        # single line, which would have rejected a two-paragraph tick that
        # reads better than the one-liner it replaced. What must not happen is
        # the tick growing into a wall nobody reads, so bound the thing that
        # actually matters.
        assert len(agreement.strip()) <= 600, (
            "the acceptance tick is growing into something nobody will read"
        )
        assert agreement.strip(), "the acceptance tick is empty"

    def test_the_agreement_tick_does_not_bundle_practice(self):
        """The mandatory tick must not carry the OPTIONAL purpose. This is
        the same defect as 09-20, one purpose smaller — the live tick ended
        'and prepare practice for me', which is a compelled yes to something
        the founder has ruled skippable."""
        agreement = _quoted("agree").lower()

        assert "practice" not in agreement, (
            "the mandatory tick still asks for practice, which is optional; "
            "it needs its own control and its own p_optional_purposes entry"
        )
        assert "exercise" not in agreement

    def test_the_privacy_copy_says_a_coach_may_listen(self):
        """Reinstated from the live 2026-09-20 bytes. The old case asserted
        the OPPOSITE — that this sentence must be absent — because the draft
        it guarded removed coach review from the product."""
        privacy = _quoted("privacy").lower()

        assert "a willpowerlab coach — a person —" in privacy, (
            "the privacy notice no longer tells people a human hears their "
            "voice, while the policy makes exactly that a condition of use"
        )
        assert "we will ask you for that separately" not in privacy, (
            "this promises coach review is refusable, which the founder "
            "ruling reverses; a promise the product cannot keep is worse "
            "than no promise"
        )

    def test_the_privacy_copy_says_practice_is_optional(self):
        """The other direction: the refusable purpose has to read as
        refusable, or the consent is not informed."""
        privacy = _quoted("privacy").lower()
        assert "optional" in privacy
        assert "practice" in privacy

    def test_the_terms_describe_coach_review(self):
        """Founder ruling 2026-09-23: 'the Terms must describe it'. Before
        this, the Privacy notice and the tick carried the entire disclosure
        and the Terms were silent on it."""
        terms = _quoted("terms").lower()

        assert "coach" in terms, (
            "the Terms still do not mention coach review, which the ruling "
            "requires them to describe"
        )


class TestTheCopyAndThePublishedBytesAgree:
    """This drift has already happened once, between agreement-1.0.txt and
    what was published on 2026-09-20."""

    def test_every_block_is_mirrored_byte_for_byte(self):
        mismatched = []
        for tag, name in MIRRORED.items():
            path = COPY / name
            if not path.exists():
                mismatched.append(f"{name}: missing")
                continue
            if path.read_text(encoding="utf-8") != _quoted(tag):
                mismatched.append(f"{name}: differs from ${tag}$ in the script")

        assert mismatched == [], (
            "the published bytes and the legal pack disagree, which is how "
            f"a user's receipt ends up naming text nobody kept: {mismatched}"
        )


class TestPublishingStaysAHumanAct:

    def test_the_script_is_not_a_migration(self):
        """`MIGRATE_ON_BOOT=1` means anything in the manifest runs at
        container start. Publishing a consent policy is not something a
        deploy should do behind anyone's back."""
        manifest = MANIFEST.read_text(encoding="utf-8")

        assert "phase1_policy_publish_unbundled.sql" not in manifest
        assert not (ROOT / "migrations" /
                    "phase1_policy_publish_unbundled.sql").exists()

    def test_it_says_what_running_it_costs(self):
        """The header has to carry the consequence, because the person
        running this by hand is the only one who can weigh it."""
        header = _script()[:_script().index("-- ── STEP 1")]

        assert "resolve_mlc3_dual_purpose_receipt_v2" in header
        assert "required_for_core_service" in header
        assert "accept_phase1_processing_authorization_v2" in header, (
            "the header must carry the way out, or the reader is left with "
            "only the cost"
        )

    def test_it_says_accept_v2_must_ship_first(self):
        """The ordering trap: accept_v1 writes receipt rows only WHERE
        required_for_core_service, so publishing an optional purpose before
        v2 ships means nobody can ever opt in and MLC-3 stays dark with no
        error to explain it."""
        header = _script()[:_script().index("-- ── STEP 1")]

        assert "DO NOT RUN THIS BEFORE" in header, (
            "the header must state the ordering dependency in terms the "
            "person running it cannot miss"
        )
