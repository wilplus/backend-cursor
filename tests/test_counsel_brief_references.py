"""The counsel brief's line references still point where they say.

`legal/phase1-2026.1/21-counsel-questions-2026-10.md` tells counsel to read
named lines of named files. Those files move: the decisions log and our code
gain lines above a cited passage (#898 moved two of them the day the brief
was written), and a draft is corrected before it is signed. A reference that
drifts sends a lawyer to the wrong words, which reads as a client describing
its own records inaccurately (tests/test_legal_citations.py says why that
matters).

Each row names a file, the first words of the cited passage, its last words,
and the reference exactly as the brief prints it. The test finds the passage
in the file as it is now and fails, naming the reference the brief should
print, when the brief no longer says so. Fix the brief and the row, never an
anchor to fit a stale number.

Anchors: "=text" matches a whole line exactly; an end of "<text" ends the
passage on the line before the one carrying that text; an end of None cites
one line.
"""
from __future__ import annotations

import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BRIEF = (ROOT / "legal" / "phase1-2026.1" /
         "21-counsel-questions-2026-10.md").read_text(encoding="utf-8")
#: The brief with every line break and run of spaces made one space, so a
#: reference wrapped across lines still reads as itself.
FLAT = " ".join(BRIEF.split())

REFERENCES: list[tuple[str, str, str | None, str]] = [
    ('legal/phase1-2026.1/03-article-50-assessment-v1.1-DRAFT.md',
     '### Decided item',
     'a later version of this document says so.',
     'lines 196–238'),
    ('legal/phase1-2026.1/03-article-50-assessment-v1.1-DRAFT.md',
     '*Corrected in 1.1.* v1.0 said that Manager Feedback',
     '(§6, gap 1).',
     'lines 138–145'),
    ('legal/phase1-2026.1/03-article-50-assessment-v1.1-DRAFT.md',
     '**We comply either way, and deliberately.**',
     'notice 3.1 does not repeat it.',
     'lines 261–269'),
    ('legal/phase1-2026.1/03-article-50-assessment-v1.1-DRAFT.md',
     '### What the screens label today',
     'marked one.',
     'lines 328–361'),
    ('legal/phase1-2026.1/02-power-score-classification-v1.1-DRAFT.md',
     '## 3b. The speaking-error detectors',
     '<## 4. Is the composite',
     'lines 166–196'),
    ('legal/phase1-2026.1/02-power-score-classification-v1.1-DRAFT.md',
     '### ⚖️ The condition this determination is made under',
     'the service.**',
     'lines 502–505'),
    ('legal/phase1-2026.1/02-power-score-classification-v1.1-DRAFT.md',
     '**The fact, stated by the founder on 2026-10-02.**',
     'stays off meanwhile.',
     'lines 467–477'),
    ('legal/phase1-2026.1/02-power-score-classification-v1.1-DRAFT.md',
     '**The moment a third party records, that stops being true.**',
     'to anyone else.',
     'lines 514–518'),
    ('legal/phase1-2026.1/02-power-score-classification-v1.1-DRAFT.md',
     '**Q7, recorded 2026-10-02',
     'detectors as for the composite.',
     'lines 459–465'),
    ('legal/phase1-2026.1/02-power-score-classification-v1.1-DRAFT.md',
     '## 9. Determination',
     'to anyone else.',
     'lines 445–518'),
    ('legal/phase1-2026.1/02-power-score-classification-v1.1-DRAFT.md',
     '**STATUS: DETERMINED AND SIGNED',
     "and counsel's confirmation is the next action",
     'lines 40–51'),
    ('legal/phase1-2026.1/11-retention-schedule-v1.1-training-DRAFT.md',
     '1. **The consent-record period.**',
     'privacy draft (`10-…`, change 4) carries the same figure.',
     'lines 71–76'),
    ('legal/phase1-2026.1/11-retention-schedule-v1.1-training-DRAFT.md',
     '| The record of your training choice | six years',
     None,
     'line 36'),
    ('legal/phase1-2026.1/13-training-consent-wording-SIGNED-2026-10-01.md',
     "Use my practice text and my coach's notes on it",
     None,
     'line 18'),
    ('legal/phase1-2026.1/15-coach-blind-check-privacy-line-and-balancing-test-SIGNED-2026-10-02.md',
     '**Conclusion.** Legitimate interest holds',
     'the same version so there is one re-acceptance, not two).',
     'lines 139–143'),
    ('legal/phase1-2026.1/15-coach-blind-check-privacy-line-and-balancing-test-SIGNED-2026-10-02.md',
     '4. Opt-out, easy:',
     '`_still_permitted`).',
     'lines 133–135'),
    ('legal/phase1-2026.1/17-door-2-coach-word-surfaces-shut-2026-10-02.md',
     '## What would open it',
     'coach_moment_line" and "… coach_take_word", each one reviewed PR.',
     'lines 29–41'),
    ('docs/SPEC-DECISIONS-LOG.md',
     '**M4 · The Terms currently describe a different product.**',
     'until it is.',
     'lines 532–538'),
    ('docs/SPEC-DECISIONS-LOG.md',
     "3. **Still counsel's:** the six-year number.",
     're-accepts (not).',
     'lines 787–788'),
    ('docs/SPEC-DECISIONS-LOG.md',
     '**N44 · Packages, bought once',
     'none can be started.',
     'lines 1446–1466'),
    ('docs/SPEC-DECISIONS-LOG.md',
     '**N49 · The legacy commerce check reads zero',
     'may be unset.',
     'lines 1611–1632'),
    ('docs/SPEC-DECISIONS-LOG.md',
     '5. **v1.4 §5 adopted, to be carried by v1.5',
     'word.',
     'lines 1658–1670'),
    ('docs/SPEC-DECISIONS-LOG.md',
     'Q18 B: no "report a recording" control',
     'agreement) and the lock is amended.',
     'lines 1574–1577'),
    ('migrations/a_training_yes_is_its_own_act.sql',
     '-- Voice is not biometric data here (counsel, 2026-09-25): no Article 9.',
     ') ON CONFLICT (approval_reference) DO NOTHING;',
     'lines 111–122'),
    ('migrations/a_training_yes_is_its_own_act.sql',
     '-- Exactly one purpose row. Voice is not biometric here: no Article 9.',
     'ON CONFLICT (consent_event_id, purpose) DO NOTHING;',
     'lines 242–246'),
    ('migrations/a_training_yes_counts_any_later_policy.sql',
     '-- Exactly one purpose row. Voice is not biometric here: no Article 9.',
     'ON CONFLICT (consent_event_id, purpose) DO NOTHING;',
     'lines 115–119'),
    ('legal/phase1-2026.1/copy/privacy-3.3.txt',
     'Legal basis: your consent (Article 6(1)(a) GDPR), given as explicit consent',
     'off at any time.',
     'lines 162–167'),
    ('legal/phase1-2026.1/copy/privacy-3.3.txt',
     'The record of your choice: we keep the record',
     'timestamps, not your words.',
     'lines 179–182'),
    ('legal/phase1-2026.1/copy/privacy-3.3.txt',
     'To check that our automated listening is right',
     'Turning it off costs you nothing else.',
     'lines 92–102'),
    ('legal/phase1-2026.1/copy/privacy-3.3.txt',
     'Legal basis: our legitimate interest in keeping the tool accurate',
     'Turning it off costs you nothing else.',
     'lines 99–102'),
    ('legal/phase1-2026.1/copy/privacy-3.3.txt',
     'Human coaches',
     'practice off.',
     'lines 245–255'),
    ('legal/phase1-2026.1/copy/privacy-3.3.txt',
     'the Terms say so in section 1 and section 11, and how many',
     'reviews you receive each month depends on your plan',
     'lines 249–250'),
    ('legal/phase1-2026.1/copy/privacy-3.3.txt',
     '=Payments',
     'We never see or store your card details.',
     'lines 240–243'),
    ('legal/phase1-2026.1/copy/privacy-3.3.txt',
     'Practice, and making it personal',
     'withdrawing it ends practice, not your account.',
     'lines 104–110'),
    ('legal/phase1-2026.1/copy/privacy-3.3.txt',
     '3. THE SOUND OF YOUR VOICE',
     'from the sound of your voice.',
     'lines 57–66'),
    ('legal/phase1-2026.1/copy/privacy-3.3.txt',
     '4. WHAT WE USE IT FOR, AND ON WHAT LEGAL BASIS',
     'Training happens only with the separate choice in section 4a.',
     'lines 75–86'),
    ('legal/phase1-2026.1/copy/privacy-3.3.txt',
     'We are not quoting fixed retention periods here.',
     'accept the version that describes it.',
     'lines 316–320'),
    ('legal/phase1-2026.1/copy/privacy-3.3.txt',
     '7. HOW LONG WE KEEP IT',
     'what survives it.',
     'lines 287–291'),
    ('legal/phase1-2026.1/copy/privacy-3.3.txt',
     'Record of your training choice: kept',
     'deleted.',
     'lines 312–314'),
    ('legal/phase1-2026.1/copy/privacy-3.3.txt',
     '- restrict how we use your data, or object',
     'legitimate interests;',
     'lines 334–335'),
    ('legal/phase1-2026.1/copy/privacy-3.3.txt',
     'When you ask us to delete your data, we build an inventory',
     'record proof of each deletion.',
     'lines 354–357'),
    ('legal/phase1-2026.1/copy/privacy-3.3.txt',
     'Three things survive deletion:',
     'for example accounting records.',
     'lines 365–376'),
    ('legal/phase1-2026.1/copy/privacy-3.3.txt',
     '- The record of your training choice (section 4a)',
     'your account, then delete it.',
     'lines 372–375'),
    ('services/pair_consent.py',
     'WHICH SURFACES NEED THE YES',
     'interest).',
     'lines 17–20'),
    ('docs/PRODUCT-LEGAL-FLOW-PLF-1.1.md',
     '3. The Terms state that the user may provide only recordings',
     'per-recording sole-speaker checkbox.*',
     'lines 52–56'),
    ('docs/PRODUCT-LEGAL-FLOW-PLF-1.1.md',
     '5. Setup collects country of residence once.',
     'location today.*',
     'lines 59–69'),
    ('scripts/phase1_policy_publish_unbundled.sql',
     'Per docs/HANDOFF-2026-09-23.md §0, counsel answered',
     'under Art 56.',
     'lines 294–299'),
    ('scripts/phase1_policy_publish_unbundled.sql',
     'COUNSEL HAS ANSWERED',
     '"provisional" has meant here all along',
     'lines 292–313'),
    ('legal/phase1-2026.1/14-founder-determinations-2026-10-02/q1.md',
     '## The answer',
     '(see Q4 for the path).',
     'lines 21–33'),
    ('legal/phase1-2026.1/19-retention-schedule-v1.3-financial-records-DRAFT.md',
     'This answers v1.0 §3 with its option 2',
     'Either answer would be a v1.4',
     'lines 43–49'),
    ('legal/phase1-2026.1/20-retention-schedule-v1.4-product-records-and-job-evidence-DRAFT.md',
     '## 1. Additions to the published schedule',
     'words and never your voice.',
     'lines 44–62'),
    ('legal/phase1-2026.1/20-retention-schedule-v1.4-product-records-and-job-evidence-DRAFT.md',
     '**5.1 Live records',
     'stops here for a person.**',
     'lines 134–152'),
    ('legal/phase1-2026.1/20-retention-schedule-v1.4-product-records-and-job-evidence-DRAFT.md',
     '**5.7 The end of the financial records',
     'new.',
     'lines 281–292'),
    ('legal/phase1-2026.1/20-retention-schedule-v1.4-product-records-and-job-evidence-DRAFT.md',
     '## 6. What this schedule does',
     'never an edit of this one.',
     'lines 294–313'),
    ('legal/phase1-2026.1/20-retention-schedule-v1.4-product-records-and-job-evidence-DRAFT.md',
     '### Table B',
     'Kept job evidence is only counted',
     'lines 100–109'),
    ('legal/phase1-2026.1/copy/terms-3.3.txt',
     '11. HUMAN COACHES',
     'section 3 of the Privacy Policy.',
     'lines 195–207'),
    ('legal/phase1-2026.1/copy/terms-3.3.txt',
     'What that means in practice.',
     'section 3 of the Privacy Policy.',
     'lines 201–207'),
    ('legal/phase1-2026.1/copy/terms-3.3.txt',
     '15. CHANGES TO THESE TERMS',
     'for that record at any time.',
     'lines 266–274'),
    ('legal/phase1-2026.1/copy/terms-3.3.txt',
     '2. WHAT IT COSTS',
     'have started using it.',
     'lines 40–64'),
    ('legal/phase1-2026.1/copy/terms-3.3.txt',
     '4. WHERE THE SERVICE IS AVAILABLE',
     'cannot provide the service to you.',
     'lines 75–79'),
    ('legal/phase1-2026.1/copy/terms-3.3.txt',
     '6. RECORDING OTHER PEOPLE',
     'deleting the audio.',
     'lines 91–104'),
    ('legal/phase1-2026.1/copy/terms-3.3.txt',
     '- record a person who has not agreed to it;',
     None,
     'line 111'),
]


def _passage(path: str, start: str, end: str | None) -> tuple[int, int]:
    text = (ROOT / path).read_text(encoding="utf-8").splitlines()
    if start.startswith("="):
        hits = [i for i, line in enumerate(text) if line.strip() == start[1:]]
    else:
        hits = [i for i, line in enumerate(text) if start in line]
    assert len(hits) == 1, f"{path}: {start!r} found {len(hits)} times"
    first = hits[0]
    if end is None:
        return first + 1, first + 1
    if end.startswith("<"):
        for index in range(first + 1, len(text)):
            if end[1:] in text[index]:
                return first + 1, index
        raise AssertionError(f"{path}: no {end[1:]!r} after {start!r}")
    for index in range(first, len(text)):
        line = text[index]
        if end in line and (index > first or line.find(end) >= line.find(start)):
            return first + 1, index + 1
    raise AssertionError(f"{path}: no {end!r} after {start!r}")


def _printed(first: int, last: int) -> str:
    return f"line {first}" if first == last else f"lines {first}–{last}"


@pytest.mark.parametrize("path,start,end,cited", REFERENCES,
                         ids=[f"{p.rsplit('/', 1)[-1]}:{c}"
                              for p, _s, _e, c in REFERENCES])
def test_each_reference_still_points_at_its_passage(path, start, end, cited):
    now = _printed(*_passage(path, start, end))
    assert now == cited, (
        f"{path}: the passage starting {start!r} is now {now}; the brief "
        f"cites {cited}. Update the brief and this row.")
    assert cited in FLAT, f"the brief no longer cites {path} as {cited}"
