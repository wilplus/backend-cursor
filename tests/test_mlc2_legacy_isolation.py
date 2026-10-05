import ast
import io
import re
import tokenize
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
        # Aggregate-only evaluator imported by the operator readiness script
        # and the research screen's Monitors panel (below); no speaker- or
        # coach-facing route imports it and it cannot write runtime state.
        ROOT / "services" / "mlc2_confidence_readiness.py",
        # ML-7 (2026-10-05): the research screen (research role and founder,
        # read-only) shows the readiness monitor's checks by running that
        # same aggregate-only evaluation over the same two aggregate RPCs the
        # five-minute cron reads. It writes nothing, starts nothing, reaches
        # no speaker, and a failed read is named, never a broken screen.
        ROOT / "services" / "research_view.py",
        # Slice 4's only application bridge. Slice 6's atomic mode selects
        # the pre-cutover, founder-canary or fully-killed writer state.
        ROOT / "services" / "take_lifecycle.py",
        # G-6 (audit 2026-09-22): the reviewed frame_factory for the dark
        # worker and the sweep that runs it. Reads snippet rows only, writes
        # only through finalize_mlc2_confidence_frame_v1, and starts nothing
        # unless the mode is founder_canary (tests/test_mlc2_confidence_frame_factory.py).
        ROOT / "services" / "mlc2_confidence_frame_factory.py",
        # Q2 (2026-09-29): the coach card's consumer of the chain. Reads the
        # writer state, writes only through the three 0393 wrappers, and is a
        # no-op unless the mode is founder_canary
        # (tests/test_confidence_chain_consumer.py).
        ROOT / "services" / "confidence_chain_consumer.py",
        # RPC adapter only; it schedules nothing and makes no decision.
        ROOT / "services" / "db.py",
        # Q1 (2026-09-29): the fail-closed HTTP doors. confidence_chain_alive
        # reads the writer state only to answer 410 while it is killed; it
        # holds no learning store and starts nothing.
        ROOT / "routes" / "phase2_guard.py",
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
    # The `changes` block moved out of the route in Phase 5 (audit Q-C1).
    block = (ROOT / "services" / "ideal_text_changes.py").read_text()
    assert "configured_confidence_cutover().canonical_writes_enabled" \
        in lifecycle
    assert "promote_recording_attempt_with_confidence_outbox" in lifecycle
    assert "and confidence_prior_learning_writes_enabled()" in block
    config = (ROOT / "config.py").read_text()
    # The flip (founder 2026-09-29): still a literal constant, never env.
    assert 'MLC2_CONFIDENCE_CUTOVER_MODE = "founder_canary"' in config


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
    # The flip (founder 2026-09-29): still a literal constant, never env.
    assert 'MLC2_CONFIDENCE_CUTOVER_MODE = "founder_canary"' in config
    assert 'os.getenv("MLC2_CONFIDENCE_CUTOVER_MODE")' not in config


# ── DA-PROHIBIT: the doors read no object the audit names (2026-10-05) ─────
#
# The guard above covers the mlc2_*.py modules only. The code that builds,
# releases, evaluates, trains on or promotes learning data lives outside
# that prefix, and the dark training-corpus copy job read confidence_labels
# (through services.professional_confidence) until 0431 gave it the chain's
# own blind judgement. Every module below is held to the same prohibition.

#: The canonical dataset, release, training, evaluation and promotion code.
CANONICAL_LEARNING_DOORS = (
    "services/pair_consent.py",          # door 1: a pair's releasability
    "services/pair_release.py",          # door 2: the weekly release
    "services/pair_release_eligibility.py",  # door 2: the release-time decision
    "services/speaker_split.py",         # doors 2 and 3: the split (F-3)
    "services/model_training.py",        # door 3: the fine-tune run
    "services/golden_set.py",            # doors 3 and 4: the sealed set
    "services/golden_evaluation.py",
    "services/model_promotion.py",       # door 4
    "services/dataset_releases.py",      # K10's release lane (dark)
    "services/confidence_dataset.py",
    "services/ml_dpo_release.py",
    "services/training_corpus.py",       # TC-4 copies (dark)
    "services/object_verification.py",   # F-8
    "scripts/promote_pair_surface.py",
    "scripts/promote_openai_model.py",
)

#: Read paths the audit's objects hide behind: the product modules that read
#: them for the product (professional verdicts are confidence_labels rows,
#: evaluation-only by the foundation's own rule).
LABEL_READER_MODULES = ("professional_confidence", "professional_verdicts")


def _audit_named_objects() -> set[str]:
    """Every object the confidence audit's storage table names."""
    audit = (ROOT / "docs" / "MLC2-CONFIDENCE-DEPENDENCY-AUDIT.md").read_text()
    section = audit.split("## Legacy storage classification and migration owners", 1)[1]
    section = section.split("\n## ", 1)[0]
    names: set[str] = set()
    for line in section.splitlines():
        if not line.startswith("| `") and not line.startswith("| old"):
            continue
        first_cell = line.split("|")[1]
        names.update(re.findall(r"`([a-z_]+)`", first_cell))
    return names


def _code_tokens(source: str) -> list[tuple[int, str]]:
    """The module's tokens without comments and docstrings: prose may name
    what the code must not read."""
    tree = ast.parse(source)
    docstring_lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                docstring_lines.update(range(body[0].lineno,
                                             (body[0].end_lineno or body[0].lineno) + 1))
    kept = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type == tokenize.COMMENT:
            continue
        if token.type == tokenize.STRING and token.start[0] in docstring_lines:
            continue
        kept.append((token.start[0], token.string))
    return kept


def _mentions(text: str, name: str) -> bool:
    """``name`` as a table, module or method part (``get_<name>_by_ids``
    counts), but never the foundation's own ``ml_<name>``."""
    return re.search(rf"(?<![A-Za-z0-9])(?<!ml_){re.escape(name)}", text) is not None


def test_the_audit_table_still_names_the_mixed_purpose_objects():
    names = _audit_named_objects()
    assert {"moment_suggestions", "confidence_labels", "take_feedback_exposure",
            "feedback_candidates", "owner_voice_album_routing", "star_verdicts",
            "training_labels", "confidence_rereview_queue"} <= names
    assert len(names) >= 25, sorted(names)


def test_every_guarded_door_exists():
    missing = [path for path in CANONICAL_LEARNING_DOORS if not (ROOT / path).exists()]
    assert missing == []


def test_canonical_learning_doors_never_read_an_object_the_audit_names():
    prohibited = (_audit_named_objects() | set(LEGACY_LEARNING_OBJECTS)
                  | set(LABEL_READER_MODULES))
    violations = []
    for path in CANONICAL_LEARNING_DOORS:
        for line, text in _code_tokens((ROOT / path).read_text()):
            for name in sorted(prohibited):
                if _mentions(text, name):
                    violations.append(f"{path}:{line}: {name}")
    assert violations == [], (
        "Canonical dataset/release/training code must not read an object the "
        "MLC-2 confidence audit names:\n" + "\n".join(violations))


def test_the_guard_catches_the_read_it_was_written_for():
    """The copy job before 0431, verbatim: the indirect read through the
    professional module, and a direct one through the database adapter."""
    before = (
        "def _copy_coach_label(database, base, snippet_id):\n"
        "    from services.professional_confidence import professional_verdicts\n"
        "    return professional_verdicts(database, [snippet_id])\n"
        "rows = database.get_confidence_labels_by_snippet_ids(ids)\n"
    )
    hits = {name for _line, text in _code_tokens(before)
            for name in ("professional_confidence", "confidence_labels")
            if _mentions(text, name)}
    assert hits == {"professional_confidence", "confidence_labels"}
    assert not _mentions("ml_candidate_sets", "candidate_sets")
    assert not _mentions("ml_evidence_spans", "evidence_spans")
    assert _mentions('table("candidate_sets")', "candidate_sets")
