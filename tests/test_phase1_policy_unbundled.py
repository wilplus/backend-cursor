"""The republished policy does not make an optional purpose a condition.

P11. `scripts/phase1_policy_publish.sql` ran in production on 2026-09-20 and
published all five purposes with `lawful_basis_code 'consent'` AND
`required_for_core_service TRUE` — including coach_review,
individual_learning_profile and personalized_exercise_recommendation, with an
agreement sentence that bundles coach review into the single tick.

`legal/phase1-2026.1/01-product-legal-approval` §3 assesses that structure as
invalid under Art 4(11) and Art 7(4) with Recital 43, and §6 says those three
were held out of v1 for exactly this reason.

These cases read the replacement script. They cannot prove it lawful — that is
counsel's — but they can prove it says what the determination says, and they
catch the two drifts that have already happened once each:

  * the published bytes and the .txt files in `legal/phase1-2026.1/copy/`
    disagreeing (agreement-1.0.txt already says a coach is asked for
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

#: Held out of v1 by doc 01 §6, for the Article 7(4) reason.
OPTIONAL_PURPOSES = (
    "coach_review",
    "individual_learning_profile",
    "personalized_exercise_recommendation",
)

#: The dollar-quoted tag in the script -> the file it must match byte for byte.
MIRRORED = {
    "terms": "terms-unbundled-2026-09-23.txt",
    "privacy": "privacy-unbundled-2026-09-23.txt",
    "notice": "ai-notice-unbundled-2026-09-23.txt",
    "agree": "agreement-unbundled-2026-09-23.txt",
}


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


def _quoted(tag: str) -> str:
    match = re.search(rf"\${tag}\$(.*?)\${tag}\$", _script(), re.S)
    assert match, f"the script no longer carries a ${tag}$ block"
    return match.group(1)


def _purposes_block() -> str:
    """Just the jsonb_build_array of policy purposes, comments stripped.

    Read without comments on purpose: the header discusses the three excluded
    purposes at length, and a test that searched the whole file for their
    names would fail on the explanation of why they are absent.
    """
    body = _script()
    start = body.index("jsonb_build_array(", body.index("'allowed_countries'"))
    end = body.index("'founder:artur@willonski.com'\n) FROM c;")
    return re.sub(r"--[^\n]*", "", body[start:end])


class TestNoOptionalPurposeIsAConditionOfService:
    """The finding itself."""

    def test_the_three_held_out_purposes_are_not_published(self):
        published = _purposes_block()
        present = [p for p in OPTIONAL_PURPOSES if p in published]
        assert present == [], (
            "a purpose doc 01 §6 holds out of v1 is back in the policy: "
            f"{present}. If it is meant to return, it returns as "
            "required_for_core_service FALSE with its own consent — never as "
            "a condition of service."
        )

    def test_every_published_purpose_is_required_and_on_contract(self):
        """Doc 01 §3: operations 1-6 are 6(1)(b) contract, and the corollary
        is that nothing outside them is a condition of use."""
        published = _purposes_block()

        assert "'lawful_basis_code','consent'" not in published, (
            "a purpose is still published on consent; §3 proposes contract "
            "for the core operations, and consent that is a condition of "
            "service is the thing this script exists to remove"
        )
        assert published.count("'lawful_basis_code','contract'") == 2
        assert published.count("'required_for_core_service',true") == 2
        assert "'required_for_core_service',false" not in published, (
            "an optional purpose cannot be published until a receipt can "
            "record one — see the script header"
        )

    def test_it_publishes_exactly_the_two_core_purposes(self):
        published = _purposes_block()
        for purpose in ("recording_voice_processing", "transcription_feedback"):
            assert f"r.id = '{purpose}'" in published, f"{purpose} is missing"

    def test_the_agreement_sentence_no_longer_bundles_coach_review(self):
        """The single tick is where the bundling was visible to the user."""
        agreement = _quoted("agree").lower()

        assert "coach" not in agreement, (
            "the acceptance sentence still asks the user to agree to coach "
            "review in the same breath as the Terms"
        )
        assert "18 or over" in agreement
        assert len(agreement.strip().splitlines()) == 1, (
            "one sentence, so what is being agreed to stays readable"
        )

    def test_the_privacy_copy_does_not_promise_a_coach_may_listen(self):
        """A policy that no longer authorises coach review must not keep
        telling people a coach may listen — the copy and the purposes have to
        describe the same product."""
        privacy = _quoted("privacy").lower()

        assert "a willpowerlab coach — a person — may listen" not in privacy
        assert "we will ask you for that separately" in privacy, (
            "dropping the claim is not enough; the copy should say what "
            "happens if coach review is ever offered"
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
        """The header has to carry the MLC-3 consequence, because the person
        running this by hand is the only one who can weigh it."""
        header = _script()[:_script().index("-- ── STEP 1")]

        assert "resolve_mlc3_dual_purpose_receipt_v2" in header
        assert "required_for_core_service" in header
        assert "accept_phase1_processing_authorization_v2" in header, (
            "the header must carry the proposed way out, or the reader is "
            "left with only the cost"
        )
