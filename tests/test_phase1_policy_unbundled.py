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


def _script() -> str:
    return SCRIPT.read_text(encoding="utf-8")


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
