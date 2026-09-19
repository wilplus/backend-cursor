"""A function that takes a row lock cannot be STABLE.

FOUND IN PRODUCTION 2026-09-19.  `read_feedback_v3_candidate_source_snapshot_v1`
was declared STABLE and its body ran ``SELECT ... FOR SHARE OF snapshot``.
PostgreSQL rejects that at runtime, every single call:

    ERROR 0A000: SELECT FOR SHARE is not allowed in a non-volatile function

So V3's source read could never return.  Every Take fell through
``_decline(take_id, "source_snapshot_rpc_failed", ...)``, V3 stood down, and no
Confident Voice item was ever produced -- which is why the whole bookmark
ladder was invisible on a stack that was otherwise built and merged.

It stayed hidden for two reasons worth keeping in mind:

  * an authority check one line earlier raised first, so the real fault was
    only uncovered once that check passed; and
  * the failure surfaced to the client as one typed decline reason, which
    looks identical whether the cause is policy or a broken declaration.

This is a STATIC guard because the fault is static: it is visible in the
declaration and needs no database to find.  It reads the EFFECTIVE definition
of each function -- the last one in manifest order -- so that historical
migrations, which are immutable and must never be edited, do not fail the
suite for a defect a later migration already corrected.
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "migrations"
MANIFEST = MIGRATIONS / "manifest.txt"

#: Clauses that acquire a row lock. Any one of them makes a function VOLATILE
#: whether its author said so or not.
ROW_LOCKS = ("FOR SHARE", "FOR UPDATE", "FOR NO KEY UPDATE", "FOR KEY SHARE")

#: Volatility promises that forbid a row lock.
NON_VOLATILE = ("STABLE", "IMMUTABLE")

_DEFINITION = re.compile(
    r"CREATE\s+OR\s+REPLACE\s+FUNCTION\s+"
    r"(?P<name>[a-z0-9_.]+)\s*\((?P<args>[^)]*)\)"
    r"(?P<decl>.*?)\bAS\s+(?P<tag>\$[a-z_]*\$)",
    re.IGNORECASE | re.DOTALL,
)


def _manifest_files() -> list[Path]:
    """Migration files in the order the runner applies them."""
    out: list[Path] = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        path = MIGRATIONS / parts[1].strip()
        if path.exists():
            out.append(path)
    return out


def _signature(name: str, args: str) -> str:
    return f"{name}({' '.join(args.split())})"


def _effective_definitions() -> dict[str, tuple[str, str, str]]:
    """signature -> (migration file name, declaration, body).

    A later migration replacing a function wins, exactly as PostgreSQL sees it.
    """
    latest: dict[str, tuple[str, str, str]] = {}
    for path in _manifest_files():
        sql = path.read_text(encoding="utf-8")
        for match in _DEFINITION.finditer(sql):
            tag = match.group("tag")
            rest = sql[match.end():]
            end = rest.find(tag)
            body = rest if end < 0 else rest[:end]
            latest[_signature(match.group("name"), match.group("args"))] = (
                path.name, match.group("decl"), body,
            )
    return latest


def _declared_non_volatile(declaration: str) -> str | None:
    upper = declaration.upper()
    for word in NON_VOLATILE:
        if re.search(rf"\b{word}\b", upper):
            return word
    return None


def _takes_a_row_lock(body: str) -> str | None:
    upper = body.upper()
    for clause in ROW_LOCKS:
        if re.search(rf"\b{re.escape(clause)}\b", upper):
            return clause
    return None


def test_the_scanner_finds_the_functions_at_all():
    # A regex that silently matches nothing would make every assertion below
    # vacuously true -- the failure mode this whole session kept hitting.
    definitions = _effective_definitions()
    assert len(definitions) > 50, (
        f"only {len(definitions)} function definitions parsed; the scanner is "
        "broken, not the migrations"
    )
    assert any(
        name.startswith("public.read_feedback_v3_candidate_source_snapshot_v1")
        for name in definitions
    ), "the function this test exists for was not parsed"


def test_no_effective_function_locks_rows_while_declaring_itself_stable():
    offenders = []
    for signature, (source, declaration, body) in _effective_definitions().items():
        volatility = _declared_non_volatile(declaration)
        if not volatility:
            continue
        clause = _takes_a_row_lock(body)
        if clause:
            offenders.append(f"{signature} in {source}: {volatility} + {clause}")

    assert not offenders, (
        "These functions take a row lock but promise they have no side "
        "effects. PostgreSQL raises 0A000 on every call, so they can never "
        "return:\n  " + "\n  ".join(sorted(offenders))
    )


def test_the_v3_source_snapshot_read_is_volatile():
    # The specific regression, pinned by name: it is the one the live loop
    # runs on every Take, and a silent decline there costs the entire
    # Confident Voice lane and every bookmark that depends on it.
    definitions = _effective_definitions()
    signature = next(
        key for key in definitions
        if key.startswith("public.read_feedback_v3_candidate_source_snapshot_v1")
    )
    source, declaration, body = definitions[signature]

    assert _takes_a_row_lock(body) == "FOR SHARE", (
        "the body no longer takes the row lock this test reasons about; "
        f"re-read {source} before trusting the assertion below"
    )
    assert _declared_non_volatile(declaration) is None, (
        f"{signature} is declared non-volatile in {source} while holding a row "
        "lock -- V3 will stand down on every Take with source_snapshot_rpc_failed"
    )
