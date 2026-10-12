from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

LEGACY_LEARNING_OBJECTS = {
    "moment_suggestions",
    "star_verdicts",
    "user_suggestion_feedback",
    "feedback_exposures",
    "confidence_labels",
    "confidence_self_reports",
    "confidence_coach_labels",
    "confidence_peer_labels",
    "praise_helpfulness",
    "correction_decisions",
    "annotation_events",
    "training_labels",
    "intervention_arms",
}


def _canonical_learning_modules():
    roots = (ROOT / "services", ROOT / "routes", ROOT / "scripts")
    for root in roots:
        if not root.exists():
            continue
        yield from root.rglob("mlc2_*.py")


def test_canonical_mlc2_modules_cannot_read_or_write_legacy_learning_objects():
    modules = list(_canonical_learning_modules())
    assert modules, "MLC-2 isolation guard must cover at least one module"
    violations = []
    for module in modules:
        source = module.read_text()
        for legacy_name in LEGACY_LEARNING_OBJECTS:
            if legacy_name in source:
                violations.append(f"{module.relative_to(ROOT)}: {legacy_name}")
    assert violations == [], (
        "Canonical MLC-2 code must not read or write legacy learning stores:\n"
        + "\n".join(violations)
    )


# ── DA-PROHIBIT: the doors read no object the audit names (2026-10-05) ─────
#
# The guard above covers the mlc2_*.py modules only. The code that builds,
# releases, evaluates, trains on or promotes learning data lives outside
# that prefix, and the dark training-corpus copy job read confidence_labels
# (through services.professional_confidence) until 0430 gave it the chain's
# own blind judgement. Every module below is held to the same prohibition.
