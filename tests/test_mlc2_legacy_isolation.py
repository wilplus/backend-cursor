"""
GUARD      The new learning code (MLC-2) never names a legacy learning table:
           no mlc2_*.py module, and none of the door modules that build,
           release, evaluate, train on or promote learning data.
CATCHES    A read or write of a retired, unconsented label store (for example
           confidence_labels, star_verdicts) from canonical training code.
           Method names count (get_confidence_labels_by_snippet_ids), and so
           does importing services.professional_confidence. Reads source:
           the mlc2_* scan is plain text; the door scan reads code only
           (identifiers, imports and non-docstring strings), because the doors
           explain in prose what they must not read.
IF REMOVED Retired, unconsented labels can leak into training unnoticed
           (DA-PROHIBIT; the training-corpus copy read confidence_labels
           until 0430).
PROVES     test_canonical_mlc2_modules_cannot_read_or_write_legacy_learning_objects
           test_the_doors_read_no_legacy_learning_object
"""
import ast
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
# https://github.com/wilplus/backend-cursor/blob/8b5205fa519f3c8447eb8c49d1bcf6f28b8df3e6/docs/MLC2-CONFIDENCE-DEPENDENCY-AUDIT.md: pair consent, the release and its
# release-time decision, the speaker split, training, the golden set and
# evaluation, promotion, the dataset and DPO release lanes, the training-corpus
# copy, and the promotion script.
DOOR_MODULES = (
    "services/pair_consent.py",
    "services/pair_release.py",
    "services/pair_release_eligibility.py",
    "services/speaker_split.py",
    "services/model_training.py",
    "services/golden_set.py",
    "services/golden_evaluation.py",
    "services/model_promotion.py",
    "services/dataset_releases.py",
    "services/training_corpus.py",
    "scripts/promote_pair_surface.py",
)
#: The professional-verdict module reads confidence_labels for the product.
LEGACY_READERS = ("professional_confidence", "professional_verdicts")


def _code_words(source: str) -> set:
    """Identifiers, attribute names, imported modules and string constants,
    without docstrings: what the module's code can actually touch."""
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value) for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef))
        and node.body and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    words: set = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            words.add(node.id)
        elif isinstance(node, ast.Attribute):
            words.add(node.attr)
        elif isinstance(node, ast.alias):
            words.add(node.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            words.add(node.module)
        elif (isinstance(node, ast.Constant) and isinstance(node.value, str)
              and id(node) not in docstrings):
            words.add(node.value)
    return words


def test_the_doors_read_no_legacy_learning_object():
    violations = []
    for rel in DOOR_MODULES:
        words = _code_words((ROOT / rel).read_text())
        for name in sorted(LEGACY_LEARNING_OBJECTS) + list(LEGACY_READERS):
            if any(name in word for word in words):
                violations.append(f"{rel}: {name}")
    assert violations == [], (
        "The learning doors must not read legacy learning stores "
        "(DA-PROHIBIT):\n" + "\n".join(violations))
