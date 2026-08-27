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


def test_dependency_audit_names_every_guarded_legacy_object():
    audit = (ROOT / "docs" / "MLC2-LEGACY-DEPENDENCY-AUDIT.md").read_text()
    missing = sorted(name for name in LEGACY_LEARNING_OBJECTS if name not in audit)
    assert missing == []


def test_confidence_dark_contract_is_not_imported_by_live_product_code():
    live_roots = (ROOT / "routes", ROOT / "services")
    allowed = {
        ROOT / "services" / "mlc2_confidence.py",
        ROOT / "services" / "mlc2_confidence_producer.py",
        ROOT / "services" / "mlc2_confidence_blind.py",
        # Aggregate-only evaluator imported by the operator readiness script;
        # no product route imports it and it cannot write runtime state.
        ROOT / "services" / "mlc2_confidence_readiness.py",
        # Slice 4's only application bridge. Slice 6's atomic mode selects
        # the pre-cutover, founder-canary or fully-killed writer state.
        ROOT / "services" / "take_lifecycle.py",
        # RPC adapter only; it schedules nothing and makes no decision.
        ROOT / "services" / "db.py",
    }
    violations = []
    for root in live_roots:
        for module in root.rglob("*.py"):
            if module in allowed:
                continue
            if "mlc2_confidence" in module.read_text():
                violations.append(str(module.relative_to(ROOT)))
    assert violations == []


def test_slice4_live_bridge_is_guarded_by_the_one_hard_disabled_flag():
    lifecycle = (ROOT / "services" / "take_lifecycle.py").read_text()
    route = (ROOT / "routes" / "v2" / "explore_ideal_text.py").read_text()
    assert "configured_confidence_cutover().canonical_writes_enabled" \
        in lifecycle
    assert "promote_recording_attempt_with_confidence_outbox" in lifecycle
    assert "and confidence_prior_learning_writes_enabled()" in route
    config = (ROOT / "config.py").read_text()
    assert 'MLC2_CONFIDENCE_CUTOVER_MODE = "dark"' in config


def test_confidence_audit_maps_every_guarded_runtime_dependency():
    audit = (ROOT / "docs" / "MLC2-CONFIDENCE-DEPENDENCY-AUDIT.md").read_text()
    required = {
        "moment_suggestions", "take_feedback_exposure",
        "take_feedback_self_report", "confidence_labels",
        "confidence_self_reports", "confidence_coach_labels",
        "confidence_peer_labels", "owner_voice_album_routing",
        "voice_album", "star_verdicts", "snippet_confidence_reviews",
        "confident_voice_practice", "confidence_rereview_queue",
        "training_labels", "MLC2_CONFIDENCE_CUTOVER_MODE",
    }
    missing = sorted(token for token in required if token not in audit)
    assert missing == []


def test_confidence_cutover_is_hard_disabled_not_environment_controlled():
    config = (ROOT / "config.py").read_text()
    assert 'MLC2_CONFIDENCE_CUTOVER_MODE = "dark"' in config
    assert 'os.getenv("MLC2_CONFIDENCE_CUTOVER_MODE")' not in config
